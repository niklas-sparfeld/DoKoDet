"""Exercise the local iOS-to-backend-to-detector pipeline over real HTTP."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from dokodetector_backend.repository import upgrade_database

REPOSITORY_ROOT = Path(__file__).parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
IOS_ROOT = REPOSITORY_ROOT / "ios"
OPERATIONS_ROOT = REPOSITORY_ROOT / "operations"
FIXTURES_ROOT = REPOSITORY_ROOT / "fixtures" / "evidence" / "v2"
COMPLETE_PACKAGE_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


class LocalBackend:
    """Start the actual local API with temporary SQLite and filesystem state."""

    def __init__(self, tmp_path: Path) -> None:
        self.database_url = f"sqlite:///{tmp_path / 'evidence.sqlite'}"
        self.evidence_root = tmp_path / "runtime"
        self.port = _unused_port()
        self.environment = {
            **os.environ,
            "REPOSITORY_ROOT": os.fspath(tmp_path),
            "DATABASE_URL": self.database_url,
            "EVIDENCE_ROOT": os.fspath(self.evidence_root),
            "REPOSITORY_INTAKE_ROOT": os.fspath(tmp_path / "repository-intake" / "recordings"),
            "EVIDENCE_PACKAGE_INTAKE_ROOT": os.fspath(
                tmp_path / "repository-intake" / "evidence-packages"
            ),
            "SERVER_HOST": "127.0.0.1",
            "SERVER_PORT": str(self.port),
            "BONJOUR_ENABLED": "false",
        }
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "dokodetector_backend.app:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=BACKEND_ROOT,
            env=self.environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("The local backend exited before it became ready.")
            try:
                response = httpx.get(f"{self.base_url}/health/ready", timeout=0.5)
            except httpx.HTTPError:
                time.sleep(0.05)
                continue
            if response.status_code == 200:
                return
            time.sleep(0.05)
        raise RuntimeError("The local backend did not become ready.")

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


@pytest.fixture()
def local_backend(tmp_path: Path) -> LocalBackend:
    backend = LocalBackend(tmp_path)
    upgrade_database(BACKEND_ROOT, backend.database_url)
    backend.start()
    try:
        yield backend
    finally:
        backend.stop()


def test_ios_client_reaches_backend_over_local_http(
    local_backend: LocalBackend,
    tmp_path: Path,
) -> None:
    """Prove all M4 package, queue, retry, and restart paths."""

    initial_root = tmp_path / "initial-queue"
    created = run_ios(
        "create",
        "--root",
        initial_root,
        "--fixtures-root",
        FIXTURES_ROOT,
        "--variant",
        "complete,incomplete,metadata",
    )
    assert created["diagnostics"]["queued"] == 3

    uploaded = run_ios("upload", "--root", initial_root, "--server", local_backend.base_url)
    assert [attempt["disposition"] for attempt in uploaded["attempts"]] == [
        "acknowledged",
        "acknowledged",
        "acknowledged",
    ]
    assert uploaded["diagnostics"]["acknowledged"] == 3

    with httpx.Client(base_url=local_backend.base_url, timeout=5) as client:
        complete_metadata = client.get(f"/v1/evidence-packages/{COMPLETE_PACKAGE_ID}").json()
        incomplete_metadata = client.get(
            "/v1/evidence-packages/550e8400-e29b-41d4-a716-446655440001"
        ).json()
        metadata_only = client.get(
            "/v1/evidence-packages/550e8400-e29b-41d4-a716-446655440002"
        ).json()
    assert len(complete_metadata["frames"]) == 6
    assert len(incomplete_metadata["frames"]) == 2
    assert len(metadata_only["frames"]) == 0
    assert len(metadata_only["missing_frame_targets_ms"]) == 6

    replay_root = tmp_path / "identical-replay"
    run_ios(
        "create",
        "--root",
        replay_root,
        "--fixtures-root",
        FIXTURES_ROOT,
        "--variant",
        "duplicate",
    )
    replay = run_ios("upload", "--root", replay_root, "--server", local_backend.base_url)
    assert replay["attempts"] == [
        {
            "created": False,
            "disposition": "acknowledged",
            "package_id": "550e8400-e29b-41d4-a716-446655440001",
            "state": "stored",
        }
    ]

    conflict_root = tmp_path / "conflict"
    run_ios(
        "create",
        "--root",
        conflict_root,
        "--fixtures-root",
        FIXTURES_ROOT,
        "--variant",
        "conflict",
    )
    conflict = run_ios("upload", "--root", conflict_root, "--server", local_backend.base_url)
    assert conflict["attempts"] == [
        {
            "disposition": "permanentFailure",
            "failure_kind": "permanent",
            "package_id": "550e8400-e29b-41d4-a716-446655440000",
            "status_code": 409,
        }
    ]
    assert conflict["diagnostics"]["permanent_failures"] == 1

    retry_root = tmp_path / "retry"
    run_ios(
        "create",
        "--root",
        retry_root,
        "--fixtures-root",
        FIXTURES_ROOT,
        "--variant",
        "retry",
    )
    local_backend.stop()
    failed = run_ios("upload", "--root", retry_root, "--server", local_backend.base_url)
    assert failed["attempts"][0]["disposition"] == "retryableFailure"
    assert failed["diagnostics"]["retryable_failures"] == 1

    local_backend.start()
    recovered = run_ios("retry", "--root", retry_root, "--server", local_backend.base_url)
    assert recovered["attempts"][0]["disposition"] == "acknowledged"
    assert recovered["diagnostics"]["acknowledged"] == 1

    restart_root = tmp_path / "app-restart"
    run_ios(
        "create",
        "--root",
        restart_root,
        "--fixtures-root",
        FIXTURES_ROOT,
        "--variant",
        "restart",
    )
    restarted = run_ios("upload", "--root", restart_root, "--server", local_backend.base_url)
    assert restarted["attempts"][0]["disposition"] == "acknowledged"
    assert restarted["diagnostics"]["queued"] == 0


def test_saved_video_clean_room_reaches_commit_ready_independent_tasks(
    local_backend: LocalBackend,
    tmp_path: Path,
) -> None:
    """Exercise the complete local recording, intake, review, and publication workflow."""

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is required to generate the short local video fixture")

    source_video = tmp_path / "saved-input.mov"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x96:rate=10",
            "-t",
            "0.6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            os.fspath(source_video),
        ],
        check=True,
        cwd=REPOSITORY_ROOT,
    )

    client_root = tmp_path / "simulator-client"
    simulation = run_ios(
        "simulate-recording",
        "--input-video",
        source_video,
        "--root",
        client_root,
        "--recording-id",
        "recording-phase5-sim",
        "--session-id",
        "550e8400-e29b-41d4-a716-446655440010",
        "--video-id",
        "video-phase5-sim",
    )
    assert simulation["input_frame_count"] == simulation["prediction_sample_count"]
    assert simulation["event_proposal_count"] == 1
    assert simulation["evidence_package_count"] == 1
    assert simulation["recording_metrics"]["received_frame_count"] == 6
    assert abs(simulation["input_duration_s"] - simulation["recording_duration_s"]) <= 0.1 + 1e-6

    local_backend.stop()
    failed = run_ios(
        "upload-recording",
        "--root",
        client_root / "training",
        "--server",
        local_backend.base_url,
    )
    assert failed["attempts"][0]["disposition"] == "retryableFailure"
    assert failed["diagnostics"]["retryable_failures"] == 1

    local_backend.start()
    uploaded = run_ios(
        "retry-recording",
        "--root",
        client_root / "training",
        "--server",
        local_backend.base_url,
    )
    assert uploaded["attempts"][0]["disposition"] == "acknowledged", uploaded
    assert uploaded["diagnostics"]["acknowledged"] == 1

    evidence_uploaded = run_ios(
        "upload",
        "--root",
        client_root / "evidence",
        "--server",
        local_backend.base_url,
    )
    assert evidence_uploaded["attempts"][0]["disposition"] == "acknowledged"

    recording_id = "recording-phase5-sim"
    session_id = "550e8400-e29b-41d4-a716-446655440010"
    with httpx.Client(base_url=local_backend.base_url, timeout=5) as client:
        recording_response = client.get(f"/v1/repository-bundles/{recording_id}")
    assert recording_response.status_code == 200
    recording_metadata = recording_response.json()
    assert recording_metadata["session_id"] == session_id
    assert recording_metadata["source_sha256"] == simulation["recording_video_sha256"]
    assert (
        recording_metadata["files"]["videos/video-phase5-sim.mov"]["sha256"]
        == simulation["recording_video_sha256"]
    )
    proposal_path = next(
        path for path in recording_metadata["files"] if path.startswith("predictions/")
    )
    assert (
        recording_metadata["files"][proposal_path]["sha256"]
        == simulation["recording_predictions_sha256"]
    )

    backend_recording = Path(local_backend.environment["REPOSITORY_INTAKE_ROOT"]) / recording_id
    backend_manifest_path = backend_recording / "manifest.json"
    backend_manifest = json.loads(backend_manifest_path.read_text(encoding="utf-8"))
    backend_video = backend_recording / backend_manifest["files"]["video"]["relative_path"]
    backend_predictions = (
        backend_recording / backend_manifest["files"]["proposal_generator_runs"][0]["relative_path"]
    )
    assert (
        hashlib.sha256(backend_video.read_bytes()).hexdigest()
        == backend_manifest["files"]["video"]["sha256"]
    )
    assert (
        hashlib.sha256(backend_predictions.read_bytes()).hexdigest()
        == backend_manifest["files"]["proposal_generator_runs"][0]["sha256"]
    )
    assert backend_video.parent == backend_recording / "videos"
    assert backend_predictions.parent == backend_recording / "predictions"

    # Rebuild the searchable index from the accepted bundle after a database restart. The
    # canonical source remains in one repository-intake bundle throughout this exercise.
    local_backend.stop()
    for suffix in ("", "-wal", "-shm"):
        (tmp_path / f"evidence.sqlite{suffix}").unlink(missing_ok=True)
    upgrade_database(BACKEND_ROOT, local_backend.database_url)
    local_backend.start()
    with httpx.Client(base_url=local_backend.base_url, timeout=5) as client:
        rebuilt = client.get(f"/v1/repository-bundles/{recording_id}")
    assert rebuilt.status_code == 200
    assert rebuilt.json()["source_sha256"] == simulation["recording_video_sha256"]

    intake_root = Path(local_backend.environment["REPOSITORY_INTAKE_ROOT"])
    artifacts_root = tmp_path / "operations"
    first = run_doko(
        "data",
        "review",
        "--repository-root",
        REPOSITORY_ROOT,
        "--intake-root",
        intake_root,
        "--artifacts-root",
        artifacts_root,
        "--task",
        "all",
        "--reviewer",
        "m11-clean-room",
        "--format",
        "json",
    )
    assert first["state"] == "in_progress"
    assert first["next_action"] is not None
    assert "Review" in first["next_action"]
    first_state = _read_review_state(artifacts_root, first["run_id"])

    cardevent_items = next(
        task["items"]
        for task in first_state["tasks"]
        if task["task"] == "cardevent_event_detection"
    )
    table_items = next(
        task["items"] for task in first_state["tasks"] if task["task"] == "table_evidence_analysis"
    )
    assert cardevent_items and table_items
    source_digests = {
        json.loads((intake_root / recording_id / "source-record.json").read_text())["sha256"]
    }

    card_decisions = tmp_path / "cardevent-decisions.json"
    card_decisions.write_text(
        json.dumps(
            {item["item_id"]: {"outcome": "reviewed"} for item in cardevent_items},
            sort_keys=True,
        )
    )
    card_complete = run_doko(
        "data",
        "review",
        "--repository-root",
        REPOSITORY_ROOT,
        "--intake-root",
        intake_root,
        "--artifacts-root",
        artifacts_root,
        "--task",
        "all",
        "--reviewer",
        "m11-clean-room",
        "--decision-file",
        card_decisions,
        "--approve-split",
        "--format",
        "json",
    )
    assert card_complete["state"] == "in_progress"
    card_task = next(
        task for task in card_complete["tasks"] if task["task"] == "cardevent_event_detection"
    )
    table_task = next(
        task for task in card_complete["tasks"] if task["task"] == "table_evidence_analysis"
    )
    assert card_task["state"] == "complete"
    assert card_task["published_outputs"]
    assert table_task["state"] != "complete"
    assert not table_task["published_outputs"]

    all_decisions = tmp_path / "all-decisions.json"
    all_decisions.write_text(
        json.dumps(
            {item["item_id"]: {"outcome": "reviewed"} for item in (*cardevent_items, *table_items)},
            sort_keys=True,
        )
    )
    completed = run_doko(
        "data",
        "review",
        "--repository-root",
        REPOSITORY_ROOT,
        "--intake-root",
        intake_root,
        "--artifacts-root",
        artifacts_root,
        "--task",
        "all",
        "--reviewer",
        "m11-clean-room",
        "--decision-file",
        all_decisions,
        "--approve-split",
        "--format",
        "json",
    )
    assert completed["state"] == "complete"
    assert {task["task"] for task in completed["tasks"]} == {
        "cardevent_event_detection",
        "table_evidence_analysis",
    }
    assert all(task["state"] == "complete" for task in completed["tasks"])
    assert completed["commit_ready_files"]
    assert all(
        (Path(path) if Path(path).is_absolute() else REPOSITORY_ROOT / path).is_file()
        for path in completed["commit_ready_files"]
    )

    validation = run_doko(
        "data",
        "validate",
        "--repository-root",
        REPOSITORY_ROOT,
        "--intake-root",
        intake_root,
        "--artifacts-root",
        artifacts_root,
        "--format",
        "json",
    )
    assert validation["valid"] is True
    published_root = artifacts_root / "published"
    assert {path.name for path in published_root.iterdir() if path.is_dir()} == {
        "cardevent_event_detection",
        "table_evidence_analysis",
    }
    assert not any(
        path.suffix.lower() in {".mov", ".mp4", ".m4v"}
        for path in published_root.rglob("*")
        if path.is_file()
    )
    for path in published_root.rglob("*.json"):
        payload = json.loads(path.read_text())
        assert set(_source_digests(payload)) <= source_digests, path
    completed_state = _read_review_state(artifacts_root, completed["run_id"])
    report = Path(completed_state["report_path"])
    if not report.is_absolute():
        report = REPOSITORY_ROOT / report
    assert report.is_file()


def run_doko(*arguments: object) -> dict[str, Any]:
    """Run the repository-operations CLI and decode its machine-readable result."""

    command = [
        "mise",
        "exec",
        "--",
        "uv",
        "run",
        "--offline",
        "--project",
        os.fspath(OPERATIONS_ROOT),
        "doko",
        *(
            os.fspath(argument) if isinstance(argument, os.PathLike) else str(argument)
            for argument in arguments
        ),
    ]
    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return json.loads(completed.stdout)


def _read_review_state(artifacts_root: Path, run_id: str) -> dict[str, Any]:
    return json.loads(
        (artifacts_root / "review-runs" / run_id / "state.json").read_text(encoding="utf-8")
    )


def _source_digests(value: object) -> list[str]:
    """Collect source digests from nested published JSON values."""

    if isinstance(value, dict):
        result: list[str] = []
        for key, nested in value.items():
            if key == "source_sha256" and isinstance(nested, str):
                result.append(nested)
            result.extend(_source_digests(nested))
        return result
    if isinstance(value, list):
        return [digest for nested in value for digest in _source_digests(nested)]
    return []


def run_ios(*arguments: object) -> dict[str, Any]:
    """Run the Swift replay client and decode its machine-readable result."""

    command = [
        "swift",
        "run",
        "--package-path",
        os.fspath(IOS_ROOT),
        "--configuration",
        "debug",
        "CardEventProbeLocalPipeline",
        *(
            os.fspath(argument) if isinstance(argument, os.PathLike) else str(argument)
            for argument in arguments
        ),
    ]
    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return json.loads(completed.stdout)


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.bind(("127.0.0.1", 0))
        return int(connection.getsockname()[1])
