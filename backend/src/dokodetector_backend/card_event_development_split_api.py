"""HTTP routes for bounded CardEventNet development partition assignment."""

from __future__ import annotations

import re
from typing import Literal

from doko_operations import (
    GROUP_KEY_NAMES,
    CardEventDevelopmentRecording,
    CardEventDevelopmentSplitConflict,
    CardEventDevelopmentSplitError,
    CardEventDevelopmentSplitStore,
    CardEventDevelopmentSplitValidationError,
)
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from dokodetector_backend.card_event_review_api import _load_source
from dokodetector_backend.errors import ContractError
from dokodetector_backend.intake_contract import (
    parse_source_record,
    parse_task_enrollment,
)
from dokodetector_backend.repository_bundle_repository import RepositoryBundleRepository
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage

router = APIRouter()
RECORDING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
DevelopmentPartition = Literal["train", "validation", "unassigned"]


class CardEventDevelopmentSplitPreviewRequest(BaseModel):
    """Request one group-safe development partition preview."""

    model_config = ConfigDict(extra="forbid")

    recording_id: str = Field(min_length=1)
    destination: DevelopmentPartition
    expected_active_split_digest: str = Field(min_length=64, max_length=64)


class CardEventDevelopmentSplitApplyRequest(CardEventDevelopmentSplitPreviewRequest):
    """Apply one previously reviewed development partition preview."""

    preview_digest: str = Field(min_length=64, max_length=64)
    operator: str = Field(min_length=1)


class DevelopmentGroupKeyResponse(BaseModel):
    """One leakage-group key shown to the operator."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: str


class DevelopmentAffectedRecordingResponse(BaseModel):
    """One recording changed together with the complete connected group."""

    model_config = ConfigDict(extra="forbid")

    recording_id: str
    source_asset_id: str
    source_sha256: str
    current_partition: str
    group_keys: list[list[str]]


class DevelopmentSplitValidationResponse(BaseModel):
    """Human-readable assignment validation results."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    blockers: list[str]


class CardEventDevelopmentSplitPreviewResponse(BaseModel):
    """Preview of one group-safe partition change."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["cardevent-development-split-preview/v1"]
    task: Literal["cardevent_event_detection"]
    recording_id: str
    destination: DevelopmentPartition
    active_split_version_id: str
    active_split_digest: str
    affected_recordings: list[DevelopmentAffectedRecordingResponse]
    affected_group_keys: list[list[str]]
    validation: DevelopmentSplitValidationResponse
    current_counts: dict[str, int]
    proposed_counts: dict[str, int]
    preview_digest: str


class CardEventDevelopmentSplitApplyResponse(BaseModel):
    """Published result of one immutable development partition change."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["cardevent-development-split-apply/v1"]
    task: Literal["cardevent_event_detection"]
    recording_id: str
    destination: DevelopmentPartition
    affected_recordings: list[DevelopmentAffectedRecordingResponse]
    split_version_id: str
    split_version_digest: str
    receipt_id: str
    receipt_digest: str
    partitions: dict[str, list[str]]
    counts: dict[str, int]


@router.post(
    "/v1/data/cardevent-development-split/preview",
    response_model=CardEventDevelopmentSplitPreviewResponse,
)
def preview_card_event_development_split(
    payload: CardEventDevelopmentSplitPreviewRequest,
    request: Request,
) -> CardEventDevelopmentSplitPreviewResponse:
    """Preview the complete connected group affected by one assignment."""

    _validate_recording_id(payload.recording_id)
    try:
        result = _split_store(request).preview(
            load_card_event_development_recordings(request),
            recording_id=payload.recording_id,
            destination=payload.destination,
            expected_active_split_digest=payload.expected_active_split_digest,
        )
    except CardEventDevelopmentSplitConflict as error:
        raise ContractError("development_split_conflict", str(error), status_code=409) from error
    except CardEventDevelopmentSplitValidationError as error:
        raise ContractError("development_split_invalid", str(error), status_code=422) from error
    except CardEventDevelopmentSplitError as error:
        raise ContractError(
            "development_split_unavailable",
            "The active development split could not be read.",
            status_code=500,
        ) from error
    return CardEventDevelopmentSplitPreviewResponse.model_validate(result)


@router.post(
    "/v1/data/cardevent-development-split/apply",
    response_model=CardEventDevelopmentSplitApplyResponse,
)
def apply_card_event_development_split(
    payload: CardEventDevelopmentSplitApplyRequest,
    request: Request,
) -> CardEventDevelopmentSplitApplyResponse:
    """Revalidate and publish one immutable development partition change."""

    _validate_recording_id(payload.recording_id)
    try:
        result = _split_store(request).apply(
            load_card_event_development_recordings(request),
            recording_id=payload.recording_id,
            destination=payload.destination,
            expected_active_split_digest=payload.expected_active_split_digest,
            preview_digest=payload.preview_digest,
            operator=payload.operator,
        )
    except CardEventDevelopmentSplitConflict as error:
        raise ContractError("development_split_conflict", str(error), status_code=409) from error
    except CardEventDevelopmentSplitValidationError as error:
        raise ContractError("development_split_blocked", str(error), status_code=422) from error
    except CardEventDevelopmentSplitError as error:
        raise ContractError(
            "development_split_unavailable",
            "The development split could not be published.",
            status_code=500,
        ) from error
    return CardEventDevelopmentSplitApplyResponse.model_validate(result)


def _split_store(request: Request) -> CardEventDevelopmentSplitStore:
    return request.app.state.card_event_development_split_store


def load_card_event_development_recordings(
    request: Request,
) -> tuple[CardEventDevelopmentRecording, ...]:
    """Project accepted repository bundles into read-only split-operation facts."""

    repository: RepositoryBundleRepository = request.app.state.repository_bundle_repository
    storage: RepositoryBundleStorage = request.app.state.repository_bundle_storage
    review_store = request.app.state.card_event_review_store
    result: list[CardEventDevelopmentRecording] = []
    for indexed in repository.list():
        bundle_path = storage.bundle_path(indexed.recording_id)
        try:
            source = parse_source_record((bundle_path / "source-record.json").read_bytes())
            enrollments = parse_task_enrollment(
                (bundle_path / "initial-task-enrollment.json").read_bytes()
            )
        except (OSError, TypeError, ValueError) as error:
            raise ContractError(
                "recording_metadata_invalid",
                "The stored recording metadata is invalid.",
                status_code=500,
            ) from error

        effective_state = _effective_source_state(request, source.model_dump())
        card_event_selected = any(
            enrollment.task == "cardevent_event_detection"
            and enrollment.disposition == "selected"
            for enrollment in enrollments.enrollments
        )
        review_state = "not_started"
        review_event_count = 0
        try:
            review_source = _load_source(request, indexed.recording_id, require_selected=False)
            review = review_store.read(review_source)
            review_state = review["review_state"]
            review_event_count = len(review["annotation"]["events"])
        except (RuntimeError, ValueError):
            # An unavailable review workspace is still a clear, safe review blocker.
            pass
        group_keys = [("source_lineage", source.source_asset_id)]
        for name in GROUP_KEY_NAMES:
            if name == "source_lineage":
                continue
            field = "table_setup" if name == "table_setup" else name
            value = getattr(source, field, None)
            if isinstance(value, str) and value:
                group_keys.append((name, value))
        result.append(
            CardEventDevelopmentRecording(
                recording_id=source.recording_id or indexed.recording_id,
                source_asset_id=source.source_asset_id,
                source_sha256=source.sha256,
                source_permission=str(effective_state.get("source_permission") or "unknown"),
                allowed_uses=tuple(effective_state.get("allowed_uses", [])),
                retention_state=str(effective_state.get("retention_state") or "unknown"),
                task_selected=card_event_selected,
                review_state=review_state,
                group_keys=tuple(group_keys),
                review_event_count=review_event_count,
            )
        )
    return tuple(result)


def _effective_source_state(request: Request, source: dict[str, object]) -> dict[str, object]:
    from doko_operations import load_current_source_state

    try:
        state = load_current_source_state(
            request.app.state.settings.operations_root,
            str(source["source_asset_id"]),
            source_record=source,
        )
    except ValueError as error:
        raise ContractError(
            "recording_metadata_invalid",
            "The source lifecycle state is invalid.",
            status_code=500,
        ) from error
    if state.get("source_sha256") not in {None, source.get("sha256")}:
        raise ContractError(
            "recording_metadata_invalid",
            "The source lifecycle state does not match the recording.",
            status_code=500,
        )
    return state


def _validate_recording_id(recording_id: str) -> None:
    if RECORDING_ID_PATTERN.fullmatch(recording_id) is None:
        raise ContractError("invalid_recording_id", "The recording ID is invalid.")


__all__ = [
    "CardEventDevelopmentSplitApplyRequest",
    "CardEventDevelopmentSplitApplyResponse",
    "CardEventDevelopmentSplitPreviewRequest",
    "CardEventDevelopmentSplitPreviewResponse",
    "DevelopmentAffectedRecordingResponse",
    "DevelopmentGroupKeyResponse",
    "DevelopmentSplitValidationResponse",
    "load_card_event_development_recordings",
    "router",
]
