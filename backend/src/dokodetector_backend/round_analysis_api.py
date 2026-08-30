"""HTTP routes for queued round analyses."""

from __future__ import annotations

import logging
import re
from uuid import UUID

from doko_operations.round_reconstruction import RoundReconstructionContractError
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from dokodetector_backend.errors import ContractError
from dokodetector_backend.logging_config import get_or_create_request_id, log_event
from dokodetector_backend.repository import (
    RoundAnalysisConflict,
    RoundAnalysisNotFound,
    StoredRoundAnalysis,
)
from dokodetector_backend.round_analysis_contract import (
    CounterfactualArtifact,
    RoundAnalysisCreateRequest,
    RoundAnalysisStatus,
    RoundCounterfactualArtifacts,
    RoundCounterfactualCreateRequest,
    RoundCounterfactualResponse,
    canonical_analysis_request_bytes,
    canonical_analysis_request_sha256,
)
from dokodetector_backend.round_analysis_service import (
    RoundAnalysisService,
    RoundAnalysisValidationError,
    RoundCounterfactualConflict,
    RoundCounterfactualIntegrityError,
    RoundCounterfactualNotFound,
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


@router.post(
    "/v1/round-analyses/{analysis_id}/counterfactuals",
    response_model=RoundCounterfactualResponse,
    status_code=201,
)
def create_round_counterfactual(
    analysis_id: str,
    payload: RoundCounterfactualCreateRequest,
    request: Request,
) -> RoundCounterfactualResponse:
    """Synchronously create or reuse one immutable counterfactual."""

    parsed_analysis_id = _parse_analysis_id(analysis_id)
    try:
        shared_request = payload.to_shared()
    except (RoundReconstructionContractError, TypeError, ValueError) as error:
        raise ContractError(
            "invalid_counterfactual_request",
            "The counterfactual request is invalid.",
        ) from error
    service: RoundAnalysisService = request.app.state.round_analysis_service
    try:
        stored = service.create_counterfactual(parsed_analysis_id, shared_request)
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
    except RoundCounterfactualConflict as error:
        raise ContractError(
            "counterfactual_conflict",
            str(error),
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
    except (RoundReconstructionContractError, TypeError, ValueError) as error:
        raise ContractError(
            "invalid_counterfactual_request",
            "The counterfactual request is invalid.",
        ) from error
    except OSError as error:
        raise ContractError(
            "internal_error",
            "The counterfactual could not be published.",
            status_code=500,
        ) from error
    return _counterfactual_response(stored)


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

    service: RoundAnalysisService = request.app.state.round_analysis_service
    existing = service.repository.get(payload.analysis_id)
    if existing is not None:
        if existing.request_sha256 != canonical_analysis_request_sha256(
            payload
        ) or existing.request_json != canonical_analysis_request_bytes(payload).decode("utf-8"):
            raise ContractError(
                "analysis_conflict",
                "The analysis ID is already stored with different request content.",
                status_code=409,
            )
        return service.status(payload.analysis_id)
    try:
        service.validate_request(payload)
        created = service.repository.create(payload)
    except RoundAnalysisValidationError as error:
        raise ContractError("invalid_analysis_request", str(error), status_code=422) from error
    except RoundAnalysisConflict as error:
        raise ContractError(
            "analysis_conflict",
            str(error),
            status_code=409,
        ) from error

    request_id = get_or_create_request_id(request)
    if created.created:
        _log_round_analysis_created(request_id, created.analysis)

    if created.created and request.app.state.run_round_analysis_synchronously:
        service.run_synchronously(payload.analysis_id, request_id)
    elif created.created:
        service.enqueue(payload.analysis_id, request_id)
    return service.status(payload.analysis_id)


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
        return service.status(parsed_id)
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


def _log_round_analysis_created(request_id: str, analysis: StoredRoundAnalysis) -> None:
    """Log the durable queued state without logging the immutable request body."""

    log_event(
        LOGGER,
        logging.INFO,
        "round_analysis_created",
        request_id=request_id,
        analysis_id=str(analysis.analysis_id),
        recording_id=analysis.recording_id,
        round_id=analysis.round_id,
        session_id=str(analysis.session_id),
        state=analysis.state,
        total_evidence_packages=analysis.total_evidence_packages,
    )


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
