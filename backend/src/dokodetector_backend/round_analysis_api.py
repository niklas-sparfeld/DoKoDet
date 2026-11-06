"""HTTP routes for queued round analyses."""

from __future__ import annotations

import logging
import re
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from dokodetector_backend.errors import ContractError
from dokodetector_backend.job_store import JobConflict, JobOwnershipError
from dokodetector_backend.logging_config import log_event
from dokodetector_backend.round_analysis_contract import (
    CounterfactualArtifact,
    RoundAnalysisCreateRequest,
    RoundAnalysisStatus,
    RoundCounterfactualArtifacts,
    RoundCounterfactualCreateRequest,
    RoundCounterfactualResponse,
)
from dokodetector_backend.round_analysis_service import (
    RoundAnalysisService,
    RoundAnalysisValidationError,
    RoundCounterfactualIntegrityError,
    RoundCounterfactualNotFound,
)
from dokodetector_backend.round_analysis_store import (
    RoundAnalysisConflict,
    RoundAnalysisNotFound,
)
from dokodetector_backend.round_analysis_timeline import (
    FRAME_PART_PATTERN,
    RoundAnalysisNotCompleteError,
    RoundAnalysisTimeline,
    RoundAnalysisTimelineError,
    TimelineFrameNotFound,
)

router = APIRouter()
LOGGER = logging.getLogger(__name__)


@router.get(
    "/v1/round-analyses/{analysis_id}/counterfactuals/{counterfactual_id}",
    response_model=RoundCounterfactualResponse,
)
def get_round_counterfactual(
    analysis_id: str,
    counterfactual_id: str,
    request: Request,
) -> RoundCounterfactualResponse:
    """Return one immutable counterfactual from its runtime artifacts."""

    parsed_analysis_id = _parse_analysis_id(analysis_id)
    parsed_counterfactual_id = _parse_counterfactual_id(counterfactual_id)
    service: RoundAnalysisService = request.app.state.round_analysis_service
    try:
        stored = service.get_counterfactual(parsed_analysis_id, parsed_counterfactual_id)
    except RoundAnalysisNotFound as error:
        raise ContractError(
            "analysis_not_found",
            "The round analysis was not found.",
            status_code=404,
        ) from error
    except RoundCounterfactualNotFound as error:
        raise ContractError(
            "counterfactual_not_found",
            "The counterfactual was not found.",
            status_code=404,
        ) from error
    except RoundAnalysisNotCompleteError as error:
        raise ContractError(
            "analysis_not_complete",
            "The round analysis is not complete.",
            status_code=409,
        ) from error
    except RoundCounterfactualIntegrityError as error:
        raise ContractError(
            "counterfactual_integrity_error",
            "The stored counterfactual failed integrity validation.",
            status_code=500,
        ) from error
    except RoundAnalysisTimelineError as error:
        raise ContractError(
            "analysis_integrity_error",
            "The stored round analysis failed integrity validation.",
            status_code=500,
        ) from error
    return _counterfactual_response(stored)


@router.post(
    "/v1/round-analyses",
    response_model=RoundAnalysisStatus,
    status_code=202,
)
async def create_round_analysis(
    payload: RoundAnalysisCreateRequest,
    request: Request,
) -> RoundAnalysisStatus:
    """Validate and queue one analysis request."""

    return await _queue_round_analysis(payload, request)


async def _queue_round_analysis(
    payload: RoundAnalysisCreateRequest,
    request: Request,
) -> RoundAnalysisStatus:
    """Validate and queue one analysis request from any API entry point."""

    service: RoundAnalysisService = request.app.state.round_analysis_service
    request_id = request.headers.get("X-DokoDetector-Request-ID") or str(payload.analysis_id)
    try:
        service.validate_request(payload)
        raw_request = {
            "type": "round_analysis",
            "context": {"recording_id": payload.recording_id},
            "request": payload.model_dump(mode="json"),
        }
        log_event(
            LOGGER,
            logging.INFO,
            "round_analysis_created",
            request_id=request_id,
            analysis_id=str(payload.analysis_id),
            recording_id=payload.recording_id,
            round_id=payload.round_id,
            session_id=payload.session_id,
            state="queued",
            total_evidence_packages=len(payload.evidence_package_ids),
        )
        job_service = request.app.state.job_manager_service
        if request.app.state.run_round_analysis_synchronously:
            job = job_service.run_inline(
                str(payload.analysis_id), raw_request, correlation_id=request_id
            )
        else:
            job = job_service.get_manager().accept(
                str(payload.analysis_id), raw_request, correlation_id=request_id
            )
    except RoundAnalysisValidationError as error:
        raise ContractError("invalid_analysis_request", str(error), status_code=422) from error
    except (RoundAnalysisConflict, JobConflict) as error:
        raise ContractError(
            "analysis_conflict",
            str(error),
            status_code=409,
        ) from error
    except (OSError, TypeError, ValueError) as error:
        raise ContractError(
            "analysis_input_error",
            "The analysis inputs could not be accepted.",
            status_code=500,
        ) from error
    try:
        return service.status(UUID(job.request["analysis_id"])).model_copy(
            update={"job_id": job.id}
        )
    except (RoundAnalysisNotFound, KeyError, TypeError, ValueError) as error:
        raise ContractError(
            "analysis_not_found", "The round analysis was not found.", status_code=500
        ) from error


@router.get(
    "/v1/round-analyses/{analysis_id}",
    response_model=RoundAnalysisStatus,
)
def get_round_analysis(analysis_id: str, request: Request) -> RoundAnalysisStatus:
    """Return one durable analysis status document."""

    try:
        parsed_id = UUID(analysis_id)
    except (AttributeError, TypeError, ValueError) as error:
        raise ContractError(
            "invalid_analysis_id",
            "The analysis ID is not a valid UUID.",
        ) from error
    service: RoundAnalysisService = request.app.state.round_analysis_service
    try:
        status = service.status(parsed_id)
        try:
            manager = request.app.state.job_manager_service.get_manager()
        except JobOwnershipError:
            job_id = None
        else:
            job_id = next(
                (
                    job.id
                    for job in manager.list_jobs()
                    if job.type == "round_analysis"
                    and job.request.get("analysis_id") == str(parsed_id)
                ),
                None,
            )
        return status.model_copy(update={"job_id": job_id})
    except RoundAnalysisNotFound as error:
        raise ContractError(
            "analysis_not_found",
            "The round analysis was not found.",
            status_code=404,
        ) from error
    except (ValidationError, RuntimeError, ValueError) as error:
        raise ContractError(
            "internal_error",
            "The stored round analysis result is invalid.",
            status_code=500,
        ) from error


@router.get(
    "/v1/round-analyses/{analysis_id}/timeline",
    response_model=RoundAnalysisTimeline,
)
def get_round_analysis_timeline(analysis_id: str, request: Request) -> RoundAnalysisTimeline:
    """Return the verified immutable timeline for one completed analysis."""

    parsed_id = _parse_analysis_id(analysis_id)
    service: RoundAnalysisService = request.app.state.round_analysis_service
    try:
        return service.timeline(parsed_id)
    except RoundAnalysisNotFound as error:
        raise ContractError(
            "analysis_not_found",
            "The round analysis was not found.",
            status_code=404,
        ) from error
    except RoundAnalysisNotCompleteError as error:
        raise ContractError(
            "analysis_not_complete",
            "The round analysis is not complete.",
            status_code=409,
        ) from error
    except (RoundAnalysisTimelineError, ValidationError, ValueError) as error:
        raise ContractError(
            "analysis_integrity_error",
            "The stored round analysis failed integrity validation.",
            status_code=500,
        ) from error


@router.get(
    "/v1/round-analyses/{analysis_id}/evidence-packages/{package_id}/frames/{part_name}",
    response_model=None,
)
def get_round_analysis_frame(
    analysis_id: str,
    package_id: str,
    part_name: str,
    request: Request,
) -> FileResponse:
    """Return one validated JPEG frame scoped to a completed analysis."""

    parsed_analysis_id = _parse_analysis_id(analysis_id)
    parsed_package_id = _parse_package_id(package_id)
    if re.fullmatch(FRAME_PART_PATTERN, part_name) is None or len(part_name) > 64:
        raise ContractError(
            "invalid_frame_part",
            "The frame part name is invalid.",
        )
    service: RoundAnalysisService = request.app.state.round_analysis_service
    try:
        frame = service.frame(parsed_analysis_id, parsed_package_id, part_name)
    except RoundAnalysisNotFound as error:
        raise ContractError(
            "analysis_not_found",
            "The round analysis was not found.",
            status_code=404,
        ) from error
    except TimelineFrameNotFound as error:
        raise ContractError(
            "frame_not_found",
            "The frame was not found for this analysis.",
            status_code=404,
        ) from error
    except RoundAnalysisNotCompleteError as error:
        raise ContractError(
            "analysis_not_complete",
            "The round analysis is not complete.",
            status_code=409,
        ) from error
    except (RoundAnalysisTimelineError, ValidationError, ValueError) as error:
        raise ContractError(
            "analysis_integrity_error",
            "The stored round analysis failed integrity validation.",
            status_code=500,
        ) from error
    return FileResponse(
        frame.path,
        media_type="image/jpeg",
        headers={
            "ETag": f'"{frame.sha256}"',
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


def _parse_analysis_id(value: str) -> UUID:
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ContractError(
            "invalid_analysis_id",
            "The analysis ID is not a valid UUID.",
        ) from error


def _parse_package_id(value: str) -> UUID:
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ContractError(
            "invalid_package_id",
            "The package ID is not a valid UUID.",
        ) from error


def _parse_counterfactual_id(value: str) -> UUID:
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ContractError(
            "invalid_counterfactual_id",
            "The counterfactual ID is not a valid UUID.",
        ) from error


def _counterfactual_response(stored) -> RoundCounterfactualResponse:
    """Convert one service result to the strict public response contract."""

    request = RoundCounterfactualCreateRequest.model_validate(stored.request.to_mapping())

    def artifact(value) -> CounterfactualArtifact:
        return CounterfactualArtifact(
            relative_path=value.relative_path,
            byte_length=value.byte_length,
            sha256=value.sha256,
        )

    return RoundCounterfactualResponse(
        counterfactual_id=stored.request.counterfactual_id,
        source_analysis_id=stored.request.source_analysis_id,
        request=request,
        artifacts=RoundCounterfactualArtifacts(
            request=artifact(stored.artifacts.request),
            input=artifact(stored.artifacts.input),
            result=artifact(stored.artifacts.result),
        ),
        result=stored.result.to_mapping(),
    )


__all__ = ["router"]
