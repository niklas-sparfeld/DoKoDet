"""HTTP routes for recording event processor runs."""

from __future__ import annotations

import re
from typing import Any, Literal

from doko_operations.derived_view import DerivedViewError
from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import Field

from dokodetector_backend.contract import ContractModel, Sha256
from dokodetector_backend.errors import APIErrorDetail, ContractError
from dokodetector_backend.observation_pipeline_service import (
    ObservationPipelineError,
    ObservationPipelineInputError,
    ObservationPipelineService,
)
from dokodetector_backend.pipeline_reference_service import (
    PipelineReferenceConflict,
    PipelineReferenceCoverageError,
    PipelineReferenceError,
    PipelineReferenceInputError,
)
from dokodetector_backend.pipeline_reference_store import (
    PipelineReferenceNotFound,
    PipelineReferenceStoreError,
)
from dokodetector_backend.pipeline_service import (
    EventPipelineService,
    PipelineComparisonError,
    PipelineComparisonInputError,
    PipelineComparisonService,
    PipelineInputError,
    PipelineServiceError,
    RecordingPipelineWorkspaceService,
)
from dokodetector_backend.pipeline_store import (
    PipelineConflict,
    PipelineNotFound,
    PipelineSelectionConflict,
    PipelineStateError,
)
from dokodetector_backend.visible_card_pipeline_service import (
    VisibleCardPipelineError,
    VisibleCardPipelineInputError,
    VisibleCardPipelineService,
)
from dokodetector_backend.visual_identity_pipeline_service import (
    VisualIdentityPipelineError,
    VisualIdentityPipelineInputError,
    VisualIdentityPipelineService,
)

router = APIRouter()
RECORDING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
WORKSPACE_BASE = "/api/recordings/{recording_id}/pipeline"
BASE = "/api/recordings/{recording_id}/pipeline/events"
VISIBLE_CARD_BASE = "/api/recordings/{recording_id}/pipeline/visible-cards"
DERIVED_FRAME_BASE = (
    "/api/recordings/{recording_id}/pipeline/derived-views/exact-event/{requested_time_us}"
)
VISUAL_IDENTITY_BASE = "/api/recordings/{recording_id}/pipeline/visual-identities"
IDENTITY_CROP_BASE = (
    "/api/recordings/{recording_id}/pipeline/derived-views/identity-crops/{revision_id}/{item_id}"
)
OBSERVATION_BASE = "/api/recordings/{recording_id}/pipeline/observations"
COMPARISON_BASE = "/api/recordings/{recording_id}/pipeline/comparisons"
REFERENCE_BASE = "/api/recordings/{recording_id}/pipeline/references/{content_type}"
REFERENCE_STAGE_BASE = "/api/recordings/{recording_id}/pipeline/{content_type}/reference"


class PipelineWorkspaceVideoResponse(ContractModel):
    """The accepted recording video identity used by all pipeline stages."""

    schema_version: Literal["recording-video/v1"]
    recording_id: str
    relative_path: str
    video_sha256: Sha256
    byte_length: int = Field(gt=0)
    duration_us: int = Field(gt=0)


class PipelineWorkspaceInputOptionResponse(ContractModel):
    """One immutable generated or maintained input revision available to a stage."""

    revision_id: str
    content_type: Literal["events", "visible_cards", "visual_identities", "table_observations"]
    origin: Literal["processor", "manual", "corrected"]
    completion_state: Literal["complete"]
    coverage_state: str
    display_label: str
    content_sha256: Sha256
    input_revision_ids: list[str]
    producer: dict[str, Any]
    coverage: dict[str, Any]
    created_at: str


class PipelineWorkspaceCompatibleInputSetResponse(ContractModel):
    """One exact revision set accepted by observation assembly."""

    input_revision_ids: list[str] = Field(min_length=3, max_length=3)
    display_label: str


class PipelineWorkspaceImplementationResponse(ContractModel):
    """The implementation identity frozen into one processor request."""

    name: str
    version: str


class PipelineWorkspaceProgressResponse(ContractModel):
    """Progress persisted for one processor or analysis execution."""

    completed: int = Field(ge=0)
    total: int = Field(ge=0)


class PipelineWorkspaceFailureResponse(ContractModel):
    """The public failure summary for one processor run."""

    code: str
    message: str


class PipelineWorkspaceRunResponse(ContractModel):
    """The retained execution facts needed to reproduce one stage result."""

    run_id: str
    status: Literal["queued", "running", "complete", "partial", "failed"]
    attempt: int = Field(gt=0)
    request: dict[str, Any]
    state: dict[str, Any]
    input_revision_ids: list[str]
    implementation: PipelineWorkspaceImplementationResponse
    model: dict[str, Any] | None = None
    configuration: dict[str, Any]
    extraction_policy: dict[str, Any]
    crop_policy: dict[str, Any] | None = None
    output_revision_ids: list[str]
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str
    progress: PipelineWorkspaceProgressResponse
    failure: PipelineWorkspaceFailureResponse | None = None
    failed_item_count: int = Field(ge=0)


class PipelineWorkspaceReferenceResponse(ContractModel):
    """The one maintained reference and its current draft facts."""

    state: Literal["empty", "draft", "complete"]
    draft_revision: int | None = Field(default=None, ge=0)
    selected_completion: str | None = None
    source_revision_id: str | None = None
    coverage: dict[str, Any] | None = None
    coverage_state: Literal["none", "incomplete", "complete"]
    affected_count: int = Field(ge=0)
    updated_at: str | None = None


class PipelineWorkspaceAnalysisResponse(ContractModel):
    """The retained round-analysis lifecycle facts shown by the final stage."""

    analysis_id: str
    recording_id: str
    round_id: str
    session_id: str
    state: Literal["queued", "analyzing_evidence", "reconstructing", "complete", "failed"]
    input_revision_ids: list[str]
    request: dict[str, Any]
    progress: PipelineWorkspaceProgressResponse
    failure: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None


class PipelineWorkspaceDiagnosticResponse(ContractModel):
    """A persisted resource that could not be used to build the workspace."""

    code: str
    message: str
    content_type: str | None = None
    revision_id: str | None = None


class PipelineWorkspaceStageResponse(ContractModel):
    """One fixed recording-pipeline stage summary."""

    key: Literal[
        "events",
        "visible_cards",
        "visual_identities",
        "table_observations",
        "round_analyses",
    ]
    processor_key: str
    processor_type: str
    output_content_type: str
    has_maintained_reference: bool
    state: Literal[
        "video-only",
        "empty",
        "active-run",
        "partial",
        "failed",
        "generated-only",
        "draft",
        "affected",
        "incomplete-coverage",
        "complete",
    ]
    input_options: list[PipelineWorkspaceInputOptionResponse]
    compatible_input_sets: list[PipelineWorkspaceCompatibleInputSetResponse]
    selection_revision: int | None = Field(default=None, ge=0)
    selected_generated_revision_id: str | None = None
    selected_completed_reference_revision_id: str | None = None
    runs: list[PipelineWorkspaceRunResponse]
    analyses: list[PipelineWorkspaceAnalysisResponse]
    reference: PipelineWorkspaceReferenceResponse | None = None
    can_run: bool
    run_blockers: list[str]
    can_review: bool
    review_blockers: list[str]
    comparable_run_ids: list[str]


class PipelineWorkspaceResponse(ContractModel):
    """Strict ``pipeline-workspace/v1`` response for one accepted recording."""

    schema_version: Literal["pipeline-workspace/v1"]
    recording_id: str
    video: PipelineWorkspaceVideoResponse
    stages: list[PipelineWorkspaceStageResponse] = Field(min_length=5, max_length=5)
    diagnostics: list[PipelineWorkspaceDiagnosticResponse]


class PipelineComparisonMatchingPolicyRequest(ContractModel):
    """The event timing policy supplied by the comparison client."""

    policy_id: str = Field(min_length=1, max_length=128)
    kind: (
        Literal[
            "event_timing",
            "visible_card_geometry",
            "visual_identity_geometry",
        ]
        | None
    ) = None
    anchor: Literal["start_us", "end_us", "midpoint_us"] | None = None
    tolerance_us: int | None = Field(default=None, ge=0)
    event_type: str | None = Field(default=None, min_length=1, max_length=128)
    iou_threshold: float | None = Field(default=None, gt=0, le=1)
    derived_box_policy: Literal["bounding_box"] | None = None


class PipelineComparisonRequest(ContractModel):
    """The strict request for one on-demand comparison."""

    schema_version: Literal["pipeline-comparison-request/v1"]
    recording_id: str = Field(min_length=1, max_length=128)
    content_type: Literal["events", "visible_cards", "visual_identities"]
    left_run_id: str = Field(min_length=1, max_length=128)
    right_run_id: str = Field(min_length=1, max_length=128)
    reference_revision_id: str = Field(min_length=1, max_length=128)
    matching_policy: PipelineComparisonMatchingPolicyRequest


class PipelineComparisonIntervalResponse(ContractModel):
    """One normalized event coverage interval."""

    start_us: int = Field(ge=0)
    end_us: int = Field(gt=0)


class PipelineComparisonScopeResponse(ContractModel):
    """The reviewed and side evidence coverage used by a comparison."""

    reviewed: list[PipelineComparisonIntervalResponse]
    common_covered: list[PipelineComparisonIntervalResponse]
    left_only: list[PipelineComparisonIntervalResponse]
    right_only: list[PipelineComparisonIntervalResponse]
    reviewed_frame_identities: list[dict[str, Any]]
    common_frame_identities: list[dict[str, Any]]
    left_only_frame_identities: list[dict[str, Any]]
    right_only_frame_identities: list[dict[str, Any]]


class PipelineComparisonCountsResponse(ContractModel):
    """Counts for one comparison side."""

    reference_events: int = Field(ge=0)
    run_events: int = Field(ge=0)
    matches: int = Field(ge=0)
    misses: int = Field(ge=0)
    extras: int = Field(ge=0)
    not_reviewed: int = Field(ge=0)
    unpaired_input: int = Field(ge=0)
    failures: int = Field(ge=0)


class PipelineComparisonMetricsResponse(ContractModel):
    """Metrics calculated from reviewed and covered events only."""

    precision: float | None
    recall: float | None
    f1: float | None
    mean_error_us: float | None
    max_error_us: int | None


class PipelineComparisonDeltaResponse(PipelineComparisonMetricsResponse):
    """Right-minus-left metrics for a paired comparison."""


class PipelineComparisonSideResponse(ContractModel):
    """Exact run and output revision facts used by one comparison side."""

    run_id: str
    revision_id: str
    status: Literal["complete", "partial"]
    input_revision_ids: list[str]
    content_sha256: Sha256
    implementation: dict[str, Any]
    model: dict[str, Any] | None
    configuration: dict[str, Any]
    extraction_policy: dict[str, Any]
    failure: dict[str, Any] | None


class PipelineComparisonReferenceResponse(ContractModel):
    """Exact completed reference revision facts used by a comparison."""

    revision_id: str
    input_revision_ids: list[str]
    content_sha256: Sha256
    origin: Literal["manual", "corrected"]


class PipelineComparisonItemResponse(ContractModel):
    """One stable source-ordered event outcome."""

    item_id: str
    side: Literal["left", "right"]
    outcome: Literal[
        "match",
        "miss",
        "extra",
        "disagreement",
        "failure",
        "empty",
        "not_reviewed",
        "unpaired_input",
    ]
    source_time_us: int | None
    event_type: str
    reference_event_id: str | None
    run_event_id: str | None
    reference_event: dict[str, Any] | None
    run_event: dict[str, Any] | None
    delta_us: int | None
    source_links: dict[str, str]
    frame_identity: dict[str, Any] | None
    reference_card_id: str | None
    run_card_id: str | None
    reference_card: dict[str, Any] | None
    run_card: dict[str, Any] | None
    iou: float | None
    reference_identity: str | None
    run_identity: str | None
    reference_candidates: list[dict[str, Any]] | None
    run_candidates: list[dict[str, Any]] | None


class PipelineComparisonResponse(ContractModel):
    """Strict ``pipeline-comparison/v1`` response."""

    schema_version: Literal["pipeline-comparison/v1"]
    comparison_id: str
    recording_id: str
    content_type: Literal["events", "visible_cards", "visual_identities"]
    mode: Literal["paired_processor", "upstream_experiment"]
    algorithm_version: str
    left: PipelineComparisonSideResponse
    right: PipelineComparisonSideResponse
    reference: PipelineComparisonReferenceResponse
    scope: PipelineComparisonScopeResponse
    matching_policy: PipelineComparisonMatchingPolicyRequest
    counts: dict[Literal["left", "right"], PipelineComparisonCountsResponse]
    metrics: dict[Literal["left", "right"], PipelineComparisonMetricsResponse]
    paired_delta: PipelineComparisonDeltaResponse | None
    items: list[PipelineComparisonItemResponse]


@router.get(WORKSPACE_BASE, response_model=PipelineWorkspaceResponse)
def get_recording_pipeline_workspace(
    recording_id: str, request: Request
) -> PipelineWorkspaceResponse:
    """Return the persisted recording-pipeline workspace summary."""

    _validate_recording_id(recording_id)
    try:
        return PipelineWorkspaceResponse.model_validate(
            _workspace_service(request).get_workspace(recording_id)
        )
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except (PipelineInputError, PipelineServiceError) as error:
        raise ContractError(
            "pipeline_workspace_unavailable", str(error), status_code=409
        ) from error


@router.post(BASE, status_code=202)
@router.post(BASE + "/runs", status_code=202, include_in_schema=False)
def start_event_run(recording_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """Freeze and queue one event processor request."""

    service = _service(request)
    _validate_recording_id(recording_id)
    try:
        return _run_response(service.start_inference(recording_id, payload))
    except (PipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_pipeline_request", str(error), status_code=422) from error
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except PipelineServiceError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(BASE)
@router.get(BASE + "/runs", include_in_schema=False)
def list_event_runs(recording_id: str, request: Request) -> dict[str, Any]:
    """List durable event processor runs for one recording."""

    _validate_recording_id(recording_id)
    try:
        runs = _service(request).list_runs(recording_id)
    except PipelineServiceError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error
    return {"recording_id": recording_id, "runs": [_run_response(run) for run in runs]}


@router.post(BASE + "/import", status_code=201)
@router.post(BASE + "/imports", status_code=201, include_in_schema=False)
def import_event_predictions(
    recording_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """Validate and import one recording-bundle event prediction artifact."""

    _validate_recording_id(recording_id)
    try:
        run = _service(request).import_predictions(recording_id, payload)
        return _run_response(run)
    except PipelineInputError as error:
        raise ContractError("invalid_event_import", str(error), status_code=422) from error
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except PipelineConflict as error:
        raise ContractError("pipeline_conflict", str(error), status_code=409) from error
    except PipelineServiceError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(BASE + "/selection")
@router.get(BASE + "/generated-selection", include_in_schema=False)
def get_generated_selection(recording_id: str, request: Request) -> dict[str, Any]:
    """Return the current generated and completed-reference event pointers."""

    _validate_recording_id(recording_id)
    selection = _service(request).selection_store.get(recording_id, "events")
    return {
        "recording_id": recording_id,
        "selection": None if selection is None else selection.to_mapping(),
    }


@router.put(BASE + "/selection")
@router.put(BASE + "/generated-selection", include_in_schema=False)
def update_generated_selection(
    recording_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """Update the generated event pointer with an optimistic revision check."""

    _validate_recording_id(recording_id)
    try:
        selection = _service(request).select_generated(recording_id, payload)
    except PipelineSelectionConflict as error:
        raise ContractError("selection_conflict", str(error), status_code=409) from error
    except (PipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_selection", str(error), status_code=422) from error
    return {"recording_id": recording_id, "selection": selection.to_mapping()}


@router.get(BASE + "/{run_id}")
@router.get(BASE + "/runs/{run_id}", include_in_schema=False)
def get_event_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return one event processor run and its immutable request."""

    try:
        return _run_response(_service(request).get_run(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except PipelineServiceError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.post(BASE + "/{run_id}/retry", status_code=202)
@router.post(BASE + "/runs/{run_id}/retry", status_code=202, include_in_schema=False)
def retry_event_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Retry one failed or partial event processor run."""

    try:
        return _run_response(_service(request).retry(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except (PipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_pipeline_retry", str(error), status_code=422) from error
    except PipelineServiceError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(BASE + "/{run_id}/result")
@router.get(BASE + "/runs/{run_id}/result", include_in_schema=False)
def get_event_result(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return a completed event run and its stored data revisions."""

    try:
        run, revisions = _service(request).get_result(recording_id, run_id)
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except PipelineServiceError as error:
        raise ContractError("pipeline_result_unavailable", str(error), status_code=409) from error
    return {
        **_run_response(run),
        "revisions": [revision.to_mapping() for revision in revisions],
    }


@router.post(VISIBLE_CARD_BASE, status_code=202)
@router.post(VISIBLE_CARD_BASE + "/runs", status_code=202, include_in_schema=False)
def start_visible_card_run(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Freeze one event revision and queue a visible-card detector run."""

    _validate_recording_id(recording_id)
    try:
        return _run_response(_visible_service(request).start_detection(recording_id, payload))
    except (VisibleCardPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_pipeline_request", str(error), status_code=422) from error
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except VisibleCardPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(VISIBLE_CARD_BASE)
@router.get(VISIBLE_CARD_BASE + "/runs", include_in_schema=False)
def list_visible_card_runs(recording_id: str, request: Request) -> dict[str, Any]:
    """List durable visible-card detector runs for one recording."""

    _validate_recording_id(recording_id)
    try:
        runs = _visible_service(request).list_runs(recording_id)
    except VisibleCardPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error
    return {"recording_id": recording_id, "runs": [_run_response(run) for run in runs]}


@router.get(VISIBLE_CARD_BASE + "/selection")
@router.get(VISIBLE_CARD_BASE + "/generated-selection", include_in_schema=False)
def get_visible_card_selection(recording_id: str, request: Request) -> dict[str, Any]:
    """Return the current visible-card generated and reference pointers."""

    _validate_recording_id(recording_id)
    selection = _visible_service(request).selection_store.get(recording_id, "visible_cards")
    return {
        "recording_id": recording_id,
        "selection": None if selection is None else selection.to_mapping(),
    }


@router.put(VISIBLE_CARD_BASE + "/selection")
@router.put(VISIBLE_CARD_BASE + "/generated-selection", include_in_schema=False)
def update_visible_card_selection(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Update the visible-card generated pointer with an optimistic revision check."""

    _validate_recording_id(recording_id)
    try:
        selection = _visible_service(request).select_generated(recording_id, payload)
    except PipelineSelectionConflict as error:
        raise ContractError("selection_conflict", str(error), status_code=409) from error
    except (VisibleCardPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_selection", str(error), status_code=422) from error
    return {"recording_id": recording_id, "selection": selection.to_mapping()}


@router.get(VISIBLE_CARD_BASE + "/{run_id}")
@router.get(VISIBLE_CARD_BASE + "/runs/{run_id}", include_in_schema=False)
def get_visible_card_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return one visible-card detector run and its immutable request."""

    try:
        return _run_response(_visible_service(request).get_run(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except VisibleCardPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.post(VISIBLE_CARD_BASE + "/{run_id}/retry", status_code=202)
@router.post(VISIBLE_CARD_BASE + "/runs/{run_id}/retry", status_code=202, include_in_schema=False)
def retry_visible_card_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Retry one failed visible-card detector run."""

    try:
        return _run_response(_visible_service(request).retry(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except (VisibleCardPipelineInputError, PipelineConflict, PipelineStateError) as error:
        raise ContractError("invalid_pipeline_retry", str(error), status_code=422) from error
    except VisibleCardPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(VISIBLE_CARD_BASE + "/{run_id}/result")
@router.get(VISIBLE_CARD_BASE + "/runs/{run_id}/result", include_in_schema=False)
def get_visible_card_result(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return one completed visible-card detector run and its stored revision."""

    try:
        run, revisions = _visible_service(request).get_result(recording_id, run_id)
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except VisibleCardPipelineError as error:
        raise ContractError("pipeline_result_unavailable", str(error), status_code=409) from error
    return {
        **_run_response(run),
        "revisions": [revision.to_mapping() for revision in revisions],
    }


@router.get(DERIVED_FRAME_BASE, response_class=Response)
def get_recording_exact_event_frame(
    recording_id: str, requested_time_us: int, request: Request
) -> Response:
    """Return one verified exact-event frame resolved from the accepted recording video."""

    _validate_recording_id(recording_id)
    if requested_time_us < 0:
        raise ContractError(
            "invalid_derived_view_request",
            "requested_time_us must be non-negative.",
            status_code=422,
        )
    try:
        frame = _visible_service(request).resolve_source_frame(recording_id, requested_time_us)
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except (VisibleCardPipelineInputError, DerivedViewError, OSError, RuntimeError) as error:
        raise ContractError("derived_view_unavailable", str(error), status_code=409) from error
    return Response(
        content=frame.image_bytes,
        media_type=frame.content_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "ETag": f'"{frame.image_sha256}"',
        },
    )


@router.get(IDENTITY_CROP_BASE, response_class=Response)
def get_recording_identity_crop(
    recording_id: str, revision_id: str, item_id: str, request: Request
) -> Response:
    """Return one verified identity crop derived from a stored identity revision."""

    _validate_recording_id(recording_id)
    try:
        crop = _visual_identity_service(request).resolve_identity_crop(
            recording_id, revision_id, item_id
        )
    except PipelineNotFound as error:
        raise ContractError("identity_crop_not_found", str(error), status_code=404) from error
    except (VisualIdentityPipelineInputError, DerivedViewError, OSError, RuntimeError) as error:
        raise ContractError("derived_view_unavailable", str(error), status_code=409) from error
    if crop.image_bytes is None:
        raise ContractError(
            "identity_crop_unavailable",
            crop.unusable_reason or "The identity crop is unavailable.",
            status_code=409,
        )
    return Response(
        content=crop.image_bytes,
        media_type=crop.content_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "ETag": f'"{crop.image_sha256}"',
        },
    )


@router.post(VISUAL_IDENTITY_BASE, status_code=202)
@router.post(VISUAL_IDENTITY_BASE + "/runs", status_code=202, include_in_schema=False)
def start_visual_identity_run(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Freeze one visible-card revision and queue identity classification."""

    _validate_recording_id(recording_id)
    try:
        return _run_response(
            _visual_identity_service(request).start_classification(recording_id, payload)
        )
    except (VisualIdentityPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_pipeline_request", str(error), status_code=422) from error
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(VISUAL_IDENTITY_BASE)
@router.get(VISUAL_IDENTITY_BASE + "/runs", include_in_schema=False)
def list_visual_identity_runs(recording_id: str, request: Request) -> dict[str, Any]:
    """List durable visual identity classifier runs for one recording."""

    _validate_recording_id(recording_id)
    try:
        runs = _visual_identity_service(request).list_runs(recording_id)
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error
    return {"recording_id": recording_id, "runs": [_run_response(run) for run in runs]}


@router.get(VISUAL_IDENTITY_BASE + "/selection")
@router.get(VISUAL_IDENTITY_BASE + "/generated-selection", include_in_schema=False)
def get_visual_identity_selection(recording_id: str, request: Request) -> dict[str, Any]:
    """Return the current visual identity generated and reference pointers."""

    _validate_recording_id(recording_id)
    selection = _visual_identity_service(request).selection_store.get(
        recording_id, "visual_identities"
    )
    return {
        "recording_id": recording_id,
        "selection": None if selection is None else selection.to_mapping(),
    }


@router.put(VISUAL_IDENTITY_BASE + "/selection")
@router.put(VISUAL_IDENTITY_BASE + "/generated-selection", include_in_schema=False)
def update_visual_identity_selection(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Update the visual identity generated pointer with an optimistic revision check."""

    _validate_recording_id(recording_id)
    try:
        selection = _visual_identity_service(request).select_generated(recording_id, payload)
    except PipelineSelectionConflict as error:
        raise ContractError("selection_conflict", str(error), status_code=409) from error
    except (VisualIdentityPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_selection", str(error), status_code=422) from error
    return {"recording_id": recording_id, "selection": selection.to_mapping()}


@router.get(VISUAL_IDENTITY_BASE + "/{run_id}")
@router.get(VISUAL_IDENTITY_BASE + "/runs/{run_id}", include_in_schema=False)
def get_visual_identity_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return one visual identity classifier run and its immutable request."""

    try:
        return _run_response(_visual_identity_service(request).get_run(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.post(VISUAL_IDENTITY_BASE + "/{run_id}/retry", status_code=202)
@router.post(
    VISUAL_IDENTITY_BASE + "/runs/{run_id}/retry", status_code=202, include_in_schema=False
)
def retry_visual_identity_run(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Retry one failed visual identity classifier run."""

    try:
        return _run_response(_visual_identity_service(request).retry(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except (VisualIdentityPipelineInputError, PipelineConflict, PipelineStateError) as error:
        raise ContractError("invalid_pipeline_retry", str(error), status_code=422) from error
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(VISUAL_IDENTITY_BASE + "/{run_id}/result")
@router.get(VISUAL_IDENTITY_BASE + "/runs/{run_id}/result", include_in_schema=False)
def get_visual_identity_result(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return a completed visual identity run and its stored revision."""

    try:
        run, revisions = _visual_identity_service(request).get_result(recording_id, run_id)
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except VisualIdentityPipelineError as error:
        raise ContractError("pipeline_result_unavailable", str(error), status_code=409) from error
    return {
        **_run_response(run),
        "revisions": [revision.to_mapping() for revision in revisions],
    }


@router.post(OBSERVATION_BASE, status_code=202)
@router.post(OBSERVATION_BASE + "/runs", status_code=202, include_in_schema=False)
def start_observation_assembly(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Freeze three selected revisions and queue observation assembly."""

    _validate_recording_id(recording_id)
    try:
        return _run_response(_observation_service(request).start_assembly(recording_id, payload))
    except (ObservationPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_pipeline_request", str(error), status_code=422) from error
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except ObservationPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(OBSERVATION_BASE)
@router.get(OBSERVATION_BASE + "/runs", include_in_schema=False)
def list_observation_assemblies(recording_id: str, request: Request) -> dict[str, Any]:
    """List durable observation assembly runs for one recording."""

    _validate_recording_id(recording_id)
    try:
        runs = _observation_service(request).list_runs(recording_id)
    except ObservationPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error
    return {"recording_id": recording_id, "runs": [_run_response(run) for run in runs]}


@router.get(OBSERVATION_BASE + "/selection")
@router.get(OBSERVATION_BASE + "/generated-selection", include_in_schema=False)
def get_observation_selection(recording_id: str, request: Request) -> dict[str, Any]:
    """Return the current table-observation generated and reference pointers."""

    _validate_recording_id(recording_id)
    selection = _observation_service(request).selection_store.get(
        recording_id, "table_observations"
    )
    return {
        "recording_id": recording_id,
        "selection": None if selection is None else selection.to_mapping(),
    }


@router.put(OBSERVATION_BASE + "/selection")
@router.put(OBSERVATION_BASE + "/generated-selection", include_in_schema=False)
def update_observation_selection(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Update the generated table-observation pointer with an optimistic revision check."""

    _validate_recording_id(recording_id)
    try:
        selection = _observation_service(request).select_generated(recording_id, payload)
    except PipelineSelectionConflict as error:
        raise ContractError("selection_conflict", str(error), status_code=409) from error
    except (ObservationPipelineInputError, PipelineConflict) as error:
        raise ContractError("invalid_selection", str(error), status_code=422) from error
    return {"recording_id": recording_id, "selection": selection.to_mapping()}


@router.get(OBSERVATION_BASE + "/{run_id}")
@router.get(OBSERVATION_BASE + "/runs/{run_id}", include_in_schema=False)
def get_observation_assembly(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Return one observation assembly run and its immutable request."""

    try:
        return _run_response(_observation_service(request).get_run(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except ObservationPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.post(OBSERVATION_BASE + "/{run_id}/retry", status_code=202)
@router.post(OBSERVATION_BASE + "/runs/{run_id}/retry", status_code=202, include_in_schema=False)
def retry_observation_assembly(recording_id: str, run_id: str, request: Request) -> dict[str, Any]:
    """Retry one failed observation assembly run."""

    try:
        return _run_response(_observation_service(request).retry(recording_id, run_id))
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except (ObservationPipelineInputError, PipelineConflict, PipelineStateError) as error:
        raise ContractError("invalid_pipeline_retry", str(error), status_code=422) from error
    except ObservationPipelineError as error:
        raise ContractError("pipeline_unavailable", str(error), status_code=503) from error


@router.get(OBSERVATION_BASE + "/{run_id}/result")
@router.get(OBSERVATION_BASE + "/runs/{run_id}/result", include_in_schema=False)
def get_observation_assembly_result(
    recording_id: str, run_id: str, request: Request
) -> dict[str, Any]:
    """Return one completed observation assembly and its stored revision."""

    try:
        run, revisions = _observation_service(request).get_result(recording_id, run_id)
    except PipelineNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    except ObservationPipelineError as error:
        raise ContractError("pipeline_result_unavailable", str(error), status_code=409) from error
    return {
        **_run_response(run),
        "revisions": [revision.to_mapping() for revision in revisions],
    }


@router.post(COMPARISON_BASE, response_model=PipelineComparisonResponse)
def compare_pipeline_runs(
    recording_id: str, payload: PipelineComparisonRequest, request: Request
) -> PipelineComparisonResponse:
    """Calculate one deterministic comparison without changing retained data."""

    _validate_recording_id(recording_id)
    try:
        comparison = _comparison_service(request).compare(recording_id, payload.model_dump())
    except PipelineNotFound as error:
        raise ContractError("comparison_input_not_found", str(error), status_code=404) from error
    except PipelineComparisonInputError as error:
        raise ContractError("invalid_comparison_request", str(error), status_code=422) from error
    except PipelineComparisonError as error:
        raise ContractError("comparison_unavailable", str(error), status_code=409) from error
    return PipelineComparisonResponse.model_validate(comparison.to_mapping())


@router.get(REFERENCE_BASE)
@router.get(REFERENCE_STAGE_BASE, include_in_schema=False)
def get_reference(recording_id: str, content_type: str, request: Request) -> dict[str, Any]:
    """Return one maintained reference draft and its current pointer."""

    _validate_recording_id(recording_id)
    try:
        reference = _reference_service(request).get_reference(recording_id, content_type)
    except PipelineReferenceNotFound as error:
        raise ContractError("reference_not_found", str(error), status_code=404) from error
    except (PipelineReferenceInputError, PipelineReferenceStoreError) as error:
        raise ContractError("reference_unavailable", str(error), status_code=409) from error
    return _reference_response(reference)


@router.post(REFERENCE_BASE, status_code=201)
@router.post(REFERENCE_STAGE_BASE, status_code=201, include_in_schema=False)
def create_reference(
    recording_id: str, content_type: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Create the one recording-owned reference, seeded from a result or empty."""

    _validate_recording_id(recording_id)
    try:
        reference = _reference_service(request).create_reference(
            recording_id, content_type, payload
        )
    except PipelineReferenceConflict as error:
        raise ContractError("reference_conflict", str(error), status_code=409) from error
    except PipelineReferenceInputError as error:
        raise ContractError("invalid_reference_request", str(error), status_code=422) from error
    except PipelineReferenceError as error:
        raise ContractError("reference_unavailable", str(error), status_code=503) from error
    return _reference_response(reference)


@router.put(REFERENCE_BASE + "/draft")
@router.put(REFERENCE_STAGE_BASE + "/draft", include_in_schema=False)
def update_reference_draft(
    recording_id: str, content_type: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Apply conflict-safe review operations to the current reference draft."""

    _validate_recording_id(recording_id)
    try:
        reference = _reference_service(request).update_draft(recording_id, content_type, payload)
    except PipelineReferenceConflict as error:
        raise ContractError(
            "reference_conflict",
            str(error),
            status_code=409,
            details=[
                APIErrorDetail(
                    field="current_revision",
                    message=str(error.current.state.draft_revision),
                )
            ],
        ) from error
    except PipelineReferenceNotFound as error:
        raise ContractError("reference_not_found", str(error), status_code=404) from error
    except PipelineReferenceInputError as error:
        raise ContractError("invalid_reference_edit", str(error), status_code=422) from error
    except PipelineReferenceError as error:
        raise ContractError("reference_unavailable", str(error), status_code=503) from error
    return _reference_response(reference)


@router.post(REFERENCE_BASE + "/complete", status_code=201)
@router.post(REFERENCE_STAGE_BASE + "/complete", status_code=201, include_in_schema=False)
def complete_reference(
    recording_id: str, content_type: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Publish the reviewed draft as an immutable completed reference revision."""

    _validate_recording_id(recording_id)
    try:
        reference = _reference_service(request).complete_reference(
            recording_id, content_type, payload
        )
    except PipelineReferenceConflict as error:
        raise ContractError(
            "reference_conflict",
            str(error),
            status_code=409,
            details=[
                APIErrorDetail(
                    field="current_revision",
                    message=str(error.current.state.draft_revision),
                )
            ],
        ) from error
    except PipelineReferenceNotFound as error:
        raise ContractError("reference_not_found", str(error), status_code=404) from error
    except PipelineReferenceCoverageError as error:
        raise ContractError(
            "incomplete_reference_coverage",
            str(error),
            status_code=422,
            details=[APIErrorDetail(**detail) for detail in error.details],
        ) from error
    except PipelineReferenceInputError as error:
        raise ContractError("invalid_reference_completion", str(error), status_code=422) from error
    except PipelineReferenceError as error:
        raise ContractError("reference_unavailable", str(error), status_code=503) from error
    return _reference_response(reference)


def _service(request: Request) -> EventPipelineService:
    return request.app.state.event_pipeline_service


def _workspace_service(request: Request) -> RecordingPipelineWorkspaceService:
    return request.app.state.pipeline_workspace_service


def _visible_service(request: Request) -> VisibleCardPipelineService:
    return request.app.state.visible_card_pipeline_service


def _visual_identity_service(request: Request) -> VisualIdentityPipelineService:
    return request.app.state.visual_identity_pipeline_service


def _observation_service(request: Request) -> ObservationPipelineService:
    return request.app.state.observation_pipeline_service


def _comparison_service(request: Request) -> PipelineComparisonService:
    return request.app.state.pipeline_comparison_service


def _reference_service(request: Request) -> Any:
    return request.app.state.pipeline_reference_service


def _validate_recording_id(recording_id: str) -> None:
    if RECORDING_ID_PATTERN.fullmatch(recording_id) is None:
        raise ContractError("invalid_recording_id", "The recording ID is invalid.")


def _run_response(run: Any) -> dict[str, Any]:
    request = run.request.to_mapping()
    state = run.state.to_mapping()
    return {
        "run_id": run.run_id,
        "recording_id": run.request.source.recording_id,
        "processor_type": run.request.processor_type,
        "status": run.state.status,
        "attempt": run.state.attempt,
        "request": request,
        "state": state,
    }


def _reference_response(reference: Any) -> dict[str, Any]:
    return {
        "recording_id": reference.state.recording_id,
        "content_type": reference.state.content_type,
        "state": reference.state.to_mapping(),
        "draft": reference.draft.to_mapping(),
    }


__all__ = ["router"]
