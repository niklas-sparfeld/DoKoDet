from __future__ import annotations

import importlib

import pytest

from cardevent.evaluate import (
    ScoredVideo,
    ThresholdSelection,
    diagnose_checkpoint_from_files,
    evaluate_streams,
    select_threshold,
)
from cardevent.events import ProbabilitySample
from cardevent.splits import VideoSplit


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
    assert overall["peak_confirmation_s"] == 0.125
    assert overall["timestamp_error_median_s"] == 0.0
    assert overall["emission_latency_median_s"] == 0.125
    assert overall["timestamp_error_p95_s"] == 0.0
    assert overall["emission_latency_p95_s"] == 0.125
    assert per_video[0]["predicted_events"]


def test_evaluate_streams_separates_timestamp_error_from_online_emission_delay() -> None:
    video = ScoredVideo(
        name="sample",
        duration_s=60.0,
        ground_truth_times_s=(10.0,),
        probabilities=(ProbabilitySample(10.1, 0.9),),
    )

    overall, per_video = evaluate_streams(
        [video],
        threshold=0.5,
        merge_window_s=0.6,
        peak_confirmation_s=0.125,
        event_match_tolerance_s=0.75,
    )

    assert overall["timestamp_error_median_s"] == pytest.approx(0.1)
    assert overall["emission_latency_median_s"] == pytest.approx(0.225)
    assert per_video[0]["timestamp_error_median_s"] == pytest.approx(0.1)
    assert per_video[0]["emission_latency_median_s"] == pytest.approx(0.225)
    # Keep old names as aliases for timestamp error during migration.
    assert overall["latency_median_s"] == overall["timestamp_error_median_s"]
    assert per_video[0]["latency_p50_s"] == per_video[0]["timestamp_error_median_s"]


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


def test_default_threshold_grid_can_select_below_point_one() -> None:
    video = ScoredVideo(
        name="sample",
        duration_s=3600.0,
        ground_truth_times_s=(10.0,),
        probabilities=(ProbabilitySample(10.0, 0.08),),
    )

    selection = select_threshold(
        [video],
        merge_window_s=0.6,
        event_match_tolerance_s=0.75,
        target_recall=0.98,
    )

    assert selection.threshold < 0.10
    assert len(selection.candidates) == 2


def test_threshold_selection_records_unmet_target_and_uses_f1_fallback() -> None:
    video = ScoredVideo(
        name="sample",
        duration_s=60.0,
        ground_truth_times_s=(10.0, 20.0),
        probabilities=(ProbabilitySample(10.0, 0.9),),
    )

    selection = select_threshold(
        [video],
        merge_window_s=0.6,
        event_match_tolerance_s=0.25,
        target_recall=0.98,
    )

    assert selection.target_recall_met is False
    assert selection.maximum_attainable_recall == 0.5
    assert selection.selection_reason == "fallback_max_f1"


def test_f1_is_zero_when_no_events_are_predicted() -> None:
    video = ScoredVideo(
        name="sample",
        duration_s=60.0,
        ground_truth_times_s=(10.0,),
        probabilities=(ProbabilitySample(10.0, 0.2),),
    )

    overall, _ = evaluate_streams(
        [video],
        threshold=0.5,
        merge_window_s=0.6,
        event_match_tolerance_s=0.75,
    )

    assert overall["event_f1"] == 0.0


def test_per_video_metrics_and_failure_details_are_reported() -> None:
    video = ScoredVideo(
        name="sample",
        duration_s=3600.0,
        ground_truth_times_s=(10.0, 10.3),
        probabilities=(
            ProbabilitySample(10.1, 0.9),
            ProbabilitySample(20.0, 0.8),
        ),
    )

    overall, per_video = evaluate_streams(
        [video],
        threshold=0.5,
        merge_window_s=0.6,
        event_match_tolerance_s=0.25,
    )

    assert overall["real_events"] == 2.0
    assert overall["detected_true_events"] == 1.0
    assert overall["false_events"] == 1.0
    assert per_video[0]["event_count"] == 2
    assert per_video[0]["detected_count"] == 1
    assert per_video[0]["missed_count"] == 1
    assert per_video[0]["false_count"] == 1
    assert per_video[0]["missed_event_details"] == [
        {
            "ground_truth_time_s": 10.3,
            "max_probability_near_event": 0.9,
            "category": "merged_event",
        }
    ]
    assert per_video[0]["false_event_details"] == [{"predicted_time_s": 20.0, "probability": 0.8}]


def test_diagnose_selects_from_validation_and_evaluates_train_and_val(
    tmp_path, monkeypatch
) -> None:
    evaluate_module = importlib.import_module("cardevent.evaluate")
    validation_video = ScoredVideo(
        name="val",
        duration_s=60.0,
        ground_truth_times_s=(10.0,),
        probabilities=(ProbabilitySample(10.0, 0.8),),
    )
    train_video = ScoredVideo(
        name="train",
        duration_s=60.0,
        ground_truth_times_s=(10.0,),
        probabilities=(ProbabilitySample(10.0, 0.9),),
    )
    config = type(
        "ConfigStub",
        (),
        {
            "inference": type("InferenceStub", (), {"merge_window_s": 0.6})(),
            "metrics": type(
                "MetricsStub",
                (),
                {"event_match_tolerance_s": 0.75, "target_recall": 0.98},
            )(),
        },
    )()
    loaded = type("LoadedStub", (), {"config": config})()
    partitions: list[str] = []

    monkeypatch.setattr(
        evaluate_module,
        "load_split",
        lambda _path: VideoSplit(("train",), ("val",), ("test",)),
    )
    monkeypatch.setattr(evaluate_module, "load_checkpoint", lambda *_args, **_kwargs: loaded)

    def fake_load_streams(_loaded, _split, partition, **_kwargs):
        partitions.append(partition)
        return [validation_video] if partition == "val" else [train_video]

    monkeypatch.setattr(evaluate_module, "load_model_streams", fake_load_streams)

    def fake_select(videos, **_kwargs):
        assert [video.name for video in videos] == ["val"]
        candidate = {
            "threshold": 0.2,
            "event_recall": 1.0,
            "event_precision": 1.0,
            "event_f1": 1.0,
            "false_events_per_hour": 0.0,
        }
        return ThresholdSelection(
            threshold=0.2,
            metrics={key: value for key, value in candidate.items() if key != "threshold"},
            candidates=(candidate,),
            max_f1=1.0,
            max_f1_threshold=0.2,
        )

    monkeypatch.setattr(evaluate_module, "select_threshold", fake_select)
    monkeypatch.setattr(
        evaluate_module,
        "save_threshold_selection",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(evaluate_module, "save_operating_plots", lambda *_args, **_kwargs: {})

    payload = diagnose_checkpoint_from_files(
        tmp_path / "best.pt",
        tmp_path / "split.yaml",
        output_path=tmp_path / "diagnostics.json",
    )

    assert partitions == ["val", "train"]
    assert payload["threshold"] == 0.2
    assert payload["generalization_gap"]["recall"] == 0.0
