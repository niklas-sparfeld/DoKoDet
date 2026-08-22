from __future__ import annotations

import pytest

from cardevent.events import (
    ProbabilitySample,
    candidate_peaks,
    match_events,
    probabilities_to_events,
)


def sample(time_s: float, probability: float) -> ProbabilitySample:
    return ProbabilitySample(time_s=time_s, probability=probability)


def test_sustained_peak_becomes_one_event_at_maximum() -> None:
    events = probabilities_to_events(
        [sample(1.0, 0.8), sample(1.125, 0.95), sample(1.25, 0.9)],
        threshold=0.5,
        merge_window_s=0.6,
    )

    assert [(event.time_s, event.probability) for event in events] == [(1.125, 0.95)]


def test_distant_peaks_become_two_events() -> None:
    events = probabilities_to_events(
        [sample(1.0, 0.8), sample(1.125, 0.9), sample(2.0, 0.7)],
        threshold=0.5,
        merge_window_s=0.6,
    )

    assert [event.time_s for event in events] == [1.125, 2.0]


def test_subthreshold_samples_produce_no_events() -> None:
    assert probabilities_to_events([sample(1.0, 0.49)], threshold=0.5) == []


def test_event_matching_counts_misses_and_false_events() -> None:
    result = match_events(
        [sample(10.2, 0.8), sample(20.0, 0.7)],
        [10.0, 10.4],
        tolerance_s=0.25,
    )

    assert result.real_events == 2
    assert result.detected_true_events == 1
    assert result.missed_events == 1
    assert result.false_events == 1
    assert result.latencies_s == pytest.approx((0.2,))


def test_event_matching_accepts_exact_and_rejects_outside_tolerance() -> None:
    result = match_events([5.0, 8.0], [5.0, 7.0], tolerance_s=0.5)

    assert result.detected_true_events == 1
    assert result.missed_events == 1
    assert result.false_events == 1


def test_event_count_is_monotonic_as_threshold_increases() -> None:
    stream = [
        sample(1.0, 0.8), sample(1.125, 0.9), sample(2.0, 0.7),
        sample(3.0, 0.85), sample(3.125, 0.8),
    ]

    counts = [
        len(probabilities_to_events(stream, threshold))
        for threshold in (0.5, 0.8, 0.86, 0.95)
    ]

    assert counts == sorted(counts, reverse=True)
    assert [event.time_s for event in candidate_peaks(stream)] == [1.125, 2.0, 3.0]


def test_order_preserving_matching_maximizes_match_count() -> None:
    result = match_events([0.4, 0.8], [0.0, 0.5], tolerance_s=0.45)

    assert result.detected_true_events == 2
    assert result.latencies_s == pytest.approx((0.4, 0.3))
