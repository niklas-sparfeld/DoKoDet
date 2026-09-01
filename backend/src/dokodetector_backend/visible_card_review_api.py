"""HTTP boundary for recording-scoped visible-card batch preparation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from doko_operations import (
    CardEventReviewError,
    VisibleCardBatchError,
    VisibleCardBatchRequest,
    VisibleCardDetectorIdentity,
    VisibleCardReviewBatchStore,
    assess_visible_card_review_readiness,
    load_visible_card_review_batch,
    prepare_visible_card_review_batch,
    preview_visible_card_review_batch,
)
from doko_operations.holdout import load_system_holdout_registry, sealed_group_keys
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from dokodetector_backend.card_event_review_api import _load_source
from dokodetector_backend.errors import APIErrorDetail, ContractError
from dokodetector_backend.intake_contract import (
    TASK_TABLE_EVIDENCE,
    IntakeContractError,
    parse_repository_bundle,
    parse_source_record,
    parse_task_enrollment,
)

router = APIRouter()
RECORDING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
BATCH_ID_PATTERN = re.compile(r"^visible-card-batch-[0-9a-f]{24}$")
SHA256_PATTERN = r"^[0-9a-f]{64}$"
BatchStatus = Literal["preparing", "ready", "failed", "blocked"]
BatchPhase = Literal[
    "validating_inputs",
    "extracting_frames",
    "running_finder",
    "ready",
    "failed",
    "blocked",
]
ReadinessState = Literal["not_ready", "ready", "preparing", "failed", "blocked"]


class VisibleCardBatchFailureResponse(BaseModel):
    """One safe batch blocker or item failure."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    stage: str
    item_id: str | None
    retryable: bool


class VisibleCardBatchProgressResponse(BaseModel):
    """Persisted preparation counters."""

    model_config = ConfigDict(extra="forbid")

    phase: BatchPhase
    total_items: int = Field(ge=0)
    frames_extracted: int = Field(ge=0)
    finder_completed: int = Field(ge=0)
    failed_items: int = Field(ge=0)


class VisibleCardBatchItemResponse(BaseModel):
    """A compact item projection without image bytes or local paths."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    status: str
    event_time_s: float
    event_time_ms: int
    target_offset_ms: int
    frame_index: int | None
    actual_offset_ms: int | None
    finder_status: Literal["ok", "unavailable"] | None
    failure: VisibleCardBatchFailureResponse | None


class VisibleCardDetectorResponse(BaseModel):
    """The detector identity frozen into the preview."""

    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    bundle_digest: str = Field(pattern=SHA256_PATTERN)
    model: str
    provider: str
    provider_version: str
    preprocessing: str
    confidence_threshold: float = Field(ge=0, le=1)
    input_size: int = Field(gt=0)


class VisibleCardBatchResponse(BaseModel):
    """Current persisted preparation state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visible-card-review-batch/v1"]
    batch_id: str
    recording_id: str
    request_digest: str = Field(pattern=SHA256_PATTERN)
    status: BatchStatus
    created_at_utc: str
    updated_at_utc: str
    detector: VisibleCardDetectorResponse
    progress: VisibleCardBatchProgressResponse
    items: list[VisibleCardBatchItemResponse]
    failures: list[VisibleCardBatchFailureResponse]
    queue_schema_version: str
    queue_digest: str | None


class VisibleCardPreviewValidationResponse(BaseModel):
    """Preview validation and plain-language blockers."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    blockers: list[VisibleCardBatchFailureResponse]


class VisibleCardReviewPreviewResponse(BaseModel):
    """The source and detector facts frozen by a preview."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visible-card-review-preview/v1"]
    recording_id: str
    batch_id: str | None
    request_digest: str | None
    preview_digest: str = Field(pattern=SHA256_PATTERN)
    source_asset_id: str
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    source_lineage_group: str
    task_enrollment_id: str | None
    task_enrollment_selected: bool
    source_permission: str
    allowed_uses: list[str]
    card_event_review_version_id: str | None
    card_event_review_version_digest: str | None
    card_event_annotation_digest: str | None
    selected_event_count: int = Field(ge=0)
    development_partition: str | None
    detector: VisibleCardDetectorResponse | None
    validation: VisibleCardPreviewValidationResponse


class VisibleCardReviewReadinessResponse(BaseModel):
    """Current recording-scoped readiness and batch state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visible-card-review-readiness/v1"]
    recording_id: str
    state: ReadinessState
    message: str
    blocker: VisibleCardBatchFailureResponse | None
    selected_event_count: int = Field(ge=0)
    batch: VisibleCardBatchResponse | None
    preview_digest: str | None


class VisibleCardReviewCreateRequest(BaseModel):
    """The preview identity required to start immutable batch work."""

    model_config = ConfigDict(extra="forbid")

    preview_digest: str = Field(pattern=SHA256_PATTERN)
    request_digest: str = Field(pattern=SHA256_PATTERN)


@dataclass(frozen=True, slots=True)
class _VisibleCardRecordingContext:
    recording_id: str
    source_asset_id: str
    source_sha256: str
    source_lineage_group: str
    source_permission: str
    allowed_uses: tuple[str, ...]
    task_enrollment_id: str | None
    task_enrollment_selected: bool
    video_path: Path
    review: dict[str, Any]
    request: VisibleCardBatchRequest | None
    detector: VisibleCardDetectorIdentity | None
    detector_provider: str | None
    detector_available: bool
    protected_source_lineage_groups: tuple[str, ...]
    development_partition: str | None

    @property
    def reviewed_card_event_count(self) -> int:
        return _reviewed_card_event_count(self.review)


@router.get(
    "/v1/recordings/{recording_id}/visible-card-review",
    response_model=VisibleCardReviewReadinessResponse,
)
def get_visible_card_review_readiness(
    recording_id: str, request: Request
) -> VisibleCardReviewReadinessResponse:
    """Return readiness and the current preparation state for one recording."""

    context = _recording_context(request, recording_id)
    preview = _preview(context)
    batch = _find_recording_batch(request, recording_id, context.request)
    if batch is not None:
        batch_response = _batch_response(batch)
        state, message = _batch_readiness(batch_response)
        blocker = _first_failure(batch_response.failures)
        return VisibleCardReviewReadinessResponse(
            schema_version="visible-card-review-readiness/v1",
            recording_id=recording_id,
            state=state,
            message=message,
            blocker=blocker,
            selected_event_count=context.reviewed_card_event_count,
            batch=batch_response,
            preview_digest=preview["preview_digest"],
        )

    blockers = preview["validation"]["blockers"]
    valid = preview["validation"]["valid"]
    first_blocker = blockers[0] if blockers else None
    return VisibleCardReviewReadinessResponse(
        schema_version="visible-card-review-readiness/v1",
        recording_id=recording_id,
        state="ready" if valid else "not_ready",
        message=(
            f"Ready — {context.reviewed_card_event_count} reviewed card-played event"
            f"{'s' if context.reviewed_card_event_count != 1 else ''}."
            if valid
            else first_blocker["message"]
        ),
        blocker=_failure_response(first_blocker) if first_blocker is not None else None,
        selected_event_count=context.reviewed_card_event_count,
        batch=None,
        preview_digest=preview["preview_digest"],
    )


@router.post(
    "/v1/recordings/{recording_id}/visible-card-review/preview",
    response_model=VisibleCardReviewPreviewResponse,
)
def preview_visible_card_review(
    recording_id: str, request: Request
) -> VisibleCardReviewPreviewResponse:
    """Preview the exact source, review, enrollment, and detector inputs."""

    context = _recording_context(request, recording_id)
    return VisibleCardReviewPreviewResponse.model_validate(_preview(context))


@router.post(
    "/v1/recordings/{recording_id}/visible-card-review/batches",
    response_model=VisibleCardBatchResponse,
    status_code=202,
)
async def create_visible_card_review_batch(
    recording_id: str,
    payload: VisibleCardReviewCreateRequest,
    request: Request,
) -> VisibleCardBatchResponse:
    """Persist and asynchronously start one preview-bound batch."""

    context = _recording_context(request, recording_id)
    preview = _preview(context)
    if not preview["validation"]["valid"] or context.request is None:
        raise ContractError(
            "visible_card_review_not_ready",
            "The visible-card review batch cannot start until its blockers are resolved.",
            details=[
                APIErrorDetail(field=blocker["code"], message=blocker["message"])
                for blocker in preview["validation"]["blockers"]
            ],
        )
    if payload.preview_digest != preview["preview_digest"] or payload.request_digest != preview[
        "request_digest"
    ]:
        raise ContractError(
            "visible_card_review_preview_stale",
            "The visible-card review preview changed. Create a new preview before starting.",
            status_code=409,
        )

    store = VisibleCardReviewBatchStore(request.app.state.settings.operations_root)
    try:
        state = store.initialize(context.request)
    except (VisibleCardBatchError, OSError) as error:
        raise ContractError(
            "visible_card_review_batch_invalid",
            "The visible-card review batch could not be initialized.",
        ) from error
    if state["status"] == "preparing":
        _schedule(request, context.request, resume=False)
    return _batch_response(state)


@router.get(
    "/v1/visible-card-reviews/{batch_id}",
    response_model=VisibleCardBatchResponse,
)
def get_visible_card_review_batch(batch_id: str, request: Request) -> VisibleCardBatchResponse:
    """Return persisted preparation progress for one batch."""

    state = _read_batch(request, batch_id)
    return _batch_response(state)


@router.post(
    "/v1/visible-card-reviews/{batch_id}/retry",
    response_model=VisibleCardBatchResponse,
    status_code=202,
)
async def retry_visible_card_review_batch(
    batch_id: str, request: Request
) -> VisibleCardBatchResponse:
    """Retry only failed items with the batch's frozen request and detector."""

    state = _read_batch(request, batch_id)
    if state["status"] != "failed":
        raise ContractError(
            "visible_card_review_retry_unavailable",
            "Only a failed visible-card batch can be retried.",
        )
    if not any(failure["retryable"] for failure in state["failures"]):
        raise ContractError(
            "visible_card_review_retry_unavailable",
            "This batch has no failed item that can be retried.",
        )
    try:
        frozen_request = VisibleCardBatchRequest.from_mapping(state["frozen_inputs"])
    except VisibleCardBatchError as error:
        raise ContractError(
            "visible_card_review_batch_invalid",
            "The frozen visible-card review inputs are invalid.",
        ) from error
    if request.app.state.visible_card_provider is None:
        raise ContractError(
            "visible_card_provider_unavailable",
            "The local visible-card finder is not available.",
        )
    tasks: dict[str, asyncio.Task[Any]] = request.app.state.visible_card_batch_tasks
    active = tasks.get(batch_id)
    if active is not None and not active.done():
        with suppress(Exception):
            await active
    store = VisibleCardReviewBatchStore(request.app.state.settings.operations_root)
    try:
        state = store.begin_retry(batch_id)
    except (VisibleCardBatchError, OSError) as error:
        raise ContractError(
            "visible_card_review_batch_invalid",
            "The visible-card batch could not be prepared for retry.",
        ) from error
    _schedule(request, frozen_request, resume=True)
    return _batch_response(state)


def _recording_context(request: Request, recording_id: str) -> _VisibleCardRecordingContext:
    if RECORDING_ID_PATTERN.fullmatch(recording_id) is None:
        raise ContractError("invalid_recording_id", "The recording ID is invalid.")
    source = _load_source(request, recording_id, require_selected=False)
    bundle_path = request.app.state.repository_bundle_storage.bundle_path(recording_id)
    try:
        descriptor = parse_repository_bundle((bundle_path / "manifest.json").read_bytes())
        source_record = parse_source_record((bundle_path / "source-record.json").read_bytes())
        enrollment_document = parse_task_enrollment(
            (bundle_path / "initial-task-enrollment.json").read_bytes()
        )
    except (IntakeContractError, OSError, ValueError) as error:
        raise ContractError(
            "recording_metadata_invalid",
            "The stored recording metadata is invalid.",
            status_code=500,
        ) from error
    table_task = next(
        (item for item in enrollment_document.enrollments if item.task == TASK_TABLE_EVIDENCE),
        None,
    )
    review = _review(request, source)
    detector, detector_provider, detector_available = _detector(request)
    protected = _protected_groups(request)
    context = _VisibleCardRecordingContext(
        recording_id=recording_id,
        source_asset_id=source.source_asset_id,
        source_sha256=source.source_sha256,
        source_lineage_group=source.source_asset_id,
        source_permission=source_record.source_permission,
        allowed_uses=tuple(source_record.allowed_uses),
        task_enrollment_id=None if table_task is None else table_task.task_enrollment_id,
        task_enrollment_selected=table_task is not None and table_task.disposition == "selected",
        video_path=bundle_path / descriptor.files.video.relative_path,
        review=review,
        request=None,
        detector=detector,
        detector_provider=detector_provider,
        detector_available=detector_available,
        protected_source_lineage_groups=protected,
        development_partition=_development_partition(request, recording_id),
    )
    batch_request = _batch_request(request, context)
    return replace(context, request=batch_request)


def _batch_request(
    request: Request, context: _VisibleCardRecordingContext
) -> VisibleCardBatchRequest | None:
    review = context.review
    if (
        context.detector is None
        or review.get("review_state") != "completed"
        or not review.get("completed_version_id")
        or not review.get("completed_version_digest")
        or not review.get("reviewed_annotation_digest")
    ):
        return None
    version_id = review["completed_version_id"]
    version_path = (
        request.app.state.settings.operations_root
        / "cardevent-reviews"
        / context.recording_id
        / "versions"
        / f"{version_id}.json"
    )
    return VisibleCardBatchRequest(
        recording_id=context.recording_id,
        source_asset_id=context.source_asset_id,
        source_sha256=context.source_sha256,
        source_lineage_group=context.source_lineage_group,
        video_path=context.video_path,
        card_event_review_version_path=version_path,
        card_event_review_version_id=version_id,
        card_event_review_version_digest=review["completed_version_digest"],
        card_event_annotation_digest=review["reviewed_annotation_digest"],
        detector=context.detector,
        request_version="visible-card-request/v2",
        task_enrollment_id=context.task_enrollment_id or "table-evidence-enrollment",
        task_enrollment_selected=context.task_enrollment_selected,
        source_permission=context.source_permission,
        allowed_uses=context.allowed_uses,
        protected_source_lineage_groups=context.protected_source_lineage_groups,
    )


def _review(request: Request, source: Any) -> dict[str, Any]:
    try:
        return request.app.state.card_event_review_store.read(source)
    except CardEventReviewError as error:
        raise ContractError(
            "card_event_review_invalid",
            "The stored CardEvent review is invalid.",
            status_code=500,
        ) from error


def _detector(
    request: Request,
) -> tuple[VisibleCardDetectorIdentity | None, str | None, bool]:
    provider = request.app.state.visible_card_provider
    configured_mode = request.app.state.settings.visible_card_provider
    underlying = getattr(provider, "provider", provider)
    provider_name = getattr(underlying, "name", None)
    if configured_mode != "local":
        return None, configured_mode, False
    if provider is None or provider_name != "local":
        return None, provider_name, False
    explicit = getattr(request.app.state, "visible_card_detector", None)
    if explicit is not None:
        return explicit, provider_name, True
    bundle = getattr(underlying, "bundle", None)
    manifest = getattr(bundle, "manifest", None)
    identity = getattr(underlying, "bundle_identity", None)
    if not isinstance(manifest, dict) or not isinstance(identity, dict):
        return None, provider_name, False
    bundle_digest = identity.get("bundle_digest")
    run_id = identity.get("run_id")
    if not isinstance(bundle_digest, str) or not isinstance(run_id, str):
        return None, provider_name, False
    recipe = manifest.get("recipe")
    preprocessing = recipe.get("preprocessing") if isinstance(recipe, dict) else None
    if not isinstance(preprocessing, str):
        preprocessing = "rfdetr_standard_704_v1"
    root = getattr(bundle, "root", None)
    return (
        VisibleCardDetectorIdentity(
            bundle_id=run_id,
            bundle_digest=bundle_digest,
            bundle_path=None if root is None else str(root),
            model=str(manifest.get("model_variant", "RFDETRLarge")),
            preprocessing=preprocessing,
            confidence_threshold=float(getattr(underlying, "confidence_threshold", 0.5)),
            provider=provider_name,
            provider_version=str(getattr(underlying, "version", "local-visible-cards-v1")),
            input_size=int(getattr(underlying, "input_size", 704)),
        ),
        provider_name,
        True,
    )


def _protected_groups(request: Request) -> tuple[str, ...]:
    registry = load_system_holdout_registry(
        request.app.state.settings.operations_root / "system-holdout-registry.json"
    )
    return tuple(
        sorted(value for name, value in sealed_group_keys(registry) if name == "source_lineage")
    )


def _development_partition(request: Request, recording_id: str) -> str | None:
    try:
        from dokodetector_backend.card_event_development_split_api import (
            load_card_event_development_recordings,
        )

        facts = load_card_event_development_recordings(request)
        split = request.app.state.card_event_development_split_store.read(facts)
        for partition in ("train", "validation", "test", "unassigned"):
            if recording_id in split[partition]:
                return partition
    except (CardEventReviewError, ContractError, RuntimeError, ValueError):
        return None
    return None


def _reviewed_card_event_count(review: dict[str, Any]) -> int:
    annotation = review.get("annotation")
    events = annotation.get("events") if isinstance(annotation, dict) else None
    if not isinstance(events, list):
        return 0
    return sum(
        isinstance(event, dict)
        and event.get("type") == "card_played"
        and event.get("confidence") in {None, "confirmed"}
        for event in events
    )


def _preview(context: _VisibleCardRecordingContext) -> dict[str, Any]:
    count = _reviewed_card_event_count(context.review)
    review_completed = context.review.get("review_state") == "completed"
    if context.request is not None:
        return preview_visible_card_review_batch(
            context.request,
            reviewed_card_event_count=count,
            development_partition=context.development_partition,
            detector_available=context.detector_available,
        )
    blockers = assess_visible_card_review_readiness(
        task_enrollment_selected=context.task_enrollment_selected,
        source_permission=context.source_permission,
        allowed_uses=context.allowed_uses,
        source_lineage_group=context.source_lineage_group,
        protected_source_lineage_groups=context.protected_source_lineage_groups,
        review_completed=review_completed,
        reviewed_card_event_count=count,
        detector_provider=context.detector_provider
        if context.detector_provider is not None
        else "local",
        detector_available=context.detector_available,
    )
    core = {
        "schema_version": "visible-card-review-preview/v1",
        "recording_id": context.recording_id,
        "source_asset_id": context.source_asset_id,
        "source_sha256": context.source_sha256,
        "review_state": context.review.get("review_state"),
        "selected_event_count": count,
        "detector": None
        if context.detector is None
        else context.detector.to_mapping_without_path(),
    }
    return {
        "schema_version": "visible-card-review-preview/v1",
        "recording_id": context.recording_id,
        "batch_id": None,
        "request_digest": None,
        "preview_digest": _digest(core),
        "source_asset_id": context.source_asset_id,
        "source_sha256": context.source_sha256,
        "source_lineage_group": context.source_lineage_group,
        "task_enrollment_id": context.task_enrollment_id,
        "task_enrollment_selected": context.task_enrollment_selected,
        "source_permission": context.source_permission,
        "allowed_uses": list(context.allowed_uses),
        "card_event_review_version_id": context.review.get("completed_version_id"),
        "card_event_review_version_digest": context.review.get("completed_version_digest"),
        "card_event_annotation_digest": context.review.get("reviewed_annotation_digest"),
        "selected_event_count": count,
        "development_partition": context.development_partition,
        "detector": None
        if context.detector is None
        else context.detector.to_mapping_without_path(),
        "validation": {
            "valid": not blockers,
            "blockers": [blocker.to_mapping() for blocker in blockers],
        },
    }


def _find_recording_batch(
    request: Request,
    recording_id: str,
    current_request: VisibleCardBatchRequest | None,
) -> dict[str, Any] | None:
    store = VisibleCardReviewBatchStore(request.app.state.settings.operations_root)
    if current_request is not None:
        path = store.batch_path(current_request.batch_id)
        if path.is_file():
            return load_visible_card_review_batch(path)
    root = store.workspace_root / "visible-card-review-batches"
    if not root.is_dir():
        return None
    candidates: list[dict[str, Any]] = []
    for path in root.glob("visible-card-batch-*/batch.json"):
        try:
            state = load_visible_card_review_batch(path)
        except (VisibleCardBatchError, OSError, ValueError):
            continue
        frozen = state["frozen_inputs"]
        if frozen.get("recording_id") == recording_id:
            candidates.append(state)
    return max(candidates, key=lambda item: item["updated_at_utc"], default=None)


def _read_batch(request: Request, batch_id: str) -> dict[str, Any]:
    if BATCH_ID_PATTERN.fullmatch(batch_id) is None:
        raise ContractError(
            "invalid_visible_card_batch_id", "The visible-card batch ID is invalid."
        )
    path = VisibleCardReviewBatchStore(
        request.app.state.settings.operations_root
    ).batch_path(batch_id)
    if not path.is_file():
        raise ContractError(
            "visible_card_review_batch_not_found",
            "The visible-card batch was not found.",
            status_code=404,
        )
    try:
        return load_visible_card_review_batch(path)
    except (VisibleCardBatchError, OSError) as error:
        raise ContractError(
            "visible_card_review_batch_invalid",
            "The stored visible-card batch is invalid.",
            status_code=500,
        ) from error


def _schedule(request: Request, batch_request: VisibleCardBatchRequest, *, resume: bool) -> None:
    tasks: dict[str, asyncio.Task[Any]] = request.app.state.visible_card_batch_tasks
    existing = tasks.get(batch_request.batch_id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(
        asyncio.to_thread(
            prepare_visible_card_review_batch,
            request.app.state.settings.operations_root,
            batch_request,
            request.app.state.visible_card_provider,
            frame_extractor=request.app.state.visible_card_frame_extractor,
            resume=resume,
        )
    )
    tasks[batch_request.batch_id] = task

    def forget(completed: asyncio.Task[Any]) -> None:
        if tasks.get(batch_request.batch_id) is completed:
            tasks.pop(batch_request.batch_id, None)

    task.add_done_callback(forget)


def _batch_response(state: dict[str, Any]) -> VisibleCardBatchResponse:
    frozen = VisibleCardBatchRequest.from_mapping(state["frozen_inputs"])
    items: list[VisibleCardBatchItemResponse] = []
    for item in state["items"]:
        event = item["event"]
        frame = item.get("frame")
        finder = item.get("finder")
        failure = item.get("failure")
        items.append(
            VisibleCardBatchItemResponse(
                item_id=item["item_id"],
                status=item["status"],
                event_time_s=event["event_time_s"],
                event_time_ms=event["event_time_ms"],
                target_offset_ms=event["target_offset_ms"],
                frame_index=None if frame is None else frame["frame_index"],
                actual_offset_ms=None if frame is None else frame["actual_offset_ms"],
                finder_status=None if finder is None else finder["result"]["status"],
                failure=(
                    None
                    if failure is None
                    else VisibleCardBatchFailureResponse.model_validate(failure)
                ),
            )
        )
    return VisibleCardBatchResponse(
        schema_version=state["schema_version"],
        batch_id=state["batch_id"],
        recording_id=frozen.recording_id,
        request_digest=state["request_digest"],
        status=state["status"],
        created_at_utc=state["created_at_utc"],
        updated_at_utc=state["updated_at_utc"],
        detector=VisibleCardDetectorResponse.model_validate(
            frozen.detector.to_mapping_without_path()
        ),
        progress=VisibleCardBatchProgressResponse.model_validate(state["progress"]),
        items=items,
        failures=[
            VisibleCardBatchFailureResponse.model_validate(failure)
            for failure in state["failures"]
        ],
        queue_schema_version=state["queue_schema_version"],
        queue_digest=state["queue_digest"],
    )


def _batch_readiness(batch: VisibleCardBatchResponse) -> tuple[ReadinessState, str]:
    if batch.status == "preparing":
        return "preparing", _progress_message(batch)
    if batch.status == "ready":
        return (
            "ready",
            f"Ready to review — {batch.progress.finder_completed} of "
            f"{batch.progress.total_items} complete.",
        )
    if batch.status == "failed":
        return "failed", "Batch failed — retry unavailable items."
    return "blocked", batch.failures[0].message if batch.failures else "Batch is blocked."


def _progress_message(batch: VisibleCardBatchResponse) -> str:
    progress = batch.progress
    if progress.phase == "running_finder":
        return f"Running finder — {progress.finder_completed} of {progress.total_items}."
    return f"Preparing frames — {progress.frames_extracted} of {progress.total_items}."


def _first_failure(
    failures: list[VisibleCardBatchFailureResponse],
) -> VisibleCardBatchFailureResponse | None:
    return failures[0] if failures else None


def _failure_response(value: dict[str, Any]) -> VisibleCardBatchFailureResponse:
    return VisibleCardBatchFailureResponse.model_validate(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "VisibleCardBatchResponse",
    "VisibleCardReviewPreviewResponse",
    "VisibleCardReviewReadinessResponse",
    "router",
]
