import copy
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.recording_contract import (
    parse_device_predictions_bytes,
    parse_recording_manifest_bytes,
)
from dokodetector_backend.recording_derivation import (
    build_candidate_review_queue,
    build_dataset_record_yaml,
)
from dokodetector_backend.recording_repository import TrainingRecordingRepository
from dokodetector_backend.recording_storage import TrainingRecordingStorage
from dokodetector_backend.repository import upgrade_database

BACKEND_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = (
    Path(__file__).parents[2] / "fixtures" / "training-recording" / "v1" / "recording-fixture-001"
)


def load_fixture() -> tuple[bytes, bytes, bytes, dict[str, object]]:
    manifest_bytes = (FIXTURE_ROOT / "manifest.json").read_bytes()
    predictions_bytes = (FIXTURE_ROOT / "video-fixture-001.json").read_bytes()
    video_bytes = (FIXTURE_ROOT / "video-fixture-001.mov").read_bytes()
    return manifest_bytes, predictions_bytes, video_bytes, json.loads(manifest_bytes)


def recording_parts(
    manifest_bytes: bytes,
    predictions_bytes: bytes,
    video_bytes: bytes,
) -> dict[str, tuple[str, bytes, str]]:
    return {
        "manifest": ("untrusted-manifest.json", manifest_bytes, "application/json"),
        "video": ("untrusted-video.mov", video_bytes, "video/quicktime"),
        "predictions": ("untrusted-predictions.json", predictions_bytes, "application/json"),
    }


@pytest.fixture()
def backend(
    tmp_path: Path,
) -> tuple[TestClient, TrainingRecordingRepository, TrainingRecordingStorage]:
    database_url = f"sqlite:///{tmp_path / 'recordings.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        evidence_root=tmp_path / "runtime",
    )
    app = create_app(settings)
    return TestClient(app), app.state.training_repository, app.state.training_storage


def test_upload_stores_immutable_bundle_and_deterministic_derived_artifacts(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, predictions_bytes, video_bytes, manifest = load_fixture()

    response = client.put(
        f"/v1/training-recordings/{manifest['recording_id']}",
        files=recording_parts(manifest_bytes, predictions_bytes, video_bytes),
    )

    assert response.status_code == 201
    assert response.json()["created"] is True
    stored = repository.get(manifest["recording_id"])
    assert stored is not None
    recording_path = storage.recording_path(manifest["recording_id"])
    assert (recording_path / "manifest.json").read_bytes() == manifest_bytes
    assert (recording_path / "videos" / "video-fixture-001.mov").read_bytes() == video_bytes
    assert (
        recording_path / "predictions" / "video-fixture-001.json"
    ).read_bytes() == predictions_bytes
    assert (recording_path / "intake" / "dataset-record.yaml").is_file()
    queue_path = recording_path / "intake" / "candidate-review-queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert queue["provenance"] == "candidate_only"
    assert [item["category"] for item in queue["items"]] == ["unmatched_model_candidate"]
    assert stored.candidate_queue is not None

    read_back = client.get(f"/v1/training-recordings/{manifest['recording_id']}")

    assert read_back.status_code == 200
    body = read_back.json()
    assert body["recording_id"] == manifest["recording_id"]
    assert body["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert body["video"]["sha256"] == manifest["video"]["sha256"]
    assert body["predictions"]["sha256"] == manifest["predictions"]["sha256"]
    assert body["derived_artifacts"]["state"] == "ready"
    assert body["derived_artifacts"]["candidate_review_queue"]["state"] == "ready"
    assert body["evidence_package_count"] == 0


def test_derived_artifacts_regenerate_byte_for_byte() -> None:
    manifest_bytes, predictions_bytes, _, _ = load_fixture()
    manifest = parse_recording_manifest_bytes(manifest_bytes)
    predictions = parse_device_predictions_bytes(predictions_bytes)
    predictions_sha256 = hashlib.sha256(predictions_bytes).hexdigest()

    assert build_dataset_record_yaml(manifest) == build_dataset_record_yaml(manifest)
    assert build_candidate_review_queue(
        manifest,
        predictions,
        predictions_sha256=predictions_sha256,
    ) == build_candidate_review_queue(
        manifest,
        predictions,
        predictions_sha256=predictions_sha256,
    )


def test_identical_retry_is_idempotent_and_conflicting_content_is_rejected(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, predictions_bytes, video_bytes, manifest = load_fixture()
    path = f"/v1/training-recordings/{manifest['recording_id']}"
    parts = recording_parts(manifest_bytes, predictions_bytes, video_bytes)

    first = client.put(path, files=parts)
    second = client.put(path, files=parts)

    changed_manifest = copy.deepcopy(manifest)
    changed_manifest["client"]["build"] = "different-build"
    conflict = client.put(
        path,
        files=recording_parts(
            json.dumps(changed_manifest, separators=(",", ":")).encode(),
            predictions_bytes,
            video_bytes,
        ),
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "recording_conflict"
    assert repository.get(manifest["recording_id"]) is not None
    assert list(storage.training_recordings_root.glob(".upload-*")) == []


@pytest.mark.parametrize("variant", ["truncated", "invalid_hash"])
def test_invalid_bundle_is_not_committed(backend, variant: str) -> None:
    client, repository, storage = backend
    manifest_bytes, predictions_bytes, video_bytes, manifest = load_fixture()
    if variant == "truncated":
        video_bytes = video_bytes[:-1]
    else:
        changed_manifest = copy.deepcopy(manifest)
        changed_manifest["video"]["sha256"] = "0" * 64
        manifest_bytes = json.dumps(changed_manifest, separators=(",", ":")).encode()

    response = client.put(
        f"/v1/training-recordings/{manifest['recording_id']}",
        files=recording_parts(manifest_bytes, predictions_bytes, video_bytes),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "recording_hash_mismatch"
    assert repository.get(manifest["recording_id"]) is None
    assert not storage.recording_path(manifest["recording_id"]).exists()
    assert list(storage.training_recordings_root.glob(".upload-*")) == []


def test_video_and_total_limits_are_reported_before_commit(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, predictions_bytes, video_bytes, manifest = load_fixture()
    client.app.state.settings.max_recording_video_bytes = len(video_bytes) - 1

    response = client.put(
        f"/v1/training-recordings/{manifest['recording_id']}",
        files=recording_parts(manifest_bytes, predictions_bytes, video_bytes),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "recording_video_too_large"
    assert repository.get(manifest["recording_id"]) is None
    assert not storage.recording_path(manifest["recording_id"]).exists()


def test_derived_failure_rolls_back_committed_bundle(backend, monkeypatch) -> None:
    client, repository, storage = backend
    manifest_bytes, predictions_bytes, video_bytes, manifest = load_fixture()

    def fail(*args, **kwargs):
        raise OSError("simulated derived write failure")

    monkeypatch.setattr(storage, "write_derived", fail)
    response = client.put(
        f"/v1/training-recordings/{manifest['recording_id']}",
        files=recording_parts(manifest_bytes, predictions_bytes, video_bytes),
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert repository.get(manifest["recording_id"]) is None
    assert not storage.recording_path(manifest["recording_id"]).exists()


def test_unknown_recording_returns_stable_not_found_error(backend) -> None:
    client, _, _ = backend

    response = client.get("/v1/training-recordings/recording-unknown")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "recording_not_found",
            "message": "The training recording was not found.",
            "details": [],
        }
    }
