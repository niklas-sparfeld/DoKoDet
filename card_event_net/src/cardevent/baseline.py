from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import torch

from .cache import CacheError
from .config import Config, load_config
from .dataset import CachedFrameStore, DatasetSample, inference_samples_for_cache
from .evaluate import (
    EvaluationError,
    ScoredVideo,
    _annotation_and_cache,
    _evaluation_payload,
    _partition_names,
    _save_evaluation,
    evaluate_streams,
    save_probability_plots,
    save_threshold_plot,
    select_threshold,
)
from .events import ProbabilitySample
from .sampling import select_frame_indices
from .splits import SplitError, VideoSplit, load_split


def _motion_score(
    sample: DatasetSample,
    store: CachedFrameStore,
    offsets_s: tuple[float, ...],
) -> float:
    indices = select_frame_indices(
        store.metadata.frame_timestamps_s,
        sample.decision_time_s,
        offsets_s=offsets_s,
    )
    frames = torch.stack([store.read_frame(index) for index in indices]).to(torch.float32)
    if frames.shape[0] < 2:
        return 0.0
    differences = (frames[1:] - frames[:-1]).abs().mean(dim=(1, 2, 3)) / 255.0
    return float(differences.mean())


def baseline_stream_for_cache(
    cache_dir: str | Path,
    config: Config,
) -> list[ProbabilitySample]:
    """Create a normalized motion score stream from one prepared cache."""
    cache_path = Path(cache_dir)
    try:
        samples = inference_samples_for_cache(
            cache_path,
            stride_s=config.input.inference_stride_s,
        )
        store = CachedFrameStore(cache_path)
    except (CacheError, ValueError) as exc:
        raise EvaluationError(f"Could not build baseline samples for {cache_path}: {exc}") from exc

    return [
        ProbabilitySample(
            time_s=sample.decision_time_s,
            probability=_motion_score(sample, store, config.input.clip_offsets_s),
        )
        for sample in samples
    ]


def load_baseline_streams(
    config: Config,
    split: VideoSplit,
    partition: str,
    *,
    cache_dir: str | Path = "data/cache",
    annotations_dir: str | Path = "data/annotations",
) -> list[ScoredVideo]:
    videos: list[ScoredVideo] = []
    cache_root = Path(cache_dir)
    annotation_root = Path(annotations_dir)
    for name in _partition_names(split, partition):
        cache_path, annotation, duration_s = _annotation_and_cache(
            name,
            cache_dir=cache_root,
            annotations_dir=annotation_root,
        )
        videos.append(
            ScoredVideo(
                name=name,
                duration_s=duration_s,
                ground_truth_times_s=tuple(event.time_s for event in annotation.events),
                probabilities=tuple(baseline_stream_for_cache(cache_path, config)),
            )
        )
    return videos


def _save_baseline_threshold(
    output_path: Path,
    *,
    threshold: float,
    metrics: dict[str, float],
    candidates: tuple[dict[str, float], ...],
) -> Path:
    path = output_path.with_name("baseline-threshold.json")
    payload = {
        "threshold": threshold,
        "validation_metrics": metrics,
        "candidates": list(candidates),
    }
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


def evaluate_baseline_from_files(
    config_path: str | Path,
    split_path: str | Path,
    *,
    partition: str,
    cache_dir: str | Path = "data/cache",
    annotations_dir: str | Path = "data/annotations",
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Tune and evaluate the classical motion baseline."""
    try:
        config = load_config(config_path)
        split = load_split(split_path)
    except (OSError, RuntimeError, SplitError, ValueError) as exc:
        raise EvaluationError(f"Could not load baseline inputs: {exc}") from exc

    destination = (
        Path(output_path)
        if output_path is not None
        else Path("data/outputs") / f"baseline-{partition}.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    validation_videos = load_baseline_streams(
        config,
        split,
        "val",
        cache_dir=cache_dir,
        annotations_dir=annotations_dir,
    )
    selection = select_threshold(
        validation_videos,
        merge_window_s=config.inference.merge_window_s,
        event_match_tolerance_s=config.metrics.event_match_tolerance_s,
        target_recall=config.metrics.target_recall,
        peak_confirmation_s=config.inference.peak_confirmation_s,
    )
    threshold_path = _save_baseline_threshold(
        destination,
        threshold=selection.threshold,
        metrics=selection.metrics,
        candidates=selection.candidates,
    )
    evaluated_videos = (
        validation_videos
        if partition == "val"
        else load_baseline_streams(
            config,
            split,
            partition,
            cache_dir=cache_dir,
            annotations_dir=annotations_dir,
        )
    )
    overall, per_video = evaluate_streams(
        evaluated_videos,
        threshold=selection.threshold,
        merge_window_s=config.inference.merge_window_s,
        event_match_tolerance_s=config.metrics.event_match_tolerance_s,
        peak_confirmation_s=config.inference.peak_confirmation_s,
    )
    plots_dir = destination.parent / f"{destination.stem}-plots"
    plots = save_probability_plots(
        evaluated_videos,
        threshold=selection.threshold,
        merge_window_s=config.inference.merge_window_s,
        output_dir=plots_dir,
    )
    threshold_plot = save_threshold_plot(
        selection.candidates,
        output_path=plots_dir / "threshold-tradeoff.png",
    )
    payload = _evaluation_payload(
        method="classical_motion_baseline",
        partition=partition,
        threshold=selection.threshold,
        overall=overall,
        per_video=per_video,
        plots=plots,
        threshold_plot=threshold_plot,
    )
    payload["config"] = str(Path(config_path))
    payload["threshold_source"] = "validation"
    payload["threshold_file"] = str(threshold_path)
    payload["max_f1"] = selection.max_f1
    payload["max_f1_threshold"] = selection.max_f1_threshold
    _save_evaluation(payload, destination)
    return payload
