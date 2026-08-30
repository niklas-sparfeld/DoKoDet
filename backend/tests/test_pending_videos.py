from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings

FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "evidence" / "v2" / "example-complete" / "snippet.mp4"
)


@pytest.fixture()
def pending_backend(tmp_path: Path) -> tuple[TestClient, Path]:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'repository.sqlite'}",
        evidence_root=tmp_path / "runtime",
        repository_intake_root=tmp_path / "data" / "intake" / "recordings",
        pending_video_root=tmp_path / "data" / "incoming" / "videos",
    )
    return TestClient(create_test_app(settings)), settings.pending_video_root


def _parts(video: bytes = FIXTURE.read_bytes(), filename: str = "pending.mov"):
    return {"video": (filename, video, "video/quicktime")}


def test_pending_upload_probes_and_persists_receipt(pending_backend) -> None:
    client, root = pending_backend
    video = FIXTURE.read_bytes()

    response = client.put("/v1/pending-videos/upload-001", files=_parts(video))

    assert response.status_code == 201
    assert response.json()["state"] == "pending"
    assert response.json()["sha256"] == hashlib.sha256(video).hexdigest()
    pending = root / "upload-001"
    receipt = json.loads((pending / "manifest.json").read_text())
    assert receipt["original_filename"] == "pending.mov"
    assert receipt["byte_length"] == len(video)
    assert receipt["media_facts"] == {
        "container": "mp4",
        "video_codec": "h264",
        "width": 640,
        "height": 360,
        "nominal_frame_rate": 15.0,
        "duration_ms": 2133,
        "frame_count": 32,
    }
    assert (pending / "pending.mov").read_bytes() == video
    assert list(root.glob(".upload-*")) == []

    read_back = client.get("/v1/pending-videos/upload-001")
    assert read_back.status_code == 200
    assert read_back.json() == response.json()


def test_identical_pending_retry_is_idempotent_and_conflict_preserves_bytes(
    pending_backend,
) -> None:
    client, root = pending_backend
    video = FIXTURE.read_bytes()
    path = "/v1/pending-videos/upload-002"

    first = client.put(path, files=_parts(video))
    second = client.put(path, files=_parts(video))
    conflict = client.put(path, files=_parts(video + b"junk"))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert conflict.status_code == 409
    assert (root / "upload-002" / "pending.mov").read_bytes() == video
    assert list(root.glob(".upload-*")) == []


@pytest.mark.parametrize("video", [FIXTURE.read_bytes()[:-100], b"not a video"])
def test_invalid_pending_upload_is_not_published(pending_backend, video: bytes) -> None:
    client, root = pending_backend

    response = client.put("/v1/pending-videos/upload-invalid", files=_parts(video))

    assert response.status_code == 422
    assert not (root / "upload-invalid").exists()
    assert list(root.glob(".upload-*")) == []


def test_pending_video_size_limit_is_checked_before_publication(pending_backend) -> None:
    client, root = pending_backend
    client.app.state.settings.max_pending_video_bytes = 10

    response = client.put("/v1/pending-videos/upload-large", files=_parts())

    assert response.status_code == 413
    assert not (root / "upload-large").exists()
    assert list(root.glob(".upload-*")) == []


def test_pending_receipt_survives_backend_restart(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'repository.sqlite'}",
        evidence_root=tmp_path / "runtime",
        repository_intake_root=tmp_path / "data" / "intake" / "recordings",
        pending_video_root=tmp_path / "data" / "incoming" / "videos",
    )
    video = FIXTURE.read_bytes()

    first = TestClient(create_test_app(settings))
    assert first.put("/v1/pending-videos/upload-restart", files=_parts(video)).status_code == 201

    second = TestClient(create_test_app(settings))
    response = second.get("/v1/pending-videos/upload-restart")

    assert response.status_code == 200
    assert response.json()["sha256"] == hashlib.sha256(video).hexdigest()
