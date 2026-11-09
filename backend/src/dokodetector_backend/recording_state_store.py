"""Immutable recording-state snapshots with direct, history-independent reads."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dokodetector_backend.filesystem import (
    commit_staged_directory,
    contained_path,
    staging_directory,
)
from dokodetector_backend.recording_state_contract import RecordingStateSnapshot


class RecordingSnapshotNotFound(FileNotFoundError):
    """The requested immutable recording snapshot does not exist."""


class RecordingSnapshotCorrupt(ValueError):
    """Persisted snapshot bytes or their compact metadata fail validation."""


class RecordingSnapshotConflict(ValueError):
    """An immutable snapshot identity already contains different bytes."""


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
