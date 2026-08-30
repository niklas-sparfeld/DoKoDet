from __future__ import annotations

import logging
import time
from pathlib import Path

from app_factory import create_test_app
from test_round_analysis_api import (
    ANALYSIS_ID,
    RECORDING_ID,
    SESSION_ID,
    _analysis_payload,
    _backend,
    _upload_linked_package,
)

from dokodetector_backend.config import Settings
from dokodetector_backend.repository import (
    RoundAnalysisRepository,
    StoredRoundAnalysis,
    create_database_engine,
    upgrade_database,
)
from dokodetector_backend.round_analysis_contract import RoundAnalysisCreateRequest

BACKEND_ROOT = Path(__file__).parents[1]


def _events(caplog, event_name: str) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records if getattr(record, "event_name", None) == event_name
    ]


def test_synchronous_analysis_logs_info_lifecycle_and_debug_package_trace(
    caplog, tmp_path: Path
) -> None:
    caplog.set_level(logging.DEBUG, logger="dokodetector_backend")
    client, _ = _backend(tmp_path, synchronous=True)
    package_id = _upload_linked_package(client)
    caplog.clear()

    response = client.post(
        "/v1/round-analyses",
        json=_analysis_payload(package_ids=[package_id]),
        headers={"X-DokoDetector-Request-ID": "request-m2-sync"},
    )

    assert response.status_code == 202
    assert response.json()["state"] == "complete"
    info_events = [record for record in caplog.records if record.levelno == logging.INFO]
    state_sequence = [
        record.event_fields["state"]
        for record in info_events
        if record.event_name in {"round_analysis_created", "round_analysis_state_changed"}
    ]
    assert state_sequence == ["queued", "analyzing_evidence", "reconstructing"]
    completed = _events(caplog, "round_analysis_completed")
    assert len(completed) == 1
    assert completed[0].levelno == logging.INFO
    assert completed[0].event_fields == {
        "analysis_id": ANALYSIS_ID,
        "completed_evidence_packages": 1,
        "recording_id": RECORDING_ID,
        "request_id": "request-m2-sync",
        "result_status": response.json()["result"]["reconstruction_status"],
        "round_id": "round-round-analysis",
        "session_id": SESSION_ID,
        "state": "complete",
        "total_evidence_packages": 1,
    }

    package_started = _events(caplog, "round_analysis_package_started")
    package_completed = _events(caplog, "round_analysis_package_completed")
    assert len(package_started) == len(package_completed) == 1
    assert package_started[0].levelno == package_completed[0].levelno == logging.DEBUG
    assert package_started[0].event_fields == {
        "analysis_id": ANALYSIS_ID,
        "package_id": package_id,
        "package_index": 1,
        "request_id": "request-m2-sync",
        "total_packages": 1,
    }
    assert package_completed[0].event_fields == {
        "analysis_id": ANALYSIS_ID,
        "analyzer": "deterministic-local",
        "analyzer_version": "v1",
        "analysis_status": "insufficient_evidence",
        "package_id": package_id,
        "package_index": 1,
        "request_id": "request-m2-sync",
        "total_packages": 1,
    }
    assert _events(caplog, "round_analysis_reconstruction_started")[0].levelno == logging.DEBUG
    assert _events(caplog, "round_analysis_reconstruction_completed")[0].levelno == logging.DEBUG
    assert _events(caplog, "round_analysis_artifacts_published")[0].levelno == logging.DEBUG


def test_asynchronous_analysis_logs_queue_and_reaches_terminal_state(
    caplog, tmp_path: Path
) -> None:
    caplog.set_level(logging.DEBUG, logger="dokodetector_backend")
    client, _ = _backend(tmp_path, synchronous=False)
    package_id = _upload_linked_package(client)
    caplog.clear()

    with client:
        response = client.post(
            "/v1/round-analyses",
            json=_analysis_payload(package_ids=[package_id]),
            headers={"X-DokoDetector-Request-ID": "request-m2-async"},
        )
        assert response.status_code == 202
        assert response.json()["state"] in {"queued", "analyzing_evidence", "complete"}

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = client.get(f"/v1/round-analyses/{ANALYSIS_ID}")
            if status.json()["state"] == "complete":
                break
            time.sleep(0.01)
        assert status.json()["state"] == "complete"

    queued = _events(caplog, "round_analysis_queued")
    assert len(queued) == 1
    assert queued[0].levelno == logging.DEBUG
    assert queued[0].event_fields["request_id"] == "request-m2-async"
    worker_started = _events(caplog, "round_analysis_worker_started")
    worker_stopped = _events(caplog, "round_analysis_worker_stopped")
    assert len(worker_started) == len(worker_stopped) == 1
    assert worker_started[0].levelno == worker_stopped[0].levelno == logging.INFO
    completed = _events(caplog, "round_analysis_completed")
    assert len(completed) == 1
    assert completed[0].event_fields["request_id"] == "request-m2-async"


def test_failed_analysis_logs_error_traceback_and_safe_terminal_fields(
    caplog, tmp_path: Path
) -> None:
    caplog.set_level(logging.DEBUG, logger="dokodetector_backend")
    client, app = _backend(tmp_path, synchronous=True)
    package_id = _upload_linked_package(client)

    def fail(_: object) -> object:
        raise RuntimeError("secret analyzer details")

    app.state.analyzer.analyze = fail
    caplog.clear()

    response = client.post(
        "/v1/round-analyses",
        json=_analysis_payload(
            analysis_id="550e8400-e29b-41d4-a716-446655440021",
            package_ids=[package_id],
        ),
        headers={"X-DokoDetector-Request-ID": "request-m2-failed"},
    )

    assert response.status_code == 202
    assert response.json()["state"] == "failed"
    assert response.json()["error"] == "The round analysis could not be completed."
    failed = _events(caplog, "round_analysis_failed")
    assert len(failed) == 1
    assert failed[0].levelno == logging.ERROR
    assert failed[0].exc_info is not None
    assert failed[0].event_fields == {
        "analysis_id": "550e8400-e29b-41d4-a716-446655440021",
        "completed_evidence_packages": 0,
        "error": "The round analysis could not be completed.",
        "recording_id": RECORDING_ID,
        "request_id": "request-m2-failed",
        "round_id": "round-round-analysis",
        "session_id": SESSION_ID,
        "state": "failed",
        "total_evidence_packages": 1,
    }
    assert "secret analyzer details" not in response.text


def test_startup_recovery_logs_a_warning_for_interrupted_analysis(caplog, tmp_path: Path) -> None:
    caplog.set_level(logging.DEBUG, logger="dokodetector_backend")
    database_url = f"sqlite:///{tmp_path / 'backend.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    request = RoundAnalysisCreateRequest.model_validate(
        {
            "analysis_id": "00000000-0000-0000-0000-000000000032",
            "recording_id": "recording-0032",
            "round_id": "round-0032",
            "session_id": "00000000-0000-0000-0000-000000000033",
            "round_setup": {
                "game_id": "game-0032",
                "round_id": "round-0032",
                "ruleset": {"name": "doko-normal", "version": "v1"},
                "deck_variant": "doko-40-v1",
                "active_players": ["seat-1", "seat-2", "seat-3", "seat-4"],
                "dealer": "seat-1",
                "first_trick_leader": "seat-2",
            },
            "evidence_package_ids": ["00000000-0000-0000-0000-000000000034"],
            "search": {
                "max_missing_plays": 2,
                "max_hypotheses": 8,
                "max_search_nodes": 1000,
            },
        }
    )
    repository = RoundAnalysisRepository(create_database_engine(database_url))
    repository.insert(StoredRoundAnalysis.from_request(request))

    create_test_app(
        Settings(
            _env_file=None,
            database_url=database_url,
            evidence_root=tmp_path / "runtime",
            repository_intake_root=tmp_path / "recordings",
            evidence_package_intake_root=tmp_path / "evidence-packages",
        )
    )

    recovered = _events(caplog, "round_analysis_recovery_failed")
    assert len(recovered) == 1
    assert recovered[0].levelno == logging.WARNING
    assert recovered[0].event_fields == {
        "analysis_count": 1,
        "reason": "backend_restarted",
    }
    checked = _events(caplog, "round_analysis_recovery_checked")
    assert len(checked) == 1
    assert checked[0].levelno == logging.DEBUG
    assert checked[0].event_fields == {"failed_count": 1}
