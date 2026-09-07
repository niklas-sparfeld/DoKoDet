"""HTTP routes for maintained pipeline references."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from dokodetector_backend.errors import APIErrorDetail, ContractError
from dokodetector_backend.pipeline_api_contracts import reference_response, validate_recording_id
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

router = APIRouter()
REFERENCE_BASE = "/api/recordings/{recording_id}/pipeline/references/{content_type}"
REFERENCE_STAGE_BASE = "/api/recordings/{recording_id}/pipeline/{content_type}/reference"


def _reference_service(request: Request) -> Any:
    return request.app.state.pipeline_reference_service


@router.get(REFERENCE_BASE)
@router.get(REFERENCE_STAGE_BASE, include_in_schema=False)
def get_reference(recording_id: str, content_type: str, request: Request) -> dict[str, Any]:
    """Return one maintained reference draft and its current pointer."""

    validate_recording_id(recording_id)
    try:
        reference = _reference_service(request).get_reference(recording_id, content_type)
    except PipelineReferenceNotFound as error:
        raise ContractError("reference_not_found", str(error), status_code=404) from error
    except (PipelineReferenceInputError, PipelineReferenceStoreError) as error:
        raise ContractError("reference_unavailable", str(error), status_code=409) from error
    return reference_response(reference)


@router.post(REFERENCE_BASE, status_code=201)
@router.post(REFERENCE_STAGE_BASE, status_code=201, include_in_schema=False)
def create_reference(
    recording_id: str, content_type: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Create the one recording-owned reference, seeded from a result or empty."""

    validate_recording_id(recording_id)
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
    return reference_response(reference)


@router.put(REFERENCE_BASE + "/draft")
@router.put(REFERENCE_STAGE_BASE + "/draft", include_in_schema=False)
def update_reference_draft(
    recording_id: str, content_type: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Apply conflict-safe review operations to the current reference draft."""

    validate_recording_id(recording_id)
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
    return reference_response(reference)


@router.post(REFERENCE_BASE + "/complete", status_code=201)
@router.post(REFERENCE_STAGE_BASE + "/complete", status_code=201, include_in_schema=False)
def complete_reference(
    recording_id: str, content_type: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Publish the reviewed draft as an immutable completed reference revision."""

    validate_recording_id(recording_id)
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
    return reference_response(reference)


__all__ = ["router"]
