import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dokodetector_backend.pipeline_node_store import NodeConflict, NodeUsed, PipelineNodeStore
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses
from dokodetector_backend.recording_history_store import RecordingHistoryStore

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}


def content(end: int) -> dict:
    return {
        "schema_version": "event-data/v1",
        "events": [
            {"event_id": "e", "event_type": "card_state_changed", "start_us": 100, "end_us": end}
        ],
    }


def test_accepted_use_is_durable_and_guards_edits(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    revision = store.create("n", "Events", "events", SOURCE, content(200), {})
    uses = PipelineNodeUses(store)
    accepted = uses.accept("run", [("n", revision.revision_id)])
    assert (
        PipelineNodeUses(PipelineNodeStore(tmp_path)).accept("run", [("n", revision.revision_id)])
        == accepted
    )
    assert store.save("n", revision.revision_id, content(200), {}) == revision
    with pytest.raises(NodeUsed):
        store.save("n", revision.revision_id, content(300), {})
    with pytest.raises(NodeConflict):
        uses.accept("run", [("n", "different")])


def test_historical_acceptance_is_explicit_exact_and_idempotent(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    first = store.create("n", "Events", "events", SOURCE, content(200), {})
    second = store.save("n", first.revision_id, content(300), {})
    uses = PipelineNodeUses(store)

    accepted = uses.accept(
        "historical-run", [("n", first.revision_id)], revision_policy="historical"
    )
    assert accepted["inputs"] == [{"node_id": "n", "revision_id": first.revision_id}]
    assert (
        uses.accept("historical-run", [("n", first.revision_id)], revision_policy="historical")
        == accepted
    )
    assert store.get("n").head_revision_id == second.revision_id


def test_historical_acceptance_requires_revision_on_specified_node(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    store.create("n", "Events", "events", SOURCE, content(200), {})
    with pytest.raises(KeyError, match="missing"):
        PipelineNodeUses(store).accept(
            "missing-run", [("n", "missing")], revision_policy="historical"
        )


def test_current_head_acceptance_rejects_changed_head(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    first = store.create("n", "Events", "events", SOURCE, content(200), {})
    store.save("n", first.revision_id, content(300), {})
    with pytest.raises(NodeConflict, match="working head changed"):
        PipelineNodeUses(store).accept("stale-run", [("n", first.revision_id)])


def test_recording_revision_history_publication_is_idempotent_after_restart(
    tmp_path: Path,
) -> None:
    store = PipelineNodeStore(tmp_path / "pipeline-nodes")
    first = store.create("n", "Events", "events", SOURCE, content(200), {})
    second = store.save("n", first.revision_id, content(300), {})

    history = RecordingHistoryStore(tmp_path)
    _, page, _ = history.ordered_page("recording-01", "revisions", limit=10)
    assert {item.resource.revision_id for item in page} == {first.revision_id, second.revision_id}
    assert all(item.resource.sha256 for item in page)


def test_concurrent_recording_revision_writers_publish_one_exact_winner(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path / "pipeline-nodes")
    first = store.create("n", "Events", "events", SOURCE, content(200), {})
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(store.save, "n", first.revision_id, content(end), {}) for end in (300, 400)
        ]
    outcomes = []
    for future in futures:
        try:
            outcomes.append(future.result())
        except NodeConflict:
            outcomes.append(None)

    assert sum(outcome is not None for outcome in outcomes) == 1
    _, page, _ = RecordingHistoryStore(tmp_path).ordered_page("recording-01", "revisions")
    assert len(page) == 2
    assert {item.resource.revision_id for item in page} == {
        first.revision_id,
        store.get("n").head_revision_id,
    }


def test_recording_revision_history_replays_after_history_commit_crash(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path / "pipeline-nodes")
    first = store.create("n", "Events", "events", SOURCE, content(200), {})

    def die(boundary: str) -> None:
        if boundary == "history_published":
            raise RuntimeError("simulated process death after history publication")

    store._after_durable_boundary = die
    with pytest.raises(RuntimeError, match="simulated process death"):
        store.save("n", first.revision_id, content(300), {})

    restarted = PipelineNodeStore(tmp_path / "pipeline-nodes")
    restarted.reconcile_revision_history_outbox()
    history = RecordingHistoryStore(tmp_path)
    authority, page, _ = history.ordered_page("recording-01", "revisions", limit=10)
    assert authority.sequence == 2
    assert len(page) == 2


def test_recording_revision_history_recovers_source_commit_gap_after_restart(
    tmp_path: Path,
) -> None:
    store = PipelineNodeStore(tmp_path / "pipeline-nodes")
    first = store.create("n", "Events", "events", SOURCE, content(200), {})

    def die(boundary: str) -> None:
        if boundary == "head":
            raise RuntimeError("simulated process death after source HEAD commit")

    store._after_durable_boundary = die
    with pytest.raises(RuntimeError, match="simulated process death"):
        store.save("n", first.revision_id, content(300), {})

    restarted = PipelineNodeStore(tmp_path / "pipeline-nodes")
    restarted.reconcile_revision_history_outbox()
    history = RecordingHistoryStore(tmp_path)
    authority, page, _ = history.ordered_page("recording-01", "revisions", limit=10)
    assert authority.sequence == 2
    assert len(page) == 2
    assert restarted.read_authorized_revision("n", page[-1].resource.revision_id)


def test_corrupt_node_keeps_pending_revision_history_intent(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path / "pipeline-nodes")
    first = store.create("n", "Events", "events", SOURCE, content(200), {})
    store._queue_revision_history(store._node_path("n"), first)
    manifest = store._node_path("n") / "manifest.json"
    manifest.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError):
        PipelineNodeStore(tmp_path / "pipeline-nodes").reconcile_revision_history_outbox()

    pending = json.loads(store._history_outbox_path.read_text(encoding="utf-8"))
    assert len(pending["entries"]) == 1
    assert pending["entries"][0]["revision_id"] == first.revision_id


def test_duplicate_revision_id_fails_before_history_outbox_write(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path / "pipeline-nodes")
    first = store.create("n", "Events", "events", SOURCE, content(200), {})
    current = store.save("n", first.revision_id, content(300), {}, revision_id="fixed-rev")
    outbox = store._history_outbox_path
    assert not outbox.exists() or json.loads(outbox.read_text(encoding="utf-8"))["entries"] == []

    with pytest.raises(NodeConflict, match="revision ID already exists"):
        store.save("n", current.revision_id, content(400), {}, revision_id="fixed-rev")

    assert not outbox.exists() or json.loads(outbox.read_text(encoding="utf-8"))["entries"] == []
    _, items, _ = RecordingHistoryStore(tmp_path).ordered_page("recording-01", "revisions")
    assert {item.resource.revision_id for item in items} == {first.revision_id, "fixed-rev"}


def test_edit_and_accept_serialize(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    revision = store.create("n", "Events", "events", SOURCE, content(200), {})

    def accept():
        try:
            return PipelineNodeUses(PipelineNodeStore(tmp_path)).accept(
                "run", [("n", revision.revision_id)]
            )
        except NodeConflict:
            return None

    def edit():
        try:
            return PipelineNodeStore(tmp_path).save("n", revision.revision_id, content(300), {})
        except NodeUsed:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        run = pool.submit(accept)
        edit_result = pool.submit(edit)
        accepted = run.result()
        edited = edit_result.result()
    if edited is not None:
        assert accepted is None
        assert store.get("n").head_revision_id == edited.revision_id
    else:
        assert accepted["inputs"] == [{"node_id": "n", "revision_id": revision.revision_id}]
        assert store.get("n").head_revision_id == revision.revision_id
