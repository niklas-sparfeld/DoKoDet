"""HTTP route and response models for pipeline comparisons."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import Field

from dokodetector_backend.contract import ContractModel, Sha256
from dokodetector_backend.errors import ContractError
from dokodetector_backend.pipeline_api_contracts import validate_recording_id
from dokodetector_backend.pipeline_service import (
    PipelineComparisonError,
    PipelineComparisonInputError,
)
from dokodetector_backend.pipeline_store import PipelineNotFound

router = APIRouter()
COMPARISON_BASE = "/api/recordings/{recording_id}/pipeline/comparisons"


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


@router.post(COMPARISON_BASE, response_model=PipelineComparisonResponse)
def compare_pipeline_runs(
    recording_id: str, payload: PipelineComparisonRequest, request: Request
) -> PipelineComparisonResponse:
    """Calculate one deterministic comparison without changing retained data."""

    validate_recording_id(recording_id)
    try:
        comparison = request.app.state.pipeline_comparison_service.compare(
            recording_id, payload.model_dump()
        )
    except PipelineNotFound as error:
        raise ContractError("comparison_input_not_found", str(error), status_code=404) from error
    except PipelineComparisonInputError as error:
        raise ContractError("invalid_comparison_request", str(error), status_code=422) from error
    except PipelineComparisonError as error:
        raise ContractError("comparison_unavailable", str(error), status_code=409) from error
    return PipelineComparisonResponse.model_validate(comparison.to_mapping())


__all__ = [
    "PipelineComparisonCountsResponse",
    "PipelineComparisonDeltaResponse",
    "PipelineComparisonIntervalResponse",
    "PipelineComparisonItemResponse",
    "PipelineComparisonMatchingPolicyRequest",
    "PipelineComparisonMetricsResponse",
    "PipelineComparisonReferenceResponse",
    "PipelineComparisonRequest",
    "PipelineComparisonResponse",
    "PipelineComparisonScopeResponse",
    "PipelineComparisonSideResponse",
    "router",
]
