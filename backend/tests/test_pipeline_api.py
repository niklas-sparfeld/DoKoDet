from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app_factory import create_test_app
from doko_operations.pipeline_data import CARD_STATE_CHANGED_EVENT_TYPE
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_api import router as pipeline_router
from dokodetector_backend.pipeline_comparison_api import router as comparison_router
from dokodetector_backend.pipeline_run_api import router as run_router
from dokodetector_backend.pipeline_stage_api import router as stage_router
from dokodetector_backend.pipeline_workspace_api import router as workspace_router
from dokodetector_backend.pipeline_workspace_service import RecordingPipelineWorkspaceService

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"
RECORDING_ID = "recording-both"


def test_pipeline_route_inventory_stays_in_focused_modules() -> None:
    child_routers = (
        workspace_router,
        run_router,
        stage_router,
        comparison_router,
    )
    routes = [
        route
        for child_router in child_routers
        for route in child_router.routes
        if route.include_in_schema
    ]

    modules = {}
    for route in routes:
        modules.setdefault(route.endpoint.__module__, 0)
        modules[route.endpoint.__module__] += 1

    assert modules == {
        "dokodetector_backend.pipeline_workspace_api": 2,
        "dokodetector_backend.pipeline_run_api": 2,
        "dokodetector_backend.pipeline_stage_api": 26,
        "dokodetector_backend.pipeline_comparison_api": 1,
    }
    assert len(pipeline_router.routes) == len(child_routers) + 2


def test_legacy_reference_and_review_routes_are_not_mounted(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    with TestClient(app) as client:
        base = f"/api/recordings/{RECORDING_ID}/pipeline"
        assert client.get(f"{base}/references/events").status_code == 404
        assert client.get(f"{base}/visible-card-reviews").status_code == 404
        assert client.post(f"{base}/visual-identities/auto-approval-plan").status_code == 404


def test_pipeline_composition_reuses_shared_stores_across_services(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    with TestClient(app):
        run_store = app.state.pipeline_run_store
        selection_store = app.state.pipeline_selection_store

        services = (
            app.state.event_pipeline_service,
            app.state.visible_card_pipeline_service,
            app.state.proposed_card_scene_pipeline_service,
            app.state.visual_identity_pipeline_service,
            app.state.observation_pipeline_service,
        )
        assert not hasattr(app.state, "pipeline_revision_store")
        assert all(not hasattr(service, "revision_store") for service in services)
        assert run_store.lineage_writer is app.state.pipeline_lineage_writer
        assert all(service.run_store is run_store for service in services)
        assert all(service.selection_store is selection_store for service in services)
        assert (
            app.state.calibration_refinement_service.store.workspace_root
            == _settings(tmp_path).operations_root / "calibration-refinement-drafts"
        )
        assert not hasattr(app.state.pipeline_workspace_service, "revision_store")
        assert app.state.pipeline_workspace_service.run_store is run_store
        assert app.state.pipeline_workspace_service.selection_store is selection_store
        assert (
            selection_store.root
            == app.state.pipeline_lineage_service.store.root / ".pipeline-node-selections"
        )
        assert not hasattr(app.state, "pipeline_reference_service")
        assert not hasattr(app.state, "pipeline_reference_store")
        assert not hasattr(app.state, "visible_card_review_service")
        assert not hasattr(app.state, "visible_card_review_store")
        assert (
            app.state.pipeline_workspace_service.recording_source_provider.__self__
            is app.state.event_pipeline_service
        )


class FakeEventProvider:
    def __init__(
        self,
        events: list[dict[str, object]] | None = None,
        probabilities: list[dict[str, object]] | None = None,
    ) -> None:
        self.events = events or [{"time_s": 0.5, "probability": 0.95}]
        self.probabilities = probabilities
        self.calls: list[Path] = []

    def infer(
        self,
        video_path: Path,
        *,
        request: object,
        progress_callback: object | None = None,
    ) -> dict[str, object]:
        del request, progress_callback
        self.calls.append(video_path)
        result: dict[str, object] = {"events": self.events}
        if self.probabilities is not None:
            result["probabilities"] = self.probabilities
        return result


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        repository_root=tmp_path,
        evidence_root=tmp_path / "runtime",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
        pending_video_root=tmp_path / "pending-videos",
    )


def _install_recording(tmp_path: Path) -> None:
    bundle = tmp_path / "recordings" / RECORDING_ID
    shutil.copytree(FIXTURE_ROOT, bundle)
    video_path = bundle / "videos" / "video-both.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=2",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(video_path),
        ],
        check=True,
    )
    digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
    byte_length = video_path.stat().st_size
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["source_sha256"] = digest
    manifest["files"]["video"].update(byte_length=byte_length, sha256=digest)
    manifest_path.write_text(json.dumps(manifest, separators=(",", ":")))

    source_path = bundle / "source-record.json"
    source = json.loads(source_path.read_text())
    source.update(byte_length=byte_length, sha256=digest)
    source_path.write_text(json.dumps(source, separators=(",", ":")))
    proposal_path = bundle / "predictions" / "proposal-both.json"
    proposal = json.loads(proposal_path.read_text())
    proposal["source_sha256"] = digest
    proposal_path.write_text(json.dumps(proposal, separators=(",", ":")))
    manifest = json.loads(manifest_path.read_text())
    for relative_path, path in (
        ("source_record", source_path),
        ("proposal_generator_runs", proposal_path),
    ):
        descriptor = (
            manifest["files"][relative_path]
            if relative_path == "source_record"
            else manifest["files"][relative_path][0]
        )
        raw = path.read_bytes()
        descriptor.update(byte_length=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest_path.write_text(json.dumps(manifest, separators=(",", ":")))


def _request(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "implementation": {"name": "fake-event-provider", "version": "v1"},
        "configuration": {"threshold": 0.5},
        "extraction_policy": {"policy_id": "exact-event/v1"},
    }


def _wait_for_status(client: TestClient, run_id: str, expected: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{run_id}")
        job = response.json()
        if job["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            result = client.get(
                f"/api/recordings/{RECORDING_ID}/pipeline/events/{run_id}/result"
            ).json()
            if result.get("state", {}).get("status") == expected:
                return result
        state = {
            "succeeded": "complete",
            "cancelled": "failed",
            "interrupted": "failed",
        }.get(job["state"], job["state"])
        step = job["steps"][0] if job["steps"] else {}
        body = {
            "state": {
                "status": state,
                "progress": {
                    "completed": step.get("completed", 0),
                    "total": step.get("total", 0),
                },
                "terminal_failure": job["failure"],
                "output_revision_ids": [result["id"] for result in job["results"]],
            }
        }
        if state == expected:
            return body
        time.sleep(0.01)
    return body


def _enqueue_event_job(
    client: TestClient,
    recording_id: str,
    payload: dict[str, Any],
    *,
    import_predictions: bool = False,
):
    return client.post(
        "/api/jobs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "type": "event_import" if import_predictions else "event_processing",
            "context": {"recording_id": recording_id},
            "request": payload,
        },
    )


def test_event_pipeline_exposes_provider_progress_while_running(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    started = threading.Event()
    release = threading.Event()

    class ProgressEventProvider:
        def infer(
            self,
            video_path: Path,
            *,
            request: object,
            progress_callback: object | None = None,
        ) -> dict[str, object]:
            del video_path, request
            if callable(progress_callback):
                progress_callback(3, 10)
            started.set()
            assert release.wait(timeout=5.0)
            if callable(progress_callback):
                progress_callback(10, 10)
            return {"events": [{"time_s": 0.5, "probability": 0.95}]}

    app = create_test_app(_settings(tmp_path), event_provider=ProgressEventProvider())
    with TestClient(app) as client:
        created = _enqueue_event_job(client, RECORDING_ID, _request("run-progress"))
        assert created.status_code == 202
        run_id = created.json()["id"]
        assert started.wait(timeout=5.0)

        deadline = time.monotonic() + 5
        progress = None
        while time.monotonic() < deadline:
            status = client.get(f"/api/jobs/{run_id}").json()
            step = status["steps"][0] if status["steps"] else {}
            progress = {"completed": step.get("completed"), "total": step.get("total")}
            if progress == {"completed": 3, "total": 10}:
                break
            time.sleep(0.01)
        assert progress == {"completed": 3, "total": 10}

        release.set()
        status = _wait_for_status(client, run_id, "complete")
        assert status["state"]["progress"] == {"completed": 1, "total": 1}


def test_generated_events_are_stored_and_selected_from_video_only(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    provider = FakeEventProvider()
    app = create_test_app(_settings(tmp_path), event_provider=provider)

    direct_body = app.state.pipeline_workspace_service.get_workspace(RECORDING_ID)
    assert direct_body["schema_version"] == "pipeline-workspace/v1"
    assert direct_body["video"]["recording_id"] == RECORDING_ID

    with TestClient(app) as client:
        created = _enqueue_event_job(client, RECORDING_ID, _request("run-generated"))
        assert created.status_code == 202
        run_id = created.json()["id"]

        status = _wait_for_status(client, run_id, "complete")
        result = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/events/{run_id}/result")
        assert result.status_code == 200
        body = result.json()
        assert status["state"]["status"] == "complete"
        assert body["state"]["status"] == "complete"
        assert body["state"]["progress"] == {"completed": 1, "total": 1}
        assert body["state"]["items"][0]["item_id"] == "event-000000"
        assert body["state"]["items"][0]["result"]["event_type"] == (CARD_STATE_CHANGED_EVENT_TYPE)
        assert body["revisions"][0]["content"]["events"][0]["start_us"] == 500_000
        assert body["revisions"][0]["content"]["events"][0]["event_type"] == (
            CARD_STATE_CHANGED_EVENT_TYPE
        )
        assert body["revisions"][0]["manifest"]["producer"]["kind"] == "processor"
        selection = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/events/selection")
        assert (
            selection.json()["selection"]["selected_generated"]["revision_id"]
            == (body["state"]["output_revision_ids"][0])
        )
        exact_selection = selection.json()["selection"]
        updated = client.put(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/selection",
            json={
                "expected_revision": exact_selection["revision"],
                "selected_generated": exact_selection["selected_generated"],
            },
        )
        assert updated.status_code == 200, updated.text
        assert (
            updated.json()["selection"]["selected_generated"]
            == exact_selection["selected_generated"]
        )
        assert updated.json()["selection"]["revision"] == exact_selection["revision"] + 1
    assert len(provider.calls) == 1


def test_recording_lineage_endpoint_returns_an_empty_exact_graph_until_migration(
    tmp_path: Path,
) -> None:
    _install_recording(tmp_path)
    app = create_test_app(_settings(tmp_path))

    with TestClient(app) as client:
        response = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/lineage")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "pipeline-lineage-graph/v1",
        "nodes": [],
        "revisions": [],
        "runs": [],
        "artifacts": [],
        "edges": [],
    }


def test_cardeventnet_probability_metrics_are_stored_with_the_run(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    provider = FakeEventProvider(
        probabilities=[
            {"time_s": 0.0, "probability": 0.1, "logit": -2.2},
            {"time_s": 0.5, "probability": 0.95, "logit": 2.9},
        ]
    )
    app = create_test_app(_settings(tmp_path), event_provider=provider)

    with TestClient(app) as client:
        created = _enqueue_event_job(client, RECORDING_ID, _request("run-metrics"))
        assert created.status_code == 202
        run_id = created.json()["id"]
        status = _wait_for_status(client, run_id, "complete")

        metrics = status["state"]["metrics"]
        assert metrics == {
            "schema_version": "cardeventnet-metrics/v1",
            "probabilities": [
                {"time_s": 0.0, "probability": 0.1, "logit": -2.2},
                {"time_s": 0.5, "probability": 0.95, "logit": 2.9},
            ],
            "threshold": 0.5,
            "events": [{"time_s": 0.5, "probability": 0.95}],
        }
        result = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/events/{run_id}/result")
        assert result.status_code == 200
        assert result.json()["state"]["metrics"] == metrics


def test_default_card_event_provider_does_not_discover_legacy_checkpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import cardevent

    _install_recording(tmp_path)
    checkpoint = tmp_path / "card_event_net" / "data" / "outputs" / "run" / "best.pt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"fixture-checkpoint")

    def fake_infer_from_files(checkpoint_path, video_path, **kwargs):
        del checkpoint_path, video_path, kwargs
        return {"events": []}

    monkeypatch.setattr(cardevent, "infer_from_files", fake_infer_from_files)
    app = create_test_app(_settings(tmp_path))

    with TestClient(app) as client:
        created = _enqueue_event_job(client, RECORDING_ID, _request("run-default-cardevent"))

        assert created.status_code == 422
        assert "model-campaign integration contract" in created.json()["error"]["message"]


def test_default_card_event_provider_uses_0063_integration_checkpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import cardevent

    _install_recording(tmp_path)
    checkpoint = (
        tmp_path
        / "data"
        / "model-campaigns"
        / "cardeventnet-0063-m9-hard-negative-ablation"
        / "runs"
        / "candidate-hard-negative-v1"
        / "best.pt"
    )
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"integration-checkpoint")
    contract_path = (
        tmp_path
        / "data"
        / "model-campaigns"
        / "cardeventnet-0063-m14-development-integration"
        / "integration-contract.json"
    )
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text(
        json.dumps(
            {
                "schema_version": "cardeventnet-m15-integration-contract/v1",
                "role": "development_integration_model",
                "production_promotion_eligible": False,
                "threshold": 0.4271905720233917,
                "decoder": {"min_event_gap_s": 0.625},
                "checkpoint": {
                    "path": checkpoint.relative_to(tmp_path).as_posix(),
                    "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                },
            }
        )
    )

    calls: dict[str, object] = {}

    def fake_infer_from_files(checkpoint_path, video_path, **kwargs):
        calls.update(checkpoint_path=checkpoint_path, video_path=video_path, kwargs=kwargs)
        return {"events": []}

    monkeypatch.setattr(cardevent, "infer_from_files", fake_infer_from_files)
    app = create_test_app(_settings(tmp_path))

    with TestClient(app) as client:
        request = _request("run-0063-integration-cardevent")
        request["configuration"] = {}
        created = _enqueue_event_job(client, RECORDING_ID, request)

        assert created.status_code == 202
        run_id = created.json()["id"]
        assert created.json()["request"]["processor_request"]["configuration"][
            "checkpoint_path"
        ] == (
            "data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/"
            "runs/candidate-hard-negative-v1/best.pt"
        )
        assert created.json()["request"]["processor_request"]["configuration"] == {
            "checkpoint_path": (
                "data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/"
                "runs/candidate-hard-negative-v1/best.pt"
            ),
            "threshold": 0.4271905720233917,
            "merge_window_s": 0.625,
            "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        }
        assert _wait_for_status(client, run_id, "complete")["state"]["status"] == "complete"
    assert calls["checkpoint_path"] == checkpoint


def test_recording_pipeline_workspace_aggregates_persisted_stage_state(
    tmp_path: Path,
) -> None:
    _install_recording(tmp_path)
    provider = FakeEventProvider()
    app = create_test_app(_settings(tmp_path), event_provider=provider)

    with TestClient(app) as client:
        initial = client.get(f"/api/recordings/{RECORDING_ID}/pipeline")
        assert initial.status_code == 200
        initial_body = initial.json()
        assert initial_body["schema_version"] == "pipeline-workspace/v1"
        assert initial_body["recording_id"] == RECORDING_ID
        assert initial_body["video"]["duration_us"] == 1_000_000
        assert [stage["key"] for stage in initial_body["stages"]] == [
            "events",
            "visible_cards",
            "visual_identities",
            "table_observations",
            "round_analyses",
        ]
        assert initial_body["stages"][0]["state"] == "video-only"
        assert initial_body["stages"][0]["selection_revision"] is None
        assert initial_body["stages"][1]["state"] == "empty"

        created = _enqueue_event_job(client, RECORDING_ID, _request("workspace-run"))
        assert created.status_code == 202
        _wait_for_status(client, created.json()["id"], "complete")

        workspace = client.get(f"/api/recordings/{RECORDING_ID}/pipeline")
        assert workspace.status_code == 200
        body = workspace.json()
        events = body["stages"][0]
        selected = events["selected_generated"]
        revision_id = selected["revision_id"]
        assert events["state"] == "data-available"
        assert revision_id is not None
        assert events["selection_revision"] == 1
        assert events["comparable_run_ids"] == [created.json()["id"]]
        assert events["runs"][0]["run_id"] == created.json()["id"]
        assert events["runs"][0]["input_revision_ids"] == []
        assert events["runs"][0]["implementation"] == {
            "name": "fake-event-provider",
            "version": "v1",
        }
        assert events["runs"][0]["state"]["items"] == []
        assert events["runs"][0]["output_revision_ids"] == [revision_id]
        assert selected["node_id"] == events["input_options"][0]["node_id"]
        assert events["input_options"][0]["node_revision_id"] == revision_id
        assert events["input_options"][0]["node_id"]
        assert events["input_options"][0]["origin"] == "processor"

        # Processor results have one canonical node write and no revision-store copy.
        assert not hasattr(app.state, "pipeline_revision_store")

        catalog = client.get("/v1/recordings")
        assert catalog.status_code == 200
        assert catalog.json()["recordings"][0]["pipeline_status"]["stages"] == [
            {"key": "events", "state": "data-available"},
            {"key": "visible_cards", "state": "empty"},
            {"key": "visual_identities", "state": "empty"},
            {"key": "table_observations", "state": "empty"},
            {"key": "round_analyses", "state": "empty"},
        ]

        reloaded = client.get(f"/api/recordings/{RECORDING_ID}/pipeline")
        assert reloaded.json() == body


def test_recording_pipeline_workspace_reads_each_selection_once(
    tmp_path: Path, monkeypatch
) -> None:
    _install_recording(tmp_path)
    app = create_test_app(_settings(tmp_path), event_provider=FakeEventProvider())
    selection_store = app.state.pipeline_selection_store
    original_get = selection_store.get_exact
    calls: list[tuple[str, str]] = []

    def traced_get(recording_id: str, content_type: str):
        calls.append((recording_id, content_type))
        return original_get(recording_id, content_type)

    def fail_full_lineage_snapshot(*_args, **_kwargs):
        raise AssertionError("workspace summaries must not rebuild the full lineage graph")

    monkeypatch.setattr(selection_store, "get_exact", traced_get)
    monkeypatch.setattr(app.state.pipeline_lineage_service, "snapshot", fail_full_lineage_snapshot)

    workspace = app.state.pipeline_workspace_service.get_workspace(RECORDING_ID)

    assert workspace["schema_version"] == "pipeline-workspace/v1"
    assert calls == [
        (RECORDING_ID, "events"),
        (RECORDING_ID, "visible_cards"),
        (RECORDING_ID, "visual_identities"),
        (RECORDING_ID, "table_observations"),
    ]


def test_workspace_run_summary_omits_frozen_crop_items() -> None:
    crop_items = [{"card_id": f"card-{index}"} for index in range(100)]
    request_mapping = {"crop_input": {"items": crop_items, "source_revision_id": "rev-1"}}
    request = SimpleNamespace(
        to_mapping=lambda: deepcopy(request_mapping),
        input_revision_ids=("rev-1",),
        implementation=SimpleNamespace(to_mapping=lambda: {"name": "test", "version": "1"}),
        model=None,
        configuration={},
        extraction_policy={},
        crop_policy={},
    )
    state = SimpleNamespace(
        status="complete",
        attempt=1,
        to_mapping=lambda: {"status": "complete"},
        output_revision_ids=("output-1",),
        created_at="2026-01-01T00:00:00Z",
        started_at=None,
        completed_at="2026-01-01T00:00:01Z",
        updated_at="2026-01-01T00:00:01Z",
        progress=SimpleNamespace(to_mapping=lambda: {"completed": 100, "total": 100}),
        terminal_failure=None,
        items=(),
    )

    summary = RecordingPipelineWorkspaceService._run_summary(
        SimpleNamespace(run_id="run-1", request=request, state=state)
    )

    assert summary["request"]["crop_input"] == {
        "item_count": 100,
        "source_revision_id": "rev-1",
    }
    assert request_mapping["crop_input"]["items"] is crop_items


def test_workspace_run_summary_uses_exact_graph_inputs(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    app = create_test_app(_settings(tmp_path), event_provider=FakeEventProvider())
    run_store = app.state.pipeline_run_store
    original_list = run_store.list_for_recording

    def stale_inputs(recording_id: str, **kwargs):
        stored_runs = original_list(recording_id, **kwargs)
        return tuple(
            replace(run, request=replace(run.request, input_revision_ids=("stale-input",)))
            for run in stored_runs
        )

    with TestClient(app) as client:
        created = _enqueue_event_job(client, RECORDING_ID, _request("graph-input-check"))
        assert created.status_code == 202
        _wait_for_status(client, created.json()["id"], "complete")
        run_store.list_for_recording = stale_inputs

        workspace = app.state.pipeline_workspace_service.get_workspace(RECORDING_ID)

    event_run = workspace["stages"][0]["runs"][0]
    assert event_run["input_revision_ids"] == []
    assert event_run["output_revision_ids"] == [
        workspace["stages"][0]["selected_generated"]["revision_id"]
    ]


def test_compatible_observation_inputs_return_exact_node_references(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    app = create_test_app(_settings(tmp_path), event_provider=FakeEventProvider())
    node_store = app.state.pipeline_lineage_writer.node_store
    source = app.state.event_pipeline_service.get_recording_source(RECORDING_ID).to_mapping()
    fixtures = (
        ("event-node", "event-r1", "events", {"schema_version": "event-data/v1", "events": []}),
        (
            "visible-node",
            "visible-r1",
            "visible_cards",
            {"schema_version": "visible-card-data/v2", "outcomes": []},
        ),
        (
            "identity-node",
            "identity-r1",
            "visual_identities",
            {"schema_version": "visual-identity-data/v2", "outcomes": []},
        ),
    )
    for node_id, revision_id, content_type, content in fixtures:
        node_store.create(
            node_id,
            node_id,
            content_type,
            source,
            content,
            {},
            revision_id=revision_id,
        )

    stage = app.state.pipeline_workspace_service.get_workspace(
        RECORDING_ID, stage_key="table_observations"
    )["stages"][3]

    assert stage["compatible_input_sets"] == [
        {
            "input_node_refs": [
                {
                    "node_id": "event-node",
                    "revision_id": "event-r1",
                    "revision_policy": "historical",
                },
                {
                    "node_id": "visible-node",
                    "revision_id": "visible-r1",
                    "revision_policy": "historical",
                },
                {
                    "node_id": "identity-node",
                    "revision_id": "identity-r1",
                    "revision_policy": "historical",
                },
            ],
            "display_label": "Processor output events + Processor output visible cards + "
            "Processor output visual identities",
        }
    ]


def test_runtime_workspace_does_not_load_legacy_reference_store(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    app = create_test_app(_settings(tmp_path), event_provider=FakeEventProvider())
    assert not hasattr(app.state, "pipeline_reference_store")

    workspace = app.state.pipeline_workspace_service.get_workspace(RECORDING_ID, stage_key="events")

    assert workspace["schema_version"] == "pipeline-workspace/v1"
    assert "reference" not in workspace["stages"][0]
    assert "can_review" not in workspace["stages"][0]
    app.state.pipeline_workspace_service.get_statuses([RECORDING_ID], analyses_by_recording={})


def test_recording_pipeline_workspace_reports_invalid_selection_pointer(
    tmp_path: Path,
) -> None:
    _install_recording(tmp_path)
    app = create_test_app(_settings(tmp_path), event_provider=FakeEventProvider())

    with TestClient(app) as client:
        created = _enqueue_event_job(client, RECORDING_ID, _request("invalid-selection-run"))
        assert created.status_code == 202
        _wait_for_status(client, created.json()["id"], "complete")

        selection_path = app.state.pipeline_selection_store.selection_path(RECORDING_ID, "events")
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        selection["selected_generated"]["revision_id"] = "missing-revision"
        selection_path.write_text(
            json.dumps(selection, separators=(",", ":")),
            encoding="utf-8",
        )

        response = client.get(f"/api/recordings/{RECORDING_ID}/pipeline")
        assert response.status_code == 200, response.text
        events = response.json()["stages"][0]
        assert events["selection_revision"] is None
        assert events["selected_generated"] is None
        assert not any(
            option["node_revision_id"] == "missing-revision" for option in events["input_options"]
        )
        assert {
            diagnostic["code"]
            for diagnostic in response.json()["diagnostics"]
            if diagnostic["content_type"] == "events"
        } == {"invalid_selection"}


def test_pipeline_workspace_does_not_read_evidence_package_media_or_manifests(
    tmp_path: Path, monkeypatch
) -> None:
    _install_recording(tmp_path)
    evidence_package_root = tmp_path / "evidence-packages"
    package_path = evidence_package_root / "package-fixture"
    package_path.mkdir(parents=True)
    (package_path / "manifest.json").write_text("{}", encoding="utf-8")
    (package_path / "frames").mkdir()
    (package_path / "frames" / "frame-0001.jpg").write_bytes(b"fixture")
    app = create_test_app(_settings(tmp_path), event_provider=FakeEventProvider())
    accesses: list[Path] = []
    original_open = Path.open

    def traced_open(path: Path, *args, **kwargs):
        accesses.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", traced_open)
    with TestClient(app) as client:
        response = client.get(f"/api/recordings/{RECORDING_ID}/pipeline")

    assert response.status_code == 200, response.text
    assert not any(
        evidence_package_root == path or evidence_package_root in path.parents for path in accesses
    )


def test_import_validates_bundle_prediction_and_preserves_absent_model_fields(
    tmp_path: Path,
) -> None:
    _install_recording(tmp_path)
    app = create_test_app(_settings(tmp_path))

    with TestClient(app) as client:
        imported = _enqueue_event_job(
            client, RECORDING_ID, {"run_id": "run-imported"}, import_predictions=True
        )
        assert imported.status_code == 202
        run_id = imported.json()["id"]
        _wait_for_status(client, run_id, "complete")
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{run_id}/result"
        ).json()
        revision = result["revisions"][0]
        assert result["state"]["status"] == "complete"
        assert result["state"]["progress"] == {"completed": 1, "total": 1}
        assert result["state"]["items"][0]["item_id"] == "import-proposal-both-0"
        assert "model" not in result["request"]
        assert "model_id" in revision["manifest"]["producer"]
        assert revision["content"]["events"][0]["event_type"] == CARD_STATE_CHANGED_EVENT_TYPE


def test_provider_failure_cannot_change_existing_generated_selection(tmp_path: Path) -> None:
    _install_recording(tmp_path)

    class FailingProvider:
        def infer(
            self,
            video_path: Path,
            *,
            request: object,
            progress_callback: object | None = None,
        ) -> object:
            del video_path, request, progress_callback
            raise RuntimeError("provider secret")

    app = create_test_app(_settings(tmp_path), event_provider=FailingProvider())
    with TestClient(app) as client:
        first = _enqueue_event_job(client, RECORDING_ID, _request("run-failed"))
        assert first.status_code == 202
        status = _wait_for_status(client, first.json()["id"], "failed")
        assert status["state"]["status"] == "failed"
        assert "provider secret" not in json.dumps(status)
        selection = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/events/selection").json()
        assert selection["selection"] is None


def test_event_job_cancel_does_not_publish_and_retry_creates_new_attempt(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    class CancelThenSucceedProvider:
        def infer(
            self,
            video_path: Path,
            *,
            request: object,
            progress_callback: object | None = None,
        ) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                assert release.wait(timeout=5)
            return {"events": [{"time_s": 0.5, "probability": 0.95}]}

    app = create_test_app(_settings(tmp_path), event_provider=CancelThenSucceedProvider())
    with TestClient(app) as client:
        accepted = _enqueue_event_job(client, RECORDING_ID, _request("run-cancel-retry"))
        assert accepted.status_code == 202
        assert started.wait(timeout=5)
        run_id = accepted.json()["id"]
        manager = app.state.job_manager_service.get_manager()
        job = manager.get(run_id)

        cancelled = client.post(f"/api/jobs/{job.id}/cancel", json={})
        assert cancelled.status_code == 200
        assert cancelled.json()["state"] == "cancelling"
        release.set()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job.id}").json()
            if current["state"] == "cancelled":
                break
            time.sleep(0.01)
        assert current["state"] == "cancelled"
        cancelled_run = app.state.pipeline_run_store.require(run_id)
        assert cancelled_run.state.status == "failed"
        assert cancelled_run.state.output_revision_ids == ()

        retried = client.post(
            f"/api/jobs/{job.id}/retry",
            headers={"Idempotency-Key": str(uuid4())},
            json={},
        )
        assert retried.status_code == 202
        retry_run_id = retried.json()["id"]
        assert retry_run_id != run_id
        completed = _wait_for_status(client, retry_run_id, "complete")
        assert completed["state"]["output_revision_ids"]
        assert calls == 2


def test_event_import_freezes_artifact_bytes_before_dispatch(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    started = threading.Event()
    release = threading.Event()

    class BlockingProvider:
        def infer(
            self,
            video_path: Path,
            *,
            request: object,
            progress_callback: object | None = None,
        ) -> dict[str, object]:
            started.set()
            assert release.wait(timeout=5)
            return {"events": [{"time_s": 0.5, "probability": 0.95}]}

    app = create_test_app(_settings(tmp_path), event_provider=BlockingProvider())
    artifact_path = tmp_path / "recordings" / RECORDING_ID / "predictions" / "proposal-both.json"
    original = artifact_path.read_bytes()
    with TestClient(app) as client:
        inference = _enqueue_event_job(client, RECORDING_ID, _request("run-blocking-before-import"))
        assert inference.status_code == 202
        assert started.wait(timeout=5)

        imported = _enqueue_event_job(
            client, RECORDING_ID, {"run_id": "run-frozen-import"}, import_predictions=True
        )
        assert imported.status_code == 202
        import_run_id = imported.json()["id"]
        manager = app.state.job_manager_service.get_manager()
        import_job = next(
            candidate
            for candidate in manager.list_jobs()
            if candidate.type == "event_import" and candidate.id == import_run_id
        )
        expected_digest = hashlib.sha256(original).hexdigest()
        assert import_job.inputs[-1]["digest"] == expected_digest

        artifact_path.write_bytes(b"changed after acceptance")
        release.set()
        assert (
            _wait_for_status(client, inference.json()["id"], "complete")["state"]["status"]
            == "complete"
        )
        imported_status = _wait_for_status(client, import_run_id, "complete")
        assert imported_status["state"]["status"] == "complete"
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{import_run_id}/result"
        ).json()
        assert result["revisions"][0]["manifest"]["producer"]["artifact_sha256"] == (
            expected_digest
        )


def test_restart_marks_running_event_run_failed(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    settings = _settings(tmp_path)

    app = create_test_app(settings, event_provider=FakeEventProvider())
    service = app.state.event_pipeline_service
    from dokodetector_backend.job_store import JobManager

    manager = JobManager(
        settings.operations_root,
        app.state.job_type_registry,
        verify_publication=app.state.job_type_registry.verify_publication,
    ).__enter__()
    job = manager.accept(
        "e161cde7-7fc9-5e9a-aa68-8f9ee0b0e912",
        {
            "type": "event_processing",
            "context": {"recording_id": RECORDING_ID},
            "request": _request("run-interrupted"),
        },
    )
    manager.transition(job.id, "running")
    service.run_store.start(service.event_run_id_for_job(job.id))
    manager.__exit__(None, None, None)

    restarted = create_test_app(settings, event_provider=FakeEventProvider())
    with TestClient(restarted):
        run = restarted.state.pipeline_run_store.require(job.id)
        assert run.state.status == "failed"
        assert run.state.terminal_failure is not None
        assert run.state.terminal_failure.code == "backend_restarted"
