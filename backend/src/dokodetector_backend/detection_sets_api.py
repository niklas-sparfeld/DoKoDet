"""HTTP API for concrete immutable detection-set versions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import Field

from dokodetector_backend.contract import ContractModel
from dokodetector_backend.detection_set_store import DetectionSetError
from dokodetector_backend.errors import ContractError

router = APIRouter(prefix="/api/recordings/{recording_id}/detection-sets")


class DetectionSetSaveRequest(ContractModel):
    set_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    origin: str
    source: dict[str, Any]
    producer: dict[str, Any]
    event_sets: list[dict[str, str]] = Field(default_factory=list)
    frames: list[dict[str, Any]]


@router.post("")
def save_detection_set(recording_id: str, body: DetectionSetSaveRequest, request: Request):
    try:
        return request.app.state.detection_set_store.save(
            recording_id,
            set_id=body.set_id,
            version=body.version,
            origin=body.origin,
            source=body.source,
            producer=body.producer,
            event_sets=body.event_sets,
            frames=body.frames,
        )
    except (DetectionSetError, ValueError, TypeError, OSError) as error:
        raise ContractError("detection_set_invalid", str(error), status_code=422) from error


@router.get("/{set_id}/versions/{version}")
def get_detection_set(recording_id: str, set_id: str, version: str, request: Request):
    result = request.app.state.detection_set_store.get(recording_id, set_id, version)
    if result is None:
        raise ContractError(
            "detection_set_not_found",
            "The detection-set version was not found.",
            status_code=404,
        )
    return result
