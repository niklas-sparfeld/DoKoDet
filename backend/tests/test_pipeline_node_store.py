import multiprocessing
import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
from dokodetector_backend.pipeline_node_store import (
    NodeConflict,
    PipelineNodeStore,
    atomic_replace_json,
)
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}


def events(start: int) -> dict:
    return {
        "schema_version": "event-data/v1",
        "events": [
            {
                "event_id": "e1",
                "event_type": "card_state_changed",
                "start_us": start,
                "end_us": start + 100,
            }
        ],
    }


def _crash_during_node_save(root: str, boundary: str) -> None:
    store = PipelineNodeStore(root)
    first = store.get("n")

    def terminate(target: str) -> None:
        if target == boundary:
            os._exit(72)

    store._after_durable_boundary = terminate
    store.save("n", first.head_revision_id, events(2), {}, revision_id="revision-2")


def _write_node_revisions(root: str, start, reader_ready, failures) -> None:
    store = PipelineNodeStore(root)
    try:
        start.wait()
        reader_ready.wait()
        current = store.get("n").head_revision_id
        for value in range(2, 22):
            current = store.save("n", current, events(value), {}).revision_id
            time.sleep(0.005)
    except Exception as error:  # pragma: no cover - reported to the parent process
        failures.put(repr(error))


def _competing_node_save(root: str, expected: str, start, result, value: int) -> None:
    store = PipelineNodeStore(root)
    start.wait()
    try:
        revision = store.save("n", expected, events(value), {})
    except NodeConflict:
        result.put("conflict")
    else:
        result.put(revision.revision_id)


def _read_node_revisions(root: str, start, ready, stop, observations, failures) -> None:
    store = PipelineNodeStore(root)
    try:
        start.wait()
        while not stop.is_set():
            head = store.get("n").head_revision_id
            revision = store.read_authorized_revision("n", head)
            observations.put(revision.revision_id)
            ready.set()
    except Exception as error:  # pragma: no cover - reported to the parent process
        failures.put(repr(error))


def test_save_history_noop_restart_and_conflict(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    first = store.create("node-a", "Events", "events", SOURCE, events(10), {"actor": "person"})
    second = store.save("node-a", first.revision_id, events(20), {"actor": "person"})
    assert second.revision_id != first.revision_id
    assert store.save("node-a", second.revision_id, events(20), {"actor": "other"}) == second
    reopened = PipelineNodeStore(tmp_path)
    assert reopened.get("node-a").head_revision_id == second.revision_id
    assert [r.revision_id for r in reopened.history("node-a")] == [
        second.revision_id,
        first.revision_id,
    ]
    assert reopened.read_revision("node-a", first.revision_id).content == events(10)
    assert [node.node_id for node in reopened.list_nodes()] == ["node-a"]
    with pytest.raises(NodeConflict):
        reopened.save("node-a", first.revision_id, events(30), {})
    with pytest.raises(ValueError):
        reopened.save("node-a", second.revision_id, {"schema_version": "wrong"}, {})
    assert reopened.get("node-a").head_revision_id == second.revision_id


def test_concurrent_writers_do_not_overwrite(tmp_path: Path) -> None:
    first = PipelineNodeStore(tmp_path).create("n", "Events", "events", SOURCE, events(1), {})

    def save(start: int) -> str:
        try:
            return (
                PipelineNodeStore(tmp_path)
                .save("n", first.revision_id, events(start), {})
                .revision_id
            )
        except NodeConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [20, 30]))
    assert results.count("conflict") == 1
    assert len(PipelineNodeStore(tmp_path).history("n")) == 2


def test_interrupted_head_update_does_not_publish_revision(tmp_path: Path, monkeypatch) -> None:
    store = PipelineNodeStore(tmp_path)
    first = store.create("n", "Events", "events", SOURCE, events(1), {})

    def fail_head(*args, **kwargs):
        path = Path(args[0])
        if path == tmp_path / "n" / "head.json":
            raise OSError("interrupted")
        return atomic_replace_json(*args, **kwargs)

    monkeypatch.setattr("dokodetector_backend.pipeline_node_store.atomic_replace_json", fail_head)
    with pytest.raises(OSError, match="interrupted"):
        store.save("n", first.revision_id, events(2), {})
    revision_dirs_before_reopen = [
        path for path in (tmp_path / "n" / "revisions").iterdir() if path.name != first.revision_id
    ]
    assert len(revision_dirs_before_reopen) == 1
    unpublished_path = revision_dirs_before_reopen[0]
    assert (unpublished_path / "revision.json").is_file()
    assert not (tmp_path / "n" / "publications" / unpublished_path.name).exists()

    reopened = PipelineNodeStore(tmp_path)
    assert unpublished_path.is_dir()
    assert not (tmp_path / "n" / "publications" / unpublished_path.name).exists()
    assert reopened.get("n").head_revision_id == first.revision_id
    assert [r.revision_id for r in reopened.history("n")] == [first.revision_id]
    unpublished = unpublished_path.name
    with pytest.raises(KeyError):
        reopened.read_revision("n", unpublished)
    with pytest.raises(KeyError):
        reopened.read_published_revision("n", unpublished)
    with pytest.raises(KeyError):
        reopened.read_revision_record("n", unpublished)
    with pytest.raises(KeyError):
        PipelineNodeUses(reopened).accept(
            "orphan-use", [("n", unpublished)], revision_policy="historical"
        )
    reviews = PipelineNodeReviews(reopened)
    with pytest.raises(KeyError):
        reviews.overall(
            "orphan-review",
            "n",
            unpublished,
            "Is this revision approved?",
            "yes",
            {"kind": "human", "id": "reviewer"},
            {"policy": "orphan-test/v1", "evidence": "crash fixture"},
        )
    assert not (tmp_path / ".accepted-uses" / "orphan-use.json").exists()
    assert not (reviews.root / "orphan-review.json").exists()


def test_reader_and_dependent_use_wait_for_node_publication(tmp_path: Path, monkeypatch) -> None:
    store = PipelineNodeStore(tmp_path)
    first = store.create("n", "Events", "events", SOURCE, events(1), {})
    revision_id = "published-after-head"
    revision_written = Event()
    publish_head = Event()
    original_replace = atomic_replace_json

    def pause_before_head(path, value):
        if Path(path) == store._node_path("n") / "head.json":
            revision_written.set()
            assert publish_head.wait(5), "test did not release the HEAD writer"
        return original_replace(path, value)

    monkeypatch.setattr(
        "dokodetector_backend.pipeline_node_store.atomic_replace_json", pause_before_head
    )
    with ThreadPoolExecutor(max_workers=3) as pool:
        writer = pool.submit(
            store.save,
            "n",
            first.revision_id,
            events(20),
            {},
            revision_id=revision_id,
        )
        assert revision_written.wait(5), "writer did not reach the HEAD replacement boundary"
        assert store.has_revision("n", revision_id)
        reader = PipelineNodeStore(tmp_path)
        read_started = Event()

        def read_pending_revision():
            read_started.set()
            return reader.read_authorized_revision("n", revision_id)

        read = pool.submit(read_pending_revision)
        assert read_started.wait(5)
        assert not read.done()

        use_started = Event()

        def accept_pending_revision():
            use_started.set()
            return PipelineNodeUses(PipelineNodeStore(tmp_path)).accept(
                "concurrent-use", [("n", revision_id)]
            )

        dependent = pool.submit(accept_pending_revision)
        assert use_started.wait(5)
        assert not dependent.done()
        publish_head.set()
        published = writer.result(timeout=5)
        assert read.result(timeout=5).content == events(20)
        accepted = dependent.result(timeout=5)

    assert published.revision_id == revision_id
    assert accepted["inputs"] == [{"node_id": "n", "revision_id": revision_id}]
    assert reader.read_published_revision("n", revision_id).content == events(20)


def test_exact_revision_read_uses_one_record_without_parent_traversal(
    tmp_path: Path, monkeypatch
) -> None:
    store = PipelineNodeStore(tmp_path)
    first = store.create("n", "Events", "events", SOURCE, events(1), {})
    revisions = [first]
    for start in range(2, 12):
        revisions.append(store.save("n", revisions[-1].revision_id, events(start), {}))

    reads: list[str] = []
    original = store._read_revision

    def count_revision(node, revision_id):
        reads.append(revision_id)
        return original(node, revision_id)

    monkeypatch.setattr(store, "_read_revision", count_revision)
    result = store.read_authorized_revision("n", first.revision_id)

    assert result.content == events(1)
    assert reads == [first.revision_id]


def test_publication_authority_is_direct_and_rejects_corrupt_record(
    tmp_path: Path,
) -> None:
    store = PipelineNodeStore(tmp_path)
    first = store.create("n", "Events", "events", SOURCE, events(1), {})
    second = store.save("n", first.revision_id, events(2), {})
    authority = tmp_path / "n" / "publications" / first.revision_id / "authority.json"
    assert authority.is_file()
    assert store.read_authorized_revision("n", first.revision_id).content == events(1)

    authority.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="publication authority"):
        store.read_authorized_revision("n", first.revision_id)
    assert store.get("n").head_revision_id == second.revision_id


@pytest.mark.parametrize(
    ("boundary", "published"),
    [
        ("revision", False),
        ("previous_publication", False),
        ("head", True),
        ("publication", True),
    ],
)
def test_process_death_at_node_publication_boundaries_recovers_direct_reads(
    tmp_path: Path, boundary: str, published: bool
) -> None:
    store = PipelineNodeStore(tmp_path)
    first = store.create("n", "Events", "events", SOURCE, events(1), {})
    context = multiprocessing.get_context("spawn")
    worker = context.Process(target=_crash_during_node_save, args=(str(tmp_path), boundary))
    worker.start()
    worker.join(10)
    assert worker.exitcode == 72

    reopened = PipelineNodeStore(tmp_path)
    current = reopened.get("n")
    if published:
        assert current.head_revision_id == "revision-2"
        assert reopened.read_authorized_revision("n", "revision-2").content == events(2)
    else:
        assert current.head_revision_id == first.revision_id
        with pytest.raises(KeyError):
            reopened.read_authorized_revision("n", "revision-2")
    assert reopened.read_authorized_revision("n", first.revision_id).content == events(1)


def test_separate_process_reader_observes_complete_node_heads_during_writes(
    tmp_path: Path,
) -> None:
    PipelineNodeStore(tmp_path).create("n", "Events", "events", SOURCE, events(1), {})
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    ready = context.Event()
    stop = context.Event()
    observations = context.Queue()
    failures = context.Queue()
    writer = context.Process(
        target=_write_node_revisions, args=(str(tmp_path), start, ready, failures)
    )
    reader = context.Process(
        target=_read_node_revisions,
        args=(str(tmp_path), start, ready, stop, observations, failures),
    )
    writer.start()
    reader.start()
    start.set()
    assert ready.wait(10), "reader did not observe an initial node head"
    writer.join(20)
    assert writer.exitcode == 0
    stop.set()
    reader.join(20)
    assert reader.exitcode == 0
    try:
        failure = failures.get_nowait()
    except queue.Empty:
        failure = None
    assert failure is None
    assert observations.get(timeout=2)
    assert len(PipelineNodeStore(tmp_path).history("n")) == 21


def test_separate_process_writers_reject_stale_node_head(tmp_path: Path) -> None:
    first = PipelineNodeStore(tmp_path).create("n", "Events", "events", SOURCE, events(1), {})
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    writers = [
        context.Process(
            target=_competing_node_save,
            args=(str(tmp_path), first.revision_id, start, results, value),
        )
        for value in (20, 30)
    ]
    for writer in writers:
        writer.start()
    start.set()
    for writer in writers:
        writer.join(10)
        assert writer.exitcode == 0
    outcomes = [results.get(timeout=2) for _ in writers]
    assert outcomes.count("conflict") == 1
    assert sum(outcome != "conflict" for outcome in outcomes) == 1
    assert len(PipelineNodeStore(tmp_path).history("n")) == 2


def test_node_enforces_content_type_and_source_duration(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    with pytest.raises(ValueError):
        store.create("n", "Events", "visible_cards", SOURCE, events(1), {})
    with pytest.raises(ValueError):
        store.create("n", "Events", "events", SOURCE, events(10_000_000), {})
    assert store.list_nodes() == ()


def test_visible_card_node_rejects_frame_from_a_different_source_video(tmp_path: Path) -> None:
    frame_identity = {
        "schema_version": "exact-event/v1",
        "source_video_sha256": "b" * 64,
        "requested_time_us": 100,
        "frame_index": 1,
        "presentation_timestamp_us": 100,
        "width": 100,
        "height": 100,
        "decoder_version": "decoder.v1",
        "transform_version": "transform.v1",
        "output_encoding": "png",
        "content_type": "image/png",
        "image_sha256": "c" * 64,
        "policy": "exact-event/v1",
    }
    content = {
        "schema_version": "visible-card-data/v2",
        "outcomes": [
            {
                "event_id": "event-1",
                "frame_identity": frame_identity,
                "status": "empty",
                "candidates": [],
                "ignored_regions": [],
                "pile_regions": [],
                "pile_detection_status": "unsupported",
                "error": None,
            }
        ],
    }
    with pytest.raises(ValueError, match="does not match its source video"):
        PipelineNodeStore(tmp_path).create(
            "visible-cards", "Detector output", "visible_cards", SOURCE, content, {}
        )
