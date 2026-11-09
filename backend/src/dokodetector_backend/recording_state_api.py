"""HTTP routes for recording-owned current-state snapshots."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import Field

from dokodetector_backend.contract import ContractModel
from dokodetector_backend.errors import ContractError
from dokodetector_backend.recording_state_contract import (
    RecordingHeadUpdate,
    RecordingStateSnapshot,
)
from dokodetector_backend.recording_state_store import (
    RecordingHeadConflict,
    RecordingHeadNotFound,
    RecordingSnapshotCorrupt,
    RecordingSnapshotNotFound,
)

router = APIRouter(prefix="/api/recordings/{recording_id}/state")


class RecordingStateWorkingEditRequest(ContractModel):
    expected_head_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1)
    actor: dict[str, Any]
    content: dict[str, Any]


def _execute(operation):
    try:
        return operation()
    except RecordingHeadConflict as error:
        raise ContractError("recording_state_conflict", str(error), status_code=409) from error
    except RecordingHeadNotFound as error:
        raise ContractError(
            "recording_state_not_initialized", str(error), status_code=404
        ) from error
    except RecordingSnapshotNotFound as error:
        raise ContractError("recording_snapshot_missing", str(error), status_code=404) from error
    except (RecordingSnapshotCorrupt, ValueError, OSError) as error:
        raise ContractError("recording_state_corrupt", str(error), status_code=422) from error


@router.post("")
def initialize_recording_state(
    recording_id: str, snapshot: RecordingStateSnapshot, request: Request
) -> dict:
    """Persist and select the first immutable snapshot for a recording."""

    if snapshot.recording_id != recording_id:
        raise ContractError(
            "recording_state_conflict", "recording identity mismatch", status_code=409
        )

    def initialize():
        store = request.app.state.recording_state_store
        stored = store.put(snapshot)
        return store.initialize(recording_id, stored.snapshot.snapshot_id)

    return _execute(lambda: _published_mapping(initialize()))


@router.get("")
def get_recording_state(recording_id: str, request: Request) -> dict:
    """Return HEAD and its verified selected snapshot."""

    return _execute(
        lambda: _published_mapping(
            request.app.state.recording_state_store.get_current(recording_id)
        )
    )


@router.put("")
def update_recording_state(
    recording_id: str, update: RecordingHeadUpdate, request: Request
) -> dict:
    """Select or restore an exact snapshot with HEAD compare-and-swap."""

    if update.recording_id != recording_id:
        raise ContractError(
            "recording_state_conflict", "recording identity mismatch", status_code=409
        )

    return _execute(
        lambda: _published_mapping(request.app.state.recording_state_store.publish(update))
    )


@router.put("/events/working-content")
def edit_selected_event_content(
    recording_id: str, body: RecordingStateWorkingEditRequest, request: Request
) -> dict:
    """Edit selected event work and publish its replacement as the current snapshot."""

    return _execute(
        lambda: request.app.state.recording_state_working_editor.edit_events(
            recording_id,
            body.expected_head_version,
            body.idempotency_key,
            body.actor,
            body.content,
        )
    )


@router.get("/snapshots/{snapshot_id}")
def get_recording_snapshot(recording_id: str, snapshot_id: str, request: Request) -> dict:
    """Read one exact immutable snapshot without discovering history."""

    return _execute(
        lambda: request.app.state.recording_state_store.get(
            recording_id, snapshot_id
        ).snapshot.model_dump(mode="json")
    )


def _published_mapping(state) -> dict:
    return {
        "head": state.head.model_dump(mode="json"),
        "snapshot": state.snapshot.model_dump(mode="json"),
        "summary": state.summary.model_dump(mode="json"),
    }
