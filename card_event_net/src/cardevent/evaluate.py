from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np

from .annotation import AnnotationError, load_annotation
from .cache import CacheError, load_cache_metadata
from .events import (
    EventMatchResult,
    ProbabilitySample,
    match_events,
    probabilities_to_events,
)
from .infer import InferenceError, LoadedCheckpoint, infer_cached_video, load_checkpoint
from .splits import SplitError, VideoSplit, load_split


class EvaluationError(RuntimeError):
    """Raised when inference or event evaluation cannot be completed."""


THRESHOLD_GRID: tuple[float, ...] = tuple(round(0.10 + index * 0.05, 2) for index in range(18))


@dataclass(frozen=True, slots=True)
class ScoredVideo:
    name: str
    duration_s: float
    ground_truth_times_s: tuple[float, ...]
    probabilities: tuple[ProbabilitySample, ...]


@dataclass(frozen=True, slots=True)
class ThresholdSelection:
    threshold: float
    metrics: dict[str, float]
    candidates: tuple[dict[str, float], ...]


def _partition_names(split: VideoSplit, partition: str) -> tuple[str, ...]:
    if partition not in {"train", "val", "test"}:
        raise EvaluationError("partition must be one of: train, val, test")
    names = getattr(split, partition)
    if not names:
        raise EvaluationError(f"The {partition} split is empty.")
    return names


def _annotation_and_cache(
    name: str,
    *,
    cache_dir: Path,
    annotations_dir: Path,
) -> tuple[Path, Any, float]:
    cache_path = cache_dir / name
    try:
        metadata = load_cache_metadata(cache_path)
    except CacheError as exc:
        raise EvaluationError(
            f"Missing or invalid cache for {name}: {exc}. "
            "Run `cardevent prepare --videos ...` first."
        ) from exc

    annotation_path = annotations_dir / f"{name}.json"
    if not annotation_path.is_file():
        raise EvaluationError(f"Missing annotation for {name}: {annotation_path}")
    try:
        annotation = load_annotation(annotation_path)
    except AnnotationError as exc:
        raise EvaluationError(f"Could not load annotation for {name}: {exc}") from exc
    if Path(metadata.source_video).stem != name:
        raise EvaluationError(
            f"Cache source video does not match split name {name}: {metadata.source_video}"
        )
    return cache_path, annotation, metadata.duration_s


def load_model_streams(
    loaded: LoadedCheckpoint,
    split: VideoSplit,
    partition: str,
    *,
    cache_dir: str | Path = "data/cache",
    annotations_dir: str | Path = "data/annotations",
) -> list[ScoredVideo]:
    """Run full-video model inference for every video in one split partition."""
    videos: list[ScoredVideo] = []
    cache_root = Path(cache_dir)
    annotation_root = Path(annotations_dir)
    for name in _partition_names(split, partition):
        cache_path, annotation, duration_s = _annotation_and_cache(
            name,
            cache_dir=cache_root,
            annotations_dir=annotation_root,
        )
        try:
            probabilities = infer_cached_video(loaded, cache_path)
        except InferenceError as exc:
            raise EvaluationError(f"Could not infer validation video {name}: {exc}") from exc
        videos.append(
            ScoredVideo(
                name=name,
                duration_s=duration_s,
                ground_truth_times_s=tuple(event.time_s for event in annotation.events),
                probabilities=tuple(probabilities),
            )
        )
    return videos


def _metrics_from_match(
    match: EventMatchResult,
    *,
    duration_s: float,
    latencies_s: Sequence[float] | None = None,
) -> dict[str, float]:
    latencies = tuple(match.latencies_s if latencies_s is None else latencies_s)
    duration_hours = duration_s / 3600.0
    return {
        "duration_s": duration_s,
        "duration_hours": duration_hours,
        "real_events": float(match.real_events),
        "detected_true_events": float(match.detected_true_events),
        "missed_events": float(match.missed_events),
        "false_events": float(match.false_events),
        "event_recall": (
            match.detected_true_events / match.real_events if match.real_events else 0.0
        ),
        "event_precision": (
            match.detected_true_events / (match.detected_true_events + match.false_events)
            if match.detected_true_events + match.false_events
            else 0.0
        ),
        "false_events_per_hour": (
            match.false_events / duration_hours if duration_hours > 0.0 else 0.0
        ),
        "latency_median_s": median(latencies) if latencies else 0.0,
        "latency_p95_s": float(np.percentile(latencies, 95)) if latencies else 0.0,
    }


def evaluate_streams(
    videos: Sequence[ScoredVideo],
    *,
    threshold: float,
    merge_window_s: float,
    event_match_tolerance_s: float,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Evaluate probability streams at one threshold."""
    if not videos:
        raise EvaluationError("No videos were provided for evaluation.")

    per_video: list[dict[str, Any]] = []
    total_duration_s = 0.0
    total_real_events = 0
    total_detected_true_events = 0
    total_missed_events = 0
    total_false_events = 0
    all_latencies: list[float] = []

    for video in videos:
        detected_events = probabilities_to_events(
            video.probabilities,
            threshold=threshold,
            merge_window_s=merge_window_s,
        )
        match = match_events(
            detected_events,
            video.ground_truth_times_s,
            tolerance_s=event_match_tolerance_s,
        )
        metrics = _metrics_from_match(match, duration_s=video.duration_s)
        per_video.append(
            {
                "video": video.name,
                **metrics,
                "ground_truth_events_s": list(video.ground_truth_times_s),
                "probabilities": [sample.to_mapping() for sample in video.probabilities],
                "predicted_events": [event.to_mapping() for event in detected_events],
            }
        )
        total_duration_s += video.duration_s
        total_real_events += match.real_events
        total_detected_true_events += match.detected_true_events
        total_missed_events += match.missed_events
        total_false_events += match.false_events
        all_latencies.extend(match.latencies_s)

    total_duration_hours = total_duration_s / 3600.0
    overall = {
        "videos": float(len(videos)),
        "duration_s": total_duration_s,
        "duration_hours": total_duration_hours,
        "real_events": float(total_real_events),
        "detected_true_events": float(total_detected_true_events),
        "missed_events": float(total_missed_events),
        "false_events": float(total_false_events),
        "event_recall": (
            total_detected_true_events / total_real_events if total_real_events else 0.0
        ),
        "event_precision": (
            total_detected_true_events / (total_detected_true_events + total_false_events)
            if total_detected_true_events + total_false_events
            else 0.0
        ),
        "false_events_per_hour": (
            total_false_events / total_duration_hours if total_duration_hours > 0.0 else 0.0
        ),
        "latency_median_s": median(all_latencies) if all_latencies else 0.0,
        "latency_p95_s": float(np.percentile(all_latencies, 95)) if all_latencies else 0.0,
    }
    return overall, per_video


def _threshold_rank(metrics: Mapping[str, float], target_recall: float) -> tuple[float, ...]:
    recall = metrics["event_recall"]
    false_events_per_hour = metrics["false_events_per_hour"]
    if recall >= target_recall:
        return (1.0, -false_events_per_hour, metrics["event_precision"])
    return (0.0, recall, -false_events_per_hour, metrics["event_precision"])


def select_threshold(
    videos: Sequence[ScoredVideo],
    *,
    merge_window_s: float,
    event_match_tolerance_s: float,
    target_recall: float,
    thresholds: Sequence[float] = THRESHOLD_GRID,
) -> ThresholdSelection:
    """Select a threshold using validation event behavior only."""
    if not 0.0 <= target_recall <= 1.0 or not isfinite(target_recall):
        raise EvaluationError("target_recall must be between 0 and 1.")
    if not thresholds:
        raise EvaluationError("At least one threshold is required.")

    candidates: list[dict[str, float]] = []
    for threshold in thresholds:
        if not isfinite(threshold):
            raise EvaluationError("Threshold candidates must be finite.")
        metrics, _ = evaluate_streams(
            videos,
            threshold=threshold,
            merge_window_s=merge_window_s,
            event_match_tolerance_s=event_match_tolerance_s,
        )
        candidates.append({"threshold": float(threshold), **metrics})

    selected = max(
        candidates,
        key=lambda candidate: _threshold_rank(candidate, target_recall),
    )
    return ThresholdSelection(
        threshold=selected["threshold"],
        metrics={key: value for key, value in selected.items() if key != "threshold"},
        candidates=tuple(candidates),
    )


def _threshold_path(checkpoint_path: Path) -> Path:
    return checkpoint_path.with_name("threshold.json")


def _save_threshold_selection(
    checkpoint_path: Path,
    selection: ThresholdSelection,
    *,
    merge_window_s: float,
    event_match_tolerance_s: float,
    target_recall: float,
) -> Path:
    path = _threshold_path(checkpoint_path)
    payload = {
        "checkpoint": str(checkpoint_path),
        "threshold": selection.threshold,
        "merge_window_s": merge_window_s,
        "event_match_tolerance_s": event_match_tolerance_s,
        "target_recall": target_recall,
        "validation_metrics": selection.metrics,
        "candidates": list(selection.candidates),
    }
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


def _load_threshold_selection(checkpoint_path: Path) -> ThresholdSelection:
    path = _threshold_path(checkpoint_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        threshold = float(payload["threshold"])
        metrics = dict(payload["validation_metrics"])
        candidates = tuple(dict(candidate) for candidate in payload["candidates"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise EvaluationError(
            f"Could not load the validation threshold from {path}. "
            "Run evaluation on the val partition first."
        ) from exc
    return ThresholdSelection(threshold=threshold, metrics=metrics, candidates=candidates)


def _safe_plot_name(video_name: str) -> str:
    return Path(video_name).stem.replace("/", "_").replace("\\", "_")


def save_probability_plots(
    videos: Sequence[ScoredVideo],
    *,
    threshold: float,
    merge_window_s: float,
    output_dir: str | Path,
) -> list[Path]:
    """Save one probability-over-time plot per evaluated video."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise EvaluationError(
            "matplotlib is required for evaluation plots. Run `uv sync` to install it."
        ) from exc

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for video in videos:
        events = probabilities_to_events(
            video.probabilities,
            threshold=threshold,
            merge_window_s=merge_window_s,
        )
        figure, axis = plt.subplots(figsize=(12, 4))
        times = [sample.time_s for sample in video.probabilities]
        probabilities = [sample.probability for sample in video.probabilities]
        axis.plot(times, probabilities, linewidth=1.0, label="probability")
        axis.axhline(threshold, color="tab:orange", linestyle="--", label="threshold")
        for index, time_s in enumerate(video.ground_truth_times_s):
            axis.axvline(
                time_s,
                color="tab:green",
                alpha=0.55,
                label="ground truth" if index == 0 else None,
            )
        for index, event in enumerate(events):
            axis.axvline(
                event.time_s,
                color="tab:red",
                alpha=0.65,
                linestyle=":",
                label="prediction" if index == 0 else None,
            )
        axis.set_title(f"CardEventNet probabilities: {video.name}")
        axis.set_xlabel("time (s)")
        axis.set_ylabel("probability")
        axis.set_ylim(0.0, 1.0)
        axis.grid(alpha=0.2)
        axis.legend(loc="upper right")
        figure.tight_layout()
        path = destination / f"{_safe_plot_name(video.name)}-probabilities.png"
        figure.savefig(path, dpi=140)
        plt.close(figure)
        paths.append(path)
    return paths


def save_threshold_plot(
    candidates: Sequence[Mapping[str, float]],
    *,
    output_path: str | Path,
) -> Path:
    """Save validation recall and false-event tradeoffs for all thresholds."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise EvaluationError(
            "matplotlib is required for evaluation plots. Run `uv sync` to install it."
        ) from exc

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    thresholds = [candidate["threshold"] for candidate in candidates]
    recalls = [candidate["event_recall"] for candidate in candidates]
    false_rates = [candidate["false_events_per_hour"] for candidate in candidates]
    figure, recall_axis = plt.subplots(figsize=(8, 5))
    false_axis = recall_axis.twinx()
    recall_axis.plot(thresholds, recalls, marker="o", color="tab:blue", label="recall")
    false_axis.plot(
        thresholds,
        false_rates,
        marker="x",
        color="tab:red",
        label="false events/hour",
    )
    recall_axis.set_xlabel("threshold")
    recall_axis.set_ylabel("event recall", color="tab:blue")
    false_axis.set_ylabel("false events/hour", color="tab:red")
    recall_axis.set_ylim(0.0, 1.05)
    recall_axis.grid(alpha=0.2)
    figure.suptitle("Validation threshold tradeoff")
    figure.tight_layout()
    figure.savefig(destination, dpi=140)
    plt.close(figure)
    return destination


def _evaluation_payload(
    *,
    method: str,
    partition: str,
    threshold: float,
    overall: Mapping[str, float],
    per_video: Sequence[Mapping[str, Any]],
    plots: Sequence[Path],
    threshold_plot: Path,
) -> dict[str, Any]:
    return {
        "method": method,
        "partition": partition,
        "threshold": threshold,
        "overall": dict(overall),
        "videos": [dict(video) for video in per_video],
        "plots": [str(path) for path in plots],
        "threshold_plot": str(threshold_plot),
    }


def _save_evaluation(payload: Mapping[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


def format_report(payload: Mapping[str, Any]) -> str:
    overall = payload["overall"]
    return "\n".join(
        (
            f"Videos:             {int(overall['videos'])}",
            f"Duration:           {overall['duration_hours']:.2f} h",
            f"True events:        {int(overall['real_events'])}",
            f"Detected:           {int(overall['detected_true_events'])}",
            f"Missed:             {int(overall['missed_events'])}",
            f"False detections:   {int(overall['false_events'])}",
            f"Recall:             {overall['event_recall']:.2%}",
            f"Precision:          {overall['event_precision']:.2%}",
            f"False/hour:         {overall['false_events_per_hour']:.2f}",
            f"Latency p50:        {overall['latency_median_s']:.2f} s",
            f"Latency p95:        {overall['latency_p95_s']:.2f} s",
            f"Threshold:          {payload['threshold']:.2f}",
        )
    )


def evaluate_checkpoint_from_files(
    checkpoint_path: str | Path,
    split_path: str | Path,
    *,
    partition: str,
    cache_dir: str | Path = "data/cache",
    annotations_dir: str | Path = "data/annotations",
    output_path: str | Path | None = None,
    device_override: str | None = None,
) -> dict[str, Any]:
    """Evaluate a checkpoint and select thresholds from validation data only."""
    try:
        split = load_split(split_path)
    except (OSError, SplitError, ValueError) as exc:
        raise EvaluationError(f"Could not load split: {exc}") from exc
    checkpoint_file = Path(checkpoint_path)
    try:
        loaded = load_checkpoint(checkpoint_file, device_override=device_override)
        validation_videos = load_model_streams(
            loaded,
            split,
            "val",
            cache_dir=cache_dir,
            annotations_dir=annotations_dir,
        )
    except (InferenceError, EvaluationError) as exc:
        raise EvaluationError(str(exc)) from exc

    selection: ThresholdSelection
    if partition == "val":
        selection = select_threshold(
            validation_videos,
            merge_window_s=loaded.config.inference.merge_window_s,
            event_match_tolerance_s=loaded.config.metrics.event_match_tolerance_s,
            target_recall=loaded.config.metrics.target_recall,
        )
        _save_threshold_selection(
            checkpoint_file,
            selection,
            merge_window_s=loaded.config.inference.merge_window_s,
            event_match_tolerance_s=loaded.config.metrics.event_match_tolerance_s,
            target_recall=loaded.config.metrics.target_recall,
        )
        evaluated_videos = validation_videos
    else:
        try:
            selection = _load_threshold_selection(checkpoint_file)
        except EvaluationError:
            selection = select_threshold(
                validation_videos,
                merge_window_s=loaded.config.inference.merge_window_s,
                event_match_tolerance_s=loaded.config.metrics.event_match_tolerance_s,
                target_recall=loaded.config.metrics.target_recall,
            )
            _save_threshold_selection(
                checkpoint_file,
                selection,
                merge_window_s=loaded.config.inference.merge_window_s,
                event_match_tolerance_s=loaded.config.metrics.event_match_tolerance_s,
                target_recall=loaded.config.metrics.target_recall,
            )
        try:
            evaluated_videos = load_model_streams(
                loaded,
                split,
                partition,
                cache_dir=cache_dir,
                annotations_dir=annotations_dir,
            )
        except (InferenceError, EvaluationError) as exc:
            raise EvaluationError(str(exc)) from exc

    overall, per_video = evaluate_streams(
        evaluated_videos,
        threshold=selection.threshold,
        merge_window_s=loaded.config.inference.merge_window_s,
        event_match_tolerance_s=loaded.config.metrics.event_match_tolerance_s,
    )
    destination = Path(output_path) if output_path is not None else (
        checkpoint_file.parent / f"evaluation-{partition}.json"
    )
    plots_dir = destination.parent / f"{destination.stem}-plots"
    plots = save_probability_plots(
        evaluated_videos,
        threshold=selection.threshold,
        merge_window_s=loaded.config.inference.merge_window_s,
        output_dir=plots_dir,
    )
    threshold_plot = save_threshold_plot(
        selection.candidates,
        output_path=plots_dir / "threshold-tradeoff.png",
    )
    payload = _evaluation_payload(
        method="cardeventnet",
        partition=partition,
        threshold=selection.threshold,
        overall=overall,
        per_video=per_video,
        plots=plots,
        threshold_plot=threshold_plot,
    )
    payload["checkpoint"] = str(checkpoint_file)
    payload["threshold_source"] = "validation"
    payload["validation_threshold_metrics"] = selection.metrics
    _save_evaluation(payload, destination)
    return payload
