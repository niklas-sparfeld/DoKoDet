from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from .annotation import AnnotationError, load_annotation
from .cache import CacheError, load_cache_metadata
from .evaluation import THRESHOLD_GRID as _THRESHOLD_GRID
from .evaluation import (
    EvaluationError,
    ScoredVideo,
    ThresholdSelection,
    evaluate_streams,
    load_threshold_selection,
    save_threshold_selection,
    save_validation_stream,
    select_threshold,
)
from .evaluation import event_f1 as _event_f1
from .events import probabilities_to_events
from .infer import InferenceError, LoadedCheckpoint, infer_cached_video, load_checkpoint
from .splits import SplitError, VideoSplit, load_split
from .transition_diagnostics import TransitionDiagnosticError, transition_diagnostics

_save_threshold_selection = save_threshold_selection
_load_threshold_selection = load_threshold_selection
THRESHOLD_GRID = _THRESHOLD_GRID
event_f1 = _event_f1

SAVED_PLOT_DPI = 280
REVIEW_TIMELINE_DPI = 220


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
        annotation_hash = hashlib.sha256(
            (annotation_root / f"{name}.json").read_bytes()
        ).hexdigest()
        confirmed_events = tuple(
            event for event in annotation.events if event.confidence in {None, "confirmed"}
        )
        videos.append(
            ScoredVideo(
                name=name,
                duration_s=duration_s,
                ground_truth_times_s=tuple(event.time_s for event in confirmed_events),
                probabilities=tuple(probabilities),
                ground_truth_types=tuple(event.type for event in confirmed_events),
                annotation_version_hash=annotation_hash,
            )
        )
    return videos


def _safe_plot_name(video_name: str) -> str:
    return Path(video_name).stem.replace("/", "_").replace("\\", "_")


def plot_probability_axis(
    axis: Any,
    *,
    times_s: Sequence[float],
    probabilities: Sequence[float],
    threshold: float,
    ground_truth_events: Sequence[Mapping[str, Any]] = (),
    predicted_events: Sequence[Mapping[str, Any]] = (),
    comparison_times_s: Sequence[float] = (),
    comparison_probabilities: Sequence[float] = (),
    comparison_predicted_events: Sequence[Mapping[str, Any]] = (),
    title: str | None = None,
) -> Any:
    """Draw one probability timeline on a Matplotlib axis.

    Evaluation plots and the interactive review timeline use this helper so
    their colours and event markers stay consistent.
    """
    axis.plot(times_s, probabilities, linewidth=1.0, label="probability")
    if len(comparison_times_s) and len(comparison_probabilities):
        axis.plot(
            comparison_times_s,
            comparison_probabilities,
            linewidth=0.9,
            alpha=0.7,
            color="tab:purple",
            label="comparison probability",
        )
    axis.axhline(threshold, color="tab:orange", linestyle="--", label="threshold")
    for index, event in enumerate(ground_truth_events):
        time_s = float(event["time_s"] if isinstance(event, Mapping) else event)
        axis.axvline(
            time_s,
            color="tab:green",
            alpha=0.55,
            label="ground truth" if index == 0 else None,
        )
    for index, event in enumerate(predicted_events):
        time_s = float(event["time_s"] if isinstance(event, Mapping) else event)
        axis.axvline(
            time_s,
            color="tab:red",
            alpha=0.65,
            linestyle=":",
            label="prediction" if index == 0 else None,
        )
    for index, event in enumerate(comparison_predicted_events):
        time_s = float(event["time_s"] if isinstance(event, Mapping) else event)
        axis.axvline(
            time_s,
            color="tab:purple",
            alpha=0.5,
            linestyle="-.",
            label="comparison prediction" if index == 0 else None,
        )
    if title:
        axis.set_title(title)
    axis.set_xlabel("time (s)")
    axis.set_ylabel("probability")
    axis.set_ylim(0.0, 1.0)
    axis.grid(alpha=0.2)
    axis.legend(loc="upper right")
    return axis


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
        times = [sample.time_s for sample in video.probabilities]
        probabilities = [sample.probability for sample in video.probabilities]
        figure, axis = plt.subplots(figsize=(12, 4))
        plot_probability_axis(
            axis,
            times_s=times,
            probabilities=probabilities,
            threshold=threshold,
            ground_truth_events=(
                {
                    "time_s": time_s,
                    "type": (
                        video.ground_truth_types[index]
                        if index < len(video.ground_truth_types)
                        else "card_played"
                    ),
                }
                for index, time_s in enumerate(video.ground_truth_times_s)
            ),
            predicted_events=(event.to_mapping() for event in events),
            title=f"CardEventNet probabilities: {video.name}",
        )
        figure.tight_layout()
        path = destination / f"{_safe_plot_name(video.name)}-probabilities.png"
        figure.savefig(path, dpi=SAVED_PLOT_DPI)
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
    figure.savefig(destination, dpi=SAVED_PLOT_DPI)
    plt.close(figure)
    return destination


def save_operating_plots(
    candidates: Sequence[Mapping[str, float]],
    *,
    selected_threshold: float,
    max_f1_threshold: float,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Save precision/recall and recall/false-event operating curves."""
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
    thresholds = [candidate["threshold"] for candidate in candidates]
    recalls = [candidate["event_recall"] for candidate in candidates]
    precisions = [candidate["event_precision"] for candidate in candidates]
    false_rates = [candidate["false_events_per_hour"] for candidate in candidates]

    def mark(axis: Any) -> None:
        for threshold, color, label in (
            (selected_threshold, "tab:green", "selected target-recall threshold"),
            (max_f1_threshold, "tab:orange", "maximum-F1 threshold"),
        ):
            try:
                index = thresholds.index(threshold)
            except ValueError:
                continue
            axis.scatter(
                [recalls[index]],
                [precisions[index]],
                color=color,
                zorder=3,
                label=label,
            )

    precision_recall_figure, precision_recall_axis = plt.subplots(figsize=(7, 5))
    precision_recall_axis.plot(recalls, precisions, marker=".", color="tab:blue")
    mark(precision_recall_axis)
    precision_recall_axis.set_xlabel("event recall")
    precision_recall_axis.set_ylabel("event precision")
    precision_recall_axis.set_xlim(0.0, 1.05)
    precision_recall_axis.set_ylim(0.0, 1.05)
    precision_recall_axis.grid(alpha=0.2)
    precision_recall_axis.legend(loc="best")
    precision_recall_figure.tight_layout()
    precision_recall_path = destination / "precision-recall.png"
    precision_recall_figure.savefig(precision_recall_path, dpi=SAVED_PLOT_DPI)
    plt.close(precision_recall_figure)

    recall_false_figure, recall_false_axis = plt.subplots(figsize=(7, 5))
    recall_false_axis.plot(recalls, false_rates, marker=".", color="tab:red")
    for threshold, color, label in (
        (selected_threshold, "tab:green", "selected target-recall threshold"),
        (max_f1_threshold, "tab:orange", "maximum-F1 threshold"),
    ):
        try:
            index = thresholds.index(threshold)
        except ValueError:
            continue
        recall_false_axis.scatter(
            [recalls[index]],
            [false_rates[index]],
            color=color,
            zorder=3,
            label=label,
        )
    recall_false_axis.set_xlabel("event recall")
    recall_false_axis.set_ylabel("false events/hour")
    recall_false_axis.set_xlim(0.0, 1.05)
    recall_false_axis.grid(alpha=0.2)
    recall_false_axis.legend(loc="best")
    recall_false_figure.tight_layout()
    recall_false_path = destination / "recall-false-events.png"
    recall_false_figure.savefig(recall_false_path, dpi=SAVED_PLOT_DPI)
    plt.close(recall_false_figure)
    return {
        "precision_recall": precision_recall_path,
        "recall_false_events": recall_false_path,
    }


def save_training_history_plot(
    rows: Sequence[Mapping[str, Any]],
    *,
    output_path: str | Path,
) -> Path:
    """Save the main training and calibrated validation history."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise EvaluationError(
            "matplotlib is required for training plots. Run `uv sync` to install it."
        ) from exc

    if not rows:
        raise EvaluationError("At least one training metric row is required.")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    epochs = [int(row["epoch"]) for row in rows]
    figure, axes = plt.subplots(2, 2, figsize=(11, 7))
    axes[0, 0].plot(epochs, [row["train_loss"] for row in rows], label="train loss")
    axes[0, 0].plot(epochs, [row["val_loss"] for row in rows], label="validation loss")
    axes[0, 0].set_title("Loss")
    axes[0, 0].legend()
    axes[0, 1].plot(
        epochs,
        [
            row.get("validation_selected_recall", row.get("validation_event_recall", 0.0))
            for row in rows
        ],
        label="recall",
    )
    axes[0, 1].plot(
        epochs,
        [
            row.get("validation_selected_precision", row.get("validation_precision", 0.0))
            for row in rows
        ],
        label="precision",
    )
    axes[0, 1].set_ylim(0.0, 1.05)
    axes[0, 1].set_title("Calibrated validation quality")
    axes[0, 1].legend()
    axes[1, 0].plot(
        epochs,
        [
            row.get(
                "validation_selected_false_events_per_hour",
                row.get("validation_false_events_per_hour", 0.0),
            )
            for row in rows
        ],
        label="false events/hour",
        color="tab:red",
    )
    axes[1, 0].set_title("Calibrated validation false events")
    axes[1, 0].legend()
    axes[1, 1].plot(
        epochs,
        [row.get("validation_selected_threshold", 0.5) for row in rows],
        label="selected threshold",
        color="tab:green",
    )
    axes[1, 1].set_ylim(0.0, 1.0)
    axes[1, 1].set_title("Selected threshold")
    axes[1, 1].legend()
    for axis in axes.flat:
        axis.set_xlabel("epoch")
        axis.grid(alpha=0.2)
    figure.tight_layout()
    figure.savefig(destination, dpi=SAVED_PLOT_DPI)
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


def _transition_diagnostics_path(evaluation_path: Path) -> Path:
    """Return the diagnostics path unique to one evaluation report."""
    return evaluation_path.parent / f"{evaluation_path.stem}-transition-diagnostics.json"


def format_report(payload: Mapping[str, Any]) -> str:
    overall = payload["overall"]
    timestamp_error_median_s = overall.get(
        "timestamp_error_median_s", overall.get("latency_median_s", 0.0)
    )
    timestamp_error_p95_s = overall.get("timestamp_error_p95_s", overall.get("latency_p95_s", 0.0))
    emission_latency_median_s = overall.get(
        "emission_latency_median_s",
        timestamp_error_median_s + overall.get("peak_confirmation_s", 0.0),
    )
    emission_latency_p95_s = overall.get(
        "emission_latency_p95_s",
        timestamp_error_p95_s + overall.get("peak_confirmation_s", 0.0),
    )
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
            f"F1:                 {overall.get('event_f1', 0.0):.2%}",
            f"Max F1:             {payload.get('max_f1', 0.0):.2%}",
            f"Timestamp error p50: {timestamp_error_median_s:.2f} s",
            f"Timestamp error p95: {timestamp_error_p95_s:.2f} s",
            f"Emission latency p50: {emission_latency_median_s:.2f} s",
            f"Emission latency p95: {emission_latency_p95_s:.2f} s",
            f"Threshold:          {payload['threshold']:.2f}",
            f"Max F1 threshold:   {payload.get('max_f1_threshold', 0.0):.2f}",
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
    reviewed_hard_negative_manifest: str | Path | None = None,
    threshold_override: float | None = None,
) -> dict[str, Any]:
    """Evaluate a checkpoint and select thresholds from validation data only."""
    try:
        split = load_split(split_path)
    except (OSError, SplitError, ValueError) as exc:
        raise EvaluationError(f"Could not load split: {exc}") from exc
    checkpoint_file = Path(checkpoint_path)
    try:
        loaded = load_checkpoint(checkpoint_file, device_override=device_override)
        peak_confirmation_s = getattr(loaded.config.inference, "peak_confirmation_s", 0.125)
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
            peak_confirmation_s=peak_confirmation_s,
        )
        if threshold_override is not None:
            if (
                isinstance(threshold_override, bool)
                or not isinstance(threshold_override, (int, float))
                or not isfinite(threshold_override)
                or not 0.0 <= threshold_override <= 1.0
            ):
                raise EvaluationError("threshold_override must be finite and between 0 and 1.")
            selection = replace(
                selection,
                threshold=float(threshold_override),
                selection_reason="explicit",
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
                peak_confirmation_s=peak_confirmation_s,
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
        peak_confirmation_s=peak_confirmation_s,
    )
    destination = (
        Path(output_path)
        if output_path is not None
        else (checkpoint_file.parent / f"evaluation-{partition}.json")
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
    operating_plots = save_operating_plots(
        selection.candidates,
        selected_threshold=selection.threshold,
        max_f1_threshold=selection.max_f1_threshold,
        output_dir=plots_dir,
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
    payload["max_f1"] = selection.max_f1
    payload["max_f1_threshold"] = selection.max_f1_threshold
    payload["operating_plots"] = {name: str(path) for name, path in operating_plots.items()}
    payload["target_recall"] = loaded.config.metrics.target_recall
    payload["target_recall_met"] = selection.target_recall_met
    payload["maximum_attainable_recall"] = selection.maximum_attainable_recall
    payload["selection_reason"] = selection.selection_reason
    validation_stream_path = save_validation_stream(
        validation_videos,
        destination.parent / "validation-streams" / "evaluation.json.gz",
    )
    payload["validation_stream"] = str(validation_stream_path)
    try:
        transition_payload = transition_diagnostics(
            validation_videos,
            threshold=selection.threshold,
            reviewed_hard_negative_manifest=reviewed_hard_negative_manifest,
        )
    except TransitionDiagnosticError as exc:
        raise EvaluationError(f"Could not create transition diagnostics: {exc}") from exc
    transition_path = _transition_diagnostics_path(destination)
    _save_evaluation(transition_payload, transition_path)
    payload["transition_diagnostics"] = str(transition_path)
    _save_evaluation(payload, destination)
    return payload


def diagnose_checkpoint_from_files(
    checkpoint_path: str | Path,
    split_path: str | Path,
    *,
    cache_dir: str | Path = "data/cache",
    annotations_dir: str | Path = "data/annotations",
    output_path: str | Path | None = None,
    device_override: str | None = None,
) -> dict[str, Any]:
    """Compare train and validation event behavior at a validation threshold."""
    try:
        split = load_split(split_path)
        checkpoint_file = Path(checkpoint_path)
        loaded = load_checkpoint(checkpoint_file, device_override=device_override)
        peak_confirmation_s = getattr(loaded.config.inference, "peak_confirmation_s", 0.125)
        validation_videos = load_model_streams(
            loaded,
            split,
            "val",
            cache_dir=cache_dir,
            annotations_dir=annotations_dir,
        )
        selection = select_threshold(
            validation_videos,
            merge_window_s=loaded.config.inference.merge_window_s,
            event_match_tolerance_s=loaded.config.metrics.event_match_tolerance_s,
            target_recall=loaded.config.metrics.target_recall,
            peak_confirmation_s=peak_confirmation_s,
        )
        save_threshold_selection(
            checkpoint_file,
            selection,
            merge_window_s=loaded.config.inference.merge_window_s,
            event_match_tolerance_s=loaded.config.metrics.event_match_tolerance_s,
            target_recall=loaded.config.metrics.target_recall,
        )
        train_videos = load_model_streams(
            loaded,
            split,
            "train",
            cache_dir=cache_dir,
            annotations_dir=annotations_dir,
        )
    except (OSError, SplitError, ValueError, InferenceError, EvaluationError) as exc:
        raise EvaluationError(f"Could not diagnose checkpoint: {exc}") from exc

    evaluation_options = {
        "threshold": selection.threshold,
        "merge_window_s": loaded.config.inference.merge_window_s,
        "event_match_tolerance_s": loaded.config.metrics.event_match_tolerance_s,
        "peak_confirmation_s": peak_confirmation_s,
        "include_streams": False,
    }
    train_overall, train_per_video = evaluate_streams(train_videos, **evaluation_options)
    validation_overall, validation_per_video = evaluate_streams(
        validation_videos,
        **evaluation_options,
    )
    plots_dir = (
        Path(output_path).parent / f"{Path(output_path).stem}-plots"
        if output_path is not None
        else checkpoint_file.parent / "diagnostics-plots"
    )
    operating_plots = save_operating_plots(
        selection.candidates,
        selected_threshold=selection.threshold,
        max_f1_threshold=selection.max_f1_threshold,
        output_dir=plots_dir,
    )
    payload: dict[str, Any] = {
        "method": "cardeventnet_train_validation_diagnostics",
        "checkpoint": str(checkpoint_file),
        "split": str(Path(split_path)),
        "partition": {"train": "train", "validation": "val"},
        "threshold": selection.threshold,
        "threshold_source": "validation",
        "threshold_selection": {
            "selected_metrics": selection.metrics,
            "max_f1": selection.max_f1,
            "max_f1_threshold": selection.max_f1_threshold,
            "candidates": list(selection.candidates),
        },
        "train": train_overall,
        "validation": validation_overall,
        "val": validation_overall,
        "generalization_gap": {
            "recall": train_overall["event_recall"] - validation_overall["event_recall"],
            "precision": train_overall["event_precision"] - validation_overall["event_precision"],
        },
        "videos": {
            "train": train_per_video,
            "validation": validation_per_video,
        },
        "operating_plots": {name: str(path) for name, path in operating_plots.items()},
    }
    destination = (
        Path(output_path)
        if output_path is not None
        else checkpoint_file.parent / "diagnostics.json"
    )
    _save_evaluation(payload, destination)
    return payload
