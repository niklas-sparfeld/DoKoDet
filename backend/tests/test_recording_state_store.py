from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dokodetector_backend.recording_state_contract import (
    ExactResourceRef,
    RecordingStateSnapshot,
    SlotSelection,
    StageSelection,
)
from dokodetector_backend.recording_state_store import (
    RecordingSnapshotCorrupt,
    RecordingSnapshotNotFound,
    RecordingStateSnapshotStore,
)


def _snapshot(predecessor: str | None = None) -> RecordingStateSnapshot:
    slots = {}
    for slot in (
        "events",
        "visible_cards",
        "table_plane_calibration",
        "virtual_scenes",
        "visual_identities",
        "table_observations",
        "reconstruction_results",
    ):
        slots[slot] = StageSelection(
            generated=SlotSelection(state="empty"),
            completed_reference=SlotSelection(state="empty"),
        )
    selected = ExactResourceRef(
        kind="pipeline-node-revision",
        resource_id="revision-1",
        schema_version="pipeline-data-revision/v1",
        sha256="a" * 64,
        node_id="node-1",
        revision_id="revision-1",
    )
    slots["events"] = StageSelection(
        generated=SlotSelection(state="selected", resource=selected),
        completed_reference=SlotSelection(state="empty"),
    )
    payload = {
        "schema_version": "recording-state-snapshot/v1",
        "recording_id": "recording-1",
        "predecessor_snapshot_id": predecessor,
        "slots": slots,
        "independent_reviews": [],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=lambda value: value.model_dump(mode="json"),
    ).encode()
    payload["snapshot_id"] = "rs_" + hashlib.sha256(canonical).hexdigest()
    return RecordingStateSnapshot.model_validate(payload)


def test_snapshot_round_trip_and_duplicate_identity_are_idempotent(tmp_path: Path) -> None:
    store = RecordingStateSnapshotStore(tmp_path / "isolated-operations")
    snapshot = _snapshot()

    first = store.put(snapshot)
    duplicate = store.put(snapshot)
    reopened = RecordingStateSnapshotStore(tmp_path / "isolated-operations").get(
        snapshot.recording_id, snapshot.snapshot_id
    )

    assert store.root == (
        (tmp_path / "isolated-operations").resolve() / "recording-state" / "snapshots"
    )
    assert first == duplicate == reopened
    assert reopened.snapshot == snapshot
    assert (
        reopened.snapshot.slots["events"].generated.resource
        == snapshot.slots["events"].generated.resource
    )
    assert reopened.stage_metadata["events"]["generated"] == "selected"
    assert set(reopened.stage_metadata) == set(snapshot.slots)


def test_snapshot_read_is_direct_and_constant_as_history_grows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RecordingStateSnapshotStore(tmp_path)
    snapshots = [_snapshot()]
    store.put(snapshots[0])
    for _ in range(10):
        snapshots.append(_snapshot(snapshots[-1].snapshot_id))
        store.put(snapshots[-1])

    reads: list[Path] = []
    original = Path.read_bytes

    def counted_read(path: Path) -> bytes:
        reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read)
    result = store.get("recording-1", snapshots[0].snapshot_id)

    assert result.snapshot.snapshot_id == snapshots[0].snapshot_id
    assert len(reads) == 2
    assert {path.name for path in reads} == {"snapshot.json", "metadata.json"}


def test_missing_and_corrupt_snapshots_are_typed_and_isolated(tmp_path: Path) -> None:
    store = RecordingStateSnapshotStore(tmp_path)
    with pytest.raises(RecordingSnapshotNotFound):
        store.get("recording-1", _snapshot().snapshot_id)

    snapshot = _snapshot()
    stored = store.put(snapshot)
    (store.snapshot_path("recording-1", snapshot.snapshot_id) / "snapshot.json").write_bytes(b"{}")
    with pytest.raises(RecordingSnapshotCorrupt):
        store.get("recording-1", snapshot.snapshot_id)
    assert stored.snapshot.recording_id == "recording-1"
    assert not store.snapshot_path("recording-2", snapshot.snapshot_id).exists()


def test_corrupt_duplicate_identity_is_not_overwritten(tmp_path: Path) -> None:
    store = RecordingStateSnapshotStore(tmp_path)
    snapshot = _snapshot()
    store.put(snapshot)
    path = store.snapshot_path("recording-1", snapshot.snapshot_id) / "metadata.json"
    path.write_bytes(b"{}")

    with pytest.raises(RecordingSnapshotCorrupt):
        store.put(snapshot)
    assert path.read_bytes() == b"{}"


def test_snapshot_identity_is_scoped_to_recording(tmp_path: Path) -> None:
    store = RecordingStateSnapshotStore(tmp_path)
    snapshot = _snapshot()
    store.put(snapshot)

    with pytest.raises(RecordingSnapshotNotFound):
        store.get("recording-2", snapshot.snapshot_id)
