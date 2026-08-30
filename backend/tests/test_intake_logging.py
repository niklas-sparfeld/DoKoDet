from __future__ import annotations

import logging
from pathlib import Path

from app_factory import create_test_app
from fastapi.testclient import TestClient
from test_api import load_upload_fixture, multipart_parts
from test_training_recordings import bundle_parts, load_fixture

from dokodetector_backend.config import Settings
from dokodetector_backend.errors import ContractError

PENDING_VIDEO = (
    Path(__file__).parents[2] / "fixtures" / "evidence" / "v2" / "example-complete" / "snippet.mp4"
).read_bytes()


def _records(caplog, event_name: str) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records if getattr(record, "event_name", None) == event_name
    ]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'backend.sqlite'}",
        evidence_root=tmp_path / "runtime",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
        pending_video_root=tmp_path / "pending-videos",
    )


def test_evidence_package_storage_event_is_structured_and_safe(caplog, tmp_path: Path) -> None:
    caplog.set_level(logging.DEBUG, logger="dokodetector_backend")
    settings = _settings(tmp_path)
    client = TestClient(create_test_app(settings))
    manifest, frames, payload, video = load_upload_fixture("example-incomplete")

    response = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest, frames, video),
        headers={
            "X-DokoDetector-Request-ID": "request-m1-evidence",
            "X-DokoDetector-Upload-ID": "upload-m1-evidence",
            "Authorization": "Bearer do-not-log-this-secret",
        },
    )

    assert response.status_code == 201
    stored = _records(caplog, "evidence_package_stored")
    assert len(stored) == 1
    assert stored[0].levelno == logging.INFO
    assert stored[0].event_fields == {
        "created": True,
        "frame_count": 2,
        "package_id": payload["package_id"],
        "request_id": "request-m1-evidence",
        "upload_id": "upload-m1-evidence",
        "video_snippet_complete": False,
    }
    assert "do-not-log-this-secret" not in caplog.text
    assert not _records(caplog, "evidence_upload_started")
    assert not _records(caplog, "evidence_upload_manifest_validated")


def test_repository_bundle_storage_event_includes_request_id(caplog, tmp_path: Path) -> None:
    caplog.set_level(logging.INFO, logger="dokodetector_backend")
    settings = _settings(tmp_path)
    client = TestClient(create_test_app(settings))
    fixture = load_fixture()
    recording_id = fixture["manifest_object"]["recording_id"]

    response = client.put(
        f"/v1/repository-bundles/{recording_id}",
        files=bundle_parts(fixture),
        headers={
            "X-DokoDetector-Request-ID": "request-m1-recording",
            "X-DokoDetector-Upload-ID": "upload-m1-recording",
        },
    )

    assert response.status_code == 201
    stored = _records(caplog, "repository_bundle_stored")
    assert len(stored) == 1
    assert stored[0].levelno == logging.INFO
    assert stored[0].event_fields == {
        "created": True,
        "proposal_count": 1,
        "recording_id": recording_id,
        "request_id": "request-m1-recording",
        "upload_id": "upload-m1-recording",
    }


def test_pending_video_storage_event_includes_path_upload_id(caplog, tmp_path: Path) -> None:
    caplog.set_level(logging.INFO, logger="dokodetector_backend")
    settings = _settings(tmp_path)
    client = TestClient(create_test_app(settings))

    response = client.put(
        "/v1/pending-videos/upload-m1-pending",
        files={"video": ("pending.mov", PENDING_VIDEO, "video/quicktime")},
        headers={"X-DokoDetector-Request-ID": "request-m1-pending"},
    )

    assert response.status_code == 201
    stored = _records(caplog, "pending_video_stored")
    assert len(stored) == 1
    assert stored[0].levelno == logging.INFO
    assert stored[0].event_fields == {
        "byte_length": len(PENDING_VIDEO),
        "created": True,
        "media_type": "video/quicktime",
        "request_id": "request-m1-pending",
        "sha256": response.json()["sha256"],
        "state": "pending",
        "upload_id": "upload-m1-pending",
    }


def test_readiness_and_rejection_events_use_request_ids_and_safe_fields(
    caplog, tmp_path: Path
) -> None:
    caplog.set_level(logging.INFO, logger="dokodetector_backend")
    settings = _settings(tmp_path)
    client = TestClient(create_test_app(settings))

    ready = client.get(
        "/health/ready",
        headers={"X-DokoDetector-Request-ID": "request-m1-ready"},
    )
    rejected = client.get(
        "/v1/evidence-packages/not-a-uuid",
        headers={
            "X-DokoDetector-Request-ID": "request-m1-rejected",
            "Authorization": "Bearer do-not-log-this-secret",
        },
    )

    assert ready.status_code == 200
    readiness = _records(caplog, "backend_ready")
    assert len(readiness) == 1
    assert readiness[0].levelno == logging.INFO
    assert readiness[0].event_fields == {"request_id": "request-m1-ready"}

    assert rejected.status_code == 422
    rejections = _records(caplog, "http_request_rejected")
    assert len(rejections) == 1
    assert rejections[0].levelno == logging.WARNING
    assert rejections[0].event_fields["request_id"] == "request-m1-rejected"
    assert rejections[0].event_fields["code"] == "invalid_package_id"
    assert rejections[0].event_fields["status_code"] == 422
    assert "do-not-log-this-secret" not in caplog.text


def test_backend_http_failure_is_error_with_the_operation_traceback(caplog, tmp_path: Path) -> None:
    caplog.set_level(logging.ERROR, logger="dokodetector_backend")
    app = create_test_app(_settings(tmp_path))

    @app.get("/test-backend-failure")
    def backend_failure() -> None:
        try:
            raise RuntimeError("storage operation failed")
        except RuntimeError as error:
            raise ContractError(
                "internal_error",
                "The backend operation failed.",
                status_code=500,
            ) from error

    response = TestClient(app).get("/test-backend-failure")

    assert response.status_code == 500
    failed = _records(caplog, "http_request_failed")
    assert len(failed) == 1
    assert failed[0].levelno == logging.ERROR
    assert failed[0].event_fields["code"] == "internal_error"
    assert failed[0].exc_info is not None


def test_identical_intake_retries_emit_one_storage_event_per_request(
    caplog, tmp_path: Path
) -> None:
    caplog.set_level(logging.INFO, logger="dokodetector_backend")
    settings = _settings(tmp_path)
    client = TestClient(create_test_app(settings))
    manifest, frames, payload, video = load_upload_fixture("example-incomplete")
    files = multipart_parts(manifest, frames, video)

    first = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=files,
        headers={"X-DokoDetector-Request-ID": "request-m1-first"},
    )
    second = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=files,
        headers={"X-DokoDetector-Request-ID": "request-m1-second"},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    stored = _records(caplog, "evidence_package_stored")
    assert [record.event_fields["created"] for record in stored] == [True, False]
    assert [record.event_fields["request_id"] for record in stored] == [
        "request-m1-first",
        "request-m1-second",
    ]
