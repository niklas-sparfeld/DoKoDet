"""Frozen recordings list contract and current growth baseline."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from dokodetector_backend.recordings_api import (
    RecordingAnalysisSummary,
    RecordingListResponse,
    RecordingPipelineStatusSummary,
    RecordingSummary,
)

RECORDING_ID = "catalog-growth-recording"
ANALYSIS_ID = UUID("550e8400-e29b-41d4-a716-446655440001")
PACKAGE_ID = UUID("550e8400-e29b-41d4-a716-446655440002")
STAGE_KEYS = (
    "events",
    "visible_cards",
    "visual_identities",
    "table_observations",
    "round_analyses",
)


def _recording(*, analyses: int, packages: int) -> RecordingSummary:
    now = datetime(2026, 11, 10, tzinfo=UTC)
    latest = RecordingAnalysisSummary(
        analysis_id=ANALYSIS_ID,
        recording_id=RECORDING_ID,
        round_id="round-growth",
        state="queued",
        total_evidence_packages=10,
        completed_evidence_packages=0,
        result_status=None,
        error=None,
        created_at=now,
        started_at=None,
        completed_at=None,
    )
    stages = [
        {"key": key, "state": "empty" if key != "events" else "active-run"} for key in STAGE_KEYS
    ]
    return RecordingSummary(
        recording_id=RECORDING_ID,
        source_asset_id="source-growth",
        video_id="video-growth",
        session_id="session-growth",
        state="accepted",
        source_sha256="0" * 64,
        received_at=now,
        round_id="round-growth",
        evidence_package_ids=[PACKAGE_ID] * packages,
        analyses=[latest] * analyses,
        pipeline_status=RecordingPipelineStatusSummary(
            schema_version="recording-pipeline-status/v1",
            stages=stages,
        ),
        can_start_analysis=False,
        analysis_blocker=(
            "No selected table observations or linked evidence packages are available."
        ),
    )


def test_recordings_list_keeps_order_status_and_blocker_contract() -> None:
    response = RecordingListResponse(recordings=[_recording(analyses=1, packages=1)])
    row = response.recordings[0]

    assert [stage.key for stage in row.pipeline_status.stages] == list(STAGE_KEYS)
    assert row.pipeline_status.stages[0].state == "active-run"
    assert row.can_start_analysis is False
    assert row.analysis_blocker is not None
    assert response.model_dump(mode="json")["recordings"][0]["recording_id"] == RECORDING_ID


@pytest.mark.xfail(
    strict=True,
    reason="M0 baseline: the current list embeds full analysis and package histories.",
)
def test_recordings_list_payload_stays_bounded_when_history_grows_tenfold() -> None:
    small = RecordingListResponse(recordings=[_recording(analyses=1, packages=1)])
    large = RecordingListResponse(recordings=[_recording(analyses=10, packages=10)])

    assert len(large.model_dump_json()) <= len(small.model_dump_json()) * 2
