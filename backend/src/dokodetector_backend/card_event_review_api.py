"""Recording-scoped CardEvent review workspace routes."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Literal

from doko_operations import (
    CardEventProposal,
    CardEventReviewConflict,
    CardEventReviewError,
    CardEventReviewNotFound,
    CardEventReviewSource,
    CardEventReviewStore,
    CardEventReviewWriteError,
    proposal_id,
)
from fastapi import APIRouter, Request
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from dokodetector_backend.errors import ContractError
from dokodetector_backend.intake_contract import (
    TASK_CARD_EVENT,
    IntakeContractError,
    ProposalGeneratorRun,
    parse_repository_bundle,
    validate_repository_bundle,
)
from dokodetector_backend.repository_bundle_repository import RepositoryBundleRepository
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.video_probe import (
    VideoProbeError,
    VideoProbeUnavailable,
    probe_video_path,
)

router = APIRouter()
RECORDING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
PROPOSAL_DECISIONS = Literal["undecided", "accepted", "dismissed"]
REVIEW_STATES = Literal["not_started", "draft", "completed"]


class CardEventProposalDecisionRequest(BaseModel):
    """The client-controlled decision for one immutable proposal."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1)
    decision: PROPOSAL_DECISIONS


class CardEventReviewDraftUpdateRequest(BaseModel):
    """A complete next draft and the revision it replaces."""

    model_config = ConfigDict(extra="forbid")

    annotation: dict[str, Any]
    proposals: list[CardEventProposalDecisionRequest] | dict[str, PROPOSAL_DECISIONS] = Field(
        default_factory=list,
        validation_alias=AliasChoices("proposals", "proposal_decisions")
    )
    expected_revision: int = Field(ge=0)
    full_video_acknowledged: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "full_video_acknowledged", "acknowledge_full_video"
        ),
    )


class CardEventReviewCompletionRequest(BaseModel):
    """The explicit full-recording completion acknowledgement."""

    model_config = ConfigDict(extra="forbid")

    reviewer: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    full_video_acknowledged: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "full_video_acknowledged", "acknowledge_full_video"
        ),
    )


class CardEventReviewRevisionRequest(BaseModel):
    """The immutable reviewed version to copy into a new draft."""

    model_config = ConfigDict(extra="forbid")

    parent_version_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("parent_version_id", "version_id"),
    )
    expected_revision: int = Field(ge=0)


class CardEventProposalResponse(BaseModel):
    """One immutable proposal with its separate human decision."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    proposal_generator_run_id: str
    time_s: float
    probability: float
    model_bundle_id: str
    execution_platform: str
    decision: PROPOSAL_DECISIONS


class CardEventReviewResponse(BaseModel):
    """The current source-linked CardEvent review state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["cardevent-review/v1"]
    recording_id: str
    source_asset_id: str
    source_sha256: str
    video: str
    annotation: dict[str, Any]
    draft_revision: int
    draft_digest: str
    review_state: REVIEW_STATES
    full_video_acknowledged: bool
    reviewer: str | None
    completed_at: str | None
    completed_version_id: str | None
    completed_version_digest: str | None
    parent_version_id: str | None
    parent_digest: str | None
    reviewed_annotation_digest: str | None
    proposal_decision_digest: str | None
    completion_receipt_id: str | None
    proposals: list[CardEventProposalResponse]


@router.get(
    "/v1/recordings/{recording_id}/card-event-review",
    response_model=CardEventReviewResponse,
)
def get_card_event_review(recording_id: str, request: Request) -> CardEventReviewResponse:
    """Return the current draft and immutable proposals for one recording."""

    source = _load_source(request, recording_id)
    try:
        state = _review_store(request).read(source)
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventReviewResponse.model_validate(state)


@router.put(
    "/v1/recordings/{recording_id}/card-event-review/draft",
    response_model=CardEventReviewResponse,
)
def update_card_event_review_draft(
    recording_id: str,
    payload: CardEventReviewDraftUpdateRequest,
    request: Request,
) -> CardEventReviewResponse:
    """Validate and save one complete CardEvent review draft."""

    source = _load_source(request, recording_id)
    try:
        state = _review_store(request).update_draft(
            source,
            annotation=payload.annotation,
            proposals=_proposal_decisions(payload.proposals),
            expected_revision=payload.expected_revision,
            full_video_acknowledged=payload.full_video_acknowledged,
        )
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventReviewResponse.model_validate(state)


@router.post(
    "/v1/recordings/{recording_id}/card-event-review/complete",
    response_model=CardEventReviewResponse,
)
def complete_card_event_review(
    recording_id: str,
    payload: CardEventReviewCompletionRequest,
    request: Request,
) -> CardEventReviewResponse:
    """Publish the current complete draft as an immutable reviewed version."""

    source = _load_source(request, recording_id)
    try:
        state = _review_store(request).complete(
            source,
            reviewer=payload.reviewer,
            expected_revision=payload.expected_revision,
            full_video_acknowledged=payload.full_video_acknowledged,
        )
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventReviewResponse.model_validate(state)


@router.post(
    "/v1/recordings/{recording_id}/card-event-review/revisions",
    response_model=CardEventReviewResponse,
)
def start_card_event_review_revision(
    recording_id: str,
    payload: CardEventReviewRevisionRequest,
    request: Request,
) -> CardEventReviewResponse:
    """Start a new draft from one immutable reviewed version."""

    source = _load_source(request, recording_id)
    try:
        state = _review_store(request).start_revision(
            source,
            parent_version_id=payload.parent_version_id,
            expected_revision=payload.expected_revision,
        )
    except CardEventReviewError as error:
        raise _review_error(error) from error
    return CardEventReviewResponse.model_validate(state)


def _review_store(request: Request) -> CardEventReviewStore:
    return request.app.state.card_event_review_store


def _load_source(
    request: Request, recording_id: str, *, require_selected: bool = True
) -> CardEventReviewSource:
    if RECORDING_ID_PATTERN.fullmatch(recording_id) is None:
        raise ContractError("invalid_recording_id", "The recording ID is invalid.")
    repository: RepositoryBundleRepository = request.app.state.repository_bundle_repository
    storage: RepositoryBundleStorage = request.app.state.repository_bundle_storage
    if repository.get(recording_id) is None:
        raise ContractError(
            "recording_not_found",
            "The recording was not found.",
            status_code=404,
        )
    bundle_path = storage.bundle_path(recording_id)
    try:
        manifest = (bundle_path / "manifest.json").read_bytes()
        source_record = (bundle_path / "source-record.json").read_bytes()
        task_enrollment = (bundle_path / "initial-task-enrollment.json").read_bytes()
        bundle_descriptor = parse_repository_bundle(manifest)
        proposal_bytes = {
            descriptor.proposal_generator_run_id: (
                bundle_path / descriptor.relative_path
            ).read_bytes()
            for descriptor in bundle_descriptor.files.proposal_generator_runs
        }
        bundle, source, enrollments, runs = validate_repository_bundle(
            manifest,
            source_record,
            task_enrollment,
            proposal_bytes,
        )
        _verify_bundle_members(bundle_path, bundle_descriptor)
    except (IntakeContractError, OSError, ValueError) as error:
        raise ContractError(
            "recording_metadata_invalid",
            "The stored recording metadata is invalid.",
            status_code=500,
        ) from error

    card_event_task = next(
        (item for item in enrollments.enrollments if item.task == TASK_CARD_EVENT),
        None,
    )
    if require_selected and (card_event_task is None or card_event_task.disposition != "selected"):
        raise ContractError(
            "card_event_review_unavailable",
            "The CardEvent task is not selected for this recording.",
            status_code=422,
        )

    video_name = Path(bundle.files.video.relative_path).name
    duration_s = _video_duration(bundle_path / bundle.files.video.relative_path)
    proposals = tuple(_proposals(source.source_asset_id, runs))
    return CardEventReviewSource(
        recording_id=bundle.recording_id,
        source_asset_id=source.source_asset_id,
        source_sha256=source.sha256,
        video=video_name,
        proposals=proposals,
        duration_s=duration_s,
    )


def _proposals(
    source_asset_id: str,
    runs: tuple[ProposalGeneratorRun, ...],
) -> list[CardEventProposal]:
    result: list[CardEventProposal] = []
    for run in sorted(runs, key=lambda item: item.proposal_generator_run_id):
        for index, event in enumerate(run.event_proposals):
            result.append(
                CardEventProposal(
                    proposal_id=proposal_id(
                        source_asset_id,
                        run.proposal_generator_run_id,
                        index,
                        event.time_s,
                    ),
                    proposal_generator_run_id=run.proposal_generator_run_id,
                    time_s=event.time_s,
                    probability=event.probability,
                    model_bundle_id=run.model_bundle_id,
                    execution_platform=run.execution_environment.platform,
                )
            )
    return result


def _proposal_decisions(
    value: list[CardEventProposalDecisionRequest] | dict[str, PROPOSAL_DECISIONS],
) -> list[dict[str, str]]:
    if isinstance(value, dict):
        return [
            {"proposal_id": proposal_id_value, "decision": decision}
            for proposal_id_value, decision in value.items()
        ]
    return [item.model_dump() for item in value]


def _verify_bundle_members(bundle_path: Path, descriptor: Any) -> None:
    members = (
        descriptor.files.video,
        descriptor.files.source_record,
        descriptor.files.task_enrollment,
        *descriptor.files.proposal_generator_runs,
    )
    for member in members:
        path = bundle_path / member.relative_path
        value = path.read_bytes()
        if len(value) != member.byte_length or hashlib.sha256(value).hexdigest() != member.sha256:
            raise IntakeContractError(f"Bundle file does not match {member.relative_path}.")


def _video_duration(path: Path) -> float | None:
    try:
        return probe_video_path(path).duration_ms / 1000.0
    except (OSError, VideoProbeError, VideoProbeUnavailable):
        return None


def _review_error(error: CardEventReviewError) -> ContractError:
    if isinstance(error, CardEventReviewConflict):
        return ContractError("card_event_review_conflict", str(error), status_code=409)
    if isinstance(error, CardEventReviewNotFound):
        return ContractError("card_event_review_version_not_found", str(error), status_code=404)
    if isinstance(error, CardEventReviewWriteError):
        return ContractError("internal_error", str(error), status_code=500)
    return ContractError("card_event_review_invalid", str(error), status_code=422)


__all__ = [
    "CardEventReviewCompletionRequest",
    "CardEventReviewDraftUpdateRequest",
    "CardEventReviewResponse",
    "CardEventReviewRevisionRequest",
    "router",
]
