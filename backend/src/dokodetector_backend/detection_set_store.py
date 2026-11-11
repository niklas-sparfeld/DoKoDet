"""Concrete immutable visual detection sets stored under recording folders."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from table_evidence_analyzer.pipeline_data import VisibleCardFrameIdentity

from dokodetector_backend.event_set_store import EventSetStore
from dokodetector_backend.filesystem import contained_path
from dokodetector_backend.recording_folder_store import RecordingFolderStore

SCHEMA = "detection-set/v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class DetectionSetError(ValueError):
    """A detection set is invalid or cannot be safely stored."""


class DetectionSetStore:
    """Save immutable concrete detection-set versions and reopen exact versions."""

    def __init__(self, recordings: RecordingFolderStore, events: EventSetStore) -> None:
        self.recordings = recordings
        self.events = events

    def save(
        self,
        recording_id: str,
        *,
        set_id: str,
        version: str,
        origin: str,
        source: dict[str, Any],
        producer: dict[str, Any],
        event_sets: list[dict[str, str]],
        frames: list[dict[str, Any]],
    ) -> dict[str, Any]:
        set_id = _identifier(set_id, "set ID")
        version = _identifier(version, "version")
        root = self.recordings.get(recording_id)
        if root is None:
            raise DetectionSetError("recording does not exist")
        if not isinstance(origin, str) or origin not in {"processor", "manual", "corrected"}:
            raise DetectionSetError("origin is invalid")
        if (
            not isinstance(source, dict)
            or source.get("source_video_sha256") != root.media["sha256"]
        ):
            raise DetectionSetError("source does not match the recording video")
        if not isinstance(producer, dict):
            raise DetectionSetError("producer facts must be an object")
        checked_events = _validate_event_sets(event_sets, self.events, recording_id)
        event_ids = {
            (reference["set_id"], reference["version"]): set(
                item["event_id"]
                for item in self.events.get(
                    recording_id, reference["set_id"], reference["version"]
                )["content"]["events"]
            )
            for reference in checked_events
        }
        checked_frames = _validate_frames(frames, root.media["sha256"], checked_events, event_ids)
        base = contained_path(
            self.recordings.recording_path(recording_id) / "detection-sets", set_id
        )
        destination = contained_path(base / "versions", version)
        if destination.exists() or destination.is_symlink():
            raise DetectionSetError("detection-set version already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".detection-set-", dir=destination.parent))
        try:
            metadata = {
                "schema_version": SCHEMA,
                "recording_id": recording_id,
                "set_id": set_id,
                "version": version,
                "origin": origin,
                "source": source,
                "producer": producer,
                "event_sets": checked_events,
                "frames": [frame["frame_id"] for frame in checked_frames],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            (staging / "detection-set.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            for frame in checked_frames:
                frame_dir = staging / "frames" / frame["frame_id"]
                frame_dir.mkdir(parents=True)
                detections_dir = frame_dir / "detections"
                detections_dir.mkdir()
                detection_ids = []
                for detection in frame["detections"]:
                    detection_ids.append(detection["object_id"])
                    detection_dir = detections_dir / detection["object_id"]
                    detection_dir.mkdir()
                    segment_dir = detection_dir / "segments"
                    segment_dir.mkdir()
                    detection_metadata = {
                        key: detection[key] for key in ("object_id", "kind", "side")
                    }
                    detection_metadata["segments"] = [
                        segment["segment_id"] for segment in detection["segments"]
                    ]
                    _write_json(detection_dir / "detection.json", detection_metadata)
                    for segment in detection["segments"]:
                        _write_json(
                            segment_dir / f"{segment['segment_id']}.json",
                            segment,
                        )
                _write_json(
                    frame_dir / "frame.json",
                    {
                        "frame_id": frame["frame_id"],
                        "frame_identity": frame["frame_identity"],
                        "event_ids": frame["event_ids"],
                        "detections": detection_ids,
                    },
                )
            for path in staging.rglob("*"):
                if path.is_file():
                    with path.open("rb") as handle:
                        os.fsync(handle.fileno())
            directories = sorted(
                (path for path in staging.rglob("*") if path.is_dir()),
                key=lambda item: len(item.parts),
                reverse=True,
            )
            for directory in [*directories, staging]:
                _fsync_directory(directory)
            os.rename(staging, destination)
            _fsync_directory(destination.parent)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        result = self.get(recording_id, set_id, version)
        if result is None:
            raise DetectionSetError("published detection set failed validation")
        return result

    def get(self, recording_id: str, set_id: str, version: str) -> dict[str, Any] | None:
        try:
            set_id = _identifier(set_id, "set ID")
            version = _identifier(version, "version")
            folder = contained_path(
                self.recordings.recording_path(recording_id)
                / "detection-sets"
                / set_id
                / "versions",
                version,
            )
            if folder.is_symlink() or not folder.is_dir():
                return None
            metadata = json.loads((folder / "detection-set.json").read_text(encoding="utf-8"))
            if (
                not isinstance(metadata, dict)
                or set(metadata)
                != {
                    "schema_version",
                    "recording_id",
                    "set_id",
                    "version",
                    "origin",
                    "source",
                    "producer",
                    "event_sets",
                    "frames",
                    "created_at",
                }
                or metadata["schema_version"] != SCHEMA
                or metadata["recording_id"] != recording_id
                or metadata["set_id"] != set_id
                or metadata["version"] != version
            ):
                return None
            frames = []
            for frame_id in metadata["frames"]:
                frame_dir = contained_path(folder / "frames", frame_id)
                if frame_dir.is_symlink() or not frame_dir.is_dir():
                    return None
                frame_metadata_path = frame_dir / "frame.json"
                if frame_metadata_path.is_symlink():
                    return None
                frame_metadata = json.loads(frame_metadata_path.read_text(encoding="utf-8"))
                if (
                    not isinstance(frame_metadata, dict)
                    or set(frame_metadata)
                    != {"frame_id", "frame_identity", "event_ids", "detections"}
                    or frame_metadata["frame_id"] != frame_id
                    or not isinstance(frame_metadata["detections"], list)
                ):
                    return None
                detections = []
                for detection_id in frame_metadata["detections"]:
                    _identifier(detection_id, "object ID")
                    detection_dir = contained_path(frame_dir / "detections", detection_id)
                    detection_path = detection_dir / "detection.json"
                    if (
                        detection_dir.is_symlink()
                        or not detection_dir.is_dir()
                        or detection_path.is_symlink()
                    ):
                        return None
                    detection = json.loads(detection_path.read_text(encoding="utf-8"))
                    if (
                        not isinstance(detection, dict)
                        or set(detection) != {"object_id", "kind", "side", "segments"}
                        or detection["object_id"] != detection_id
                        or not isinstance(detection["segments"], list)
                    ):
                        return None
                    segments = []
                    for segment_id in detection["segments"]:
                        _identifier(segment_id, "segment ID")
                        segment_path = contained_path(
                            detection_dir / "segments", f"{segment_id}.json"
                        )
                        if segment_path.is_symlink():
                            return None
                        segment = json.loads(segment_path.read_text(encoding="utf-8"))
                        if (
                            not isinstance(segment, dict)
                            or set(segment) != {"segment_id", "polygon"}
                            or segment["segment_id"] != segment_id
                        ):
                            return None
                        segments.append(segment)
                    detections.append({**detection, "segments": segments})
                frames.append(
                    {
                        "frame_id": frame_id,
                        "frame_identity": frame_metadata["frame_identity"],
                        "event_ids": frame_metadata["event_ids"],
                        "detections": detections,
                    }
                )
            content = {"schema_version": SCHEMA, "frames": frames}
            digest = hashlib.sha256(
                json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            ).hexdigest()
            return {**metadata, "content": content, "content_sha256": digest}
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            return None


def _validate_event_sets(
    references: list[dict[str, str]], events: EventSetStore, recording_id: str
) -> list[dict[str, str]]:
    if not isinstance(references, list):
        raise DetectionSetError("event-set references must be a list")
    result = []
    seen = set()
    for reference in references:
        if not isinstance(reference, dict) or set(reference) != {
            "set_id",
            "version",
            "content_sha256",
        }:
            raise DetectionSetError("event-set reference needs set_id, version and content_sha256")
        _identifier(reference["set_id"], "event-set ID")
        _identifier(reference["version"], "event-set version")
        digest = reference["content_sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise DetectionSetError("event-set content digest must be a lower-case SHA-256")
        saved = events.get(recording_id, reference["set_id"], reference["version"])
        if saved is None or saved["content_sha256"] != reference["content_sha256"]:
            raise DetectionSetError("event-set reference is unavailable or has a mismatched digest")
        key = (reference["set_id"], reference["version"])
        if key in seen:
            raise DetectionSetError("event-set references must be unique")
        seen.add(key)
        result.append(dict(reference))
    return result


def _validate_frames(
    frames: list[dict[str, Any]],
    source_sha256: str,
    event_sets: list[dict[str, str]],
    event_ids: dict[tuple[str, str], set[str]],
) -> list[dict[str, Any]]:
    if not isinstance(frames, list) or not frames:
        raise DetectionSetError("at least one examined frame is required")
    allowed_refs = {(item["set_id"], item["version"]) for item in event_sets}
    result = []
    frame_ids = set()
    for raw in frames:
        if not isinstance(raw, dict) or set(raw) != {
            "frame_id",
            "frame_identity",
            "event_ids",
            "detections",
        }:
            raise DetectionSetError("frame fields are invalid")
        frame_id = _identifier(raw["frame_id"], "frame ID")
        if frame_id in frame_ids:
            raise DetectionSetError("frame IDs must be unique")
        frame_ids.add(frame_id)
        identity = VisibleCardFrameIdentity.from_mapping(raw["frame_identity"])
        if identity.source_video_sha256 != source_sha256:
            raise DetectionSetError("frame source does not match recording video")
        event_ids_in_frame = raw["event_ids"]
        if not isinstance(event_ids_in_frame, list):
            raise DetectionSetError("frame event IDs must be a unique list")
        event_keys = [
            (item.get("set_id"), item.get("version"), item.get("event_id"))
            if isinstance(item, dict)
            else None
            for item in event_ids_in_frame
        ]
        if any(
            not isinstance(value, str) for key in event_keys if key is not None for value in key
        ):
            raise DetectionSetError("frame event references must use text identifiers")
        if len(event_keys) != len(set(event_keys)):
            raise DetectionSetError("frame event IDs must be a unique list")
        for item in event_ids_in_frame:
            if not isinstance(item, dict) or set(item) != {"set_id", "version", "event_id"}:
                raise DetectionSetError("frame event reference fields are invalid")
            key = (item["set_id"], item["version"])
            if key not in allowed_refs or item["event_id"] not in event_ids[key]:
                raise DetectionSetError("frame event reference is unavailable")
        detections = raw["detections"]
        if not isinstance(detections, list):
            raise DetectionSetError("detections must be a list")
        ids = set()
        clean_detections = []
        for detection in detections:
            if not isinstance(detection, dict) or set(detection) != {
                "object_id",
                "kind",
                "side",
                "segments",
            }:
                raise DetectionSetError("detection fields are invalid")
            object_id = _identifier(detection["object_id"], "object ID")
            if object_id in ids:
                raise DetectionSetError("object IDs must be unique within a frame")
            ids.add(object_id)
            kind, side = detection["kind"], detection["side"]
            if not isinstance(kind, str) or kind not in {"visible_card", "pile", "ignore"}:
                raise DetectionSetError("detection kind is invalid")
            if kind == "visible_card" and (
                not isinstance(side, str) or side not in {"face_up", "face_down", "unknown"}
            ):
                raise DetectionSetError("card side must apply only to visible cards")
            if kind != "visible_card" and side is not None:
                raise DetectionSetError("card side must apply only to visible cards")
            segments = detection["segments"]
            if not isinstance(segments, list) or not segments:
                raise DetectionSetError("each detection needs at least one segment")
            segment_ids = set()
            clean_segments = []
            for segment in segments:
                if not isinstance(segment, dict) or set(segment) != {"segment_id", "polygon"}:
                    raise DetectionSetError("segment fields are invalid")
                segment_id = _identifier(segment["segment_id"], "segment ID")
                if segment_id in segment_ids:
                    raise DetectionSetError("segment IDs must be unique within an object")
                segment_ids.add(segment_id)
                polygon = segment["polygon"]
                if not isinstance(polygon, list) or len(polygon) < 3:
                    raise DetectionSetError("polygon needs at least three points")
                points = []
                for point in polygon:
                    if not isinstance(point, dict) or set(point) != {"x", "y"}:
                        raise DetectionSetError("polygon points need x and y")
                    x, y = point["x"], point["y"]
                    if any(isinstance(v, bool) or not isinstance(v, int) for v in (x, y)) or not (
                        0 <= x <= identity.width and 0 <= y <= identity.height
                    ):
                        raise DetectionSetError("polygon point is outside source frame")
                    points.append((x, y))
                area = sum(
                    points[i][0] * points[(i + 1) % len(points)][1]
                    - points[(i + 1) % len(points)][0] * points[i][1]
                    for i in range(len(points))
                )
                if area == 0:
                    raise DetectionSetError("polygon must have non-zero area")
                if not _polygon_is_simple(points):
                    raise DetectionSetError("polygon must not self-intersect")
                clean_segments.append({"segment_id": segment_id, "polygon": polygon})
            clean_detections.append(
                {"object_id": object_id, "kind": kind, "side": side, "segments": clean_segments}
            )
        result.append(
            {
                "frame_id": frame_id,
                "frame_identity": identity.to_mapping(),
                "event_ids": event_ids_in_frame,
                "detections": clean_detections,
            }
        )
    return result


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise DetectionSetError(f"{field} must be a safe identifier")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _polygon_is_simple(points: list[tuple[int, int]]) -> bool:
    """Reject intersections between non-adjacent polygon edges."""
    count = len(points)
    for first in range(count):
        a, b = points[first], points[(first + 1) % count]
        for second in range(first + 1, count):
            if second == first + 1 or (first == 0 and second == count - 1):
                continue
            c, d = points[second], points[(second + 1) % count]
            if _segments_intersect(a, b, c, d):
                return False
    return True


def _segments_intersect(
    a: tuple[int, int], b: tuple[int, int], c: tuple[int, int], d: tuple[int, int]
) -> bool:
    def orientation(p: tuple[int, int], q: tuple[int, int], r: tuple[int, int]) -> int:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_segment(p: tuple[int, int], q: tuple[int, int], r: tuple[int, int]) -> bool:
        return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(
            p[1], r[1]
        )

    first = orientation(a, b, c)
    second = orientation(a, b, d)
    third = orientation(c, d, a)
    fourth = orientation(c, d, b)
    if first == 0 and on_segment(a, c, b):
        return True
    if second == 0 and on_segment(a, d, b):
        return True
    if third == 0 and on_segment(c, a, d):
        return True
    if fourth == 0 and on_segment(c, b, d):
        return True
    return first * second < 0 and third * fourth < 0


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
