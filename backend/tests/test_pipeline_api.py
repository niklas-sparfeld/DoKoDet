from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"
RECORDING_ID = "recording-both"


class FakeEventProvider:
    def __init__(self, events: list[dict[str, object]] | None = None) -> None:
        self.events = events or [{"time_s": 0.5, "probability": 0.95}]
        self.calls: list[Path] = []

    def infer(self, video_path: Path, *, request: object) -> dict[str, object]:
        del request
        self.calls.append(video_path)
        return {"events": self.events}


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


def test_generated_events_are_stored_and_selected_from_video_only(tmp_path: Path) -> None:
    _install_recording(tmp_path)
    provider = FakeEventProvider()
    app = create_test_app(_settings(tmp_path), event_provider=provider)

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
        assert body["revisions"][0]["content"]["events"][0]["start_us"] == 500_000
        assert body["revisions"][0]["manifest"]["producer"]["kind"] == "processor"
        selection = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/generated-selection"
        )
        assert (
            selection.json()["selection"]["selected_generated_revision_id"]
            == (body["state"]["output_revision_ids"][0])
        )
    assert len(provider.calls) == 1


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
        assert "model" not in result["request"]
        assert "model_id" in revision["manifest"]["producer"]
        assert revision["content"]["events"][0]["event_type"] == "card_played"


def test_provider_failure_cannot_change_existing_generated_selection(tmp_path: Path) -> None:
    _install_recording(tmp_path)

    class FailingProvider:
        def infer(self, video_path: Path, *, request: object) -> object:
            del video_path, request
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
    source = service._accepted_source(RECORDING_ID)[1]  # noqa: SLF001
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
