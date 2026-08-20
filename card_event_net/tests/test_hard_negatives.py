from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cardevent.hard_negatives as hard_negative_module
from cardevent.evaluate import ScoredVideo
from cardevent.events import DetectedEvent, ProbabilitySample
from cardevent.hard_negatives import (
    HardNegativeError,
    false_triggers,
    load_hard_negative_times,
)
from cardevent.train import _hard_negative_samples_for_video


def test_false_triggers_keeps_only_unmatched_predictions() -> None:
    predicted = (
        DetectedEvent(time_s=1.0, probability=0.9),
        DetectedEvent(time_s=2.0, probability=0.8),
        DetectedEvent(time_s=4.0, probability=0.7),
    )

    hard_negatives = false_triggers(predicted, (1.2, 8.0), tolerance_s=0.25)

    assert [(event.time_s, event.probability) for event in hard_negatives] == [
        (2.0, 0.8),
        (4.0, 0.7),
    ]


def test_load_hard_negative_times_returns_only_requested_train_videos(tmp_path: Path) -> None:
    manifest_path = tmp_path / "hard-negatives.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format": "cardevent-hard-negatives-v1",
                "partition": "train",
                "videos": [
                    {
                        "video": "game",
                        "duration_s": 10.0,
                        "hard_negatives": [
                            {"time_s": 4.0, "probability": 0.9},
                            {"time_s": 2.0, "probability": 0.8},
                            {"time_s": 2.0, "probability": 0.7},
                        ],
                    },
                    {
                        "video": "ignored",
                        "duration_s": 10.0,
                        "hard_negatives": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = load_hard_negative_times(manifest_path, ("game",))

    assert result == {"game": (2.0, 4.0)}


def test_load_hard_negative_times_rejects_non_train_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "hard-negatives.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format": "cardevent-hard-negatives-v1",
                "partition": "test",
                "videos": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HardNegativeError, match="train partition"):
        load_hard_negative_times(manifest_path, ("game",))


def test_hard_negative_samples_are_repeated(tmp_path: Path) -> None:
    cache_dir = tmp_path / "game"
    cache_dir.mkdir()
    (cache_dir / "metadata.json").write_text(
        json.dumps(
            {
                "source_video": "game.mov",
                "cache_fps": 10.0,
                "duration_s": 10.0,
                "frame_timestamps_s": [0.0, 1.0, 2.0],
                "frame_size": 224,
            }
        ),
        encoding="utf-8",
    )

    samples = _hard_negative_samples_for_video(
        cache_dir,
        "game",
        (2.0, 1.0),
        repeat=3,
    )

    assert len(samples) == 6
    assert [sample.decision_time_s for sample in samples] == [1.0] * 3 + [2.0] * 3
    assert all(sample.label == 0.0 for sample in samples)


def test_mining_writes_false_trigger_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    split = SimpleNamespace(train=("game",), val=(), test=())
    loaded = SimpleNamespace(
        config=SimpleNamespace(
            inference=SimpleNamespace(merge_window_s=0.6),
            metrics=SimpleNamespace(event_match_tolerance_s=0.25, target_recall=0.98),
        )
    )
    scored_video = ScoredVideo(
        name="game",
        duration_s=10.0,
        ground_truth_times_s=(1.0,),
        probabilities=(
            ProbabilitySample(1.0, 0.9),
            ProbabilitySample(2.0, 0.8),
            ProbabilitySample(3.0, 0.1),
        ),
    )
    monkeypatch.setattr(hard_negative_module, "load_split", lambda path: split)
    monkeypatch.setattr(hard_negative_module, "load_checkpoint", lambda path, **kwargs: loaded)
    monkeypatch.setattr(
        hard_negative_module,
        "load_model_streams",
        lambda *args, **kwargs: [scored_video],
    )

    output_path = tmp_path / "hard-negatives.json"
    payload = hard_negative_module.mine_hard_negatives_from_files(
        "checkpoint.pt",
        "split.yaml",
        out_path=output_path,
        threshold=0.5,
    )

    assert payload["hard_negative_count"] == 1
    assert payload["videos"][0]["hard_negatives"] == [{"time_s": 2.0, "probability": 0.8}]
    assert json.loads(output_path.read_text(encoding="utf-8"))["partition"] == "train"
