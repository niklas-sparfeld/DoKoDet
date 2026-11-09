"""Immutable recording-state snapshots with direct, history-independent reads."""

from __future__ import annotations

import hashlib
import json
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


class RecordingStateSnapshotStore:
    """Store and load snapshots by exact recording and content-derived identity."""

    def __init__(self, operations_root: Path | str) -> None:
        self.operations_root = Path(operations_root).expanduser().resolve()
        self.root = self.operations_root / "recording-state" / "snapshots"
        self.state_root = self.operations_root / "recording-state"
        self.head_root = self.state_root / "heads"
        self.summary_root = self.state_root / "summaries"
        self.transaction_root = self.state_root / "transactions"
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
                next_version = 1
            else:
                if current is None or current.version != expected_head_version:
                    actual = None if current is None else current.version
                    raise RecordingHeadConflict(
                        f"expected recording HEAD {expected_head_version}, found {actual}"
                    )
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

    def _finish_journal(self, recording_id: str, journal: dict[str, Any]) -> None:
        head = RecordingHead.model_validate(journal["head"])
        summary = RecordingStateSummary.model_validate(journal["summary"])
        # The immutable snapshot is already durable and verified before the journal is written.
        self.get(recording_id, head.snapshot_id)
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
            if head.recording_id != recording_id or summary.recording_id != recording_id:
                raise ValueError("publication journal recording identity mismatch")
            if summary.head_version != head.version or summary.snapshot_id != head.snapshot_id:
                raise ValueError("publication journal HEAD and summary disagree")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise RecordingSnapshotCorrupt(
                f"recording state publication journal is corrupt: {recording_id}"
            ) from error
        if journal["status"] == "prepared":
            self._finish_journal(recording_id, journal)

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
        if destination.exists():
            return self._existing_or_conflict(destination, raw, verified_snapshot)

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with staging_directory(destination.parent, prefix=".snapshot-") as staging:
                (staging / "snapshot.json").write_bytes(raw)
                (staging / "metadata.json").write_bytes(_canonical_json(metadata))
                commit_staged_directory(staging, destination)
        except FileExistsError:
            return self._existing_or_conflict(destination, raw, verified_snapshot)
        return StoredRecordingSnapshot(verified_snapshot, digest, metadata["stage_metadata"])

    def get(self, recording_id: str, snapshot_id: str) -> StoredRecordingSnapshot:
        """Read exactly one snapshot and its compact metadata, without listing history."""
        directory = self.snapshot_path(recording_id, snapshot_id)
        if not directory.is_dir():
            raise RecordingSnapshotNotFound(f"snapshot not found: {recording_id}/{snapshot_id}")
        try:
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
