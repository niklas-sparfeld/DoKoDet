"""HTTP routes for recording-wide calibration refinement previews."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from dokodetector_backend.calibration_refinement_service import (
    CalibrationRefinementConflict,
    CalibrationRefinementInputError,
    CalibrationRefinementNotFound,
)
from dokodetector_backend.errors import ContractError
from dokodetector_backend.pipeline_api_contracts import validate_recording_id

router = APIRouter()
BASE = "/api/recordings/{recording_id}/pipeline/calibration-refinement"


def _service(request: Request) -> Any:
    return request.app.state.calibration_refinement_service


@router.post(BASE, status_code=201)
def start_calibration_refinement(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Create or reload the mutable calibration draft for one proposal revision."""

    validate_recording_id(recording_id)
    try:
        return _service(request).start(recording_id, payload)
    except CalibrationRefinementInputError as error:
        raise ContractError(
            "invalid_calibration_refinement", str(error), status_code=422
        ) from error


@router.get(BASE)
def get_calibration_refinement(
    recording_id: str, proposal_revision_id: str, request: Request, draft_id: str | None = None
) -> dict[str, Any]:
    """Return the current draft and its deterministic preview."""

    validate_recording_id(recording_id)
    try:
        return _service(request).get(recording_id, proposal_revision_id, draft_id)
    except CalibrationRefinementNotFound as error:
        raise ContractError(
            "calibration_refinement_not_found", str(error), status_code=404
        ) from error
    except CalibrationRefinementInputError as error:
        raise ContractError(
            "invalid_calibration_refinement", str(error), status_code=422
        ) from error


@router.put(BASE)
def update_calibration_refinement(
    recording_id: str,
    proposal_revision_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """Apply one ordered anchor command and return the new preview."""

    validate_recording_id(recording_id)
    try:
        return _service(request).update(recording_id, proposal_revision_id, payload)
    except CalibrationRefinementInputError as error:
        raise ContractError(
            "invalid_calibration_refinement", str(error), status_code=422
        ) from error


@router.post(BASE + "/discard")
def discard_calibration_refinement(
    recording_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    """Discard all preview commands and restore the clean draft value."""

    validate_recording_id(recording_id)
    proposal_revision_id = payload.get("proposal_revision_id")
    draft_id = payload.get("draft_id")
    if not isinstance(proposal_revision_id, str) or not isinstance(draft_id, str):
        raise ContractError(
            "invalid_calibration_refinement",
            "proposal_revision_id and draft_id are required",
            status_code=422,
        )
    try:
        return _service(request).discard(recording_id, proposal_revision_id, draft_id)
    except CalibrationRefinementNotFound as error:
        raise ContractError(
            "calibration_refinement_not_found", str(error), status_code=404
        ) from error


@router.post(BASE + "/apply")
def apply_calibration_refinement(
    recording_id: str,
    proposal_revision_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """Publish one calibration revision and reflow the maintained visible-card draft."""

    validate_recording_id(recording_id)
    try:
        return _service(request).apply(recording_id, proposal_revision_id, payload)
    except CalibrationRefinementConflict as error:
        raise ContractError(
            "calibration_refinement_conflict", str(error), status_code=409
        ) from error
    except CalibrationRefinementInputError as error:
        raise ContractError(
            "invalid_calibration_refinement", str(error), status_code=422
        ) from error


__all__ = ["router"]
