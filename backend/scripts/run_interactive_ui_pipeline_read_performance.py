#!/usr/bin/env python3
"""Run correctness and preliminary speed cases for pipeline reads."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs/reports/0114-M0_Interactive_UI_Performance_Inventory.json"
MANIFEST = ROOT / "backend/fixtures/interactive-ui-performance/v1/manifest.json"
DEFAULT_CACHE = Path.home() / ".cache/doko-detector/interactive-performance"
RECORDING = "game-2026-08-20-01-001"
IDENTITY_NODE = "e0d2e2fb-53ab-59c5-8991-3aba74f828ae"
IDENTITY_REVISION = "f78c1e0a-2c0f-5312-98d6-b0b9b6650c0e"
POLYGON_NODE = "b5090a82-d8ba-5714-a66b-6ee4e4e707f1"
POLYGON_REVISION = "dd8b1436-cf47-5104-87c6-6b2b0cc4c572"
CALIBRATION_RECORDING = "cardeventnet-IMG_0655"
CALIBRATION_REVISION = "calibration-cd1069b46e30480b057d90b0"
CALIBRATION_SOURCE_NODE = "m4-calibration-visible-cards"
CALIBRATION_SOURCE_REVISION = "visible-cards-visible_cards-run-6e44ce5b-753-attempt-1"
CALIBRATION_PROPOSAL_NODE = "m4-calibration-card-scene-proposals"
CALIBRATION_PROPOSAL_REVISION = (
    "card-scene-proposals-card-scene-proposal-0086-91x59-IMG_0655-retry-65bb8ec7-attempt-1"
)
CALIBRATION_SOURCE_FIXTURE_NODE = "65289367-05b8-5844-8bdd-17c5eeab0c49"
CALIBRATION_SOURCE_FIXTURE_REVISION = "a4d0fba9-ed38-5365-9df0-2596b6be5b3b"
CALIBRATION_PROPOSAL_FIXTURE_NODE = "aa909e7f-041d-573f-8d7b-df634d9f2123"
CALIBRATION_PROPOSAL_FIXTURE_REVISION = "7c1657af-01dc-589f-aec0-32b3e733b9f8"
DRAFT_ID = (
    "calibration-draft-card-scene-proposals-card-scene-proposal-0086-91x59-IMG_0655-"
    "retry-65bb8ec7-attempt-1"
)
UNKNOWN = "22222222-2222-5222-8222-222222222222"
M5_OPERATIONS = {
    ("GET", "/api/recordings/{recording_id}/pipeline/events"),
    ("GET", "/api/recordings/{recording_id}/pipeline/events/selection"),
    ("GET", "/api/recordings/{recording_id}/pipeline/events/{run_id}/result"),
    ("GET", "/api/recordings/{recording_id}/pipeline/observations"),
    ("GET", "/api/recordings/{recording_id}/pipeline/observations/selection"),
    ("GET", "/api/recordings/{recording_id}/pipeline/observations/{run_id}/result"),
    ("GET", "/api/recordings/{recording_id}/pipeline/proposed-card-scenes"),
    ("GET", "/api/recordings/{recording_id}/pipeline/proposed-card-scenes/{run_id}/result"),
    ("GET", "/api/recordings/{recording_id}/pipeline/runs/{run_id}"),
    ("GET", "/api/recordings/{recording_id}/pipeline/visible-cards"),
    ("GET", "/api/recordings/{recording_id}/pipeline/visible-cards/selection"),
    ("GET", "/api/recordings/{recording_id}/pipeline/visible-cards/{run_id}/result"),
    ("GET", "/api/recordings/{recording_id}/pipeline/visual-identities"),
    ("GET", "/api/recordings/{recording_id}/pipeline/visual-identities/proposed-crop-inputs"),
    ("GET", "/api/recordings/{recording_id}/pipeline/visual-identities/selection"),
    ("GET", "/api/recordings/{recording_id}/pipeline/visual-identities/{run_id}/result"),
    ("POST", "/api/recordings/{recording_id}/pipeline/comparisons"),
}


@dataclass(frozen=True)
class Scenario:
    name: str
    route: str
    path: str
    status: int
    check: str
    method: str = "GET"
    body: dict[str, Any] | None = None


def scenarios() -> list[Scenario]:
    cases = [
        Scenario(
            "workspace_full_hard",
            "/api/recordings/{recording_id}/pipeline",
            f"/api/recordings/{RECORDING}/pipeline",
            200,
            "workspace_full",
        ),
        Scenario(
            "workspace_stage_visual_identities_hard",
            "/api/recordings/{recording_id}/pipeline",
            f"/api/recordings/{RECORDING}/pipeline?stage=visual_identities",
            200,
            "workspace_stage",
        ),
        Scenario(
            "workspace_missing",
            "/api/recordings/{recording_id}/pipeline",
            "/api/recordings/missing-m4-recording/pipeline",
            404,
            "recording_missing",
        ),
        Scenario(
            "lineage_hard",
            "/api/recordings/{recording_id}/pipeline/lineage",
            f"/api/recordings/{RECORDING}/pipeline/lineage",
            200,
            "lineage",
        ),
        Scenario(
            "lineage_missing",
            "/api/recordings/{recording_id}/pipeline/lineage",
            "/api/recordings/missing-m4-recording/pipeline/lineage",
            404,
            "recording_missing",
        ),
        Scenario(
            "revision_max_identity_payload",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}",
            f"/api/pipeline/nodes/{IDENTITY_NODE}/revisions/{IDENTITY_REVISION}",
            200,
            "identity_revision",
        ),
        Scenario(
            "revision_max_polygon_payload",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}",
            f"/api/pipeline/nodes/{POLYGON_NODE}/revisions/{POLYGON_REVISION}",
            200,
            "polygon_revision",
        ),
        Scenario(
            "revision_missing_stale",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}",
            f"/api/pipeline/nodes/{IDENTITY_NODE}/revisions/{UNKNOWN}",
            404,
            "node_missing",
        ),
        Scenario(
            "reviews_exact_revision",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}/reviews",
            f"/api/pipeline/nodes/{IDENTITY_NODE}/revisions/{IDENTITY_REVISION}/reviews",
            200,
            "reviews",
        ),
        Scenario(
            "reviews_stale_revision",
            "/api/pipeline/nodes/{node_id}/revisions/{revision_id}/reviews",
            f"/api/pipeline/nodes/{IDENTITY_NODE}/revisions/{UNKNOWN}/reviews",
            404,
            "review_missing",
        ),
        Scenario(
            "calibration_draft_snapshot",
            "/api/recordings/{recording_id}/pipeline/calibration-refinement",
            f"/api/recordings/{CALIBRATION_RECORDING}/pipeline/calibration-refinement?proposal_revision_id={CALIBRATION_PROPOSAL_REVISION}&draft_id={DRAFT_ID}",
            200,
            "draft",
        ),
        Scenario(
            "calibration_draft_invalid_lineage",
            "/api/recordings/{recording_id}/pipeline/calibration-refinement",
            f"/api/recordings/{CALIBRATION_RECORDING}/pipeline/calibration-refinement?proposal_revision_id=7c1657af-01dc-589f-aec0-32b3e733b9f8&draft_id={DRAFT_ID}",
            422,
            "draft_invalid_lineage",
        ),
        Scenario(
            "calibration_draft_missing",
            "/api/recordings/{recording_id}/pipeline/calibration-refinement",
            f"/api/recordings/{CALIBRATION_RECORDING}/pipeline/calibration-refinement?proposal_revision_id={UNKNOWN}&draft_id={UNKNOWN}",
            404,
            "draft_missing",
        ),
        Scenario(
            "calibration_published_snapshot",
            "/api/recordings/{recording_id}/pipeline/calibrations/{calibration_revision_id}",
            f"/api/recordings/{CALIBRATION_RECORDING}/pipeline/calibrations/{CALIBRATION_REVISION}",
            200,
            "calibration",
        ),
        Scenario(
            "calibration_published_missing",
            "/api/recordings/{recording_id}/pipeline/calibrations/{calibration_revision_id}",
            f"/api/recordings/{CALIBRATION_RECORDING}/pipeline/calibrations/{UNKNOWN}",
            404,
            "calibration_missing",
        ),
        Scenario(
            "event_runs_exact",
            "/api/recordings/{recording_id}/pipeline/events",
            f"/api/recordings/{RECORDING}/pipeline/events",
            200,
            "runs_exact",
        ),
        Scenario(
            "event_result_exact",
            "/api/recordings/{recording_id}/pipeline/events/{run_id}/result",
            f"/api/recordings/{RECORDING}/pipeline/events/m5-event-run/result",
            200,
            "event_result_exact",
        ),
        *[
            Scenario(
                f"{stage}_result_missing",
                f"/api/recordings/{{recording_id}}/pipeline/{path}/{{run_id}}/result",
                f"/api/recordings/{RECORDING}/pipeline/{path}/missing-m5-result/result",
                404,
                "stage_result_missing",
            )
            for stage, path in (
                ("event", "events"),
                ("observation", "observations"),
                ("proposed_scene", "proposed-card-scenes"),
                ("visible_card", "visible-cards"),
                ("visual_identity", "visual-identities"),
            )
        ],
        Scenario(
            "event_selection_exact",
            "/api/recordings/{recording_id}/pipeline/events/selection",
            f"/api/recordings/{RECORDING}/pipeline/events/selection",
            200,
            "selection_exact",
        ),
        Scenario(
            "observation_runs_empty",
            "/api/recordings/{recording_id}/pipeline/observations",
            f"/api/recordings/{RECORDING}/pipeline/observations",
            200,
            "runs_empty",
        ),
        Scenario(
            "proposed_scene_runs_empty",
            "/api/recordings/{recording_id}/pipeline/proposed-card-scenes",
            f"/api/recordings/{RECORDING}/pipeline/proposed-card-scenes",
            200,
            "runs_empty",
        ),
        Scenario(
            "visible_card_runs_empty",
            "/api/recordings/{recording_id}/pipeline/visible-cards",
            f"/api/recordings/{RECORDING}/pipeline/visible-cards",
            200,
            "runs_empty",
        ),
        Scenario(
            "visual_identity_runs_empty",
            "/api/recordings/{recording_id}/pipeline/visual-identities",
            f"/api/recordings/{RECORDING}/pipeline/visual-identities",
            200,
            "runs_empty",
        ),
        *[
            Scenario(
                f"{stage}_selection_empty",
                f"/api/recordings/{{recording_id}}/pipeline/{path}/selection",
                f"/api/recordings/{RECORDING}/pipeline/{path}/selection",
                200,
                "selection_empty",
            )
            for stage, path in (
                ("observation", "observations"),
                ("visible_card", "visible-cards"),
                ("visual_identity", "visual-identities"),
            )
        ],
        Scenario(
            "visual_identity_proposed_inputs_empty",
            "/api/recordings/{recording_id}/pipeline/visual-identities/proposed-crop-inputs",
            f"/api/recordings/{RECORDING}/pipeline/visual-identities/proposed-crop-inputs",
            200,
            "inputs_empty",
        ),
        Scenario(
            "automated_run_missing",
            "/api/recordings/{recording_id}/pipeline/runs/{run_id}",
            f"/api/recordings/{RECORDING}/pipeline/runs/missing-m5-run",
            404,
            "automated_run_missing",
        ),
        Scenario(
            "automated_run_exact",
            "/api/recordings/{recording_id}/pipeline/runs/{run_id}",
            f"/api/recordings/{RECORDING}/pipeline/runs/m5-automated-run",
            200,
            "automated_run_exact",
        ),
        Scenario(
            "comparison_missing_inputs",
            "/api/recordings/{recording_id}/pipeline/comparisons",
            f"/api/recordings/{RECORDING}/pipeline/comparisons",
            404,
            "comparison_missing",
            "POST",
            {
                "schema_version": "pipeline-comparison-request/v1",
                "recording_id": RECORDING,
                "content_type": "events",
                "left_run_id": "missing-m5-left",
                "right_run_id": "missing-m5-right",
                "reference_revision_id": "missing-m5-reference",
                "matching_policy": {
                    "policy_id": "event-timing/v1",
                    "anchor": "start_us",
                    "tolerance_us": 1,
                },
            },
        ),
        Scenario(
            "comparison_exact_runs",
            "/api/recordings/{recording_id}/pipeline/comparisons",
            f"/api/recordings/{RECORDING}/pipeline/comparisons",
            200,
            "comparison_exact",
            "POST",
            {
                "schema_version": "pipeline-comparison-request/v1",
                "recording_id": RECORDING,
                "content_type": "events",
                "left_run_id": "m5-event-run",
                "right_run_id": "m5-event-run-right",
                "reference_revision_id": "m5-event-reference",
                "matching_policy": {
                    "policy_id": "event-timing/v1",
                    "anchor": "start_us",
                    "tolerance_us": 1,
                },
            },
        ),
    ]
    inventory = json.loads(INVENTORY.read_text())
    inventory_operations = {
        (item["method"], item["route"])
        for item in inventory["operations"]
        if item["classification"] == "ui"
    }
    expected = M5_OPERATIONS & inventory_operations
    covered = {(case.method, case.route) for case in cases} & M5_OPERATIONS
    if expected != M5_OPERATIONS or covered != expected:
        raise ValueError(
            "pipeline-read inventory mismatch: "
            f"missing={sorted(expected - covered)}, "
            f"unregistered={sorted(M5_OPERATIONS - inventory_operations)}"
        )
    return cases


def _link_hard_snapshot(root: Path, cache: Path) -> None:
    from materialize_interactive_ui_performance_fixtures import validate_hard_snapshot

    validate_hard_snapshot(cache)
    manifest = json.loads(MANIFEST.read_text())
    for asset in manifest["assets"]:
        source = cache / "sha256" / asset["sha256"]
        target = root / asset["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, target)


def _settings(root: Path):
    from dokodetector_backend.config import Settings

    return Settings(
        _env_file=None,
        repository_root=root,
        evidence_root=root / ".runtime",
        operations_root=root / "data/operations",
        repository_intake_root=root / "data/intake/recordings",
        evidence_package_intake_root=root / "data/intake/evidence-packages",
        pending_video_root=root / "data/incoming/videos",
        bonjour_enabled=False,
    )


def _check(case: Scenario, response: httpx.Response) -> str | None:
    if response.status_code != case.status:
        try:
            detail = response.json().get("error")
        except (ValueError, AttributeError):
            detail = None
        return f"expected HTTP {case.status}; got {response.status_code}; error={detail!r}"
    try:
        payload = response.json()
    except ValueError:
        return "response is not JSON"
    check = case.check
    if check in {
        "recording_missing",
        "node_missing",
        "review_missing",
        "draft_missing",
        "calibration_missing",
        "automated_run_missing",
        "comparison_missing",
        "stage_result_missing",
    }:
        expected = {
            "recording_missing": "recording_not_found",
            "node_missing": "pipeline_node_not_found",
            "review_missing": "pipeline_node_review_unavailable",
            "draft_missing": "calibration_refinement_not_found",
            "calibration_missing": "calibration_revision_not_found",
            "automated_run_missing": "pipeline_run_not_found",
            "comparison_missing": "comparison_input_not_found",
            "stage_result_missing": "pipeline_run_not_found",
        }[check]
        if payload.get("error", {}).get("code") != expected:
            return f"expected error code {expected}; got {payload.get('error')}"
    elif check.startswith("workspace"):
        if (
            payload.get("schema_version") != "pipeline-workspace/v1"
            or payload.get("recording_id") != RECORDING
        ):
            return "workspace schema or recording identity mismatch"
        if len(payload.get("stages", [])) != 5:
            return "workspace does not contain the five declared stages"
        if check == "workspace_stage" and not any(
            stage.get("key") == "visual_identities" for stage in payload["stages"]
        ):
            return "stage-filtered workspace omitted the requested stage"
    elif check == "lineage":
        nodes = payload.get("nodes", [])
        node_ids = {node.get("node_id") for node in nodes}
        revisions = {
            (item.get("node_id"), item.get("revision_id")) for item in payload.get("revisions", [])
        }
        expected_nodes = {IDENTITY_NODE, POLYGON_NODE}
        expected_revisions = {
            (IDENTITY_NODE, IDENTITY_REVISION),
            (POLYGON_NODE, POLYGON_REVISION),
        }
        if not expected_nodes <= node_ids or not expected_revisions <= revisions:
            return "lineage omitted exact fixture nodes or revisions"
        expected_parents = {
            ("b63729af-60c9-54dd-be3f-f6220db3d19c", "c7f4da13-b918-5009-8ff8-5aec7e099cfe"),
            ("29ff4e43-4ade-568a-9e2f-36b95d075067", "391c5a12-d875-5f8e-b5ee-dd6a75f89695"),
        }
        parent_edges = {
            (edge["from"][1], edge["from"][2])
            for edge in payload.get("edges", [])
            if edge.get("kind") == "copied" and edge.get("from", [None])[0] == "revision"
        }
        if not expected_parents <= parent_edges:
            return "lineage omitted exact fixture parent revisions"
    elif check in {"identity_revision", "polygon_revision"}:
        node, revision = (
            (IDENTITY_NODE, IDENTITY_REVISION)
            if check == "identity_revision"
            else (POLYGON_NODE, POLYGON_REVISION)
        )
        if (payload.get("node_id"), payload.get("revision_id")) != (node, revision):
            return "revision node or revision identity mismatch"
        content = payload.get("content", {})
        values = content.get("items", content.get("visible_cards", content.get("identities", [])))
        if not values and len(json.dumps(content)) < 1000:
            return "expected retained maximum-payload revision content"
    elif check == "reviews":
        if not isinstance(payload, list):
            return "reviews response is not a list"
    elif check == "draft":
        draft = payload.get("draft", {})
        if draft.get("draft_id") != DRAFT_ID:
            return f"calibration draft identity mismatch: {draft.get('draft_id')!r}"
        if payload.get("recording_id") != CALIBRATION_RECORDING:
            return "calibration draft recording identity mismatch"
        if payload.get("proposal_revision_id") != CALIBRATION_PROPOSAL_REVISION:
            return "calibration draft proposal identity mismatch"
    elif check == "calibration":
        if (
            payload.get("calibration_revision_id") != CALIBRATION_REVISION
            or payload.get("recording_id") != CALIBRATION_RECORDING
        ):
            return "published calibration identity mismatch"
    elif check == "runs_empty":
        if payload.get("recording_id") != RECORDING or payload.get("runs") != []:
            return "pipeline run list identity or sparse content mismatch"
    elif check == "runs_exact":
        runs = payload.get("runs", [])
        if payload.get("recording_id") != RECORDING or len(runs) != 1:
            return "pipeline run list identity or count mismatch"
        if runs[0].get("run_id") != "m5-event-run":
            return "pipeline run list omitted the exact selected run"
    elif check == "selection_empty":
        if payload.get("recording_id") != RECORDING or payload.get("selection") is not None:
            return "empty pipeline selection identity or value mismatch"
    elif check == "selection_exact":
        selection = payload.get("selection") or {}
        if payload.get("recording_id") != RECORDING:
            return "pipeline selection recording identity mismatch"
        if selection.get("selected_generated") != {
            "node_id": "data-" + hashlib.sha256(b"m5-event-revision").hexdigest()[:32],
            "revision_id": "m5-event-revision",
        }:
            return "pipeline selection omitted the exact generated revision"
    elif check == "inputs_empty":
        if payload.get("recording_id") != RECORDING or payload.get("inputs") != []:
            return "empty proposed-crop input identity or content mismatch"
    elif check == "event_result_exact":
        if (
            payload.get("run_id"),
            payload.get("recording_id"),
            payload.get("processor_type"),
        ) != (
            "m5-event-run",
            RECORDING,
            "event-detection",
        ):
            return "event result run or recording identity mismatch"
        revisions = payload.get("revisions", [])
        if (
            len(revisions) != 1
            or revisions[0].get("manifest", {}).get("revision_id") != "m5-event-revision"
        ):
            return "event result omitted the exact output revision"
    elif check == "comparison_exact":
        if (
            payload.get("recording_id") != RECORDING
            or payload.get("content_type") != "events"
            or payload.get("left", {}).get("run_id") != "m5-event-run"
            or payload.get("right", {}).get("run_id") != "m5-event-run-right"
            or payload.get("reference", {}).get("revision_id") != "m5-event-reference"
        ):
            return "comparison omitted exact run or reference identities"
    elif check == "automated_run_exact":
        if payload.get("run_id") != "m5-automated-run" or payload.get("recording_id") != RECORDING:
            return "automated pipeline run identity mismatch"
    return None


def _seed_event_result(app: Any, *, include_comparison: bool = False) -> None:
    """Seed a small valid event run through production stores in disposable storage."""
    runs = app.state.pipeline_run_store
    node_id = "data-" + hashlib.sha256(b"m5-event-revision").hexdigest()[:32]
    if runs.get("m5-event-run") is None:
        _create_event_run(runs, source_id=node_id)
        _create_event_reference(
            runs, source_id="data-" + hashlib.sha256(b"m5-event-reference").hexdigest()[:32]
        )
    if include_comparison and runs.get("m5-event-run-right") is None:
        _create_event_run(
            runs,
            source_id="data-" + hashlib.sha256(b"m5-event-revision-right").hexdigest()[:32],
            run_id="m5-event-run-right",
            revision_id="m5-event-revision-right",
        )
    selection_store = app.state.event_pipeline_service.selection_store
    if selection_store.get_exact(RECORDING, "events") is None:
        selection_store.update_exact(
            RECORDING,
            "events",
            expected_revision=0,
            selected_generated={"node_id": node_id, "revision_id": "m5-event-revision"},
            selected_completed_reference=None,
            updated_at="2026-11-07T00:00:04Z",
        )


def _create_event_reference(runs: Any, *, source_id: str) -> None:
    from doko_operations.pipeline_data import (
        DataRevision,
        EventData,
        HumanProducer,
        RecordingVideoSource,
        canonical_event_data_bytes,
        sha256_bytes,
    )

    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    source = RecordingVideoSource(
        recording_id=RECORDING,
        relative_path="recordings/m5-event/video.mov",
        video_sha256="a" * 64,
        byte_length=100,
        duration_us=1_000_000,
    )
    content = EventData.from_mapping(
        {
            "schema_version": "event-data/v1",
            "events": [
                {
                    "event_id": "m5-reference-event",
                    "event_type": "card_state_changed",
                    "start_us": 100_000,
                    "end_us": 110_000,
                }
            ],
        }
    )
    manifest = DataRevision(
        revision_id="m5-event-reference",
        content_type="events",
        content_schema="event-data/v1",
        recording_id=RECORDING,
        source=source,
        content_sha256=sha256_bytes(canonical_event_data_bytes(content)),
        input_revision_ids=(),
        origin="manual",
        producer=HumanProducer(review_id="m5-fixture-review", operator_id="fixture"),
        coverage={
            "kind": "event_intervals",
            "intervals": [{"start_us": 0, "end_us": 1_000_000}],
        },
        created_at="2026-11-07T00:00:05Z",
    )
    PipelineNodeStore(runs.storage.operations_root / "pipeline-nodes").create(
        source_id,
        "M5 event reference fixture",
        "events",
        source.to_mapping(),
        content.to_mapping(),
        {
            "origin": manifest.origin,
            "input_revision_ids": [],
            "producer": manifest.producer.to_mapping(),
            "coverage": manifest.coverage,
            "data_revision": manifest.to_mapping(),
        },
        revision_id="m5-event-reference",
    )


def _seed_automated_run(app: Any) -> None:
    stages = (
        "event_proposals",
        "visible_card_and_pile_proposals",
        "card_scene_and_calibration",
        "visual_identity_proposals",
        "table_observations",
        "reconstruction",
    )
    app.state.automated_pipeline_run_service.store.create(
        {
            "schema_version": "automated-pipeline-run/v1",
            "run_id": "m5-automated-run",
            "job_id": None,
            "recording_id": RECORDING,
            "status": "complete",
            "created_at": "2026-11-07T00:00:00Z",
            "updated_at": "2026-11-07T00:00:03Z",
            "source": {"recording_id": RECORDING, "video_sha256": "a" * 64},
            "request_sha256": "b" * 64,
            "client_request_sha256": "c" * 64,
            "request": {},
            "resolved_providers": {},
            "failure": None,
            "stages": [
                {
                    "name": name,
                    "status": "complete",
                    "run_id": None,
                    "child_job_id": None,
                    "input_revision_ids": [],
                    "output_revision_ids": [],
                    "failure": None,
                }
                for name in stages
            ],
        }
    )


def _create_event_run(
    runs: Any,
    *,
    source_id: str,
    run_id: str = "m5-event-run",
    revision_id: str = "m5-event-revision",
) -> None:
    from doko_operations.pipeline_data import (
        DataRevision,
        EventData,
        ProcessorProducer,
        ProcessorRunRequest,
        RecordingVideoSource,
        canonical_event_data_bytes,
        sha256_bytes,
    )

    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    source = RecordingVideoSource(
        recording_id=RECORDING,
        relative_path="recordings/m5-event/video.mov",
        video_sha256="a" * 64,
        byte_length=100,
        duration_us=1_000_000,
    )
    content = EventData.from_mapping(
        {
            "schema_version": "event-data/v1",
            "events": [
                {
                    "event_id": "m5-event",
                    "event_type": "card_state_changed",
                    "start_us": 100_000,
                    "end_us": 110_000,
                }
            ],
        }
    )
    request = ProcessorRunRequest.from_mapping(
        {
            "schema_version": "processor-run-request/v1",
            "run_id": run_id,
            "processor_type": "event-detection",
            "source": source.to_mapping(),
            "input_revision_ids": [],
            "implementation": {"name": "m5-fixture", "version": "1"},
            "configuration": {"fixture": True},
            "extraction_policy": {"policy_id": "event-extract/v1"},
            "crop_policy": None,
        }
    )
    runs.create(request, created_at="2026-11-07T00:00:00Z")
    runs.start(run_id, started_at="2026-11-07T00:00:01Z")
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="events",
        content_schema="event-data/v1",
        recording_id=RECORDING,
        source=source,
        content_sha256=sha256_bytes(canonical_event_data_bytes(content)),
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id=run_id,
            processor_type="event-detection",
            implementation_id="m5-fixture/1",
        ),
        coverage={"kind": "full-recording"},
        created_at="2026-11-07T00:00:02Z",
    )
    PipelineNodeStore(runs.storage.operations_root / "pipeline-nodes").create(
        source_id,
        "M5 event fixture",
        "events",
        source.to_mapping(),
        content.to_mapping(),
        {
            "origin": "processor",
            "input_revision_ids": [],
            "producer": manifest.producer.to_mapping(),
            "coverage": manifest.coverage,
            "data_revision": manifest.to_mapping(),
        },
        revision_id=revision_id,
    )
    runs.complete(run_id, [revision_id], completed_at="2026-11-07T00:00:03Z")


async def _exercise(
    app: Any,
    case: Scenario,
    warmups: int,
    repeats: int,
    timeout: float,
    samples: list[dict[str, Any]],
    profile: str,
    batch: int,
) -> None:
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://m4.local", timeout=timeout
        ) as client,
    ):

        async def sample(*, cache_state: str, warmup: bool, iteration: int) -> None:
            started = time.perf_counter_ns()
            try:
                response = await asyncio.wait_for(
                    client.request(case.method, case.path, json=case.body), timeout=timeout
                )
                error = _check(case, response)
                row = {
                    "case": case.name,
                    "profile": profile,
                    "cache_state": cache_state,
                    "batch": batch,
                    "iteration": iteration,
                    "warmup": warmup,
                    "duration_ns": time.perf_counter_ns() - started,
                    "status_code": response.status_code,
                    "response_bytes": len(response.content),
                    "response_sha256": hashlib.sha256(response.content).hexdigest(),
                    "ok": error is None,
                    "error": error,
                }
            except Exception as exc:
                row = {
                    "case": case.name,
                    "profile": profile,
                    "cache_state": cache_state,
                    "batch": batch,
                    "iteration": iteration,
                    "warmup": warmup,
                    "duration_ns": time.perf_counter_ns() - started,
                    "status_code": 0,
                    "response_bytes": 0,
                    "response_sha256": hashlib.sha256(b"").hexdigest(),
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            samples.append(row)

        await sample(cache_state="cold", warmup=False, iteration=0)
        for iteration in range(warmups):
            await sample(cache_state="warm", warmup=True, iteration=iteration)
        for iteration in range(repeats):
            await sample(cache_state="warm", warmup=False, iteration=iteration)


def _prepare_current_calibration_draft_fixture(root: Path) -> None:
    """Create current-schema lineage records in disposable storage with production stores."""
    from unittest.mock import patch

    import dokodetector_backend.pipeline_node_store as node_store_module
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    store = PipelineNodeStore(root / "data/operations/pipeline-nodes")
    source_revision = store.read_revision_record(
        CALIBRATION_SOURCE_FIXTURE_NODE, CALIBRATION_SOURCE_FIXTURE_REVISION
    )
    source_node = store.get(CALIBRATION_SOURCE_FIXTURE_NODE)
    with patch.object(
        node_store_module, "_canonical_timestamp", return_value="2026-11-07T00:00:00Z"
    ):
        store.create(
            CALIBRATION_SOURCE_NODE,
            "M4 calibration detector input",
            "visible_cards",
            source_node.source,
            source_revision.content,
            source_revision.metadata,
            revision_id=CALIBRATION_SOURCE_REVISION,
        )

    proposal_revision = store.read_revision_record(
        CALIBRATION_PROPOSAL_FIXTURE_NODE, CALIBRATION_PROPOSAL_FIXTURE_REVISION
    )
    proposal_node = store.get(CALIBRATION_PROPOSAL_FIXTURE_NODE)
    metadata = dict(proposal_revision.metadata)
    metadata["input_revision_ids"] = [CALIBRATION_SOURCE_REVISION]
    with patch.object(
        node_store_module, "_canonical_timestamp", return_value="2026-11-07T00:00:00Z"
    ):
        store.create(
            CALIBRATION_PROPOSAL_NODE,
            "M4 calibration proposal input",
            "card_scene_proposals",
            proposal_node.source,
            proposal_revision.content,
            metadata,
            revision_id=CALIBRATION_PROPOSAL_REVISION,
        )


def run(
    *,
    hard_cache: Path,
    warmups: int,
    repeats: int,
    batches: int,
    timeout: float,
    case_names: set[str] | None = None,
) -> dict[str, Any]:
    from dokodetector_backend.app import create_app

    cases = scenarios()
    if case_names is not None:
        cases = [case for case in cases if case.name in case_names]
        if {case.name for case in cases} != case_names:
            raise ValueError(
                f"unknown scenario names: {sorted(case_names - {case.name for case in cases})}"
            )
    samples: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="doko-ui-pipeline-m4-") as temp:
        parent = Path(temp)
        for batch in range(batches):
            root = parent / f"hard-{batch}"
            root.mkdir()
            _link_hard_snapshot(root, hard_cache)
            _prepare_current_calibration_draft_fixture(root)
            for case in cases:
                app = create_app(_settings(root))
                if case.name in {
                    "event_runs_exact",
                    "event_result_exact",
                    "event_selection_exact",
                    "comparison_exact_runs",
                }:
                    _seed_event_result(app, include_comparison=case.name == "comparison_exact_runs")
                if case.name == "automated_run_exact":
                    _seed_automated_run(app)
                asyncio.run(_exercise(app, case, warmups, repeats, timeout, samples, "hard", batch))
    distributions = []
    groups: dict[str, list[int]] = {}
    for sample in samples:
        if not sample["warmup"] and sample["ok"]:
            groups.setdefault(
                f"{sample['profile']}:{sample['case']}:{sample['cache_state']}", []
            ).append(sample["duration_ns"])
    for name, values in sorted(groups.items()):
        distributions.append(
            {
                "case": name,
                "samples": len(values),
                "median_ns": statistics.median(values),
                "max_ns": max(values),
            }
        )
    return {
        "schema_version": "interactive-ui-pipeline-read-samples/v1",
        "kind": "preliminary_samples",
        "protocol": {
            "warmups": warmups,
            "repeats": repeats,
            "batches": batches,
            "timeout_seconds": timeout,
            "cache_policy": "fresh isolated app per batch; first measured request is process-cold, "
            "subsequent requests are warm; OS filesystem cache not flushed",
        },
        "fixture_manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "samples": samples,
        "distributions": distributions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hard-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--batches", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--case", action="append", help="Run one named case; may be repeated")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.warmups, args.repeats) < 0 or args.batches < 1:
        parser.error("warmups and repeats cannot be negative; batches must be positive")
    result = run(
        hard_cache=args.hard_cache,
        warmups=args.warmups,
        repeats=args.repeats,
        batches=args.batches,
        timeout=args.timeout,
        case_names=None if args.case is None else set(args.case),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    failed = [sample for sample in result["samples"] if not sample["ok"]]
    print(f"Wrote {len(result['samples'])} samples to {args.output}; failures={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
