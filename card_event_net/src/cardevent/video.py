from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class VideoError(RuntimeError):
    pass


def _import_cv2() -> Any:
    try:
        import cv2
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OpenCV is not available. Run `uv sync` to install the project dependencies."
        ) from exc
    return cv2


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    path: Path
    width: int
    height: int
    fps: float
    frame_count: int
    duration_s: float

    @property
    def source_video(self) -> str:
        return self.path.name


def read_video_metadata(video_path: str | Path) -> VideoMetadata:
    path = Path(video_path).expanduser()
    if not path.is_file():
        raise VideoError(f"Video file does not exist: {path}")

    cv2 = _import_cv2()
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise VideoError(
                "OpenCV could not open the video file. "
                "Check FFmpeg/OpenCV support for this container and codec: "
                f"{path}"
            )

        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()

    if width <= 0 or height <= 0:
        raise VideoError(
            "OpenCV reported an invalid frame size for the video. "
            "Check FFmpeg/OpenCV support and the source file: "
            f"{path}"
        )
    if fps <= 0.0:
        raise VideoError(
            "OpenCV reported an invalid frame rate for the video. "
            "Check FFmpeg/OpenCV support and the source file: "
            f"{path}"
        )
    if frame_count <= 0:
        raise VideoError(
            "OpenCV reported no frames for the video. "
            "Check FFmpeg/OpenCV support and the source file: "
            f"{path}"
        )

    duration_s = frame_count / fps

    return VideoMetadata(
        path=path.resolve(),
        width=width,
        height=height,
        fps=fps,
        frame_count=frame_count,
        duration_s=duration_s,
    )
