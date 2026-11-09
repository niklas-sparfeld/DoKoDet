from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import dokodetector_backend.pipeline_workspace_service as workspace_module
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
    payload_reads = 0
    payload_bytes = 0
    revision_validations = 0
    original_history = store.history
    original_revision_read = store._read_revision
    original_parser = workspace_module.parse_event_data_bytes
    original_glob = Path.glob
    lineage_enumerations = 0
    lineage_entries_enumerated = 0

    def counted_history(node_id: str):
        nonlocal history_reads
        history_reads += 1
        return original_history(node_id)

    def counted_revision_read(node, revision_id):
        nonlocal payload_reads, payload_bytes, revision_validations
        payload_reads += 1
        revision_validations += 1
        payload_bytes += (
            store.revision_path(node.node_id, revision_id).joinpath("revision.json").stat().st_size
        )
        return original_revision_read(node, revision_id)

    parse_calls = 0

    def counted_parser(raw, **kwargs):
        nonlocal parse_calls
        parse_calls += 1
        return original_parser(raw, **kwargs)

    def counted_glob(path, pattern):
        nonlocal lineage_enumerations, lineage_entries_enumerated
        matches = list(original_glob(path, pattern))
        if path == lineage_root:
            lineage_enumerations += 1
            lineage_entries_enumerated += len(matches)
        return iter(matches)

    store.history = counted_history  # type: ignore[method-assign]
    store._read_revision = counted_revision_read  # type: ignore[method-assign]
    lineage_root = root / ".lineage-runs"
    lineage_root.mkdir(parents=True, exist_ok=True)
    service = RecordingPipelineWorkspaceService(
        recording_source_provider=lambda _: None,
        run_store=None,
        selection_store=None,
        round_analysis_store=None,
        node_store=store,
        lineage_service=SimpleNamespace(root=lineage_root),
    )
    workspace_module.parse_event_data_bytes = counted_parser
    Path.glob = counted_glob  # type: ignore[method-assign]
    started = time.perf_counter_ns()
    try:
        revisions = service._node_revisions_for_recording("recording-main", include_content=True)
    finally:
        workspace_module.parse_event_data_bytes = original_parser
        Path.glob = original_glob  # type: ignore[method-assign]
    elapsed_ns = time.perf_counter_ns() - started
    counters = {
        "history_calls": history_reads,
        "revision_payload_reads": payload_reads,
        "revision_payload_bytes": payload_bytes,
        "revision_validations": revision_validations,
        "domain_parser_calls": parse_calls,
        "lineage_enumerations": lineage_enumerations,
        "lineage_entries_enumerated": lineage_entries_enumerated,
        "elapsed_ns": elapsed_ns,
    }
    return store, revisions, counters, current


def test_workspace_growth_fixture_keeps_current_state_and_counts_history_work(tmp_path: Path):
    small, small_revisions, small_counters, current = _populate(
        tmp_path / "small", history_count=2, unrelated_count=1
    )
    large, large_revisions, large_counters, large_current = _populate(
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
    assert small_counters["history_calls"] == large_counters["history_calls"] == 2
    assert len(small_revisions) == 3
    assert len(large_revisions) == 21
    assert small_counters["revision_payload_reads"] == 3
    assert large_counters["revision_payload_reads"] == 21
    assert small_counters["revision_validations"] == 3
    assert large_counters["revision_validations"] == 21
    assert small_counters["domain_parser_calls"] == 3
    assert large_counters["domain_parser_calls"] == 21
    assert small_counters["lineage_enumerations"] == large_counters["lineage_enumerations"] == 1
    assert small_counters["lineage_entries_enumerated"] == 0
    assert large_counters["lineage_entries_enumerated"] == 0
    assert small_counters["revision_payload_bytes"] < large_counters["revision_payload_bytes"]
    assert 0 < small_counters["elapsed_ns"] < 1_000_000_000
    assert 0 < large_counters["elapsed_ns"] < 1_000_000_000
    assert len(small.list_nodes()) == 3
    assert len(large.list_nodes()) == 12
    print(
        "M0_GROWTH "
        + json.dumps(
            {
                "small": small_counters,
                "large": large_counters,
                "small_nodes_enumerated": len(small.list_nodes()),
                "large_nodes_enumerated": len(large.list_nodes()),
            },
            sort_keys=True,
        )
    )
