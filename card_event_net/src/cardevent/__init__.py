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
from .evaluate import (
    EvaluationError,
    ScoredVideo,
    ThresholdSelection,
    diagnose_checkpoint_from_files,
    evaluate_checkpoint_from_files,
    evaluate_streams,
    event_f1,
    plot_probability_axis,
    select_threshold,
)
from .events import (
    DetectedEvent,
    EventError,
    EventMatch,
    EventMatchResult,
    ProbabilitySample,
    match_events,
    probabilities_to_events,
)
from .export_coreml import (
    COREML_INPUT_NAME,
    COREML_INPUT_SHAPE,
    COREML_OUTPUT_NAME,
    CoreMLExportError,
    CoreMLExportResult,
    deterministic_sample,
    export_checkpoint_to_coreml,
    verify_coreml_parity,
)
from .hard_negatives import (
    HardNegativeError,
    HardNegativeSample,
    false_triggers,
    load_hard_negative_times,
    mine_hard_negatives_from_files,
)
from .infer import InferenceError, infer_cached_video, infer_from_files, load_checkpoint
from .model import (
    CardEventNet,
    ModelError,
    backbone_is_frozen,
    build_model,
    freeze_backbone,
    unfreeze_backbone,
)
from .review import (
    ReviewQueueError,
    ReviewSession,
    ReviewSessionError,
    apply_review_queue,
    build_review_queue,
    review_queue_from_files,
)
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
from .train import TrainingError, TrainingResult, train_from_files, train_model
from .transforms import ClipTransform, TransformError
from .video import VideoError, VideoMetadata, read_video_metadata, resolve_video_path


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
    "CardEventNet",
    "COREML_INPUT_NAME",
    "COREML_INPUT_SHAPE",
    "COREML_OUTPUT_NAME",
    "CachedFrameStore",
    "Config",
    "CoreMLExportError",
    "CoreMLExportResult",
    "CausalClipDataset",
    "ClipTransform",
    "DatasetSample",
    "DEFAULT_CLIP_OFFSETS_S",
    "DetectedEvent",
    "deterministic_sample",
    "EventError",
    "EventMatch",
    "EventMatchResult",
    "EvaluationError",
    "InferenceError",
    "HardNegativeError",
    "HardNegativeSample",
    "LabeledTime",
    "ModelError",
    "ProbabilitySample",
    "Roi",
    "ReviewQueueError",
    "ReviewSession",
    "ReviewSessionError",
    "SamplingError",
    "SplitError",
    "TransformError",
    "TrainingError",
    "TrainingResult",
    "ScoredVideo",
    "ThresholdSelection",
    "VideoAnnotation",
    "VideoDataset",
    "VideoError",
    "VideoMetadata",
    "VideoSplit",
    "annotate_video",
    "apply_review_queue",
    "annotation_path_for_video",
    "build_inference_times",
    "build_model",
    "build_review_queue",
    "build_training_times",
    "cache_path_for_video",
    "backbone_is_frozen",
    "extract_video_cache",
    "event_in_window",
    "export_checkpoint_to_coreml",
    "evaluate_checkpoint_from_files",
    "diagnose_checkpoint_from_files",
    "evaluate_streams",
    "event_f1",
    "plot_probability_axis",
    "infer_cached_video",
    "infer_from_files",
    "inference_samples_for_cache",
    "is_clean_negative_time",
    "is_positive_time",
    "load_annotation",
    "load_cache_metadata",
    "load_config",
    "load_checkpoint",
    "load_hard_negative_times",
    "load_split",
    "make_video_split",
    "match_events",
    "false_triggers",
    "mine_hard_negatives_from_files",
    "open_annotation_session",
    "prepare_videos",
    "resolve_device",
    "read_video_metadata",
    "resolve_video_path",
    "review_queue_from_files",
    "samples_for_annotation",
    "samples_for_cache",
    "save_config",
    "save_annotation",
    "save_split",
    "select_frame_indices",
    "select_frame_timestamps",
    "select_threshold",
    "probabilities_to_events",
    "freeze_backbone",
    "train_from_files",
    "train_model",
    "unfreeze_backbone",
    "verify_coreml_parity",
    "validate_annotation",
    "video_id",
    "__version__",
]
