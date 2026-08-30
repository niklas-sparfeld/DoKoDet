import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from dokodetector_backend.round_analysis_contract import (
    ROUND_ANALYSIS_STATES,
    RoundAnalysisCreateRequest,
    RoundAnalysisResult,
    RoundAnalysisStatus,
    canonical_analysis_request_bytes,
    canonical_analysis_request_sha256,
    parse_round_analysis_create_request_bytes,
)

ANALYSIS_ID = UUID("00000000-0000-0000-0000-000000000032")
SESSION_ID = UUID("00000000-0000-0000-0000-000000000033")
PACKAGE_IDS = [
    UUID("00000000-0000-0000-0000-000000000034"),
    UUID("00000000-0000-0000-0000-000000000035"),
]
STATUS_FIXTURE = Path(__file__).parents[2] / "fixtures" / "round-analysis" / "v1" / "statuses.json"


def create_payload() -> dict[str, object]:
    return {
        "analysis_id": str(ANALYSIS_ID),
        "recording_id": "recording-0032",
        "round_id": "round-0032",
        "session_id": str(SESSION_ID),
        "round_setup": {
            "game_id": "game-0032",
            "round_id": "round-0032",
            "ruleset": {"name": "doko-normal", "version": "v1"},
            "deck_variant": "doko-40-v1",
            "active_players": ["seat-1", "seat-2", "seat-3", "seat-4"],
            "dealer": "seat-1",
            "first_trick_leader": "seat-2",
        },
        "evidence_package_ids": [str(package_id) for package_id in PACKAGE_IDS],
        "search": {
            "max_missing_plays": 2,
            "max_hypotheses": 8,
            "max_search_nodes": 1000,
        },
    }


def test_create_request_is_strict_and_canonical() -> None:
    request = RoundAnalysisCreateRequest.model_validate(create_payload())
    reordered = dict(reversed(list(create_payload().items())))

    assert request.analysis_id == ANALYSIS_ID
    assert request.evidence_package_ids == PACKAGE_IDS
    assert canonical_analysis_request_bytes(request) == canonical_analysis_request_bytes(
        RoundAnalysisCreateRequest.model_validate(reordered)
    )
    assert canonical_analysis_request_sha256(request) == canonical_analysis_request_sha256(request)
    assert (
        parse_round_analysis_create_request_bytes(canonical_analysis_request_bytes(request))
        == request
    )


@pytest.mark.parametrize(
    "change",
    [
        {"unexpected": True},
        {"evidence_package_ids": [str(PACKAGE_IDS[0]), str(PACKAGE_IDS[0])]},
        {"round_setup": {"round_id": "other-round"}},
    ],
)
def test_create_request_rejects_invalid_shape(change: dict[str, object]) -> None:
    payload = create_payload()
    if "round_setup" in change:
        payload["round_setup"] = {**payload["round_setup"], **change["round_setup"]}  # type: ignore[index]
    else:
        payload.update(change)

    with pytest.raises(ValidationError):
        RoundAnalysisCreateRequest.model_validate(payload)


def test_status_requires_result_for_complete_and_error_for_failed() -> None:
    timestamp = datetime(2026, 8, 30, tzinfo=timezone.utc)
    result = RoundAnalysisResult(
        analysis_id=ANALYSIS_ID,
        terminal_status="complete",
        reconstruction_status="incomplete",
        hypotheses=[],
        focused_decisions=[],
        diagnostics={},
        input_artifact_id="round-analyses/analysis/input.json",
        input_artifact_sha256="0" * 64,
        result_artifact_id="round-analyses/analysis/result.json",
        result_artifact_sha256="1" * 64,
    )

    status = RoundAnalysisStatus(
        analysis_id=ANALYSIS_ID,
        recording_id="recording-0032",
        round_id="round-0032",
        session_id=SESSION_ID,
        state="complete",
        total_evidence_packages=2,
        completed_evidence_packages=2,
        result=result,
        created_at=timestamp,
        started_at=timestamp,
        completed_at=timestamp,
    )

    assert status.state in ROUND_ANALYSIS_STATES
    with pytest.raises(ValidationError):
        RoundAnalysisStatus(
            **status.model_dump(exclude={"result"}),
            result=None,
        )


def test_create_request_bytes_are_utf8_json() -> None:
    request = RoundAnalysisCreateRequest.model_validate(create_payload())

    assert json.loads(canonical_analysis_request_bytes(request)) == request.model_dump(mode="json")


def test_status_fixtures_cover_lifecycle_and_all_reconstruction_outcomes() -> None:
    payloads = json.loads(STATUS_FIXTURE.read_text(encoding="utf-8"))
    statuses = [RoundAnalysisStatus.model_validate(payload) for payload in payloads]

    assert [status.state for status in statuses[:3]] == [
        "queued",
        "analyzing_evidence",
        "reconstructing",
    ]
    completed = [status for status in statuses if status.state == "complete"]
    assert {status.result.reconstruction_status for status in completed if status.result} == {
        "resolved",
        "ambiguous",
        "incomplete",
        "impossible",
    }
    failed = next(status for status in statuses if status.state == "failed")
    assert failed.error == "The analysis did not finish before the backend restarted."
