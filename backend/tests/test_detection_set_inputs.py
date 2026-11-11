from __future__ import annotations

import pytest

from dokodetector_backend.detection_set_inputs import detection_set_to_visible_card_data
from dokodetector_backend.detection_set_store import DetectionSetError


def _set(width: int = 1000) -> dict:
    return {
        "content": {
            "frames": [
                {
                    "frame_id": "frame-a",
                    "frame_identity": {
                        "schema_version": "exact-event/v1",
                        "source_video_sha256": "a" * 64,
                        "requested_time_us": 100,
                        "frame_index": 0,
                        "presentation_timestamp_us": 100,
                        "width": width,
                        "height": 1000,
                        "decoder_version": "fixture/1",
                        "transform_version": "identity/1",
                        "output_encoding": "jpeg",
                        "content_type": "image/jpeg",
                        "image_sha256": "b" * 64,
                        "policy": "exact-event/v1",
                    },
                    "event_ids": [{"set_id": "events", "version": "1", "event_id": "event-a"}],
                    "detections": [
                        {
                            "object_id": "card-a",
                            "kind": "visible_card",
                            "side": "face_up",
                            "segments": [
                                {
                                    "segment_id": "segment-a",
                                    "polygon": [
                                        {"x": 101, "y": 100},
                                        {"x": 201, "y": 100},
                                        {"x": 201, "y": 250},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }


def test_adapter_preserves_exact_event_frame_object_and_polygon_pixels() -> None:
    result = detection_set_to_visible_card_data(_set())

    outcome = result.outcomes[0]
    assert outcome.event_id == "event-a"
    assert outcome.frame_identity.frame_index == 0
    assert outcome.candidates[0].card_id == "card-a"
    assert outcome.candidates[0].geometry.to_mapping()["visible_region"]["polygons"] == [
        [{"x": 101, "y": 100}, {"x": 201, "y": 100}, {"x": 201, "y": 250}]
    ]


def test_adapter_rejects_pixel_precision_that_existing_geometry_cannot_represent() -> None:
    with pytest.raises(DetectionSetError, match="precision"):
        detection_set_to_visible_card_data(_set(width=1920))
