from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dokodetector_backend.automated_pipeline_run import (
    AutomatedPipelineRunService,
    AutomatedPipelineRunStore,
)
from dokodetector_backend.errors import register_error_handlers
from dokodetector_backend.pipeline_run_api import router


def _app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    register_error_handlers(app)
    app.state.automated_pipeline_run_service = AutomatedPipelineRunService(
        store=AutomatedPipelineRunStore(tmp_path),
        recording_source_provider=lambda recording_id: SimpleNamespace(
            to_mapping=lambda: {
                "schema_version": "recording-video/v1",
                "recording_id": recording_id,
                "video_sha256": "a" * 64,
            }
        ),
        recording_provider_validator=lambda _recording_id, stage_requests: {
            "stage_requests": stage_requests,
            "providers": {"event_proposals": {"name": "fixture"}},
        },
        round_session_provider=lambda _recording_id: "session-1",
    )
    accepted: list[dict[str, object]] = []

    def accept(_key: str, request: dict[str, object]):
        accepted.append(request)
        return SimpleNamespace(id="managed-parent-job")

    app.state.accepted_jobs = accepted
    app.state.job_manager_service = SimpleNamespace(
        get_manager=lambda: SimpleNamespace(accept=accept)
    )
    return app


def _payload() -> dict[str, object]:
    return {
        "idempotency_key": str(uuid4()),
        "session_id": "session-1",
        "round_context": {
            "game_id": "game-1",
            "round_id": "round-1",
            "active_players": ["p1", "p2", "p3", "p4"],
            "dealer": "p1",
            "first_trick_leader": "p2",
        },
        "rules_version": "v1",
        "search": {
            "max_missing_plays": 1,
            "max_hypotheses": 16,
            "max_search_nodes": 1000,
        },
        "stage_requests": {
            name: {"configuration": {"stage": name}}
            for name in (
                "event_proposals",
                "visible_card_and_pile_proposals",
                "card_scene_and_calibration",
                "visual_identity_proposals",
                "table_observations",
            )
        },
    }


def test_start_and_status_routes_return_the_durable_run(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post("/api/recordings/recording-1/pipeline/runs", json=_payload())
        assert response.status_code == 202, response.text
        started = response.json()
        assert started["status"] == "accepted"

        status = client.get(f"/api/recordings/recording-1/pipeline/runs/{started['run_id']}")
        assert status.status_code == 200
        assert status.json() == started


def test_start_retry_returns_existing_run(tmp_path: Path) -> None:
    payload = _payload()
    with TestClient(_app(tmp_path)) as client:
        first = client.post("/api/recordings/recording-1/pipeline/runs", json=payload)
        retry = client.post("/api/recordings/recording-1/pipeline/runs", json=payload)

    assert first.status_code == 202
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert first.json()["job_id"] == "managed-parent-job"


def test_start_freezes_explicit_round_context_and_source_digest(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post("/api/recordings/recording-1/pipeline/runs", json=_payload())

    assert response.status_code == 202, response.text
    request = response.json()["request"]
    assert request["session_id"] == "session-1"
    assert request["round_id"] == "round-1"
    context = request["round_context"]
    assert context["game_id"] == "game-1"
    assert context["round_id"] == request["round_id"]
    assert context["active_players"] == ["p1", "p2", "p3", "p4"]
    assert context["dealer"] == "p1"
    assert context["first_trick_leader"] == "p2"
    assert response.json()["source"]["video_sha256"] == "a" * 64


def test_invalid_round_facts_create_no_run_or_parent_job(tmp_path: Path) -> None:
    payload = _payload()
    payload["round_context"] = {"game_id": "game-1"}
    with TestClient(_app(tmp_path)) as client:
        response = client.post("/api/recordings/recording-1/pipeline/runs", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "pipeline_preflight_failed"
        assert client.app.state.accepted_jobs == []
    assert list((tmp_path / "runs").glob("*.json")) == []
