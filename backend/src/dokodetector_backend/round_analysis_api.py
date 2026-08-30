"""HTTP routes for queued round analyses."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import ValidationError

from dokodetector_backend.errors import ContractError
from dokodetector_backend.repository import RoundAnalysisConflict, RoundAnalysisNotFound
from dokodetector_backend.round_analysis_contract import (
    RoundAnalysisCreateRequest,
    RoundAnalysisStatus,
    canonical_analysis_request_bytes,
    canonical_analysis_request_sha256,
)
from dokodetector_backend.round_analysis_service import (
    RoundAnalysisService,
    RoundAnalysisValidationError,
)

router = APIRouter()


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

    if created.created and request.app.state.run_round_analysis_synchronously:
        service.run_synchronously(payload.analysis_id)
    elif created.created:
        service.enqueue(payload.analysis_id)
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


__all__ = ["router"]
