from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from cardevent.config import Config
from cardevent.dataset import DatasetSample
from cardevent.splits import VideoSplit
from cardevent.train import (
    TrainingError,
    TrainingRuntimeOptions,
    _checkpoint_rank,
    _limit_samples,
    _make_loader,
    _resume_state,
    _save_checkpoint,
    resolve_runtime_options,
)


def make_sample(label: float, time_s: float) -> DatasetSample:
    return DatasetSample(
        source_video="sample.mov",
        cache_dir=Path("data/cache/sample"),
        decision_time_s=time_s,
        label=label,
    )


def make_config() -> Config:
    return Config.from_mapping(
        {
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
                "pretrained": False,
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
                "device": "cpu",
            },
            "inference": {"merge_window_s": 0.6},
            "metrics": {
                "event_match_tolerance_s": 0.75,
                "target_recall": 0.98,
            },
        }
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


def test_runtime_defaults_and_overrides() -> None:
    config = SimpleNamespace(training=SimpleNamespace(batch_size=16))

    cpu_runtime = resolve_runtime_options(config, torch.device("cpu"))
    assert cpu_runtime == TrainingRuntimeOptions(16, 0, False, "fp32")

    cuda_runtime = resolve_runtime_options(
        config,
        torch.device("cuda"),
        batch_size=32,
        num_workers=4,
        precision="fp32",
    )
    assert cuda_runtime == TrainingRuntimeOptions(32, 4, True, "fp32")


def test_runtime_rejects_bf16_without_cuda() -> None:
    config = SimpleNamespace(training=SimpleNamespace(batch_size=16))

    with pytest.raises(TrainingError, match="requires an available CUDA device"):
        resolve_runtime_options(config, torch.device("cpu"), precision="bf16")


def test_loader_propagates_worker_and_pin_options() -> None:
    runtime = TrainingRuntimeOptions(16, 4, True, "fp32")

    loader = _make_loader(
        [],
        training=True,
        batch_size=runtime.batch_size,
        shuffle=False,
        runtime=runtime,
    )

    assert loader.num_workers == 4
    assert loader.pin_memory is True
    assert loader.persistent_workers is True
    assert loader.prefetch_factor == 2


def test_checkpoint_stores_resume_and_runtime_state(tmp_path: Path) -> None:
    config = make_config()
    split = VideoSplit(train=("train",), val=("val",), test=("test",))
    model = torch.nn.Linear(1, 1)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001)
    path = tmp_path / "last.pt"

    _save_checkpoint(
        path,
        model=model,
        optimizer=optimizer,
        epoch=2,
        stage="warmup",
        stage_epoch=2,
        config=config,
        split=split,
        device=torch.device("cpu"),
        metrics={
            "epoch": 2,
            "validation_event_recall": 0.5,
            "validation_false_events_per_hour": 1.0,
            "validation_precision": 0.5,
        },
        hard_negative_manifest=None,
        runtime=TrainingRuntimeOptions(32, 2, False, "fp32"),
    )

    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    assert {
        "model_state",
        "optimizer_state",
        "epoch",
        "stage",
        "stage_epoch",
        "config",
        "split",
        "runtime",
        "metrics",
    }.issubset(checkpoint)
    assert checkpoint["runtime"]["batch_size"] == 32


def test_resume_infers_stage_epoch_for_older_checkpoint(tmp_path: Path) -> None:
    config = make_config()
    split = VideoSplit(train=("train",), val=("val",), test=("test",))
    checkpoint_path = tmp_path / "last.pt"
    torch.save(
        {
            "model_state": {},
            "optimizer_state": {},
            "epoch": 6,
            "stage": "finetune",
            "config": config.to_dict(),
            "split": split.to_mapping(),
        },
        checkpoint_path,
    )

    state = _resume_state(checkpoint_path, config=config, split=split)

    assert state.global_epoch == 6
    assert state.stage == "finetune"
    assert state.stage_epoch == 1


def test_resume_rejects_config_mismatch(tmp_path: Path) -> None:
    config = make_config()
    changed_config = make_config()
    changed_config = Config.from_mapping(
        {**changed_config.to_dict(), "seed": 43}
    )
    split = VideoSplit(train=("train",), val=("val",), test=("test",))
    checkpoint_path = tmp_path / "last.pt"
    torch.save(
        {
            "model_state": {},
            "optimizer_state": {},
            "epoch": 1,
            "stage": "warmup",
            "config": config.to_dict(),
            "split": split.to_mapping(),
        },
        checkpoint_path,
    )

    with pytest.raises(TrainingError, match="config does not match"):
        _resume_state(checkpoint_path, config=changed_config, split=split)


def test_training_resume_keeps_completed_epochs_and_best_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    train_module = importlib.import_module("cardevent.train")
    config_data = make_config().to_dict()
    config_data["training"] = {
        **config_data["training"],
        "warmup_epochs": 2,
        "finetune_epochs": 1,
    }
    config = Config.from_mapping(config_data)
    split = VideoSplit(train=("train",), val=("val",), test=("test",))
    samples = [make_sample(0.0, 0.0), make_sample(1.0, 0.1)]
    run_dir = tmp_path / "run"

    class FakeModel(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.backbone = torch.nn.Sequential(torch.nn.Linear(1, 1))
            self.head = torch.nn.Linear(1, 1)

    train_calls: list[int] = []

    monkeypatch.setattr(train_module, "build_model", lambda _config: FakeModel())
    monkeypatch.setattr(
        train_module,
        "_training_samples_for_split",
        lambda *_args, **_kwargs: samples,
    )
    monkeypatch.setattr(train_module, "_validation_videos", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        train_module,
        "_make_loader",
        lambda *_args, **_kwargs: SimpleNamespace(batch_size=2, num_workers=0),
    )

    def fake_train_epoch(*_args, **kwargs) -> float:
        train_calls.append(kwargs.get("backbone_frozen"))
        return 1.0

    monkeypatch.setattr(train_module, "_run_train_epoch", fake_train_epoch)
    monkeypatch.setattr(
        train_module,
        "_evaluate_validation",
        lambda *_args, **_kwargs: {
            "val_loss": 1.0,
            "validation_event_recall": 0.5,
            "validation_precision": 0.5,
            "validation_false_events_per_hour": 1.0,
            "validation_latency_median_s": 0.0,
        },
    )

    original_save_checkpoint = train_module._save_checkpoint
    save_count = 0

    def save_then_interrupt(*args, **kwargs) -> None:
        nonlocal save_count
        original_save_checkpoint(*args, **kwargs)
        save_count += 1
        if save_count == 2:
            raise RuntimeError("simulated interruption")

    monkeypatch.setattr(train_module, "_save_checkpoint", save_then_interrupt)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        train_module.train_model(config, split, run_dir=run_dir, device_override="cpu")

    monkeypatch.setattr(train_module, "_save_checkpoint", original_save_checkpoint)
    result = train_module.train_model(
        config,
        split,
        run_dir=run_dir,
        device_override="cpu",
        resume_path=run_dir / "last.pt",
    )

    rows = [
        json.loads(line)
        for line in (run_dir / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["epoch"] for row in rows] == [1, 2, 3]
    assert result.summary["best_epoch"] == 1
    assert len(train_calls) == 3
