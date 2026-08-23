from __future__ import annotations

import json
import math
import tempfile
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .video import VideoError, VideoMetadata, _import_cv2, read_video_metadata


class AnnotationError(ValueError):
    pass


EVENT_TYPES = frozenset(
    {
        "card_played",
        "trick_cleared",
        "card_moved",
        "card_removed",
        "card_returned",
        "multiple_cards_dropped",
        "anomalous_state_change",
    }
)
EVENT_CONFIDENCES = frozenset({"confirmed", "uncertain", "ignore", "proposed"})
DEFAULT_DUPLICATE_TOLERANCE_S = 0.01
ANNOTATION_SCHEMA_VERSION = "cardevent-annotation/v2"
EVENT_TYPE_SHORTCUTS = {
    ord("1"): "card_played",
    ord("2"): "trick_cleared",
    ord("3"): "card_moved",
    ord("4"): "card_removed",
    ord("5"): "card_returned",
    ord("6"): "multiple_cards_dropped",
    ord("7"): "anomalous_state_change",
}


def _require_mapping(data: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise AnnotationError(f"{context} must be a mapping.")
    return data


def _require_exact_keys(data: Mapping[str, Any], expected: Sequence[str], context: str) -> None:
    actual_keys = set(data)
    expected_keys = set(expected)
    missing_keys = expected_keys - actual_keys
    extra_keys = actual_keys - expected_keys
    if missing_keys or extra_keys:
        parts: list[str] = []
        if missing_keys:
            parts.append(f"missing keys: {', '.join(sorted(missing_keys))}")
        if extra_keys:
            parts.append(f"extra keys: {', '.join(sorted(extra_keys))}")
        raise AnnotationError(f"{context} has invalid keys ({'; '.join(parts)}).")


def _require_string(data: Mapping[str, Any], key: str) -> str:
    try:
        value = data[key]
    except KeyError as exc:
        raise AnnotationError(f"Missing required annotation key: {key}") from exc
    if not isinstance(value, str) or not value:
        raise AnnotationError(f"{key} must be a non-empty string.")
    return value


def _require_float(data: Mapping[str, Any], key: str, *, min_value: float | None = None) -> float:
    try:
        value = data[key]
    except KeyError as exc:
        raise AnnotationError(f"Missing required annotation key: {key}") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnnotationError(f"{key} must be a number.")
    result = float(value)
    if not math.isfinite(result):
        raise AnnotationError(f"{key} must be finite.")
    if min_value is not None and result < min_value:
        raise AnnotationError(f"{key} must be >= {min_value}.")
    return result


def _require_list(data: Mapping[str, Any], key: str) -> list[Any]:
    try:
        value = data[key]
    except KeyError as exc:
        raise AnnotationError(f"Missing required annotation key: {key}") from exc
    if not isinstance(value, list):
        raise AnnotationError(f"{key} must be a list.")
    return value


def _validate_sorted_events(events: Sequence["AnnotationEvent"]) -> None:
    for previous, current in zip(events, events[1:], strict=False):
        if current.time_s < previous.time_s:
            raise AnnotationError("events must be sorted by time before saving.")


@dataclass(frozen=True, slots=True)
class Roi:
    x: float
    y: float
    width: float
    height: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Roi":
        mapping = _require_mapping(data, "roi")
        _require_exact_keys(mapping, ("x", "y", "width", "height"), "roi")
        roi = cls(
            x=_require_float(mapping, "x"),
            y=_require_float(mapping, "y"),
            width=_require_float(mapping, "width"),
            height=_require_float(mapping, "height"),
        )
        roi.validate()
        return roi

    @classmethod
    def from_pixels(
        cls,
        x: int,
        y: int,
        width: int,
        height: int,
        frame_width: int,
        frame_height: int,
    ) -> "Roi":
        if frame_width <= 0 or frame_height <= 0:
            raise AnnotationError("frame size must be positive.")
        if x < 0 or y < 0:
            raise AnnotationError("roi origin must not be negative.")
        if width <= 0 or height <= 0:
            raise AnnotationError("roi width and height must be positive.")
        if x + width > frame_width or y + height > frame_height:
            raise AnnotationError("roi must fit inside the frame.")
        roi = cls(
            x=x / frame_width,
            y=y / frame_height,
            width=width / frame_width,
            height=height / frame_height,
        )
        roi.validate()
        return roi

    def validate(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if any(not math.isfinite(value) for value in values):
            raise AnnotationError("roi values must be finite.")
        if self.x < 0.0 or self.y < 0.0:
            raise AnnotationError("roi origin must be within the frame.")
        if self.width <= 0.0 or self.height <= 0.0:
            raise AnnotationError("roi width and height must be positive.")
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise AnnotationError("roi must fit inside the normalized frame.")

    def to_mapping(self) -> dict[str, float]:
        self.validate()
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }

    def to_pixels(self, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
        self.validate()
        if frame_width <= 0 or frame_height <= 0:
            raise AnnotationError("frame size must be positive.")

        x1 = math.floor(self.x * frame_width)
        y1 = math.floor(self.y * frame_height)
        x2 = math.ceil((self.x + self.width) * frame_width)
        y2 = math.ceil((self.y + self.height) * frame_height)

        x1 = max(0, min(x1, frame_width - 1))
        y1 = max(0, min(y1, frame_height - 1))
        x2 = max(x1 + 1, min(x2, frame_width))
        y2 = max(y1 + 1, min(y2, frame_height))

        return x1, y1, x2 - x1, y2 - y1


@dataclass(frozen=True, slots=True)
class AnnotationEvent:
    time_s: float
    type: str = "card_played"
    confidence: str | None = None
    notes: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AnnotationEvent":
        mapping = _require_mapping(data, "event")
        allowed_keys = {"time_s", "type", "confidence", "notes"}
        unknown_keys = set(mapping) - allowed_keys
        if unknown_keys:
            names = ", ".join(sorted(unknown_keys))
            raise AnnotationError(f"event has invalid keys (extra keys: {names}).")
        confidence = mapping.get("confidence")
        notes = mapping.get("notes")
        if confidence is not None and (
            not isinstance(confidence, str) or confidence not in EVENT_CONFIDENCES
        ):
            raise AnnotationError(
                "event.confidence must be confirmed, uncertain, ignore, or proposed."
            )
        if notes is not None and not isinstance(notes, str):
            raise AnnotationError("event.notes must be a string or null.")
        event = cls(
            time_s=_require_float(mapping, "time_s", min_value=0.0),
            type=_require_string(mapping, "type"),
            confidence=confidence,
            notes=notes,
        )
        if event.type not in EVENT_TYPES:
            raise AnnotationError(f"Unknown event type: {event.type}.")
        return event

    def to_mapping(self) -> dict[str, Any]:
        if not math.isfinite(self.time_s) or self.time_s < 0.0:
            raise AnnotationError("event time must be a finite, non-negative number.")
        if self.type not in EVENT_TYPES:
            raise AnnotationError(f"Unknown event type: {self.type}.")
        if self.confidence is not None and self.confidence not in EVENT_CONFIDENCES:
            raise AnnotationError("event.confidence is invalid.")
        if self.notes is not None and not isinstance(self.notes, str):
            raise AnnotationError("event.notes must be a string or null.")
        result: dict[str, Any] = {
            "time_s": self.time_s,
            "type": self.type,
        }
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.notes is not None:
            result["notes"] = self.notes
        return result


@dataclass(frozen=True, slots=True)
class AnnotationProposal:
    """A model candidate shown to the reviewer but never saved automatically."""

    time_s: float
    probability: float | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.time_s) or self.time_s < 0.0:
            raise AnnotationError("Proposal time must be finite and non-negative.")
        if self.probability is not None and not math.isfinite(self.probability):
            raise AnnotationError("Proposal probability must be finite when provided.")


def load_annotation_proposals(path: str | Path) -> tuple[AnnotationProposal, ...]:
    """Load event candidates from an inference or review-manifest JSON file."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnnotationError(f"Could not read model proposals: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise AnnotationError("Model proposals must contain a JSON object.")
    candidates = payload.get("events", payload.get("proposals", ()))
    if not isinstance(candidates, list):
        raise AnnotationError("Model proposals must contain an events list.")
    proposals: list[AnnotationProposal] = []
    for item in candidates:
        if not isinstance(item, Mapping):
            raise AnnotationError("Each model proposal must be a mapping.")
        time_s = item.get("time_s", item.get("predicted_time_s"))
        if isinstance(time_s, bool) or not isinstance(time_s, (int, float)):
            raise AnnotationError("Each model proposal needs a numeric time_s.")
        probability = item.get("probability")
        if probability is not None and (
            isinstance(probability, bool) or not isinstance(probability, (int, float))
        ):
            raise AnnotationError("Proposal probability must be numeric when provided.")
        proposals.append(
            AnnotationProposal(float(time_s), None if probability is None else float(probability))
        )
    return tuple(sorted(proposals, key=lambda proposal: proposal.time_s))


@dataclass(frozen=True, slots=True)
class VideoAnnotation:
    video: str
    events: tuple[AnnotationEvent, ...] = ()
    legacy_roi: Roi | None = None

    @property
    def roi(self) -> Roi | None:
        """Return V1 geometry for legacy callers.

        New annotations never write this value. Full-frame consumers must ignore it.
        """
        return self.legacy_roi

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "VideoAnnotation":
        mapping = _require_mapping(data, "annotation")
        if "schema_version" in mapping:
            _require_exact_keys(mapping, ("schema_version", "video", "events"), "annotation")
            if _require_string(mapping, "schema_version") != ANNOTATION_SCHEMA_VERSION:
                raise AnnotationError(f"schema_version must be {ANNOTATION_SCHEMA_VERSION}.")
            legacy_roi = None
        else:
            _require_exact_keys(mapping, ("video", "roi", "events"), "annotation")
            legacy_roi = Roi.from_mapping(mapping["roi"])
        events = tuple(
            AnnotationEvent.from_mapping(item) for item in _require_list(mapping, "events")
        )
        annotation = cls(
            video=_require_string(mapping, "video"),
            events=events,
            legacy_roi=legacy_roi,
        )
        _validate_sorted_events(annotation.events)
        return annotation

    def to_mapping(self) -> dict[str, Any]:
        _validate_sorted_events(self.events)
        return {
            "schema_version": ANNOTATION_SCHEMA_VERSION,
            "video": self.video,
            "events": [event.to_mapping() for event in self.events],
        }


def annotation_path_for_video(
    video_path: str | Path, *, annotations_dir: str | Path | None = None
) -> Path:
    path = Path(video_path)
    if annotations_dir is not None:
        return Path(annotations_dir) / f"{path.stem}.json"

    for parent in path.parents:
        if parent.name == "raw" and parent.parent.name == "data":
            return parent.parent / "annotations" / f"{path.stem}.json"

    return path.parent / "annotations" / f"{path.stem}.json"


def load_annotation(annotation_path: str | Path) -> VideoAnnotation:
    path = Path(annotation_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AnnotationError(f"Could not read annotation file: {path}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnnotationError(f"Invalid JSON in annotation file {path}: {exc.msg}.") from exc

    return VideoAnnotation.from_mapping(data)


def _validate_duplicate_events(
    annotation: VideoAnnotation,
    *,
    tolerance_s: float = DEFAULT_DUPLICATE_TOLERANCE_S,
) -> None:
    if tolerance_s < 0.0 or not math.isfinite(tolerance_s):
        raise AnnotationError("Duplicate-event tolerance must be finite and non-negative.")
    for previous, current in zip(annotation.events, annotation.events[1:], strict=False):
        gap_s = current.time_s - previous.time_s
        if gap_s <= tolerance_s:
            raise AnnotationError(
                f"Annotation {annotation.video} has duplicate events within "
                f"{tolerance_s * 1000:.0f} ms at {previous.time_s:.3f}s and {current.time_s:.3f}s."
            )
        if gap_s < 0.1:
            warnings.warn(
                f"Annotation {annotation.video} has events less than 100 ms apart at "
                f"{previous.time_s:.3f}s and {current.time_s:.3f}s.",
                stacklevel=2,
            )


def validate_annotation(
    annotation: VideoAnnotation,
    metadata: VideoMetadata,
    *,
    duplicate_tolerance_s: float = DEFAULT_DUPLICATE_TOLERANCE_S,
) -> None:
    if Path(annotation.video).name != metadata.path.name:
        raise AnnotationError(
            "Annotation video does not match the loaded source video: "
            f"{annotation.video} != {metadata.path.name}"
        )

    if annotation.legacy_roi is not None:
        annotation.legacy_roi.validate()
    _validate_sorted_events(annotation.events)

    for event in annotation.events:
        if event.type not in EVENT_TYPES:
            raise AnnotationError(f"Unknown event type: {event.type}.")
        if event.time_s > metadata.duration_s + 1e-6:
            raise AnnotationError(
                "Event time exceeds the video duration: "
                f"{event.time_s:.3f}s > {metadata.duration_s:.3f}s"
            )

    _validate_duplicate_events(annotation, tolerance_s=duplicate_tolerance_s)


def save_annotation(
    annotation: VideoAnnotation,
    annotation_path: str | Path,
    *,
    metadata: VideoMetadata,
) -> Path:
    sorted_events = tuple(sorted(annotation.events, key=lambda event: event.time_s))
    sorted_annotation = VideoAnnotation(
        video=annotation.video,
        events=sorted_events,
        legacy_roi=annotation.legacy_roi,
    )
    validate_annotation(sorted_annotation, metadata)

    path = Path(annotation_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.stem}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(sorted_annotation.to_mapping(), handle, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)

    temp_path.replace(path)
    return path


@dataclass(slots=True)
class AnnotationSession:
    video_path: Path
    metadata: VideoMetadata
    annotation_path: Path
    events: list[AnnotationEvent] = field(default_factory=list)

    @property
    def event_count(self) -> int:
        return len(self.events)

    @classmethod
    def open(
        cls, video_path: str | Path, *, annotations_dir: str | Path | None = None
    ) -> "AnnotationSession":
        metadata = read_video_metadata(video_path)
        annotation_path = annotation_path_for_video(
            metadata.path,
            annotations_dir=annotations_dir,
        )

        if annotation_path.exists():
            annotation = load_annotation(annotation_path)
            validate_annotation(annotation, metadata)
            return cls(
                video_path=metadata.path,
                metadata=metadata,
                annotation_path=annotation_path,
                events=list(annotation.events),
            )

        return cls(
            video_path=metadata.path,
            metadata=metadata,
            annotation_path=annotation_path,
        )

    def to_annotation(self) -> VideoAnnotation:
        return VideoAnnotation(
            video=self.metadata.path.name,
            events=tuple(self.events),
        )

    def save(self) -> Path:
        return save_annotation(
            self.to_annotation(),
            self.annotation_path,
            metadata=self.metadata,
        )

    def add_event(
        self,
        time_s: float,
        *,
        event_type: str = "card_played",
        confidence: str | None = "confirmed",
        notes: str | None = None,
    ) -> Path:
        self.events.append(
            AnnotationEvent(time_s=time_s, type=event_type, confidence=confidence, notes=notes)
        )
        return self.save()

    def update_event(
        self,
        index: int,
        *,
        time_s: float | None = None,
        event_type: str | None = None,
        confidence: str | None = None,
        notes: str | None = None,
    ) -> Path:
        try:
            previous = self.events[index]
        except IndexError as exc:
            raise AnnotationError("Event index is out of range.") from exc
        self.events[index] = AnnotationEvent(
            time_s=previous.time_s if time_s is None else time_s,
            type=previous.type if event_type is None else event_type,
            confidence=previous.confidence if confidence is None else confidence,
            notes=previous.notes if notes is None else notes,
        )
        return self.save()

    def delete_event(self, index: int) -> AnnotationEvent:
        try:
            event = self.events.pop(index)
        except IndexError as exc:
            raise AnnotationError("Event index is out of range.") from exc
        self.save()
        return event

    def delete_latest_event(self) -> AnnotationEvent | None:
        if not self.events:
            return None
        event = self.events.pop()
        self.save()
        return event


def open_annotation_session(
    video_path: str | Path, *, annotations_dir: str | Path | None = None
) -> AnnotationSession:
    return AnnotationSession.open(video_path, annotations_dir=annotations_dir)


def _resize_preview(
    frame: Any,
    *,
    max_width: int = 1280,
    max_height: int = 720,
) -> tuple[Any, float]:
    cv2 = _import_cv2()
    height, width = frame.shape[:2]
    scale = min(max_width / width, max_height / height, 1.0)
    if scale == 1.0:
        return frame.copy(), 1.0

    preview_width = max(1, int(round(width * scale)))
    preview_height = max(1, int(round(height * scale)))
    preview = cv2.resize(frame, (preview_width, preview_height), interpolation=cv2.INTER_AREA)
    return preview, scale


def _format_timestamp(seconds: float) -> str:
    total_milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def _draw_overlay(frame: Any, lines: Sequence[str]) -> Any:
    cv2 = _import_cv2()
    top = 28
    for line in lines:
        cv2.putText(
            frame,
            line,
            (16, top),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            line,
            (16, top),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        top += 28
    return frame


def _capture_frame(cap: Any, frame_index: int, metadata: VideoMetadata) -> Any:
    cv2 = _import_cv2()
    frame_index = max(0, min(frame_index, metadata.frame_count - 1))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    if not ok or frame is None:
        raise VideoError(
            "OpenCV could not read the requested frame. "
            "Check FFmpeg/OpenCV support and the source file: "
            f"{metadata.path}"
        )
    return frame


def _print_annotation_help(session: AnnotationSession) -> None:
    print()
    print("Event definition:")
    print(
        "  Event time is the first frame at which the card has substantially "
        "reached its final position in the trick area."
    )
    print()
    print("Controls:")
    print("  1-7     select event type (card play, clear, move, remove, return, drop, anomaly)")
    print("  SPACE   add a confirmed event of the selected type")
    print("  W / S   select previous or next saved event")
    print("  , / .   move the selected event one frame backward or forward")
    print("  T       cycle the selected event type")
    print("  U       mark the selected event or proposal uncertain")
    print("  N / B   jump to next or previous model proposal")
    print("  C       toggle before/after comparison")
    print("  P       pause or play")
    print("  A / D   seek backward or forward about 250 ms")
    print("  J / L   seek backward or forward about 2 s")
    print("  BACKSPACE or X  remove the selected event")
    print("  Q       save and exit")
    print()
    print(f"Video: {session.metadata.path}")
    print(f"Annotation file: {session.annotation_path}")
    print(
        f"Video size: {session.metadata.width}x{session.metadata.height} at "
        f"{session.metadata.fps:.3f} fps"
    )
    print(f"Duration: {_format_timestamp(session.metadata.duration_s)}")
    print()


def annotate_video(
    video_path: str | Path,
    *,
    annotations_dir: str | Path | None = None,
    proposals: Sequence[AnnotationProposal] = (),
) -> Path:
    cv2 = _import_cv2()
    session = open_annotation_session(video_path, annotations_dir=annotations_dir)
    capture = cv2.VideoCapture(str(session.video_path))
    if not capture.isOpened():
        raise VideoError(
            "OpenCV could not open the source video for annotation. "
            "Check FFmpeg/OpenCV support and the source file: "
            f"{session.video_path}"
        )

    window_name = f"CardEventNet annotate - {session.video_path.name}"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    _print_annotation_help(session)

    current_frame_index = 0
    current_frame = _capture_frame(capture, current_frame_index, session.metadata)

    playing = False
    needs_frame_refresh = False
    selected_event_index: int | None = len(session.events) - 1 if session.events else None
    selected_proposal_index: int | None = None
    selected_type = "card_played"
    compare_before_after = False
    wait_key = getattr(cv2, "waitKeyEx", cv2.waitKey)

    try:
        while True:
            if needs_frame_refresh:
                current_frame = _capture_frame(capture, current_frame_index, session.metadata)
                needs_frame_refresh = False

            preview, _ = _resize_preview(current_frame)
            timestamp_s = current_frame_index / session.metadata.fps
            if compare_before_after:
                before = _capture_frame(
                    capture,
                    current_frame_index - max(1, int(round(session.metadata.fps * 0.5))),
                    session.metadata,
                )
                after = _capture_frame(
                    capture,
                    current_frame_index + max(1, int(round(session.metadata.fps * 0.5))),
                    session.metadata,
                )
                before_preview, _ = _resize_preview(before, max_width=620, max_height=600)
                after_preview, _ = _resize_preview(after, max_width=620, max_height=600)
                preview = cv2.hconcat((before_preview, after_preview))
            event_selection = selected_event_index if selected_event_index is not None else "-"
            proposal_selection = (
                selected_proposal_index if selected_proposal_index is not None else "-"
            )
            overlay = [
                (
                    f"Time: {_format_timestamp(timestamp_s)} / "
                    f"{_format_timestamp(session.metadata.duration_s)}"
                ),
                f"Events: {session.event_count}",
                f"Type: {selected_type}",
                f"Selected event: {event_selection}",
                f"Proposal: {proposal_selection}",
                f"State: {'PLAY' if playing else 'PAUSE'}",
            ]
            shown_frame = _draw_overlay(preview, overlay)
            cv2.imshow(window_name, shown_frame)

            delay_ms = max(1, int(round(1000.0 / session.metadata.fps))) if playing else 30
            key = wait_key(delay_ms)
            if key != -1:
                key &= 0xFF

            frame_changed = False

            if key in (-1, 255):
                pass
            elif key in (ord("q"), ord("Q")):
                break
            elif key in (ord("p"), ord("P")):
                playing = not playing
                frame_changed = True
            elif key in (ord("a"), ord("A")):
                step = max(1, int(round(0.25 * session.metadata.fps)))
                current_frame_index = max(0, current_frame_index - step)
                frame_changed = True
            elif key in (ord("d"), ord("D")):
                step = max(1, int(round(0.25 * session.metadata.fps)))
                current_frame_index = min(
                    session.metadata.frame_count - 1,
                    current_frame_index + step,
                )
                frame_changed = True
            elif key in (ord("j"), ord("J")):
                step = max(1, int(round(2.0 * session.metadata.fps)))
                current_frame_index = max(0, current_frame_index - step)
                frame_changed = True
            elif key in (ord("l"), ord("L")):
                step = max(1, int(round(2.0 * session.metadata.fps)))
                current_frame_index = min(
                    session.metadata.frame_count - 1,
                    current_frame_index + step,
                )
                frame_changed = True
            elif key in EVENT_TYPE_SHORTCUTS:
                selected_type = EVENT_TYPE_SHORTCUTS[key]
                print(f"Selected event type: {selected_type}")
            elif key in (ord("w"), ord("W")):
                if session.events:
                    selected_event_index = max(0, (selected_event_index or 0) - 1)
            elif key in (ord("s"), ord("S")):
                if session.events:
                    selected_event_index = min(
                        len(session.events) - 1, (selected_event_index or -1) + 1
                    )
            elif key in (ord("n"), ord("N"), ord("b"), ord("B")):
                if proposals:
                    direction = 1 if key in (ord("n"), ord("N")) else -1
                    current = selected_proposal_index if selected_proposal_index is not None else 0
                    selected_proposal_index = (current + direction) % len(proposals)
                    current_frame_index = min(
                        session.metadata.frame_count - 1,
                        max(
                            0,
                            int(
                                round(
                                    proposals[selected_proposal_index].time_s * session.metadata.fps
                                )
                            ),
                        ),
                    )
                    frame_changed = True
            elif key in (8, 127, ord("x"), ord("X")):
                if selected_event_index is not None:
                    session.delete_event(selected_event_index)
                    selected_event_index = (
                        min(selected_event_index, len(session.events) - 1)
                        if session.events
                        else None
                    )
            elif key in (ord(","), ord(".")) and selected_event_index is not None:
                delta = -1 if key == ord(",") else 1
                session.update_event(
                    selected_event_index,
                    time_s=max(
                        0.0,
                        session.events[selected_event_index].time_s + delta / session.metadata.fps,
                    ),
                )
            elif key in (ord("t"), ord("T")) and selected_event_index is not None:
                types = tuple(sorted(EVENT_TYPES))
                current_type = session.events[selected_event_index].type
                session.update_event(
                    selected_event_index,
                    event_type=types[(types.index(current_type) + 1) % len(types)],
                )
            elif key in (ord("u"), ord("U")):
                if selected_event_index is not None:
                    session.update_event(selected_event_index, confidence="uncertain")
                elif selected_proposal_index is not None:
                    proposal = proposals[selected_proposal_index]
                    session.add_event(
                        proposal.time_s, event_type=selected_type, confidence="uncertain"
                    )
                    selected_event_index = len(session.events) - 1
            elif key == ord(" "):
                session.add_event(timestamp_s, event_type=selected_type)
                selected_event_index = len(session.events) - 1
            elif key in (ord("c"), ord("C")):
                compare_before_after = not compare_before_after
            if playing and not frame_changed:
                if current_frame_index >= session.metadata.frame_count - 1:
                    playing = False
                else:
                    current_frame_index += 1
                    needs_frame_refresh = True

            if frame_changed:
                needs_frame_refresh = True
    finally:
        capture.release()
        cv2.destroyAllWindows()

    session.save()
    return session.annotation_path
