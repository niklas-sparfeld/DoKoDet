from __future__ import annotations

import struct
from pathlib import Path

import pytest

from cardevent.evaluate import (
    ScoredVideo,
    save_operating_plots,
    save_probability_plots,
    save_threshold_plot,
    save_training_history_plot,
)
from cardevent.events import ProbabilitySample
from cardevent.review_ui import TimelineRenderer


def _png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as image:
        header = image.read(24)
    return struct.unpack(">II", header[16:24])


def test_saved_plots_use_double_resolution(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    candidates = (
        {
            "threshold": 0.5,
            "event_recall": 0.9,
            "event_precision": 0.8,
            "false_events_per_hour": 1.0,
        },
    )
    video = ScoredVideo(
        name="sample",
        duration_s=1.0,
        ground_truth_times_s=(0.5,),
        probabilities=(ProbabilitySample(0.5, 0.9),),
    )

    probability_path = save_probability_plots(
        (video,), threshold=0.5, merge_window_s=0.6, output_dir=tmp_path
    )[0]
    threshold_path = save_threshold_plot(candidates, output_path=tmp_path / "threshold.png")
    operating_paths = save_operating_plots(
        candidates,
        selected_threshold=0.5,
        max_f1_threshold=0.5,
        output_dir=tmp_path,
    )
    history_path = save_training_history_plot(
        ({"epoch": 1, "train_loss": 0.4, "val_loss": 0.5},),
        output_path=tmp_path / "history.png",
    )

    assert _png_size(probability_path) == (3360, 1120)
    assert _png_size(threshold_path) == (2240, 1400)
    assert _png_size(operating_paths["precision_recall"]) == (1960, 1400)
    assert _png_size(operating_paths["recall_false_events"]) == (1960, 1400)
    assert _png_size(history_path) == (3080, 1960)


def test_review_timeline_uses_double_resolution() -> None:
    pytest.importorskip("matplotlib")

    renderer = TimelineRenderer({}, video_name="sample")

    try:
        assert renderer.figure.get_dpi() == 220
        assert renderer.render(
            candidate_time_s=0.0,
            current_time_s=0.0,
            target_time_s=None,
        ).shape[:2] == (517, 2200)
    finally:
        renderer.figure.clear()
