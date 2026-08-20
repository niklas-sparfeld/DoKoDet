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
from .cache import (
    CacheError,
    CacheMetadata,
    cache_path_for_video,
    extract_video_cache,
    load_cache_metadata,
    prepare_videos,
)
from .config import Config, load_config, save_config
from .dataset import (
    CachedFrameStore,
    CausalClipDataset,
    DatasetSample,
    VideoDataset,
    inference_samples_for_cache,
    samples_for_annotation,
    samples_for_cache,
)
from .device import resolve_device
from .sampling import (
    DEFAULT_CLIP_OFFSETS_S,
    LabeledTime,
    SamplingError,
    build_inference_times,
    build_training_times,
    event_in_window,
    is_clean_negative_time,
    is_positive_time,
    select_frame_indices,
    select_frame_timestamps,
)
from .splits import SplitError, VideoSplit, load_split, make_video_split, save_split, video_id
from .transforms import ClipTransform, TransformError
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
    "CacheError",
    "CacheMetadata",
    "CachedFrameStore",
    "Config",
    "CausalClipDataset",
    "ClipTransform",
    "DatasetSample",
    "DEFAULT_CLIP_OFFSETS_S",
    "LabeledTime",
    "Roi",
    "SamplingError",
    "SplitError",
    "TransformError",
    "VideoAnnotation",
    "VideoDataset",
    "VideoError",
    "VideoMetadata",
    "VideoSplit",
    "annotate_video",
    "annotation_path_for_video",
    "build_inference_times",
    "build_training_times",
    "cache_path_for_video",
    "extract_video_cache",
    "event_in_window",
    "inference_samples_for_cache",
    "is_clean_negative_time",
    "is_positive_time",
    "load_annotation",
    "load_cache_metadata",
    "load_config",
    "load_split",
    "make_video_split",
    "open_annotation_session",
    "prepare_videos",
    "resolve_device",
    "read_video_metadata",
    "samples_for_annotation",
    "samples_for_cache",
    "save_config",
    "save_annotation",
    "save_split",
    "select_frame_indices",
    "select_frame_timestamps",
    "validate_annotation",
    "video_id",
    "__version__",
]
