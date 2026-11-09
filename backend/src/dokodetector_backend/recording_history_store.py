"""Durable per-recording sequence authority for metadata-only history entries."""

from __future__ import annotations

import hashlib
import json
import shutil
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
from dokodetector_backend.recording_history_order_index import (
    RecordingHistoryOrderIndex,
    stable_history_key,
)
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


class RecordingHistoryRebuildRequired(ValueError):
    """An interrupted initial rebuild needs its source metadata supplied again."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
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


def _item_document(item: HistoryItem) -> dict[str, Any]:
    mapping = item.model_dump(mode="json")
    return {
        "schema_version": "recording-history-item/v1",
        "collection": _collection(item),
        "item": mapping,
        "item_sha256": hashlib.sha256(_canonical_json(mapping)).hexdigest(),
    }


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

    def _read_item_file(self, path: Path, collection: str | None = None) -> HistoryItem:
        document = self._read_object(path, "history item")
        if (
            set(document) != {"schema_version", "collection", "item", "item_sha256"}
            or document["schema_version"] != "recording-history-item/v1"
            or not isinstance(document["collection"], str)
            or not isinstance(document["item_sha256"], str)
        ):
            raise RecordingHistoryCorrupt("invalid history item envelope")
        try:
            item = _ITEM_ADAPTER.validate_python(document["item"])
        except ValueError as error:
            raise RecordingHistoryCorrupt("history item failed contract validation") from error
        item_mapping = item.model_dump(mode="json")
        expected_digest = hashlib.sha256(_canonical_json(item_mapping)).hexdigest()
        if (
            document["collection"] != _collection(item)
            or document["item_sha256"] != expected_digest
            or (collection is not None and document["collection"] != collection)
        ):
            raise RecordingHistoryCorrupt("history item metadata digest or collection mismatch")
        return item

    def _write_item_file(self, path: Path, item: HistoryItem) -> None:
        atomic_replace_json(path, _item_document(item))

    def _ensure_generation(self, recording_id: str) -> tuple[str, Path]:
        current = self._active_generation(recording_id)
        if current is not None:
            self._authority(recording_id, *current)
            return current
        if self._has_generation_data(recording_id):
            raise RecordingHistoryCorrupt("history generations exist without an active pointer")
        return self._rebuild_locked(recording_id, ())

    def _has_generation_data(self, recording_id: str) -> bool:
        generations_root = contained_path(self._recording_root(recording_id), "generations")
        if not generations_root.exists():
            return False
        return any(
            not (path.name.startswith(".staging-") and path.is_dir() and not path.is_symlink())
            for path in generations_root.iterdir()
        )

    def _remove_staging_generations(self, recording_id: str) -> None:
        generations_root = contained_path(self._recording_root(recording_id), "generations")
        if not generations_root.exists():
            return
        for path in generations_root.iterdir():
            if path.name.startswith(".staging-") and path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)

    def _pending_generation_path(self, recording_id: str) -> Path:
        return contained_path(self._recording_root(recording_id), "pending-generation.json")

    def get_authority(self, recording_id: str) -> RecordingHistoryAuthority:
        with self._lock(recording_id):
            self._recover_locked(recording_id)
            self._recover_generation_locked(recording_id)
            generation = self._ensure_generation(recording_id)
            return self._authority(recording_id, *generation)

    def publish(self, recording_id: str, item: HistoryItem) -> HistoryItem:
        """Publish one metadata item, assigning an idempotent monotonic sequence."""
        item = _ITEM_ADAPTER.validate_python(item)
        if not isinstance(item, (SnapshotHistoryItem, ResourceHistoryItem, LineageEdgeHistoryItem)):
            raise ValueError("unsupported recording history item")
        with self._lock(recording_id):
            self._recover_locked(recording_id)
            self._recover_generation_locked(recording_id)
            item = item.model_copy(update={"publication_sequence": 1})
            generation, generation_root = self._ensure_generation(recording_id)
            authority = self._authority(recording_id, generation, generation_root)
            path = _item_path(generation_root, item)
            if path.exists():
                stored = self._read_item_file(path, _collection(item))
                if not 1 <= stored.publication_sequence <= authority.sequence:
                    raise RecordingHistoryCorrupt("history item sequence exceeds its authority")
                if _without_sequence(stored) != _without_sequence(item):
                    raise RecordingHistoryConflict("history item key is already bound")
                try:
                    indexed = RecordingHistoryOrderIndex(generation_root).contains(
                        _collection(stored),
                        authority.sequence,
                        stable_history_key(stored),
                        stored.item_key,
                        stored.publication_sequence,
                    )
                except (OSError, ValueError) as error:
                    raise RecordingHistoryCorrupt(
                        "history order index failed validation"
                    ) from error
                if not indexed:
                    raise RecordingHistoryCorrupt("published item is missing from history order")
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
            stored = self._read_item_file(path, _collection(item))
            return stored

    def read_item(self, recording_id: str, collection: str, item_key: str) -> HistoryItem:
        with self._lock(recording_id):
            self._recover_locked(recording_id)
            self._recover_generation_locked(recording_id)
            current = self._active_generation(recording_id)
            if current is None:
                if self._has_generation_data(recording_id):
                    raise RecordingHistoryCorrupt(
                        "history generations exist without an active pointer"
                    )
                raise FileNotFoundError(item_key)
            generation, generation_root = current
            authority = self._authority(recording_id, generation, generation_root)
            digest = hashlib.sha256(item_key.encode("utf-8")).hexdigest()
            path = contained_path(generation_root, Path("items") / collection / f"{digest}.json")
            if not path.exists():
                raise FileNotFoundError(item_key)
            item = self._read_item_file(path, collection)
            if item.item_key != item_key or _collection(item) != collection:
                raise RecordingHistoryCorrupt("history item address mismatch")
            if not 1 <= item.publication_sequence <= authority.sequence:
                raise RecordingHistoryCorrupt("history item sequence exceeds its authority")
            return item

    def _read_history_item(
        self, generation_root: Path, collection: str, item_key: str
    ) -> HistoryItem:
        digest = hashlib.sha256(item_key.encode("utf-8")).hexdigest()
        path = contained_path(generation_root, Path("items") / collection / f"{digest}.json")
        if not path.exists():
            raise RecordingHistoryCorrupt("history order index references a missing item")
        item = self._read_item_file(path, collection)
        if item.item_key != item_key or _collection(item) != collection:
            raise RecordingHistoryCorrupt("history order index item address mismatch")
        return item

    @staticmethod
    def _publish_order_index(generation_root: Path, item: HistoryItem) -> None:
        try:
            RecordingHistoryOrderIndex(generation_root).publish(item)
        except (OSError, ValueError) as error:
            raise RecordingHistoryCorrupt("history order publication failed") from error

    def ordered_page(
        self,
        recording_id: str,
        collection: str,
        *,
        upper_bound_sequence: int | None = None,
        history_generation: str | None = None,
        after_key: tuple[str, ...] | None = None,
        limit: int = 50,
    ) -> tuple[RecordingHistoryAuthority, list[HistoryItem], bool]:
        """Read a stable-key page from its immutable publication-sequence index root."""
        with self._lock(recording_id):
            self._recover_locked(recording_id)
            self._recover_generation_locked(recording_id)
            current = self._active_generation(recording_id)
            if current is None:
                if self._has_generation_data(recording_id):
                    raise RecordingHistoryCorrupt(
                        "history generations exist without an active pointer"
                    )
                current = self._ensure_generation(recording_id)
            generation, generation_root = current
            if history_generation is not None and history_generation != generation:
                raise RecordingHistoryCursorExpired("history cursor belongs to an old generation")
            authority = self._authority(recording_id, generation, generation_root)
            boundary = authority.sequence if upper_bound_sequence is None else upper_bound_sequence
            if boundary < 0 or boundary > authority.sequence:
                raise RecordingHistoryCorrupt("history cursor boundary exceeds its authority")
            index = RecordingHistoryOrderIndex(generation_root)
            try:
                refs, has_more = index.next_refs(collection, boundary, after_key, limit)
            except (OSError, ValueError) as error:
                raise RecordingHistoryCorrupt("history order index failed validation") from error
            items = []
            for key, item_key, sequence in refs:
                item = self._read_history_item(generation_root, collection, item_key)
                if item.publication_sequence != sequence or stable_history_key(item) != key:
                    raise RecordingHistoryCorrupt("history order entry does not match its item")
                items.append(item)
            return authority, items, has_more

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
            self._recover_generation_locked(recording_id, retry_initial_incomplete=True)
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
        current = self._active_generation(recording_id)
        expected_generation = None if current is None else current[0]
        journal_payload = {
            "schema_version": "recording-history-generation-publication/v1",
            "recording_id": recording_id,
            "generation": generation,
            "expected_active_generation": expected_generation,
            "item_count": len(ordered),
        }
        journal = {
            **journal_payload,
            "sha256": hashlib.sha256(_canonical_json(journal_payload)).hexdigest(),
        }
        self._after_boundary("rebuild_before_journal_replacement")
        atomic_replace_json(self._pending_generation_path(recording_id), journal)
        self._after_boundary("rebuild_journal")
        generations_root.mkdir(parents=True, exist_ok=True)
        generation_root = contained_path(generations_root, generation)
        try:
            with staging_directory(generations_root) as staging:
                self._after_boundary("rebuild_staging_started")
                index = RecordingHistoryOrderIndex(staging)
                index.initialize()
                for sequence, item in enumerate(ordered, start=1):
                    stored = item.model_copy(update={"publication_sequence": sequence})
                    path = _item_path(staging, stored)
                    self._write_item_file(path, stored)
                    index.publish(stored)
                    self._after_boundary("rebuild_item_staged")
                authority = RecordingHistoryAuthority(
                    recording_id=recording_id,
                    generation=generation,
                    sequence=len(ordered),
                )
                atomic_replace_json(staging / "authority.json", authority.model_dump(mode="json"))
                self._after_boundary("rebuild_before_generation_commit")
                commit_staged_directory(staging, generation_root)
            self._after_boundary("rebuild_generation_committed")
            self._validate_generation(recording_id, generation, generation_root)
        except Exception:
            if generation_root.exists() and not generation_root.is_symlink():
                shutil.rmtree(generation_root)
            if expected_generation is not None or not ordered:
                self._pending_generation_path(recording_id).unlink(missing_ok=True)
            raise
        self._write_active_generation(recording_id, generation)
        self._after_boundary("rebuild_active")
        self._pending_generation_path(recording_id).unlink(missing_ok=True)
        self._after_boundary("rebuild_journal_cleared")
        return generation, generation_root

    def _write_active_generation(self, recording_id: str, generation: str) -> None:
        atomic_replace_json(
            contained_path(self._recording_root(recording_id), "active.json"),
            {
                "schema_version": "recording-history-active/v1",
                "recording_id": recording_id,
                "generation": generation,
            },
        )

    def _recover_generation_locked(
        self, recording_id: str, *, retry_initial_incomplete: bool = False
    ) -> None:
        pending_path = self._pending_generation_path(recording_id)
        if not pending_path.exists():
            return
        pending = self._read_object(pending_path, "history generation journal")
        if (
            set(pending)
            != {
                "schema_version",
                "recording_id",
                "generation",
                "expected_active_generation",
                "item_count",
                "sha256",
            }
            or pending["schema_version"] != "recording-history-generation-publication/v1"
            or pending["recording_id"] != recording_id
            or not isinstance(pending["generation"], str)
            or not pending["generation"].startswith("gen-")
            or (
                pending["expected_active_generation"] is not None
                and not isinstance(pending["expected_active_generation"], str)
            )
            or isinstance(pending["item_count"], bool)
            or not isinstance(pending["item_count"], int)
            or pending["item_count"] < 0
        ):
            raise RecordingHistoryCorrupt("invalid history generation journal")
        journal_payload = {key: value for key, value in pending.items() if key != "sha256"}
        if pending["sha256"] != hashlib.sha256(_canonical_json(journal_payload)).hexdigest():
            raise RecordingHistoryCorrupt("history generation journal digest mismatch")
        generation = pending["generation"]
        current = self._active_generation(recording_id)
        current_generation = None if current is None else current[0]
        expected_generation = pending["expected_active_generation"]
        if current_generation not in {expected_generation, generation}:
            raise RecordingHistoryCorrupt("active history generation changed during rebuild")
        generation_root = contained_path(
            self._recording_root(recording_id), Path("generations") / generation
        )
        if not generation_root.exists():
            if current_generation == generation:
                raise RecordingHistoryCorrupt("active history generation is missing")
            self._remove_staging_generations(recording_id)
            if (
                expected_generation is None
                and pending["item_count"] > 0
                and not retry_initial_incomplete
            ):
                raise RecordingHistoryRebuildRequired(
                    "initial history rebuild stopped before commit; retry rebuild with "
                    "source metadata"
                )
            if expected_generation is None and pending["item_count"] > 0:
                # Keep the old journal until _rebuild_locked validates the retry input and
                # atomically replaces it with the new generation journal.
                return
            pending_path.unlink(missing_ok=True)
            return
        self._validate_generation(recording_id, generation, generation_root)
        if current_generation != generation:
            self._write_active_generation(recording_id, generation)
        pending_path.unlink(missing_ok=True)

    def _validate_generation(self, recording_id: str, generation: str, root: Path) -> None:
        authority = self._authority(recording_id, generation, root)
        items_root = contained_path(root, "items")
        observed: list[HistoryItem] = []
        if items_root.exists():
            for collection_root in sorted(items_root.iterdir(), key=lambda path: path.name):
                if collection_root.is_symlink() or not collection_root.is_dir():
                    raise RecordingHistoryCorrupt("history generation has an invalid collection")
                if collection_root.name not in {
                    "snapshots",
                    "revisions",
                    "candidates",
                    "lineage_edges",
                }:
                    raise RecordingHistoryCorrupt("history generation has an unknown collection")
                for path in sorted(collection_root.iterdir(), key=lambda item: item.name):
                    if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                        raise RecordingHistoryCorrupt("history generation has an invalid item file")
                    item = self._read_item_file(path, collection_root.name)
                    expected_path = _item_path(root, item)
                    if expected_path != path:
                        raise RecordingHistoryCorrupt(
                            "history item filename does not match its key"
                        )
                    observed.append(item)
        ordered = sorted(observed, key=_item_identity)
        sequences = [item.publication_sequence for item in ordered]
        if len(observed) != authority.sequence or sequences != list(
            range(1, authority.sequence + 1)
        ):
            raise RecordingHistoryCorrupt("history generation does not match its authority")
        try:
            index = RecordingHistoryOrderIndex(root)
            index.validate_prefixes(sorted(observed, key=lambda item: item.publication_sequence))
            indexed_entries = index.validate_latest(authority.sequence)
        except (OSError, ValueError) as error:
            raise RecordingHistoryCorrupt("history order index failed validation") from error
        expected_entries = {
            collection: sorted(
                (
                    stable_history_key(item),
                    item.item_key,
                    item.publication_sequence,
                )
                for item in observed
                if _collection(item) == collection
            )
            for collection in ("snapshots", "revisions", "candidates", "lineage_edges")
        }
        if indexed_entries != expected_entries:
            raise RecordingHistoryCorrupt("history order index does not match its metadata")

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
                existing = self._read_item_file(destination, _collection(item))
                if existing != stored_item:
                    raise RecordingHistoryCorrupt("pending history item conflicts with stored item")
            else:
                self._write_item_file(destination, stored_item)
            self._after_boundary("item")
            self._publish_order_index(generation_root, stored_item)
            self._after_boundary("order_index")
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
            existing = self._read_item_file(destination, _collection(item))
            if existing != stored_item:
                raise RecordingHistoryCorrupt("committed authority item does not match journal")
            try:
                indexed = RecordingHistoryOrderIndex(generation_root).contains(
                    _collection(existing),
                    authority.sequence,
                    stable_history_key(existing),
                    existing.item_key,
                    existing.publication_sequence,
                )
            except (OSError, ValueError) as error:
                raise RecordingHistoryCorrupt("history order index failed validation") from error
            if not indexed:
                raise RecordingHistoryCorrupt("committed history item is absent from its index")
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
