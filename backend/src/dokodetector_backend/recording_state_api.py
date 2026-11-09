"""HTTP routes for recording-owned current-state snapshots."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import Field, TypeAdapter, ValidationError

from dokodetector_backend.contract import ContractModel
from dokodetector_backend.errors import ContractError
from dokodetector_backend.recording_history_order_index import stable_history_key
from dokodetector_backend.recording_history_store import (
    RecordingHistoryCorrupt,
    RecordingHistoryCursorExpired,
)
from dokodetector_backend.recording_state_contract import (
    HistoryPageCursor,
    Identifier,
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

_HISTORY_FILTER_SHA256 = hashlib.sha256(b"{}").hexdigest()
_IDENTIFIER_ADAPTER = TypeAdapter(Identifier)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _encode_history_cursor(cursor: HistoryPageCursor, key: bytes) -> str:
    payload = _canonical_json(cursor.model_dump(mode="json"))
    signature = hmac.new(key, payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(signature)}"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_history_cursor(token: str, key: bytes) -> HistoryPageCursor:
    try:
        payload_text, signature_text = token.split(".", 1)
        payload = base64.urlsafe_b64decode(payload_text + "=" * (-len(payload_text) % 4))
        signature = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
        expected = hmac.new(key, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("cursor signature mismatch")
        value = json.loads(payload)
        if not isinstance(value, dict) or _canonical_json(value) != payload:
            raise ValueError("cursor is not canonical")
        return HistoryPageCursor.model_validate(value)
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError("recording_cursor_invalid", "The history cursor is invalid.") from error


def _history_page(
    recording_id: str, collection: str, request: Request, limit: int, token: str | None
):
    try:
        recording_id = _IDENTIFIER_ADAPTER.validate_python(recording_id)
    except ValidationError as error:
        raise ContractError("invalid_request", "The request failed validation.") from error
    if request.app.state.recording_bundle_store.get_metadata(recording_id) is None:
        raise ContractError("recording_not_found", "The recording was not found.", status_code=404)
    try:
        request.app.state.recording_state_store.reconcile_snapshot_history_outbox(recording_id)
    except (OSError, ValueError) as error:
        raise ContractError(
            "recording_history_corrupt", "The recording history is corrupt.", status_code=500
        ) from error
    store = request.app.state.recording_history_store
    node_edits = getattr(request.app.state, "pipeline_node_edits", None)
    if node_edits is not None:
        try:
            node_edits.store.reconcile_revision_history_outbox()
        except (OSError, ValueError) as error:
            raise ContractError(
                "recording_history_corrupt", "The recording history is corrupt.", status_code=500
            ) from error
    lineage = getattr(request.app.state, "pipeline_lineage_service", None)
    if lineage is not None:
        try:
            lineage.reconcile_history_outbox(recording_id)
        except (OSError, ValueError) as error:
            raise ContractError(
                "recording_history_corrupt", "The recording history is corrupt.", status_code=500
            ) from error
    try:
        key = store.cursor_integrity_key()
    except (RecordingHistoryCorrupt, OSError) as error:
        raise ContractError(
            "recording_history_corrupt", "The recording history is corrupt.", status_code=500
        ) from error
    cursor = _decode_history_cursor(token, key) if token is not None else None
    if cursor is not None and (
        cursor.recording_id != recording_id
        or cursor.collection != collection
        or cursor.filter_sha256 != _HISTORY_FILTER_SHA256
        or cursor.page_size != limit
    ):
        raise ContractError(
            "recording_cursor_invalid", "The history cursor does not match this request."
        )
    after_key = None
    if cursor is None:
        upper_bound = None
        generation = None
    else:
        upper_bound = cursor.upper_bound_sequence
        generation = cursor.history_generation
        if cursor.last_key is not None:
            try:
                decoded_key = json.loads(cursor.last_key)
                if not isinstance(decoded_key, list) or not all(
                    isinstance(part, str) for part in decoded_key
                ):
                    raise ValueError("invalid stable key")
                if _canonical_json(decoded_key).decode() != cursor.last_key:
                    raise ValueError("non-canonical stable key")
                after_key = tuple(decoded_key)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                raise ContractError(
                    "recording_cursor_invalid", "The history cursor is invalid."
                ) from error
    try:
        authority, items, has_more = store.ordered_page(
            recording_id,
            collection,
            upper_bound_sequence=upper_bound,
            history_generation=generation,
            after_key=after_key,
            limit=limit,
        )
    except RecordingHistoryCursorExpired as error:
        raise ContractError(
            "recording_cursor_expired", "The history cursor has expired.", status_code=410
        ) from error
    except (RecordingHistoryCorrupt, OSError, ValueError) as error:
        raise ContractError(
            "recording_history_corrupt", "The recording history is corrupt.", status_code=500
        ) from error
    next_cursor = None
    if has_more:
        next_cursor = _encode_history_cursor(
            HistoryPageCursor(
                recording_id=recording_id,
                collection=collection,
                filter_sha256=_HISTORY_FILTER_SHA256,
                upper_bound_sequence=authority.sequence
                if cursor is None
                else cursor.upper_bound_sequence,
                history_generation=authority.generation,
                last_key=json.dumps(stable_history_key(items[-1]), separators=(",", ":")),
                page_size=limit,
            ),
            key,
        )
    return RecordingHistoryPage(
        recording_id=recording_id,
        collection=collection,
        upper_bound_sequence=authority.sequence if cursor is None else cursor.upper_bound_sequence,
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
    )


def _history_route(collection: str):
    def route(
        recording_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=8192),
    ) -> RecordingHistoryPage:
        return _history_page(recording_id, collection, request, limit, cursor)

    route.__name__ = f"get_{collection}_history"
    return route


for _path, _collection_name in (
    ("/history", "snapshots"),
    ("/revisions", "revisions"),
    ("/candidates", "candidates"),
    ("/lineage-edges", "lineage_edges"),
):
    router.add_api_route(
        _path,
        _history_route(_collection_name),
        methods=["GET"],
        response_model=RecordingHistoryPage,
        name=f"recording_{_collection_name}_history",
    )


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
