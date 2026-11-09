from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_workspace_service import RecordingPipelineWorkspaceService

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-main",
    "relative_path": "data/intake/recordings/recording-main/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}


def _content(start_us: int) -> dict[str, object]:
    return {
        "schema_version": "event-data/v1",
        "events": [
            {
                "event_id": "event-main",
                "event_type": "card_state_changed",
                "start_us": start_us,
                "end_us": start_us + 250_000,
            }
        ],
    }


def _populate(root: Path, *, history_count: int, unrelated_count: int):
    store = PipelineNodeStore(root)
    current = _content(8_000_000)
    revision = store.create(
        "selected-events",
        "Selected events",
        "events",
        SOURCE,
        _content(1_000_000),
        {},
        revision_id="selected-00",
    )
    for index in range(1, history_count):
        content = current if index == history_count - 1 else _content(index * 100_000)
        revision = store.save(
            "selected-events",
            revision.revision_id,
            content,
            (
                {
                    "fixture_empty_stage": "table_observations",
                    "fixture_stale_stage": "visual_identities",
                }
                if index == history_count - 1
                else {}
            ),
            revision_id=f"selected-{index:02d}",
        )
    store.create(
        "sibling-review",
        "Independent review",
        "events",
        SOURCE,
        _content(2_000_000),
        {},
        revision_id="review-00",
    )
    for index in range(unrelated_count):
        source = {**SOURCE, "recording_id": f"recording-other-{index:03d}"}
        store.create(
            f"other-{index:03d}",
            "Unrelated recording",
            "events",
            source,
            _content(3_000_000),
            {},
            revision_id=f"other-{index:03d}-00",
        )

    history_reads = 0
    original_history = store.history

    def counted_history(node_id: str):
        nonlocal history_reads
        history_reads += 1
        return original_history(node_id)

    store.history = counted_history  # type: ignore[method-assign]
    service = RecordingPipelineWorkspaceService(
        recording_source_provider=lambda _: None,
        run_store=None,
        selection_store=None,
        round_analysis_store=None,
        node_store=store,
        lineage_service=SimpleNamespace(root=root / ".lineage"),
    )
    revisions = service._node_revisions_for_recording("recording-main")
    return store, revisions, history_reads, current


def test_workspace_growth_fixture_keeps_current_state_and_counts_history_work(tmp_path: Path):
    small, small_revisions, small_history_reads, current = _populate(
        tmp_path / "small", history_count=2, unrelated_count=1
    )
    large, large_revisions, large_history_reads, large_current = _populate(
        tmp_path / "large", history_count=20, unrelated_count=10
    )

    assert current == large_current
    assert small.get("selected-events").head_revision_id == "selected-01"
    assert large.get("selected-events").head_revision_id == "selected-19"
    assert small.read_revision_record("selected-events", "selected-01").content == current
    assert large.read_revision_record("selected-events", "selected-19").content == current
    assert (
        small.read_revision_record("selected-events", "selected-01").metadata["fixture_empty_stage"]
        == "table_observations"
    )
    assert (
        large.read_revision_record("selected-events", "selected-19").metadata["fixture_stale_stage"]
        == "visual_identities"
    )
    assert {item.node_id for item in small_revisions} == {"selected-events", "sibling-review"}
    assert {item.node_id for item in large_revisions} == {"selected-events", "sibling-review"}
    assert small_history_reads == large_history_reads == 2
    assert len(small_revisions) == 3
    assert len(large_revisions) == 21
    assert len(small.list_nodes()) == 3
    assert len(large.list_nodes()) == 12
