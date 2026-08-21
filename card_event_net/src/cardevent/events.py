from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence


class EventError(ValueError):
    """Raised when event probabilities or timestamps are invalid."""


@dataclass(frozen=True, slots=True)
class ProbabilitySample:
    """The model score at one causal decision timestamp."""

    time_s: float
    probability: float

    def __post_init__(self) -> None:
        if not isfinite(self.time_s) or self.time_s < 0.0:
            raise EventError("Probability sample time must be finite and non-negative.")
        if not isfinite(self.probability):
            raise EventError("Probability sample probability must be finite.")

    def to_mapping(self) -> dict[str, float]:
        return {"time_s": self.time_s, "probability": self.probability}


@dataclass(frozen=True, slots=True)
class DetectedEvent:
    """One event produced by probability clustering."""

    time_s: float
    probability: float

    def __post_init__(self) -> None:
        if not isfinite(self.time_s) or self.time_s < 0.0:
            raise EventError("Detected event time must be finite and non-negative.")
        if not isfinite(self.probability):
            raise EventError("Detected event probability must be finite.")

    def to_mapping(self) -> dict[str, float]:
        return {"time_s": self.time_s, "probability": self.probability}


def probabilities_to_events(
    samples: Sequence[ProbabilitySample],
    threshold: float,
    merge_window_s: float = 0.6,
) -> list[DetectedEvent]:
    """Convert a causal probability stream into one event per probability cluster."""
    if not isfinite(threshold):
        raise EventError("threshold must be finite.")
    if merge_window_s < 0.0 or not isfinite(merge_window_s):
        raise EventError("merge_window_s must be finite and non-negative.")

    ordered_samples = sorted(samples, key=lambda sample: sample.time_s)
    clusters: list[list[ProbabilitySample]] = []
    for sample in ordered_samples:
        if sample.probability < threshold:
            continue
        if not clusters or sample.time_s - clusters[-1][-1].time_s > merge_window_s:
            clusters.append([])
        clusters[-1].append(sample)

    return [
        DetectedEvent(
            time_s=maximum.time_s,
            probability=maximum.probability,
        )
        for cluster in clusters
        for maximum in [max(cluster, key=lambda sample: sample.probability)]
    ]


@dataclass(frozen=True, slots=True)
class EventMatch:
    predicted_time_s: float
    ground_truth_time_s: float

    @property
    def latency_s(self) -> float:
        return self.predicted_time_s - self.ground_truth_time_s


@dataclass(frozen=True, slots=True)
class EventMatchResult:
    """One-to-one event matching results for one video."""

    real_events: int
    detected_true_events: int
    missed_events: int
    false_events: int
    matches: tuple[EventMatch, ...]
    unmatched_predicted_indices: tuple[int, ...] = ()
    unmatched_ground_truth_indices: tuple[int, ...] = ()
    unmatched_predicted_times_s: tuple[float, ...] = ()
    unmatched_ground_truth_times_s: tuple[float, ...] = ()

    @property
    def latencies_s(self) -> tuple[float, ...]:
        return tuple(match.latency_s for match in self.matches)


def _event_time(value: float | DetectedEvent | ProbabilitySample) -> float:
    time_s = value.time_s if isinstance(value, (DetectedEvent, ProbabilitySample)) else float(value)
    if not isfinite(time_s) or time_s < 0.0:
        raise EventError("Event times must be finite and non-negative.")
    return time_s


def match_events(
    predicted_events: Sequence[float | DetectedEvent | ProbabilitySample],
    ground_truth_times_s: Sequence[float],
    *,
    tolerance_s: float = 0.75,
) -> EventMatchResult:
    """Match predictions to ground truth with deterministic nearest-time matching."""
    if tolerance_s < 0.0 or not isfinite(tolerance_s):
        raise EventError("tolerance_s must be finite and non-negative.")

    predicted_times = sorted(_event_time(event) for event in predicted_events)
    ground_truth_times = sorted(_event_time(time_s) for time_s in ground_truth_times_s)
    available_predictions = set(range(len(predicted_times)))
    matched_ground_truth_indices: set[int] = set()
    matches: list[EventMatch] = []

    for ground_truth_index, ground_truth_time_s in enumerate(ground_truth_times):
        candidates = [
            index
            for index in available_predictions
            if abs(predicted_times[index] - ground_truth_time_s) <= tolerance_s
        ]
        if not candidates:
            continue
        prediction_index = min(
            candidates,
            key=lambda index: (abs(predicted_times[index] - ground_truth_time_s), index),
        )
        available_predictions.remove(prediction_index)
        matched_ground_truth_indices.add(ground_truth_index)
        matches.append(
            EventMatch(
                predicted_time_s=predicted_times[prediction_index],
                ground_truth_time_s=ground_truth_time_s,
            )
        )

    detected_true_events = len(matches)
    return EventMatchResult(
        real_events=len(ground_truth_times),
        detected_true_events=detected_true_events,
        missed_events=len(ground_truth_times) - detected_true_events,
        false_events=len(predicted_times) - detected_true_events,
        matches=tuple(matches),
        unmatched_predicted_indices=tuple(sorted(available_predictions)),
        unmatched_ground_truth_indices=tuple(
            index
            for index in range(len(ground_truth_times))
            if index not in matched_ground_truth_indices
        ),
        unmatched_predicted_times_s=tuple(
            predicted_times[index] for index in sorted(available_predictions)
        ),
        unmatched_ground_truth_times_s=tuple(
            ground_truth_times[index]
            for index in range(len(ground_truth_times))
            if index not in matched_ground_truth_indices
        ),
    )
