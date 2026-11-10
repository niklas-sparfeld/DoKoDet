"""HTTP API for concrete event-set resources."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import Field

from dokodetector_backend.contract import ContractModel
from dokodetector_backend.errors import ContractError
from dokodetector_backend.event_set_store import EventSetError
from dokodetector_backend.recording_folder_store import RecordingVersionConflict

router = APIRouter(prefix="/api/recordings/{recording_id}/event-sets")


class EventSetSaveRequest(ContractModel):
    set_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content: dict[str, Any]
    origin: str = "manual"
    provenance: dict[str, Any] = Field(default_factory=dict)


class EventSetSelectionRequest(ContractModel):
    choice: str
    reference: dict[str, str] | None
    expected_recording_version: int = Field(ge=1)


@router.get("")
def list_event_sets(recording_id: str, request: Request):
    store = request.app.state.event_set_store
    root = store.recordings.get(recording_id)
    if root is None:
        raise ContractError("recording_not_found", "The recording was not found.", status_code=404)
    results = []
    base = store.recordings.recording_path(recording_id) / "event-sets"
    if base.exists() and not base.is_symlink():
        for set_path in sorted(base.iterdir(), key=lambda item: item.name):
            versions_path = set_path / "versions"
            if set_path.is_symlink() or not versions_path.is_dir() or versions_path.is_symlink():
                continue
            for version_path in sorted(versions_path.iterdir(), key=lambda item: item.name):
                if version_path.is_symlink() or not version_path.is_dir():
                    continue
                item = store.get(recording_id, set_path.name, version_path.name)
                if item is not None:
                    results.append(
                        {
                            key: item[key]
                            for key in (
                                "set_id",
                                "version",
                                "events",
                                "source",
                                "provenance",
                                "created_at",
                                "origin",
                            )
                        }
                    )
    return {
        "recording_id": recording_id,
        "recording_version": root.version,
        "head": root.head.get("events", {}),
        "event_sets": results,
    }


@router.post("")
def save_event_set(recording_id: str, body: EventSetSaveRequest, request: Request):
    try:
        return request.app.state.event_set_store.save(
            recording_id,
            set_id=body.set_id,
            version=body.version,
            content=body.content,
            origin=body.origin,
            provenance=body.provenance,
        )
    except (EventSetError, ValueError, OSError) as error:
        raise ContractError("event_set_invalid", str(error), status_code=422) from error


@router.get("/{set_id}/versions/{version}")
def get_event_set(recording_id: str, set_id: str, version: str, request: Request):
    result = request.app.state.event_set_store.get(recording_id, set_id, version)
    if result is None:
        raise ContractError(
            "event_set_not_found",
            "The event-set version was not found.",
            status_code=404,
        )
    return result


@router.put("/selection")
def select_event_set(recording_id: str, body: EventSetSelectionRequest, request: Request):
    try:
        return request.app.state.event_set_store.select(
            recording_id,
            choice=body.choice,
            reference=body.reference,
            expected_version=body.expected_recording_version,
        )
    except RecordingVersionConflict as error:
        raise ContractError("event_set_selection_conflict", str(error), status_code=409) from error
    except (EventSetError, ValueError, OSError) as error:
        raise ContractError("event_set_selection_invalid", str(error), status_code=422) from error
