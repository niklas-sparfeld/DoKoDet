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
                            "kind": "visible-region/v1",
                            "visible_region": {
                                "polygons": [
                                    [
                                        {"x": 100, "y": 200},
                                        {"x": 700, "y": 200},
                                        {"x": 700, "y": 800},
                                        {"x": 100, "y": 800},
                                    ]
                                ]
                            },
                        },
                        "normalization": {
                            "width": 64,
                            "height": 64,
                            "policy_id": "full-frame-0-1000/v1",
                        },
                        "side": "face_up",
                        "model_scores": [{"producer_id": "detector.v1", "score": 0.8}],
                    }
                ],
                "ignored_regions": [],
                "error": None,
            },
            {
                "event_id": "event-2",
                "frame_identity": _frame(),
                "status": "empty",
                "candidates": [],
                "ignored_regions": [],
                "error": None,
            },
            {
                "event_id": "event-3",
                "frame_identity": None,
                "status": "failed",
                "candidates": [],
                "ignored_regions": [],
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
            kind="unsupported/v1"
        ),
        lambda value: value["outcomes"][0]["candidates"][0].pop("side"),
        lambda value: value["outcomes"][2].update(error=None),
        lambda value: value["outcomes"][0].update(unexpected=True),
    ],
)
def test_visible_card_data_rejects_invalid_outcomes(mutate) -> None:
    value = _content()
    mutate(value)

    with pytest.raises(PipelineDataError):
        VisibleCardData.from_mapping(value)


def _ignore_region() -> dict[str, object]:
    return {
        "region_id": "ignore-region-001",
        "geometry": {
            "kind": "reviewed-ignore-region/v1",
            "polygons": [
                [
                    {"x": 100, "y": 100},
                    {"x": 400, "y": 100},
                    {"x": 400, "y": 400},
                    {"x": 100, "y": 400},
                ],
                [
                    {"x": 600, "y": 200},
                    {"x": 800, "y": 200},
                    {"x": 700, "y": 500},
                ],
            ],
        },
        "normalization": {
            "width": 64,
            "height": 64,
            "policy_id": "full-frame-0-1000/v1",
        },
        "reason": "untidy_stack",
        "source_candidates": [
            {"revision_id": "visible-cards-run-001", "card_id": "generated-card-003"}
        ],
    }


def test_visible_card_data_supports_mixed_and_ignore_only_detected_frames() -> None:
    value = _content()
    value["outcomes"][0]["ignored_regions"] = [_ignore_region()]
    value["outcomes"][1] = {
        "event_id": "event-ignore-only",
        "frame_identity": _frame(),
        "status": "detected",
        "candidates": [],
        "ignored_regions": [_ignore_region()],
        "error": None,
    }

    parsed = VisibleCardData.from_mapping(value)
    raw = canonical_visible_card_data_bytes(parsed)

    assert len(parsed.outcomes[0].ignored_regions) == 1
    assert parsed.outcomes[1].candidates == ()
    assert parsed.outcomes[1].status == "detected"
    assert parse_visible_card_data_bytes(raw) == parsed
    assert b"reviewed-ignore-region/v1" in raw
    assert b"visible-cards-run-001" in raw


def test_visible_card_ignore_region_allows_manual_regions_without_source_candidates() -> None:
    value = _content()
    region = _ignore_region()
    region["source_candidates"] = []
    value["outcomes"][0]["ignored_regions"] = [region]

    parsed = VisibleCardData.from_mapping(value)

    assert parsed.outcomes[0].ignored_regions[0].source_candidates == ()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["outcomes"][0].pop("ignored_regions"),
        lambda value: value["outcomes"][0]["ignored_regions"].append(_ignore_region()),
        lambda value: value["outcomes"][0]["ignored_regions"][0].update(
            region_id="run-1-event-1-card-0"
        ),
        lambda value: value["outcomes"][0]["ignored_regions"][0]["geometry"].update(polygons=[]),
        lambda value: value["outcomes"][0]["ignored_regions"][0]["geometry"]["polygons"][0][
            0
        ].update(x=1001),
        lambda value: value["outcomes"][0]["ignored_regions"][0]["source_candidates"].append(
            {"revision_id": "visible-cards-run-001", "card_id": "generated-card-003"}
        ),
        lambda value: value["outcomes"][0]["ignored_regions"][0].update(reason="untidy_stack/v2"),
        lambda value: value["outcomes"][0].update(status="empty"),
        lambda value: value["outcomes"][0].update(status="failed", error="failed"),
    ],
)
def test_visible_card_data_rejects_invalid_ignore_region_state(mutate) -> None:
    value = _content()
    value["outcomes"][0]["ignored_regions"] = [_ignore_region()]
    mutate(value)

    with pytest.raises(PipelineDataError):
        VisibleCardData.from_mapping(value)


def test_visible_card_data_rejects_duplicate_json_fields() -> None:
    raw = canonical_visible_card_data_bytes(_content()).replace(
        b'"ignored_regions":[],"status"',
        b'"ignored_regions":[],"ignored_regions":[],"status"',
    )

    with pytest.raises(PipelineDataError, match="duplicate field"):
        parse_visible_card_data_bytes(raw)
