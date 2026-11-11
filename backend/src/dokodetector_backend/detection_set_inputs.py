"""Resolve exact saved detection-set inputs for pipeline consumers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from table_evidence_analyzer.pipeline_data import VisibleCardData

from dokodetector_backend.detection_set_store import DetectionSetError, DetectionSetStore


def resolve_detection_set(
    store: DetectionSetStore,
    recording_id: str,
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Load one exact recording-owned detection set and reject stale references."""

    if not isinstance(reference, Mapping) or set(reference) != {
        "set_id",
        "version",
        "content_sha256",
    }:
        raise DetectionSetError("detection-set reference must identify set, version, and digest")
    result = store.get(recording_id, reference["set_id"], reference["version"])
    if result is None:
        raise DetectionSetError("the exact detection-set version is unavailable")
    if result["content_sha256"] != reference["content_sha256"]:
        raise DetectionSetError("the detection-set content digest does not match")
    if result["recording_id"] != recording_id:
        raise DetectionSetError("the detection set belongs to another recording")
    return result


def detection_set_to_local_result(
    detection_set: Mapping[str, Any], *, recording_id: str, source_revision: str
) -> dict[str, Any]:
    """Convert visible-card detections to the existing scene algorithm input in memory."""

    content = detection_set["content"]
    frames: list[dict[str, Any]] = []
    for frame in content["frames"]:
        identity = frame["frame_identity"]
        predictions: list[dict[str, Any]] = []
        for detection in frame["detections"]:
            if detection["kind"] != "visible_card":
                raise DetectionSetError(
                    f"scene proposal cannot represent {detection['kind']} detection geometry"
                )
            polygons = [segment["polygon"] for segment in detection["segments"]]
            if not polygons:
                raise DetectionSetError("scene proposal needs visible-card polygons")
            predictions.append(
                {
                    "candidate_id": detection["object_id"],
                    "confidence": 1.0,
                    "confidence_available": False,
                    "polygons": polygons,
                    "side": detection["side"],
                }
            )
        frames.append(
            {
                "frame_id": frame["frame_id"],
                "source_frame_digest": identity["image_sha256"],
                "frame_index": identity["frame_index"],
                "timestamp_us": identity["requested_time_us"],
                "width": identity["width"],
                "height": identity["height"],
                "source_transform": identity["transform_version"],
                "predictions": predictions,
                "outcome_status": "detected" if predictions else "empty",
                "source_identity": identity,
                "pile_regions": [],
            }
        )
    if not frames:
        raise DetectionSetError("the detection set has no examined frames")
    return {
        "recording_id": recording_id,
        "source_revision": source_revision,
        "frames": frames,
        "unresolvable_frames": [],
    }


def detection_set_to_visible_card_data(
    detection_set: Mapping[str, Any], *, expected_event_ids: set[str] | None = None
) -> VisibleCardData:
    """Adapt exactly representable card geometry for existing event consumers."""

    frames = detection_set["content"]["frames"]
    outcomes: list[dict[str, Any]] = []
    for frame in frames:
        identity = frame["frame_identity"]
        event_ids = [item["event_id"] for item in frame["event_ids"]]
        if not event_ids:
            raise DetectionSetError(
                f"frame {frame['frame_id']} has no event reference for this consumer"
            )
        detections = frame["detections"]
        if any(item["kind"] != "visible_card" for item in detections):
            raise DetectionSetError(
                f"frame {frame['frame_id']} contains geometry this consumer cannot represent"
            )
        candidates = []
        for detection in detections:
            polygons = []
            for segment in detection["segments"]:
                points = []
                for point in segment["polygon"]:
                    x = round(point["x"] * 1000 / identity["width"])
                    y = round(point["y"] * 1000 / identity["height"])
                    if (
                        round(x * identity["width"] / 1000) != point["x"]
                        or round(y * identity["height"] / 1000) != point["y"]
                    ):
                        raise DetectionSetError(
                            f"frame {frame['frame_id']} geometry precision exceeds this consumer"
                        )
                    points.append({"x": x, "y": y})
                polygons.append(points)
            candidates.append(
                {
                    "card_id": detection["object_id"],
                    "geometry": {
                        "kind": "visible-region/v1",
                        "visible_region": {"polygons": polygons},
                    },
                    "normalization": {
                        "width": identity["width"],
                        "height": identity["height"],
                        "policy_id": "detection-set-pixel-adapter/v1",
                    },
                    "side": detection["side"],
                }
            )
        for event_id in event_ids:
            outcomes.append(
                {
                    "event_id": event_id,
                    "frame_identity": identity,
                    "status": "detected" if candidates else "empty",
                    "candidates": candidates,
                    "ignored_regions": [],
                    "error": None,
                    "pile_regions": [],
                    "pile_detection_status": "unsupported",
                }
            )
    if expected_event_ids is not None:
        observed_event_ids = {item["event_id"] for item in outcomes}
        for event_id in sorted(expected_event_ids - observed_event_ids):
            outcomes.append(
                {
                    "event_id": event_id,
                    "frame_identity": None,
                    "status": "failed",
                    "candidates": [],
                    "ignored_regions": [],
                    "error": "the exact detection set has no examined frame for this event",
                }
            )
    return VisibleCardData.from_mapping(
        {"schema_version": "visible-card-data/v2", "outcomes": outcomes}
    )
