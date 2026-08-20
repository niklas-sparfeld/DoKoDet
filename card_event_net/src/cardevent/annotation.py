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

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AnnotationEvent":
        mapping = _require_mapping(data, "event")
        _require_exact_keys(mapping, ("time_s", "type"), "event")
        event = cls(
            time_s=_require_float(mapping, "time_s", min_value=0.0),
            type=_require_string(mapping, "type"),
        )
        if event.type != "card_played":
            raise AnnotationError("event.type must be card_played in phase 2.")
        return event

    def to_mapping(self) -> dict[str, Any]:
        if not math.isfinite(self.time_s) or self.time_s < 0.0:
            raise AnnotationError("event time must be a finite, non-negative number.")
        return {
            "time_s": self.time_s,
            "type": self.type,
        }


@dataclass(frozen=True, slots=True)
class VideoAnnotation:
    video: str
    roi: Roi
    events: tuple[AnnotationEvent, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "VideoAnnotation":
        mapping = _require_mapping(data, "annotation")
        _require_exact_keys(mapping, ("video", "roi", "events"), "annotation")
        events = tuple(
            AnnotationEvent.from_mapping(item)
            for item in _require_list(mapping, "events")
        )
        annotation = cls(
            video=_require_string(mapping, "video"),
            roi=Roi.from_mapping(mapping["roi"]),
            events=events,
        )
        _validate_sorted_events(annotation.events)
        return annotation

    def to_mapping(self) -> dict[str, Any]:
        self.roi.validate()
        _validate_sorted_events(self.events)
        return {
            "video": self.video,
            "roi": self.roi.to_mapping(),
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


def _warn_close_events(annotation: VideoAnnotation) -> None:
    for previous, current in zip(annotation.events, annotation.events[1:], strict=False):
        gap_s = current.time_s - previous.time_s
        if gap_s < 0.1:
            warnings.warn(
                (
                    f"Annotation {annotation.video} has events less than 100 ms apart at "
                    f"{previous.time_s:.3f}s and {current.time_s:.3f}s."
                ),
                stacklevel=2,
            )


def validate_annotation(annotation: VideoAnnotation, metadata: VideoMetadata) -> None:
    if Path(annotation.video).name != metadata.path.name:
        raise AnnotationError(
            "Annotation video does not match the loaded source video: "
            f"{annotation.video} != {metadata.path.name}"
        )

    annotation.roi.validate()
    _validate_sorted_events(annotation.events)

    for event in annotation.events:
        if event.type != "card_played":
            raise AnnotationError("Only card_played events are valid in phase 2.")
        if event.time_s > metadata.duration_s + 1e-6:
            raise AnnotationError(
                "Event time exceeds the video duration: "
                f"{event.time_s:.3f}s > {metadata.duration_s:.3f}s"
            )

    _warn_close_events(annotation)


def save_annotation(
    annotation: VideoAnnotation,
    annotation_path: str | Path,
    *,
    metadata: VideoMetadata,
) -> Path:
    sorted_events = tuple(sorted(annotation.events, key=lambda event: event.time_s))
    sorted_annotation = VideoAnnotation(
        video=annotation.video,
        roi=annotation.roi,
        events=sorted_events,
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
    roi: Roi | None = None
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
                roi=annotation.roi,
                events=list(annotation.events),
            )

        return cls(
            video_path=metadata.path,
            metadata=metadata,
            annotation_path=annotation_path,
        )

    def to_annotation(self) -> VideoAnnotation:
        if self.roi is None:
            raise AnnotationError("ROI is not set.")
        return VideoAnnotation(
            video=self.metadata.path.name,
            roi=self.roi,
            events=tuple(self.events),
        )

    def save(self) -> Path:
        return save_annotation(
            self.to_annotation(),
            self.annotation_path,
            metadata=self.metadata,
        )

    def set_roi(self, roi: Roi) -> Path:
        self.roi = roi
        return self.save()

    def add_event(self, time_s: float) -> Path:
        if self.roi is None:
            raise AnnotationError("ROI is not set.")
        self.events.append(AnnotationEvent(time_s=time_s))
        return self.save()

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


def _select_roi(
    frame: Any,
    *,
    metadata: VideoMetadata,
    cv2: Any,
) -> Roi:
    preview, scale = _resize_preview(frame)
    print(
        "Select the table ROI in the OpenCV window. "
        "Drag a box and press Enter or Space to confirm."
    )
    print("Press C to cancel the ROI selection.")
    selection = cv2.selectROI("CardEventNet ROI", preview, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow("CardEventNet ROI")
    x, y, width, height = (int(value) for value in selection)
    if width <= 0 or height <= 0:
        raise AnnotationError("ROI selection was cancelled.")

    x1 = math.floor(x / scale)
    y1 = math.floor(y / scale)
    x2 = math.ceil((x + width) / scale)
    y2 = math.ceil((y + height) / scale)

    x1 = max(0, min(x1, metadata.width - 1))
    y1 = max(0, min(y1, metadata.height - 1))
    x2 = max(x1 + 1, min(x2, metadata.width))
    y2 = max(y1 + 1, min(y2, metadata.height))

    roi = Roi.from_pixels(
        x=x1,
        y=y1,
        width=x2 - x1,
        height=y2 - y1,
        frame_width=metadata.width,
        frame_height=metadata.height,
    )
    roi.validate()
    return roi


def _print_annotation_help(session: AnnotationSession) -> None:
    print()
    print("Event definition:")
    print(
        "  Event time is the first frame at which the card has substantially "
        "reached its final position in the trick area."
    )
    print()
    print("Controls:")
    print("  SPACE   mark a card_played event")
    print("  P       pause or play")
    print("  A / D   seek backward or forward about 250 ms")
    print("  J / L   seek backward or forward about 2 s")
    print("  BACKSPACE or X  remove the latest event")
    print("  R       redefine the ROI")
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


def annotate_video(video_path: str | Path, *, annotations_dir: str | Path | None = None) -> Path:
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
    if session.roi is None:
        session.set_roi(_select_roi(current_frame, metadata=session.metadata, cv2=cv2))
        current_frame = _capture_frame(capture, current_frame_index, session.metadata)

    playing = False
    needs_frame_refresh = False
    wait_key = getattr(cv2, "waitKeyEx", cv2.waitKey)

    try:
        while True:
            if needs_frame_refresh:
                current_frame = _capture_frame(capture, current_frame_index, session.metadata)
                needs_frame_refresh = False

            preview, _ = _resize_preview(current_frame)
            timestamp_s = current_frame_index / session.metadata.fps
            overlay = [
                (
                    f"Time: {_format_timestamp(timestamp_s)} / "
                    f"{_format_timestamp(session.metadata.duration_s)}"
                ),
                f"Events: {session.event_count}",
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
            elif key in (8, 127, ord("x"), ord("X")):
                deleted = session.delete_latest_event()
                if deleted is None:
                    print("No events to delete.")
            elif key == ord(" "):
                session.add_event(timestamp_s)
            elif key in (ord("r"), ord("R")):
                was_playing = playing
                playing = False
                session.set_roi(_select_roi(current_frame, metadata=session.metadata, cv2=cv2))
                playing = was_playing
                frame_changed = True

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
