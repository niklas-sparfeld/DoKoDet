from __future__ import annotations

from importlib import metadata

from .annotation import (
    AnnotationError,
    AnnotationEvent,
    AnnotationSession,
    Roi,
    VideoAnnotation,
    annotate_video,
    annotation_path_for_video,
    load_annotation,
    open_annotation_session,
    save_annotation,
    validate_annotation,
)
from .config import Config, load_config, save_config
from .device import resolve_device
from .video import VideoError, VideoMetadata, read_video_metadata


def _resolve_version() -> str:
    try:
        return metadata.version("cardevent")
    except metadata.PackageNotFoundError:
        return "0.1.0"


__version__ = _resolve_version()

__all__ = [
    "AnnotationError",
    "AnnotationEvent",
    "AnnotationSession",
    "Config",
    "Roi",
    "VideoAnnotation",
    "VideoError",
    "VideoMetadata",
    "annotate_video",
    "annotation_path_for_video",
    "load_annotation",
    "load_config",
    "open_annotation_session",
    "resolve_device",
    "read_video_metadata",
    "save_config",
    "save_annotation",
    "validate_annotation",
    "__version__",
]
