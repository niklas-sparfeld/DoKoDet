from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from app_factory import create_test_app
from doko_operations.pipeline_data import CARD_STATE_CHANGED_EVENT_TYPE
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_api import router as pipeline_router
from dokodetector_backend.pipeline_comparison_api import router as comparison_router
from dokodetector_backend.pipeline_reference_api import router as reference_router
from dokodetector_backend.pipeline_stage_api import router as stage_router
from dokodetector_backend.pipeline_workspace_api import router as workspace_router

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"
RECORDING_ID = "recording-both"


def test_pipeline_route_inventory_stays_in_focused_modules() -> None:
    child_routers = (workspace_router, stage_router, comparison_router, reference_router)
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
        "dokodetector_backend.pipeline_workspace_api": 1,
        "dokodetector_backend.pipeline_stage_api": 36,
        "dokodetector_backend.pipeline_comparison_api": 1,
        "dokodetector_backend.pipeline_reference_api": 6,
    }
    assert len(pipeline_router.routes) == len(child_routers)


def test_pipeline_composition_reuses_shared_stores_across_services(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    with TestClient(app):
        revision_store = app.state.pipeline_revision_store
        run_store = app.state.pipeline_run_store
        selection_store = app.state.pipeline_selection_store

        services = (
            app.state.event_pipeline_service,
            app.state.visible_card_pipeline_service,
            app.state.proposed_card_scene_pipeline_service,
            app.state.visual_identity_pipeline_service,
            app.state.observation_pipeline_service,
        )
        assert all(service.revision_store is revision_store for service in services)
        assert all(service.run_store is run_store for service in services)
        assert all(service.selection_store is selection_store for service in services)
        assert app.state.pipeline_reference_service.revision_store is revision_store
        assert app.state.pipeline_reference_service.selection_store is selection_store
        assert app.state.pipeline_workspace_service.revision_store is revision_store
        assert app.state.pipeline_workspace_service.run_store is run_store
        assert app.state.pipeline_workspace_service.selection_store is selection_store
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
        response = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/events/{run_id}")
        body = response.json()
        if body["state"]["status"] == expected:
            return body
        time.sleep(0.01)
    return body


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
        created = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json=_request("run-progress"),
        )
        assert created.status_code == 202
        assert started.wait(timeout=5.0)

        deadline = time.monotonic() + 5
        progress = None
        while time.monotonic() < deadline:
            status = client.get(
                f"/api/recordings/{RECORDING_ID}/pipeline/events/run-progress"
            ).json()
            progress = status["state"]["progress"]
            if progress == {"completed": 3, "total": 10}:
                break
            time.sleep(0.01)
        assert progress == {"completed": 3, "total": 10}

        release.set()
        status = _wait_for_status(client, "run-progress", "complete")
        assert status["state"]["progress"] == {"completed": 1, "total": 1}


def test_generated_events_are_stored_and_selected_from_video_only(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    provider = FakeEventProvider()
    app = create_test_app(_settings(tmp_path), event_provider=provider)

    direct_body = app.state.pipeline_workspace_service.get_workspace(RECORDING_ID)
    assert direct_body["schema_version"] == "pipeline-workspace/v1"
    assert direct_body["video"]["recording_id"] == RECORDING_ID

    with TestClient(app) as client:
        created = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events", json=_request("run-generated")
        )
        assert created.status_code == 202

        status = _wait_for_status(client, "run-generated", "complete")
        result = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/events/run-generated/result")
        assert result.status_code == 200
        body = result.json()
        assert status["state"]["status"] == "complete"
        assert body["state"]["status"] == "complete"
        assert body["state"]["progress"] == {"completed": 1, "total": 1}
        assert body["state"]["items"][0]["item_id"] == "event-000000"
        assert body["state"]["items"][0]["result"]["event_type"] == (
            CARD_STATE_CHANGED_EVENT_TYPE
        )
        assert body["revisions"][0]["content"]["events"][0]["start_us"] == 500_000
        assert body["revisions"][0]["content"]["events"][0]["event_type"] == (
            CARD_STATE_CHANGED_EVENT_TYPE
        )
        assert body["revisions"][0]["manifest"]["producer"]["kind"] == "processor"
        selection = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/generated-selection"
        )
        assert (
            selection.json()["selection"]["selected_generated_revision_id"]
            == (body["state"]["output_revision_ids"][0])
        )
    assert len(provider.calls) == 1


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
        created = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events", json=_request("run-metrics")
        )
        assert created.status_code == 202
        status = _wait_for_status(client, "run-metrics", "complete")

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
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/run-metrics/result"
        )
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
        created = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json=_request("run-default-cardevent"),
        )

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
        created = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json=request,
        )

        assert created.status_code == 202
        assert created.json()["request"]["configuration"]["checkpoint_path"] == (
            "data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/"
            "runs/candidate-hard-negative-v1/best.pt"
        )
        assert created.json()["request"]["configuration"] == {
            "checkpoint_path": (
                "data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/"
                "runs/candidate-hard-negative-v1/best.pt"
            ),
            "threshold": 0.4271905720233917,
            "merge_window_s": 0.625,
        }
        assert (
            _wait_for_status(client, "run-0063-integration-cardevent", "complete")["state"][
                "status"
            ]
            == "complete"
        )
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

        created = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json=_request("workspace-run"),
        )
        assert created.status_code == 202
        _wait_for_status(client, "workspace-run", "complete")

        workspace = client.get(f"/api/recordings/{RECORDING_ID}/pipeline")
        assert workspace.status_code == 200
        body = workspace.json()
        events = body["stages"][0]
        revision_id = events["selected_generated_revision_id"]
        assert events["state"] == "generated-only"
        assert revision_id is not None
        assert events["selection_revision"] == 1
        assert events["comparable_run_ids"] == ["workspace-run"]
        assert events["runs"][0]["run_id"] == "workspace-run"
        assert events["runs"][0]["input_revision_ids"] == []
        assert events["runs"][0]["implementation"] == {
            "name": "fake-event-provider",
            "version": "v1",
        }
        assert events["runs"][0]["state"]["items"] == []
        assert events["runs"][0]["output_revision_ids"] == [revision_id]
        assert events["input_options"][0]["revision_id"] == revision_id
        assert events["input_options"][0]["origin"] == "processor"

        catalog = client.get("/v1/recordings")
        assert catalog.status_code == 200
        assert catalog.json()["recordings"][0]["pipeline_status"]["stages"] == [
            {"key": "events", "state": "generated-only"},
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
    original_get = selection_store.get
    calls: list[tuple[str, str]] = []

    def traced_get(recording_id: str, content_type: str, **kwargs):
        calls.append((recording_id, content_type))
        return original_get(recording_id, content_type, **kwargs)

    monkeypatch.setattr(selection_store, "get", traced_get)

    workspace = app.state.pipeline_workspace_service.get_workspace(RECORDING_ID)

    assert workspace["schema_version"] == "pipeline-workspace/v1"
    assert calls == [
        (RECORDING_ID, "events"),
        (RECORDING_ID, "visible_cards"),
        (RECORDING_ID, "visual_identities"),
        (RECORDING_ID, "table_observations"),
    ]


def test_recording_pipeline_workspace_reports_invalid_selection_pointer(
    tmp_path: Path,
) -> None:
    _install_recording(tmp_path)
    app = create_test_app(_settings(tmp_path), event_provider=FakeEventProvider())

    with TestClient(app) as client:
        created = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json=_request("invalid-selection-run"),
        )
        assert created.status_code == 202
        _wait_for_status(client, "invalid-selection-run", "complete")

        selection_path = app.state.pipeline_selection_store.selection_path(RECORDING_ID, "events")
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        selection["selected_generated_revision_id"] = "missing-revision"
        selection_path.write_text(
            json.dumps(selection, separators=(",", ":")),
            encoding="utf-8",
        )

        response = client.get(f"/api/recordings/{RECORDING_ID}/pipeline")
        assert response.status_code == 200, response.text
        events = response.json()["stages"][0]
        assert events["selection_revision"] is None
        assert events["selected_generated_revision_id"] is None
        assert not any(
            option["revision_id"] == "missing-revision" for option in events["input_options"]
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
        imported = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/import",
            json={"run_id": "run-imported"},
        )
        assert imported.status_code == 201
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/run-imported/result"
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
        first = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json=_request("run-failed"),
        )
        assert first.status_code == 202
        status = _wait_for_status(client, "run-failed", "failed")
        assert status["state"]["status"] == "failed"
        assert "provider secret" not in json.dumps(status)
        selection = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/events/selection").json()
        assert selection["selection"] is None


def test_restart_marks_running_event_run_failed(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    settings = _settings(tmp_path)

    app = create_test_app(settings, event_provider=FakeEventProvider())
    service = app.state.event_pipeline_service
    source = service.get_recording_source(RECORDING_ID)
    request = {
        **_request("run-interrupted"),
        "source": source.to_mapping(),
    }
    service.start_inference(RECORDING_ID, request)
    service._executor.shutdown(wait=False, cancel_futures=True)  # noqa: SLF001

    restarted = create_test_app(settings, event_provider=FakeEventProvider())
    run = restarted.state.pipeline_run_store.require("run-interrupted")
    assert run.state.status == "failed"
    assert run.state.terminal_failure is not None
    assert run.state.terminal_failure.code == "backend_restarted"
