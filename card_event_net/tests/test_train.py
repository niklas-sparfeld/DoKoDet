from __future__ import annotations

from pathlib import Path

from cardevent.dataset import DatasetSample
from cardevent.train import _checkpoint_rank, _limit_samples


def make_sample(label: float, time_s: float) -> DatasetSample:
    return DatasetSample(
        source_video="sample.mov",
        cache_dir=Path("data/cache/sample"),
        decision_time_s=time_s,
        label=label,
    )


def test_development_sample_limit_keeps_both_classes() -> None:
    samples = [make_sample(0.0, 0.0), make_sample(0.0, 0.1), make_sample(1.0, 0.2)]

    limited = _limit_samples(samples, 2)

    assert {sample.label for sample in limited} == {0.0, 1.0}


def test_checkpoint_ranking_prefers_low_false_rate_after_target_recall() -> None:
    target = 0.98
    low_false = {
        "validation_event_recall": 0.99,
        "validation_false_events_per_hour": 1.0,
        "validation_precision": 0.9,
    }
    high_false = {
        "validation_event_recall": 1.0,
        "validation_false_events_per_hour": 2.0,
        "validation_precision": 0.95,
    }

    assert _checkpoint_rank(low_false, target) > _checkpoint_rank(high_false, target)
