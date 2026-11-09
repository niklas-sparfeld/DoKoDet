"""Durable per-recording sequence authority for metadata-only history entries."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import stat
import tempfile
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


def _cursor_key_state(key_sha256: str) -> dict[str, str]:
    return {
        "schema_version": "recording-history-cursor-key-state/v1",
        "sha256": key_sha256,
    }


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

    def cursor_integrity_key(self) -> bytes:
        """Return the established cursor key, refusing silent key replacement after loss."""
        self.root.mkdir(parents=True, exist_ok=True)
        path = contained_path(self.root, "cursor-integrity-key")
        state_path = contained_path(self.root, "cursor-integrity-key-state.json")
        authority_path = contained_path(self.root.parent, "recording-history-cursor-authority.json")
        authority_lock = self.root.parent / ".recording-history-cursor-authority.lock"
        with _process_lock(authority_lock, self._thread_lock):
            for abandoned in self.root.glob(".cursor-integrity-key.*"):
                abandoned.unlink(missing_ok=True)
            for abandoned in self.root.glob(".cursor-integrity-key-state.json.*"):
                abandoned.unlink(missing_ok=True)
            for abandoned in self.root.parent.glob(".recording-history-cursor-authority.json.*"):
                abandoned.unlink(missing_ok=True)
            if path.is_symlink() or state_path.is_symlink() or authority_path.is_symlink():
                raise RecordingHistoryCorrupt("history cursor key files cannot be symlinks")
            authority = None
            if authority_path.exists():
                try:
                    raw_authority = authority_path.read_bytes()
                    authority = json.loads(raw_authority)
                except (OSError, TypeError, UnicodeError, json.JSONDecodeError) as error:
                    raise RecordingHistoryCorrupt("history cursor authority is invalid") from error
                if (
                    not isinstance(authority, dict)
                    or _canonical_json(authority) != raw_authority
                    or set(authority) != {"schema_version", "sha256"}
                    or authority["schema_version"] != "recording-history-cursor-authority/v1"
                    or not isinstance(authority["sha256"], str)
                ):
                    raise RecordingHistoryCorrupt("history cursor authority is invalid")
                if stat.S_IMODE(authority_path.stat().st_mode) != 0o600:
                    raise RecordingHistoryCorrupt("history cursor authority is not private")

            if not path.exists() and authority is not None:
                raise RecordingHistoryCorrupt("established history cursor key is missing")
            if not path.exists() and state_path.exists():
                raise RecordingHistoryCorrupt("established history cursor key is missing")
            if not path.exists() and self._has_history_generation_data():
                raise RecordingHistoryCorrupt(
                    "pre-existing history has no cursor key; restore or explicitly bootstrap it"
                )
            if authority is None and self._has_history_generation_data():
                raise RecordingHistoryCorrupt(
                    "pre-existing history has no independent cursor authority;"
                    " explicitly bootstrap it"
                )
            if not path.exists():
                key = secrets.token_bytes(32)
                self._write_private_file(path, key)
                self._after_cursor_key_boundary("key_published")
            try:
                key = path.read_bytes()
                mode = stat.S_IMODE(path.stat().st_mode)
            except OSError as error:
                raise RecordingHistoryCorrupt("history cursor key is unavailable") from error
            if len(key) != 32:
                raise RecordingHistoryCorrupt("history cursor key is invalid")
            if mode != 0o600:
                try:
                    path.chmod(0o600)
                except OSError as error:
                    raise RecordingHistoryCorrupt("history cursor key is not private") from error
                if stat.S_IMODE(path.stat().st_mode) != 0o600:
                    raise RecordingHistoryCorrupt("history cursor key is not private")
            key_digest = hashlib.sha256(key).hexdigest()
            if authority is not None and authority["sha256"] != key_digest:
                raise RecordingHistoryCorrupt("history cursor key does not match its authority")
            state = _cursor_key_state(key_digest)
            if state_path.exists():
                try:
                    raw_state = state_path.read_bytes()
                    stored_state = json.loads(raw_state)
                except (OSError, TypeError, UnicodeError, json.JSONDecodeError) as error:
                    raise RecordingHistoryCorrupt("history cursor key state is invalid") from error
                if (
                    not isinstance(stored_state, dict)
                    or _canonical_json(stored_state) != raw_state
                    or stored_state != state
                ):
                    raise RecordingHistoryCorrupt("history cursor key state does not match")
                if stat.S_IMODE(state_path.stat().st_mode) != 0o600:
                    raise RecordingHistoryCorrupt("history cursor key state is not private")
            else:
                self._write_private_file(state_path, _canonical_json(state))
                self._after_cursor_key_boundary("state_published")
            if authority is None:
                # One-time upgrade preserves an established pre-authority key. If neither that
                # key nor its state marker exists beside pre-existing history, fail above.
                self._write_private_file(
                    authority_path,
                    _canonical_json(
                        {
                            "schema_version": "recording-history-cursor-authority/v1",
                            "sha256": key_digest,
                        }
                    ),
                )
                self._after_cursor_key_boundary("authority_published")
            return key

    def bootstrap_cursor_integrity_key_for_existing_history(
        self, *, invalidate_existing_cursors: bool = False
    ) -> bytes:
        """Explicitly establish independent cursor authority for pre-existing history.

        Preserve an available 32-byte key. If no key remains, refuse by default because existing
        cursors cannot be validated. An operator can explicitly allow replacement, which
        invalidates every prior cursor.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        path = contained_path(self.root, "cursor-integrity-key")
        state_path = contained_path(self.root, "cursor-integrity-key-state.json")
        authority_path = contained_path(self.root.parent, "recording-history-cursor-authority.json")
        authority_lock = self.root.parent / ".recording-history-cursor-authority.lock"
        if authority_path.is_symlink():
            raise RecordingHistoryCorrupt("history cursor authority cannot be a symlink")
        if authority_path.exists():
            return self.cursor_integrity_key()
        with _process_lock(authority_lock, self._thread_lock):
            if not authority_path.exists() and self._has_history_generation_data():
                if path.is_symlink() or state_path.is_symlink():
                    raise RecordingHistoryCorrupt("history cursor key files cannot be symlinks")
                if path.exists():
                    key = path.read_bytes()
                    if len(key) != 32:
                        raise RecordingHistoryCorrupt("history cursor key is invalid")
                    if stat.S_IMODE(path.stat().st_mode) != 0o600:
                        path.chmod(0o600)
                    if stat.S_IMODE(path.stat().st_mode) != 0o600:
                        raise RecordingHistoryCorrupt("history cursor key is not private")
                    if state_path.exists():
                        try:
                            raw_state = state_path.read_bytes()
                            state = json.loads(raw_state)
                        except (OSError, TypeError, UnicodeError, json.JSONDecodeError) as error:
                            raise RecordingHistoryCorrupt(
                                "history cursor key state is invalid"
                            ) from error
                        if (
                            not isinstance(state, dict)
                            or _canonical_json(state) != raw_state
                            or state != _cursor_key_state(hashlib.sha256(key).hexdigest())
                        ):
                            raise RecordingHistoryCorrupt("history cursor key state does not match")
                        if stat.S_IMODE(state_path.stat().st_mode) != 0o600:
                            state_path.chmod(0o600)
                        if stat.S_IMODE(state_path.stat().st_mode) != 0o600:
                            raise RecordingHistoryCorrupt("history cursor key state is not private")
                else:
                    if state_path.exists():
                        raise RecordingHistoryCorrupt("established history cursor key is missing")
                    if not invalidate_existing_cursors:
                        raise RecordingHistoryCorrupt(
                            "history has no cursor key; explicit cursor invalidation is required"
                        )
                    key = secrets.token_bytes(32)
                    self._write_private_file(path, key)
                key_digest = hashlib.sha256(key).hexdigest()
                state = _cursor_key_state(key_digest)
                self._write_private_file(state_path, _canonical_json(state))
                self._write_private_file(
                    authority_path,
                    _canonical_json(
                        {
                            "schema_version": "recording-history-cursor-authority/v1",
                            "sha256": key_digest,
                        }
                    ),
                )
        return self.cursor_integrity_key()

    def _has_history_generation_data(self) -> bool:
        internal = {"cursor-integrity-key", "cursor-integrity-key-state.json"}
        for recording_root in self.root.iterdir():
            if recording_root.name in internal or recording_root.name.startswith("."):
                continue
            if not recording_root.is_dir() or recording_root.is_symlink():
                return True
            if any(
                (recording_root / name).exists()
                for name in ("pending.json", "pending-generation.json")
            ):
                return True
            active_path = recording_root / "active.json"
            if not active_path.exists():
                if any(path.name != ".history.lock" for path in recording_root.iterdir()):
                    return True
                continue
            try:
                active = self._read_object(active_path, "active history generation")
                generation = active["generation"]
                if (
                    active.get("schema_version") != "recording-history-active/v1"
                    or active.get("recording_id") != recording_root.name
                    or not isinstance(generation, str)
                    or not generation.startswith("gen-")
                ):
                    return True
                generation_root = contained_path(recording_root, Path("generations") / generation)
                authority = self._read_object(
                    generation_root / "authority.json", "history authority"
                )
                if (
                    authority.get("schema_version") != "recording-history-authority/v1"
                    or authority.get("recording_id") != recording_root.name
                    or authority.get("generation") != generation
                    or not isinstance(authority.get("sequence"), int)
                    or authority["sequence"] < 0
                ):
                    return True
                if authority.get("sequence", 0) > 0:
                    return True
                items_root = generation_root / "items"
                if items_root.exists() and any(items_root.rglob("*.json")):
                    return True
                # A rebuild can leave the active generation empty while an older generation
                # still proves that cursors were issued against retained history.
                generations_root = recording_root / "generations"
                for retained_root in generations_root.iterdir():
                    if retained_root == generation_root or retained_root.name.startswith(
                        ".staging-"
                    ):
                        continue
                    retained_authority = self._read_object(
                        retained_root / "authority.json", "retained history authority"
                    )
                    retained_sequence = retained_authority.get("sequence")
                    if not isinstance(retained_sequence, int) or retained_sequence > 0:
                        return True
                    retained_items = retained_root / "items"
                    if retained_items.exists() and any(retained_items.rglob("*.json")):
                        return True
            except (KeyError, OSError, TypeError, ValueError):
                return True
        return False

    @staticmethod
    def _write_private_file(path: Path, contents: bytes) -> None:
        """Publish a private file atomically and sync both file and parent directory."""
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def _after_cursor_key_boundary(self, boundary: str) -> None:
        """Expose durable key creation boundaries for crash-recovery tests."""

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
        # Establish cursor authority before new history can become durable. Existing histories
        # without a key-state marker are legacy data and receive their first key on access.
        self.cursor_integrity_key()
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
        self.cursor_integrity_key()
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
            for collection in ("snapshots", "revisions", "lineage_edges")
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
