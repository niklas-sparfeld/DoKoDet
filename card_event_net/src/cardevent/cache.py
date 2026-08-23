from __future__ import annotations

import json
import math
import shutil
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .annotation import (
    AnnotationError,
    annotation_path_for_video,
    load_annotation,
    validate_annotation,
)
from .video import VideoError, _import_cv2, read_video_metadata


class CacheError(RuntimeError):
    pass


FULL_FRAME_LETTERBOX_V1 = "full_frame_letterbox_v1"
LEGACY_ROI_LETTERBOX_V1 = "roi_letterbox_v1"


FrameProgressCallback = Callable[[int, int], None]
PrepareProgressCallback = Callable[[Path, int, int], None]
PrepareSkipCallback = Callable[[Path, Path], None]


@dataclass(frozen=True, slots=True)
class CacheMetadata:
    source_video: str
    cache_fps: float
    duration_s: float
    frame_timestamps_s: tuple[float, ...]
    frame_size: int = 224
    preprocessing: str = FULL_FRAME_LETTERBOX_V1

    @classmethod
    def from_mapping(cls, data: Any) -> "CacheMetadata":
        if not isinstance(data, dict):
            raise CacheError("Cache metadata must be a JSON object.")

        source_video = data.get("source_video")
        if not isinstance(source_video, str) or not source_video:
            raise CacheError("Cache metadata source_video must be a non-empty string.")

        cache_fps = data.get("cache_fps")
        duration_s = data.get("duration_s")
        frame_size = data.get("frame_size", 224)
        preprocessing = data.get("preprocessing", LEGACY_ROI_LETTERBOX_V1)
        timestamps = data.get("frame_timestamps_s")
        if isinstance(cache_fps, bool) or not isinstance(cache_fps, (int, float)):
            raise CacheError("Cache metadata cache_fps must be a number.")
        if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)):
            raise CacheError("Cache metadata duration_s must be a number.")
        if isinstance(frame_size, bool) or not isinstance(frame_size, int) or frame_size <= 0:
            raise CacheError("Cache metadata frame_size must be a positive integer.")
        if not isinstance(preprocessing, str) or not preprocessing:
            raise CacheError("Cache metadata preprocessing must be a non-empty string.")
        if not isinstance(timestamps, list):
            raise CacheError("Cache metadata frame_timestamps_s must be a list.")

        frame_timestamps_s = tuple(float(value) for value in timestamps)
        if any(not math.isfinite(value) or value < 0.0 for value in frame_timestamps_s):
            raise CacheError("Cache timestamps must be finite and non-negative.")
        if any(
            current < previous
            for previous, current in zip(frame_timestamps_s, frame_timestamps_s[1:], strict=False)
        ):
            raise CacheError("Cache timestamps must be sorted.")
        if float(cache_fps) <= 0.0 or float(duration_s) < 0.0:
            raise CacheError("Cache metadata has invalid duration or frame rate.")

        return cls(
            source_video=source_video,
            cache_fps=float(cache_fps),
            duration_s=float(duration_s),
            frame_timestamps_s=frame_timestamps_s,
            frame_size=frame_size,
            preprocessing=preprocessing,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "source_video": self.source_video,
            "cache_fps": self.cache_fps,
            "duration_s": self.duration_s,
            "frame_timestamps_s": list(self.frame_timestamps_s),
            "frame_size": self.frame_size,
            "preprocessing": self.preprocessing,
        }


def cache_path_for_video(video_path: str | Path, *, cache_root: str | Path | None = None) -> Path:
    path = Path(video_path)
    if cache_root is not None:
        return Path(cache_root) / path.stem

    for parent in path.parents:
        if parent.name == "raw" and parent.parent.name == "data":
            return parent.parent / "cache" / path.stem

    return path.parent / "cache" / path.stem


def load_cache_metadata(cache_dir: str | Path) -> CacheMetadata:
    path = Path(cache_dir) / "metadata.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CacheError(f"Could not read cache metadata: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CacheError(f"Invalid JSON in cache metadata {path}: {exc.msg}.") from exc
    return CacheMetadata.from_mapping(data)


def cache_is_usable(
    video_path: str | Path,
    *,
    cache_root: str | Path | None,
    cache_fps: float,
    size: int,
) -> bool:
    """Return true only for a complete cache that matches this request."""
    source = Path(video_path)
    cache_path = cache_path_for_video(source, cache_root=cache_root)
    try:
        metadata = load_cache_metadata(cache_path)
    except CacheError:
        return False
    if (
        Path(metadata.source_video).name != source.name
        or not math.isclose(metadata.cache_fps, cache_fps)
        or metadata.frame_size != size
        or metadata.preprocessing != FULL_FRAME_LETTERBOX_V1
    ):
        return False
    frames_dir = cache_path / "frames"
    return frames_dir.is_dir() and all(
        (frames_dir / f"{index:06d}.jpg").is_file()
        for index in range(len(metadata.frame_timestamps_s))
    )


def _full_frame_letterbox(frame: Any, *, size: int, cv2: Any) -> Any:
    import numpy as np

    frame_height, frame_width = frame.shape[:2]
    if frame_width <= 0 or frame_height <= 0:
        raise CacheError("The source frame has an invalid size.")

    scale = min(size / frame_width, size / frame_height)
    resized_width = max(1, round(frame_width * scale))
    resized_height = max(1, round(frame_height * scale))
    resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_AREA)

    canvas = np.zeros((size, size, 3), dtype=resized.dtype)
    x_offset = (size - resized_width) // 2
    y_offset = (size - resized_height) // 2
    canvas[y_offset : y_offset + resized_height, x_offset : x_offset + resized_width] = resized
    return canvas


def extract_video_cache(
    video_path: str | Path,
    *,
    annotations_dir: str | Path | None = None,
    cache_root: str | Path | None = None,
    cache_fps: float = 10.0,
    size: int = 224,
    progress_callback: FrameProgressCallback | None = None,
) -> Path:
    if cache_fps <= 0.0 or not math.isfinite(cache_fps):
        raise CacheError("cache_fps must be a finite positive number.")
    if size <= 0:
        raise CacheError("cache size must be positive.")

    metadata = read_video_metadata(video_path)
    annotation_path = annotation_path_for_video(metadata.path, annotations_dir=annotations_dir)
    if not annotation_path.is_file():
        raise AnnotationError(
            f"No annotation exists for {metadata.path.name}: {annotation_path}. "
            "Annotate the video before preparing the cache."
        )
    annotation = load_annotation(annotation_path)
    validate_annotation(annotation, metadata)

    cv2 = _import_cv2()
    capture = cv2.VideoCapture(str(metadata.path))
    if not capture.isOpened():
        raise VideoError(
            "OpenCV could not open the source video for cache extraction. "
            "Check FFmpeg/OpenCV support for this codec: "
            f"{metadata.path}"
        )
    orientation_auto = getattr(cv2, "CAP_PROP_ORIENTATION_AUTO", None)
    if orientation_auto is not None:
        capture.set(orientation_auto, 1)

    destination = cache_path_for_video(metadata.path, cache_root=cache_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    frames_dir = temporary_dir / "frames"
    frames_dir.mkdir()
    frame_timestamps_s: list[float] = []
    target_time_s = 0.0
    target_step_s = 1.0 / cache_fps
    previous_frame: Any | None = None
    previous_time_s: float | None = None
    frame_index = 0

    try:
        if progress_callback is not None:
            progress_callback(0, metadata.frame_count)

        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                if frame_index < metadata.frame_count:
                    raise VideoError(
                        "OpenCV could not decode the source video at frame "
                        f"{frame_index}. Check FFmpeg/OpenCV support and the source file: "
                        f"{metadata.path}"
                    )
                break

            current_time_s = frame_index / metadata.fps
            while target_time_s <= current_time_s + 1e-9:
                if previous_frame is None or previous_time_s is None:
                    selected_frame = frame
                    selected_time_s = current_time_s
                elif target_time_s - previous_time_s <= current_time_s - target_time_s:
                    selected_frame = previous_frame
                    selected_time_s = previous_time_s
                else:
                    selected_frame = frame
                    selected_time_s = current_time_s

                cached_frame = _full_frame_letterbox(
                    selected_frame,
                    size=size,
                    cv2=cv2,
                )
                frame_path = frames_dir / f"{len(frame_timestamps_s):06d}.jpg"
                written = cv2.imwrite(
                    str(frame_path),
                    cached_frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 90],
                )
                if not written:
                    raise CacheError(f"OpenCV could not write cached frame: {frame_path}")
                frame_timestamps_s.append(float(selected_time_s))
                target_time_s += target_step_s

            previous_frame = frame.copy()
            previous_time_s = current_time_s
            frame_index += 1
            if progress_callback is not None:
                progress_callback(frame_index, metadata.frame_count)

        if not frame_timestamps_s:
            raise CacheError(
                "The source video produced no cached frames. "
                "Check FFmpeg/OpenCV support and the source file."
            )

        cache_metadata = CacheMetadata(
            source_video=metadata.source_video,
            cache_fps=cache_fps,
            duration_s=metadata.duration_s,
            frame_timestamps_s=tuple(frame_timestamps_s),
            frame_size=size,
            preprocessing=FULL_FRAME_LETTERBOX_V1,
        )
        (temporary_dir / "metadata.json").write_text(
            json.dumps(cache_metadata.to_mapping(), indent=2) + "\n",
            encoding="utf-8",
        )
        if destination.exists():
            shutil.rmtree(destination)
        temporary_dir.replace(destination)
        temporary_dir = Path()
        return destination
    except (OSError, ValueError) as exc:
        raise CacheError(f"Could not write the video cache for {metadata.path}: {exc}") from exc
    finally:
        capture.release()
        if temporary_dir != Path():
            shutil.rmtree(temporary_dir, ignore_errors=True)


def prepare_videos(
    videos: Sequence[str | Path],
    *,
    annotations_dir: str | Path | None = None,
    cache_root: str | Path | None = None,
    cache_fps: float = 10.0,
    size: int = 224,
    progress_callback: PrepareProgressCallback | None = None,
    skip_callback: PrepareSkipCallback | None = None,
    force: bool = False,
) -> list[Path]:
    cache_paths: list[Path] = []
    for video in videos:
        video_path = Path(video)
        cache_path = cache_path_for_video(video_path, cache_root=cache_root)
        if not force and cache_is_usable(
            video_path,
            cache_root=cache_root,
            cache_fps=cache_fps,
            size=size,
        ):
            if skip_callback is not None:
                skip_callback(video_path, cache_path)
            cache_paths.append(cache_path)
            continue
        frame_progress_callback = None
        if progress_callback is not None:

            def frame_progress_callback(current: int, total: int, path: Path = video_path) -> None:
                progress_callback(path, current, total)

        cache_paths.append(
            extract_video_cache(
                video_path,
                annotations_dir=annotations_dir,
                cache_root=cache_root,
                cache_fps=cache_fps,
                size=size,
                progress_callback=frame_progress_callback,
            )
        )
    return cache_paths
