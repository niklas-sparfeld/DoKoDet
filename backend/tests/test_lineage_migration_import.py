from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from doko_operations.pipeline_data import canonical_json_bytes

from dokodetector_backend.lineage_migration_import import import_package
from dokodetector_backend.pipeline_lineage import PipelineLineage
from dokodetector_backend.pipeline_node_store import PipelineNodeStore

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}


def _write_json(path: Path, value: Any) -> tuple[int, str]:
    raw = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return len(raw), hashlib.sha256(raw).hexdigest()


def test_import_package_maps_revision_and_terminal_run_idempotently(tmp_path: Path) -> None:
    package = tmp_path / "package"
    old_revision_id = "legacy-events-01"
    node_id = "migrated-node-01"
    node_revision_id = "migrated-revision-01"
    run_id = "migrated-run-01"
    content = {"schema_version": "event-data/v1", "events": []}
    revision_manifest = {
        "schema_version": "data-revision/v1",
        "revision_id": old_revision_id,
        "content_type": "events",
        "content_schema": "event-data/v1",
        "recording_id": "recording-01",
        "source": SOURCE,
        "content_sha256": hashlib.sha256(canonical_json_bytes(content)).hexdigest(),
        "input_revision_ids": [],
        "origin": "processor",
        "producer": {"kind": "processor", "processor_type": "event-detection"},
        "coverage": {"kind": "processed", "intervals": []},
        "created_at": "2026-09-05T10:00:00Z",
    }
    revision_manifest_path = (
        package / "evidence" / "operations" / "pipeline/revisions/legacy-events-01/manifest.json"
    )
    content_path = (
        package / "evidence" / "operations" / "pipeline/revisions/legacy-events-01/content.json"
    )
    manifest_size, manifest_digest = _write_json(revision_manifest_path, revision_manifest)
    content_size, content_digest = _write_json(content_path, content)
    request = {
        "run_id": "legacy-run-01",
        "processor_type": "event-detection",
        "source": SOURCE,
        "input_revision_ids": [],
        "implementation": {"name": "fixture", "version": "1"},
        "model": None,
        "configuration": {"fixture": True},
        "extraction_policy": None,
        "crop_policy": None,
    }
    state = {"status": "complete", "attempt": 1, "output_revision_ids": [old_revision_id]}
    request_path = package / "evidence/operations/pipeline/runs/legacy-run-01/request.json"
    state_path = package / "evidence/operations/pipeline/runs/legacy-run-01/state.json"
    request_size, request_digest = _write_json(request_path, request)
    state_size, state_digest = _write_json(state_path, state)
    selection = {
        "schema_version": "pipeline-selection/v1",
        "revision": 2,
        "recording_id": "recording-01",
        "content_type": "events",
        "selected_generated_revision_id": old_revision_id,
        "selected_completed_reference_revision_id": None,
        "updated_at": "2026-09-05T11:00:00Z",
    }
    selection_path = package / "evidence/operations/pipeline/selections/recording-01/events.json"
    selection_size, selection_digest = _write_json(selection_path, selection)
    draft_content = b'{"draft_revision":1,"recording_id":"recording-01"}'
    draft_path = package / "evidence/operations/pipeline-references/recording-01/events/draft.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_bytes(draft_content)
    resources = [
        {
            "schema_version": "lineage-migration-resource/v1",
            "kind": "pipeline_revision",
            "old_id": old_revision_id,
            "new_id": node_id,
            "new_revision_id": node_revision_id,
            "old_root_id": "operations",
            "content_type": "events",
            "content_schema": "event-data/v1",
            "unknown_history": "not_recorded",
            "files": [
                {
                    "path": "pipeline/revisions/legacy-events-01/manifest.json",
                    "byte_length": manifest_size,
                    "sha256": manifest_digest,
                },
                {
                    "path": "pipeline/revisions/legacy-events-01/content.json",
                    "byte_length": content_size,
                    "sha256": content_digest,
                },
            ],
            "references": [],
        },
        {
            "schema_version": "lineage-migration-resource/v1",
            "kind": "processor_run",
            "old_id": "legacy-run-01",
            "new_id": run_id,
            "old_root_id": "operations",
            "files": [
                {
                    "path": "pipeline/runs/legacy-run-01/request.json",
                    "byte_length": request_size,
                    "sha256": request_digest,
                },
                {
                    "path": "pipeline/runs/legacy-run-01/state.json",
                    "byte_length": state_size,
                    "sha256": state_digest,
                },
            ],
            "references": [
                {
                    "role": "output",
                    "old_revision_id": old_revision_id,
                    "target_id": node_id,
                    "target_revision_id": node_revision_id,
                }
            ],
        },
        {
            "schema_version": "lineage-migration-resource/v1",
            "kind": "selection",
            "old_id": "recording-01/events",
            "new_id": "recording-01/events",
            "old_root_id": "operations",
            "files": [
                {
                    "path": "pipeline/selections/recording-01/events.json",
                    "byte_length": selection_size,
                    "sha256": selection_digest,
                }
            ],
            "references": [
                {
                    "role": "generated",
                    "old_revision_id": old_revision_id,
                    "target_id": node_id,
                    "target_revision_id": node_revision_id,
                }
            ],
        },
        {
            "schema_version": "lineage-migration-resource/v1",
            "kind": "maintained_draft",
            "old_id": "recording-01/events",
            "new_id": "recording-01/events",
            "old_root_id": "operations",
            "files": [
                {
                    "path": "pipeline-references/recording-01/events/draft.json",
                    "byte_length": len(draft_content),
                    "sha256": hashlib.sha256(draft_content).hexdigest(),
                }
            ],
            "references": [
                {
                    "role": "base",
                    "old_revision_id": old_revision_id,
                    "target_id": node_id,
                    "target_revision_id": node_revision_id,
                }
            ],
        },
    ]
    _write_json(
        package / "migration.json",
        {
            "schema_version": "lineage-migration-stage/v1",
            "snapshot_sha256": "c" * 64,
            "activation_ready": True,
            "resources": resources,
        },
    )
    store_root = tmp_path / "nodes"

    result = import_package(package, store_root)
    retry = import_package(package, store_root)

    assert (
        result
        == retry
        == {
            "pipeline_revisions": 1,
            "processor_runs": 1,
            "analysis_runs": 0,
            "selections": 1,
            "maintained_draft": 1,
            "independent_review": 0,
            "calibration_draft": 0,
            "nodes": 1,
            "lineage_runs": 1,
        }
    )
    graph = PipelineLineage(PipelineNodeStore(store_root)).snapshot("recording-01")
    run = graph["runs"][0]
    assert run["status"] == "succeeded"
    assert run["result"] == "empty"
    assert run["outputs"][0]["node_id"] == node_id
    assert run["outputs"][0]["revision_id"] == node_revision_id
    migrated_selection = (store_root / ".migrated-selections/recording-01/events.json").read_bytes()
    assert (
        b'"selected_generated":{"node_id":"migrated-node-01",'
        b'"revision_id":"migrated-revision-01"}' in migrated_selection
    )
    record_key = hashlib.sha256(b"maintained_draft/recording-01/events").hexdigest()
    migrated_record = json.loads(
        (store_root / f".migrated-records/maintained_draft/{record_key}.json").read_bytes()
    )
    migrated_draft = migrated_record["files"]["pipeline-references/recording-01/events/draft.json"]
    assert base64.b64decode(migrated_draft["base64"]) == draft_content
    assert migrated_record["references"][0]["mapped_revision"] == {
        "node_id": node_id,
        "revision_id": node_revision_id,
    }
