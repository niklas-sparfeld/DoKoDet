"""HTTP routes for recording-wide calibration refinement previews."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import Field

from dokodetector_backend.calibration_refinement_service import (
    CalibrationRefinementConflict,
    CalibrationRefinementInputError,
    CalibrationRefinementNotFound,
)
from dokodetector_backend.contract import ContractModel
from dokodetector_backend.errors import ContractError
from dokodetector_backend.pipeline_api_contracts import validate_recording_id

router = APIRouter()
BASE = "/api/recordings/{recording_id}/pipeline/calibration-refinement"
CALIBRATION_BASE = "/api/recordings/{recording_id}/pipeline/calibrations/{calibration_revision_id}"


class TablePlaneCalibrationResponse(ContractModel):
    """One exact immutable published table-plane calibration."""

    schema_version: Literal["table-plane-calibration/v1"]
    calibration_revision_id: str
    recording_id: str
    source_revision: str
    frame_width: int = Field(gt=0)
    frame_height: int = Field(gt=0)
    image_to_table: list[list[float]]
    table_to_image: list[list[float]]
    card_short_size: float = Field(gt=0)
    card_long_size: float = Field(gt=0)
    card_aspect_ratio: float = Field(gt=0)
    candidate_receipt_digests: list[str]
    algorithm_version: str
    coordinate_system: str
    corner_order: str
    angle_convention: str
    diagnostics: dict[str, Any]
    calibration_digest: str


def _service(request: Request) -> Any:
    return request.app.state.calibration_refinement_service


@router.get(CALIBRATION_BASE, response_model=TablePlaneCalibrationResponse)
def get_published_calibration(
    recording_id: str, calibration_revision_id: str, request: Request
) -> dict[str, Any]:
    """Read one exact published calibration without selecting or changing it."""

    validate_recording_id(recording_id)
    try:
        return _service(request).read_published_calibration(recording_id, calibration_revision_id)
    except CalibrationRefinementNotFound as error:
        raise ContractError(
            "calibration_revision_not_found", str(error), status_code=404
        ) from error
    except CalibrationRefinementInputError as error:
        raise ContractError("invalid_calibration_revision", str(error), status_code=422) from error


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
    """Return the current draft without starting a calibration preview."""

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
    """Apply one ordered anchor command without starting a calibration preview."""

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
    except CalibrationRefinementInputError as error:
        raise ContractError(
            "invalid_calibration_refinement", str(error), status_code=422
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
