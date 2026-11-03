from __future__ import annotations

from pathlib import Path

from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        repository_root=tmp_path,
        evidence_root=tmp_path / "runtime",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
        pending_video_root=tmp_path / "pending-videos",
    )


def test_review_api_creates_independent_reviews_and_retries_by_key(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    path = "/api/recordings/recording-01/pipeline/visible-card-reviews"
    payload = {
        "operator_id": "operator-01",
        "seed": "empty",
        "idempotency_key": "request-01",
    }

    with TestClient(app) as client:
        first_response = client.post(path, json=payload)
        retry_response = client.post(path, json=payload)
        second_response = client.post(path, json={**payload, "idempotency_key": "request-02"})
        changed_retry = client.post(path, json={**payload, "seed": "selected_generated"})

        assert first_response.status_code == 201
        assert retry_response.status_code == 201
        assert second_response.status_code == 201
        assert changed_retry.status_code == 409
        first = first_response.json()
        retry = retry_response.json()
        second = second_response.json()
        assert first["review_id"] == retry["review_id"]
        assert first["review_id"] != second["review_id"]
        assert first["draft"]["items"] == []
        assert client.get(path + "/" + first["review_id"]).json()["review_id"] == first["review_id"]
        assert len(client.get(path).json()["reviews"]) == 2
        stale = client.put(
            path + "/" + first["review_id"] + "/draft",
            json={
                "operator_id": "operator-01",
                "command_id": "stale-edit",
                "expected_revision": 1,
                "operations": [{"operation": "set_frame_empty", "item_id": "frame-01"}],
            },
        )
        assert stale.status_code == 409
        assert client.get(path + "/" + first["review_id"]).json()["draft"]["revision"] == 0

    restarted = create_test_app(_settings(tmp_path))
    with TestClient(restarted) as client:
        assert len(client.get(path).json()["reviews"]) == 2
