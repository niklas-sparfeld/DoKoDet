"""The recording row carries identity and selected-data metadata only."""

from datetime import UTC, datetime

from dokodetector_backend.recordings_api import (
    RecordingListResponse,
    RecordingSelectionSummary,
    RecordingSummary,
)


def test_recording_row_does_not_expose_process_history() -> None:
    selections = [
        RecordingSelectionSummary(
            content_type=content_type,
            state="not-selected",
            selected_generated=None,
            selected_completed_reference=None,
        )
        for content_type in (
            "events",
            "visible_cards",
            "virtual_scenes",
            "card_scene_proposals",
            "visual_identities",
            "table_observations",
        )
    ]
    row = RecordingSummary(
        recording_id="recording-growth",
        source_asset_id="source-growth",
        video_id="video-growth",
        session_id="session-growth",
        display_name="round.mov",
        received_at=datetime(2026, 11, 10, tzinfo=UTC),
        thumbnail_url="/v1/repository-bundles/recording-growth/thumbnail",
        metadata_state="available",
        selections=selections,
    )

    response = RecordingListResponse(recordings=[row]).model_dump(mode="json")
    payload = response["recordings"][0]
    assert set(payload) == {
        "recording_id",
        "source_asset_id",
        "video_id",
        "session_id",
        "display_name",
        "received_at",
        "thumbnail_url",
        "metadata_state",
        "selections",
    }
    assert len(payload["selections"]) == 6
