from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dokodetector_backend.pipeline_item_provenance import ItemProvenanceService
from dokodetector_backend.pipeline_node_edits import PipelineNodeEdits
from dokodetector_backend.pipeline_node_store import NodeConflict, PipelineNodeStore
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}
ACTOR = {"kind": "human", "id": "person"}
TOOL = {"kind": "processor", "id": "detector"}


def content(end: int) -> dict:
    return {
        "schema_version": "event-data/v1",
        "events": [
            {"event_id": "e", "event_type": "card_state_changed", "start_us": 100, "end_us": end}
        ],
    }


def test_used_edit_copy_retry_and_subsequent_edits(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    initial = ItemProvenanceService(store).create(
        "n", "Events", "events", SOURCE, content(200), {"e": "/events/0"}, TOOL
    )
    PipelineNodeUses(store).accept("failed-run", [("n", initial.revision_id)])
    edits = PipelineNodeEdits(store)
    operation = [{"kind": "replace", "before": ["e"], "after": ["e"]}]
    args = ("n", initial.revision_id, content(300), "request1", ACTOR)
    result = edits.edit(*args, pointers={"e": "/events/0"}, operations=operation)
    assert result["copied"] and result["reason"] == "downstream_use"
    assert edits.edit(*args, pointers={"e": "/events/0"}, operations=operation) == result
    with pytest.raises(NodeConflict):
        edits.edit(
            "n",
            initial.revision_id,
            content(400),
            "request1",
            ACTOR,
            pointers={"e": "/events/0"},
            operations=operation,
        )
    new = store.read_revision(result["node_id"], result["revision_id"])
    changes = new.metadata["item_provenance"]["changes"]
    assert changes[0]["actor"] == TOOL and changes[1]["actor"] == ACTOR
    assert changes[1]["before_revision"]["revision_id"] == initial.revision_id
    assert changes[1]["after_revision"]["node_id"] == result["node_id"]
    assert store.read_revision("n", initial.revision_id).content == content(200)
    following = edits.edit(
        result["node_id"],
        result["revision_id"],
        content(400),
        "request2",
        ACTOR,
        pointers={"e": "/events/0"},
        operations=operation,
    )
    assert not following["copied"] and following["node_id"] == result["node_id"]


def test_concurrent_retry_and_invalid_edit_leaves_no_copy(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    initial = store.create("n", "Events", "events", SOURCE, content(200), {})
    PipelineNodeUses(store).accept("run", [("n", initial.revision_id)])

    def call():
        return PipelineNodeEdits(PipelineNodeStore(tmp_path)).edit(
            "n", initial.revision_id, content(300), "same", ACTOR
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: call(), range(2)))
    assert results[0] == results[1]
    assert len(store.list_nodes()) == 2
    with pytest.raises(ValueError):
        PipelineNodeEdits(store).edit("n", initial.revision_id, content(50), "invalid", ACTOR)
    assert len(store.list_nodes()) == 2


def test_first_human_event_edit_seeds_and_records_item_provenance(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    initial = store.create("n", "Events", "events", SOURCE, content(200), {})
    result = PipelineNodeEdits(store).edit(
        "n",
        initial.revision_id,
        content(300),
        "human-edit",
        ACTOR,
        pointers={"e": "/events/0"},
        base_pointers={"e": "/events/0"},
        operations=[{"kind": "replace", "before": ["e"], "after": ["e"]}],
    )
    revision = store.read_revision(result["node_id"], result["revision_id"])
    provenance = revision.metadata["item_provenance"]
    assert provenance["items"]["e"]["pointer"] == "/events/0"
    assert provenance["changes"][-1]["actor"] == ACTOR
    assert provenance["changes"][-1]["kind"] == "replace"


def test_copy_historical_restore_and_recovery(tmp_path: Path, monkeypatch) -> None:
    store = PipelineNodeStore(tmp_path)
    first = store.create("n", "Events", "events", SOURCE, content(200), {})
    second = store.save("n", first.revision_id, content(300), {})
    edits = PipelineNodeEdits(store)
    explicit = edits.copy("n", first.revision_id, "copy", ACTOR, reason="comparison")
    assert store.read_revision(explicit["node_id"], explicit["revision_id"]).content == content(200)
    restored = edits.restore("n", second.revision_id, first.revision_id, "restore", ACTOR)
    assert not restored["copied"]
    assert store.read_revision("n", restored["revision_id"]).content == content(200)
    PipelineNodeUses(store).accept("run", [("n", restored["revision_id"])])
    real_journal = edits._journal
    calls = []

    def interrupt(path, key, digest, result):
        calls.append(result)
        if result is not None:
            raise OSError("interrupted after publication")
        return real_journal(path, key, digest, result)

    monkeypatch.setattr(edits, "_journal", interrupt)
    with pytest.raises(OSError):
        edits.restore("n", restored["revision_id"], second.revision_id, "recover", ACTOR)
    monkeypatch.setattr(edits, "_journal", real_journal)
    recovered = edits.restore("n", restored["revision_id"], second.revision_id, "recover", ACTOR)
    assert recovered["copied"]
    assert store.read_revision(recovered["node_id"], recovered["revision_id"]).content == content(
        300
    )
    assert (
        edits.restore("n", restored["revision_id"], second.revision_id, "recover", ACTOR)
        == recovered
    )


def test_retry_after_revision_published_but_head_update_failed(tmp_path: Path, monkeypatch) -> None:
    store = PipelineNodeStore(tmp_path)
    initial = store.create("n", "Events", "events", SOURCE, content(200), {})
    edits = PipelineNodeEdits(store)

    def fail(*args, **kwargs):
        raise OSError("head update failed")

    with monkeypatch.context() as context:
        context.setattr("dokodetector_backend.pipeline_node_store.atomic_replace_json", fail)
        with pytest.raises(OSError, match="head update failed"):
            edits.edit("n", initial.revision_id, content(300), "retry", ACTOR)
    assert store.get("n").head_revision_id == initial.revision_id
    result = edits.edit("n", initial.revision_id, content(300), "retry", ACTOR)
    assert not result["copied"]
    assert store.read_revision("n", result["revision_id"]).content == content(300)
    assert len(store.history("n")) == 2


def test_run_acceptance_and_service_edit_race(tmp_path: Path) -> None:
    store = PipelineNodeStore(tmp_path)
    initial = store.create("n", "Events", "events", SOURCE, content(200), {})

    def accept():
        try:
            return PipelineNodeUses(PipelineNodeStore(tmp_path)).accept(
                "run", [("n", initial.revision_id)]
            )
        except NodeConflict:
            return None

    def edit():
        return PipelineNodeEdits(PipelineNodeStore(tmp_path)).edit(
            "n", initial.revision_id, content(300), "racing", ACTOR
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted_future = pool.submit(accept)
        edit_future = pool.submit(edit)
        accepted = accepted_future.result()
        result = edit_future.result()
    if accepted is None:
        assert not result["copied"]
        assert store.get("n").head_revision_id == result["revision_id"]
    else:
        assert result["copied"]
        assert store.get("n").head_revision_id == initial.revision_id
        assert accepted["inputs"][0]["revision_id"] == initial.revision_id
