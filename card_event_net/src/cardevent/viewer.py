from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .video import VideoError, VideoMetadata, _import_cv2, read_video_metadata


def resize_preview(
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


def format_timestamp(seconds: float) -> str:
    total_milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def draw_overlay(frame: Any, lines: Sequence[str]) -> Any:
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


def capture_frame(cap: Any, frame_index: int, metadata: VideoMetadata) -> Any:
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


def normalize_key(key: int) -> int | None:
    if key in (-1, 255):
        return None
    return key & 0xFF


def before_after_frame(
    cap: Any,
    frame_index: int,
    metadata: VideoMetadata,
    *,
    offset_s: float = 0.5,
) -> Any:
    cv2 = _import_cv2()
    offset_frames = max(1, int(round(metadata.fps * offset_s)))
    before = capture_frame(cap, frame_index - offset_frames, metadata)
    after = capture_frame(cap, frame_index + offset_frames, metadata)
    before_preview, _ = resize_preview(before, max_width=620, max_height=600)
    after_preview, _ = resize_preview(after, max_width=620, max_height=600)
    return cv2.hconcat((before_preview, after_preview))


@dataclass(slots=True)
class VideoViewer:
    """Small shared OpenCV viewer used by annotation and queue review."""

    metadata: VideoMetadata
    capture: Any
    window_name: str

    @classmethod
    def open(cls, video_path: str, *, window_name: str) -> "VideoViewer":
        cv2 = _import_cv2()
        metadata = read_video_metadata(video_path)
        capture = cv2.VideoCapture(str(metadata.path))
        if not capture.isOpened():
            capture.release()
            raise VideoError(
                "OpenCV could not open the source video. "
                "Check FFmpeg/OpenCV support and the source file: "
                f"{metadata.path}"
            )
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        return cls(metadata=metadata, capture=capture, window_name=window_name)

    def frame(self, frame_index: int) -> Any:
        return capture_frame(self.capture, frame_index, self.metadata)

    def render(self, frame_index: int, lines: Sequence[str], *, compare: bool = False) -> None:
        cv2 = _import_cv2()
        frame = (
            before_after_frame(self.capture, frame_index, self.metadata)
            if compare
            else self.frame(frame_index)
        )
        preview, _ = resize_preview(frame)
        cv2.imshow(self.window_name, draw_overlay(preview, lines))

    def wait_key(self, delay_ms: int) -> int | None:
        cv2 = _import_cv2()
        wait_key = getattr(cv2, "waitKeyEx", cv2.waitKey)
        return normalize_key(wait_key(delay_ms))

    def close(self) -> None:
        cv2 = _import_cv2()
        self.capture.release()
        cv2.destroyWindow(self.window_name)


__all__ = [
    "VideoViewer",
    "before_after_frame",
    "capture_frame",
    "draw_overlay",
    "format_timestamp",
    "normalize_key",
    "resize_preview",
]
