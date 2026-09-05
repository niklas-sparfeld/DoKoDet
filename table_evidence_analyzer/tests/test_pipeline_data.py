from __future__ import annotations

import pytest

from table_evidence_analyzer.pipeline_data import (
    PipelineDataError,
    VisibleCardData,
    canonical_visible_card_data_bytes,
    parse_visible_card_data_bytes,
)


def _frame() -> dict[str, object]:
    return {
        "schema_version": "exact-event/v1",
        "source_video_sha256": "a" * 64,
        "requested_time_us": 500_000,
        "frame_index": 1,
        "presentation_timestamp_us": 500_000,
        "width": 64,
        "height": 64,
        "decoder_version": "ffmpeg/test",
        "transform_version": "ffmpeg-mjpeg/test",
        "output_encoding": "jpeg",
        "content_type": "image/jpeg",
        "image_sha256": "b" * 64,
        "policy": "exact-event/v1",
    }


def _content() -> dict[str, object]:
    return {
        "schema_version": "visible-card-data/v1",
        "outcomes": [
            {
                "event_id": "event-1",
                "frame_identity": _frame(),
                "status": "detected",
                "candidates": [
                    {
                        "card_id": "run-1-event-1-card-0",
                        "geometry": {
                            "kind": "detector-box/v1",
                            "box_2d": {"x_min": 100, "y_min": 200, "x_max": 700, "y_max": 800},
                        },
                        "normalization": {
                            "width": 64,
                            "height": 64,
                            "policy_id": "full-frame-0-1000/v1",
                        },
                        "model_scores": [{"producer_id": "detector.v1", "score": 0.8}],
                    }
                ],
                "error": None,
            },
            {
                "event_id": "event-2",
                "frame_identity": _frame(),
                "status": "empty",
                "candidates": [],
                "error": None,
            },
            {
                "event_id": "event-3",
                "frame_identity": None,
                "status": "failed",
                "candidates": [],
                "error": "exact event frame is unavailable",
            },
        ],
    }


def test_visible_card_data_round_trips_to_canonical_bytes() -> None:
    content = VisibleCardData.from_mapping(_content())
    raw = canonical_visible_card_data_bytes(content)

    assert parse_visible_card_data_bytes(raw) == content
    assert raw == canonical_visible_card_data_bytes(parse_visible_card_data_bytes(raw))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["outcomes"][0].update(status="empty"),
        lambda value: value["outcomes"][0]["candidates"][0]["geometry"].update(
            kind="reviewed-visible-region/v1"
        ),
        lambda value: value["outcomes"][2].update(error=None),
        lambda value: value["outcomes"][0].update(unexpected=True),
    ],
)
def test_visible_card_data_rejects_invalid_outcomes(mutate) -> None:
    value = _content()
    mutate(value)

    with pytest.raises(PipelineDataError):
        VisibleCardData.from_mapping(value)
