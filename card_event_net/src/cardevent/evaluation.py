from __future__ import annotations

import gzip
import json
import math
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np

from .events import (
    DetectedEvent,
    EventMatchResult,
    ProbabilitySample,
    candidate_peaks,
    match_events,
    probabilities_to_events,
)


class EvaluationError(RuntimeError):
    """Raised when event evaluation cannot be completed."""


# Kept for import compatibility. Calibration now uses candidate-peak scores.
THRESHOLD_GRID: tuple[float, ...] = tuple(round(index / 100, 2) for index in range(1, 100))


@dataclass(frozen=True, slots=True)
class ScoredVideo:
    """One video probability stream and its event annotations."""

    name: str
    duration_s: float
    ground_truth_times_s: tuple[float, ...]
    probabilities: tuple[ProbabilitySample, ...]
    ground_truth_types: tuple[str, ...] = ()
    annotation_version_hash: str | None = None


@dataclass(frozen=True, slots=True)
class ThresholdSelection:
    """The operating point selected from validation event behavior."""

    threshold: float
    metrics: dict[str, float]
    candidates: tuple[dict[str, float], ...]
    max_f1: float = 0.0
    max_f1_threshold: float = 0.0
    target_recall_met: bool = False
    maximum_attainable_recall: float = 0.0
    selection_reason: str = "fallback_max_f1"


def event_f1(precision: float, recall: float) -> float:
    """Return event F1, including the defined zero case."""
    if precision + recall == 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _metrics_from_match(
    match: EventMatchResult,
    *,
    duration_s: float,
    peak_confirmation_s: float,
    latencies_s: Sequence[float] | None = None,
) -> dict[str, float]:
    latencies = tuple(match.latencies_s if latencies_s is None else latencies_s)
    emission_latencies = tuple(
        matched.emission_latency_s
        if matched.emission_latency_s is not None
        else latency + peak_confirmation_s
        for latency, matched in zip(latencies, match.matches, strict=True)
    )
    duration_hours = duration_s / 3600.0
    recall = match.detected_true_events / match.real_events if match.real_events else 0.0
    precision = (
        match.detected_true_events / (match.detected_true_events + match.false_events)
        if match.detected_true_events + match.false_events
        else 0.0
    )
    timestamp_error_median_s = median(latencies) if latencies else 0.0
    timestamp_error_p95_s = float(np.percentile(latencies, 95)) if latencies else 0.0
    emission_latency_median_s = median(emission_latencies) if emission_latencies else 0.0
    emission_latency_p95_s = (
        float(np.percentile(emission_latencies, 95)) if emission_latencies else 0.0
    )
    return {
        "duration_s": duration_s,
        "duration_hours": duration_hours,
        "real_events": float(match.real_events),
        "detected_true_events": float(match.detected_true_events),
        "missed_events": float(match.missed_events),
        "false_events": float(match.false_events),
        "event_recall": recall,
        "event_precision": precision,
        "event_f1": event_f1(precision, recall),
        "false_events_per_hour": (
            match.false_events / duration_hours if duration_hours > 0.0 else 0.0
        ),
        "peak_confirmation_s": peak_confirmation_s,
        "timestamp_error_median_s": timestamp_error_median_s,
        "timestamp_error_p95_s": timestamp_error_p95_s,
        "emission_latency_median_s": emission_latency_median_s,
        "emission_latency_p95_s": emission_latency_p95_s,
        # Compatibility aliases. These have always meant signed peak timestamp
        # error, not the time at which an online event becomes available.
        "latency_median_s": timestamp_error_median_s,
        "latency_p95_s": timestamp_error_p95_s,
    }


def _max_probability_near_event(
    probabilities: Sequence[ProbabilitySample],
    event_time_s: float,
    radius_s: float,
) -> float:
    nearby = (
        sample.probability
        for sample in probabilities
        if abs(sample.time_s - event_time_s) <= radius_s
    )
    return max(nearby, default=0.0)


def _failure_details(
    video: ScoredVideo,
    predicted_events: Sequence[DetectedEvent],
    match: EventMatchResult,
    *,
    threshold: float,
    merge_window_s: float,
    event_match_tolerance_s: float,
) -> tuple[list[dict[str, float | str]], list[dict[str, float]]]:
    missed: list[dict[str, float | str]] = []
    ground_truth_times = tuple(sorted(video.ground_truth_times_s))
    for ground_truth_index in match.unmatched_ground_truth_indices:
        ground_truth_time_s = ground_truth_times[ground_truth_index]
        max_probability = _max_probability_near_event(
            video.probabilities,
            ground_truth_time_s,
            event_match_tolerance_s,
        )
        has_prediction_in_tolerance = any(
            abs(event.time_s - ground_truth_time_s) <= event_match_tolerance_s
            for event in predicted_events
        )
        has_prediction_nearby = any(
            event_match_tolerance_s
            < abs(event.time_s - ground_truth_time_s)
            <= max(merge_window_s, event_match_tolerance_s)
            for event in predicted_events
        )
        if has_prediction_in_tolerance:
            category = "merged_event"
        elif has_prediction_nearby or max_probability >= threshold:
            category = "near_miss"
        else:
            category = "missed_completely"
        missed.append(
            {
                "ground_truth_time_s": ground_truth_time_s,
                "max_probability_near_event": max_probability,
                "category": category,
            }
        )

    false_events = [
        {
            "predicted_time_s": predicted_events[index].time_s,
            "probability": predicted_events[index].probability,
        }
        for index in match.unmatched_predicted_indices
    ]
    return missed, false_events


def evaluate_streams(
    videos: Sequence[ScoredVideo],
    *,
    threshold: float,
    merge_window_s: float,
    event_match_tolerance_s: float,
    peak_confirmation_s: float = 0.125,
    include_streams: bool = True,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Evaluate saved probability streams at one threshold.

    The model is not called here. This function only decodes and matches the
    probability streams, so it is suitable for threshold sweeps.
    """
    if not videos:
        raise EvaluationError("No videos were provided for evaluation.")
    if peak_confirmation_s < 0.0 or not isfinite(peak_confirmation_s):
        raise EvaluationError("peak_confirmation_s must be finite and non-negative.")

    per_video: list[dict[str, Any]] = []
    total_duration_s = 0.0
    total_real_events = 0
    total_detected_true_events = 0
    total_missed_events = 0
    total_false_events = 0
    all_latencies: list[float] = []
    all_emission_latencies: list[float] = []

    for video in videos:
        detected_events = probabilities_to_events(
            video.probabilities,
            threshold=threshold,
            merge_window_s=merge_window_s,
            peak_confirmation_s=peak_confirmation_s,
        )
        match = match_events(
            detected_events,
            video.ground_truth_times_s,
            tolerance_s=event_match_tolerance_s,
        )
        metrics = _metrics_from_match(
            match,
            duration_s=video.duration_s,
            peak_confirmation_s=peak_confirmation_s,
        )
        missed_details, false_details = _failure_details(
            video,
            detected_events,
            match,
            threshold=threshold,
            merge_window_s=merge_window_s,
            event_match_tolerance_s=event_match_tolerance_s,
        )
        video_payload: dict[str, Any] = {
            "video": video.name,
            **metrics,
            "event_count": int(match.real_events),
            "detected_count": int(match.detected_true_events),
            "missed_count": int(match.missed_events),
            "false_count": int(match.false_events),
            "recall": metrics["event_recall"],
            "precision": metrics["event_precision"],
            "false_events_per_hour": metrics["false_events_per_hour"],
            "latency_p50_s": metrics["latency_median_s"],
            "latency_p95_s": metrics["latency_p95_s"],
            "missed_event_details": missed_details,
            "false_event_details": false_details,
            "failure_manifest": {
                "missed_events": missed_details,
                "false_events": false_details,
            },
        }
        if include_streams:
            video_payload.update(
                {
                    "ground_truth_events_s": list(video.ground_truth_times_s),
                    "probabilities": [sample.to_mapping() for sample in video.probabilities],
                    "predicted_events": [event.to_mapping() for event in detected_events],
                }
            )
        per_video.append(video_payload)
        total_duration_s += video.duration_s
        total_real_events += match.real_events
        total_detected_true_events += match.detected_true_events
        total_missed_events += match.missed_events
        total_false_events += match.false_events
        all_latencies.extend(match.latencies_s)
        all_emission_latencies.extend(
            matched.emission_latency_s
            if matched.emission_latency_s is not None
            else matched.latency_s + peak_confirmation_s
            for matched in match.matches
        )

    total_duration_hours = total_duration_s / 3600.0
    recall = total_detected_true_events / total_real_events if total_real_events else 0.0
    precision = (
        total_detected_true_events / (total_detected_true_events + total_false_events)
        if total_detected_true_events + total_false_events
        else 0.0
    )
    timestamp_error_median_s = median(all_latencies) if all_latencies else 0.0
    timestamp_error_p95_s = float(np.percentile(all_latencies, 95)) if all_latencies else 0.0
    emission_latencies = tuple(all_emission_latencies)
    emission_latency_median_s = median(emission_latencies) if emission_latencies else 0.0
    emission_latency_p95_s = (
        float(np.percentile(emission_latencies, 95)) if emission_latencies else 0.0
    )
    overall = {
        "videos": float(len(videos)),
        "duration_s": total_duration_s,
        "duration_hours": total_duration_hours,
        "real_events": float(total_real_events),
        "detected_true_events": float(total_detected_true_events),
        "missed_events": float(total_missed_events),
        "false_events": float(total_false_events),
        "event_recall": recall,
        "event_precision": precision,
        "event_f1": event_f1(precision, recall),
        "false_events_per_hour": (
            total_false_events / total_duration_hours if total_duration_hours > 0.0 else 0.0
        ),
        "peak_confirmation_s": peak_confirmation_s,
        "timestamp_error_median_s": timestamp_error_median_s,
        "timestamp_error_p95_s": timestamp_error_p95_s,
        "emission_latency_median_s": emission_latency_median_s,
        "emission_latency_p95_s": emission_latency_p95_s,
        # Compatibility aliases. These have always meant signed peak timestamp
        # error, not the time at which an online event becomes available.
        "latency_median_s": timestamp_error_median_s,
        "latency_p95_s": timestamp_error_p95_s,
    }
    return overall, per_video


def _threshold_rank(metrics: Mapping[str, float], target_recall: float) -> tuple[float, ...]:
    if metrics["event_recall"] >= target_recall:
        return (1.0, -metrics["false_events_per_hour"], metrics["event_precision"])
    return (0.0, metrics["event_f1"], metrics["event_recall"], metrics["event_precision"])


def _candidate_thresholds(
    videos: Sequence[ScoredVideo],
    *,
    merge_window_s: float,
) -> tuple[float, ...]:
    scores = {
        event.probability
        for video in videos
        for event in candidate_peaks(video.probabilities, min_event_gap_s=merge_window_s)
    }
    # Include one value above all scores to represent an empty event set.
    if not scores:
        return (1.0,)
    return tuple(sorted(scores | {math.nextafter(max(scores), math.inf)}, reverse=True))


def select_threshold(
    videos: Sequence[ScoredVideo],
    *,
    merge_window_s: float,
    event_match_tolerance_s: float,
    target_recall: float,
    peak_confirmation_s: float = 0.125,
    thresholds: Sequence[float] | None = None,
) -> ThresholdSelection:
    """Select a threshold from validation event behavior only."""
    if not 0.0 <= target_recall <= 1.0 or not isfinite(target_recall):
        raise EvaluationError("target_recall must be between 0 and 1.")
    if thresholds is None:
        thresholds = _candidate_thresholds(videos, merge_window_s=merge_window_s)
    if not thresholds:
        raise EvaluationError("At least one threshold is required.")

    candidates: list[dict[str, float]] = []
    for threshold in thresholds:
        if not isfinite(threshold) or threshold < 0.0:
            raise EvaluationError("Threshold candidates must be finite and non-negative.")
        metrics, _ = evaluate_streams(
            videos,
            threshold=threshold,
            merge_window_s=merge_window_s,
            event_match_tolerance_s=event_match_tolerance_s,
            peak_confirmation_s=peak_confirmation_s,
            include_streams=False,
        )
        candidates.append({"threshold": float(threshold), **metrics})

    target_candidates = [
        candidate for candidate in candidates if candidate["event_recall"] >= target_recall
    ]
    target_recall_met = bool(target_candidates)
    selected = (
        max(target_candidates, key=lambda candidate: _threshold_rank(candidate, target_recall))
        if target_candidates
        else max(
            candidates,
            key=lambda candidate: (
                candidate["event_f1"],
                candidate["event_recall"],
                candidate["event_precision"],
                -candidate["false_events_per_hour"],
                candidate["threshold"],
            ),
        )
    )
    max_f1_candidate = max(
        candidates,
        key=lambda candidate: (
            candidate["event_f1"],
            candidate["event_recall"],
            candidate["event_precision"],
            -candidate["false_events_per_hour"],
        ),
    )
    return ThresholdSelection(
        threshold=selected["threshold"],
        metrics={key: value for key, value in selected.items() if key != "threshold"},
        candidates=tuple(candidates),
        max_f1=max_f1_candidate["event_f1"],
        max_f1_threshold=max_f1_candidate["threshold"],
        target_recall_met=target_recall_met,
        maximum_attainable_recall=max(
            (candidate["event_recall"] for candidate in candidates), default=0.0
        ),
        selection_reason="target_recall_lowest_false_events_per_hour"
        if target_recall_met
        else "fallback_max_f1",
    )


def threshold_selection_to_mapping(selection: ThresholdSelection) -> dict[str, Any]:
    return {
        "threshold": selection.threshold,
        "metrics": dict(selection.metrics),
        "candidates": [dict(candidate) for candidate in selection.candidates],
        "max_f1": selection.max_f1,
        "max_f1_threshold": selection.max_f1_threshold,
        "target_recall_met": selection.target_recall_met,
        "maximum_attainable_recall": selection.maximum_attainable_recall,
        "selection_reason": selection.selection_reason,
    }


def threshold_selection_from_mapping(mapping: Mapping[str, Any]) -> ThresholdSelection:
    try:
        candidates = tuple(dict(candidate) for candidate in mapping["candidates"])
        metrics = dict(mapping["metrics"])
        threshold = float(mapping["threshold"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EvaluationError("Invalid threshold selection data.") from exc
    max_f1_candidate = max(
        candidates,
        key=lambda candidate: (
            candidate.get(
                "event_f1",
                event_f1(
                    candidate.get("event_precision", 0.0),
                    candidate.get("event_recall", 0.0),
                ),
            ),
            candidate.get("event_recall", 0.0),
            candidate.get("event_precision", 0.0),
            -candidate.get("false_events_per_hour", 0.0),
        ),
        default={"event_f1": 0.0, "threshold": 0.0},
    )
    return ThresholdSelection(
        threshold=threshold,
        metrics=metrics,
        candidates=candidates,
        max_f1=float(
            mapping.get(
                "max_f1",
                max_f1_candidate.get(
                    "event_f1",
                    event_f1(
                        max_f1_candidate.get("event_precision", 0.0),
                        max_f1_candidate.get("event_recall", 0.0),
                    ),
                ),
            )
        ),
        max_f1_threshold=float(
            mapping.get("max_f1_threshold", max_f1_candidate.get("threshold", 0.0))
        ),
        target_recall_met=bool(
            mapping.get("target_recall_met", metrics.get("event_recall", 0.0) >= 0.98)
        ),
        maximum_attainable_recall=float(
            mapping.get(
                "maximum_attainable_recall",
                max((candidate.get("event_recall", 0.0) for candidate in candidates), default=0.0),
            )
        ),
        selection_reason=str(mapping.get("selection_reason", "legacy")),
    )


def save_threshold_selection(
    checkpoint_path: str | Path,
    selection: ThresholdSelection,
    *,
    merge_window_s: float,
    event_match_tolerance_s: float,
    target_recall: float,
) -> Path:
    """Persist the validation-selected threshold beside a checkpoint."""
    path = Path(checkpoint_path).with_name("threshold.json")
    payload = {
        "checkpoint": str(checkpoint_path),
        "threshold": selection.threshold,
        "merge_window_s": merge_window_s,
        "event_match_tolerance_s": event_match_tolerance_s,
        "target_recall": target_recall,
        "validation_metrics": selection.metrics,
        "candidates": list(selection.candidates),
        "max_f1": selection.max_f1,
        "max_f1_threshold": selection.max_f1_threshold,
        "target_recall_met": selection.target_recall_met,
        "maximum_attainable_recall": selection.maximum_attainable_recall,
        "selection_reason": selection.selection_reason,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


def load_threshold_selection(checkpoint_path: str | Path) -> ThresholdSelection:
    """Load a validation-selected threshold sidecar."""
    path = Path(checkpoint_path).with_name("threshold.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        selection_mapping: dict[str, Any] = {
            "threshold": payload["threshold"],
            "metrics": payload["validation_metrics"],
            "candidates": payload["candidates"],
        }
        if "max_f1" in payload:
            selection_mapping["max_f1"] = payload["max_f1"]
        if "max_f1_threshold" in payload:
            selection_mapping["max_f1_threshold"] = payload["max_f1_threshold"]
        for key in ("target_recall_met", "maximum_attainable_recall", "selection_reason"):
            if key in payload:
                selection_mapping[key] = payload[key]
        selection = threshold_selection_from_mapping(selection_mapping)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, EvaluationError) as exc:
        raise EvaluationError(
            f"Could not load the validation threshold from {path}. "
            "Run evaluation on the val partition first."
        ) from exc
    return selection


def save_validation_stream(
    videos: Sequence[ScoredVideo],
    output_path: str | Path,
) -> Path:
    """Persist a decoder-ready, gzip-compressed validation stream artifact."""
    payload = {
        "format": "cardevent-validation-stream-v1",
        "videos": [
            {
                "video": video.name,
                "decision_timestamps_s": [sample.time_s for sample in video.probabilities],
                "logits": [sample.logit for sample in video.probabilities],
                "probabilities": [sample.probability for sample in video.probabilities],
                "ground_truth_events_s": list(video.ground_truth_times_s),
                "ground_truth_event_types": list(video.ground_truth_types),
                "annotation_version_hash": video.annotation_version_hash,
            }
            for video in videos
        ],
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, allow_nan=False)
        handle.write("\n")
    return path
