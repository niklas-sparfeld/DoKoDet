from __future__ import annotations

import hashlib
import multiprocessing
from pathlib import Path

import pytest

from dokodetector_backend.recording_history_store import (
    RecordingHistoryConflict,
    RecordingHistoryCorrupt,
    RecordingHistoryCursorExpired,
    RecordingHistoryStore,
)
from dokodetector_backend.recording_state_contract import (
    ExactResourceRef,
    ResourceHistoryItem,
    SnapshotHistoryItem,
)

_DIGEST = hashlib.sha256(b"history item").hexdigest()


def _snapshot(key: str, byte: str = "a") -> SnapshotHistoryItem:
    snapshot_id = "rs_" + byte * 64
    return SnapshotHistoryItem(
        item_key=key,
        snapshot_id=snapshot_id,
        sha256=_DIGEST,
        publication_sequence=1,
    )


def _revision(key: str, revision_id: str) -> ResourceHistoryItem:
    return ResourceHistoryItem(
        collection="revisions",
        item_key=key,
        resource=ExactResourceRef(
            kind="pipeline-node-revision",
            resource_id=revision_id,
            schema_version="pipeline-node-revision/v1",
            sha256=_DIGEST,
            node_id="node-1",
            revision_id=revision_id,
        ),
        publication_sequence=1,
    )


def _process_publish(
    root: str, index: int, start: multiprocessing.synchronize.Event, queue
) -> None:
    try:
        store = RecordingHistoryStore(root)
        start.wait()
        for offset in range(5):
            item_number = index * 5 + offset
            store.publish(
                "recording-1", _snapshot(f"snapshot-{item_number}", format(item_number, "x"))
            )
        queue.put(None)
    except Exception as error:  # pragma: no cover - reported to the parent test
        queue.put(repr(error))


def test_history_publication_assigns_sequence_and_retries_idempotently(tmp_path: Path):
    store = RecordingHistoryStore(tmp_path)
    first = store.publish("recording-1", _snapshot("snapshot-1"))
    retry = store.publish("recording-1", _snapshot("snapshot-1"))

    assert first.publication_sequence == 1
    assert retry == first
    assert store.get_authority("recording-1").sequence == 1
    with pytest.raises(RecordingHistoryConflict):
        store.publish("recording-1", _snapshot("snapshot-1", "c"))


@pytest.mark.parametrize("boundary", ["journal", "item", "authority", "journal_cleared"])
def test_history_publication_recovers_after_each_durable_boundary(tmp_path: Path, boundary: str):
    store = RecordingHistoryStore(tmp_path)

    def stop_after(target: str) -> None:
        if target == boundary:
            raise RuntimeError("simulated process stop")

    store._after_durable_boundary = stop_after
    with pytest.raises(RuntimeError, match="simulated process stop"):
        store.publish("recording-1", _snapshot("snapshot-1"))

    restarted = RecordingHistoryStore(tmp_path)
    assert restarted.get_authority("recording-1").sequence == 1
    assert restarted.read_item("recording-1", "snapshots", "snapshot-1").publication_sequence == 1


def test_rebuild_publishes_a_new_generation_and_expires_old_cursors(tmp_path: Path):
    store = RecordingHistoryStore(tmp_path)
    old_generation = store.get_authority("recording-1").generation

    generation, _ = store.rebuild(
        "recording-1", [_snapshot("snapshot-1"), _revision("revision-1", "revision-1")]
    )

    assert generation != old_generation
    authority = store.get_authority("recording-1")
    assert authority.generation == generation
    assert authority.sequence == 2
    with pytest.raises(RecordingHistoryCursorExpired):
        store.validate_generation("recording-1", old_generation)
    assert store.read_item("recording-1", "snapshots", "snapshot-1").publication_sequence == 2


def test_rebuild_restart_observes_complete_active_generation(tmp_path: Path):
    store = RecordingHistoryStore(tmp_path)

    def stop_after_switch(boundary: str) -> None:
        if boundary == "rebuild_active":
            raise RuntimeError("simulated process stop")

    store._after_durable_boundary = stop_after_switch
    with pytest.raises(RuntimeError, match="simulated process stop"):
        store.rebuild("recording-1", [_snapshot("snapshot-1"), _snapshot("snapshot-2", "b")])

    restarted = RecordingHistoryStore(tmp_path)
    authority = restarted.get_authority("recording-1")
    assert authority.sequence == 2
    assert restarted.read_item("recording-1", "snapshots", "snapshot-1").publication_sequence == 1
    assert restarted.read_item("recording-1", "snapshots", "snapshot-2").publication_sequence == 2


def test_two_process_writers_allocate_unique_monotonic_sequences(tmp_path: Path):
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    queue = context.Queue()
    workers = [
        context.Process(target=_process_publish, args=(str(tmp_path), index, start, queue))
        for index in range(2)
    ]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0
    assert [queue.get(timeout=2) for _ in workers] == [None, None]

    store = RecordingHistoryStore(tmp_path)
    authority = store.get_authority("recording-1")
    entries = list(
        (
            tmp_path / "recording-history" / "recording-1" / "generations" / authority.generation
        ).glob("items/snapshots/*.json")
    )
    assert authority.sequence == 10
    assert len(entries) == 10


def test_corrupt_publication_journal_is_rejected(tmp_path: Path):
    store = RecordingHistoryStore(tmp_path)

    def stop_after_journal(boundary: str) -> None:
        if boundary == "journal":
            raise RuntimeError("stop")

    store._after_durable_boundary = stop_after_journal
    with pytest.raises(RuntimeError):
        store.publish("recording-1", _snapshot("snapshot-1"))
    pending = tmp_path / "recording-history" / "recording-1" / "pending.json"
    pending.write_text('{"broken":true}', encoding="utf-8")

    with pytest.raises(RecordingHistoryCorrupt):
        RecordingHistoryStore(tmp_path).get_authority("recording-1")
