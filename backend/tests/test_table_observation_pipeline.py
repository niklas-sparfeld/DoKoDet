import hashlib
import json
import sys
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from vision_detector import (
    AnalyzerEvidence,
    TableObservation,
    canonical_json_bytes,
    parse_observation_bytes,
)

from dokodetector_backend.analyzer_adapter import EvidenceIntegrityError
from dokodetector_backend.analyzer_runner import AnalyzerRunner, AnalyzerRunnerError
from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.persistence import TableObservationPersister
from dokodetector_backend.repository import (
    EvidenceRepository,
    RepositoryError,
    TableObservationConflict,
    upgrade_database,
)
from dokodetector_backend.storage import EvidenceStorage

BACKEND_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "evidence" / "v2"
OBSERVATION_FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "game-engine" / "v1" / "observations" / "minimal.json"
)
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


def upload_fixture(client: TestClient, name: str) -> tuple[dict[str, object], bytes]:
    manifest_bytes, frame_sources, payload = load_upload_fixture(name)
    response = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=multipart_parts(manifest_bytes, frame_sources),
    )
    assert response.status_code == 201
    return payload, manifest_bytes


class FixtureAnalyzer:
    name = "fixture"
    version = "fixture-v1"

    def __init__(self, fixture: bytes | None = None) -> None:
        self.fixture = fixture or OBSERVATION_FIXTURE.read_bytes()

    def analyze(self, evidence: AnalyzerEvidence) -> TableObservation:
        observation = parse_observation_bytes(self.fixture)
        payload = observation.model_dump(mode="python", exclude_none=True)
        payload["observation_id"] = f"{evidence.package_id}-observation"
        payload["analyzer"] = {"name": self.name, "version": self.version}
        return TableObservation.model_validate(payload)


def test_runner_verifies_evidence_before_analyzer_invocation(backend) -> None:
    client, repository, storage = backend
    payload, _ = upload_fixture(client, "example-complete")
    frame_path = storage.root / "evidence" / payload["package_id"] / "frames" / "frame_00.jpg"
    frame_path.write_bytes(b"corrupted evidence")
    called = False

    class Analyzer:
        name = "fixture"
        version = "fixture-v1"

        def analyze(self, evidence: AnalyzerEvidence) -> TableObservation:
            nonlocal called
            called = True
            return FixtureAnalyzer().analyze(evidence)

    with pytest.raises(EvidenceIntegrityError):
        AnalyzerRunner(repository, storage, Analyzer()).run_once(PACKAGE_ID)

    assert called is False
    assert repository.list_table_observations(PACKAGE_ID) == ()


def test_observation_crosses_analyzer_backend_reconstruction_boundary(backend) -> None:
    client, repository, storage = backend
    payload, _ = upload_fixture(client, "example-complete")
    stored = AnalyzerRunner(repository, storage, FixtureAnalyzer()).run_once(payload["package_id"])

    assert stored is not None
    persisted = parse_observation_bytes(stored.observation_json.encode())
    assert persisted.schema_version == "table-observation/v1"
    assert persisted.source.package_id == str(PACKAGE_ID)
    assert persisted.session.event_sequence == 1
    assert (storage.root / stored.relative_path).read_bytes() == stored.observation_json.encode()

    sys.path.insert(0, str(Path(__file__).parents[2] / "game_engine" / "src"))
    from game_engine.contract import canonical_json_bytes as reconstruction_json
    from game_engine.contract import parse_observation_bytes as parse_reconstruction_observation

    assert reconstruction_json(
        parse_reconstruction_observation(stored.observation_json.encode())
    ) == canonical_json_bytes(persisted)
    response = client.get(f"/v1/evidence-packages/{payload['package_id']}/table-observations")
    direct = client.get(f"/v1/table-observations/{stored.observation_id}")
    assert response.status_code == direct.status_code == 200
    assert response.json() == [direct.json()]


def test_runner_is_idempotent_and_processes_pending_packages(backend) -> None:
    client, repository, storage = backend
    first_payload, _ = upload_fixture(client, "example-complete")
    second_payload, _ = upload_fixture(client, "example-incomplete")
    runner = AnalyzerRunner(repository, storage, FixtureAnalyzer())

    first = runner.run_once(first_payload["package_id"])
    replay = runner.run_once(first_payload["package_id"])
    assert first is not None and replay == first
    assert runner.run_once(second_payload["package_id"]) is not None
    assert runner.run_all() == ()


def test_analyzer_failure_does_not_create_observation_and_can_retry(backend) -> None:
    client, repository, storage = backend
    payload, _ = upload_fixture(client, "example-complete")
    attempts = 0

    class FlakyAnalyzer:
        name = "fixture"
        version = "fixture-v1"

        def analyze(self, evidence: AnalyzerEvidence) -> TableObservation:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("analyzer failed")
            return FixtureAnalyzer().analyze(evidence)

    runner = AnalyzerRunner(repository, storage, FlakyAnalyzer())
    with pytest.raises(AnalyzerRunnerError):
        runner.run_once(payload["package_id"])
    assert repository.list_table_observations(PACKAGE_ID) == ()
    recovered = runner.run_once(payload["package_id"])
    assert recovered is not None
    assert attempts == 2


def test_observation_conflict_keeps_original_bytes(backend) -> None:
    client, repository, storage = backend
    payload, _ = upload_fixture(client, "example-complete")
    stored = AnalyzerRunner(repository, storage, FixtureAnalyzer()).run_once(payload["package_id"])
    assert stored is not None
    original_bytes = stored.observation_json.encode()
    changed = TableObservation.model_validate(
        json.loads(original_bytes) | {"observation_id": "observation-other"}
    )
    # Same package and analyzer identity must remain idempotent, even with a different ID.
    with pytest.raises(TableObservationConflict):
        TableObservationPersister(repository, storage).persist(
            changed, canonical_json_bytes(changed)
        )
    assert (
        repository.get_table_observation(stored.observation_id).observation_json.encode()
        == original_bytes
    )
    assert (storage.root / stored.relative_path).read_bytes() == original_bytes


def test_database_failure_removes_staged_observation_directory(backend, monkeypatch) -> None:
    client, repository, storage = backend
    payload, _ = upload_fixture(client, "example-complete")

    def fail(*args, **kwargs):
        raise RepositoryError("database failed")

    monkeypatch.setattr(repository, "insert_table_observation", fail)
    with pytest.raises(RepositoryError):
        AnalyzerRunner(repository, storage, FixtureAnalyzer()).run_once(payload["package_id"])

    assert repository.list_table_observations(PACKAGE_ID) == ()
    assert storage.table_observations_root.exists()
    assert list(storage.table_observations_root.iterdir()) == []
