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

from dokodetector_backend.recording_history_store import RecordingHistoryStore
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


def _snapshot_history_crash_worker(root: str, snapshot_data: dict, boundary: str) -> None:
    from dokodetector_backend.recording_state_contract import RecordingStateSnapshot

    store = RecordingStateSnapshotStore(root)

    def terminate_after(target: str) -> None:
        if target == boundary:
            os._exit(73)

    store._after_durable_boundary = terminate_after
    store.put(RecordingStateSnapshot.model_validate(snapshot_data))


def _put_snapshot_worker(root: str, snapshot_data: dict, barrier, results) -> None:
    from dokodetector_backend.recording_state_contract import RecordingStateSnapshot

    barrier.wait()
    stored = RecordingStateSnapshotStore(root).put(
        RecordingStateSnapshot.model_validate(snapshot_data)
    )
    results.put(stored.snapshot.snapshot_id)


def _paused_publish_worker(root: str, snapshot_id: str, head_replaced, release) -> None:
    store = RecordingStateSnapshotStore(root)

    def pause_after_head(target: str) -> None:
        if target == "head":
            head_replaced.set()
            if not release.wait(10):
                raise TimeoutError("reader contention test did not release publisher")

    store._after_durable_boundary = pause_after_head
    store.publish(
        RecordingHeadUpdate(
            recording_id="recording-1",
            expected_head_version=1,
            snapshot_id=snapshot_id,
            action="select_snapshot",
        )
    )


def _single_read_worker(root: str, attempt_started, contention_confirmed, results) -> None:
    from fcntl import LOCK_EX, LOCK_NB
    from fcntl import flock as real_flock

    from dokodetector_backend import pipeline_storage

    def observe_lock_attempt(fd: int, operation: int) -> None:
        if operation == LOCK_EX:
            attempt_started.set()
            try:
                real_flock(fd, LOCK_EX | LOCK_NB)
            except BlockingIOError:
                contention_confirmed.set()
                real_flock(fd, LOCK_EX)
            return
        real_flock(fd, operation)

    pipeline_storage.flock = observe_lock_attempt
    store = RecordingStateSnapshotStore(root)
    try:
        state = store.get_current("recording-1")
        results.put(
            (
                "read",
                state.head.version,
                state.head.snapshot_id,
                state.snapshot.snapshot_id,
                state.summary.head_version,
                state.summary.snapshot_id,
            )
        )
    except Exception as error:  # pragma: no cover - reports child-process failures
        results.put(("error", repr(error)))


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


@pytest.mark.parametrize("boundary", ["history_outbox", "snapshot", "history_published"])
def test_snapshot_history_outbox_recovers_after_process_death(
    tmp_path: Path, boundary: str
) -> None:
    from test_recording_state_store import _snapshot

    snapshot = _snapshot()
    process = multiprocessing.get_context("fork").Process(
        target=_snapshot_history_crash_worker,
        args=(str(tmp_path), snapshot.model_dump(mode="json"), boundary),
    )
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 73

    state_store = RecordingStateSnapshotStore(tmp_path)
    history = RecordingHistoryStore(tmp_path)
    outbox = state_store._snapshot_history_outbox_path(snapshot.recording_id)
    if boundary == "history_outbox":
        assert not state_store.snapshot_path(snapshot.recording_id, snapshot.snapshot_id).exists()
        state_store.reconcile_snapshot_history_outbox(snapshot.recording_id)
        assert history.get_authority(snapshot.recording_id).sequence == 0
        state_store.put(snapshot)
    else:
        assert state_store.snapshot_path(snapshot.recording_id, snapshot.snapshot_id).is_dir()
        assert outbox.exists()
        state_store.reconcile_snapshot_history_outbox(snapshot.recording_id)

    authority = history.get_authority(snapshot.recording_id)
    assert authority.sequence == 1
    _, items, has_more = history.ordered_page(
        snapshot.recording_id, "snapshots", upper_bound_sequence=1, limit=10
    )
    assert [item.snapshot_id for item in items] == [snapshot.snapshot_id]
    assert not has_more
    state_store.reconcile_snapshot_history_outbox(snapshot.recording_id)
    assert history.get_authority(snapshot.recording_id).sequence == 1


def test_snapshot_history_recovery_fails_closed_on_corrupt_committed_source(tmp_path: Path) -> None:
    from test_recording_state_store import _snapshot

    snapshot = _snapshot()
    store = RecordingStateSnapshotStore(tmp_path)

    def stop_after_source(boundary: str) -> None:
        if boundary == "snapshot":
            raise RuntimeError("stop")

    store._after_durable_boundary = stop_after_source
    with pytest.raises(RuntimeError, match="stop"):
        store.put(snapshot)
    path = store._snapshot_history_outbox_path(snapshot.recording_id)
    metadata_path = (
        store.snapshot_path(snapshot.recording_id, snapshot.snapshot_id) / "metadata.json"
    )
    metadata = json.loads(metadata_path.read_text())
    metadata["snapshot_sha256"] = "b" * 64
    metadata_path.write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")))

    with pytest.raises(RecordingSnapshotCorrupt, match="source identity"):
        store.reconcile_snapshot_history_outbox(snapshot.recording_id)
    assert path.exists()
    assert RecordingHistoryStore(tmp_path).get_authority(snapshot.recording_id).sequence == 0


def test_concurrent_snapshot_publishers_preserve_both_exact_history_items(tmp_path: Path) -> None:
    from test_recording_state_store import _snapshot

    first = _snapshot()
    second = _snapshot(first.snapshot_id)
    second.predecessor_snapshot_id = first.snapshot_id
    from dokodetector_backend.recording_state_contract import RecordingStateSnapshot

    second = RecordingStateSnapshot.model_validate(second.model_dump(mode="json"))
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_put_snapshot_worker,
            args=(str(tmp_path), snapshot.model_dump(mode="json"), barrier, results),
        )
        for snapshot in (first, second)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0

    assert {results.get(timeout=2), results.get(timeout=2)} == {
        first.snapshot_id,
        second.snapshot_id,
    }
    history = RecordingHistoryStore(tmp_path)
    authority = history.get_authority(first.recording_id)
    assert authority.sequence == 2
    _, items, has_more = history.ordered_page(
        first.recording_id, "snapshots", upper_bound_sequence=2, limit=10
    )
    assert {item.snapshot_id for item in items} == {first.snapshot_id, second.snapshot_id}
    assert len(items) == 2
    assert not has_more


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


def test_reader_waits_for_head_and_summary_publication_to_finish(tmp_path: Path) -> None:
    store, _, second, _ = _prepare(tmp_path)
    context = multiprocessing.get_context("spawn")
    head_replaced = context.Event()
    release_publisher = context.Event()
    lock_attempt_started = context.Event()
    lock_contention_confirmed = context.Event()
    results = context.Queue()
    publisher = context.Process(
        target=_paused_publish_worker,
        args=(str(tmp_path), second.snapshot_id, head_replaced, release_publisher),
    )
    reader = context.Process(
        target=_single_read_worker,
        args=(str(tmp_path), lock_attempt_started, lock_contention_confirmed, results),
    )
    publisher.start()
    try:
        assert head_replaced.wait(10), "publisher did not pause after replacing HEAD"
        assert store._read_head("recording-1").version == 2
        assert store._read_summary("recording-1").head_version == 1

        reader.start()
        assert lock_attempt_started.wait(10), "reader did not reach the process-lock attempt"
        assert lock_contention_confirmed.wait(10), (
            "reader lock attempt was not blocked by publisher"
        )
        with pytest.raises(queue.Empty):
            results.get(timeout=0.2)

        release_publisher.set()
        publisher.join(20)
        reader.join(20)
        assert publisher.exitcode == 0
        assert reader.exitcode == 0
        assert results.get(timeout=2) == (
            "read",
            2,
            second.snapshot_id,
            second.snapshot_id,
            2,
            second.snapshot_id,
        )
    finally:
        release_publisher.set()
        if publisher.is_alive():
            publisher.join(20)
        if reader.is_alive():
            reader.join(20)


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
