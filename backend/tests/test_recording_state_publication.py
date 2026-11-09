from __future__ import annotations

import json
import multiprocessing
import os
import queue
import shutil
import time
from pathlib import Path

import pytest
from test_recording_state_store import _snapshot

from dokodetector_backend.recording_state_contract import RecordingHeadUpdate
from dokodetector_backend.recording_state_store import (
    RecordingHeadConflict,
    RecordingHeadNotFound,
    RecordingSnapshotCorrupt,
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


def _reader_worker(root: str, stop, ready, observations, failures) -> None:
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
            observations.put((state.head.version, state.head.snapshot_id))
            ready.set()
            time.sleep(0.001)
        except Exception as error:  # pragma: no cover - reports child-process failures
            failures.put(repr(error))
            return


def _crash_worker(root: str, snapshot_id: str, boundary: str) -> None:
    store = RecordingStateSnapshotStore(root)

    def terminate_after(target: str) -> None:
        if target == boundary:
            os._exit(72)

    store._after_durable_boundary = terminate_after
    store.publish(
        RecordingHeadUpdate(
            recording_id="recording-1",
            expected_head_version=1,
            snapshot_id=snapshot_id,
            action="select_snapshot",
        )
    )


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
    store, first, _, _ = _prepare(tmp_path)
    context = multiprocessing.get_context("spawn")
    stop = context.Event()
    ready = context.Event()
    observations = context.Queue()
    failures = context.Queue()
    reader = context.Process(
        target=_reader_worker,
        args=(str(tmp_path), stop, ready, observations, failures),
    )
    reader.start()

    def wait_for_state(version: int, snapshot_id: str) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                observed_version, observed_snapshot = observations.get(timeout=1)
            except queue.Empty:
                continue
            if (observed_version, observed_snapshot) == (version, snapshot_id):
                observed_states.add((observed_version, observed_snapshot))
                return
            observed_states.add((observed_version, observed_snapshot))
        pytest.fail(f"reader did not observe HEAD {version}/{snapshot_id}")

    observed_states: set[tuple[int, str]] = set()
    try:
        assert ready.wait(10), "reader did not complete its initial read"
        wait_for_state(1, first.snapshot_id)
        for _version in range(1, 8):
            previous = store.get_current("recording-1")
            stored = store.put(_snapshot(previous.head.snapshot_id))
            store.publish(
                RecordingHeadUpdate(
                    recording_id="recording-1",
                    expected_head_version=previous.head.version,
                    snapshot_id=stored.snapshot.snapshot_id,
                    action="select_snapshot",
                )
            )
            wait_for_state(previous.head.version + 1, stored.snapshot.snapshot_id)
    finally:
        stop.set()
        reader.join(20)
    assert reader.exitcode == 0
    assert failures.empty()
    assert {version for version, _ in observed_states} == set(range(1, 9))


@pytest.mark.parametrize("boundary", ["journal_prepared", "head", "summary", "journal_committed"])
def test_process_crash_at_durable_boundary_recovers_and_summary_is_fresh(
    tmp_path: Path, boundary: str
) -> None:
    store, _, second, _ = _prepare(tmp_path)
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_crash_worker,
        args=(str(tmp_path), second.snapshot_id, boundary),
    )
    process.start()
    process.join(20)
    assert process.exitcode == 72

    restarted = RecordingStateSnapshotStore(tmp_path)
    current = restarted.get_current("recording-1")
    assert current.head.version == 2
    assert current.head.snapshot_id == second.snapshot_id
    assert current.summary.head_version == 2
    assert current.summary.snapshot_id == second.snapshot_id
    assert restarted._read_summary("recording-1") == current.summary


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_publication_cannot_replace_a_missing_or_corrupt_current_snapshot(
    tmp_path: Path, damage: str
) -> None:
    store, _, second, _ = _prepare(tmp_path)
    current = store.get_current("recording-1")
    current_path = store.snapshot_path("recording-1", current.head.snapshot_id)
    if damage == "missing":
        shutil.rmtree(current_path)
    else:
        (current_path / "snapshot.json").write_bytes(b"{}")

    with pytest.raises(RecordingSnapshotCorrupt):
        store.publish(
            RecordingHeadUpdate(
                recording_id="recording-1",
                expected_head_version=1,
                snapshot_id=second.snapshot_id,
                action="select_snapshot",
            )
        )
    assert store._read_head("recording-1").version == 1


@pytest.mark.parametrize("operation", ["initialize", "publish"])
def test_missing_head_after_publication_cannot_be_reinitialized(
    tmp_path: Path, operation: str
) -> None:
    store, _, second, _ = _prepare(tmp_path)
    store.head_path("recording-1").unlink()

    with pytest.raises(RecordingSnapshotCorrupt):
        if operation == "initialize":
            store.initialize("recording-1", second.snapshot_id)
        else:
            store.publish(
                RecordingHeadUpdate(
                    recording_id="recording-1",
                    expected_head_version=1,
                    snapshot_id=second.snapshot_id,
                    action="select_snapshot",
                )
            )


def test_recovery_rejects_prepared_journal_with_wrong_derived_summary(
    tmp_path: Path,
) -> None:
    _, _, second, _ = _prepare(tmp_path)
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_crash_worker,
        args=(str(tmp_path), second.snapshot_id, "journal_prepared"),
    )
    process.start()
    process.join(20)
    assert process.exitcode == 72

    restarted = RecordingStateSnapshotStore(tmp_path)
    journal_path = restarted.transaction_path("recording-1")
    journal = json.loads(journal_path.read_bytes())
    journal["summary"]["slots"]["events"]["generated"] = "empty"
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(RecordingSnapshotCorrupt, match="summary does not match"):
        restarted.get_current("recording-1")
    assert restarted._read_head("recording-1").version == 1


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
