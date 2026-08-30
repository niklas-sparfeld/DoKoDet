import hashlib
import json
import sys
from pathlib import Path
from uuid import UUID

import pytest
from app_factory import create_test_app
from fastapi.testclient import TestClient
from table_evidence_analyzer import (
    AnalyzerEvidence,
    TableObservation,
    canonical_json_bytes,
    parse_observation_bytes,
)

from dokodetector_backend.analyzer_adapter import EvidenceIntegrityError
from dokodetector_backend.analyzer_runner import AnalyzerRunner, AnalyzerRunnerError
from dokodetector_backend.config import Settings
from dokodetector_backend.evidence_package_storage import EvidencePackageStorage
from dokodetector_backend.persistence import TableObservationPersister
from dokodetector_backend.repository import (
    EvidenceRepository,
    RepositoryError,
    TableObservationConflict,
    upgrade_database,
)

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
    payload = json.loads(manifest_bytes)
    source_asset_id = f"source-evidence-{payload['package_id']}"

    def encode(value: dict[str, object]) -> bytes:
        return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()

    parts = {
        "manifest": ("manifest.json", manifest_bytes, "application/json"),
        "package_record": (
            "package-record.json",
            encode(
                {
                    "schema_version": "evidence-package-record/v1",
                    "package_id": payload["package_id"],
                    "source_asset_id": source_asset_id,
                    "source_permission": "project_use",
                    "allowed_uses": ["evaluation"],
                    "retention_state": "active",
                    "notes": "test",
                }
            ),
            "application/json",
        ),
        "task_enrollment": (
            "initial-task-enrollment.json",
            encode(
                {
                    "schema_version": "task-enrollment/v1",
                    "source_asset_id": source_asset_id,
                    "enrollments": [
                        {
                            "task_enrollment_id": f"enrollment-{payload['package_id']}-cardevent",
                            "task": "cardevent_event_detection",
                            "disposition": "selected",
                            "lifecycle_state": "intake",
                            "operator": "test",
                            "created_at_utc": "2026-01-01T00:00:00Z",
                            "reason": None,
                        },
                        {
                            "task_enrollment_id": f"enrollment-{payload['package_id']}-table",
                            "task": "table_evidence_analysis",
                            "disposition": "selected",
                            "lifecycle_state": "intake",
                            "operator": "test",
                            "created_at_utc": "2026-01-01T00:00:00Z",
                            "reason": None,
                        },
                    ],
                }
            ),
            "application/json",
        ),
        "lineage": (
            "lineage.json",
            encode(
                {
                    "schema_version": "evidence-package-lineage/v1",
                    "package_id": payload["package_id"],
                    "parent_source_asset_id": None,
                    "parent_recording_id": None,
                    "parent_video_id": None,
                    "session_id": payload["session"]["session_id"],
                }
            ),
            "application/json",
        ),
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
def backend(tmp_path) -> tuple[TestClient, EvidenceRepository, EvidencePackageStorage]:
    database_url = f"sqlite:///{tmp_path / 'evidence.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        evidence_root=tmp_path / "runtime",
        evidence_package_intake_root=tmp_path / "intake" / "evidence-packages",
    )
    app = create_test_app(settings)
    return TestClient(app), app.state.repository, app.state.evidence_package_storage


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
    frame_path = storage.package_path(payload["package_id"]) / "frames" / "frame_00.jpg"
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
        AnalyzerRunner(
            repository, storage, Analyzer(), observation_storage=client.app.state.storage
        ).run_once(PACKAGE_ID)

    assert called is False
    assert repository.list_table_observations(PACKAGE_ID) == ()


def test_observation_crosses_analyzer_backend_reconstruction_boundary(backend) -> None:
    client, repository, storage = backend
    payload, _ = upload_fixture(client, "example-complete")
    stored = AnalyzerRunner(
        repository, storage, FixtureAnalyzer(), observation_storage=client.app.state.storage
    ).run_once(payload["package_id"])

    assert stored is not None
    persisted = parse_observation_bytes(stored.observation_json.encode())
    assert persisted.schema_version == "table-observation/v1"
    assert persisted.source.package_id == str(PACKAGE_ID)
    assert persisted.session.event_sequence == 1
    assert (
        client.app.state.storage.root / stored.relative_path
    ).read_bytes() == stored.observation_json.encode()

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


def test_persisted_analyzer_observation_runs_through_round_reconstruction_harness(
    backend, monkeypatch
) -> None:
    client, repository, storage = backend
    payload, _ = upload_fixture(client, "example-complete")
    stored = AnalyzerRunner(
        repository, storage, FixtureAnalyzer(), observation_storage=client.app.state.storage
    ).run_once(payload["package_id"])
    assert stored is not None

    request_path = client.app.state.storage.root / "round-reconstruction-request.json"
    request_path.write_text(
        json.dumps(
            {
                "schema_version": "round-reconstruction-run/v1",
                "run_id": "persisted-observation-round-01",
                "round_setup": {
                    "game_id": "game-01",
                    "round_id": "game-01-round-01",
                    "ruleset": {"name": "doko-normal", "version": "v1"},
                    "deck_variant": "doko-40-v1",
                    "active_players": [
                        "player-01",
                        "player-02",
                        "player-03",
                        "player-04",
                    ],
                    "dealer": "player-04",
                    "first_trick_leader": "player-01",
                },
                "observation_paths": [stored.relative_path],
                "search": {
                    "max_missing_plays": 1,
                    "max_hypotheses": 256,
                    "max_search_nodes": 250000,
                },
                "output_root": "artifacts/round-reconstruction",
            }
        ),
        encoding="utf-8",
    )

    repository_root = Path(__file__).parents[2]
    monkeypatch.syspath_prepend(str(repository_root / "operations" / "src"))
    monkeypatch.syspath_prepend(str(repository_root / "game_engine" / "src"))
    from doko_operations.round_reconstruction import (
        parse_round_reconstruction_result_bytes,
        run_round_reconstruction,
    )

    monkeypatch.chdir(repository_root / "backend")
    artifacts = run_round_reconstruction(request_path)

    persisted_path = client.app.state.storage.root / stored.relative_path
    assert persisted_path.read_bytes() == stored.observation_json.encode()
    assert artifacts.result.status == "incomplete"
    assert artifacts.result.sources[0].observation_path == stored.relative_path
    assert artifacts.result.sources[0].observation_id == stored.observation_id
    assert artifacts.result.sources[0].sha256 == hashlib.sha256(
        persisted_path.read_bytes()
    ).hexdigest()
    assert parse_round_reconstruction_result_bytes(
        artifacts.result_path.read_bytes()
    ).to_mapping() == artifacts.result.to_mapping()


def test_runner_is_idempotent_and_processes_pending_packages(backend) -> None:
    client, repository, storage = backend
    first_payload, _ = upload_fixture(client, "example-complete")
    second_payload, _ = upload_fixture(client, "example-incomplete")
    runner = AnalyzerRunner(
        repository, storage, FixtureAnalyzer(), observation_storage=client.app.state.storage
    )

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

    runner = AnalyzerRunner(
        repository, storage, FlakyAnalyzer(), observation_storage=client.app.state.storage
    )
    with pytest.raises(AnalyzerRunnerError):
        runner.run_once(payload["package_id"])
    assert repository.list_table_observations(PACKAGE_ID) == ()
    recovered = runner.run_once(payload["package_id"])
    assert recovered is not None
    assert attempts == 2


def test_observation_conflict_keeps_original_bytes(backend) -> None:
    client, repository, storage = backend
    payload, _ = upload_fixture(client, "example-complete")
    stored = AnalyzerRunner(
        repository, storage, FixtureAnalyzer(), observation_storage=client.app.state.storage
    ).run_once(payload["package_id"])
    assert stored is not None
    original_bytes = stored.observation_json.encode()
    changed = TableObservation.model_validate(
        json.loads(original_bytes) | {"observation_id": "observation-other"}
    )
    # Same package and analyzer identity must remain idempotent, even with a different ID.
    with pytest.raises(TableObservationConflict):
        TableObservationPersister(repository, client.app.state.storage).persist(
            changed, canonical_json_bytes(changed)
        )
    assert (
        repository.get_table_observation(stored.observation_id).observation_json.encode()
        == original_bytes
    )
    assert (client.app.state.storage.root / stored.relative_path).read_bytes() == original_bytes


def test_database_failure_removes_staged_observation_directory(backend, monkeypatch) -> None:
    client, repository, storage = backend
    payload, _ = upload_fixture(client, "example-complete")

    def fail(*args, **kwargs):
        raise RepositoryError("database failed")

    monkeypatch.setattr(repository, "insert_table_observation", fail)
    with pytest.raises(RepositoryError):
        AnalyzerRunner(
            repository, storage, FixtureAnalyzer(), observation_storage=client.app.state.storage
        ).run_once(payload["package_id"])

    assert repository.list_table_observations(PACKAGE_ID) == ()
    assert client.app.state.storage.table_observations_root.exists()
    assert list(client.app.state.storage.table_observations_root.iterdir()) == []
