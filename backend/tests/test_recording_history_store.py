from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from dokodetector_backend.recording_history_store import (
    RecordingHistoryConflict,
    RecordingHistoryCorrupt,
    RecordingHistoryCursorExpired,
    RecordingHistoryRebuildRequired,
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


def _process_stop_after_initial_generation_commit(root: str) -> None:
    store = RecordingHistoryStore(root)

    def stop_after(boundary: str) -> None:
        if boundary == "rebuild_generation_committed":
            os._exit(73)

    store._after_durable_boundary = stop_after
    store.rebuild("recording-1", [_snapshot("snapshot-1"), _snapshot("snapshot-2", "b")])


def _process_stop_during_initial_generation_staging(root: str, mode: str) -> None:
    store = RecordingHistoryStore(root)
    if mode == "replacement":
        store.publish("recording-1", _snapshot("snapshot-old"))

    def stop_during_staging(boundary: str) -> None:
        if boundary == ("rebuild_staging_started" if mode == "empty" else "rebuild_item_staged"):
            os._exit(74)

    store._after_durable_boundary = stop_during_staging
    if mode == "empty":
        store.get_authority("recording-1")
    else:
        store.rebuild(
            "recording-1",
            [_snapshot("snapshot-1"), _snapshot("snapshot-2", "b")]
            if mode == "nonempty"
            else [_snapshot("snapshot-new")],
        )


def _process_stop_after_retry_journal_replacement(root: str) -> None:
    store = RecordingHistoryStore(root)

    def stop_after(boundary: str) -> None:
        if boundary == "rebuild_journal":
            os._exit(75)

    store._after_durable_boundary = stop_after
    store.rebuild("recording-1", [_snapshot("snapshot-1"), _snapshot("snapshot-2", "b")])


def _process_stop_before_retry_journal_replacement(root: str) -> None:
    store = RecordingHistoryStore(root)

    def stop_before(boundary: str) -> None:
        if boundary == "rebuild_before_journal_replacement":
            os._exit(76)

    store._after_durable_boundary = stop_before
    store.rebuild("recording-1", [_snapshot("snapshot-1"), _snapshot("snapshot-2", "b")])


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


@pytest.mark.parametrize("failure", ["metadata_digest", "authority_sequence"])
def test_read_and_duplicate_publish_reject_corrupt_metadata(tmp_path: Path, failure: str):
    store = RecordingHistoryStore(tmp_path)
    item = store.publish("recording-1", _snapshot("snapshot-1"))
    authority = store.get_authority("recording-1")
    generation_root = (
        tmp_path / "recording-history" / "recording-1" / "generations" / authority.generation
    )
    path = next((generation_root / "items" / "snapshots").glob("*.json"))
    document = json.loads(path.read_text(encoding="utf-8"))
    if failure == "metadata_digest":
        document["item"]["sha256"] = "b" * 64
    else:
        document["item"]["publication_sequence"] = authority.sequence + 1
        document["item_sha256"] = hashlib.sha256(
            json.dumps(
                document["item"], sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
        ).hexdigest()
    path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        encoding="utf-8",
    )

    with pytest.raises(RecordingHistoryCorrupt):
        store.read_item("recording-1", "snapshots", "snapshot-1")
    with pytest.raises(RecordingHistoryCorrupt):
        store.publish("recording-1", item)


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


def test_initial_generation_commit_survives_process_death_before_active_pointer(tmp_path: Path):
    context = multiprocessing.get_context("spawn")
    worker = context.Process(
        target=_process_stop_after_initial_generation_commit, args=(str(tmp_path),)
    )
    worker.start()
    worker.join(timeout=20)
    assert worker.exitcode == 73
    assert not (tmp_path / "recording-history" / "recording-1" / "active.json").exists()

    restarted = RecordingHistoryStore(tmp_path)
    authority = restarted.get_authority("recording-1")
    assert authority.sequence == 2
    assert restarted.read_item("recording-1", "snapshots", "snapshot-1").publication_sequence == 1
    assert restarted.read_item("recording-1", "snapshots", "snapshot-2").publication_sequence == 2


def test_empty_initialization_recovers_process_death_during_staging(tmp_path: Path):
    context = multiprocessing.get_context("spawn")
    worker = context.Process(
        target=_process_stop_during_initial_generation_staging, args=(str(tmp_path), "empty")
    )
    worker.start()
    worker.join(timeout=20)
    assert worker.exitcode == 74

    authority = RecordingHistoryStore(tmp_path).get_authority("recording-1")
    assert authority.sequence == 0


def test_nonempty_initial_rebuild_can_retry_after_process_death_during_staging(
    tmp_path: Path,
):
    context = multiprocessing.get_context("spawn")
    worker = context.Process(
        target=_process_stop_during_initial_generation_staging, args=(str(tmp_path), "nonempty")
    )
    worker.start()
    worker.join(timeout=20)
    assert worker.exitcode == 74

    restarted = RecordingHistoryStore(tmp_path)
    with pytest.raises(RecordingHistoryRebuildRequired, match="retry rebuild"):
        restarted.get_authority("recording-1")
    restarted.rebuild("recording-1", [_snapshot("snapshot-1"), _snapshot("snapshot-2", "b")])
    assert restarted.get_authority("recording-1").sequence == 2
    assert restarted.read_item("recording-1", "snapshots", "snapshot-1").publication_sequence == 1


def test_invalid_initial_rebuild_retry_keeps_pending_journal(tmp_path: Path):
    context = multiprocessing.get_context("spawn")
    worker = context.Process(
        target=_process_stop_during_initial_generation_staging, args=(str(tmp_path), "nonempty")
    )
    worker.start()
    worker.join(timeout=20)
    assert worker.exitcode == 74

    restarted = RecordingHistoryStore(tmp_path)
    with pytest.raises(RecordingHistoryConflict, match="duplicate history item keys"):
        restarted.rebuild("recording-1", [_snapshot("duplicate"), _snapshot("duplicate", "b")])
    with pytest.raises(RecordingHistoryRebuildRequired, match="retry rebuild"):
        restarted.get_authority("recording-1")

    restarted.rebuild("recording-1", [_snapshot("snapshot-1"), _snapshot("snapshot-2", "b")])
    assert restarted.get_authority("recording-1").sequence == 2


def test_process_death_after_retry_journal_replacement_requires_retry(tmp_path: Path):
    context = multiprocessing.get_context("spawn")
    first = context.Process(
        target=_process_stop_during_initial_generation_staging, args=(str(tmp_path), "nonempty")
    )
    first.start()
    first.join(timeout=20)
    assert first.exitcode == 74

    retry = context.Process(
        target=_process_stop_after_retry_journal_replacement, args=(str(tmp_path),)
    )
    retry.start()
    retry.join(timeout=20)
    assert retry.exitcode == 75

    restarted = RecordingHistoryStore(tmp_path)
    with pytest.raises(RecordingHistoryRebuildRequired, match="retry rebuild"):
        restarted.get_authority("recording-1")
    restarted.rebuild("recording-1", [_snapshot("snapshot-1"), _snapshot("snapshot-2", "b")])
    assert restarted.get_authority("recording-1").sequence == 2


def test_process_death_before_retry_journal_replacement_keeps_old_journal(tmp_path: Path):
    context = multiprocessing.get_context("spawn")
    first = context.Process(
        target=_process_stop_during_initial_generation_staging, args=(str(tmp_path), "nonempty")
    )
    first.start()
    first.join(timeout=20)
    assert first.exitcode == 74

    retry = context.Process(
        target=_process_stop_before_retry_journal_replacement, args=(str(tmp_path),)
    )
    retry.start()
    retry.join(timeout=20)
    assert retry.exitcode == 76

    restarted = RecordingHistoryStore(tmp_path)
    with pytest.raises(RecordingHistoryRebuildRequired, match="retry rebuild"):
        restarted.get_authority("recording-1")
    restarted.rebuild("recording-1", [_snapshot("snapshot-1"), _snapshot("snapshot-2", "b")])
    assert restarted.get_authority("recording-1").sequence == 2


def test_rebuild_death_during_staging_keeps_previous_generation_active(tmp_path: Path):
    context = multiprocessing.get_context("spawn")
    worker = context.Process(
        target=_process_stop_during_initial_generation_staging,
        args=(str(tmp_path), "replacement"),
    )
    worker.start()
    worker.join(timeout=20)
    assert worker.exitcode == 74

    restarted = RecordingHistoryStore(tmp_path)
    authority = restarted.get_authority("recording-1")
    assert authority.sequence == 1
    assert restarted.read_item("recording-1", "snapshots", "snapshot-old").publication_sequence == 1


def test_rebuild_validates_generation_before_switching_active_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = RecordingHistoryStore(tmp_path)
    original_generation = store.get_authority("recording-1").generation
    original_write = store._write_item_file

    def write_corrupt(path: Path, item) -> None:
        original_write(path, item)
        if item.item_key == "revision-1":
            document = json.loads(path.read_text(encoding="utf-8"))
            document["item_sha256"] = "0" * 64
            path.write_text(
                json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
                encoding="utf-8",
            )

    monkeypatch.setattr(store, "_write_item_file", write_corrupt)
    with pytest.raises(RecordingHistoryCorrupt, match="digest or collection mismatch"):
        store.rebuild(
            "recording-1", [_snapshot("snapshot-1"), _revision("revision-1", "revision-1")]
        )

    assert store.get_authority("recording-1").generation == original_generation
    assert store.get_authority("recording-1").sequence == 0


def test_missing_active_pointer_does_not_discard_existing_generation(tmp_path: Path):
    store = RecordingHistoryStore(tmp_path)
    store.publish("recording-1", _snapshot("snapshot-1"))
    active_path = tmp_path / "recording-history" / "recording-1" / "active.json"
    active_path.unlink()

    with pytest.raises(RecordingHistoryCorrupt, match="without an active pointer"):
        RecordingHistoryStore(tmp_path).get_authority("recording-1")
    with pytest.raises(RecordingHistoryCorrupt, match="without an active pointer"):
        RecordingHistoryStore(tmp_path).read_item("recording-1", "snapshots", "snapshot-1")


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
