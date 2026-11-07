from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from app_factory import create_test_app
from fastapi.testclient import TestClient
from support.job_participants import FakeParticipant

from dokodetector_backend.config import Settings
from dokodetector_backend.filesystem import atomic_replace_json

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def make_app(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        repository_root=REPOSITORY_ROOT,
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "operations",
        frontend_dist=tmp_path / "frontend",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "packages",
        pending_video_root=tmp_path / "pending",
    )
    app = create_test_app(settings)
    app.state.job_type_registry.register_fake(
        FakeParticipant(settings.operations_root / "job-domain")
    )
    return app


def enqueue(client: TestClient, value: str, key: str | None = None) -> dict:
    response = client.post(
        "/api/jobs",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={
            "type": "fake",
            "context": {"recording_id": "recording-1"},
            "request": {"input": value},
        },
    )
    assert response.status_code == 202, response.text
    assert response.headers["location"] == f"/api/jobs/{response.json()['id']}"
    return response.json()


def test_job_acceptance_is_idempotent_and_types_are_closed(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    key = str(uuid4())
    with TestClient(app) as client:
        accepted = enqueue(client, "one", key)
        replay = enqueue(client, "one", key)
        assert replay["id"] == accepted["id"]
        conflict = client.post(
            "/api/jobs",
            headers={"Idempotency-Key": key},
            json={
                "type": "fake",
                "context": {"recording_id": "recording-1"},
                "request": {"input": "different"},
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_conflict"

        unknown = client.post(
            "/api/jobs",
            headers={"Idempotency-Key": str(uuid4())},
            json={"type": "not-registered", "context": {}, "request": {}},
        )
        assert unknown.status_code == 422
        assert unknown.json()["error"]["code"] == "unknown_job_type"

        invalid = client.post(
            "/api/jobs",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "type": "fake",
                "context": {"recording_id": "recording-1", "path": "/tmp/no"},
                "request": {"input": "one"},
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "invalid_request"


def test_list_filters_cursor_binding_and_detail_capabilities(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app) as client:
        first = enqueue(client, "one")
        second = enqueue(client, "two")
        third = enqueue(client, "three")
        page = client.get("/api/jobs?scope=all&recording_id=recording-1&limit=2")
        assert page.status_code == 200
        payload = page.json()
        assert [item["id"] for item in payload["items"]] == [third["id"], second["id"]]
        assert payload["next_cursor"]
        assert len(payload["groups"]) == 3

        next_page = client.get(
            "/api/jobs",
            params={
                "scope": "all",
                "recording_id": "recording-1",
                "limit": 2,
                "cursor": payload["next_cursor"],
            },
        )
        assert [item["id"] for item in next_page.json()["items"]] == [first["id"]]
        mismatched = client.get(
            "/api/jobs",
            params={"scope": "all", "recording_id": "other", "cursor": payload["next_cursor"]},
        )
        assert mismatched.status_code == 422

        detail = client.get(f"/api/jobs/{first['id']}")
        assert detail.status_code == 200
        assert detail.json()["capabilities"]["cancel"]["allowed"] is True
        assert detail.json()["capabilities"]["retry"]["allowed"] is False
        filtered = client.get("/api/jobs?state=queued&type=fake&scope=active")
        assert all(item["state"] == "queued" for item in filtered.json()["items"])
        assert client.get("/api/jobs?state=not-a-state").status_code == 422

        missing = client.get(f"/api/jobs/{uuid4()}")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "job_not_found"


def test_cancel_retry_logs_and_unavailable_results(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app) as client:
        job = enqueue(client, "cancel-me")
        missing_body = client.post(f"/api/jobs/{job['id']}/cancel")
        assert missing_body.status_code == 422
        cancelled = client.post(f"/api/jobs/{job['id']}/cancel", json={})
        assert cancelled.status_code == 200
        assert cancelled.json()["state"] == "cancelled"
        assert cancelled.json()["capabilities"]["retry"]["allowed"] is True

        retry_key = str(uuid4())
        retried = client.post(
            f"/api/jobs/{job['id']}/retry",
            headers={"Idempotency-Key": retry_key},
            json={},
        )
        assert retried.status_code == 202
        assert retried.headers["location"] == f"/api/jobs/{retried.json()['id']}"
        assert retried.json()["retry_of"] == job["id"]
        retry_replay = client.post(
            f"/api/jobs/{job['id']}/retry",
            headers={"Idempotency-Key": retry_key},
            json={},
        )
        assert retry_replay.json()["id"] == retried.json()["id"]

        manager = app.state.job_manager_service.get_manager()
        manager.append_log(job["id"], "sample", "one")
        manager.append_log(job["id"], "sample", "two")
        logs = client.get(f"/api/jobs/{job['id']}/logs?limit=1")
        assert logs.status_code == 200
        assert logs.json()["entries"][0]["message"] == "Job accepted and queued."
        assert logs.json()["next_after"] == 1

        stored = manager.get(retried.json()["id"])
        stored.results = [{"kind": "fake_result", "id": "missing", "digest": "abc"}]
        manager._write_job(stored)
        result = client.get(f"/api/jobs/{stored.id}").json()["results"][0]
        assert result["available"] is False


def test_log_page_reports_truncated_history(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app) as client:
        job = enqueue(client, "logs")
        log_path = tmp_path / "operations" / "jobs" / job["id"] / "logs.json"
        atomic_replace_json(
            log_path,
            [
                {
                    "sequence": sequence,
                    "timestamp": "2026-11-05T12:00:00+00:00",
                    "level": "info",
                    "code": "sample",
                    "message": str(sequence),
                }
                for sequence in (8, 9)
            ],
        )
        page = client.get(f"/api/jobs/{job['id']}/logs?after=0&limit=1").json()
        assert page["truncated_before"] == 7
        assert page["entries"][0]["sequence"] == 8


def test_queue_move_conflict_returns_current_order(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app) as client:
        first, second = enqueue(client, "first"), enqueue(client, "second")
        initial = client.get("/api/jobs").json()
        revision = initial["queue_revision"]

        def move(group_id: str):
            return client.post(
                "/api/jobs/queue/move",
                json={"group_id": group_id, "before_group_id": None, "expected_revision": revision},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(move, (first["id"], second["id"])))
        assert sorted(response.status_code for response in responses) == [200, 409]
        conflict = next(response for response in responses if response.status_code == 409)
        assert conflict.json()["error"]["code"] == "queue_revision_conflict"
        details = {item["field"]: item["message"] for item in conflict.json()["error"]["details"]}
        assert int(details["revision"]) == revision + 1
        assert json.loads(details["groups"])
        current = client.get("/api/jobs").json()
        assert current["queue_revision"] == revision + 1
