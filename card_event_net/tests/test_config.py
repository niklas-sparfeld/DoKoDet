from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from cardevent.cache import FULL_FRAME_LETTERBOX_V1, LEGACY_ROI_LETTERBOX_V1
from cardevent.config import Config, ConfigError, load_config


def sample_config_dict() -> dict[str, object]:
    return {
        "seed": 42,
        "input": {
            "size": 224,
            "cache_fps": 10.0,
            "clip_offsets_s": [-1.4, -1.2, -1.0, -0.8, -0.6, -0.4, -0.2, 0.0],
            "inference_stride_s": 0.125,
        },
        "labels": {
            "positive_window_s": 0.45,
            "negative_past_exclusion_s": 1.8,
            "negative_future_exclusion_s": 0.8,
            "negative_to_positive_ratio": 3,
        },
        "model": {
            "backbone": "mobilenet_v3_small",
            "pretrained": True,
            "feature_dim": 128,
            "temporal_hidden_1": 64,
            "temporal_hidden_2": 32,
            "dropout": 0.1,
        },
        "training": {
            "batch_size": 16,
            "warmup_epochs": 5,
            "finetune_epochs": 15,
            "warmup_lr": 0.001,
            "finetune_lr": 0.0001,
            "weight_decay": 0.0001,
            "device": "auto",
        },
        "inference": {"merge_window_s": 0.6},
        "metrics": {
            "event_match_tolerance_s": 0.75,
            "target_recall": 0.98,
        },
    }


def test_config_from_mapping_round_trips() -> None:
    config = Config.from_mapping(sample_config_dict())

    assert config.seed == 42
    assert config.input.preprocessing == LEGACY_ROI_LETTERBOX_V1
    assert config.input.clip_offsets_s == (-1.4, -1.2, -1.0, -0.8, -0.6, -0.4, -0.2, 0.0)
    assert config.training.hard_negative_repeat == 3
    assert config.model.temporal_head == "padded_tail_v1"
    assert config.to_dict()["input"]["clip_offsets_s"] == [
        -1.4,
        -1.2,
        -1.0,
        -0.8,
        -0.6,
        -0.4,
        -0.2,
        0.0,
    ]


def test_config_declares_full_frame_preprocessing() -> None:
    data = sample_config_dict()
    data["input"] = dict(data["input"])
    data["input"]["preprocessing"] = FULL_FRAME_LETTERBOX_V1

    config = Config.from_mapping(data)

    assert config.input.preprocessing == FULL_FRAME_LETTERBOX_V1
    assert config.to_dict()["input"]["preprocessing"] == FULL_FRAME_LETTERBOX_V1


@pytest.mark.parametrize("value", ("center_crop_v1", []))
def test_config_rejects_unknown_preprocessing(value: object) -> None:
    data = sample_config_dict()
    data["input"] = dict(data["input"])
    data["input"]["preprocessing"] = value

    with pytest.raises(ConfigError, match="input.preprocessing"):
        Config.from_mapping(data)


def test_config_rejects_future_offsets() -> None:
    data = sample_config_dict()
    data["input"] = dict(data["input"])
    data["input"]["clip_offsets_s"] = [-1.0, -0.5, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]

    with pytest.raises(ConfigError, match="future frames"):
        Config.from_mapping(data)


def test_config_allows_equal_positive_and_post_event_exclusion_windows() -> None:
    data = sample_config_dict()
    data["labels"] = {
        **data["labels"],
        "positive_window_s": 0.35,
        "negative_past_exclusion_s": 0.35,
    }

    assert Config.from_mapping(data).labels.positive_window_s == 0.35


def test_config_rejects_positive_window_after_post_event_exclusion() -> None:
    data = sample_config_dict()
    data["labels"] = {
        **data["labels"],
        "positive_window_s": 0.36,
        "negative_past_exclusion_s": 0.35,
    }

    with pytest.raises(ConfigError, match="positive_window_s"):
        Config.from_mapping(data)


def test_config_round_trips_full_clip_temporal_head() -> None:
    data = sample_config_dict()
    data["model"] = {**data["model"], "temporal_head": "full_clip_v2"}

    assert Config.from_mapping(data).to_dict()["model"]["temporal_head"] == "full_clip_v2"


def test_transition_label_experiment_config_loads() -> None:
    config_path = Path(__file__).parents[1] / "configs" / "transition-label-v1.yaml"

    config = load_config(config_path)

    assert config.labels.positive_window_s == 0.25
    assert config.labels.negative_past_exclusion_s == 0.35
    assert config.labels.negative_future_exclusion_s == 0.10


def test_load_config_uses_yaml_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "base.yaml"
    config_path.write_text("seed: 42\n", encoding="utf-8")

    captured: dict[str, str] = {}

    def fake_safe_load(text: str) -> dict[str, object]:
        captured["text"] = text
        return sample_config_dict()

    fake_yaml = types.SimpleNamespace(safe_load=fake_safe_load)
    monkeypatch.setitem(sys.modules, "yaml", fake_yaml)

    config = load_config(config_path)

    assert captured["text"] == "seed: 42\n"
    assert config.seed == 42
