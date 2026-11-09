"""Immutable recording-state snapshots with direct, history-independent reads."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from dokodetector_backend.filesystem import (
    atomic_replace_json,
    commit_staged_directory,
    contained_path,
    staging_directory,
)
from dokodetector_backend.pipeline_storage import _process_lock
from dokodetector_backend.recording_state_contract import (
    RecordingHead,
    RecordingHeadUpdate,
    RecordingStateSnapshot,
    RecordingStateSummary,
    SlotName,
    SnapshotHistoryItem,
    StageSummarySelection,
)


class RecordingSnapshotNotFound(FileNotFoundError):
    """The requested immutable recording snapshot does not exist."""


class RecordingSnapshotCorrupt(ValueError):
    """Persisted snapshot bytes or their compact metadata fail validation."""


class RecordingSnapshotConflict(ValueError):
    """An immutable snapshot identity already contains different bytes."""


class RecordingHeadConflict(ValueError):
    """The recording HEAD changed since the caller read it."""


class RecordingHeadNotFound(FileNotFoundError):
    """No current recording state has been published."""


@dataclass(frozen=True, slots=True)
class PublishedRecordingState:
    head: RecordingHead
    snapshot: RecordingStateSnapshot
    summary: RecordingStateSummary


@dataclass(frozen=True, slots=True)
class StoredRecordingSnapshot:
    snapshot: RecordingStateSnapshot
    snapshot_sha256: str
    stage_metadata: dict[str, dict[str, str]]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _stage_metadata(snapshot: RecordingStateSnapshot) -> dict[str, dict[str, str]]:
    return {
        slot: {
            "generated": selection.generated.state,
            "completed_reference": selection.completed_reference.state,
        }
        for slot, selection in snapshot.slots.items()
    }


def _verified_stage_metadata(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict) or set(value) != set(SlotName.__args__):
        raise ValueError("snapshot history stage metadata is invalid")
    result = {}
    for slot, selection in value.items():
        if not isinstance(selection, dict) or set(selection) != {
            "generated",
            "completed_reference",
        }:
            raise ValueError("snapshot history stage metadata is invalid")
        result[slot] = StageSummarySelection.model_validate(selection).model_dump(mode="json")
    return result


class RecordingStateSnapshotStore:
    """Store and load snapshots by exact recording and content-derived identity."""

    def __init__(self, operations_root: Path | str) -> None:
        self.operations_root = Path(operations_root).expanduser().resolve()
        self.root = self.operations_root / "recording-state" / "snapshots"
        self.state_root = self.operations_root / "recording-state"
        self.head_root = self.state_root / "heads"
        self.summary_root = self.state_root / "summaries"
        self.transaction_root = self.state_root / "transactions"
        self.snapshot_history_outbox_root = self.state_root / "snapshot-history-outbox"
        self._thread_lock = RLock()

    def head_path(self, recording_id: str) -> Path:
        return contained_path(self.head_root, f"{recording_id}.json")

    def summary_path(self, recording_id: str) -> Path:
        return contained_path(self.summary_root, f"{recording_id}.json")

    def transaction_path(self, recording_id: str) -> Path:
        return contained_path(self.transaction_root, f"{recording_id}.json")

    def initialize(self, recording_id: str, snapshot_id: str) -> PublishedRecordingState:
        """Publish the first current snapshot at version one."""
        return self._publish(recording_id, snapshot_id, expected_head_version=None)

    def publish(self, update: RecordingHeadUpdate) -> PublishedRecordingState:
        """Atomically advance HEAD and its compact summary using compare-and-swap."""
        if update.action not in {"select_snapshot", "restore_snapshot"}:
            raise ValueError("unsupported recording state action")
        return self._publish(
            update.recording_id,
            update.snapshot_id,
            expected_head_version=update.expected_head_version,
        )

    def get_current(self, recording_id: str) -> PublishedRecordingState:
        """Read a complete published state and repair only its derived summary if needed."""
        with self._lock(recording_id):
            self._recover_locked(recording_id)
            head = self._read_head(recording_id)
            snapshot = self.get(recording_id, head.snapshot_id)
            summary = self._fresh_summary(head, snapshot)
            summary_path = self.summary_path(recording_id)
            try:
                existing_summary = self._read_summary(recording_id)
            except RecordingSnapshotCorrupt:
                existing_summary = None
            if existing_summary != summary:
                atomic_replace_json(summary_path, summary.model_dump(mode="json"))
            return PublishedRecordingState(head, snapshot.snapshot, summary)

    def _publish(
        self, recording_id: str, snapshot_id: str, expected_head_version: int | None
    ) -> PublishedRecordingState:
        with self._lock(recording_id):
            self._recover_locked(recording_id)
            current = self._read_head_optional(recording_id)
            if expected_head_version is None:
                if current is not None:
                    raise RecordingHeadConflict("recording HEAD is already initialized")
                if self.transaction_path(recording_id).exists():
                    raise RecordingHeadNotFound(
                        f"recording HEAD is missing after prior publication: {recording_id}"
                    )
                next_version = 1
            else:
                if current is None or current.version != expected_head_version:
                    actual = None if current is None else current.version
                    raise RecordingHeadConflict(
                        f"expected recording HEAD {expected_head_version}, found {actual}"
                    )
                # Do not replace a missing or corrupt selected state with another snapshot.
                self.get(recording_id, current.snapshot_id)
                next_version = current.version + 1

            stored = self.get(recording_id, snapshot_id)
            head = RecordingHead(
                recording_id=recording_id, version=next_version, snapshot_id=snapshot_id
            )
            summary = self._fresh_summary(head, stored)
            journal = {
                "schema_version": "recording-state-publication/v1",
                "recording_id": recording_id,
                "expected_head_version": expected_head_version,
                "expected_head": None if current is None else current.model_dump(mode="json"),
                "head": head.model_dump(mode="json"),
                "summary": summary.model_dump(mode="json"),
                "status": "prepared",
            }
            path = self.transaction_path(recording_id)
            self._durable_write(path, journal, "journal_prepared")
            self._finish_journal(recording_id, journal)
            return PublishedRecordingState(head, stored.snapshot, summary)

    def _lock(self, recording_id: str):
        return _process_lock(self.state_root / f".{recording_id}.lock", self._thread_lock)

    def _durable_write(self, path: Path, value: dict[str, Any], boundary: str) -> None:
        atomic_replace_json(path, value)
        hook = getattr(self, "_after_durable_boundary", None)
        if hook is not None:
            hook(boundary)

    def _snapshot_history_boundary(self, boundary: str) -> None:
        hook = getattr(self, "_after_durable_boundary", None)
        if hook is not None:
            hook(boundary)

    def _finish_journal(self, recording_id: str, journal: dict[str, Any]) -> None:
        head = RecordingHead.model_validate(journal["head"])
        summary = RecordingStateSummary.model_validate(journal["summary"])
        expected = journal["expected_head"]
        current = self._read_head_optional(recording_id)
        if current == head:
            pass  # Recovery after the HEAD replacement is idempotent.
        elif expected is None:
            if current is not None:
                raise RecordingSnapshotCorrupt(
                    f"recording HEAD changed during initialization: {recording_id}"
                )
        elif current != RecordingHead.model_validate(expected):
            raise RecordingSnapshotCorrupt(
                f"recording HEAD changed during publication: {recording_id}"
            )
        # The immutable snapshot is already durable and verified before the journal is written.
        try:
            stored = self.get(recording_id, head.snapshot_id)
        except (RecordingSnapshotNotFound, RecordingSnapshotCorrupt) as error:
            raise RecordingSnapshotCorrupt(
                f"publication snapshot is missing or corrupt: {recording_id}"
            ) from error
        if summary != self._fresh_summary(head, stored):
            raise RecordingSnapshotCorrupt(
                f"publication summary does not match its snapshot: {recording_id}"
            )
        self._durable_write(self.head_path(recording_id), head.model_dump(mode="json"), "head")
        self._durable_write(
            self.summary_path(recording_id), summary.model_dump(mode="json"), "summary"
        )
        committed = {**journal, "status": "committed"}
        self._durable_write(self.transaction_path(recording_id), committed, "journal_committed")

    def _recover_locked(self, recording_id: str) -> None:
        path = self.transaction_path(recording_id)
        if not path.exists():
            return
        try:
            journal = json.loads(path.read_bytes())
            if (
                not isinstance(journal, dict)
                or set(journal)
                != {
                    "schema_version",
                    "recording_id",
                    "expected_head_version",
                    "expected_head",
                    "head",
                    "summary",
                    "status",
                }
                or journal["schema_version"] != "recording-state-publication/v1"
                or journal["recording_id"] != recording_id
                or journal["status"] not in {"prepared", "committed"}
            ):
                raise ValueError("invalid recording-state publication journal")
            head = RecordingHead.model_validate(journal["head"])
            summary = RecordingStateSummary.model_validate(journal["summary"])
            expected_version = journal["expected_head_version"]
            expected_head = journal["expected_head"]
            if head.recording_id != recording_id or summary.recording_id != recording_id:
                raise ValueError("publication journal recording identity mismatch")
            if expected_version is None:
                if expected_head is not None or head.version != 1:
                    raise ValueError("publication journal initialization version is invalid")
            else:
                if (
                    isinstance(expected_version, bool)
                    or not isinstance(expected_version, int)
                    or expected_version < 1
                    or expected_head is None
                    or head.version != expected_version + 1
                ):
                    raise ValueError("publication journal version transition is invalid")
                previous = RecordingHead.model_validate(expected_head)
                if previous.recording_id != recording_id or previous.version != expected_version:
                    raise ValueError("publication journal expected HEAD is invalid")
            if (
                summary.head_version != head.version
                or summary.snapshot_id != head.snapshot_id
                or summary.recording_id != head.recording_id
            ):
                raise ValueError("publication journal HEAD and summary disagree")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise RecordingSnapshotCorrupt(
                f"recording state publication journal is corrupt: {recording_id}"
            ) from error
        current = self._read_head_optional(recording_id)
        target = RecordingHead.model_validate(journal["head"])
        if journal["status"] == "prepared":
            self._finish_journal(recording_id, journal)
        elif current != target:
            raise RecordingSnapshotCorrupt(
                f"committed publication does not match recording HEAD: {recording_id}"
            )
        else:
            # A committed journal remains evidence that this recording was initialized.
            self._finish_validate_only(recording_id, journal)

    def _finish_validate_only(self, recording_id: str, journal: dict[str, Any]) -> None:
        head = RecordingHead.model_validate(journal["head"])
        summary = RecordingStateSummary.model_validate(journal["summary"])
        try:
            stored = self.get(recording_id, head.snapshot_id)
        except (RecordingSnapshotNotFound, RecordingSnapshotCorrupt) as error:
            raise RecordingSnapshotCorrupt(
                f"committed publication snapshot is missing or corrupt: {recording_id}"
            ) from error
        if summary != self._fresh_summary(head, stored):
            raise RecordingSnapshotCorrupt(
                f"committed publication summary does not match its snapshot: {recording_id}"
            )

    def _read_head_optional(self, recording_id: str) -> RecordingHead | None:
        path = self.head_path(recording_id)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_bytes())
            head = RecordingHead.model_validate(value)
            if head.recording_id != recording_id:
                raise ValueError("HEAD recording identity mismatch")
            return head
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise RecordingSnapshotCorrupt(f"recording HEAD is corrupt: {recording_id}") from error

    def _read_head(self, recording_id: str) -> RecordingHead:
        head = self._read_head_optional(recording_id)
        if head is None:
            raise RecordingHeadNotFound(f"recording HEAD not found: {recording_id}")
        return head

    def _read_summary(self, recording_id: str) -> RecordingStateSummary:
        try:
            value = json.loads(self.summary_path(recording_id).read_bytes())
            summary = RecordingStateSummary.model_validate(value)
            if summary.recording_id != recording_id:
                raise ValueError("summary recording identity mismatch")
            return summary
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise RecordingSnapshotCorrupt(
                f"recording summary is corrupt: {recording_id}"
            ) from error

    @staticmethod
    def _fresh_summary(
        head: RecordingHead, stored: StoredRecordingSnapshot
    ) -> RecordingStateSummary:
        return RecordingStateSummary(
            recording_id=head.recording_id,
            head_version=head.version,
            snapshot_id=head.snapshot_id,
            snapshot_sha256=stored.snapshot_sha256,
            slots={
                slot: StageSummarySelection(**selection)
                for slot, selection in stored.stage_metadata.items()
            },
        )

    def snapshot_path(self, recording_id: str, snapshot_id: str) -> Path:
        candidate = self.root / recording_id / snapshot_id
        if self.root.is_symlink() or candidate.parent.is_symlink() or candidate.is_symlink():
            raise RecordingSnapshotCorrupt("snapshot path cannot contain symlinks")
        recording_root = contained_path(self.root, recording_id)
        return contained_path(recording_root, snapshot_id)

    def put(self, snapshot: RecordingStateSnapshot) -> StoredRecordingSnapshot:
        """Publish one complete immutable snapshot; exact duplicate puts are idempotent."""
        # Pydantic models are mutable and assignment validation is disabled. Validate a detached
        # dump so callers cannot publish nested changes under an identity computed earlier.
        verified_snapshot = RecordingStateSnapshot.model_validate(snapshot.model_dump(mode="json"))
        raw = _canonical_json(verified_snapshot.model_dump(mode="json"))
        digest = hashlib.sha256(raw).hexdigest()
        metadata = {
            "schema_version": "recording-state-snapshot-metadata/v1",
            "recording_id": verified_snapshot.recording_id,
            "snapshot_id": verified_snapshot.snapshot_id,
            "snapshot_sha256": digest,
            "stage_metadata": _stage_metadata(verified_snapshot),
        }
        destination = self.snapshot_path(
            verified_snapshot.recording_id, verified_snapshot.snapshot_id
        )
        with self._lock(verified_snapshot.recording_id):
            self._reconcile_snapshot_history_outbox_locked(verified_snapshot.recording_id)
            if destination.exists() or destination.is_symlink():
                stored = self._existing_or_conflict(destination, raw, verified_snapshot)
            else:
                self._queue_snapshot_history(verified_snapshot, digest)
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with staging_directory(destination.parent, prefix=".snapshot-") as staging:
                        (staging / "snapshot.json").write_bytes(raw)
                        (staging / "metadata.json").write_bytes(_canonical_json(metadata))
                        commit_staged_directory(staging, destination)
                except FileExistsError:
                    stored = self._existing_or_conflict(destination, raw, verified_snapshot)
                else:
                    stored = StoredRecordingSnapshot(
                        verified_snapshot, digest, metadata["stage_metadata"]
                    )
                self._snapshot_history_boundary("snapshot")
            # Existing snapshots can predate the publisher. An exact repeat also repairs their
            # missing history entry without discovering or scanning other snapshots.
            if not self._snapshot_history_outbox_path(verified_snapshot.recording_id).exists():
                self._queue_snapshot_history(verified_snapshot, digest)
            self._reconcile_snapshot_history_outbox_locked(verified_snapshot.recording_id)
            return stored

    def _snapshot_history_outbox_path(self, recording_id: str) -> Path:
        candidate = self.snapshot_history_outbox_root / f"{recording_id}.json"
        if self.snapshot_history_outbox_root.is_symlink() or candidate.is_symlink():
            raise RecordingSnapshotCorrupt("snapshot history outbox cannot be a symlink")
        return contained_path(self.snapshot_history_outbox_root, f"{recording_id}.json")

    @staticmethod
    def _clear_snapshot_history_outbox(path: Path) -> None:
        path.unlink(missing_ok=True)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _queue_snapshot_history(
        self, snapshot: RecordingStateSnapshot, snapshot_sha256: str
    ) -> None:
        path = self._snapshot_history_outbox_path(snapshot.recording_id)
        if path.is_symlink():
            raise RecordingSnapshotCorrupt("snapshot history outbox cannot be a symlink")
        if path.exists():
            try:
                current = json.loads(path.read_bytes())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RecordingSnapshotCorrupt("snapshot history outbox is corrupt") from error
            if (
                not isinstance(current, dict)
                or _canonical_json(current) != path.read_bytes()
                or set(current)
                != {"schema_version", "recording_id", "item", "stage_metadata", "sha256"}
                or current["schema_version"] != "recording-snapshot-history-outbox/v1"
                or current["recording_id"] != snapshot.recording_id
            ):
                raise RecordingSnapshotCorrupt("snapshot history outbox is corrupt")
            payload = {key: value for key, value in current.items() if key != "sha256"}
            if current["sha256"] != hashlib.sha256(_canonical_json(payload)).hexdigest():
                raise RecordingSnapshotCorrupt("snapshot history outbox digest mismatch")
            try:
                item = SnapshotHistoryItem.model_validate(current["item"])
                stage_metadata = _verified_stage_metadata(current["stage_metadata"])
            except ValueError as error:
                raise RecordingSnapshotCorrupt("snapshot history outbox item is corrupt") from error
            if item.snapshot_id != snapshot.snapshot_id:
                raise RecordingSnapshotCorrupt("another snapshot publication is still pending")
            if (
                item.sha256 != snapshot_sha256
                or item.predecessor_snapshot_id != snapshot.predecessor_snapshot_id
                or stage_metadata != _stage_metadata(snapshot)
            ):
                raise RecordingSnapshotCorrupt("snapshot history outbox digest mismatch")
            return
        item = SnapshotHistoryItem(
            item_key=snapshot.snapshot_id,
            snapshot_id=snapshot.snapshot_id,
            sha256=snapshot_sha256,
            publication_sequence=1,
            predecessor_snapshot_id=snapshot.predecessor_snapshot_id,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "recording-snapshot-history-outbox/v1",
            "recording_id": snapshot.recording_id,
            "item": item.model_dump(mode="json"),
            "stage_metadata": _stage_metadata(snapshot),
        }
        atomic_replace_json(
            path,
            {**payload, "sha256": hashlib.sha256(_canonical_json(payload)).hexdigest()},
        )
        self._snapshot_history_boundary("history_outbox")

    def _reconcile_snapshot_history_outbox_locked(self, recording_id: str) -> None:
        path = self._snapshot_history_outbox_path(recording_id)
        if path.is_symlink():
            raise RecordingSnapshotCorrupt("snapshot history outbox cannot be a symlink")
        if not path.exists():
            return
        try:
            raw = path.read_bytes()
            value = json.loads(raw)
            if (
                not isinstance(value, dict)
                or _canonical_json(value) != raw
                or set(value)
                != {"schema_version", "recording_id", "item", "stage_metadata", "sha256"}
                or value["schema_version"] != "recording-snapshot-history-outbox/v1"
                or value["recording_id"] != recording_id
            ):
                raise ValueError("invalid snapshot history outbox")
            payload = {key: part for key, part in value.items() if key != "sha256"}
            if value["sha256"] != hashlib.sha256(_canonical_json(payload)).hexdigest():
                raise ValueError("snapshot history outbox digest mismatch")
            item = SnapshotHistoryItem.model_validate(value["item"])
            stage_metadata = _verified_stage_metadata(value["stage_metadata"])
            if item.publication_sequence != 1 or item.item_key != item.snapshot_id:
                raise ValueError("invalid snapshot history identity")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise RecordingSnapshotCorrupt("snapshot history outbox is corrupt") from error

        source_path = self.snapshot_path(recording_id, item.snapshot_id)
        if source_path.is_symlink():
            raise RecordingSnapshotCorrupt("published snapshot path cannot be a symlink")
        if not source_path.exists():
            # The intent is durable before the staged directory commit. Missing source is the
            # only state that proves the snapshot write did not commit.
            self._clear_snapshot_history_outbox(path)
            self._snapshot_history_boundary("history_outbox_cleared")
            return
        try:
            metadata_path = source_path / "metadata.json"
            if metadata_path.is_symlink():
                raise ValueError("snapshot source metadata cannot be a symlink")
            metadata_raw = metadata_path.read_bytes()
            metadata = json.loads(metadata_raw)
            expected_metadata = {
                "schema_version": "recording-state-snapshot-metadata/v1",
                "recording_id": recording_id,
                "snapshot_id": item.snapshot_id,
                "snapshot_sha256": item.sha256,
                "stage_metadata": stage_metadata,
            }
            if (
                not isinstance(metadata, dict)
                or _canonical_json(metadata) != metadata_raw
                or metadata != expected_metadata
            ):
                raise ValueError("snapshot source metadata does not match its history intent")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise RecordingSnapshotCorrupt("snapshot history source identity mismatch") from error
        from dokodetector_backend.recording_history_store import RecordingHistoryStore

        RecordingHistoryStore(self.operations_root).publish(recording_id, item)
        self._snapshot_history_boundary("history_published")
        self._clear_snapshot_history_outbox(path)
        self._snapshot_history_boundary("history_outbox_cleared")

    def reconcile_snapshot_history_outbox(self, recording_id: str) -> None:
        """Replay one named snapshot publication intent without scanning snapshot history."""
        with self._lock(recording_id):
            self._reconcile_snapshot_history_outbox_locked(recording_id)

    def get(self, recording_id: str, snapshot_id: str) -> StoredRecordingSnapshot:
        """Read exactly one snapshot and its compact metadata, without listing history."""
        directory = self.snapshot_path(recording_id, snapshot_id)
        if not directory.is_dir():
            raise RecordingSnapshotNotFound(f"snapshot not found: {recording_id}/{snapshot_id}")
        try:
            if (directory / "snapshot.json").is_symlink() or (
                directory / "metadata.json"
            ).is_symlink():
                raise ValueError("snapshot files cannot be symlinks")
            snapshot_raw = (directory / "snapshot.json").read_bytes()
            metadata_raw = (directory / "metadata.json").read_bytes()
            snapshot_value = json.loads(snapshot_raw)
            if (
                not isinstance(snapshot_value, dict)
                or _canonical_json(snapshot_value) != snapshot_raw
            ):
                raise ValueError("snapshot bytes are not canonical JSON")
            snapshot = RecordingStateSnapshot.model_validate(snapshot_value)
            metadata = json.loads(metadata_raw)
            if not isinstance(metadata, dict) or _canonical_json(metadata) != metadata_raw:
                raise ValueError("metadata bytes are not canonical JSON")
            digest = hashlib.sha256(snapshot_raw).hexdigest()
            expected_metadata = {
                "schema_version": "recording-state-snapshot-metadata/v1",
                "recording_id": snapshot.recording_id,
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_sha256": digest,
                "stage_metadata": _stage_metadata(snapshot),
            }
            if metadata != expected_metadata:
                raise ValueError("compact stage metadata does not match verified snapshot")
            if snapshot.recording_id != recording_id or snapshot.snapshot_id != snapshot_id:
                raise ValueError("snapshot identity does not match requested path")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise RecordingSnapshotCorrupt(
                f"snapshot is missing or corrupt: {recording_id}/{snapshot_id}"
            ) from error
        return StoredRecordingSnapshot(snapshot, digest, expected_metadata["stage_metadata"])

    def _existing_or_conflict(
        self, destination: Path, raw: bytes, snapshot: RecordingStateSnapshot
    ) -> StoredRecordingSnapshot:
        try:
            existing = self.get(snapshot.recording_id, snapshot.snapshot_id)
        except RecordingSnapshotCorrupt:
            raise
        if _canonical_json(existing.snapshot.model_dump(mode="json")) != raw:
            raise RecordingSnapshotConflict(
                f"snapshot identity already exists with different bytes: {snapshot.snapshot_id}"
            )
        return existing
