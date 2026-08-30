from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.repository import upgrade_database
from dokodetector_backend.repository_bundle_repository import RepositoryBundleRepository

BACKEND_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"


def load_fixture() -> dict[str, bytes | dict[str, object]]:
    manifest_bytes = (FIXTURE_ROOT / "manifest.json").read_bytes()
    source_bytes = (FIXTURE_ROOT / "source-record.json").read_bytes()
    enrollment_bytes = (FIXTURE_ROOT / "initial-task-enrollment.json").read_bytes()
    proposal_path = next((FIXTURE_ROOT / "predictions").glob("*.json"))
    video_path = FIXTURE_ROOT / "videos" / "video-both.mov"
    return {
        "manifest": manifest_bytes,
        "source_record": source_bytes,
        "task_enrollment": enrollment_bytes,
        "proposal": proposal_path.read_bytes(),
        "proposal_name": proposal_path.name,
        "video": video_path.read_bytes(),
        "video_name": video_path.name,
        "manifest_object": json.loads(manifest_bytes),
    }


def bundle_parts(
    fixture: dict[str, bytes | dict[str, object]],
) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        ("manifest", ("manifest.json", fixture["manifest"], "application/json")),
        ("source_record", ("source-record.json", fixture["source_record"], "application/json")),
        (
            "task_enrollment",
            ("initial-task-enrollment.json", fixture["task_enrollment"], "application/json"),
        ),
        ("video", (fixture["video_name"], fixture["video"], "video/quicktime")),
        ("proposal", (fixture["proposal_name"], fixture["proposal"], "application/json")),
    ]


@pytest.fixture()
def backend(tmp_path: Path) -> tuple[TestClient, RepositoryBundleRepository, Path]:
    database_url = f"sqlite:///{tmp_path / 'repository.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    intake_root = tmp_path / "data" / "intake" / "recordings"
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        evidence_root=tmp_path / "runtime",
        repository_intake_root=intake_root,
    )
    app = create_test_app(settings)
    return TestClient(app), app.state.repository_bundle_repository, intake_root


def test_upload_stores_one_complete_commit_ready_bundle(backend) -> None:
    client, repository, intake_root = backend
    fixture = load_fixture()
    recording_id = fixture["manifest_object"]["recording_id"]

    response = client.put(
        f"/v1/repository-bundles/{recording_id}",
        files=bundle_parts(fixture),
    )

    assert response.status_code == 201
    assert response.json()["created"] is True
    bundle_path = intake_root / recording_id
    assert {
        path.relative_to(bundle_path).as_posix()
        for path in bundle_path.rglob("*")
        if path.is_file()
    } == {
        "manifest.json",
        "source-record.json",
        "initial-task-enrollment.json",
        "videos/video-both.mov",
        "predictions/proposal-both.json",
    }
    assert (bundle_path / "videos" / "video-both.mov").read_bytes() == fixture["video"]
    assert (bundle_path / "source-record.json").read_bytes() == fixture["source_record"]
    assert (bundle_path / "initial-task-enrollment.json").read_bytes() == fixture["task_enrollment"]
    assert repository.get(recording_id) is not None
    assert not (intake_root / "training-recordings").exists()
    assert list(intake_root.glob(".upload-*")) == []

    read_back = client.get(f"/v1/repository-bundles/{recording_id}")

    assert read_back.status_code == 200
    assert read_back.json()["source_asset_id"] == fixture["manifest_object"]["source_asset_id"]
    assert (
        read_back.json()["files"]["videos/video-both.mov"]["sha256"]
        == hashlib.sha256(fixture["video"]).hexdigest()
    )


def test_identical_retry_is_idempotent_and_conflicting_content_is_rejected(backend) -> None:
    client, repository, intake_root = backend
    fixture = load_fixture()
    manifest = copy.deepcopy(fixture["manifest_object"])
    recording_id = manifest["recording_id"]
    path = f"/v1/repository-bundles/{recording_id}"

    first = client.put(path, files=bundle_parts(fixture))
    accepted_before = (intake_root / recording_id / "source-record.json").read_bytes()
    second = client.put(path, files=bundle_parts(fixture))

    source = json.loads(fixture["source_record"])
    source["notes"] = "conflicting retry"
    source_bytes = json.dumps(source, separators=(",", ":")).encode()
    manifest["files"]["source_record"]["byte_length"] = len(source_bytes)
    manifest["files"]["source_record"]["sha256"] = hashlib.sha256(source_bytes).hexdigest()
    changed = dict(fixture)
    changed["source_record"] = source_bytes
    changed["manifest"] = json.dumps(manifest, separators=(",", ":")).encode()
    conflict = client.put(path, files=bundle_parts(changed))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "recording_conflict"
    assert (intake_root / recording_id / "source-record.json").read_bytes() == accepted_before
    assert repository.get(recording_id) is not None
    assert list(intake_root.glob(".upload-*")) == []


@pytest.mark.parametrize("variant", ["truncated", "invalid_hash", "missing_source"])
def test_interrupted_or_invalid_upload_leaves_no_final_bundle_or_row(backend, variant: str) -> None:
    client, repository, intake_root = backend
    fixture = load_fixture()
    recording_id = fixture["manifest_object"]["recording_id"]
    changed = dict(fixture)
    if variant == "truncated":
        changed["video"] = fixture["video"][:-1]
    elif variant == "invalid_hash":
        manifest = copy.deepcopy(fixture["manifest_object"])
        manifest["files"]["video"]["sha256"] = "0" * 64
        manifest["source_sha256"] = "0" * 64
        changed["manifest"] = json.dumps(manifest, separators=(",", ":")).encode()
    else:
        changed["source_record"] = b"{}"

    response = client.put(
        f"/v1/repository-bundles/{recording_id}",
        files=bundle_parts(changed),
    )

    assert response.status_code == 422
    assert repository.get(recording_id) is None
    assert not (intake_root / recording_id).exists()
    assert list(intake_root.glob(".upload-*")) == []


def test_bundle_and_part_limits_are_checked_before_publication(backend) -> None:
    client, repository, intake_root = backend
    fixture = load_fixture()
    recording_id = fixture["manifest_object"]["recording_id"]
    client.app.state.settings.max_recording_video_bytes = len(fixture["video"]) - 1

    response = client.put(
        f"/v1/repository-bundles/{recording_id}",
        files=bundle_parts(fixture),
    )

    assert response.status_code == 413
    assert repository.get(recording_id) is None
    assert not (intake_root / recording_id).exists()


def test_sqlite_index_failure_does_not_change_canonical_bundle(backend, monkeypatch) -> None:
    client, repository, intake_root = backend
    fixture = load_fixture()
    recording_id = fixture["manifest_object"]["recording_id"]

    def fail(*args, **kwargs):
        raise RuntimeError("simulated index failure")

    monkeypatch.setattr(repository, "insert", fail)
    response = client.put(
        f"/v1/repository-bundles/{recording_id}",
        files=bundle_parts(fixture),
    )

    assert response.status_code == 500
    assert (intake_root / recording_id / "manifest.json").read_bytes() == fixture["manifest"]
    assert repository.get(recording_id) is None


def test_restart_reads_the_same_index_and_canonical_bundle(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'repository.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    intake_root = tmp_path / "intake"
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        evidence_root=tmp_path / "runtime",
        repository_intake_root=intake_root,
    )
    fixture = load_fixture()
    recording_id = fixture["manifest_object"]["recording_id"]

    first = TestClient(create_test_app(settings))
    assert (
        first.put(f"/v1/repository-bundles/{recording_id}", files=bundle_parts(fixture)).status_code
        == 201
    )
    second = TestClient(create_test_app(settings))

    response = second.put(f"/v1/repository-bundles/{recording_id}", files=bundle_parts(fixture))

    assert response.status_code == 200
    assert response.json()["created"] is False
