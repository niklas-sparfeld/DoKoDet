"""HTTP routes and response models for the recording pipeline workspace."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import Field

from dokodetector_backend.contract import ContractModel, Sha256
from dokodetector_backend.errors import ContractError
from dokodetector_backend.pipeline_api_contracts import validate_recording_id
from dokodetector_backend.pipeline_service import (
    PipelineInputError,
    PipelineServiceError,
)
from dokodetector_backend.pipeline_store import PipelineNotFound

router = APIRouter()
WORKSPACE_BASE = "/api/recordings/{recording_id}/pipeline"


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


@router.get(WORKSPACE_BASE, response_model=PipelineWorkspaceResponse)
def get_recording_pipeline_workspace(
    recording_id: str, request: Request
) -> PipelineWorkspaceResponse:
    """Return the persisted recording-pipeline workspace summary."""

    validate_recording_id(recording_id)
    try:
        return PipelineWorkspaceResponse.model_validate(
            request.app.state.pipeline_workspace_service.get_workspace(recording_id)
        )
    except PipelineNotFound as error:
        raise ContractError("recording_not_found", str(error), status_code=404) from error
    except (PipelineInputError, PipelineServiceError) as error:
        raise ContractError(
            "pipeline_workspace_unavailable", str(error), status_code=409
        ) from error


__all__ = [
    "PipelineWorkspaceAnalysisResponse",
    "PipelineWorkspaceCompatibleInputSetResponse",
    "PipelineWorkspaceDiagnosticResponse",
    "PipelineWorkspaceFailureResponse",
    "PipelineWorkspaceImplementationResponse",
    "PipelineWorkspaceInputOptionResponse",
    "PipelineWorkspaceProgressResponse",
    "PipelineWorkspaceReferenceResponse",
    "PipelineWorkspaceResponse",
    "PipelineWorkspaceRunResponse",
    "PipelineWorkspaceStageResponse",
    "PipelineWorkspaceVideoResponse",
    "router",
]
