from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from app_factory import create_test_app
from fastapi.testclient import TestClient
from table_evidence_analyzer import TableObservation, parse_observation_bytes
from test_api import load_upload_fixture, multipart_parts

from dokodetector_backend.config import Settings
from dokodetector_backend.repository import upgrade_database
from dokodetector_backend.repository_bundle_repository import StoredRepositoryBundle

BACKEND_ROOT = Path(__file__).parents[1]
SESSION_ID = "6ba7b810-9dad-41d1-80b4-00c04fd430c8"
RECORDING_ID = "recording-round-analysis"
ANALYSIS_ID = "550e8400-e29b-41d4-a716-446655440020"


def _analysis_payload(
    *, analysis_id: str = ANALYSIS_ID, package_ids: list[str]
) -> dict[str, object]:
    return {
        "schema_version": "round-analysis/v1",
        "analysis_id": analysis_id,
        "recording_id": RECORDING_ID,
        "round_id": "round-round-analysis",
        "session_id": SESSION_ID,
        "round_setup": {
            "game_id": "game-round-analysis",
            "round_id": "round-round-analysis",
            "ruleset": {"name": "doko-normal", "version": "v1"},
            "deck_variant": "doko-40-v1",
            "active_players": ["seat-1", "seat-2", "seat-3", "seat-4"],
            "dealer": "seat-1",
            "first_trick_leader": "seat-1",
        },
        "evidence_package_ids": package_ids,
        "search": {
            "max_missing_plays": 40,
            "max_hypotheses": 8,
            "max_search_nodes": 1000,
        },
    }


def _backend(tmp_path: Path, *, synchronous: bool = True) -> tuple[TestClient, object]:
    database_url = f"sqlite:///{tmp_path / 'round-analysis.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    app = create_test_app(
        Settings(
            _env_file=None,
            database_url=database_url,
            evidence_root=tmp_path / "runtime",
            evidence_package_intake_root=tmp_path / "intake" / "evidence-packages",
            repository_intake_root=tmp_path / "intake" / "recordings",
        ),
        run_round_analysis_synchronously=synchronous,
    )
    app.state.repository_bundle_repository.insert(
        StoredRepositoryBundle(
            recording_id=RECORDING_ID,
            source_asset_id="source-round-analysis",
            video_id="video-round-analysis",
            session_id=SESSION_ID,
            source_sha256="a" * 64,
            manifest_sha256="b" * 64,
            source_record_sha256="c" * 64,
            task_enrollment_sha256="d" * 64,
            proposal_run_ids=(),
            bundle_fingerprint="e" * 64,
            state="complete",
            received_at=datetime.now(timezone.utc),
        )
    )
    return TestClient(app), app


def _upload_linked_package(
    client: TestClient,
    *,
    package_id: str | None = None,
    event_sequence: int | None = None,
) -> str:
    manifest_bytes, frame_sources, payload, video_source = load_upload_fixture("example-incomplete")
    if package_id is not None:
        payload["package_id"] = package_id
    if event_sequence is not None:
        payload["session"]["event_sequence"] = event_sequence  # type: ignore[index]
    if package_id is not None or event_sequence is not None:
        manifest_bytes = json.dumps(payload, separators=(",", ":")).encode()
    parts = multipart_parts(manifest_bytes, frame_sources, video_source)
    lineage = json.loads(parts["lineage"][1])
    lineage["parent_recording_id"] = RECORDING_ID
    parts["lineage"] = (
        "lineage.json",
        json.dumps(lineage, separators=(",", ":"), sort_keys=True).encode(),
        "application/json",
    )
    response = client.put(
        f"/v1/evidence-packages/{payload['package_id']}",
        files=parts,
    )
    assert response.status_code == 201
    return str(payload["package_id"])


def test_create_runs_worker_and_publishes_compact_result(backend_tmp_path: Path) -> None:
    client, app = _backend(backend_tmp_path)
    package_id = _upload_linked_package(client)
    payload = _analysis_payload(package_ids=[package_id])

    response = client.post("/v1/round-analyses", json=payload)

    assert response.status_code == 202
    body = response.json()
    assert body["analysis_id"] == ANALYSIS_ID
    assert body["state"] == "complete"
    assert body["completed_evidence_packages"] == 1
    assert body["result"]["terminal_status"] == "complete"
    assert body["result"]["reconstruction_status"] in {
        "resolved",
        "ambiguous",
        "incomplete",
        "impossible",
    }
    assert body["result"]["input_artifact_id"] == (f"round-analyses/{ANALYSIS_ID}/input.json")
    assert body["result"]["result_artifact_id"] == (f"round-analyses/{ANALYSIS_ID}/result.json")
    assert app.state.round_analysis_storage.analysis_path(ANALYSIS_ID).is_dir()
    assert client.get(f"/v1/round-analyses/{ANALYSIS_ID}").json() == body


def test_timeline_projects_exact_analysis_and_selects_central_frame(
    backend_tmp_path: Path,
) -> None:
    client, app = _backend(backend_tmp_path)
    package_id = _upload_linked_package(client)
    created = client.post(
        "/v1/round-analyses",
        json=_analysis_payload(package_ids=[package_id]),
    )

    response = client.get(f"/v1/round-analyses/{ANALYSIS_ID}/timeline")

    assert created.status_code == 202
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "round-analysis-timeline/v1"
    assert body["analysis_id"] == ANALYSIS_ID
    assert (
        body["artifact_hashes"]["input_sha256"]
        == hashlib.sha256(
            (
                app.state.round_analysis_storage.analysis_path(ANALYSIS_ID) / "input.json"
            ).read_bytes()
        ).hexdigest()
    )
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["package_id"] == package_id
    assert row["observation_id"] == f"{package_id}-observation"
    assert row["table_observation"]["source"]["package_id"] == package_id
    assert row["central_frame"]["part_name"] == "frame_03"
    assert row["central_frame"]["actual_offset_ms"] == 149
    assert row["central_frame"]["width"] == 1920
    assert row["central_frame"]["height"] == 1080
    assert row["central_frame"]["url"] == (
        f"/v1/round-analyses/{ANALYSIS_ID}/evidence-packages/{package_id}/frames/frame_03"
    )
    assert body["hypotheses"] == []
    assert {warning["code"] for warning in body["warnings"]} >= {"insufficient_evidence"}


def test_timeline_preserves_observed_card_fields_from_exact_input(
    backend_tmp_path: Path,
) -> None:
    client, app = _backend(backend_tmp_path)
    package_id = _upload_linked_package(client)
    observation_fixture = (
        Path(__file__).parents[2]
        / "fixtures"
        / "game-engine"
        / "v1"
        / "observations"
        / "minimal.json"
    )

    class ObservedCardAnalyzer:
        name = "deterministic-local"
        version = "v1"

        def analyze(self, evidence: object) -> TableObservation:
            source = parse_observation_bytes(observation_fixture.read_bytes())
            payload = source.model_dump(mode="python", exclude_none=True)
            payload["observation_id"] = f"{package_id}-observation"
            payload["source"] = {"package_id": package_id}
            payload["session"] = {
                "session_id": SESSION_ID,
                "event_sequence": 2,
            }
            payload["analyzer"] = {"name": self.name, "version": self.version}
            return TableObservation.model_validate(payload)

    app.state.round_analysis_service.analyzer_runner.analyzer = ObservedCardAnalyzer()
    created = client.post(
        "/v1/round-analyses",
        json=_analysis_payload(package_ids=[package_id]),
    )

    response = client.get(f"/v1/round-analyses/{ANALYSIS_ID}/timeline")

    assert created.status_code == 202
    assert response.status_code == 200
    assert (
        response.json()["rows"][0]["table_observation"]["cards"][0]["identity_candidates"][0][
            "card"
        ]
        == "HEARTS_TEN"
    )


def test_analysis_scoped_frame_delivery_checks_ownership_and_media_integrity(
    backend_tmp_path: Path,
) -> None:
    client, app = _backend(backend_tmp_path)
    package_id = _upload_linked_package(client)
    foreign_package_id = _upload_linked_package(
        client,
        package_id="550e8400-e29b-41d4-a716-446655440099",
        event_sequence=3,
    )
    created = client.post(
        "/v1/round-analyses",
        json=_analysis_payload(package_ids=[package_id]),
    )
    frame_path = (
        app.state.evidence_package_storage.package_path(package_id) / "frames" / "frame_03.jpg"
    )
    frame_bytes = frame_path.read_bytes()

    delivered = client.get(
        f"/v1/round-analyses/{ANALYSIS_ID}/evidence-packages/{package_id}/frames/frame_03"
    )
    foreign = client.get(
        f"/v1/round-analyses/{ANALYSIS_ID}/evidence-packages/{foreign_package_id}/frames/frame_03"
    )
    missing = client.get(
        f"/v1/round-analyses/{ANALYSIS_ID}/evidence-packages/{package_id}/frames/not_declared"
    )

    assert created.status_code == 202
    assert delivered.status_code == 200
    assert delivered.content == frame_bytes
    assert delivered.headers["content-type"] == "image/jpeg"
    assert delivered.headers["etag"] == '"' + hashlib.sha256(frame_bytes).hexdigest() + '"'
    assert delivered.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "frame_not_found"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "frame_not_found"

    frame_path.write_bytes(b"corrupted frame")
    invalid_media = client.get(
        f"/v1/round-analyses/{ANALYSIS_ID}/evidence-packages/{package_id}/frames/frame_03"
    )

    assert invalid_media.status_code == 500
    assert invalid_media.json()["error"]["code"] == "analysis_integrity_error"


def test_timeline_rejects_tampered_analysis_artifacts(
    backend_tmp_path: Path,
) -> None:
    client, app = _backend(backend_tmp_path)
    package_id = _upload_linked_package(client)
    created = client.post(
        "/v1/round-analyses",
        json=_analysis_payload(package_ids=[package_id]),
    )
    result_path = app.state.round_analysis_storage.analysis_path(ANALYSIS_ID) / "result.json"
    result_path.write_bytes(result_path.read_bytes() + b" ")

    response = client.get(f"/v1/round-analyses/{ANALYSIS_ID}/timeline")

    assert created.status_code == 202
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "analysis_integrity_error"


def test_create_is_idempotent_and_conflicting_input_is_rejected(backend_tmp_path: Path) -> None:
    client, _ = _backend(backend_tmp_path)
    package_id = _upload_linked_package(client)
    payload = _analysis_payload(package_ids=[package_id])

    first = client.post("/v1/round-analyses", json=payload)
    replay = client.post("/v1/round-analyses", json=payload)
    changed = json.loads(json.dumps(payload))
    changed["search"]["max_hypotheses"] = 9
    conflict = client.post("/v1/round-analyses", json=changed)

    assert first.status_code == 202
    assert replay.status_code == 202
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "analysis_conflict"


def test_create_rejects_unlinked_package(backend_tmp_path: Path) -> None:
    client, _ = _backend(backend_tmp_path)
    package_id = _upload_linked_package(client)
    package_path = client.app.state.evidence_package_storage.package_path(package_id)
    lineage = json.loads((package_path / "lineage.json").read_text())
    lineage["parent_recording_id"] = "another-recording"
    (package_path / "lineage.json").write_text(json.dumps(lineage))

    response = client.post(
        "/v1/round-analyses",
        json=_analysis_payload(package_ids=[package_id]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_analysis_request"


def test_create_rejects_unknown_fields_and_unknown_packages(backend_tmp_path: Path) -> None:
    client, _ = _backend(backend_tmp_path)
    payload = _analysis_payload(package_ids=["550e8400-e29b-41d4-a716-446655440099"])
    payload["unexpected"] = True

    unknown_field = client.post("/v1/round-analyses", json=payload)
    payload.pop("unexpected")
    unknown_package = client.post("/v1/round-analyses", json=payload)

    assert unknown_field.status_code == 422
    assert unknown_field.json()["error"]["code"] == "invalid_request"
    assert unknown_package.status_code == 422
    assert unknown_package.json()["error"]["code"] == "invalid_analysis_request"


def test_worker_failure_is_a_terminal_safe_error(backend_tmp_path: Path) -> None:
    client, app = _backend(backend_tmp_path)
    package_id = _upload_linked_package(client)

    def fail(_: object) -> object:
        raise RuntimeError("secret analyzer details")

    app.state.analyzer.analyze = fail
    response = client.post(
        "/v1/round-analyses",
        json=_analysis_payload(
            analysis_id="550e8400-e29b-41d4-a716-446655440021",
            package_ids=[package_id],
        ),
    )

    assert response.status_code == 202
    assert response.json()["state"] == "failed"
    assert response.json()["error"] == "The round analysis could not be completed."
    assert "secret" not in response.text


def test_lifespan_starts_and_stops_one_worker(backend_tmp_path: Path) -> None:
    client, app = _backend(backend_tmp_path, synchronous=False)

    with client:
        assert app.state.round_analysis_service.worker_task is not None
        assert not app.state.round_analysis_service.worker_task.done()
    assert app.state.round_analysis_service.worker_task is None


def test_lifespan_worker_processes_queued_analysis(backend_tmp_path: Path) -> None:
    client, _ = _backend(backend_tmp_path, synchronous=False)
    package_id = _upload_linked_package(client)

    with client:
        created = client.post(
            "/v1/round-analyses",
            json=_analysis_payload(package_ids=[package_id]),
        )
        assert created.status_code == 202
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = client.get(f"/v1/round-analyses/{ANALYSIS_ID}")
            if status.json()["state"] == "complete":
                break
            time.sleep(0.01)
        assert status.json()["state"] == "complete"


def _install_two_observation_analyzer(app, package_ids: list[str]) -> None:
    observation_fixture = (
        Path(__file__).parents[2]
        / "fixtures"
        / "game-engine"
        / "v1"
        / "observations"
        / "minimal.json"
    )
    calls = 0

    class TwoObservationAnalyzer:
        name = "deterministic-local"
        version = "v1"

        def analyze(self, evidence: object) -> TableObservation:
            nonlocal calls
            package_id = package_ids[calls]
            calls += 1
            source = parse_observation_bytes(observation_fixture.read_bytes())
            payload = source.model_dump(mode="python", exclude_none=True)
            payload["observation_id"] = f"{package_id}-observation"
            payload["source"] = {"package_id": package_id}
            payload["session"] = {
                "session_id": SESSION_ID,
                "event_sequence": calls,
            }
            payload["analyzer"] = {"name": self.name, "version": self.version}
            return TableObservation.model_validate(payload)

    app.state.round_analysis_service.analyzer_runner.analyzer = TwoObservationAnalyzer()


def _counterfactual_payload(
    source: dict[str, object],
    *,
    counterfactual_id: str,
    excluded_observation_ids: list[str],
    card_identity_overrides: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    result = source["result"]
    assert isinstance(result, dict)
    return {
        "schema_version": "round-analysis-counterfactual/v1",
        "counterfactual_id": counterfactual_id,
        "source_analysis_id": ANALYSIS_ID,
        "source_input_sha256": result["input_artifact_sha256"],
        "source_result_sha256": result["result_artifact_sha256"],
        "excluded_observation_ids": excluded_observation_ids,
        "excluded_observed_cards": [],
        "card_identity_overrides": card_identity_overrides or [],
        "candidate_probability_overrides": [],
    }


def _snapshot_files(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_counterfactual_create_read_is_idempotent_and_restart_safe(
    backend_tmp_path: Path,
) -> None:
    client, app = _backend(backend_tmp_path)
    package_ids = [
        _upload_linked_package(client, event_sequence=1),
        _upload_linked_package(
            client,
            package_id="550e8400-e29b-41d4-a716-446655440098",
            event_sequence=2,
        ),
    ]
    _install_two_observation_analyzer(app, package_ids)
    created_analysis = client.post(
        "/v1/round-analyses",
        json=_analysis_payload(package_ids=package_ids),
    )
    assert created_analysis.status_code == 202
    source = created_analysis.json()
    source_input = (
        app.state.round_analysis_storage.analysis_path(ANALYSIS_ID) / "input.json"
    ).read_bytes()
    source_result = (
        app.state.round_analysis_storage.analysis_path(ANALYSIS_ID) / "result.json"
    ).read_bytes()
    source_package_files = {
        package_id: _snapshot_files(app.state.evidence_package_storage.package_path(package_id))
        for package_id in package_ids
    }
    source_observation_files = {
        observation_id: _snapshot_files(app.state.storage.table_observation_path(observation_id))
        for observation_id in (f"{package_id}-observation" for package_id in package_ids)
    }
    counterfactual_id = "550e8400-e29b-41d4-a716-446655440097"
    payload = _counterfactual_payload(
        source,
        counterfactual_id=counterfactual_id,
        excluded_observation_ids=[f"{package_ids[0]}-observation"],
    )

    first = client.post(
        f"/v1/round-analyses/{ANALYSIS_ID}/counterfactuals",
        json=payload,
    )
    replay = client.post(
        f"/v1/round-analyses/{ANALYSIS_ID}/counterfactuals",
        json=payload,
    )
    read = client.get(f"/v1/round-analyses/{ANALYSIS_ID}/counterfactuals/{counterfactual_id}")

    assert first.status_code == 201
    assert replay.status_code == 201
    assert read.status_code == 200
    assert replay.json() == first.json()
    assert read.json() == first.json()
    body = first.json()
    assert body["counterfactual_id"] == counterfactual_id
    assert body["result"]["run_id"] == counterfactual_id
    assert body["result"]["search"] == {
        "max_missing_plays": 40,
        "max_hypotheses": 8,
        "max_search_nodes": 1000,
    }
    assert body["artifacts"]["request"]["relative_path"].endswith(
        f"/counterfactuals/{counterfactual_id}/request.json"
    )
    counterfactual_path = app.state.round_analysis_storage.counterfactual_path(
        ANALYSIS_ID, counterfactual_id
    )
    assert {path.name for path in counterfactual_path.iterdir()} == {
        "manifest.json",
        "request.json",
        "input.json",
        "result.json",
    }
    assert (
        app.state.round_analysis_storage.analysis_path(ANALYSIS_ID) / "input.json"
    ).read_bytes() == source_input
    assert (
        app.state.round_analysis_storage.analysis_path(ANALYSIS_ID) / "result.json"
    ).read_bytes() == source_result
    assert source_package_files == {
        package_id: _snapshot_files(app.state.evidence_package_storage.package_path(package_id))
        for package_id in package_ids
    }
    assert source_observation_files == {
        observation_id: _snapshot_files(app.state.storage.table_observation_path(observation_id))
        for observation_id in (f"{package_id}-observation" for package_id in package_ids)
    }

    changed = dict(payload)
    changed["excluded_observation_ids"] = [f"{package_ids[1]}-observation"]
    conflict = client.post(
        f"/v1/round-analyses/{ANALYSIS_ID}/counterfactuals",
        json=changed,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "counterfactual_conflict"

    for package_id in package_ids:
        assert app.state.repository.delete_table_observation(f"{package_id}-observation")

    database_url = f"sqlite:///{backend_tmp_path / 'round-analysis.sqlite'}"
    restarted_app = create_test_app(
        Settings(
            _env_file=None,
            database_url=database_url,
            evidence_root=backend_tmp_path / "runtime",
            evidence_package_intake_root=backend_tmp_path / "intake" / "evidence-packages",
            repository_intake_root=backend_tmp_path / "intake" / "recordings",
        ),
        run_round_analysis_synchronously=True,
    )
    restarted_client = TestClient(restarted_app)
    restarted = restarted_client.get(
        f"/v1/round-analyses/{ANALYSIS_ID}/counterfactuals/{counterfactual_id}"
    )
    source_timeline = restarted_client.get(f"/v1/round-analyses/{ANALYSIS_ID}/timeline")
    assert restarted.status_code == 200
    assert restarted.json() == first.json()
    assert source_timeline.status_code == 200
    assert len(source_timeline.json()["rows"]) == 2


def test_counterfactual_can_replace_a_one_candidate_card_identity(
    backend_tmp_path: Path,
) -> None:
    client, app = _backend(backend_tmp_path)
    package_ids = [
        _upload_linked_package(client, event_sequence=1),
        _upload_linked_package(
            client,
            package_id="550e8400-e29b-41d4-a716-446655440098",
            event_sequence=2,
        ),
    ]
    _install_two_observation_analyzer(app, package_ids)
    created_analysis = client.post(
        "/v1/round-analyses",
        json=_analysis_payload(package_ids=package_ids),
    )
    assert created_analysis.status_code == 202
    source = created_analysis.json()
    observation_id = f"{package_ids[0]}-observation"
    counterfactual_id = "550e8400-e29b-41d4-a716-446655440096"
    payload = _counterfactual_payload(
        source,
        counterfactual_id=counterfactual_id,
        excluded_observation_ids=[],
        card_identity_overrides=[
            {
                "observation_id": observation_id,
                "observed_card_id": "observation-001-card-01",
                "card": "CLUBS_TEN",
            }
        ],
    )

    response = client.post(
        f"/v1/round-analyses/{ANALYSIS_ID}/counterfactuals",
        json=payload,
    )

    assert response.status_code == 201
    assert response.json()["request"]["card_identity_overrides"] == [
        payload["card_identity_overrides"][0]
    ]
    derived_input = json.loads(
        (
            app.state.round_analysis_storage.counterfactual_path(ANALYSIS_ID, counterfactual_id)
            / "input.json"
        ).read_text(encoding="utf-8")
    )
    assert derived_input["observations"][0]["cards"][0]["identity_candidates"] == [
        {"card": "CLUBS_TEN", "probability": 1.0}
    ]


def test_counterfactual_failed_publication_can_be_retried(
    backend_tmp_path: Path,
    monkeypatch,
) -> None:
    client, app = _backend(backend_tmp_path)
    package_ids = [
        _upload_linked_package(client, event_sequence=1),
        _upload_linked_package(
            client,
            package_id="550e8400-e29b-41d4-a716-446655440096",
            event_sequence=2,
        ),
    ]
    _install_two_observation_analyzer(app, package_ids)
    source_response = client.post(
        "/v1/round-analyses",
        json=_analysis_payload(package_ids=package_ids),
    )
    assert source_response.status_code == 202
    counterfactual_id = "550e8400-e29b-41d4-a716-446655440095"
    payload = _counterfactual_payload(
        source_response.json(),
        counterfactual_id=counterfactual_id,
        excluded_observation_ids=[f"{package_ids[0]}-observation"],
    )
    storage = app.state.round_analysis_storage
    original_rename = storage._rename

    def fail_once(source, destination):
        monkeypatch.setattr(storage, "_rename", original_rename)
        raise OSError("simulated counterfactual publication failure")

    monkeypatch.setattr(storage, "_rename", fail_once)
    failed = client.post(
        f"/v1/round-analyses/{ANALYSIS_ID}/counterfactuals",
        json=payload,
    )
    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "internal_error"
    assert not storage.counterfactual_path(ANALYSIS_ID, counterfactual_id).exists()
    assert (
        list(
            storage.counterfactual_path(ANALYSIS_ID, counterfactual_id).parent.glob(
                f".{counterfactual_id}-*"
            )
        )
        == []
    )

    retried = client.post(
        f"/v1/round-analyses/{ANALYSIS_ID}/counterfactuals",
        json=payload,
    )
    assert retried.status_code == 201


@pytest.fixture()
def backend_tmp_path(tmp_path: Path) -> Path:
    return tmp_path
