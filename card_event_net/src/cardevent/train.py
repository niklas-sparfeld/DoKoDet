from __future__ import annotations

import json
import logging
import platform
import random
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Sequence

import numpy as np
import torch
from torch.utils.data import DataLoader

from .annotation import AnnotationError, load_annotation
from .cache import CacheError, load_cache_metadata
from .config import Config, load_config, save_config
from .dataset import (
    CausalClipDataset,
    DatasetSample,
    inference_samples_for_cache,
    samples_for_annotation,
)
from .device import resolve_device
from .events import ProbabilitySample, match_events, probabilities_to_events
from .hard_negatives import HardNegativeError, load_hard_negative_times
from .model import CardEventNet, build_model, freeze_backbone, unfreeze_backbone
from .sampling import DEFAULT_CLIP_OFFSETS_S
from .splits import SplitError, VideoSplit, load_split
from .transforms import ClipTransform

LOGGER = logging.getLogger(__name__)


class TrainingError(RuntimeError):
    """Raised when a training run cannot be prepared or completed."""


@dataclass(frozen=True, slots=True)
class TrainingResult:
    run_dir: Path
    summary: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _ValidationVideo:
    name: str
    samples: tuple[DatasetSample, ...]
    event_times_s: tuple[float, ...]
    duration_s: float


def seed_everything(seed: int) -> None:
    """Set the random seeds used by the local training loop."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _find_repo_root() -> Path | None:
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        if (directory / ".git").exists():
            return directory
    return None


def _git_commit() -> str | None:
    repo_root = _find_repo_root()
    if repo_root is None:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _torchvision_version() -> str | None:
    try:
        import torchvision
    except ModuleNotFoundError:
        return None
    return torchvision.__version__


def _new_run_dir(output_dir: Path, run_name: str | None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = run_name or f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    candidate = output_dir / base_name
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{base_name}-{suffix}"
        suffix += 1
    candidate.mkdir()
    return candidate


def _annotation_for_video(name: str, annotations_dir: Path) -> Any:
    path = annotations_dir / f"{name}.json"
    if not path.is_file():
        raise TrainingError(
            f"Missing annotation for split video {name}: {path}. "
            "Annotate the video before training."
        )
    try:
        return load_annotation(path)
    except AnnotationError as exc:
        raise TrainingError(f"Could not load annotation for {name}: {exc}") from exc


def _cache_for_video(name: str, cache_dir: Path) -> Path:
    path = cache_dir / name
    if not (path / "metadata.json").is_file():
        raise TrainingError(
            f"Missing prepared cache for split video {name}: {path}. "
            "Run `cardevent prepare --videos ...` first."
        )
    return path


def _training_samples_for_split(
    split: VideoSplit,
    *,
    cache_dir: Path,
    annotations_dir: Path,
    config: Config,
    hard_negative_manifest: str | Path | None = None,
) -> list[DatasetSample]:
    samples: list[DatasetSample] = []
    hard_negative_times: dict[str, tuple[float, ...]] = {}
    if hard_negative_manifest is not None:
        try:
            hard_negative_times = load_hard_negative_times(
                hard_negative_manifest,
                split.train,
            )
        except HardNegativeError as exc:
            raise TrainingError(str(exc)) from exc

    for name in split.train:
        cache_path = _cache_for_video(name, cache_dir)
        annotation = _annotation_for_video(name, annotations_dir)
        try:
            samples.extend(_training_samples_for_annotation(cache_path, annotation, config))
            samples.extend(
                _hard_negative_samples_for_video(
                    cache_path,
                    name,
                    hard_negative_times.get(name, ()),
                    repeat=config.training.hard_negative_repeat,
                )
            )
        except (AnnotationError, CacheError, ValueError) as exc:
            raise TrainingError(f"Could not build training samples for {name}: {exc}") from exc
    if not samples:
        raise TrainingError("The train split produced no samples.")
    if not any(sample.label == 1.0 for sample in samples):
        raise TrainingError("The train split produced no positive samples.")
    return samples


def _hard_negative_samples_for_video(
    cache_path: Path,
    name: str,
    times_s: Sequence[float],
    *,
    repeat: int,
) -> list[DatasetSample]:
    if repeat < 2:
        raise TrainingError("hard_negative_repeat must be at least 2.")
    try:
        source_video = load_cache_metadata(cache_path).source_video
    except CacheError as exc:
        raise TrainingError(
            f"Could not load cache metadata for hard negatives in {name}: {exc}"
        ) from exc
    return [
        DatasetSample(
            source_video=source_video,
            cache_dir=cache_path,
            decision_time_s=time_s,
            label=0.0,
        )
        for time_s in sorted(times_s)
        for _ in range(repeat)
    ]


def _training_samples_for_annotation(
    cache_path: Path,
    annotation: Any,
    config: Config,
) -> list[DatasetSample]:
    return samples_for_annotation(
        cache_path,
        annotation,
        positive_window_s=config.labels.positive_window_s,
        past_exclusion_s=config.labels.negative_past_exclusion_s,
        future_exclusion_s=config.labels.negative_future_exclusion_s,
        negative_to_positive_ratio=config.labels.negative_to_positive_ratio,
        seed=config.seed,
    )


def _validation_videos(
    split: VideoSplit,
    *,
    cache_dir: Path,
    annotations_dir: Path,
    config: Config,
    max_samples: int | None = None,
) -> list[_ValidationVideo]:
    videos: list[_ValidationVideo] = []
    for name in split.val:
        cache_path = _cache_for_video(name, cache_dir)
        annotation = _annotation_for_video(name, annotations_dir)
        metadata = load_cache_metadata(cache_path)
        event_times_s = tuple(event.time_s for event in annotation.events)
        samples = inference_samples_for_cache(
            cache_path,
            stride_s=config.input.inference_stride_s,
            event_times_s=event_times_s,
            positive_window_s=config.labels.positive_window_s,
        )
        if max_samples is not None:
            samples = _limit_samples(samples, max_samples)
        videos.append(
            _ValidationVideo(
                name=name,
                samples=tuple(samples),
                event_times_s=event_times_s,
                duration_s=metadata.duration_s,
            )
        )
    if not videos:
        raise TrainingError("The val split is empty. Add at least one validation video.")
    return videos


def _limit_samples(
    samples: Sequence[DatasetSample], max_samples: int | None
) -> list[DatasetSample]:
    if max_samples is None:
        return list(samples)
    if max_samples <= 0:
        raise TrainingError("max_samples must be positive.")
    if len(samples) <= max_samples:
        return list(samples)
    LOGGER.warning("Limiting training data from %d to %d samples.", len(samples), max_samples)
    selected: list[DatasetSample] = []
    if max_samples >= 2:
        first_positive = next((sample for sample in samples if sample.label == 1.0), None)
        first_negative = next((sample for sample in samples if sample.label == 0.0), None)
        if first_positive is not None and first_negative is not None:
            selected.extend((first_positive, first_negative))
    selected_ids = {id(sample) for sample in selected}
    selected.extend(sample for sample in samples if id(sample) not in selected_ids)
    return selected[:max_samples]


def _make_loader(
    samples: Sequence[DatasetSample],
    *,
    training: bool,
    batch_size: int,
    shuffle: bool,
    offsets_s: Sequence[float] | None = None,
) -> DataLoader[Any]:
    dataset = CausalClipDataset(
        samples,
        offsets_s=DEFAULT_CLIP_OFFSETS_S if offsets_s is None else offsets_s,
        transform=ClipTransform(training=training),
    )
    return DataLoader(dataset, batch_size=batch_size, shuffle=shuffle, num_workers=0)


def _run_train_epoch(
    model: CardEventNet,
    loader: DataLoader[Any],
    optimizer: Any,
    criterion: Any,
    device: torch.device,
    *,
    backbone_frozen: bool,
) -> float:
    model.train()
    if backbone_frozen:
        model.backbone.eval()

    total_loss = 0.0
    sample_count = 0
    for clips, labels in loader:
        clips = clips.to(device=device, dtype=torch.float32)
        labels = labels.to(device=device, dtype=torch.float32)
        optimizer.zero_grad(set_to_none=True)
        logits = model(clips)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()
        batch_size = labels.shape[0]
        total_loss += float(loss.detach().cpu()) * batch_size
        sample_count += batch_size
    if sample_count == 0:
        raise TrainingError("The train loader produced no samples.")
    return total_loss / sample_count


@torch.no_grad()
def _evaluate_validation(
    model: CardEventNet,
    videos: Sequence[_ValidationVideo],
    *,
    batch_size: int,
    device: torch.device,
    merge_window_s: float,
    event_tolerance_s: float,
    offsets_s: Sequence[float],
) -> dict[str, float]:
    model.eval()
    criterion = torch.nn.BCEWithLogitsLoss()
    total_loss = 0.0
    total_samples = 0
    total_events = 0
    total_detected = 0
    total_false = 0
    total_duration_s = 0.0
    latencies: list[float] = []

    for video in videos:
        loader = _make_loader(
            video.samples,
            training=False,
            batch_size=batch_size,
            shuffle=False,
            offsets_s=offsets_s,
        )
        probabilities: list[ProbabilitySample] = []
        sample_offset = 0
        for clips, labels in loader:
            clips = clips.to(device=device, dtype=torch.float32)
            labels = labels.to(device=device, dtype=torch.float32)
            logits = model(clips)
            loss = criterion(logits, labels)
            batch_size_actual = labels.shape[0]
            total_loss += float(loss.detach().cpu()) * batch_size_actual
            total_samples += batch_size_actual
            probabilities.extend(
                ProbabilitySample(
                    time_s=video.samples[sample_offset + index].decision_time_s,
                    probability=float(probability),
                )
                for index, probability in enumerate(torch.sigmoid(logits).detach().cpu().tolist())
            )
            sample_offset += len(logits)

        predictions = probabilities_to_events(
            probabilities,
            threshold=0.5,
            merge_window_s=merge_window_s,
        )
        match = match_events(
            predictions,
            video.event_times_s,
            tolerance_s=event_tolerance_s,
        )
        total_events += len(video.event_times_s)
        total_detected += match.detected_true_events
        total_false += match.false_events
        total_duration_s += video.duration_s
        latencies.extend(match.latencies_s)

    if total_samples == 0:
        raise TrainingError("The validation loader produced no samples.")
    duration_hours = total_duration_s / 3600.0
    return {
        "val_loss": total_loss / total_samples,
        "validation_event_recall": total_detected / total_events if total_events else 0.0,
        "validation_precision": (
            total_detected / (total_detected + total_false)
            if total_detected + total_false
            else 0.0
        ),
        "validation_false_events_per_hour": total_false / duration_hours
        if duration_hours > 0.0
        else 0.0,
        "validation_latency_median_s": median(latencies) if latencies else 0.0,
    }


def _checkpoint_rank(metrics: dict[str, float], target_recall: float) -> tuple[float, ...]:
    recall = metrics["validation_event_recall"]
    false_events_per_hour = metrics["validation_false_events_per_hour"]
    if recall >= target_recall:
        return (1.0, -false_events_per_hour, metrics["validation_precision"])
    return (0.0, recall, -false_events_per_hour, metrics["validation_precision"])


def _save_checkpoint(
    path: Path,
    *,
    model: CardEventNet,
    optimizer: Any,
    epoch: int,
    stage: str,
    config: Config,
    split: VideoSplit,
    device: torch.device,
    metrics: dict[str, float],
    hard_negative_manifest: str | Path | None,
) -> None:
    torch.save(
        {
            "model_state": model.state_dict(),
            "optimizer_state": optimizer.state_dict(),
            "epoch": epoch,
            "stage": stage,
            "config": config.to_dict(),
            "split": split.to_mapping(),
            "device": str(device),
            "metrics": metrics,
            "hard_negative_manifest": (
                str(hard_negative_manifest) if hard_negative_manifest is not None else None
            ),
        },
        path,
    )


def train_model(
    config: Config,
    split: VideoSplit,
    *,
    run_dir: str | Path,
    cache_dir: str | Path = "data/cache",
    annotations_dir: str | Path = "data/annotations",
    max_samples: int | None = None,
    device_override: str | None = None,
    hard_negative_manifest: str | Path | None = None,
) -> TrainingResult:
    """Run the two-stage CardEventNet training schedule."""
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    cache_path = Path(cache_dir)
    annotation_path = Path(annotations_dir)
    seed_everything(config.seed)
    device = resolve_device(device_override or config.training.device)

    train_samples = _training_samples_for_split(
        split,
        cache_dir=cache_path,
        annotations_dir=annotation_path,
        config=config,
        hard_negative_manifest=hard_negative_manifest,
    )
    train_samples = _limit_samples(train_samples, max_samples)
    validation_videos = _validation_videos(
        split,
        cache_dir=cache_path,
        annotations_dir=annotation_path,
        config=config,
        max_samples=max_samples,
    )

    model = build_model(config.model).to(device)
    criterion = torch.nn.BCEWithLogitsLoss()
    metrics_path = run_path / "metrics.jsonl"
    best_rank: tuple[float, ...] | None = None
    best_metrics: dict[str, float] | None = None
    best_epoch = 0
    best_stage = ""
    epoch_number = 0

    stages = (
        ("warmup", config.training.warmup_epochs, config.training.warmup_lr, True),
        ("finetune", config.training.finetune_epochs, config.training.finetune_lr, False),
    )
    with metrics_path.open("w", encoding="utf-8") as metrics_file:
        for stage_name, stage_epochs, learning_rate, backbone_frozen in stages:
            if backbone_frozen:
                freeze_backbone(model)
            else:
                unfreeze_backbone(model)
            optimizer = torch.optim.AdamW(
                (parameter for parameter in model.parameters() if parameter.requires_grad),
                lr=learning_rate,
                weight_decay=config.training.weight_decay,
            )
            for _ in range(stage_epochs):
                epoch_number += 1
                train_loader = _make_loader(
                    train_samples,
                    training=True,
                    batch_size=config.training.batch_size,
                    shuffle=True,
                    offsets_s=config.input.clip_offsets_s,
                )
                train_loss = _run_train_epoch(
                    model,
                    train_loader,
                    optimizer,
                    criterion,
                    device,
                    backbone_frozen=backbone_frozen,
                )
                validation_metrics = _evaluate_validation(
                    model,
                    validation_videos,
                    batch_size=config.training.batch_size,
                    device=device,
                    merge_window_s=config.inference.merge_window_s,
                    event_tolerance_s=config.metrics.event_match_tolerance_s,
                    offsets_s=config.input.clip_offsets_s,
                )
                row = {
                    "epoch": epoch_number,
                    "stage": stage_name,
                    "train_loss": train_loss,
                    "learning_rate": learning_rate,
                    **validation_metrics,
                }
                metrics_file.write(json.dumps(row, allow_nan=False) + "\n")
                metrics_file.flush()
                _save_checkpoint(
                    run_path / "last.pt",
                    model=model,
                    optimizer=optimizer,
                    epoch=epoch_number,
                    stage=stage_name,
                    config=config,
                    split=split,
                    device=device,
                    metrics=row,
                    hard_negative_manifest=hard_negative_manifest,
                )
                rank = _checkpoint_rank(validation_metrics, config.metrics.target_recall)
                if best_rank is None or rank > best_rank:
                    best_rank = rank
                    best_metrics = row
                    best_epoch = epoch_number
                    best_stage = stage_name
                    _save_checkpoint(
                        run_path / "best.pt",
                        model=model,
                        optimizer=optimizer,
                        epoch=epoch_number,
                        stage=stage_name,
                        config=config,
                        split=split,
                        device=device,
                        metrics=row,
                        hard_negative_manifest=hard_negative_manifest,
                    )
                LOGGER.info(
                    "epoch=%d stage=%s train_loss=%.4f val_loss=%.4f recall=%.3f false/hour=%.2f",
                    epoch_number,
                    stage_name,
                    train_loss,
                    validation_metrics["val_loss"],
                    validation_metrics["validation_event_recall"],
                    validation_metrics["validation_false_events_per_hour"],
                )

    if best_metrics is None:
        raise TrainingError("Training completed without producing a checkpoint.")

    summary: dict[str, Any] = {
        "best_epoch": best_epoch,
        "best_stage": best_stage,
        "best_metrics": best_metrics,
        "device": str(device),
        "seed": config.seed,
        "config": config.to_dict(),
        "split": split.to_mapping(),
        "git_commit": _git_commit(),
        "python_version": platform.python_version(),
        "torch_version": torch.__version__,
        "torchvision_version": _torchvision_version(),
        "hard_negative_manifest": (
            str(hard_negative_manifest) if hard_negative_manifest is not None else None
        ),
    }
    (run_path / "summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    save_config(config, run_path / "config.yaml")
    return TrainingResult(run_dir=run_path, summary=summary)


def train_from_files(
    config_path: str | Path,
    split_path: str | Path,
    *,
    output_dir: str | Path = "data/outputs",
    run_name: str | None = None,
    cache_dir: str | Path = "data/cache",
    annotations_dir: str | Path = "data/annotations",
    max_samples: int | None = None,
    device_override: str | None = None,
    hard_negative_manifest: str | Path | None = None,
) -> TrainingResult:
    try:
        config = load_config(config_path)
        split = load_split(split_path)
    except (OSError, RuntimeError, SplitError, ValueError) as exc:
        raise TrainingError(f"Could not load training inputs: {exc}") from exc
    run_dir = _new_run_dir(Path(output_dir), run_name)
    return train_model(
        config,
        split,
        run_dir=run_dir,
        cache_dir=cache_dir,
        annotations_dir=annotations_dir,
        max_samples=max_samples,
        device_override=device_override,
        hard_negative_manifest=hard_negative_manifest,
    )
