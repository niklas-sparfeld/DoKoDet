from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dokodetector_backend.pipeline_node_store import NodeConflict, NodeUsed, PipelineNodeStore
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses

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
