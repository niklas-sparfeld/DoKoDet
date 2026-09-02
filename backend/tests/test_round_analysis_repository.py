import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from dokodetector_backend.repository import StoredRoundAnalysis
from dokodetector_backend.round_analysis_contract import RoundAnalysisCreateRequest
from dokodetector_backend.round_analysis_storage import RoundAnalysisArtifactStorage
from dokodetector_backend.round_analysis_store import (
    RoundAnalysisConflict,
    RoundAnalysisStore,
)

ANALYSIS_ID = UUID("00000000-0000-0000-0000-000000000032")
SESSION_ID = UUID("00000000-0000-0000-0000-000000000033")


def analysis_request(*, analysis_id: UUID = ANALYSIS_ID) -> RoundAnalysisCreateRequest:
    return RoundAnalysisCreateRequest.model_validate(
        {
            "analysis_id": str(analysis_id),
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
            "evidence_package_ids": [
                "00000000-0000-0000-0000-000000000034",
                "00000000-0000-0000-0000-000000000035",
            ],
            "search": {
                "max_missing_plays": 2,
                "max_hypotheses": 8,
                "max_search_nodes": 1000,
            },
        }
    )


def store_for(tmp_path: Path) -> tuple[RoundAnalysisStore, RoundAnalysisArtifactStorage]:
    artifacts = RoundAnalysisArtifactStorage(tmp_path)
    return RoundAnalysisStore(artifacts), artifacts


def test_round_analysis_state_supports_lifecycle_and_restart_conversion(tmp_path: Path) -> None:
    store, _ = store_for(tmp_path)
    request = analysis_request()
    analysis = StoredRoundAnalysis.from_request(
        request,
        created_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )

    inserted, created = store.insert(analysis)
    replayed, replay_created = store.insert(analysis)
    store.update_progress(ANALYSIS_ID, state="analyzing_evidence", completed=1)
    converted = store.fail_non_terminal(
        now=datetime(2026, 8, 30, 1, 2, 3, tzinfo=timezone.utc)
    )

    assert created is True
    assert replay_created is False
    assert inserted == analysis
    assert replayed == analysis
    assert converted == 1
    stored = store.get(ANALYSIS_ID)
    assert stored is not None
    assert stored.state == "failed"
    assert stored.error == "The analysis did not finish before the backend restarted."
    assert stored.completed_at == datetime(2026, 8, 30, 1, 2, 3, tzinfo=timezone.utc)
    assert (tmp_path / "round-analyses" / str(ANALYSIS_ID) / "state.json").is_file()
    fresh_store = RoundAnalysisStore(RoundAnalysisArtifactStorage(tmp_path))
    assert fresh_store.get(ANALYSIS_ID) == stored


def test_round_analysis_store_keeps_terminal_state_and_rejects_conflicts(
    tmp_path: Path,
) -> None:
    store, artifacts = store_for(tmp_path)
    request = analysis_request()
    store.create(request)

    with pytest.raises(RoundAnalysisConflict):
        store.create(
            request.model_copy(
                update={
                    "search": request.search.model_copy(update={"max_hypotheses": 9}),
                }
            ),
        )

    published = artifacts.publish(ANALYSIS_ID, b'{"input":true}', b'{"result":true}')
    complete = store.mark_complete(
        ANALYSIS_ID,
        result_status="resolved",
        result_json='{"result":true}',
        input_artifact_id=published.input.relative_path,
        input_artifact_sha256=published.input.sha256,
        result_artifact_id=published.result.relative_path,
        result_artifact_sha256=published.result.sha256,
        completed_at=datetime(2026, 8, 30, 2, 3, 4, tzinfo=timezone.utc),
    )

    assert store.fail_non_terminal() == 0
    assert store.get(ANALYSIS_ID) == complete
    assert store.list_by_recording("recording-0032") == (complete,)


def test_round_analysis_progress_cannot_regress(tmp_path: Path) -> None:
    store, _ = store_for(tmp_path)
    store.create(analysis_request())
    store.update_progress(ANALYSIS_ID, state="analyzing_evidence", completed=1)

    with pytest.raises(ValueError, match="cannot regress"):
        store.update_progress(ANALYSIS_ID, state="analyzing_evidence", completed=0)
    with pytest.raises(ValueError, match="cannot change"):
        store.update_progress(ANALYSIS_ID, state="queued", completed=1)


def test_round_analysis_completion_requires_immutable_artifacts(tmp_path: Path) -> None:
    store, _ = store_for(tmp_path)
    store.create(analysis_request())

    with pytest.raises(OSError, match="artifact is unavailable"):
        store.mark_complete(
            ANALYSIS_ID,
            result_status="resolved",
            result_json=json.dumps({"result": True}),
            input_artifact_id=f"round-analyses/{ANALYSIS_ID}/input.json",
            input_artifact_sha256="0" * 64,
            result_artifact_id=f"round-analyses/{ANALYSIS_ID}/result.json",
            result_artifact_sha256="1" * 64,
        )

    assert store.get(ANALYSIS_ID).state == "queued"  # type: ignore[union-attr]


def test_round_analysis_concurrent_progress_updates_keep_the_highest_progress(
    tmp_path: Path,
) -> None:
    store, _ = store_for(tmp_path)
    store.create(analysis_request())
    store.update_progress(ANALYSIS_ID, state="analyzing_evidence", completed=0)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                store.update_progress,
                ANALYSIS_ID,
                state="analyzing_evidence",
                completed=completed,
            )
            for completed in (1, 2)
        ]
        errors = []
        for future in futures:
            try:
                future.result()
            except ValueError as error:
                errors.append(str(error))

    assert all("cannot regress" in error for error in errors)
    assert store.get(ANALYSIS_ID).completed_evidence_packages == 2  # type: ignore[union-attr]
