from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class VideoError(RuntimeError):
    pass


SUPPORTED_VIDEO_EXTENSIONS = frozenset({".mov", ".m4v", ".mp4"})


def resolve_video_path(videos_dir: str | Path, video_name: str) -> Path:
    """Resolve one queue video by stem and reject missing or ambiguous files."""
    directory = Path(videos_dir)
    if not isinstance(video_name, str) or not video_name:
        raise VideoError("A review item needs a video name.")
    if Path(video_name).name != video_name:
        raise VideoError(f"Review item video must be a simple name: {video_name}")
    if not directory.is_dir():
        raise VideoError(f"Video directory does not exist: {directory}")

    stem = Path(video_name).stem.casefold()
    matches = sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.casefold() in SUPPORTED_VIDEO_EXTENSIONS
        and path.stem.casefold() == stem
    )
    if not matches:
        raise VideoError(f"No source video matches queue item {video_name} in {directory}")
    if len(matches) > 1:
        names = ", ".join(path.name for path in matches)
        raise VideoError(f"Source video {video_name} is ambiguous: {names}")
    return matches[0].resolve()


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
