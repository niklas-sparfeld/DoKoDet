import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from vision_detector import (
    ScriptedVisionDetector,
    VisionDetectionResult,
    VisionEvidence,
    canonical_json_bytes,
    parse_result_bytes,
)

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.persistence import VisionResultPersister
from dokodetector_backend.repository import (
    EvidenceRepository,
    RepositoryError,
    VisionResultConflict,
    upgrade_database,
)
from dokodetector_backend.run_vision import main
from dokodetector_backend.storage import EvidenceStorage
from dokodetector_backend.vision_adapter import EvidenceIntegrityError
from dokodetector_backend.vision_runner import VisionRunner, VisionRunnerError

BACKEND_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "evidence" / "v2"
PACKAGE_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


def load_upload_fixture(name: str) -> tuple[bytes, dict[str, bytes], dict[str, object]]:
    payload = json.loads((FIXTURE_ROOT / name / "manifest.json").read_bytes())
    frame_sources: dict[str, bytes] = {}
    for frame in payload["frames"]:
        frame_bytes = f"jpeg bytes for {frame['part_name']}".encode()
        frame_sources[frame["part_name"]] = frame_bytes
        frame["byte_length"] = len(frame_bytes)
        frame["sha256"] = hashlib.sha256(frame_bytes).hexdigest()
    return json.dumps(payload, separators=(",", ":")).encode(), frame_sources, payload


def multipart_parts(manifest_bytes: bytes, frame_sources: dict[str, bytes]) -> dict[str, tuple]:
    parts = {
        "manifest": ("manifest.json", manifest_bytes, "application/json"),
        **{
            part_name: (f"{part_name}.jpg", frame_bytes, "image/jpeg")
            for part_name, frame_bytes in frame_sources.items()
        },
    }
    payload = json.loads(manifest_bytes)
    if payload.get("video_snippet") is not None:
        video = (FIXTURE_ROOT / "example-complete" / "snippet.mp4").read_bytes()
        parts[payload["video_snippet"]["part_name"]] = ("snippet.mp4", video, "video/mp4")
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


def upload_fixture(
    client: TestClient, name: str
) -> tuple[dict[str, object], bytes, dict[str, bytes]]:
    manifest_bytes, frame_sources, payload = load_upload_fixture(name)
    response = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, frame_sources),
    )
    assert response.status_code == 201
    return payload, manifest_bytes, frame_sources


def test_runner_verifies_evidence_before_detector_invocation(backend) -> None:
    client, repository, storage = backend
    payload, manifest_bytes, frame_sources = upload_fixture(client, "example-complete")
    frame_path = storage.root / "evidence" / payload["package_id"] / "frames" / "frame_00.jpg"
    frame_path.write_bytes(b"corrupted evidence")
    called = False

    class Detector:
        name = "scripted"
        version = "scripted-v1"

        def detect(self, evidence: VisionEvidence) -> VisionDetectionResult:
            nonlocal called
            called = True
            return ScriptedVisionDetector().detect(evidence)

    runner = VisionRunner(repository, storage, Detector())

    with pytest.raises(EvidenceIntegrityError):
        runner.run_once(PACKAGE_ID)

    assert called is False
    assert repository.list_vision_results(PACKAGE_ID) == ()
    assert frame_path.read_bytes() == b"corrupted evidence"
    assert (
        manifest_bytes
        == (storage.root / "evidence" / payload["package_id"] / "manifest.json").read_bytes()
    )
    assert frame_sources["frame_00"] != frame_path.read_bytes()


def test_runner_persists_result_and_read_routes_hide_local_paths(backend) -> None:
    client, repository, storage = backend
    payload, _, _ = upload_fixture(client, "example-complete")
    runner = VisionRunner(repository, storage, ScriptedVisionDetector())

    stored = runner.run_once(payload["package_id"])

    assert stored is not None
    result_bytes = stored.result_json.encode()
    result_path = storage.root / stored.relative_path
    assert result_path.read_bytes() == result_bytes
    assert stored.result_sha256 == hashlib.sha256(result_bytes).hexdigest()
    assert stored.relative_path == f"vision-results/{stored.result_id}/result.json"

    package_response = client.get(f"/v1/evidence-packages/{payload['package_id']}/vision-results")
    result_response = client.get(f"/v1/vision-results/{stored.result_id}")

    assert package_response.status_code == 200
    assert result_response.status_code == 200
    assert package_response.json() == [result_response.json()]
    assert result_response.json()["package_id"] == payload["package_id"]
    assert "relative_path" not in result_response.json()


def test_complete_local_pipeline_proof(backend, monkeypatch, capsys) -> None:
    """Prove the shared fixture path from HTTP upload to game-facing result parsing."""

    client, repository, storage = backend
    payload, manifest_bytes, frame_sources = upload_fixture(client, "example-complete")

    package_response = client.get(f"/v1/evidence-packages/{payload['package_id']}")

    assert package_response.status_code == 200
    package_metadata = package_response.json()
    assert package_metadata["package_id"] == payload["package_id"]
    assert package_metadata["manifest"] == json.loads(manifest_bytes)
    assert package_metadata["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert [frame["part_name"] for frame in package_metadata["frames"]] == list(frame_sources)

    settings = client.app.state.settings
    for name, value in {
        "DATABASE_URL": settings.database_url,
        "EVIDENCE_ROOT": os.fspath(settings.evidence_root),
        "VISION_DETECTOR_NAME": "scripted",
        "VISION_DETECTOR_VERSION": "scripted-v1",
    }.items():
        monkeypatch.setenv(name, value)

    assert main(["--once", "--package-id", payload["package_id"]]) == 0
    command_result = json.loads(capsys.readouterr().out)

    stored = repository.get_vision_result(UUID(command_result["result_id"]))
    assert stored is not None
    stored_result = parse_result_bytes(stored.result_json.encode("utf-8"))
    assert stored_result.status == "uncertain"
    assert stored_result.package_id == PACKAGE_ID

    result_response = client.get(f"/v1/vision-results/{stored.result_id}")
    package_results_response = client.get(
        f"/v1/evidence-packages/{payload['package_id']}/vision-results"
    )

    assert result_response.status_code == 200
    assert package_results_response.status_code == 200
    api_result = parse_result_bytes(result_response.content)
    assert api_result == stored_result
    assert package_results_response.json() == [api_result.model_dump(mode="json")]
    assert (storage.root / stored.relative_path).read_bytes() == stored.result_json.encode("utf-8")


def test_runner_is_idempotent_and_keeps_a_second_detector_version(backend) -> None:
    client, repository, storage = backend
    payload, _, _ = upload_fixture(client, "example-complete")
    first_runner = VisionRunner(repository, storage, ScriptedVisionDetector())
    second_runner = VisionRunner(
        repository,
        storage,
        ScriptedVisionDetector(version="scripted-v2"),
    )

    first = first_runner.run_once(payload["package_id"])
    replay = first_runner.run_once(payload["package_id"])
    second_version = second_runner.run_once(payload["package_id"])

    assert first is not None
    assert replay == first
    assert second_version is not None
    assert second_version.result_id != first.result_id
    assert second_version.detector_version == "scripted-v2"
    assert {result.detector_version for result in repository.list_vision_results(PACKAGE_ID)} == {
        "scripted-v1",
        "scripted-v2",
    }
    assert len(list(storage.vision_results_root.glob(".result-*"))) == 0


def test_runner_can_process_all_pending_packages(backend) -> None:
    client, repository, storage = backend
    complete_payload, _, _ = upload_fixture(client, "example-complete")
    incomplete_payload, _, _ = upload_fixture(client, "example-incomplete")
    runner = VisionRunner(repository, storage, ScriptedVisionDetector())

    results = runner.run_all()

    assert [result.package_id for result in results] == [
        UUID(complete_payload["package_id"]),
        UUID(incomplete_payload["package_id"]),
    ]
    assert [result.status for result in results] == ["uncertain", "insufficient_evidence"]
    assert runner.run_all() == ()


def test_run_vision_command_processes_an_explicit_package(backend, monkeypatch, capsys) -> None:
    client, repository, storage = backend
    payload, _, _ = upload_fixture(client, "example-complete")
    settings = client.app.state.settings
    for name, value in {
        "DATABASE_URL": settings.database_url,
        "EVIDENCE_ROOT": os.fspath(settings.evidence_root),
        "VISION_DETECTOR_NAME": "scripted",
        "VISION_DETECTOR_VERSION": "scripted-v1",
    }.items():
        monkeypatch.setenv(name, value)

    assert main(["--once", "--package-id", payload["package_id"]]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["package_id"] == payload["package_id"]
    assert repository.get_vision_result(UUID(output["result_id"])) is not None
    assert storage.vision_results_root.exists()


def test_different_result_for_same_detector_key_is_a_conflict(backend) -> None:
    client, repository, storage = backend
    payload, _, _ = upload_fixture(client, "example-complete")
    runner = VisionRunner(repository, storage, ScriptedVisionDetector())
    stored = runner.run_once(payload["package_id"])
    assert stored is not None
    original_bytes = stored.result_json.encode()

    original = VisionDetectionResult.model_validate(json.loads(stored.result_json))
    conflicting = original.model_copy(
        update={"result_id": UUID("c648d0b8-f82f-4c50-9505-970907ea1f99")}
    )

    with pytest.raises(VisionResultConflict):
        VisionResultPersister(repository, storage).persist(
            conflicting,
            canonical_json_bytes(conflicting),
        )

    assert repository.get_vision_result(stored.result_id).result_json.encode() == original_bytes
    assert (storage.root / stored.relative_path).read_bytes() == original_bytes
    assert list(storage.vision_results_root.glob(".result-*")) == []


def test_detector_failure_does_not_create_result(backend) -> None:
    client, repository, storage = backend
    payload, _, _ = upload_fixture(client, "example-complete")

    class FailingDetector:
        name = "scripted"
        version = "scripted-v1"

        def detect(self, evidence: VisionEvidence) -> VisionDetectionResult:
            raise RuntimeError("detector failed")

    runner = VisionRunner(repository, storage, FailingDetector())

    with pytest.raises(VisionRunnerError):
        runner.run_once(payload["package_id"])

    assert repository.list_vision_results(PACKAGE_ID) == ()
    assert not storage.vision_results_root.exists()


def test_detector_failure_can_be_retried_successfully(backend) -> None:
    client, repository, storage = backend
    payload, _, _ = upload_fixture(client, "example-complete")
    attempts = 0
    scripted_detector = ScriptedVisionDetector()

    class FlakyDetector:
        name = "scripted"
        version = "scripted-v1"

        def detect(self, evidence: VisionEvidence) -> VisionDetectionResult:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient detector failure")
            return scripted_detector.detect(evidence)

    runner = VisionRunner(repository, storage, FlakyDetector())

    with pytest.raises(VisionRunnerError):
        runner.run_once(payload["package_id"])

    assert repository.list_vision_results(PACKAGE_ID) == ()
    assert not storage.vision_results_root.exists()

    recovered = runner.run_once(payload["package_id"])

    assert recovered is not None
    assert recovered.status == "uncertain"
    assert attempts == 2
    assert (storage.root / recovered.relative_path).is_file()


def test_database_failure_removes_staged_result_directory(backend, monkeypatch) -> None:
    client, repository, storage = backend
    payload, _, _ = upload_fixture(client, "example-complete")

    def fail(*args, **kwargs):
        raise RepositoryError("database failed")

    monkeypatch.setattr(repository, "insert_vision_result", fail)
    runner = VisionRunner(repository, storage, ScriptedVisionDetector())

    with pytest.raises(RepositoryError):
        runner.run_once(payload["package_id"])

    assert repository.list_vision_results(PACKAGE_ID) == ()
    assert storage.vision_results_root.exists()
    assert list(storage.vision_results_root.glob(".result-*")) == []
    assert list(storage.vision_results_root.iterdir()) == []


def test_package_result_route_returns_empty_list_before_processing(backend) -> None:
    client, _, _ = backend
    payload, _, _ = upload_fixture(client, "example-complete")

    response = client.get(f"/v1/evidence-packages/{payload['package_id']}/vision-results")

    assert response.status_code == 200
    assert response.json() == []


def test_unknown_vision_result_returns_stable_not_found_error(backend) -> None:
    client, _, _ = backend

    response = client.get("/v1/vision-results/550e8400-e29b-41d4-a716-446655440099")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "vision_result_not_found",
            "message": "The vision result was not found.",
            "details": [],
        }
    }
