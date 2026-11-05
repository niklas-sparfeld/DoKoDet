from __future__ import annotations

from pathlib import Path

import pytest
from doko_operations.pipeline_data import (
    EventDataRevision,
    ProcessorRunRequest,
    RunProgress,
    canonical_json_bytes,
    sha256_bytes,
)

from dokodetector_backend.filesystem import atomic_write_json
from dokodetector_backend.pipeline_lineage import PipelineLineage
from dokodetector_backend.pipeline_lineage_writer import PipelineLineageWriter
from dokodetector_backend.pipeline_node_store import NodeUsed, PipelineNodeStore
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses
from dokodetector_backend.pipeline_store import (
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    ProcessorRunStore,
)

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}


def _request(run_id: str, processor_type: str, inputs: list[str]) -> ProcessorRunRequest:
    return ProcessorRunRequest.from_mapping(
        {
            "schema_version": "processor-run-request/v1",
            "run_id": run_id,
            "processor_type": processor_type,
            "source": SOURCE,
            "input_revision_ids": inputs,
            "implementation": {"name": "fixture", "version": "1"},
            "model": None,
            "configuration": {"fixture": True},
            "extraction_policy": {"policy_id": "fixture/v1"},
            "crop_policy": None,
        }
    )


def test_processor_lineage_keeps_empty_results_and_protects_accepted_inputs(
    tmp_path: Path,
) -> None:
    storage = PipelineRuntimeStorage(tmp_path / "runtime", tmp_path / "operations")
    revisions = PipelineRevisionStore(storage)
    node_store = PipelineNodeStore(tmp_path / "nodes")
    lineage = PipelineLineage(node_store)
    writer = PipelineLineageWriter(node_store, lineage, PipelineNodeUses(node_store), revisions)
    runs = ProcessorRunStore(storage, revision_store=revisions, lineage_writer=writer)

    event_run, _ = runs.create(_request("events-01", "event-detection", []))
    runs.start(event_run.run_id)
    event_content = {"schema_version": "event-data/v1", "events": []}
    output = EventDataRevision.from_mapping(
        {
            "manifest": {
                "schema_version": "data-revision/v1",
                "revision_id": "events-revision-01",
                "content_type": "events",
                "content_schema": "event-data/v1",
                "recording_id": "recording-01",
                "source": SOURCE,
                "content_sha256": sha256_bytes(canonical_json_bytes(event_content)),
                "input_revision_ids": [],
                "origin": "processor",
                "producer": {
                    "kind": "processor",
                    "processor_type": "event-detection",
                    "run_id": "events-01",
                    "implementation_id": "fixture",
                    "model_id": None,
                },
                "coverage": {"kind": "processed", "intervals": []},
                "created_at": "2026-09-05T10:00:00Z",
            },
            "content": event_content,
        }
    )
    revisions.publish(output)
    runs.complete(event_run.run_id, [output.manifest.revision_id])

    graph = lineage.snapshot("recording-01")
    run = next(item for item in graph["runs"] if item["run_id"] == "events-01")
    assert run["status"] == "succeeded"
    assert run["result"] == "empty"
    assert run["inputs"][0]["kind"] == "artifact"
    assert run["outputs"][0]["revision_id"] == output.manifest.revision_id

    visible_run, _ = runs.create(
        _request("visible-01", "visible-card-detection", [output.manifest.revision_id])
    )
    assert visible_run.state.status == "queued"
    accepted = next(item for item in lineage.snapshot()["runs"] if item["run_id"] == "visible-01")
    assert accepted["status"] == "accepted"
    assert accepted["inputs"][0]["role"] == "events"
    node_id = accepted["inputs"][0]["node_id"]
    changed = {"schema_version": "event-data/v1", "events": []}
    changed["events"].append(
        {
            "event_id": "new-event",
            "event_type": "card_state_changed",
            "start_us": 100,
            "end_us": 110,
        }
    )
    with pytest.raises(NodeUsed):
        node_store.save(
            node_id,
            output.manifest.revision_id,
            changed,
            {},
        )

    failed_run, _ = runs.create(_request("failed-01", "event-detection", []))
    runs.start(failed_run.run_id)
    runs.fail(failed_run.run_id, {"code": "fixture_failure", "message": "stop"})
    runs.retry(failed_run.run_id)
    retried = next(
        item
        for item in lineage.snapshot("recording-01")["runs"]
        if item["run_id"] == "failed-01-attempt-2"
    )
    assert retried["status"] == "accepted"
    assert retried["inputs"][0]["role"] == "recording_video"
    runs.partial(failed_run.run_id, progress=RunProgress(completed=0, total=0), items=())
    partial = next(
        item
        for item in lineage.snapshot("recording-01")["runs"]
        if item["run_id"] == "failed-01-attempt-2"
    )
    assert partial["status"] == "partial"
    assert partial["result"] is None


def test_processor_lineage_reuses_imported_revision_nodes(tmp_path: Path) -> None:
    storage = PipelineRuntimeStorage(tmp_path / "runtime", tmp_path / "operations")
    revisions = PipelineRevisionStore(storage)
    node_store = PipelineNodeStore(tmp_path / "nodes")
    content = {"schema_version": "event-data/v1", "events": []}
    revision = EventDataRevision.from_mapping(
        {
            "manifest": {
                "schema_version": "data-revision/v1",
                "revision_id": "legacy-events-revision",
                "content_type": "events",
                "content_schema": "event-data/v1",
                "recording_id": "recording-01",
                "source": SOURCE,
                "content_sha256": sha256_bytes(canonical_json_bytes(content)),
                "input_revision_ids": [],
                "origin": "processor",
                "producer": {
                    "kind": "processor",
                    "processor_type": "event-detection",
                    "run_id": "legacy-run",
                    "implementation_id": "fixture",
                    "model_id": None,
                },
                "coverage": {"kind": "processed", "intervals": []},
                "created_at": "2026-09-05T10:00:00Z",
            },
            "content": content,
        }
    )
    revisions.publish(revision)
    node_store.create(
        "migrated-events-node",
        "Migrated events",
        "events",
        SOURCE,
        content,
        {"legacy_revision_id": revision.manifest.revision_id},
        revision_id="migrated-events-revision",
    )
    atomic_write_json(
        node_store.root / ".legacy-revision-map.json",
        {
            "schema_version": "legacy-revision-map/v1",
            "snapshot_sha256": "b" * 64,
            "revisions": {
                revision.manifest.revision_id: {
                    "node_id": "migrated-events-node",
                    "revision_id": "migrated-events-revision",
                }
            },
        },
    )
    writer = PipelineLineageWriter(
        node_store, PipelineLineage(node_store), PipelineNodeUses(node_store), revisions
    )

    assert writer._ensure_revision_node(revisions.require(revision.manifest.revision_id)) == (
        "migrated-events-node",
        "migrated-events-revision",
    )
    assert len(node_store.list_nodes()) == 1
