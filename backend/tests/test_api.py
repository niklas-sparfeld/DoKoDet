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
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "evidence" / "v2"


def load_upload_fixture(
    name: str, *, package_id: str | None = None
) -> tuple[bytes, dict[str, bytes], dict[str, object], bytes | None]:
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
    video_source = None
    if payload.get("video_snippet") is not None:
        video_source = (FIXTURE_ROOT / name / "snippet.mp4").read_bytes()
    return manifest_bytes, frame_sources, payload, video_source


def multipart_parts(
    manifest_bytes: bytes,
    frame_sources: dict[str, bytes],
    video_source: bytes | None = None,
) -> dict[str, tuple]:
    parts = {"manifest": ("untrusted-name.json", manifest_bytes, "application/json")}
    parts.update(
        {
            part_name: ("untrusted-name.jpg", frame_bytes, "image/jpeg")
            for part_name, frame_bytes in frame_sources.items()
        }
    )
    if video_source is not None:
        payload = json.loads(manifest_bytes)
        part_name = payload["video_snippet"]["part_name"]
        parts[part_name] = ("untrusted-name.mp4", video_source, "video/mp4")
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
        manifest_bytes, frame_sources, payload, video_source = load_upload_fixture(fixture_name)
        response = client.put(
            f"/v1/evidence-packages/{payload['package_id']}",
            files=multipart_parts(manifest_bytes, frame_sources, video_source),
        )
        assert response.status_code == 201
        assert response.json()["created"] is True
        assert repository.get_package(payload["package_id"]) is not None

    manifest_bytes, _, payload, _ = load_upload_fixture(
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


def test_get_returns_stored_package_metadata(backend) -> None:
    client, _, storage = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-complete")
    package_id = payload["package_id"]

    upload = client.put(
        f"/v1/evidence-packages/{package_id}",
        files=multipart_parts(manifest_bytes, frame_sources, video_source),
    )
    response = client.get(f"/v1/evidence-packages/{package_id}")

    assert upload.status_code == 201
    assert response.status_code == 200
    body = response.json()
    assert body["package_id"] == package_id
    assert body["state"] == "stored"
    assert body["schema_version"] == "cardevent-evidence/v2"
    assert body["session"] == payload["session"]
    assert body["event"] == payload["event"]
    assert body["manifest"]["video_snippet"] == payload["video_snippet"]
    assert body["video_snippet"] == payload["video_snippet"]
    assert body["video_relative_path"] == (f"evidence/{package_id}/video/snippet_00.mp4")
    assert body["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert body["manifest"] == payload
    assert body["missing_frame_targets_ms"] == []
    assert [frame["part_name"] for frame in body["frames"]] == [
        frame["part_name"] for frame in payload["frames"]
    ]
    assert body["frames"][0]["byte_length"] == len(frame_sources["frame_00"])
    assert body["frames"][0]["sha256"] == hashlib.sha256(frame_sources["frame_00"]).hexdigest()
    assert body["frames"][0]["relative_path"] == (f"evidence/{package_id}/frames/frame_00.jpg")
    assert (storage.root / body["frames"][0]["relative_path"]).is_file()
    video_path = storage.root / "evidence" / package_id / "video" / "snippet_00.mp4"
    assert video_source is not None
    assert video_path.read_bytes() == video_source

    video_response = client.get(f"/v1/evidence-packages/{package_id}/video-snippet")
    assert video_response.status_code == 200
    assert video_response.headers["content-type"] == "video/mp4"
    assert video_response.headers["content-length"] == str(len(video_source))
    assert video_response.headers["etag"] == f'"{payload["video_snippet"]["sha256"]}"'
    assert video_response.content == video_source


def test_get_unknown_package_returns_stable_not_found_error(backend) -> None:
    client, _, _ = backend

    response = client.get("/v1/evidence-packages/550e8400-e29b-41d4-a716-446655440099")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "package_not_found",
            "message": "The package was not found.",
            "details": [],
        }
    }


def test_identical_replay_returns_original_receipt_without_duplicate_files(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-incomplete")
    parts = multipart_parts(manifest_bytes, frame_sources, video_source)
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


def test_identical_complete_replay_is_idempotent_and_keeps_original_video(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-complete")
    path = f"/v1/evidence-packages/{payload['package_id']}"
    parts = multipart_parts(manifest_bytes, frame_sources, video_source)

    first = client.put(path, files=parts)
    second = client.put(path, files=parts)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert repository.get_package(payload["package_id"]) is not None
    assert video_source is not None
    assert storage.video_path(payload["package_id"], "snippet_00").read_bytes() == video_source
    assert list(storage.evidence_root.glob(".upload-*")) == []


def test_conflicting_package_id_returns_409_without_overwriting_files(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-incomplete")
    path = f"/v1/evidence-packages/{payload['package_id']}"
    first = client.put(path, files=multipart_parts(manifest_bytes, frame_sources, video_source))

    changed_payload = copy.deepcopy(payload)
    changed_payload["client"]["build"] = "different-build"
    changed_manifest = json.dumps(changed_payload, separators=(",", ":")).encode()
    second = client.put(path, files=multipart_parts(changed_manifest, frame_sources, video_source))

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
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-incomplete")
    first = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, frame_sources, video_source),
    )

    second_manifest, second_frames, second_payload, second_video = load_upload_fixture(
        "example-incomplete", package_id="550e8400-e29b-41d4-a716-446655440099"
    )
    second = client.put(
        f"/v1/evidence-packages/{second_payload['package_id']}",
        files=multipart_parts(second_manifest, second_frames, second_video),
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "logical_event_conflict"
    assert repository.get_package(second_payload["package_id"]) is None
    assert not storage.package_path(second_payload["package_id"]).exists()
    assert list(storage.evidence_root.glob(".upload-*")) == []


def test_package_size_limit_rejects_the_complete_package(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-complete")
    client.app.state.settings.max_package_bytes = len(manifest_bytes) + len(
        frame_sources["frame_00"]
    )

    response = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, frame_sources, video_source),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "package_too_large"
    assert repository.get_package(payload["package_id"]) is None
    assert not storage.package_path(payload["package_id"]).exists()
    assert list(storage.evidence_root.glob(".upload-*")) == []


def test_video_size_limit_rejects_the_complete_package(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-complete")
    assert video_source is not None
    client.app.state.settings.max_video_bytes = len(video_source) - 1

    response = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, frame_sources, video_source),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "video_too_large"
    assert repository.get_package(payload["package_id"]) is None
    assert not storage.package_path(payload["package_id"]).exists()
    assert list(storage.evidence_root.glob(".upload-*")) == []


def test_unsupported_video_part_media_type_is_rejected(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-complete")
    assert video_source is not None
    parts = multipart_parts(manifest_bytes, frame_sources, video_source)
    parts["snippet_00"] = ("untrusted-name.mov", video_source, "video/quicktime")

    response = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=parts,
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert repository.get_package(payload["package_id"]) is None
    assert not storage.package_path(payload["package_id"]).exists()


def test_video_hash_mismatch_is_rejected_before_probe(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-complete")
    assert video_source is not None
    wrong_video = b"wrong video bytes"

    response = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, frame_sources, wrong_video),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "hash_mismatch"
    assert repository.get_package(payload["package_id"]) is None
    assert not storage.package_path(payload["package_id"]).exists()


def test_truncated_video_is_rejected_after_hash_matches(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-complete")
    assert video_source is not None
    truncated_video = video_source[:-100]
    payload["video_snippet"]["byte_length"] = len(truncated_video)
    payload["video_snippet"]["sha256"] = hashlib.sha256(truncated_video).hexdigest()
    manifest_bytes = json.dumps(payload, separators=(",", ":")).encode()

    response = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, frame_sources, truncated_video),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_video"
    assert repository.get_package(payload["package_id"]) is None
    assert not storage.package_path(payload["package_id"]).exists()
    assert list(storage.evidence_root.glob(".upload-*")) == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("width", 641),
        ("height", 359),
        ("duration_ms", 2233),
        ("nominal_frame_rate", 10.0),
    ),
)
def test_video_probe_rejects_material_manifest_disagreements(backend, field, value) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-complete")
    assert video_source is not None
    snippet = payload["video_snippet"]
    snippet[field] = value
    if field == "duration_ms":
        snippet["end_offset_ms"] = snippet["start_offset_ms"] + value
    manifest_bytes = json.dumps(payload, separators=(",", ":")).encode()

    response = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, frame_sources, video_source),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_video"
    assert repository.get_package(payload["package_id"]) is None
    assert not storage.package_path(payload["package_id"]).exists()
    assert list(storage.evidence_root.glob(".upload-*")) == []


def test_video_files_are_removed_when_database_insert_conflicts(backend) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-complete")
    first = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, frame_sources, video_source),
    )

    second_manifest, second_frames, second_payload, second_video = load_upload_fixture(
        "example-complete", package_id="550e8400-e29b-41d4-a716-446655440099"
    )
    second = client.put(
        f"/v1/evidence-packages/{second_payload['package_id']}",
        files=multipart_parts(second_manifest, second_frames, second_video),
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "logical_event_conflict"
    assert repository.get_package(second_payload["package_id"]) is None
    assert not storage.package_path(second_payload["package_id"]).exists()
    assert list(storage.evidence_root.glob(".upload-*")) == []


def test_missing_video_read_returns_not_found_for_frame_only_package(backend) -> None:
    client, _, _ = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-incomplete")
    upload = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, frame_sources, video_source),
    )

    response = client.get(f"/v1/evidence-packages/{payload['package_id']}/video-snippet")

    assert upload.status_code == 201
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "video_snippet_not_found"


@pytest.mark.parametrize("rejection", ("missing", "extra", "oversized", "hash"))
def test_rejected_parts_are_not_stored(backend, rejection: str) -> None:
    client, repository, storage = backend
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-complete")
    parts = multipart_parts(manifest_bytes, frame_sources, video_source)
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
