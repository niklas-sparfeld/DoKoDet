import copy
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.repository import EvidenceRepository, upgrade_database
from dokodetector_backend.storage import EvidenceStorage

BACKEND_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "evidence" / "v1"


def load_upload_fixture(
    name: str, *, package_id: str | None = None
) -> tuple[bytes, dict[str, bytes], dict[str, object]]:
    payload = json.loads((FIXTURE_ROOT / name / "manifest.json").read_bytes())
    if package_id is not None:
        payload["package_id"] = package_id

    frame_sources: dict[str, bytes] = {}
    for frame in payload["frames"]:
        frame_bytes = f"jpeg bytes for {frame['part_name']}".encode()
        frame_sources[frame["part_name"]] = frame_bytes
        frame["byte_length"] = len(frame_bytes)
        frame["sha256"] = hashlib.sha256(frame_bytes).hexdigest()

    manifest_bytes = json.dumps(payload, separators=(",", ":")).encode()
    return manifest_bytes, frame_sources, payload


def multipart_parts(manifest_bytes: bytes, frame_sources: dict[str, bytes]) -> dict[str, tuple]:
    parts = {"manifest": ("untrusted-name.json", manifest_bytes, "application/json")}
    parts.update(
        {
            part_name: ("untrusted-name.jpg", frame_bytes, "image/jpeg")
            for part_name, frame_bytes in frame_sources.items()
        }
    )
    return parts


@pytest.fixture()
def backend(tmp_path) -> tuple[TestClient, EvidenceRepository, EvidenceStorage]:
    database_url = f"sqlite:///{tmp_path / 'evidence.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        evidence_root=tmp_path / "runtime",
    )
    app = create_app(settings)
    return TestClient(app), app.state.repository, app.state.storage


def test_upload_accepts_complete_incomplete_and_metadata_only_packages(backend) -> None:
    client, repository, _ = backend

    for fixture_name in ("example-complete", "example-incomplete"):
        manifest_bytes, frame_sources, payload = load_upload_fixture(fixture_name)
        response = client.put(
            f"/v1/evidence-packages/{payload['package_id']}",
            files=multipart_parts(manifest_bytes, frame_sources),
        )
        assert response.status_code == 201
        assert response.json()["created"] is True
        assert repository.get_package(payload["package_id"]) is not None

    manifest_bytes, _, payload = load_upload_fixture(
        "example-incomplete", package_id="550e8400-e29b-41d4-a716-446655440002"
    )
    payload["session"]["event_sequence"] = 3
    payload["frames"] = []
    payload["missing_frame_targets_ms"] = payload["evidence_capture"]["target_offsets_ms"]
    payload["event"]["evidence_complete"] = False
    manifest_bytes = json.dumps(payload, separators=(",", ":")).encode()
    response = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, {}),
    )

    assert response.status_code == 201
    assert response.json()["created"] is True
    assert repository.get_package(payload["package_id"]).frames == ()


def test_identical_replay_returns_original_receipt_without_duplicate_files(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload = load_upload_fixture("example-incomplete")
    parts = multipart_parts(manifest_bytes, frame_sources)
    path = f"/v1/evidence-packages/{payload['package_id']}"

    first = client.put(path, files=parts)
    second = client.put(path, files=parts)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["received_at"] == first.json()["received_at"]
    assert repository.get_package(payload["package_id"]) is not None
    assert storage.package_path(payload["package_id"]).is_dir()
    assert list(storage.evidence_root.glob(".upload-*")) == []


def test_conflicting_package_id_returns_409_without_overwriting_files(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload = load_upload_fixture("example-incomplete")
    path = f"/v1/evidence-packages/{payload['package_id']}"
    first = client.put(path, files=multipart_parts(manifest_bytes, frame_sources))

    changed_payload = copy.deepcopy(payload)
    changed_payload["client"]["build"] = "different-build"
    changed_manifest = json.dumps(changed_payload, separators=(",", ":")).encode()
    second = client.put(path, files=multipart_parts(changed_manifest, frame_sources))

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "package_conflict"
    assert (
        repository.get_package(UUID(payload["package_id"])).manifest_json == manifest_bytes.decode()
    )
    assert (
        storage.package_path(payload["package_id"]) / "manifest.json"
    ).read_bytes() == manifest_bytes


def test_conflicting_logical_event_returns_409_without_storing_second_package(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload = load_upload_fixture("example-incomplete")
    first = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, frame_sources),
    )

    second_manifest, second_frames, second_payload = load_upload_fixture(
        "example-incomplete", package_id="550e8400-e29b-41d4-a716-446655440099"
    )
    second = client.put(
        f"/v1/evidence-packages/{second_payload['package_id']}",
        files=multipart_parts(second_manifest, second_frames),
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "logical_event_conflict"
    assert repository.get_package(second_payload["package_id"]) is None
    assert not storage.package_path(second_payload["package_id"]).exists()
    assert list(storage.evidence_root.glob(".upload-*")) == []


def test_package_size_limit_rejects_the_complete_package(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload = load_upload_fixture("example-complete")
    client.app.state.settings.max_package_bytes = len(manifest_bytes) + len(
        frame_sources["frame_00"]
    )

    response = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, frame_sources),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "package_too_large"
    assert repository.get_package(payload["package_id"]) is None
    assert not storage.package_path(payload["package_id"]).exists()
    assert list(storage.evidence_root.glob(".upload-*")) == []


@pytest.mark.parametrize("rejection", ("missing", "extra", "oversized", "hash"))
def test_rejected_parts_are_not_stored(backend, rejection: str) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload = load_upload_fixture("example-complete")
    parts = multipart_parts(manifest_bytes, frame_sources)
    package_id = payload["package_id"]

    if rejection == "missing":
        del parts["frame_05"]
    elif rejection == "extra":
        parts["frame_extra"] = ("ignored.jpg", b"extra", "image/jpeg")
    elif rejection == "oversized":
        settings = client.app.state.settings
        settings.max_frame_bytes = 4
    elif rejection == "hash":
        parts["frame_00"] = ("ignored.jpg", b"wrong bytes", "image/jpeg")

    response = client.put(f"/v1/evidence-packages/{package_id}", files=parts)

    expected_status = (
        400 if rejection in {"missing", "extra"} else 413 if rejection == "oversized" else 422
    )
    expected_code = {
        "missing": "invalid_request",
        "extra": "invalid_request",
        "oversized": "frame_too_large",
        "hash": "hash_mismatch",
    }[rejection]
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert repository.get_package(package_id) is None
    assert not storage.package_path(package_id).exists()
    assert list(storage.evidence_root.glob(".upload-*")) == []
