from __future__ import annotations

import multiprocessing
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

from fastapi.testclient import TestClient
from support.job_participants import FakeParticipant

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.job_store import JobManager

RECORDING = "recording-both"
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"


def _create_app(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        repository_root=Path(__file__).parents[2],
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "operations",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "packages",
        pending_video_root=tmp_path / "incoming",
        frontend_dist=tmp_path / "frontend",
    )
    bundle_path = settings.repository_intake_root / RECORDING
    if not bundle_path.exists():
        shutil.copytree(FIXTURE_ROOT, bundle_path)
    app = create_app(settings)
    app.state.job_manager_service.cpu_budget = 1
    app.state.job_type_registry.register_fake(FakeParticipant(settings.operations_root / "domain"))
    return app


def _enqueue(client: TestClient, recording_id: str = RECORDING) -> dict:
    response = client.post(
        "/api/jobs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "type": "fake",
            "context": {"recording_id": recording_id},
            "request": {"input": "projection"},
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def _transition_job_in_process(operations_root: str, job_id: str, target: str) -> None:
    root = Path(operations_root)
    with JobManager(root, FakeParticipant(root / "domain")) as manager:
        manager.transition(job_id, target)


def test_recording_job_pages_rebuild_on_transition_and_survive_restart(tmp_path: Path) -> None:
    app = _create_app(tmp_path)
    with TestClient(app) as client:
        app.state.job_manager_service.scheduler.__exit__(None, None, None)
        app.state.job_manager_service.scheduler = None
        created = [_enqueue(client) for _ in range(21)]
        _enqueue(client, "another-recording")
        first = client.get(f"/api/recordings/{RECORDING}/state/jobs")
        assert first.status_code == 200, first.text
        first_page = first.json()
        assert first_page["active_job_count"] == 21
        assert len(first_page["jobs"]) == 20
        assert first_page["has_more"] is True
        assert all(item["status"] == "queued" for item in first_page["jobs"])

        second = client.get(
            f"/api/recordings/{RECORDING}/state/jobs",
            params={"cursor": first_page["next_cursor"]},
        )
        assert second.status_code == 200, second.text
        assert second.json()["active_job_count"] == 1
        assert len(second.json()["jobs"]) == 1
        assert {item["job_id"] for item in first_page["jobs"] + second.json()["jobs"]} == {
            item["id"] for item in created
        }

        cursor = first_page["next_cursor"]

    process = multiprocessing.get_context("spawn").Process(
        target=_transition_job_in_process,
        args=(str(tmp_path / "operations"), created[0]["id"], "running"),
    )
    process.start()
    process.join(10)
    assert process.exitcode == 0

    app = _create_app(tmp_path)
    with TestClient(app) as client:
        app.state.job_manager_service.scheduler.__exit__(None, None, None)
        app.state.job_manager_service.scheduler = None
        expired = client.get(f"/api/recordings/{RECORDING}/state/jobs", params={"cursor": cursor})
        assert expired.status_code == 410
        refreshed = client.get(f"/api/recordings/{RECORDING}/state/jobs").json()
        assert refreshed["active_job_count"] == 20
        assert all(item["job_id"] != created[0]["id"] for item in refreshed["jobs"])

    restarted = _create_app(tmp_path)
    with TestClient(restarted) as client:
        restarted.state.job_manager_service.scheduler.__exit__(None, None, None)
        restarted.state.job_manager_service.scheduler = None
        after_restart = client.get(f"/api/recordings/{RECORDING}/state/jobs")
        assert after_restart.status_code == 200, after_restart.text
        assert after_restart.json()["active_job_count"] == len(after_restart.json()["jobs"])
        assert all(
            item["status"] in {"queued", "running", "cancelling"}
            for item in after_restart.json()["jobs"]
        )
        assert all(item["job_id"] != created[0]["id"] for item in after_restart.json()["jobs"])


def test_projection_reader_waits_for_writer_and_returns_current_authority(tmp_path: Path) -> None:
    prepared = Event()
    release = Event()
    pause_transition = False

    def after_write(point: str) -> None:
        if pause_transition and point == "job_transition_prepared":
            prepared.set()
            assert release.wait(5)

    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant, after_write=after_write) as manager:
        job = manager.accept(
            str(uuid4()),
            {"type": "fake", "context": {"recording_id": RECORDING}, "request": {"input": "x"}},
        )
        assert manager.recording_job_projection(RECORDING).jobs[0].status == "queued"
        pause_transition = True
        with ThreadPoolExecutor(max_workers=2) as pool:
            writing = pool.submit(manager.transition, job.id, "running")
            assert prepared.wait(5)
            reading = pool.submit(manager.recording_job_projection, RECORDING)
            assert not reading.done()
            release.set()
            assert writing.result(timeout=5).state == "running"
            projection = reading.result(timeout=5)
        assert projection.authority_sequence == manager.projection_authority().sequence
        assert projection.jobs[0].status == "running"
