from __future__ import annotations

from cardevent.evaluate import ScoredVideo, evaluate_streams, select_threshold
from cardevent.events import ProbabilitySample


def test_evaluate_streams_reports_event_metrics() -> None:
    video = ScoredVideo(
        name="sample",
        duration_s=3600.0,
        ground_truth_times_s=(10.0, 20.0),
        probabilities=(
            ProbabilitySample(10.0, 0.9),
            ProbabilitySample(20.0, 0.8),
            ProbabilitySample(30.0, 0.9),
        ),
    )

    overall, per_video = evaluate_streams(
        [video],
        threshold=0.5,
        merge_window_s=0.6,
        event_match_tolerance_s=0.75,
    )

    assert overall["real_events"] == 2.0
    assert overall["detected_true_events"] == 2.0
    assert overall["missed_events"] == 0.0
    assert overall["false_events"] == 1.0
    assert overall["event_recall"] == 1.0
    assert overall["false_events_per_hour"] == 1.0
    assert per_video[0]["predicted_events"]


def test_threshold_selection_prefers_low_false_rate_at_target_recall() -> None:
    video = ScoredVideo(
        name="sample",
        duration_s=3600.0,
        ground_truth_times_s=(10.0,),
        probabilities=(
            ProbabilitySample(10.0, 0.8),
            ProbabilitySample(20.0, 0.7),
        ),
    )

    selection = select_threshold(
        [video],
        merge_window_s=0.6,
        event_match_tolerance_s=0.75,
        target_recall=0.98,
        thresholds=(0.5, 0.8, 0.9),
    )

    assert selection.threshold == 0.8
    assert len(selection.candidates) == 3
