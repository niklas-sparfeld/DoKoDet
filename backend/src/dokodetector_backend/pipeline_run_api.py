"""HTTP boundary for preflighted automated recording runs."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import Field

from dokodetector_backend.automated_pipeline_run import (
    PIPELINE_STAGE_NAMES,
    AutomatedPipelinePreflightError,
    AutomatedPipelineRunConflict,
    AutomatedPipelineRunNotFound,
)
from dokodetector_backend.contract import ContractModel
from dokodetector_backend.errors import APIErrorDetail, ContractError
from dokodetector_backend.pipeline_api_contracts import validate_recording_id
from dokodetector_backend.round_analysis_contract import AnalysisSearchLimits

router = APIRouter()
BASE = "/api/recordings/{recording_id}/pipeline/runs"


class AutomatedPipelineRunStartRequest(ContractModel):
    """Exact round context and stage settings needed before acceptance."""

    idempotency_key: UUID
    session_id: str
    round_context: dict[str, Any]
    rules_version: Literal["v1"]
    search: AnalysisSearchLimits
    stage_requests: dict[str, dict[str, Any]]


class AutomatedPipelineRunStageResponse(ContractModel):
    """Persisted state for one stage in the overall run."""

    name: Literal[
        "event_proposals",
        "visible_card_and_pile_proposals",
        "card_scene_and_calibration",
        "visual_identity_proposals",
        "table_observations",
        "reconstruction",
    ]
    status: Literal["pending", "queued", "running", "complete", "partial", "failed"]
    run_id: str | None = None
    child_job_id: str | None = None
    input_revision_ids: list[str] = Field(default_factory=list)
    output_revision_ids: list[str] = Field(default_factory=list)
    failure: dict[str, Any] | None = None


class AutomatedPipelineRunResponse(ContractModel):
    """Overall run record returned by start and status routes."""

    schema_version: Literal["automated-pipeline-run/v1"]
    run_id: str
    job_id: str | None = None
    recording_id: str
    status: Literal["accepted", "queued", "running", "complete", "failed", "cancelled"]
    created_at: str
    updated_at: str
    source: dict[str, Any]
    request_sha256: str
    client_request_sha256: str
    request: dict[str, Any]
    resolved_providers: dict[str, Any]
    failure: dict[str, Any] | None
    stages: list[AutomatedPipelineRunStageResponse] = Field(
        min_length=len(PIPELINE_STAGE_NAMES), max_length=len(PIPELINE_STAGE_NAMES)
    )


@router.post(BASE, response_model=AutomatedPipelineRunResponse, status_code=202)
def start_automated_pipeline_run(
    recording_id: str,
    payload: AutomatedPipelineRunStartRequest,
    request: Request,
    response: Response,
) -> AutomatedPipelineRunResponse:
    """Validate and freeze a complete pipeline request before accepting it."""

    validate_recording_id(recording_id)
    service = request.app.state.automated_pipeline_run_service
    try:
        document, idempotent = service.start(
            recording_id,
            payload.model_dump(mode="json"),
        )
    except AutomatedPipelinePreflightError as error:
        raise ContractError(
            "pipeline_preflight_failed",
            "The pipeline run cannot start until its prerequisites are fixed.",
            status_code=422,
            details=[
                APIErrorDetail(field="preflight", message=blocker) for blocker in error.blockers
            ],
        ) from error
    except AutomatedPipelineRunConflict as error:
        message = str(error)
        if error.active_run_id:
            message = f"{message} Active run: {error.active_run_id}."
        raise ContractError("pipeline_run_conflict", message, status_code=409) from error
    job_request = {
        "type": "automated_pipeline",
        "context": {"recording_id": recording_id},
        "request": {"run_id": str(document["run_id"])},
    }
    try:
        job = request.app.state.job_manager_service.get_manager().accept(
            str(document["request"]["idempotency_key"]), job_request
        )
    except Exception as error:
        from dokodetector_backend.job_store import JobOwnershipError

        if not isinstance(error, JobOwnershipError):
            raise
        job = request.app.state.job_manager_service.run_inline(
            str(document["request"]["idempotency_key"]), job_request
        )
    if document.get("job_id") != job.id:
        document = request.app.state.automated_pipeline_run_service.store.update(
            str(document["run_id"]), lambda current: current.update({"job_id": job.id})
        )
    response.status_code = 200 if idempotent else 202
    return AutomatedPipelineRunResponse.model_validate(document)


@router.get(BASE + "/{run_id}", response_model=AutomatedPipelineRunResponse)
def get_automated_pipeline_run(
    recording_id: str,
    run_id: str,
    request: Request,
) -> AutomatedPipelineRunResponse:
    """Read one durable run record without contacting a stage worker."""

    validate_recording_id(recording_id)
    try:
        document = request.app.state.automated_pipeline_run_service.read(run_id)
    except AutomatedPipelineRunNotFound as error:
        raise ContractError("pipeline_run_not_found", str(error), status_code=404) from error
    if document.get("recording_id") != recording_id:
        raise ContractError(
            "pipeline_run_not_found", "The pipeline run was not found.", status_code=404
        )
    return AutomatedPipelineRunResponse.model_validate(document)


__all__ = ["AutomatedPipelineRunResponse", "AutomatedPipelineRunStartRequest", "router"]
