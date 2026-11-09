"""HTTP routes for recording-owned current-state snapshots."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import Field

from dokodetector_backend.contract import ContractModel
from dokodetector_backend.errors import ContractError
from dokodetector_backend.recording_history_store import (
    RecordingHistoryCorrupt,
    RecordingHistoryCursorExpired,
)
from dokodetector_backend.recording_state_contract import (
    HistoryPageCursor,
    RecordingHeadUpdate,
    RecordingHistoryPage,
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


@router.get("/history/{collection}")
def get_recording_history_page(
    recording_id: str,
    request: Request,
    collection: Literal["snapshots", "revisions", "candidates", "lineage_edges"],
    cursor: str | None = None,
    page_size: int = Query(default=50, ge=1, le=100),
) -> RecordingHistoryPage:
    """Return a stable metadata page from the derived history index."""
    filters = {"recording_id": recording_id, "collection": collection}
    filter_digest = hashlib.sha256(
        json.dumps(filters, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    decoded: HistoryPageCursor | None = None
    if cursor is not None:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            decoded = HistoryPageCursor.model_validate_json(raw)
            if (
                decoded.recording_id != recording_id
                or decoded.collection != collection
                or decoded.filter_sha256 != filter_digest
                or decoded.page_size != page_size
                or decoded.last_key is None
                or not decoded.last_key.isdecimal()
            ):
                raise ValueError("history cursor does not match this request")
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise ContractError(
                "recording_cursor_invalid", "The history cursor is invalid."
            ) from error
    try:
        authority, items, has_more = request.app.state.recording_history_store.page(
            recording_id,
            collection,
            upper_bound_sequence=(None if decoded is None else decoded.upper_bound_sequence),
            history_generation=(None if decoded is None else decoded.history_generation),
            after_sequence=(0 if decoded is None else int(decoded.last_key)),
            limit=page_size,
        )
    except RecordingHistoryCursorExpired as error:
        raise ContractError("recording_cursor_expired", str(error), status_code=410) from error
    except (RecordingHistoryCorrupt, ValueError, OSError) as error:
        raise ContractError("recording_state_corrupt", str(error), status_code=422) from error

    next_cursor = None
    if has_more and items:
        next_request = HistoryPageCursor(
            recording_id=recording_id,
            collection=collection,
            filter_sha256=filter_digest,
            upper_bound_sequence=(
                authority.sequence if decoded is None else decoded.upper_bound_sequence
            ),
            history_generation=authority.generation,
            last_key=str(items[-1].publication_sequence),
            page_size=page_size,
        )
        next_cursor = (
            base64.urlsafe_b64encode(next_request.model_dump_json().encode()).decode().rstrip("=")
        )
    return RecordingHistoryPage(
        recording_id=recording_id,
        collection=collection,
        upper_bound_sequence=(
            authority.sequence if decoded is None else decoded.upper_bound_sequence
        ),
        items=items,
        has_more=has_more,
        next_cursor=next_cursor,
    )


def _published_mapping(state) -> dict:
    return {
        "head": state.head.model_dump(mode="json"),
        "snapshot": state.snapshot.model_dump(mode="json"),
        "summary": state.summary.model_dump(mode="json"),
    }
