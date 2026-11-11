from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dokodetector_backend.pipeline_node_selection_store import PipelineNodeSelectionStore
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_storage import PipelineSelectionConflict

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}
EVENTS = {"schema_version": "visible-card-data/v1", "outcomes": []}


def _store(root: Path) -> tuple[PipelineNodeStore, PipelineNodeSelectionStore]:
    nodes = PipelineNodeStore(root / "nodes")
    selections = PipelineNodeSelectionStore(nodes)
    return nodes, selections


def test_exact_selection_roundtrips_without_legacy_mapping(tmp_path: Path) -> None:
    nodes, selections = _store(tmp_path)
    revision = nodes.create("event-node", "Events", "visible_cards", SOURCE, EVENTS, {})

    saved = selections.update_exact(
        "recording-01",
        "visible_cards",
        expected_revision=0,
        selected_generated={"node_id": "event-node", "revision_id": revision.revision_id},
        selected_completed_reference=None,
    )

    assert saved.revision == 1
    assert selections.get_exact("recording-01", "visible_cards") == saved
    exact = selections.get_exact("recording-01", "visible_cards")
    assert exact is not None
    assert exact.selected_generated == {
        "node_id": "event-node",
        "revision_id": revision.revision_id,
    }


def test_runtime_selection_does_not_read_legacy_revision_map(tmp_path: Path) -> None:
    nodes, selections = _store(tmp_path)
    revision = nodes.create(
        "event-node",
        "Events",
        "visible_cards",
        SOURCE,
        EVENTS,
        {"legacy_revision_id": "old-event-revision"},
        revision_id="canonical-node-revision",
    )
    selections.update_exact(
        "recording-01",
        "visible_cards",
        expected_revision=0,
        selected_generated={"node_id": "event-node", "revision_id": revision.revision_id},
        selected_completed_reference=None,
    )
    (nodes.root / ".legacy-revision-map.json").write_text("not json")

    exact = selections.get_exact("recording-01", "visible_cards")

    assert exact is not None
    assert exact.selected_generated == {
        "node_id": "event-node",
        "revision_id": "canonical-node-revision",
    }


def test_exact_selection_checks_node_identity_and_revision(tmp_path: Path) -> None:
    nodes, selections = _store(tmp_path)
    revision = nodes.create("event-node", "Events", "visible_cards", SOURCE, EVENTS, {})
    with pytest.raises(ValueError, match="recording and content type"):
        selections.update_exact(
            "recording-01",
            "visual_identities",
            expected_revision=0,
            selected_generated={"node_id": "event-node", "revision_id": revision.revision_id},
            selected_completed_reference=None,
        )
    with pytest.raises(ValueError, match="matching node revision"):
        selections.update_exact(
            "recording-01",
            "visible_cards",
            expected_revision=0,
            selected_generated={"node_id": "event-node", "revision_id": "missing"},
            selected_completed_reference=None,
        )
    assert selections.get_exact("recording-01", "visible_cards") is None


def test_exact_selection_compare_and_swap_serializes_writers(tmp_path: Path) -> None:
    nodes, selections = _store(tmp_path)
    revision = nodes.create("event-node", "Events", "visible_cards", SOURCE, EVENTS, {})
    other_revision = nodes.create("event-node-2", "Events 2", "visible_cards", SOURCE, EVENTS, {})
    pointers = [
        {"node_id": "event-node", "revision_id": revision.revision_id},
        {"node_id": "event-node-2", "revision_id": other_revision.revision_id},
    ]

    def write(pointer: dict[str, str]) -> bool:
        try:
            PipelineNodeSelectionStore(
                PipelineNodeStore(tmp_path / "nodes"),
            ).update_exact(
                "recording-01",
                "visible_cards",
                expected_revision=0,
                selected_generated=pointer,
                selected_completed_reference=None,
            )
            return True
        except PipelineSelectionConflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(write, pointers))

    assert sorted(outcomes) == [False, True]
    assert selections.get_exact("recording-01", "visible_cards").revision == 1


def test_exact_selection_identical_retry_is_idempotent(tmp_path: Path) -> None:
    nodes, selections = _store(tmp_path)
    revision = nodes.create("event-node", "Events", "visible_cards", SOURCE, EVENTS, {})
    pointer = {"node_id": "event-node", "revision_id": revision.revision_id}

    def write() -> int:
        return (
            PipelineNodeSelectionStore(PipelineNodeStore(tmp_path / "nodes"))
            .update_exact(
                "recording-01",
                "visible_cards",
                expected_revision=0,
                selected_generated=pointer,
                selected_completed_reference=None,
            )
            .revision
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        revisions = list(pool.map(lambda _: write(), range(2)))

    assert revisions == [1, 1]
    assert selections.get_exact("recording-01", "visible_cards").revision == 1
    other = nodes.create("event-node-2", "Events 2", "visible_cards", SOURCE, EVENTS, {})
    selections.update_exact(
        "recording-01",
        "visible_cards",
        expected_revision=1,
        selected_generated={"node_id": "event-node-2", "revision_id": other.revision_id},
        selected_completed_reference=None,
    )
    with pytest.raises(PipelineSelectionConflict):
        write()


def test_standalone_selection_recovers_after_selection_boundary(tmp_path: Path) -> None:
    nodes, selections = _store(tmp_path)
    revision = nodes.create("event-node", "Events", "visible_cards", SOURCE, EVENTS, {})
    pointer = {"node_id": "event-node", "revision_id": revision.revision_id}

    def interrupt(boundary: str) -> None:
        if boundary == "selection":
            raise RuntimeError("interrupted")

    nodes._after_durable_boundary = interrupt
    with pytest.raises(RuntimeError, match="interrupted"):
        selections.update_exact(
            "recording-01",
            "visible_cards",
            expected_revision=0,
            selected_generated=pointer,
            selected_completed_reference=None,
        )
    reopened = PipelineNodeSelectionStore(PipelineNodeStore(tmp_path / "nodes"))
    assert reopened.get_exact("recording-01", "visible_cards").selected_generated == pointer
    assert (
        reopened.update_exact(
            "recording-01",
            "visible_cards",
            expected_revision=0,
            selected_generated=pointer,
            selected_completed_reference=None,
        ).revision
        == 1
    )
