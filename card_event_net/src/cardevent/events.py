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
    logit: float | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.time_s) or self.time_s < 0.0:
            raise EventError("Probability sample time must be finite and non-negative.")
        if not isfinite(self.probability):
            raise EventError("Probability sample probability must be finite.")
        if self.logit is not None and not isfinite(self.logit):
            raise EventError("Probability sample logit must be finite when provided.")

    def to_mapping(self) -> dict[str, float]:
        result = {"time_s": self.time_s, "probability": self.probability}
        if self.logit is not None:
            result["logit"] = self.logit
        return result


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


def candidate_peaks(
    samples: Sequence[ProbabilitySample],
    *,
    peak_confirmation_s: float = 0.125,
    min_event_gap_s: float = 0.6,
) -> list[DetectedEvent]:
    """Extract and suppress score peaks without applying an operating threshold.

    A flat top becomes one peak at its first timestamp. The confirmation window
    describes online emission delay only. Offline decoding keeps the peak time.
    """
    if peak_confirmation_s < 0.0 or not isfinite(peak_confirmation_s):
        raise EventError("peak_confirmation_s must be finite and non-negative.")
    if min_event_gap_s < 0.0 or not isfinite(min_event_gap_s):
        raise EventError("min_event_gap_s must be finite and non-negative.")
    ordered = sorted(samples, key=lambda sample: sample.time_s)
    if not ordered:
        return []

    raw_peaks: list[ProbabilitySample] = []
    segment_start = 0
    for segment_end in (*(
        index
        for index in range(1, len(ordered))
        if ordered[index].time_s - ordered[index - 1].time_s > min_event_gap_s
    ), len(ordered)):
        index = segment_start
        while index < segment_end:
            start = index
            score = ordered[index].probability
            while index + 1 < segment_end and ordered[index + 1].probability == score:
                index += 1
            end = index
            left = ordered[start - 1].probability if start > segment_start else float("-inf")
            right = ordered[end + 1].probability if end + 1 < segment_end else float("-inf")
            if score >= left and score >= right and (score > left or score > right):
                raw_peaks.append(ordered[start])
            index += 1
        segment_start = segment_end

    # Score-first suppression makes the candidate set independent of threshold.
    selected: list[ProbabilitySample] = []
    for peak in sorted(raw_peaks, key=lambda item: (-item.probability, item.time_s)):
        if all(abs(peak.time_s - accepted.time_s) > min_event_gap_s for accepted in selected):
            selected.append(peak)
    return [
        DetectedEvent(time_s=peak.time_s, probability=peak.probability)
        for peak in sorted(selected, key=lambda item: item.time_s)
    ]


def probabilities_to_events(
    samples: Sequence[ProbabilitySample],
    threshold: float,
    merge_window_s: float = 0.6,
    *,
    peak_confirmation_s: float = 0.125,
    min_event_gap_s: float | None = None,
) -> list[DetectedEvent]:
    """Accept fixed candidate peaks at an operating threshold.

    ``merge_window_s`` remains as a compatibility alias for
    ``min_event_gap_s``. New code should use ``min_event_gap_s``.
    """
    if not isfinite(threshold):
        raise EventError("threshold must be finite.")
    if merge_window_s < 0.0 or not isfinite(merge_window_s):
        raise EventError("merge_window_s must be finite and non-negative.")
    gap = merge_window_s if min_event_gap_s is None else min_event_gap_s
    return [
        event
        for event in candidate_peaks(
            samples,
            peak_confirmation_s=peak_confirmation_s,
            min_event_gap_s=gap,
        )
        if event.probability >= threshold
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
    """Match events in order with maximum cardinality and minimum time error."""
    if tolerance_s < 0.0 or not isfinite(tolerance_s):
        raise EventError("tolerance_s must be finite and non-negative.")

    predicted_times = sorted(_event_time(event) for event in predicted_events)
    ground_truth_times = sorted(_event_time(time_s) for time_s in ground_truth_times_s)
    # Dynamic programming state: count, total error, matched index pairs. The
    # final tuple provides deterministic tie-breaking for equal solutions.
    states: list[list[tuple[int, float, tuple[tuple[int, int], ...]]]] = [
        [(0, 0.0, ()) for _ in range(len(ground_truth_times) + 1)]
        for _ in range(len(predicted_times) + 1)
    ]

    def better(
        first: tuple[int, float, tuple[tuple[int, int], ...]],
        second: tuple[int, float, tuple[tuple[int, int], ...]],
    ) -> tuple[int, float, tuple[tuple[int, int], ...]]:
        if first[0] != second[0]:
            return first if first[0] > second[0] else second
        if abs(first[1] - second[1]) > 1e-12:
            return first if first[1] < second[1] else second
        return first if first[2] <= second[2] else second

    for prediction_index in range(1, len(predicted_times) + 1):
        for ground_truth_index in range(1, len(ground_truth_times) + 1):
            state = better(
                states[prediction_index - 1][ground_truth_index],
                states[prediction_index][ground_truth_index - 1],
            )
            error = abs(
                predicted_times[prediction_index - 1] - ground_truth_times[ground_truth_index - 1]
            )
            if error <= tolerance_s:
                prior = states[prediction_index - 1][ground_truth_index - 1]
                matched = (
                    prior[0] + 1,
                    prior[1] + error,
                    (*prior[2], (prediction_index - 1, ground_truth_index - 1)),
                )
                state = better(state, matched)
            states[prediction_index][ground_truth_index] = state

    pairs = states[-1][-1][2]
    matched_prediction_indices = {pair[0] for pair in pairs}
    matched_ground_truth_indices = {pair[1] for pair in pairs}
    available_predictions = set(range(len(predicted_times))) - matched_prediction_indices
    matches = [
        EventMatch(
            predicted_time_s=predicted_times[prediction_index],
            ground_truth_time_s=ground_truth_times[ground_truth_index],
        )
        for prediction_index, ground_truth_index in pairs
    ]

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
