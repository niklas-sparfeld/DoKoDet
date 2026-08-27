"""Exercise the local iOS-to-backend-to-detector pipeline over real HTTP."""

from __future__ import annotations

import json
import os
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
FIXTURES_ROOT = REPOSITORY_ROOT / "fixtures" / "evidence" / "v1"
COMPLETE_PACKAGE_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


class LocalBackend:
    """Start the actual local API with temporary SQLite and filesystem state."""

    def __init__(self, tmp_path: Path) -> None:
        self.database_url = f"sqlite:///{tmp_path / 'evidence.sqlite'}"
        self.evidence_root = tmp_path / "runtime"
        self.port = _unused_port()
        self.environment = {
            **os.environ,
            "DATABASE_URL": self.database_url,
            "EVIDENCE_ROOT": os.fspath(self.evidence_root),
            "SERVER_HOST": "127.0.0.1",
            "SERVER_PORT": str(self.port),
            "BONJOUR_ENABLED": "false",
            "VISION_DETECTOR_NAME": "scripted",
            "VISION_DETECTOR_VERSION": "scripted-v1",
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


def test_ios_client_reaches_scripted_detector_over_local_http(
    local_backend: LocalBackend,
    tmp_path: Path,
) -> None:
    """Prove all M4 package, queue, retry, restart, and result paths."""

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

    detector = subprocess.run(
        [sys.executable, "-m", "dokodetector_backend.run_vision", "--once", "--all"],
        cwd=BACKEND_ROOT,
        env=local_backend.environment,
        check=True,
        capture_output=True,
        text=True,
    )
    detector_results = json.loads(detector.stdout)
    result_by_package = {result["package_id"]: result for result in detector_results}
    assert result_by_package[str(COMPLETE_PACKAGE_ID)]["status"] == "uncertain"
    assert (
        result_by_package["550e8400-e29b-41d4-a716-446655440001"]["status"]
        == "insufficient_evidence"
    )
    assert (
        result_by_package["550e8400-e29b-41d4-a716-446655440002"]["status"]
        == "insufficient_evidence"
    )

    result = run_ios(
        "result",
        "--server",
        local_backend.base_url,
        "--package-id",
        COMPLETE_PACKAGE_ID,
    )
    assert result["package_id"] == str(COMPLETE_PACKAGE_ID)
    assert result["results"][0]["status"] == "uncertain"
    assert result["results"][0]["candidate_count"] == 2
    assert result["direct_result_status"] == "uncertain"


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
