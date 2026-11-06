from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dokodetector_backend.pipeline_node_selection_store import PipelineNodeSelectionStore
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_store import PipelineRevisionStore, PipelineSelectionConflict

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}
EVENTS = {
    "schema_version": "event-data/v1",
    "events": [
        {"event_id": "event-1", "event_type": "card_state_changed", "start_us": 10, "end_us": 20}
    ],
}


def _store(root: Path) -> tuple[PipelineNodeStore, PipelineNodeSelectionStore]:
    nodes = PipelineNodeStore(root / "nodes")
    selections = PipelineNodeSelectionStore(nodes, PipelineRevisionStore(root / "legacy-revisions"))
    return nodes, selections


def test_exact_selection_roundtrips_without_legacy_mapping(tmp_path: Path) -> None:
    nodes, selections = _store(tmp_path)
    revision = nodes.create("event-node", "Events", "events", SOURCE, EVENTS, {})

    saved = selections.update_exact(
        "recording-01",
        "events",
        expected_revision=0,
        selected_generated={"node_id": "event-node", "revision_id": revision.revision_id},
        selected_completed_reference=None,
    )

    assert saved.revision == 1
    assert selections.get_exact("recording-01", "events") == saved
    projected = selections.get("recording-01", "events")
    assert projected is not None
    assert projected.selected_generated_revision_id == revision.revision_id


def test_runtime_selection_does_not_read_legacy_revision_map(tmp_path: Path) -> None:
    nodes, selections = _store(tmp_path)
    revision = nodes.create(
        "event-node",
        "Events",
        "events",
        SOURCE,
        EVENTS,
        {"legacy_revision_id": "old-event-revision"},
        revision_id="canonical-node-revision",
    )
    selections.update_exact(
        "recording-01",
        "events",
        expected_revision=0,
        selected_generated={"node_id": "event-node", "revision_id": revision.revision_id},
        selected_completed_reference=None,
    )
    (nodes.root / ".legacy-revision-map.json").write_text("not json")

    projected = selections.get("recording-01", "events")

    assert projected is not None
    assert projected.selected_generated_revision_id == "old-event-revision"


def test_exact_selection_checks_node_identity_and_revision(tmp_path: Path) -> None:
    nodes, selections = _store(tmp_path)
    revision = nodes.create("event-node", "Events", "events", SOURCE, EVENTS, {})
    with pytest.raises(ValueError, match="recording and content type"):
        selections.update_exact(
            "recording-01",
            "visible_cards",
            expected_revision=0,
            selected_generated={"node_id": "event-node", "revision_id": revision.revision_id},
            selected_completed_reference=None,
        )
    with pytest.raises(ValueError, match="matching node revision"):
        selections.update_exact(
            "recording-01",
            "events",
            expected_revision=0,
            selected_generated={"node_id": "event-node", "revision_id": "missing"},
            selected_completed_reference=None,
        )
    assert selections.get_exact("recording-01", "events") is None


def test_exact_selection_compare_and_swap_serializes_writers(tmp_path: Path) -> None:
    nodes, selections = _store(tmp_path)
    revision = nodes.create("event-node", "Events", "events", SOURCE, EVENTS, {})
    pointer = {"node_id": "event-node", "revision_id": revision.revision_id}

    def write() -> bool:
        try:
            PipelineNodeSelectionStore(
                PipelineNodeStore(tmp_path / "nodes"),
                PipelineRevisionStore(tmp_path / "legacy-revisions"),
            ).update_exact(
                "recording-01",
                "events",
                expected_revision=0,
                selected_generated=pointer,
                selected_completed_reference=None,
            )
            return True
        except PipelineSelectionConflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: write(), range(2)))

    assert sorted(outcomes) == [False, True]
    assert selections.get_exact("recording-01", "events").revision == 1
