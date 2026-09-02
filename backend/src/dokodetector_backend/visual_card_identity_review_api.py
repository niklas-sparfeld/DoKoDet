"""HTTP boundary for visual-card identity review batch preparation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from doko_operations import (
    VisualCardIdentityBatchConflict,
    VisualCardIdentityBatchError,
    VisualCardIdentityBatchRequest,
    VisualCardIdentityBatchStore,
    VisualCardIdentityClassifierIdentity,
    assess_visual_card_identity_review_readiness,
    load_visual_card_identity_review_batch,
    prepare_visual_card_identity_review_batch,
    preview_visual_card_identity_review_batch,
)
from doko_operations.holdout import load_system_holdout_registry, sealed_group_keys
from doko_operations.visible_card_review_batch import (
    VisibleCardBatchError,
    VisibleCardReviewBatchStore,
    load_visible_card_review_batch,
)
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from dokodetector_backend.card_event_review_api import _load_source
from dokodetector_backend.errors import APIErrorDetail, ContractError

router = APIRouter()
RECORDING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
BATCH_ID_PATTERN = re.compile(r"^visual-card-identity-batch-[0-9a-f]{24}$")
SHA256_PATTERN = r"^[0-9a-f]{64}$"
BatchStatus = Literal["preparing", "ready", "failed", "blocked"]
BatchPhase = Literal[
    "validating_inputs",
    "materializing_crops",
    "running_proposals",
    "ready",
    "failed",
    "blocked",
]
ReadinessState = Literal["not_ready", "ready", "preparing", "failed", "blocked"]


class IdentityBatchFailureResponse(BaseModel):
    """One safe identity batch blocker or item failure."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    stage: str
    item_id: str | None
    retryable: bool


class IdentityClassifierResponse(BaseModel):
    """The configured proposal generator identity."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    calibration: str
    bundle_identity: dict[str, Any] | None


class IdentityCropPolicyResponse(BaseModel):
    """The selected policy from the frozen visible-card crop policy."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str
    policy_digest: str = Field(pattern=SHA256_PATTERN)
    policy: dict[str, Any]


class IdentityBatchProgressResponse(BaseModel):
    """Persisted crop and proposal preparation counters."""

    model_config = ConfigDict(extra="forbid")

    phase: BatchPhase
    total_items: int = Field(ge=0)
    crops_materialized: int = Field(ge=0)
    proposals_completed: int = Field(ge=0)
    failed_items: int = Field(ge=0)


class IdentityCandidateResponse(BaseModel):
    """One canonical visual card identity candidate."""

    model_config = ConfigDict(extra="forbid")

    card: str
    probability: float = Field(gt=0, le=1)


class IdentityProposalResponse(BaseModel):
    """A classifier proposal kept separate from human identity decisions."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visual-card-identity-proposal/v1"]
    item_id: str
    crop_sha256: str = Field(pattern=SHA256_PATTERN)
    classifier: IdentityClassifierResponse
    status: Literal["ok", "unavailable"]
    candidates: list[IdentityCandidateResponse]
    score: float | None
    result: dict[str, Any]
    result_digest: str = Field(pattern=SHA256_PATTERN)


class IdentitySourceResponse(BaseModel):
    """Source frame lineage for one identity crop."""

    model_config = ConfigDict(extra="forbid")

    visible_card_review_batch_id: str
    visible_card_review_item_id: str
    package_id: str
    frame_part_name: str
    image_url: str
    frame_sha256: str = Field(pattern=SHA256_PATTERN)
    source_asset_id: str
    source_lineage_group: str
    source_asset_sha256: str = Field(pattern=SHA256_PATTERN)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class IdentityCropResponse(BaseModel):
    """Frozen crop metadata and its local image URL."""

    model_config = ConfigDict(extra="forbid")

    image_url: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    byte_length: int = Field(gt=0)
    content_type: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    policy_id: str
    policy_digest: str = Field(pattern=SHA256_PATTERN)


class IdentityDecisionResponse(BaseModel):
    """One explicit human identity decision."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visual-card-identity-decision/v1"]
    status: Literal["pending", "accepted", "corrected", "identity_unusable", "source_problem"]
    identity: str | None
    reason: str | None
    failure_tags: list[str]
    reviewer: str | None
    updated_at_utc: str | None


class IdentityReviewSummaryResponse(BaseModel):
    """Counts used to show identity review completion state."""

    model_config = ConfigDict(extra="forbid")

    total_items: int = Field(ge=0)
    pending_items: int = Field(ge=0)
    decided_items: int = Field(ge=0)
    accepted_items: int = Field(ge=0)
    corrected_items: int = Field(ge=0)
    identity_unusable_items: int = Field(ge=0)
    source_problem_items: int = Field(ge=0)
    failed_items: int = Field(ge=0)


class IdentityDecisionUpdateRequest(BaseModel):
    """One revision-guarded human identity decision."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    action: Literal[
        "accept_proposal",
        "select_identity",
        "mark_identity_unusable",
        "report_source_problem",
    ]
    identity: str | None = None
    reason: str | None = None
    failure_tags: list[str] = Field(default_factory=list)
    reviewer: str = Field(min_length=1)


class IdentityReviewCompletionRequest(BaseModel):
    """The explicit operator confirmation for completing an identity review."""

    model_config = ConfigDict(extra="forbid")

    reviewer: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)


class IdentityReviewItemResponse(BaseModel):
    """One reviewable crop with source and proposal lineage."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visual-card-identity-review-item/v1"]
    item_id: str
    visible_card_review_item_id: str
    source: IdentitySourceResponse
    visible_card: dict[str, Any]
    visible_card_digest: str = Field(pattern=SHA256_PATTERN)
    crop: IdentityCropResponse | None
    proposal: IdentityProposalResponse | None
    decision: IdentityDecisionResponse
    status: Literal["ready", "failed"]
    failure: IdentityBatchFailureResponse | None


class IdentityCoverageResponse(BaseModel):
    """Coverage of usable and excluded reviewed visible cards."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visual-card-identity-review-coverage/v1"]
    visible_card_review_item_count: int = Field(ge=0)
    reviewed_visible_card_count: int = Field(ge=0)
    identity_usable_card_count: int = Field(ge=0)
    excluded_card_count: int = Field(ge=0)
    excluded_cards: list[dict[str, Any]]
    coverage_digest: str = Field(pattern=SHA256_PATTERN)


class IdentityReviewBatchResponse(BaseModel):
    """Current persisted identity batch state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visual-card-identity-review-batch/v1"]
    batch_id: str
    recording_id: str
    request_digest: str = Field(pattern=SHA256_PATTERN)
    status: BatchStatus
    created_at_utc: str
    updated_at_utc: str
    classifier: IdentityClassifierResponse
    crop_policy: IdentityCropPolicyResponse
    progress: IdentityBatchProgressResponse
    revision: int
    review_state: Literal["draft", "completed"]
    reviewer: str | None
    completed_at_utc: str | None
    summary: IdentityReviewSummaryResponse
    items: list[IdentityReviewItemResponse]
    coverage: IdentityCoverageResponse
    failures: list[IdentityBatchFailureResponse]


class IdentityReviewPreviewValidationResponse(BaseModel):
    """Preview validation and explicit blockers."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    blockers: list[IdentityBatchFailureResponse]


class IdentityReviewPreviewResponse(BaseModel):
    """Frozen visible-card, crop, and classifier facts."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visual-card-identity-review-preview/v1"]
    recording_id: str
    batch_id: str | None
    request_digest: str | None
    preview_digest: str = Field(pattern=SHA256_PATTERN)
    visible_card_review_batch_id: str | None
    visible_card_review_version_id: str | None
    visible_card_review_version_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    visible_card_review_queue_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    source_asset_id: str
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    source_lineage_group: str
    classifier: IdentityClassifierResponse | None
    crop_policy: IdentityCropPolicyResponse
    selected_card_count: int = Field(ge=0)
    coverage: IdentityCoverageResponse | None
    validation: IdentityReviewPreviewValidationResponse


class IdentityReviewReadinessResponse(BaseModel):
    """Recording-scoped identity review readiness."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visual-card-identity-review-readiness/v1"]
    recording_id: str
    state: ReadinessState
    message: str
    blocker: IdentityBatchFailureResponse | None
    selected_card_count: int = Field(ge=0)
    batch: IdentityReviewBatchResponse | None
    preview_digest: str | None


class IdentityReviewCreateRequest(BaseModel):
    """The preview identity required to start preparation."""

    model_config = ConfigDict(extra="forbid")

    preview_digest: str = Field(pattern=SHA256_PATTERN)
    request_digest: str = Field(pattern=SHA256_PATTERN)


@dataclass(frozen=True, slots=True)
class _IdentityContext:
    recording_id: str
    source_asset_id: str
    source_sha256: str
    source_lineage_group: str
    visible_batch: dict[str, Any] | None
    classifier: Any | None
    request: VisualCardIdentityBatchRequest | None
    protected_groups: tuple[str, ...]


@router.get(
    "/v1/recordings/{recording_id}/identity-review",
    response_model=IdentityReviewReadinessResponse,
)
def get_identity_review_readiness(
    recording_id: str, request: Request
) -> IdentityReviewReadinessResponse:
    """Return recording readiness and any persisted identity preparation state."""

    context = _context(request, recording_id)
    preview = _preview(context)
    batch = _find_recording_batch(request, recording_id)
    if batch is not None:
        batch_response = _batch_response(request, batch)
        state, message = _batch_readiness(batch_response)
        return IdentityReviewReadinessResponse(
            schema_version="visual-card-identity-review-readiness/v1",
            recording_id=recording_id,
            state=state,
            message=message,
            blocker=_first_failure(batch_response.failures),
            selected_card_count=batch_response.coverage.identity_usable_card_count,
            batch=batch_response,
            preview_digest=preview["preview_digest"],
        )
    blockers = preview["validation"]["blockers"]
    first = blockers[0] if blockers else None
    return IdentityReviewReadinessResponse(
        schema_version="visual-card-identity-review-readiness/v1",
        recording_id=recording_id,
        state="ready" if not blockers else "not_ready",
        message=(
            f"Ready — {preview['selected_card_count']} identity-usable reviewed card"
            f"{'s' if preview['selected_card_count'] != 1 else ''}."
            if first is None
            else first["message"]
        ),
        blocker=None if first is None else IdentityBatchFailureResponse.model_validate(first),
        selected_card_count=preview["selected_card_count"],
        batch=None,
        preview_digest=preview["preview_digest"],
    )


@router.post(
    "/v1/recordings/{recording_id}/identity-review/preview",
    response_model=IdentityReviewPreviewResponse,
)
def preview_identity_review(recording_id: str, request: Request) -> IdentityReviewPreviewResponse:
    """Return the immutable visible-card and classifier facts for one preview."""

    return IdentityReviewPreviewResponse.model_validate(_preview(_context(request, recording_id)))


@router.post(
    "/v1/recordings/{recording_id}/identity-review/batches",
    response_model=IdentityReviewBatchResponse,
    status_code=202,
)
async def create_identity_review_batch(
    recording_id: str,
    payload: IdentityReviewCreateRequest,
    request: Request,
) -> IdentityReviewBatchResponse:
    """Create one preview-bound batch and schedule preparation outside the request thread."""

    context = _context(request, recording_id)
    preview = _preview(context)
    if not preview["validation"]["valid"] or context.request is None or context.classifier is None:
        raise ContractError(
            "identity_review_not_ready",
            "The visual card identity review batch cannot start until its blockers are resolved.",
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
            "identity_review_preview_stale",
            "The identity review preview changed. Create a new preview before starting.",
            status_code=409,
        )
    store = VisualCardIdentityBatchStore(request.app.state.settings.operations_root)
    try:
        state = store.initialize(context.request)
    except (VisualCardIdentityBatchError, OSError) as error:
        raise ContractError(
            "identity_review_batch_invalid",
            "The visual card identity review batch could not be initialized.",
        ) from error
    if state["status"] == "preparing":
        _schedule(request, context.request, context.classifier, resume=False)
    return _batch_response(request, state)


@router.get(
    "/v1/identity-reviews/{batch_id}",
    response_model=IdentityReviewBatchResponse,
)
def get_identity_review_batch(batch_id: str, request: Request) -> IdentityReviewBatchResponse:
    """Return one persisted identity preparation batch."""

    return _batch_response(request, _read_batch(request, batch_id))


@router.get(
    "/v1/identity-reviews/{batch_id}/items/{item_id}/crop",
    response_class=FileResponse,
)
def get_identity_review_crop(batch_id: str, item_id: str, request: Request) -> FileResponse:
    """Serve one frozen identity crop after batch ownership and digest checks."""

    state = _read_batch(request, batch_id)
    item = next((value for value in state["items"] if value["item_id"] == item_id), None)
    if item is None or not isinstance(item.get("crop"), dict):
        raise ContractError(
            "identity_review_crop_unavailable",
            "The identity crop is not available.",
            status_code=404,
        )
    crop = item["crop"]
    path = Path(crop["path"]).resolve()
    try:
        path.relative_to(
            VisualCardIdentityBatchStore(request.app.state.settings.operations_root)
            .batch_root(batch_id)
            .resolve()
        )
    except ValueError as error:
        raise ContractError(
            "identity_review_batch_invalid",
            "The stored identity crop is outside its batch.",
            status_code=500,
        ) from error
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != crop["sha256"]:
        raise ContractError(
            "identity_review_batch_invalid",
            "The frozen identity crop does not match its digest.",
            status_code=500,
        )
    return FileResponse(
        path, media_type=crop["content_type"], headers={"Cache-Control": "no-store"}
    )


@router.put(
    "/v1/identity-reviews/{batch_id}/items/{item_id}",
    response_model=IdentityReviewBatchResponse,
)
def update_identity_review_item(
    batch_id: str,
    item_id: str,
    payload: IdentityDecisionUpdateRequest,
    request: Request,
) -> IdentityReviewBatchResponse:
    """Save one explicit identity decision with an optimistic revision guard."""

    _read_batch(request, batch_id)
    store = VisualCardIdentityBatchStore(request.app.state.settings.operations_root)
    try:
        state = store.update_decision(
            batch_id,
            item_id,
            action=payload.action,
            identity=payload.identity,
            reason=payload.reason,
            failure_tags=payload.failure_tags,
            reviewer=payload.reviewer,
            expected_revision=payload.expected_revision,
        )
    except VisualCardIdentityBatchConflict as error:
        raise ContractError(
            "identity_review_conflict",
            "This review changed in another window. Reload the current revision before saving.",
            status_code=409,
        ) from error
    except (VisualCardIdentityBatchError, OSError) as error:
        raise ContractError(
            "identity_review_decision_invalid",
            str(error),
        ) from error
    return _batch_response(request, state)


@router.post(
    "/v1/identity-reviews/{batch_id}/complete",
    response_model=IdentityReviewBatchResponse,
)
def complete_identity_review(
    batch_id: str,
    payload: IdentityReviewCompletionRequest,
    request: Request,
) -> IdentityReviewBatchResponse:
    """Complete a draft after every crop has an explicit valid decision."""

    _read_batch(request, batch_id)
    store = VisualCardIdentityBatchStore(request.app.state.settings.operations_root)
    try:
        state = store.complete(
            batch_id,
            reviewer=payload.reviewer,
            expected_revision=payload.expected_revision,
        )
    except VisualCardIdentityBatchConflict as error:
        raise ContractError(
            "identity_review_conflict",
            "This review changed in another window. Reload the current revision before completing.",
            status_code=409,
        ) from error
    except (VisualCardIdentityBatchError, OSError) as error:
        raise ContractError(
            "identity_review_completion_invalid",
            str(error),
        ) from error
    return _batch_response(request, state)


@router.post(
    "/v1/identity-reviews/{batch_id}/retry",
    response_model=IdentityReviewBatchResponse,
    status_code=202,
)
async def retry_identity_review_batch(
    batch_id: str, request: Request
) -> IdentityReviewBatchResponse:
    """Retry failed preparation or unavailable classifier proposals with frozen inputs."""

    state = _read_batch(request, batch_id)
    if state["status"] not in {"failed", "ready"}:
        raise ContractError(
            "identity_review_retry_unavailable",
            "Only a failed or ready identity batch can be retried.",
        )
    context = _context(request, state["recording_id"])
    if context.request is None or context.classifier is None:
        raise ContractError(
            "identity_review_retry_unavailable",
            "The configured identity review inputs are no longer available.",
        )
    try:
        frozen = VisualCardIdentityBatchRequest.from_mapping(state["frozen_inputs"])
        current_identity = VisualCardIdentityClassifierIdentity.from_classifier(context.classifier)
    except (TypeError, ValueError, VisualCardIdentityBatchError) as error:
        raise ContractError(
            "identity_review_retry_unavailable",
            "The configured identity review inputs are no longer available.",
        ) from error
    if current_identity != frozen.classifier:
        raise ContractError(
            "identity_review_classifier_changed",
            "The configured classifier changed. Create a new identity review batch.",
            status_code=409,
        )
    context = _IdentityContext(
        recording_id=context.recording_id,
        source_asset_id=context.source_asset_id,
        source_sha256=context.source_sha256,
        source_lineage_group=context.source_lineage_group,
        visible_batch=context.visible_batch,
        classifier=context.classifier,
        request=frozen,
        protected_groups=context.protected_groups,
    )
    tasks: dict[str, asyncio.Task[Any]] = request.app.state.identity_review_batch_tasks
    active = tasks.get(batch_id)
    if active is not None and not active.done():
        with suppress(Exception):
            await active
    store = VisualCardIdentityBatchStore(request.app.state.settings.operations_root)
    try:
        state = store.begin_retry(batch_id)
    except (VisualCardIdentityBatchError, OSError) as error:
        raise ContractError(
            "identity_review_batch_invalid",
            "The identity review batch could not be prepared for retry.",
        ) from error
    _schedule(request, context.request, context.classifier, resume=True)
    return _batch_response(request, state)


def _context(request: Request, recording_id: str) -> _IdentityContext:
    if RECORDING_ID_PATTERN.fullmatch(recording_id) is None:
        raise ContractError("invalid_recording_id", "The recording ID is invalid.")
    source = _load_source(request, recording_id, require_selected=False)
    visible_batch = _find_visible_card_batch(request, recording_id)
    classifier = getattr(request.app.state, "visible_card_identity_classifier", None)
    if classifier is None:
        classifier = getattr(getattr(request.app.state, "analyzer", None), "classifier", None)
    identity = None
    if classifier is not None:
        try:
            identity = VisualCardIdentityClassifierIdentity.from_classifier(classifier)
        except VisualCardIdentityBatchError:
            identity = None
    frozen_request = None
    if visible_batch is not None and visible_batch.get("status") == "completed":
        queue_path = visible_batch.get("completed_queue_path")
        if isinstance(queue_path, str):
            try:
                frozen_request = (
                    VisualCardIdentityBatchRequest(
                        recording_id=recording_id,
                        source_asset_id=source.source_asset_id,
                        source_sha256=source.source_sha256,
                        source_lineage_group=source.source_asset_id,
                        visible_card_review_batch_id=visible_batch["batch_id"],
                        visible_card_review_version_id=visible_batch["completed_version_id"],
                        visible_card_review_version_digest=visible_batch[
                            "completed_version_digest"
                        ],
                        visible_card_review_queue_path=Path(queue_path),
                        visible_card_review_queue_digest=visible_batch["queue_digest"],
                        classifier=identity,
                        protected_source_lineage_groups=_protected_groups(request),
                    )
                    if identity is not None
                    else None
                )
            except (KeyError, TypeError, ValueError, VisualCardIdentityBatchError):
                frozen_request = None
    return _IdentityContext(
        recording_id=recording_id,
        source_asset_id=source.source_asset_id,
        source_sha256=source.source_sha256,
        source_lineage_group=source.source_asset_id,
        visible_batch=visible_batch,
        classifier=classifier,
        request=frozen_request,
        protected_groups=_protected_groups(request),
    )


def _protected_groups(request: Request) -> tuple[str, ...]:
    registry = load_system_holdout_registry(
        request.app.state.settings.operations_root / "system-holdout-registry.json"
    )
    return tuple(
        sorted(value for name, value in sealed_group_keys(registry) if name == "source_lineage")
    )


def _preview(context: _IdentityContext) -> dict[str, Any]:
    policy = context.request.crop_policy if context.request is not None else None
    if policy is None:
        from table_evidence_analyzer import frozen_visible_card_crop_policy

        policy = frozen_visible_card_crop_policy()
    crop_policy = {
        "policy_id": "raw_rectangular",
        "policy_digest": policy["policy_digest"],
        "policy": policy,
    }
    blockers = assess_visual_card_identity_review_readiness(
        source_lineage_group=context.source_lineage_group,
        protected_source_lineage_groups=context.protected_groups,
        source_review_available=context.visible_batch is not None
        and context.visible_batch.get("status") == "completed",
        classifier_available=context.classifier is not None,
        selected_card_count=0,
    )
    coverage = None
    selected_count = 0
    if context.request is not None and not any(
        failure.code
        in {
            "protected_source_group",
            "missing_visible_card_review",
            "identity_classifier_unavailable",
        }
        for failure in blockers
    ):
        try:
            facts = preview_visual_card_identity_review_batch(context.request)
            coverage = facts["coverage"]
            selected_count = facts["selected_card_count"]
            blockers = assess_visual_card_identity_review_readiness(
                source_lineage_group=context.source_lineage_group,
                protected_source_lineage_groups=context.protected_groups,
                source_review_available=True,
                classifier_available=True,
                selected_card_count=selected_count,
            )
        except VisualCardIdentityBatchError as error:
            blockers = [
                {
                    "code": "stale_visible_card_review",
                    "message": str(error),
                    "stage": "validation",
                    "item_id": None,
                    "retryable": False,
                }
            ]
    core = {
        "schema_version": "visual-card-identity-review-preview/v1",
        "recording_id": context.recording_id,
        "request_digest": None if context.request is None else context.request.request_digest,
        "visible_card_review_batch_id": None
        if context.visible_batch is None
        else context.visible_batch.get("batch_id"),
        "visible_card_review_version_id": None
        if context.visible_batch is None
        else context.visible_batch.get("completed_version_id"),
        "visible_card_review_version_digest": None
        if context.visible_batch is None
        else context.visible_batch.get("completed_version_digest"),
        "visible_card_review_queue_digest": None
        if context.visible_batch is None
        else context.visible_batch.get("queue_digest"),
        "source_asset_id": context.source_asset_id,
        "source_sha256": context.source_sha256,
        "source_lineage_group": context.source_lineage_group,
        "classifier": None if context.request is None else context.request.classifier.to_mapping(),
        "crop_policy": crop_policy,
        "selected_card_count": selected_count,
        "coverage": coverage,
        "blockers": [
            failure.to_mapping() if hasattr(failure, "to_mapping") else failure
            for failure in blockers
        ],
    }
    return {
        **{key: value for key, value in core.items() if key != "blockers"},
        "preview_digest": hashlib.sha256(
            json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "validation": {
            "valid": not blockers,
            "blockers": [
                failure.to_mapping() if hasattr(failure, "to_mapping") else failure
                for failure in blockers
            ],
        },
        "batch_id": None if context.request is None else context.request.batch_id,
        "request_digest": None if context.request is None else context.request.request_digest,
        "classifier": None if context.request is None else context.request.classifier.to_mapping(),
        "crop_policy": crop_policy,
        "coverage": coverage,
    }


def _find_recording_batch(request: Request, recording_id: str) -> dict[str, Any] | None:
    root = (
        VisualCardIdentityBatchStore(request.app.state.settings.operations_root).workspace_root
        / "visual-card-identity-review-batches"
    )
    if not root.is_dir():
        return None
    candidates: list[dict[str, Any]] = []
    for path in root.glob("visual-card-identity-batch-*/batch.json"):
        try:
            state = load_visual_card_identity_review_batch(path)
        except (VisualCardIdentityBatchError, OSError, ValueError):
            continue
        if state["recording_id"] == recording_id:
            candidates.append(state)
    return max(candidates, key=lambda value: value["updated_at_utc"], default=None)


def _find_visible_card_batch(request: Request, recording_id: str) -> dict[str, Any] | None:
    store = VisibleCardReviewBatchStore(request.app.state.settings.operations_root)
    root = store.workspace_root / "visible-card-review-batches"
    if not root.is_dir():
        return None
    candidates: list[dict[str, Any]] = []
    for path in root.glob("visible-card-batch-*/batch.json"):
        try:
            state = load_visible_card_review_batch(path)
        except (VisibleCardBatchError, OSError, ValueError):
            continue
        if state["frozen_inputs"].get("recording_id") == recording_id:
            candidates.append(state)
    return max(candidates, key=lambda value: value["updated_at_utc"], default=None)


def _read_batch(request: Request, batch_id: str) -> dict[str, Any]:
    if BATCH_ID_PATTERN.fullmatch(batch_id) is None:
        raise ContractError("invalid_identity_batch_id", "The identity batch ID is invalid.")
    path = VisualCardIdentityBatchStore(request.app.state.settings.operations_root).batch_path(
        batch_id
    )
    if not path.is_file():
        raise ContractError(
            "identity_review_batch_not_found",
            "The identity review batch was not found.",
            status_code=404,
        )
    try:
        return load_visual_card_identity_review_batch(path)
    except (VisualCardIdentityBatchError, OSError) as error:
        raise ContractError(
            "identity_review_batch_invalid",
            "The stored identity batch is invalid.",
            status_code=500,
        ) from error


def _schedule(
    request: Request,
    batch_request: VisualCardIdentityBatchRequest,
    classifier: Any,
    *,
    resume: bool,
) -> None:
    tasks: dict[str, asyncio.Task[Any]] = request.app.state.identity_review_batch_tasks
    existing = tasks.get(batch_request.batch_id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(
        asyncio.to_thread(
            prepare_visual_card_identity_review_batch,
            request.app.state.settings.operations_root,
            batch_request,
            classifier,
            resume=resume,
        )
    )
    tasks[batch_request.batch_id] = task

    def forget(completed: asyncio.Task[Any]) -> None:
        if tasks.get(batch_request.batch_id) is completed:
            tasks.pop(batch_request.batch_id, None)

    task.add_done_callback(forget)


def _batch_response(request: Request, state: dict[str, Any]) -> IdentityReviewBatchResponse:
    frozen = VisualCardIdentityBatchRequest.from_mapping(state["frozen_inputs"])
    items: list[IdentityReviewItemResponse] = []
    for item in state["items"]:
        source = item["source"]
        source_item_id = f"{source['package_id']}:{source['frame_part_name']}"
        source_url = (
            f"/v1/visible-card-reviews/{frozen.visible_card_review_batch_id}/items/"
            f"{source_item_id.replace(':', '%3A')}/image"
        )
        source_response = {
            "visible_card_review_batch_id": frozen.visible_card_review_batch_id,
            "visible_card_review_item_id": source_item_id,
            "package_id": source["package_id"],
            "frame_part_name": source["frame_part_name"],
            "image_url": source_url,
            "frame_sha256": source["frame_sha256"],
            "source_asset_id": source["source_asset_id"],
            "source_lineage_group": source["source_lineage_group"],
            "source_asset_sha256": source["source_asset_sha256"],
            "width": source["width"],
            "height": source["height"],
        }
        crop = item.get("crop")
        crop_response = None
        if isinstance(crop, dict):
            crop_url = f"/v1/identity-reviews/{state['batch_id']}/items/{item['item_id']}/crop"
            crop_response = {
                **{key: crop[key] for key in crop if key != "path"},
                "image_url": crop_url,
            }
        proposal = item.get("proposal")
        proposal_response = None
        if isinstance(proposal, dict):
            proposal_response = {
                key: value for key, value in proposal.items() if key != "result_path"
            }
        items.append(
            IdentityReviewItemResponse(
                schema_version=item["schema_version"],
                item_id=item["item_id"],
                visible_card_review_item_id=source_item_id,
                source=source_response,
                visible_card=item["visible_card"],
                visible_card_digest=item["visible_card_digest"],
                crop=crop_response,
                proposal=proposal_response,
                decision=item["decision"],
                status=item["status"],
                failure=item["failure"],
            )
        )
    policy = frozen.crop_policy
    assert policy is not None
    return IdentityReviewBatchResponse(
        schema_version=state["schema_version"],
        batch_id=state["batch_id"],
        recording_id=state["recording_id"],
        request_digest=state["request_digest"],
        status=state["status"],
        created_at_utc=state["created_at_utc"],
        updated_at_utc=state["updated_at_utc"],
        classifier=state["classifier"],
        crop_policy={
            "policy_id": state["crop_policy_id"],
            "policy_digest": policy["policy_digest"],
            "policy": policy,
        },
        progress=state["progress"],
        revision=state["revision"],
        review_state=state["review_state"],
        reviewer=state["reviewer"],
        completed_at_utc=state["completed_at_utc"],
        summary=state["summary"],
        items=items,
        coverage=state["coverage"],
        failures=state["failures"],
    )


def _batch_readiness(batch: IdentityReviewBatchResponse) -> tuple[ReadinessState, str]:
    if batch.status == "preparing":
        return "preparing", _progress_message(batch)
    if batch.status == "failed":
        return "failed", "Identity review preparation failed. Retry the failed items."
    if batch.status == "blocked":
        return "blocked", _first_failure(
            batch.failures
        ).message if batch.failures else "Identity review is blocked."
    if batch.review_state == "completed":
        return "ready", "Identity review complete. The current draft is ready for publication."
    crop_word = "crop" if len(batch.items) == 1 else "crops"
    return "ready", f"Ready to review — {len(batch.items)} identity {crop_word}."


def _progress_message(batch: IdentityReviewBatchResponse) -> str:
    return (
        f"Preparing identity review — {batch.progress.proposals_completed} of "
        f"{batch.progress.total_items} proposal{'s' if batch.progress.total_items != 1 else ''}."
    )


def _first_failure(
    failures: list[IdentityBatchFailureResponse],
) -> IdentityBatchFailureResponse | None:
    return failures[0] if failures else None


__all__ = [
    "IdentityReviewBatchResponse",
    "IdentityReviewPreviewResponse",
    "IdentityReviewReadinessResponse",
    "router",
]
