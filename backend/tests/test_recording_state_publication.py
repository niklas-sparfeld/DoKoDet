from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

import pytest
from test_recording_state_store import _snapshot

from dokodetector_backend.recording_state_contract import RecordingHeadUpdate
from dokodetector_backend.recording_state_store import (
    RecordingHeadConflict,
    RecordingHeadNotFound,
    RecordingStateSnapshotStore,
)


def _publish_worker(root: str, snapshot_id: str, barrier, results) -> None:
    store = RecordingStateSnapshotStore(root)
    barrier.wait()
    try:
        state = store.publish(
            RecordingHeadUpdate(
                recording_id="recording-1",
                expected_head_version=1,
                snapshot_id=snapshot_id,
                action="select_snapshot",
            )
        )
        results.put(("published", state.head.version, snapshot_id))
    except RecordingHeadConflict:
        results.put(("conflict", None, snapshot_id))


def _reader_worker(root: str, stop, failures) -> None:
    store = RecordingStateSnapshotStore(root)
    while not stop.is_set():
        try:
            state = store.get_current("recording-1")
            if (
                state.summary.head_version != state.head.version
                or state.summary.snapshot_id != state.head.snapshot_id
                or state.snapshot.snapshot_id != state.head.snapshot_id
            ):
                failures.put("mixed state")
                return
        except Exception as error:  # pragma: no cover - reports child-process failures
            failures.put(repr(error))
            return


def _prepare(root: Path):
    store = RecordingStateSnapshotStore(root)
    first = _snapshot()
    store.put(first)
    state = store.initialize("recording-1", first.snapshot_id)
    second = _snapshot(first.snapshot_id)
    # Vary the exact immutable snapshot identity while keeping every slot valid.
    second.predecessor_snapshot_id = first.snapshot_id
    from dokodetector_backend.recording_state_contract import RecordingStateSnapshot

    second = RecordingStateSnapshot.model_validate(second.model_dump(mode="json"))
    store.put(second)
    third = _snapshot(second.snapshot_id)
    third.independent_reviews = []
    third.predecessor_snapshot_id = second.snapshot_id
    third_payload = third.model_dump(mode="json")
    import hashlib
    import json

    third_payload["snapshot_id"] = (
        "rs_"
        + hashlib.sha256(
            json.dumps(
                {key: value for key, value in third_payload.items() if key != "snapshot_id"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
    )
    third = RecordingStateSnapshot.model_validate(third_payload)
    store.put(third)
    assert state.head.version == 1
    return store, first, second, third


def test_two_processes_compare_and_swap_one_head(tmp_path: Path) -> None:
    store, _, second, third = _prepare(tmp_path)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_publish_worker,
            args=(str(tmp_path), snapshot.snapshot_id, barrier, results),
        )
        for snapshot in (second, third)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0

    outcomes = [results.get(timeout=2)[0] for _ in processes]
    assert sorted(outcomes) == ["conflict", "published"]
    current = store.get_current("recording-1")
    assert current.head.version == 2
    assert current.head.snapshot_id in {second.snapshot_id, third.snapshot_id}
    assert current.summary.head_version == current.head.version


def test_concurrent_reader_observes_only_complete_old_or_new_state(tmp_path: Path) -> None:
    store, _, second, _ = _prepare(tmp_path)
    context = multiprocessing.get_context("spawn")
    stop = context.Event()
    failures = context.Queue()
    reader = context.Process(target=_reader_worker, args=(str(tmp_path), stop, failures))
    reader.start()
    try:
        for version in range(1, 8):
            previous = store.get_current("recording-1")
            snapshot = second if version % 2 else _snapshot(previous.head.snapshot_id)
            if snapshot.snapshot_id == previous.head.snapshot_id:
                # Reuse an already persisted snapshot with a distinct predecessor.
                snapshot = second
            stored = store.put(snapshot)
            store.publish(
                RecordingHeadUpdate(
                    recording_id="recording-1",
                    expected_head_version=previous.head.version,
                    snapshot_id=stored.snapshot.snapshot_id,
                    action="select_snapshot",
                )
            )
            time.sleep(0.005)
    finally:
        stop.set()
        reader.join(20)
    assert reader.exitcode == 0
    assert failures.empty()


@pytest.mark.parametrize("boundary", ["journal_prepared", "head", "summary", "journal_committed"])
def test_interrupted_publication_recovers_and_summary_is_fresh(
    tmp_path: Path, boundary: str
) -> None:
    store, _, second, _ = _prepare(tmp_path)

    class SimulatedCrash(BaseException):
        pass

    def crash_after(target: str) -> None:
        if target == boundary:
            raise SimulatedCrash

    store._after_durable_boundary = crash_after
    with pytest.raises(SimulatedCrash):
        store.publish(
            RecordingHeadUpdate(
                recording_id="recording-1",
                expected_head_version=1,
                snapshot_id=second.snapshot_id,
                action="select_snapshot",
            )
        )

    restarted = RecordingStateSnapshotStore(tmp_path)
    current = restarted.get_current("recording-1")
    assert current.head.version == 2
    assert current.head.snapshot_id == second.snapshot_id
    assert current.summary.head_version == 2
    assert current.summary.snapshot_id == second.snapshot_id
    assert restarted._read_summary("recording-1") == current.summary


def test_orphan_snapshot_does_not_reconstruct_recording_authority(tmp_path: Path) -> None:
    store = RecordingStateSnapshotStore(tmp_path)
    snapshot = _snapshot()
    store.put(snapshot)

    with pytest.raises(RecordingHeadNotFound):
        store.get_current(snapshot.recording_id)


def test_missing_stale_expected_version_is_rejected(tmp_path: Path) -> None:
    store, _, second, _ = _prepare(tmp_path)
    with pytest.raises(RecordingHeadConflict, match="expected recording HEAD 2"):
        store.publish(
            RecordingHeadUpdate(
                recording_id="recording-1",
                expected_head_version=2,
                snapshot_id=second.snapshot_id,
                action="restore_snapshot",
            )
        )
