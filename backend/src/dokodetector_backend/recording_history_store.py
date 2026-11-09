"""Durable per-recording sequence authority for metadata-only history entries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter

from dokodetector_backend.filesystem import (
    atomic_replace_json,
    commit_staged_directory,
    contained_path,
    staging_directory,
)
from dokodetector_backend.pipeline_storage import _process_lock
from dokodetector_backend.recording_state_contract import (
    HistoryItem,
    Identifier,
    LineageEdgeHistoryItem,
    RecordingHistoryAuthority,
    ResourceHistoryItem,
    SnapshotHistoryItem,
)

_ITEM_ADAPTER = TypeAdapter(HistoryItem)
_IDENTIFIER_ADAPTER = TypeAdapter(Identifier)


class RecordingHistoryCorrupt(ValueError):
    """History authority or an immutable metadata item failed validation."""


class RecordingHistoryConflict(ValueError):
    """An item key already refers to different immutable metadata."""


class RecordingHistoryCursorExpired(ValueError):
    """A cursor was created against a previous history authority generation."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _collection(item: HistoryItem) -> str:
    if isinstance(item, SnapshotHistoryItem):
        return "snapshots"
    if isinstance(item, LineageEdgeHistoryItem):
        return "lineage_edges"
    if isinstance(item, ResourceHistoryItem):
        return item.collection
    raise TypeError("unsupported recording history item")


def _item_identity(item: HistoryItem) -> tuple[str, str]:
    return _collection(item), item.item_key


def _item_path(generation_root: Path, item: HistoryItem) -> Path:
    collection, key = _item_identity(item)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return contained_path(generation_root, Path("items") / collection / f"{digest}.json")


def _without_sequence(item: HistoryItem) -> dict[str, Any]:
    return item.model_dump(mode="json", exclude={"publication_sequence"})


class RecordingHistoryStore:
    """Publish immutable metadata and its sequence through one recoverable boundary.

    A metadata item becomes visible through this store only after its source payload is durable.
    Writers first record the complete item in a per-recording journal. Readers recover that
    journal under the same process lock before they read the active generation or an item.
    """

    def __init__(self, operations_root: Path | str) -> None:
        self.root = Path(operations_root).expanduser().resolve() / "recording-history"
        self._thread_lock = RLock()

    def _recording_root(self, recording_id: str) -> Path:
        recording_id = _IDENTIFIER_ADAPTER.validate_python(recording_id)
        return contained_path(self.root, recording_id)

    def _lock(self, recording_id: str):
        root = self._recording_root(recording_id)
        return _process_lock(root / ".history.lock", self._thread_lock)

    def _active_generation(self, recording_id: str) -> tuple[str, Path] | None:
        root = self._recording_root(recording_id)
        active_path = contained_path(root, "active.json")
        if not active_path.exists():
            return None
        active = self._read_object(active_path, "active history generation")
        if (
            set(active) != {"schema_version", "recording_id", "generation"}
            or active["schema_version"] != "recording-history-active/v1"
            or active["recording_id"] != recording_id
            or not isinstance(active["generation"], str)
            or not active["generation"].startswith("gen-")
        ):
            raise RecordingHistoryCorrupt("invalid active history generation")
        generation = active["generation"]
        return generation, contained_path(root, Path("generations") / generation)

    @staticmethod
    def _read_object(path: Path, label: str) -> dict[str, Any]:
        try:
            raw = path.read_bytes()
            value = json.loads(raw)
            if not isinstance(value, dict) or _canonical_json(value) != raw:
                raise ValueError("not a canonical JSON object")
            return value
        except (OSError, TypeError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise RecordingHistoryCorrupt(f"invalid {label}: {path}") from error

    def _authority(self, recording_id: str, generation: str, generation_root: Path):
        path = contained_path(generation_root, "authority.json")
        authority = RecordingHistoryAuthority.model_validate(
            self._read_object(path, "history authority")
        )
        if authority.recording_id != recording_id or authority.generation != generation:
            raise RecordingHistoryCorrupt("history authority identity mismatch")
        return authority

    def _ensure_generation(self, recording_id: str) -> tuple[str, Path]:
        current = self._active_generation(recording_id)
        if current is not None:
            self._authority(recording_id, *current)
            return current
        return self._rebuild_locked(recording_id, ())

    def get_authority(self, recording_id: str) -> RecordingHistoryAuthority:
        with self._lock(recording_id):
            self._recover_locked(recording_id)
            generation = self._ensure_generation(recording_id)
            return self._authority(recording_id, *generation)

    def publish(self, recording_id: str, item: HistoryItem) -> HistoryItem:
        """Publish one metadata item, assigning an idempotent monotonic sequence."""
        item = _ITEM_ADAPTER.validate_python(item)
        if not isinstance(item, (SnapshotHistoryItem, ResourceHistoryItem, LineageEdgeHistoryItem)):
            raise ValueError("unsupported recording history item")
        with self._lock(recording_id):
            self._recover_locked(recording_id)
            item = item.model_copy(update={"publication_sequence": 1})
            generation, generation_root = self._ensure_generation(recording_id)
            authority = self._authority(recording_id, generation, generation_root)
            path = _item_path(generation_root, item)
            if path.exists():
                stored = _ITEM_ADAPTER.validate_python(self._read_object(path, "history item"))
                if _without_sequence(stored) != _without_sequence(item):
                    raise RecordingHistoryConflict("history item key is already bound")
                return stored
            payload = {
                "schema_version": "recording-history-publication/v1",
                "recording_id": recording_id,
                "generation": generation,
                "expected_sequence": authority.sequence,
                "item": item.model_dump(mode="json"),
            }
            record = {**payload, "sha256": hashlib.sha256(_canonical_json(payload)).hexdigest()}
            pending = contained_path(self._recording_root(recording_id), "pending.json")
            atomic_replace_json(pending, record)
            self._after_boundary("journal")
            self._recover_locked(recording_id)
            stored = _ITEM_ADAPTER.validate_python(
                self._read_object(path, "published history item")
            )
            return stored

    def read_item(self, recording_id: str, collection: str, item_key: str) -> HistoryItem:
        with self._lock(recording_id):
            self._recover_locked(recording_id)
            current = self._active_generation(recording_id)
            if current is None:
                raise FileNotFoundError(item_key)
            generation, generation_root = current
            self._authority(recording_id, generation, generation_root)
            digest = hashlib.sha256(item_key.encode("utf-8")).hexdigest()
            path = contained_path(generation_root, Path("items") / collection / f"{digest}.json")
            if not path.exists():
                raise FileNotFoundError(item_key)
            item = _ITEM_ADAPTER.validate_python(self._read_object(path, "history item"))
            if item.item_key != item_key or _collection(item) != collection:
                raise RecordingHistoryCorrupt("history item address mismatch")
            return item

    def validate_generation(self, recording_id: str, generation: str) -> None:
        """Reject a cursor after an offline rebuild changes history membership."""
        authority = self.get_authority(recording_id)
        if authority.generation != generation:
            raise RecordingHistoryCursorExpired("history cursor belongs to an old generation")

    def rebuild(self, recording_id: str, items: Any) -> tuple[str, Path]:
        """Replace derived history from source metadata and expire cursors atomically.

        Callers supply the exact metadata they can prove from durable source stores. Rebuild
        assigns sequences in deterministic collection/key order; it never reads result payloads.
        """
        with self._lock(recording_id):
            self._recover_locked(recording_id)
            return self._rebuild_locked(recording_id, items)

    def _rebuild_locked(self, recording_id: str, items: Any) -> tuple[str, Path]:
        validated = [_ITEM_ADAPTER.validate_python(item) for item in items]
        identities = [_item_identity(item) for item in validated]
        if len(set(identities)) != len(identities):
            raise RecordingHistoryConflict("rebuild contains duplicate history item keys")
        ordered = sorted(validated, key=lambda item: _item_identity(item))
        root = self._recording_root(recording_id)
        generations_root = contained_path(root, "generations")
        generation = f"gen-{uuid4().hex}"
        generations_root.mkdir(parents=True, exist_ok=True)
        with staging_directory(generations_root) as staging:
            for sequence, item in enumerate(ordered, start=1):
                stored = item.model_copy(update={"publication_sequence": sequence})
                path = _item_path(staging, stored)
                atomic_replace_json(path, stored.model_dump(mode="json"))
            authority = RecordingHistoryAuthority(
                recording_id=recording_id,
                generation=generation,
                sequence=len(ordered),
            )
            atomic_replace_json(staging / "authority.json", authority.model_dump(mode="json"))
            generation_root = contained_path(generations_root, generation)
            commit_staged_directory(staging, generation_root)
        atomic_replace_json(
            contained_path(root, "active.json"),
            {
                "schema_version": "recording-history-active/v1",
                "recording_id": recording_id,
                "generation": generation,
            },
        )
        self._after_boundary("rebuild_active")
        return generation, generation_root

    def _after_boundary(self, boundary: str) -> None:
        hook = getattr(self, "_after_durable_boundary", None)
        if hook is not None:
            hook(boundary)

    def _recover_locked(self, recording_id: str) -> None:
        pending_path = contained_path(self._recording_root(recording_id), "pending.json")
        if not pending_path.exists():
            return
        pending = self._read_object(pending_path, "history publication journal")
        if (
            set(pending)
            != {
                "schema_version",
                "recording_id",
                "generation",
                "expected_sequence",
                "item",
                "sha256",
            }
            or pending["schema_version"] != "recording-history-publication/v1"
            or pending["recording_id"] != recording_id
            or isinstance(pending["expected_sequence"], bool)
            or not isinstance(pending["expected_sequence"], int)
            or pending["expected_sequence"] < 0
        ):
            raise RecordingHistoryCorrupt("invalid history publication journal")
        payload = {key: value for key, value in pending.items() if key != "sha256"}
        if pending["sha256"] != hashlib.sha256(_canonical_json(payload)).hexdigest():
            raise RecordingHistoryCorrupt("history publication journal digest mismatch")
        current = self._active_generation(recording_id)
        if current is None or current[0] != pending["generation"]:
            raise RecordingHistoryCorrupt("history publication journal generation changed")
        generation, generation_root = current
        authority = self._authority(recording_id, generation, generation_root)
        item = _ITEM_ADAPTER.validate_python(pending["item"])
        if item.publication_sequence != 1:
            raise RecordingHistoryCorrupt("unpublished journal item has a sequence")
        next_sequence = pending["expected_sequence"] + 1
        destination = _item_path(generation_root, item)
        stored_item = item.model_copy(update={"publication_sequence": next_sequence})
        if authority.sequence == pending["expected_sequence"]:
            if destination.exists():
                existing = _ITEM_ADAPTER.validate_python(
                    self._read_object(destination, "history item")
                )
                if existing != stored_item:
                    raise RecordingHistoryCorrupt("pending history item conflicts with stored item")
            else:
                atomic_replace_json(destination, stored_item.model_dump(mode="json"))
            self._after_boundary("item")
            atomic_replace_json(
                contained_path(generation_root, "authority.json"),
                RecordingHistoryAuthority(
                    recording_id=recording_id,
                    generation=generation,
                    sequence=next_sequence,
                ).model_dump(mode="json"),
            )
            self._after_boundary("authority")
        elif authority.sequence == next_sequence:
            if not destination.exists():
                raise RecordingHistoryCorrupt("authority advanced without its history item")
            existing = _ITEM_ADAPTER.validate_python(self._read_object(destination, "history item"))
            if existing != stored_item:
                raise RecordingHistoryCorrupt("committed authority item does not match journal")
        else:
            raise RecordingHistoryCorrupt("history authority sequence changed during publication")
        pending_path.unlink(missing_ok=True)
        self._after_boundary("journal_cleared")


__all__ = [
    "RecordingHistoryConflict",
    "RecordingHistoryCorrupt",
    "RecordingHistoryCursorExpired",
    "RecordingHistoryStore",
]
