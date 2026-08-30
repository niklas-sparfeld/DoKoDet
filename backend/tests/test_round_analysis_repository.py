from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from dokodetector_backend.repository import (
    RoundAnalysisRepository,
    StoredRoundAnalysis,
    create_database_engine,
    upgrade_database,
)

BACKEND_ROOT = Path(__file__).parents[1]
ANALYSIS_ID = UUID("00000000-0000-0000-0000-000000000032")
SESSION_ID = UUID("00000000-0000-0000-0000-000000000033")


def stored_analysis(*, state: str = "queued") -> StoredRoundAnalysis:
    created_at = datetime(2026, 8, 30, tzinfo=timezone.utc)
    return StoredRoundAnalysis(
        analysis_id=ANALYSIS_ID,
        recording_id="recording-0032",
        round_id="round-0032",
        session_id=SESSION_ID,
        request_json='{"analysis_id":"00000000-0000-0000-0000-000000000032"}',
        request_sha256="0" * 64,
        state=state,
        total_evidence_packages=2,
        completed_evidence_packages=0,
        result_status=None,
        result_json=None,
        error=None,
        input_artifact_id=None,
        input_artifact_sha256=None,
        result_artifact_id=None,
        result_artifact_sha256=None,
        created_at=created_at,
        started_at=None,
        completed_at=None,
    )


def test_round_analysis_rows_support_lifecycle_and_restart_conversion(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'analysis.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    repository = RoundAnalysisRepository(create_database_engine(database_url))
    analysis = stored_analysis()

    inserted, created = repository.insert(analysis)
    replayed, replay_created = repository.insert(analysis)
    repository.update_progress(ANALYSIS_ID, state="analyzing_evidence", completed=1)
    converted = repository.fail_non_terminal(
        now=datetime(2026, 8, 30, 1, 2, 3, tzinfo=timezone.utc)
    )

    assert created is True
    assert replay_created is False
    assert inserted == analysis
    assert replayed == analysis
    assert converted == 1
    stored = repository.get(ANALYSIS_ID)
    assert stored is not None
    assert stored.state == "failed"
    assert stored.error == "The analysis did not finish before the backend restarted."
    assert stored.completed_at == datetime(2026, 8, 30, 1, 2, 3, tzinfo=timezone.utc)


def test_restart_conversion_leaves_terminal_rows_unchanged(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'analysis.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    repository = RoundAnalysisRepository(create_database_engine(database_url))
    complete = stored_analysis(state="complete")
    repository.insert(complete)

    assert repository.fail_non_terminal() == 0
    assert repository.get(ANALYSIS_ID) == complete


def test_migration_creates_round_analyses_table(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'analysis.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    engine = create_database_engine(database_url)

    with engine.connect() as connection:
        assert connection.scalar(select(1)) == 1
        assert engine.dialect.has_table(connection, "round_analyses")
