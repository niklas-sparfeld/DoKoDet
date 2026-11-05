from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dokodetector_backend.pipeline_node_store import NodeConflict, PipelineNodeStore

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
        raise OSError("interrupted")

    monkeypatch.setattr("dokodetector_backend.pipeline_node_store.atomic_replace_json", fail_head)
    with pytest.raises(OSError, match="interrupted"):
        store.save("n", first.revision_id, events(2), {})
    reopened = PipelineNodeStore(tmp_path)
    assert reopened.get("n").head_revision_id == first.revision_id
    assert [r.revision_id for r in reopened.history("n")] == [first.revision_id]
    unpublished = next(
        p.name for p in (tmp_path / "n" / "revisions").iterdir() if p.name != first.revision_id
    )
    with pytest.raises(KeyError):
        reopened.read_revision("n", unpublished)


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
