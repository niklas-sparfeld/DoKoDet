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
from urllib.parse import quote

from doko_operations import (
    CardEventReviewError,
    VisibleCardBatchConflict,
    VisibleCardBatchError,
    VisibleCardBatchRequest,
    VisibleCardDetectorIdentity,
    VisibleCardRedetectError,
    VisibleCardReviewBatchStore,
    assess_visible_card_review_readiness,
    load_visible_card_review_batch,
    prepare_visible_card_review_batch,
    preview_visible_card_review_batch,
    summarize_visible_card_review_queue,
)
from doko_operations.holdout import load_system_holdout_registry, sealed_group_keys
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from table_evidence_analyzer.visible_card_review_workflow import (
    VisibleCardReviewConflict,
    VisibleCardReviewWorkflowError,
    load_visible_card_review_queue,
    update_frame_review,
    validate_completed_visible_card_review_queue,
)
from table_evidence_analyzer.visible_cards import normalize_prediction

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
BatchStatus = Literal["preparing", "ready", "failed", "blocked", "completed"]
BatchPhase = Literal[
    "validating_inputs",
    "extracting_frames",
    "running_finder",
    "ready",
    "failed",
    "blocked",
    "completed",
]
ReadinessState = Literal["not_ready", "ready", "preparing", "failed", "blocked", "completed"]


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
    """One review item with source, finder, and current review state."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    status: str
    event_id: str
    event_index: int
    event_time_s: float
    event_time_ms: int
    target_offset_ms: int
    frame_index: int | None
    actual_offset_ms: int | None
    finder_status: Literal["ok", "unavailable"] | None
    failure: VisibleCardBatchFailureResponse | None
    source: "VisibleCardSourceLineageResponse | None"
    finder: "VisibleCardFinderResponse | None"
    last_detector: "VisibleCardDetectorResponse | None"
    review: "VisibleCardFrameReviewResponse | None"


class VisibleCardPointResponse(BaseModel):
    """One normalized overlay point."""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0, le=1000)
    y: int = Field(ge=0, le=1000)


class VisibleCardBoxResponse(BaseModel):
    """One normalized overlay box."""

    model_config = ConfigDict(extra="forbid")

    y_min: int = Field(ge=0, le=1000)
    x_min: int = Field(ge=0, le=1000)
    y_max: int = Field(ge=0, le=1000)
    x_max: int = Field(ge=0, le=1000)


class VisibleCardSourceLineageResponse(BaseModel):
    """Immutable frame lineage and its safe image URL."""

    model_config = ConfigDict(extra="forbid")

    package_id: str
    frame_part_name: str
    target_offset_ms: int
    image_url: str
    frame_sha256: str = Field(pattern=SHA256_PATTERN)
    source_asset_id: str
    source_lineage_group: str
    source_asset_sha256: str | None
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class VisibleCardProposalResponse(BaseModel):
    """One finder proposal in normalized coordinates."""

    model_config = ConfigDict(extra="forbid")

    proposal_index: int = Field(ge=0)
    box_2d: VisibleCardBoxResponse
    polygon: list[VisibleCardPointResponse]
    side: Literal["face_up", "face_down", "unknown"]
    label: str


class VisibleCardFinderResponse(BaseModel):
    """Immutable finder request, prediction, and failure diagnostics projection."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    provider_version: str
    request_digest: str = Field(pattern=SHA256_PATTERN)
    result_digest: str = Field(pattern=SHA256_PATTERN)
    prediction_sha256: str = Field(pattern=SHA256_PATTERN)
    proposals: list[VisibleCardProposalResponse]
    proposals_recovered: bool
    raw_response: dict[str, Any] | None


class VisibleCardIdentityUsabilityResponse(BaseModel):
    """Identity usability for one reviewed visible card."""

    model_config = ConfigDict(extra="forbid")

    usable: bool
    reason: str


class VisibleCardReviewedRegionResponse(BaseModel):
    """Reviewed geometry, derived box, and card metadata."""

    model_config = ConfigDict(extra="forbid")

    card_id: str
    visible_region: dict[str, list[list[VisibleCardPointResponse]]]
    derived_box: VisibleCardBoxResponse
    identity_usability: VisibleCardIdentityUsabilityResponse
    side: Literal["face_up", "face_down", "unknown"]
    failure_tags: list[str]


class VisibleCardReviewActionResponse(BaseModel):
    """One persisted review action."""

    model_config = ConfigDict(extra="forbid")

    card_id: str
    action: Literal["accepted", "reshaped", "added", "removed"]
    proposal_index: int | None
    reviewed_card: VisibleCardReviewedRegionResponse | None


class VisibleCardFrameReviewResponse(BaseModel):
    """Current review state for one source frame."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["unreviewed", "in_progress", "reviewed"]
    decision: Literal["GOOD", "BAD"] | None
    empty_frame: bool | None
    failure_tags: list[str]
    actions: list[VisibleCardReviewActionResponse]
    reviewer: str | None
    review_id: str | None
    started_at_utc: str | None
    updated_at_utc: str | None
    completed_at_utc: str | None


class VisibleCardFrameReviewUpdateRequest(BaseModel):
    """The reviewer-owned portion of one complete frame update."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["in_progress", "reviewed"]
    decision: Literal["GOOD", "BAD"]
    empty_frame: bool
    failure_tags: list[str]
    actions: list[VisibleCardReviewActionResponse]
    reviewer: str


class VisibleCardReviewItemUpdateRequest(BaseModel):
    """One revision-guarded frame review replacement."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    review: VisibleCardFrameReviewUpdateRequest


class VisibleCardReviewItemRedetectRequest(BaseModel):
    """The detector selection and revision guard for one frame re-detection."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    model: str | None = Field(
        default=None,
        min_length=1,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


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
    revision: int
    summary: VisibleCardBatchSummaryResponse
    review_state: Literal["draft", "completed"]
    reviewer: str | None
    completed_at_utc: str | None
    completed_version_id: str | None
    completed_version_digest: str | None
    completion_receipt_id: str | None
    completion_receipt_digest: str | None
    parent_version_id: str | None
    parent_digest: str | None
    downstream_readiness: VisibleCardDownstreamReadinessResponse


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


class VisibleCardReviewCompletionRequest(BaseModel):
    """The explicit operator confirmation for publishing a reviewed batch."""

    model_config = ConfigDict(extra="forbid")

    reviewer: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)


class VisibleCardReviewRevisionRequest(BaseModel):
    """The immutable published review to copy into a new draft."""

    model_config = ConfigDict(extra="forbid")

    parent_version_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)


class VisibleCardBatchSummaryResponse(BaseModel):
    """Counts shown before a batch is published."""

    model_config = ConfigDict(extra="forbid")

    total_frames: int = Field(ge=0)
    reviewed_frames: int = Field(ge=0)
    pending_frames: int = Field(ge=0)
    failed_frames: int = Field(ge=0)
    usable_frames: int = Field(ge=0)
    empty_frames: int = Field(ge=0)
    unusable_frames: int = Field(ge=0)
    retained_cards: int = Field(ge=0)
    accepted_proposals: int = Field(ge=0)
    corrected_proposals: int = Field(ge=0)
    removed_proposals: int = Field(ge=0)
    added_cards: int = Field(ge=0)
    identity_unusable_cards: int = Field(ge=0)


class VisibleCardDownstreamReadinessResponse(BaseModel):
    """Readiness of the published v2 queue for the existing freeze boundary."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["not_ready", "ready"]
    message: str
    queue_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)


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
        batch_response = _batch_response(request, batch)
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
    if (
        payload.preview_digest != preview["preview_digest"]
        or payload.request_digest != preview["request_digest"]
    ):
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
    return _batch_response(request, state)


@router.get(
    "/v1/visible-card-reviews/{batch_id}",
    response_model=VisibleCardBatchResponse,
)
def get_visible_card_review_batch(batch_id: str, request: Request) -> VisibleCardBatchResponse:
    """Return persisted preparation progress and review data for one batch."""

    state = _read_batch(request, batch_id)
    return _batch_response(request, state)


@router.get(
    "/v1/visible-card-reviews/{batch_id}/items/{item_id}/image",
    response_class=FileResponse,
)
def get_visible_card_review_item_image(
    batch_id: str, item_id: str, request: Request
) -> FileResponse:
    """Return one immutable extracted source frame after batch ownership checks."""

    state = _read_batch(request, batch_id)
    item = next((item for item in state["items"] if item["item_id"] == item_id), None)
    if item is None:
        raise ContractError(
            "visible_card_review_item_not_found",
            "The visible-card review item was not found.",
            status_code=404,
        )
    frame = item.get("frame")
    if not isinstance(frame, dict) or not isinstance(frame.get("path"), str):
        raise ContractError(
            "visible_card_review_item_image_unavailable",
            "This visible-card review item has no extracted source frame yet.",
            status_code=404,
        )
    store = VisibleCardReviewBatchStore(request.app.state.settings.operations_root)
    batch_root = store.batch_path(batch_id).parent.resolve()
    frame_path = Path(frame["path"]).resolve()
    try:
        frame_path.relative_to(batch_root)
    except ValueError as error:
        raise ContractError(
            "visible_card_review_batch_invalid",
            "The stored visible-card frame is outside its batch.",
            status_code=500,
        ) from error
    if not frame_path.is_file():
        raise ContractError(
            "visible_card_review_item_image_unavailable",
            "The extracted source frame is no longer available.",
            status_code=404,
        )
    try:
        actual_digest = hashlib.sha256(frame_path.read_bytes()).hexdigest()
    except OSError as error:
        raise ContractError(
            "visible_card_review_item_image_unavailable",
            "The extracted source frame could not be read.",
            status_code=404,
        ) from error
    if actual_digest != frame.get("sha256"):
        raise ContractError(
            "visible_card_review_batch_invalid",
            "The extracted source frame does not match its frozen digest.",
            status_code=500,
        )
    return FileResponse(
        frame_path,
        media_type=frame.get("content_type", "image/jpeg"),
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/v1/visible-card-reviews/{batch_id}/items/{item_id}/redetect",
    response_model=VisibleCardBatchResponse,
)
def redetect_visible_card_review_item(
    batch_id: str,
    item_id: str,
    payload: VisibleCardReviewItemRedetectRequest,
    request: Request,
) -> VisibleCardBatchResponse:
    """Re-run one source frame and retain only its latest successful finder result."""

    state = _read_batch(request, batch_id)
    if not any(item.get("item_id") == item_id for item in state["items"]):
        raise ContractError(
            "visible_card_review_item_not_found",
            "The visible-card review item was not found.",
            status_code=404,
        )
    detector = _redetect_detector(request, state, item_id, payload.model)
    try:
        updated = VisibleCardReviewBatchStore(
            request.app.state.settings.operations_root
        ).redetect(
            batch_id,
            item_id,
            request.app.state.visible_card_provider,
            detector=detector,
            expected_revision=payload.expected_revision,
        )
    except VisibleCardBatchConflict as error:
        raise ContractError(
            "visible_card_review_conflict",
            "This review changed in another window. Reload the current revision before "
            "re-detecting.",
            status_code=409,
        ) from error
    except VisibleCardRedetectError as error:
        raise ContractError(
            "visible_card_redetect_failed",
            str(error),
            status_code=503,
        ) from error
    return _batch_response(request, updated)


@router.put(
    "/v1/visible-card-reviews/{batch_id}/items/{item_id}",
    response_model=VisibleCardBatchResponse,
)
def update_visible_card_review_item(
    batch_id: str,
    item_id: str,
    payload: VisibleCardReviewItemUpdateRequest,
    request: Request,
) -> VisibleCardBatchResponse:
    """Persist one complete frame review with an optimistic revision guard."""

    state = _read_batch(request, batch_id)
    if state["status"] != "ready" or not isinstance(state.get("queue_path"), str):
        raise ContractError(
            "visible_card_review_update_unavailable",
            "Review updates are available after the batch is ready.",
        )
    try:
        update_frame_review(
            state["queue_path"],
            item_id,
            payload.review.model_dump(mode="json"),
            expected_revision=payload.expected_revision,
        )
    except VisibleCardReviewConflict as error:
        raise ContractError(
            "visible_card_review_conflict",
            "This review changed in another window. Reload the current revision before saving.",
            status_code=409,
        ) from error
    except VisibleCardReviewWorkflowError as error:
        raise ContractError(
            "visible_card_review_invalid",
            "The visible-card review could not be saved.",
        ) from error
    return _batch_response(request, _read_batch(request, batch_id))


@router.post(
    "/v1/visible-card-reviews/{batch_id}/complete",
    response_model=VisibleCardBatchResponse,
)
def complete_visible_card_review(
    batch_id: str,
    payload: VisibleCardReviewCompletionRequest,
    request: Request,
) -> VisibleCardBatchResponse:
    """Publish one fully reviewed batch as an immutable v2 queue artifact."""

    _read_batch(request, batch_id)
    try:
        state = VisibleCardReviewBatchStore(request.app.state.settings.operations_root).complete(
            batch_id,
            reviewer=payload.reviewer,
            expected_revision=payload.expected_revision,
        )
    except VisibleCardBatchConflict as error:
        raise ContractError(
            "visible_card_review_conflict",
            str(error),
            status_code=409,
        ) from error
    except (VisibleCardBatchError, OSError) as error:
        raise ContractError(
            "visible_card_review_completion_invalid",
            str(error),
        ) from error
    return _batch_response(request, state)


@router.post(
    "/v1/visible-card-reviews/{batch_id}/revisions",
    response_model=VisibleCardBatchResponse,
)
def start_visible_card_review_revision(
    batch_id: str,
    payload: VisibleCardReviewRevisionRequest,
    request: Request,
) -> VisibleCardBatchResponse:
    """Start a new draft from one immutable completed visible-card review."""

    _read_batch(request, batch_id)
    try:
        state = VisibleCardReviewBatchStore(
            request.app.state.settings.operations_root
        ).start_revision(
            batch_id,
            parent_version_id=payload.parent_version_id,
            expected_revision=payload.expected_revision,
        )
    except VisibleCardBatchConflict as error:
        raise ContractError(
            "visible_card_review_conflict",
            str(error),
            status_code=409,
        ) from error
    except (VisibleCardBatchError, OSError) as error:
        raise ContractError(
            "visible_card_review_revision_invalid",
            str(error),
        ) from error
    return _batch_response(request, state)


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
            "The configured visible-card finder is not available.",
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
    return _batch_response(request, state)


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
    version_path = request.app.state.card_event_review_store.completed_version_path(
        context.recording_id, version_id
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
    if configured_mode not in {"local", "gemini"}:
        return None, configured_mode, False
    if provider is None or provider_name != configured_mode:
        return None, provider_name, False
    explicit = getattr(request.app.state, "visible_card_detector", None)
    if explicit is not None:
        if explicit.provider != configured_mode:
            return None, provider_name, False
        return explicit, provider_name, True
    if configured_mode == "gemini":
        model = request.app.state.settings.gemini_model
        provider_version = str(getattr(underlying, "version", "gemini-visible-cards-v1"))
        identity_core = {
            "provider": provider_name,
            "provider_version": provider_version,
            "model": model,
            "preprocessing": "gemini-native-image-v1",
        }
        identity_digest = hashlib.sha256(
            json.dumps(identity_core, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return (
            VisibleCardDetectorIdentity(
                bundle_id=f"{provider_name}-{model}",
                bundle_digest=identity_digest,
                model=model,
                preprocessing="gemini-native-image-v1",
                confidence_threshold=0.0,
                input_size=1,
                provider=provider_name,
                provider_version=provider_version,
            ),
            provider_name,
            True,
        )
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


def _redetect_detector(
    request: Request,
    state: dict[str, Any],
    item_id: str,
    requested_model: str | None,
) -> VisibleCardDetectorIdentity:
    """Resolve a safe detector identity for one item-level run."""

    configured, provider_name, available = _detector(request)
    if configured is None or not available:
        raise ContractError(
            "visible_card_provider_unavailable",
            "The configured visible-card finder is not available.",
        )
    item = next(item for item in state["items"] if item.get("item_id") == item_id)
    previous = item.get("last_detector") or state["frozen_inputs"].get("detector")
    if not isinstance(previous, dict):
        previous = configured.to_mapping()
    try:
        previous_detector = VisibleCardDetectorIdentity.from_mapping(previous)
    except VisibleCardBatchError:
        previous_detector = configured
    model = requested_model or (
        previous_detector.model
        if previous_detector.provider == provider_name
        else configured.model
    )
    if provider_name == "local":
        if model != configured.model:
            raise ContractError(
                "visible_card_detector_unavailable",
                "The configured local detector does not support a different model.",
                status_code=422,
            )
        return configured
    identity_core = {
        "provider": configured.provider,
        "provider_version": configured.provider_version,
        "model": model,
        "preprocessing": configured.preprocessing,
    }
    identity_digest = hashlib.sha256(
        json.dumps(identity_core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return replace(
        configured,
        bundle_id=f"{configured.provider}-{model}",
        bundle_digest=identity_digest,
        model=model,
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
    path = VisibleCardReviewBatchStore(request.app.state.settings.operations_root).batch_path(
        batch_id
    )
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


def _batch_response(request: Request, state: dict[str, Any]) -> VisibleCardBatchResponse:
    frozen = VisibleCardBatchRequest.from_mapping(state["frozen_inputs"])
    queue_items: dict[str, Any] = {}
    queue = None
    queue_path = state.get("queue_path")
    if isinstance(queue_path, str):
        try:
            queue = load_visible_card_review_queue(queue_path)
        except (OSError, ValueError, VisibleCardReviewWorkflowError) as error:
            raise ContractError(
                "visible_card_review_batch_invalid",
                "The stored visible-card review queue is invalid.",
                status_code=500,
            ) from error
        queue_items = {item.item_id: item for item in queue.items}

    items: list[VisibleCardBatchItemResponse] = []
    for item in state["items"]:
        event = item["event"]
        frame = item.get("frame")
        finder = item.get("finder")
        failure = item.get("failure")
        queue_item = queue_items.get(item["item_id"])
        source = _source_response(
            state["batch_id"],
            item["item_id"],
            frame,
            None if queue_item is None else queue_item.source.to_mapping(),
            frozen,
        )
        finder_response = _finder_response(
            finder,
            None if queue_item is None else queue_item.teacher.prediction,
        )
        last_detector = item.get("last_detector")
        if not isinstance(last_detector, dict) and isinstance(finder, dict):
            last_detector = finder.get("detector")
        review_response = (
            None
            if queue_item is None
            else VisibleCardFrameReviewResponse.model_validate(queue_item.review.to_mapping())
        )
        items.append(
            VisibleCardBatchItemResponse(
                item_id=item["item_id"],
                status=item["status"],
                event_id=event["event_id"],
                event_index=event["event_index"],
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
                source=source,
                finder=finder_response,
                last_detector=_detector_response(last_detector),
                review=review_response,
            )
        )
    queue_revision = 0 if queue is None else queue.revision
    queue_digest = state["queue_digest"]
    if isinstance(queue_path, str):
        try:
            queue_digest = hashlib.sha256(Path(queue_path).read_bytes()).hexdigest()
        except OSError as error:
            raise ContractError(
                "visible_card_review_batch_invalid",
                "The stored visible-card review queue is invalid.",
                status_code=500,
            ) from error
    summary = (
        summarize_visible_card_review_queue(queue)
        if queue is not None
        else _summary_for_preparation_state(state)
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
            VisibleCardBatchFailureResponse.model_validate(failure) for failure in state["failures"]
        ],
        queue_schema_version=state["queue_schema_version"],
        queue_digest=queue_digest,
        revision=queue_revision,
        summary=VisibleCardBatchSummaryResponse.model_validate(summary),
        review_state=state["lifecycle_state"],
        reviewer=state["reviewer"],
        completed_at_utc=state["completed_at_utc"],
        completed_version_id=state["completed_version_id"],
        completed_version_digest=state["completed_version_digest"],
        completion_receipt_id=state["completion_receipt_id"],
        completion_receipt_digest=state["completion_receipt_digest"],
        parent_version_id=state["parent_version_id"],
        parent_digest=state["parent_digest"],
        downstream_readiness=_downstream_readiness(state),
    )


def _summary_for_preparation_state(state: dict[str, Any]) -> dict[str, int]:
    items = state["items"]
    failed = sum(item.get("failure") is not None for item in items)
    return {
        "total_frames": len(items),
        "reviewed_frames": 0,
        "pending_frames": len(items) - failed,
        "failed_frames": failed,
        "usable_frames": 0,
        "empty_frames": 0,
        "unusable_frames": 0,
        "retained_cards": 0,
        "accepted_proposals": 0,
        "corrected_proposals": 0,
        "removed_proposals": 0,
        "added_cards": 0,
        "identity_unusable_cards": 0,
    }


def _downstream_readiness(state: dict[str, Any]) -> VisibleCardDownstreamReadinessResponse:
    if state["status"] != "completed" or not isinstance(state.get("completed_queue_path"), str):
        return VisibleCardDownstreamReadinessResponse(
            state="not_ready",
            message="Complete and publish the visible-card review before freeze use.",
            queue_digest=None,
        )
    path = Path(state["completed_queue_path"])
    try:
        queue = validate_completed_visible_card_review_queue(load_visible_card_review_queue(path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError, VisibleCardReviewWorkflowError) as error:
        return VisibleCardDownstreamReadinessResponse(
            state="not_ready",
            message=f"The published review is not ready for freeze use: {error}",
            queue_digest=None,
        )
    if digest != state["completed_version_digest"] or queue.run_id != state["batch_id"]:
        return VisibleCardDownstreamReadinessResponse(
            state="not_ready",
            message="The published review lineage is stale and cannot enter freeze use.",
            queue_digest=None,
        )
    return VisibleCardDownstreamReadinessResponse(
        state="ready",
        message="Published v2 queue passed the existing visible-card freeze boundary.",
        queue_digest=digest,
    )


def _source_response(
    batch_id: str,
    item_id: str,
    frame: dict[str, Any] | None,
    queued_source: dict[str, Any] | None,
    request: VisibleCardBatchRequest,
) -> VisibleCardSourceLineageResponse | None:
    source = queued_source
    if source is None and frame is not None:
        source = {
            "package_id": item_id.rsplit(":", 1)[0],
            "frame_part_name": item_id.rsplit(":", 1)[1],
            "target_offset_ms": request.target_offset_ms,
            "image": frame["path"],
            "frame_sha256": frame["sha256"],
            "source_asset_id": request.source_asset_id,
            "source_lineage_group": request.source_lineage_group,
            "source_asset_sha256": request.source_sha256,
            "width": frame["width"],
            "height": frame["height"],
        }
    if source is None or not source.get("source_asset_id"):
        return None
    return VisibleCardSourceLineageResponse(
        package_id=source["package_id"],
        frame_part_name=source["frame_part_name"],
        target_offset_ms=source["target_offset_ms"],
        image_url=(
            f"/v1/visible-card-reviews/{quote(batch_id, safe='')}/items/"
            f"{quote(item_id, safe='')}/image"
        ),
        frame_sha256=source["frame_sha256"],
        source_asset_id=source["source_asset_id"],
        source_lineage_group=source["source_lineage_group"],
        source_asset_sha256=source.get("source_asset_sha256"),
        width=source["width"],
        height=source["height"],
    )


def _finder_response(
    finder: dict[str, Any] | None,
    queued_prediction: dict[str, Any] | None,
) -> VisibleCardFinderResponse | None:
    if finder is None:
        return None
    result = finder.get("result")
    prediction = queued_prediction
    proposals_recovered = False
    raw_response = None
    if isinstance(result, dict):
        if prediction is None:
            prediction = result.get("prediction")
        if result.get("status") == "unavailable":
            candidate_response = result.get("raw_response")
            raw_response = candidate_response if isinstance(candidate_response, dict) else None
            if _prediction_is_empty(prediction):
                recovered = _recover_prediction_for_display(raw_response)
                if recovered is not None:
                    prediction = recovered
                    proposals_recovered = True
    cards = prediction.get("cards") if isinstance(prediction, dict) else []
    if not isinstance(cards, list):
        cards = []
    proposals = [
        VisibleCardProposalResponse(proposal_index=index, **card)
        for index, card in enumerate(cards)
        if isinstance(card, dict)
    ]
    provider = finder.get("provider")
    return VisibleCardFinderResponse(
        provider=(provider or {}).get("name", "local"),
        provider_version=(provider or {}).get("version", "unknown"),
        request_digest=finder["request_digest"],
        result_digest=finder["result_digest"],
        prediction_sha256=finder["prediction_sha256"],
        proposals=proposals,
        proposals_recovered=proposals_recovered,
        raw_response=raw_response,
    )


def _prediction_is_empty(prediction: Any) -> bool:
    return (
        not isinstance(prediction, dict)
        or not isinstance(prediction.get("cards"), list)
        or len(prediction["cards"]) == 0
    )


def _recover_prediction_for_display(raw_response: dict[str, Any] | None) -> dict[str, Any] | None:
    """Recover safe display geometry from a malformed Gemini response without approving it."""

    if raw_response is None:
        return None
    candidates = raw_response.get("candidates")
    if not isinstance(candidates, list):
        return None
    for candidate in candidates[:1]:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            continue
        for part in parts:
            text = part.get("text") if isinstance(part, dict) else None
            if not isinstance(text, str):
                continue
            try:
                value = json.loads(text)
                return normalize_prediction(value, repair_tight_boxes=True).to_mapping()
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
    return None


def _detector_response(value: Any) -> VisibleCardDetectorResponse | None:
    if not isinstance(value, dict):
        return None
    fields = {
        "bundle_id",
        "bundle_digest",
        "model",
        "provider",
        "provider_version",
        "preprocessing",
        "confidence_threshold",
        "input_size",
    }
    if not fields.issubset(value):
        return None
    return VisibleCardDetectorResponse.model_validate(
        {field: value[field] for field in fields}
    )


def _batch_readiness(batch: VisibleCardBatchResponse) -> tuple[ReadinessState, str]:
    if batch.status == "completed":
        return "completed", "Review complete — published immutable review is ready for freeze use."
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
    "VisibleCardBatchSummaryResponse",
    "VisibleCardDownstreamReadinessResponse",
    "VisibleCardReviewCompletionRequest",
    "VisibleCardReviewPreviewResponse",
    "VisibleCardReviewReadinessResponse",
    "VisibleCardReviewRevisionRequest",
    "router",
]
