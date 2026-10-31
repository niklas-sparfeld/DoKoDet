from __future__ import annotations

import pytest
from doko_operations.pipeline_reference import ReferenceDraftItem

from dokodetector_backend.pipeline_reference_errors import PipelineReferenceInputError
from dokodetector_backend.visible_card_reference_coverage import (
    frame_coverage_entries,
    frame_coverage_key,
    item_frame_key,
)

FRAME = {
    "schema_version": "exact-event/v1",
    "source_video_sha256": "a" * 64,
    "requested_time_us": 1_000_000,
    "frame_index": 2,
    "presentation_timestamp_us": 1_000_000,
    "width": 100,
    "height": 100,
    "decoder_version": "decoder.v1",
    "transform_version": "transform.v1",
    "output_encoding": "png",
    "content_type": "image/png",
    "image_sha256": "b" * 64,
    "policy": "exact-event/v1",
}


def test_resolved_coverage_normalizes_frame_and_matches_item() -> None:
    entries = frame_coverage_entries([{"frame_identity": FRAME, "decision": "cards"}])
    item = ReferenceDraftItem(
        item_id="event-01",
        base_item_id="event-01",
        review_state="accepted",
        item={"frame_identity": FRAME},
    )

    assert entries[0]["frame_identity"] == FRAME
    assert frame_coverage_key(entries[0]) == item_frame_key(item)


def test_unresolved_coverage_uses_item_key() -> None:
    entries = frame_coverage_entries(
        [{"item_id": "event-02", "frame_identity": None, "decision": "unusable"}]
    )
    item = ReferenceDraftItem(
        item_id="event-02",
        base_item_id=None,
        review_state="unusable",
        item={"frame_identity": None},
    )

    assert frame_coverage_key(entries[0]) == "item:event-02"
    assert item_frame_key(item) == "item:event-02"


def test_duplicate_normalized_frame_coverage_is_rejected() -> None:
    duplicate = {"frame_identity": FRAME, "decision": "cards"}

    with pytest.raises(PipelineReferenceInputError, match="unique frames"):
        frame_coverage_entries([duplicate, duplicate])


def test_invalid_frame_identity_is_reported_as_reference_input_error() -> None:
    with pytest.raises(PipelineReferenceInputError, match="frame_identity is invalid"):
        frame_coverage_entries(
            [{"frame_identity": {"schema_version": "wrong"}, "decision": "cards"}]
        )
