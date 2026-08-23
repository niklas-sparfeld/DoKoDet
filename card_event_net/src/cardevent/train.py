from __future__ import annotations

import json
import logging
import math
import os
import platform
import random
import socket
import subprocess
import tempfile
import time
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
from torch.utils.data import DataLoader

from .annotation import AnnotationError, load_annotation
from .cache import CacheError, load_cache_metadata
from .config import Config, ConfigError, load_config, save_config
from .dataset import (
    CausalClipDataset,
    DatasetSample,
    inference_samples_for_cache,
    samples_for_annotation,
)
from .device import resolve_device
from .evaluate import save_operating_plots, save_training_history_plot
from .evaluation import (
    EvaluationError,
    ScoredVideo,
    ThresholdSelection,
    evaluate_streams,
    save_threshold_selection,
    save_validation_stream,
    select_threshold,
)
from .events import ProbabilitySample
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
class TrainingRuntimeOptions:
    """Resolved options that affect one training process."""

    batch_size: int
    num_workers: int
    pin_memory: bool
    precision: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "batch_size": self.batch_size,
            "num_workers": self.num_workers,
            "pin_memory": self.pin_memory,
            "precision": self.precision,
        }


@dataclass(frozen=True, slots=True)
class _ValidationVideo:
    name: str
    samples: tuple[DatasetSample, ...]
    event_times_s: tuple[float, ...]
    duration_s: float


@dataclass(frozen=True, slots=True)
class _ResumeState:
    checkpoint_path: Path
    checkpoint: Mapping[str, Any]
    global_epoch: int
    stage: str
    stage_epoch: int


def seed_everything(seed: int) -> None:
    """Set the random seeds used by the local training loop."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def resolve_runtime_options(
    config: Config,
    device: torch.device,
    *,
    batch_size: int | None = None,
    num_workers: int | None = None,
    precision: str | None = None,
) -> TrainingRuntimeOptions:
    """Resolve command-line runtime overrides for the selected device."""
    resolved_batch_size = config.training.batch_size if batch_size is None else batch_size
    if isinstance(resolved_batch_size, bool) or not isinstance(resolved_batch_size, int):
        raise TrainingError("batch_size must be an integer.")
    if resolved_batch_size <= 0:
        raise TrainingError("batch_size must be positive.")

    resolved_num_workers = 0 if num_workers is None else num_workers
    if isinstance(resolved_num_workers, bool) or not isinstance(resolved_num_workers, int):
        raise TrainingError("num_workers must be an integer.")
    if resolved_num_workers < 0:
        raise TrainingError("num_workers must be zero or greater.")

    if precision is not None and not isinstance(precision, str):
        raise TrainingError("precision must be a string.")
    resolved_precision = "fp32" if precision is None else precision.strip().lower()
    if resolved_precision not in {"fp32", "bf16"}:
        raise TrainingError("precision must be one of: fp32, bf16.")
    if resolved_precision == "bf16":
        if device.type != "cuda" or not torch.cuda.is_available():
            raise TrainingError(
                "BF16 precision requires an available CUDA device. "
                "Use --precision fp32 on CPU or MPS."
            )
        is_supported = getattr(torch.cuda, "is_bf16_supported", None)
        if not callable(is_supported) or not is_supported():
            raise TrainingError(
                "BF16 precision is not supported by this CUDA device. "
                "Use --precision fp32 or a GPU with BF16 support."
            )

    return TrainingRuntimeOptions(
        batch_size=resolved_batch_size,
        num_workers=resolved_num_workers,
        pin_memory=device.type == "cuda",
        precision=resolved_precision,
    )


def _seed_worker(_worker_id: int) -> None:
    """Seed Python and NumPy in each DataLoader worker."""
    worker_seed = torch.initial_seed() % (2**32)
    random.seed(worker_seed)
    np.random.seed(worker_seed)


def _autocast_context(device: torch.device, runtime: TrainingRuntimeOptions) -> Any:
    if runtime.precision == "bf16":
        return torch.autocast(device_type=device.type, dtype=torch.bfloat16)
    return nullcontext()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(text)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _atomic_torch_save(payload: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            torch.save(payload, temporary_file)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


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


def _environment_metadata(device: torch.device) -> dict[str, Any]:
    cuda_available = device.type == "cuda" and torch.cuda.is_available()
    gpu_name: str | None = None
    gpu_count: int | None = None
    gpu_total_memory: int | None = None
    cudnn_version: int | None = None
    if cuda_available:
        gpu_count = torch.cuda.device_count()
        current_device = torch.cuda.current_device()
        gpu_name = torch.cuda.get_device_name(current_device)
        gpu_total_memory = int(torch.cuda.get_device_properties(current_device).total_memory)
        cudnn_version = torch.backends.cudnn.version()

    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "torch_version": torch.__version__,
        "torchvision_version": _torchvision_version(),
        "git_commit": _git_commit(),
        "device": str(device),
        "cuda_version": torch.version.cuda if cuda_available else None,
        "cudnn_version": cudnn_version,
        "gpu_name": gpu_name,
        "gpu_count": gpu_count,
        "gpu_total_memory": gpu_total_memory,
    }


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
            label_state="confirmed_hard_negative",
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
        event_times_s = tuple(
            event.time_s
            for event in annotation.events
            if event.confidence in {None, "confirmed"}
        )
        samples = inference_samples_for_cache(
            cache_path,
            stride_s=config.input.inference_stride_s,
            event_times_s=event_times_s,
            positive_window_s=config.labels.positive_window_s,
            past_exclusion_s=config.labels.negative_past_exclusion_s,
            future_exclusion_s=config.labels.negative_future_exclusion_s,
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
    batch_size: int,
    shuffle: bool,
    offsets_s: Sequence[float] | None = None,
    runtime: TrainingRuntimeOptions | None = None,
) -> DataLoader[Any]:
    if runtime is None:
        runtime = TrainingRuntimeOptions(
            batch_size=batch_size,
            num_workers=0,
            pin_memory=False,
            precision="fp32",
        )
    dataset = CausalClipDataset(
        samples,
        offsets_s=DEFAULT_CLIP_OFFSETS_S if offsets_s is None else offsets_s,
    )
    loader_options: dict[str, Any] = {
        "batch_size": batch_size,
        "shuffle": shuffle,
        "num_workers": runtime.num_workers,
        "pin_memory": runtime.pin_memory,
        "worker_init_fn": _seed_worker,
    }
    if runtime.num_workers > 0:
        loader_options.update(
            {
                "persistent_workers": True,
                "prefetch_factor": 2,
            }
        )
    return DataLoader(dataset, **loader_options)


def _run_train_epoch(
    model: CardEventNet,
    loader: DataLoader[Any],
    optimizer: Any,
    criterion: Any,
    device: torch.device,
    *,
    backbone_frozen: bool,
    runtime: TrainingRuntimeOptions | None = None,
    transform: ClipTransform | None = None,
) -> float:
    if runtime is None:
        runtime = TrainingRuntimeOptions(
            batch_size=loader.batch_size or 1,
            num_workers=loader.num_workers,
            pin_memory=device.type == "cuda",
            precision="fp32",
        )
    model.train()
    if backbone_frozen:
        model.backbone.eval()
    train_transform = transform or ClipTransform(training=True)

    total_loss = 0.0
    sample_count = 0
    for clips, labels in loader:
        clips = clips.to(
            device=device,
            non_blocking=runtime.pin_memory,
        )
        clips = train_transform(clips)
        labels = labels.to(
            device=device,
            dtype=torch.float32,
            non_blocking=runtime.pin_memory,
        )
        optimizer.zero_grad(set_to_none=True)
        with _autocast_context(device, runtime):
            logits = model(clips)
            loss = criterion(logits.float(), labels)
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
    target_recall: float,
    offsets_s: Sequence[float],
    runtime: TrainingRuntimeOptions | None = None,
    transform: ClipTransform | None = None,
) -> dict[str, Any]:
    if runtime is None:
        runtime = TrainingRuntimeOptions(
            batch_size=batch_size,
            num_workers=0,
            pin_memory=device.type == "cuda",
            precision="fp32",
        )
    model.eval()
    eval_transform = transform or ClipTransform(training=False)
    criterion = torch.nn.BCEWithLogitsLoss()
    total_loss = 0.0
    total_samples = 0
    scored_videos: list[ScoredVideo] = []

    for video in videos:
        loader = _make_loader(
            video.samples,
            batch_size=batch_size,
            shuffle=False,
            offsets_s=offsets_s,
            runtime=runtime,
        )
        probabilities = []
        sample_offset = 0
        for clips, labels in loader:
            clips = clips.to(
                device=device,
                non_blocking=runtime.pin_memory,
            )
            clips = eval_transform(clips)
            labels = labels.to(
                device=device,
                dtype=torch.float32,
                non_blocking=runtime.pin_memory,
            )
            with _autocast_context(device, runtime):
                logits = model(clips)
            labeled_mask = labels >= 0.0
            if bool(labeled_mask.any()):
                loss = criterion(logits.float()[labeled_mask], labels[labeled_mask])
                batch_size_actual = int(labeled_mask.sum().item())
                total_loss += float(loss.detach().cpu()) * batch_size_actual
                total_samples += batch_size_actual
            probabilities.extend(
                ProbabilitySample(
                    time_s=video.samples[sample_offset + index].decision_time_s,
                    probability=float(probability),
                    logit=float(logit),
                )
                for index, (logit, probability) in enumerate(
                    zip(
                        logits.float().detach().cpu().tolist(),
                        torch.sigmoid(logits.float()).detach().cpu().tolist(),
                        strict=True,
                    )
                )
            )
            sample_offset += len(logits)
        scored_videos.append(
            ScoredVideo(
                name=video.name,
                duration_s=video.duration_s,
                ground_truth_times_s=video.event_times_s,
                probabilities=tuple(probabilities),
            )
        )

    if total_samples == 0:
        raise TrainingError("The validation loader produced no samples.")
    try:
        fixed_overall, _ = evaluate_streams(
            scored_videos,
            threshold=0.5,
            merge_window_s=merge_window_s,
            event_match_tolerance_s=event_tolerance_s,
            include_streams=False,
        )
        selection = select_threshold(
            scored_videos,
            merge_window_s=merge_window_s,
            event_match_tolerance_s=event_tolerance_s,
            target_recall=target_recall,
        )
    except EvaluationError as exc:
        raise TrainingError(f"Could not evaluate validation streams: {exc}") from exc

    try:
        selected_overall, selected_per_video = evaluate_streams(
            scored_videos,
            threshold=selection.threshold,
            merge_window_s=merge_window_s,
            event_match_tolerance_s=event_tolerance_s,
            include_streams=False,
        )
    except EvaluationError as exc:
        raise TrainingError(f"Could not evaluate selected validation threshold: {exc}") from exc
    recalls = [float(video["event_recall"]) for video in selected_per_video]
    metrics: dict[str, Any] = {
        "val_loss": total_loss / total_samples,
        "validation_fixed_threshold": 0.5,
        "validation_fixed_recall": fixed_overall["event_recall"],
        "validation_fixed_precision": fixed_overall["event_precision"],
        "validation_fixed_f1": fixed_overall["event_f1"],
        "validation_fixed_false_events_per_hour": fixed_overall["false_events_per_hour"],
        "validation_selected_threshold": selection.threshold,
        "validation_selected_recall": selected_overall["event_recall"],
        "validation_selected_precision": selected_overall["event_precision"],
        "validation_selected_f1": selected_overall["event_f1"],
        "validation_selected_false_events_per_hour": selected_overall["false_events_per_hour"],
        "validation_selected_latency_median_s": selected_overall["latency_median_s"],
        "validation_labeled_loss": total_loss / total_samples,
        "validation_event_f1": selected_overall["event_f1"],
        "validation_emission_latency": 0.0,
        "validation_timestamp_error": selected_overall["latency_median_s"],
        "validation_target_recall_met": selection.target_recall_met,
        "validation_maximum_attainable_recall": selection.maximum_attainable_recall,
        "validation_threshold_selection_reason": selection.selection_reason,
        "validation_max_f1": selection.max_f1,
        "validation_max_f1_threshold": selection.max_f1_threshold,
        "validation_recall_min_video": min(recalls, default=0.0),
        "validation_recall_median_video": float(np.median(recalls)) if recalls else 0.0,
        "validation_recall_max_video": max(recalls, default=0.0),
        # Keep the old names in checkpoints and metrics files for consumers
        # from before the calibrated validation metrics were added.
        "validation_event_recall": selected_overall["event_recall"],
        "validation_precision": selected_overall["event_precision"],
        "validation_false_events_per_hour": selected_overall["false_events_per_hour"],
        "validation_latency_median_s": selected_overall["latency_median_s"],
        "_detail": {
            "selected_threshold": selection.threshold,
            "target_recall": target_recall,
            "selected_metrics": selected_overall,
            "fixed_threshold": 0.5,
            "fixed_metrics": fixed_overall,
            "max_f1": selection.max_f1,
            "max_f1_threshold": selection.max_f1_threshold,
            "threshold_candidates": list(selection.candidates),
            "per_video": selected_per_video,
        },
        "_streams": tuple(scored_videos),
    }
    return metrics


def _checkpoint_rank(metrics: Mapping[str, float], target_recall: float) -> tuple[float, ...]:
    recall = (
        metrics["validation_selected_recall"]
        if "validation_selected_recall" in metrics
        else metrics["validation_event_recall"]
    )
    false_events_per_hour = (
        metrics["validation_selected_false_events_per_hour"]
        if "validation_selected_false_events_per_hour" in metrics
        else metrics["validation_false_events_per_hour"]
    )
    precision = (
        metrics["validation_selected_precision"]
        if "validation_selected_precision" in metrics
        else metrics["validation_precision"]
    )
    if bool(metrics.get("validation_target_recall_met", recall >= target_recall)):
        return (1.0, -false_events_per_hour, precision)
    f1 = float(
        metrics.get(
            "validation_selected_f1",
            metrics.get("validation_event_f1", 0.0),
        )
    )
    return (0.0, f1, recall, precision, -false_events_per_hour)


def _load_training_checkpoint(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise TrainingError(f"Checkpoint does not exist: {path}")
    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise TrainingError(f"Could not load checkpoint {path}: {exc}") from exc
    if not isinstance(checkpoint, Mapping):
        raise TrainingError(f"Checkpoint must contain a mapping: {path}")
    return checkpoint


def _validate_checkpoint_compatibility(
    checkpoint: Mapping[str, Any],
    *,
    config: Config,
    split: VideoSplit,
    path: Path,
) -> None:
    checkpoint_config = checkpoint.get("config")
    if not isinstance(checkpoint_config, Mapping):
        raise TrainingError(f"Checkpoint is missing its config: {path}")
    try:
        normalized_checkpoint_config = Config.from_mapping(checkpoint_config).to_dict()
    except (ConfigError, TypeError, ValueError) as exc:
        raise TrainingError(f"Checkpoint has an invalid config: {path}") from exc
    if normalized_checkpoint_config != config.to_dict():
        raise TrainingError(
            "The resume checkpoint config does not match the supplied config. "
            "Resume with the original config."
        )

    checkpoint_split = checkpoint.get("split")
    if checkpoint_split != split.to_mapping():
        raise TrainingError(
            "The resume checkpoint split does not match the supplied split. "
            "Resume with the original split."
        )
    if not isinstance(checkpoint.get("model_state"), Mapping):
        raise TrainingError(f"Checkpoint is missing model_state: {path}")


def _resume_state(
    checkpoint_path: Path,
    *,
    config: Config,
    split: VideoSplit,
) -> _ResumeState:
    checkpoint = _load_training_checkpoint(checkpoint_path)
    _validate_checkpoint_compatibility(
        checkpoint,
        config=config,
        split=split,
        path=checkpoint_path,
    )
    global_epoch_value = checkpoint.get("global_epoch", checkpoint.get("epoch"))
    if isinstance(global_epoch_value, bool) or not isinstance(global_epoch_value, int):
        raise TrainingError(f"Checkpoint has no valid epoch: {checkpoint_path}")
    global_epoch = global_epoch_value

    stages = (
        ("warmup", config.training.warmup_epochs),
        ("finetune", config.training.finetune_epochs),
    )
    stage = checkpoint.get("stage")
    if stage not in {stage_name for stage_name, _ in stages}:
        raise TrainingError(f"Checkpoint has an unknown training stage: {stage}")
    stage_index = next(index for index, (stage_name, _) in enumerate(stages) if stage_name == stage)
    stage_offset = sum(stage_epochs for _, stage_epochs in stages[:stage_index])
    stage_epochs = stages[stage_index][1]
    stage_epoch_value = checkpoint.get("stage_epoch")
    if stage_epoch_value is None:
        stage_epoch = global_epoch - stage_offset
    elif isinstance(stage_epoch_value, int) and not isinstance(stage_epoch_value, bool):
        stage_epoch = stage_epoch_value
    else:
        raise TrainingError(f"Checkpoint has no valid stage_epoch: {checkpoint_path}")

    if stage_epoch < 1 or stage_epoch > stage_epochs or global_epoch != stage_offset + stage_epoch:
        raise TrainingError(f"Checkpoint has an invalid epoch position: {checkpoint_path}")
    total_epochs = sum(stage_epochs for _, stage_epochs in stages)
    if global_epoch >= total_epochs:
        raise TrainingError(
            f"Checkpoint already completed all {total_epochs} configured epochs. "
            "Choose a checkpoint from an earlier epoch."
        )
    return _ResumeState(
        checkpoint_path=checkpoint_path,
        checkpoint=checkpoint,
        global_epoch=global_epoch,
        stage=stage,
        stage_epoch=stage_epoch,
    )


def _best_state(
    run_path: Path,
    *,
    resume_state: _ResumeState,
    config: Config,
    split: VideoSplit,
) -> tuple[tuple[float, ...], dict[str, Any], int, str]:
    best_path = run_path / "best.pt"
    best_checkpoints: list[Mapping[str, Any]] = []
    if best_path.is_file():
        best_checkpoint = _load_training_checkpoint(best_path)
        _validate_checkpoint_compatibility(
            best_checkpoint,
            config=config,
            split=split,
            path=best_path,
        )
        best_checkpoints.append(best_checkpoint)
    else:
        LOGGER.warning("Resume run has no best.pt. Using last.pt as the initial best checkpoint.")
    best_checkpoints.append(resume_state.checkpoint)

    selected: tuple[tuple[float, ...], dict[str, Any], int, str] | None = None
    for checkpoint in best_checkpoints:
        best_metrics = checkpoint.get("best_metrics", checkpoint.get("metrics"))
        if not isinstance(best_metrics, Mapping):
            raise TrainingError("The resume checkpoint does not contain best metrics.")
        best_metrics = dict(best_metrics)
        try:
            best_rank = _checkpoint_rank(best_metrics, config.metrics.target_recall)
            best_epoch = int(checkpoint.get("best_epoch", checkpoint["epoch"]))
            best_stage = str(checkpoint.get("best_stage", checkpoint["stage"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise TrainingError(
                "The resume checkpoint has invalid best-checkpoint metadata."
            ) from exc
        candidate = (best_rank, best_metrics, best_epoch, best_stage)
        if selected is None or candidate[0] > selected[0]:
            selected = candidate
    if selected is None:
        raise TrainingError("The resume checkpoint does not contain best metrics.")
    return selected


def _optimizer_to_device(optimizer: Any, device: torch.device) -> None:
    for state in optimizer.state.values():
        for key, value in state.items():
            if isinstance(value, torch.Tensor):
                state[key] = value.to(device)


def _reconcile_metrics_file(
    path: Path,
    *,
    checkpoint_epoch: int,
    checkpoint_metrics: Mapping[str, Any] | None,
) -> None:
    if not path.exists():
        rows: list[str] = []
    else:
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TrainingError(f"Metrics file contains invalid JSON: {path}") from exc
            row_epoch = row.get("epoch") if isinstance(row, Mapping) else None
            if isinstance(row_epoch, int) and row_epoch <= checkpoint_epoch:
                rows.append(json.dumps(row, allow_nan=False))

    last_epoch = None
    if rows:
        last_row = json.loads(rows[-1])
        last_epoch = last_row.get("epoch")
    if last_epoch != checkpoint_epoch and checkpoint_metrics is not None:
        rows.append(json.dumps(dict(checkpoint_metrics), allow_nan=False))
    _atomic_write_text(path, "".join(f"{row}\n" for row in rows))


def _restore_early_stopping_state(
    checkpoint_path: Path,
    checkpoint: Mapping[str, Any],
    *,
    checkpoint_epoch: int,
    config: Config,
) -> tuple[float, int]:
    """Restore fine-tune early-stopping state, including legacy checkpoints."""
    best_value = checkpoint.get("early_stopping_best")
    epochs_value = checkpoint.get("early_stopping_epochs_without_improvement")
    if best_value is not None or epochs_value is not None:
        if (
            isinstance(best_value, bool)
            or not isinstance(best_value, (int, float))
            or math.isnan(float(best_value))
            or float(best_value) == float("inf")
            or isinstance(epochs_value, bool)
            or not isinstance(epochs_value, int)
            or epochs_value < 0
        ):
            raise TrainingError(f"Checkpoint has invalid early-stopping state: {checkpoint_path}")
        return float(best_value), epochs_value

    metrics_path = checkpoint_path.parent / "metrics.jsonl"
    rows: list[Mapping[str, Any]] = []
    if metrics_path.is_file():
        for line in metrics_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TrainingError(f"Metrics file contains invalid JSON: {metrics_path}") from exc
            if not isinstance(row, Mapping):
                raise TrainingError(f"Metrics file contains an invalid row: {metrics_path}")
            row_epoch = row.get("global_epoch", row.get("epoch"))
            if (
                row.get("stage") == "finetune"
                and isinstance(row_epoch, int)
                and not isinstance(row_epoch, bool)
                and row_epoch <= checkpoint_epoch
            ):
                rows.append(row)

    checkpoint_metrics = checkpoint.get("metrics")
    if isinstance(checkpoint_metrics, Mapping):
        checkpoint_metrics_epoch = checkpoint_metrics.get(
            "global_epoch", checkpoint_metrics.get("epoch")
        )
        if (
            checkpoint_metrics.get("stage") == "finetune"
            and checkpoint_metrics_epoch == checkpoint_epoch
            and not any(
                row.get("global_epoch", row.get("epoch")) == checkpoint_epoch for row in rows
            )
        ):
            rows.append(checkpoint_metrics)

    rows.sort(key=lambda row: int(row.get("global_epoch", row.get("epoch"))))
    best = float("-inf")
    epochs_without_improvement = 0
    early_stopping = config.training.early_stopping
    for row in rows:
        metric_value = row.get(early_stopping.metric, row.get("validation_event_f1", 0.0))
        try:
            metric = float(metric_value)
        except (TypeError, ValueError) as exc:
            raise TrainingError(
                f"Metrics file contains an invalid early-stopping metric: {metrics_path}"
            ) from exc
        if metric > best + early_stopping.min_delta:
            best = metric
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
    return best, epochs_without_improvement


def _save_checkpoint(
    path: Path,
    *,
    model: CardEventNet,
    optimizer: Any,
    epoch: int,
    stage: str,
    stage_epoch: int | None = None,
    global_epoch: int | None = None,
    config: Config,
    split: VideoSplit,
    device: torch.device,
    metrics: Mapping[str, Any],
    hard_negative_manifest: str | Path | None,
    runtime: TrainingRuntimeOptions | None = None,
    max_samples: int | None = None,
    best_metrics: Mapping[str, Any] | None = None,
    best_epoch: int | None = None,
    best_stage: str | None = None,
    best_rank: Sequence[float] | None = None,
    validation_detail: Mapping[str, Any] | None = None,
    best_validation_detail: Mapping[str, Any] | None = None,
    early_stopping_best: float | None = None,
    early_stopping_epochs_without_improvement: int | None = None,
) -> None:
    if runtime is None:
        runtime = TrainingRuntimeOptions(
            batch_size=config.training.batch_size,
            num_workers=0,
            pin_memory=device.type == "cuda",
            precision="fp32",
        )
    payload: dict[str, Any] = {
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "epoch": epoch,
        "global_epoch": epoch if global_epoch is None else global_epoch,
        "stage": stage,
        "stage_epoch": epoch if stage_epoch is None else stage_epoch,
        "config": config.to_dict(),
        "split": split.to_mapping(),
        "runtime": runtime.to_mapping(),
        "device": str(device),
        "metrics": dict(metrics),
        "hard_negative_manifest": (
            str(hard_negative_manifest) if hard_negative_manifest is not None else None
        ),
        "max_samples": max_samples,
    }
    if best_metrics is not None:
        payload["best_metrics"] = dict(best_metrics)
    if best_epoch is not None:
        payload["best_epoch"] = best_epoch
    if best_stage is not None:
        payload["best_stage"] = best_stage
    if best_rank is not None:
        payload["best_rank"] = list(best_rank)
    if validation_detail is not None:
        payload["validation_detail"] = dict(validation_detail)
    if best_validation_detail is not None:
        payload["best_validation_detail"] = dict(best_validation_detail)
    if (early_stopping_best is None) != (early_stopping_epochs_without_improvement is None):
        raise TrainingError("Checkpoint early-stopping state must include both values.")
    if early_stopping_best is not None:
        payload["early_stopping_best"] = early_stopping_best
        payload["early_stopping_epochs_without_improvement"] = (
            early_stopping_epochs_without_improvement
        )
    _atomic_torch_save(payload, path)


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
    batch_size: int | None = None,
    num_workers: int | None = None,
    precision: str | None = None,
    resume_path: str | Path | None = None,
) -> TrainingResult:
    """Run the two-stage CardEventNet training schedule."""
    run_path = Path(run_dir)
    resume_state: _ResumeState | None = None
    if resume_path is not None:
        resume_file = Path(resume_path)
        resume_state = _resume_state(resume_file, config=config, split=split)
        if not run_path.is_dir():
            raise TrainingError(f"Resume run directory does not exist: {run_path}")
    else:
        run_path.mkdir(parents=True, exist_ok=True)

    cache_path = Path(cache_dir)
    annotation_path = Path(annotations_dir)
    seed_everything(config.seed)
    device = resolve_device(device_override or config.training.device)

    save_config(config, run_path / "config.yaml")
    environment = _environment_metadata(device)
    _atomic_write_text(
        run_path / "environment.json",
        json.dumps(environment, indent=2, allow_nan=False) + "\n",
    )

    saved_runtime = resume_state.checkpoint.get("runtime") if resume_state else None
    if saved_runtime is not None and not isinstance(saved_runtime, Mapping):
        raise TrainingError("The resume checkpoint has invalid runtime metadata.")
    if resume_state and isinstance(saved_runtime, Mapping):
        if batch_size is None:
            batch_size = saved_runtime.get("batch_size")
        if num_workers is None:
            num_workers = saved_runtime.get("num_workers")
        if precision is None:
            precision = saved_runtime.get("precision")
    runtime = resolve_runtime_options(
        config,
        device,
        batch_size=batch_size,
        num_workers=num_workers,
        precision=precision,
    )
    train_transform = ClipTransform(training=True)
    eval_transform = ClipTransform(training=False)

    has_saved_max_samples = resume_state is not None and "max_samples" in resume_state.checkpoint
    saved_max_samples = resume_state.checkpoint.get("max_samples") if resume_state else None
    if resume_state and max_samples is None and has_saved_max_samples:
        max_samples = saved_max_samples
    elif resume_state and has_saved_max_samples and max_samples != saved_max_samples:
        raise TrainingError(
            "The resume max-samples setting does not match the checkpoint. "
            "Resume with the original --max-samples value."
        )

    has_saved_manifest = (
        resume_state is not None and "hard_negative_manifest" in resume_state.checkpoint
    )
    saved_manifest = resume_state.checkpoint.get("hard_negative_manifest") if resume_state else None
    if (
        resume_state
        and hard_negative_manifest is None
        and has_saved_manifest
        and saved_manifest is not None
    ):
        hard_negative_manifest = saved_manifest
    elif resume_state and has_saved_manifest and str(hard_negative_manifest) != str(saved_manifest):
        raise TrainingError(
            "The resume hard-negative manifest does not match the checkpoint. "
            "Resume with the original manifest."
        )

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

    model_config = replace(config.model, pretrained=False) if resume_state else config.model
    model = build_model(model_config).to(device)
    if resume_state:
        try:
            model.load_state_dict(resume_state.checkpoint["model_state"])
        except (RuntimeError, TypeError, ValueError) as exc:
            raise TrainingError(
                f"Could not load model state from {resume_state.checkpoint_path}: {exc}"
            ) from exc
    criterion = torch.nn.BCEWithLogitsLoss()
    metrics_path = run_path / "metrics.jsonl"
    best_rank: tuple[float, ...] | None = None
    best_metrics: dict[str, Any] | None = None
    best_epoch = 0
    best_stage = ""
    best_validation_detail: dict[str, Any] | None = None
    resume_early_stopping_best: float | None = None
    resume_epochs_without_improvement = 0
    if resume_state:
        best_rank, best_metrics, best_epoch, best_stage = _best_state(
            run_path,
            resume_state=resume_state,
            config=config,
            split=split,
        )
        _reconcile_metrics_file(
            metrics_path,
            checkpoint_epoch=resume_state.global_epoch,
            checkpoint_metrics=(
                resume_state.checkpoint.get("metrics")
                if isinstance(resume_state.checkpoint.get("metrics"), Mapping)
                else None
            ),
        )
        if resume_state.stage == "finetune":
            (
                resume_early_stopping_best,
                resume_epochs_without_improvement,
            ) = _restore_early_stopping_state(
                resume_state.checkpoint_path,
                resume_state.checkpoint,
                checkpoint_epoch=resume_state.global_epoch,
                config=config,
            )
        resume_detail = resume_state.checkpoint.get("best_validation_detail")
        if isinstance(resume_detail, Mapping):
            best_validation_detail = dict(resume_detail)
        else:
            best_path = run_path / "best.pt"
            best_detail = _load_training_checkpoint(best_path) if best_path.is_file() else None
            if isinstance(best_detail, Mapping):
                detail = best_detail.get("validation_detail")
                if isinstance(detail, Mapping):
                    best_validation_detail = dict(detail)

    stages = (
        ("warmup", config.training.warmup_epochs, config.training.warmup_lr, True),
        ("finetune", config.training.finetune_epochs, config.training.finetune_lr, False),
    )
    start_stage_index = 0
    if resume_state:
        start_stage_index = next(
            index
            for index, (stage_name, *_rest) in enumerate(stages)
            if stage_name == resume_state.stage
        )

    metrics_mode = "a" if resume_state else "w"
    stop_training = False
    with metrics_path.open(metrics_mode, encoding="utf-8") as metrics_file:
        for stage_index, (stage_name, stage_epochs, learning_rate, backbone_frozen) in enumerate(
            stages
        ):
            if stop_training:
                break
            if stage_index < start_stage_index:
                continue
            if backbone_frozen:
                freeze_backbone(model)
            else:
                unfreeze_backbone(model)
            # Warm-up must always reach the fine-tune boundary. Early stopping
            # starts fresh when the backbone is unfrozen, except when resuming
            # inside the fine-tune stage.
            if resume_state and stage_name == resume_state.stage == "finetune":
                early_stopping_best = (
                    float("-inf")
                    if resume_early_stopping_best is None
                    else resume_early_stopping_best
                )
                epochs_without_improvement = resume_epochs_without_improvement
            else:
                early_stopping_best = float("-inf")
                epochs_without_improvement = 0
            optimizer = torch.optim.AdamW(
                (parameter for parameter in model.parameters() if parameter.requires_grad),
                lr=learning_rate,
                weight_decay=config.training.weight_decay,
            )
            stage_start_epoch = 0
            if resume_state and stage_name == resume_state.stage:
                optimizer_state = resume_state.checkpoint.get("optimizer_state")
                if not isinstance(optimizer_state, Mapping):
                    raise TrainingError(
                        f"Checkpoint is missing optimizer state for stage {stage_name}."
                    )
                try:
                    optimizer.load_state_dict(optimizer_state)
                    _optimizer_to_device(optimizer, device)
                except (RuntimeError, ValueError, TypeError) as exc:
                    raise TrainingError(
                        f"Could not restore the {stage_name} optimizer state: {exc}"
                    ) from exc
                stage_start_epoch = resume_state.stage_epoch

            stage_offset = sum(stage_length for _, stage_length, *_rest in stages[:stage_index])
            for stage_epoch in range(stage_start_epoch + 1, stage_epochs + 1):
                epoch_number = stage_offset + stage_epoch
                train_start = time.perf_counter()
                train_loader = _make_loader(
                    train_samples,
                    batch_size=runtime.batch_size,
                    shuffle=True,
                    offsets_s=config.input.clip_offsets_s,
                    runtime=runtime,
                )
                train_loss = _run_train_epoch(
                    model,
                    train_loader,
                    optimizer,
                    criterion,
                    device,
                    backbone_frozen=backbone_frozen,
                    runtime=runtime,
                    transform=train_transform,
                )
                train_duration_s = time.perf_counter() - train_start
                validation_start = time.perf_counter()
                validation_metrics = _evaluate_validation(
                    model,
                    validation_videos,
                    batch_size=runtime.batch_size,
                    device=device,
                    merge_window_s=config.inference.merge_window_s,
                    event_tolerance_s=config.metrics.event_match_tolerance_s,
                    target_recall=config.metrics.target_recall,
                    offsets_s=config.input.clip_offsets_s,
                    runtime=runtime,
                    transform=eval_transform,
                )
                validation_duration_s = time.perf_counter() - validation_start
                validation_streams = validation_metrics.pop("_streams", ())
                validation_detail = validation_metrics.pop("_detail", None)
                if not isinstance(validation_detail, Mapping):
                    validation_detail = {
                        "selected_threshold": validation_metrics.get(
                            "validation_selected_threshold", 0.5
                        ),
                        "target_recall": config.metrics.target_recall,
                        "selected_metrics": {},
                        "fixed_threshold": 0.5,
                        "fixed_metrics": {},
                        "max_f1": validation_metrics.get("validation_max_f1", 0.0),
                        "max_f1_threshold": validation_metrics.get(
                            "validation_max_f1_threshold", 0.5
                        ),
                        "threshold_candidates": [],
                        "per_video": [],
                    }
                validation_detail = dict(validation_detail)
                row: dict[str, Any] = {
                    "epoch": epoch_number,
                    "global_epoch": epoch_number,
                    "stage": stage_name,
                    "stage_epoch": stage_epoch,
                    "train_loss": train_loss,
                    "learning_rate": learning_rate,
                    "train_duration_s": train_duration_s,
                    "train_samples_per_s": len(train_samples) / max(train_duration_s, 1e-9),
                    "validation_duration_s": validation_duration_s,
                    **validation_metrics,
                }
                rank = _checkpoint_rank(validation_metrics, config.metrics.target_recall)
                is_new_best = best_rank is None or rank > best_rank
                if is_new_best:
                    best_rank = rank
                    best_metrics = row
                    best_epoch = epoch_number
                    best_stage = stage_name
                    best_validation_detail = validation_detail

                epoch_detail = {
                    "epoch": epoch_number,
                    "stage": stage_name,
                    "stage_epoch": stage_epoch,
                    **validation_detail,
                }
                _atomic_write_text(
                    run_path / "epochs" / f"epoch-{epoch_number:03d}.json",
                    json.dumps(epoch_detail, indent=2, allow_nan=False) + "\n",
                )
                if isinstance(validation_streams, Sequence):
                    # The validation stream is saved once per epoch. It permits
                    # decoder and threshold experiments without neural inference.
                    try:
                        save_validation_stream(
                            validation_streams,
                            run_path / "validation-streams" / f"epoch-{epoch_number:03d}.json.gz",
                        )
                    except (OSError, TypeError, ValueError) as exc:
                        LOGGER.warning(
                            "Could not save validation stream for epoch %d: %s",
                            epoch_number,
                            exc,
                        )

                early_stopping_triggered = False
                if stage_index == len(stages) - 1:
                    early_metric = float(
                        validation_metrics.get(
                            config.training.early_stopping.metric,
                            validation_metrics.get("validation_event_f1", 0.0),
                        )
                    )
                    if (
                        early_metric
                        > early_stopping_best + config.training.early_stopping.min_delta
                    ):
                        early_stopping_best = early_metric
                        epochs_without_improvement = 0
                    else:
                        epochs_without_improvement += 1
                        early_stopping_triggered = (
                            epochs_without_improvement >= config.training.early_stopping.patience
                        )

                _save_checkpoint(
                    run_path / "last.pt",
                    model=model,
                    optimizer=optimizer,
                    epoch=epoch_number,
                    stage=stage_name,
                    stage_epoch=stage_epoch,
                    global_epoch=epoch_number,
                    config=config,
                    split=split,
                    device=device,
                    metrics=row,
                    hard_negative_manifest=hard_negative_manifest,
                    runtime=runtime,
                    max_samples=max_samples,
                    best_metrics=best_metrics,
                    best_epoch=best_epoch,
                    best_stage=best_stage,
                    best_rank=best_rank,
                    validation_detail=validation_detail,
                    best_validation_detail=best_validation_detail,
                    early_stopping_best=(
                        early_stopping_best if stage_index == len(stages) - 1 else None
                    ),
                    early_stopping_epochs_without_improvement=(
                        epochs_without_improvement if stage_index == len(stages) - 1 else None
                    ),
                )
                if is_new_best:
                    _save_checkpoint(
                        run_path / "best.pt",
                        model=model,
                        optimizer=optimizer,
                        epoch=epoch_number,
                        stage=stage_name,
                        stage_epoch=stage_epoch,
                        global_epoch=epoch_number,
                        config=config,
                        split=split,
                        device=device,
                        metrics=row,
                        hard_negative_manifest=hard_negative_manifest,
                        runtime=runtime,
                        max_samples=max_samples,
                        best_metrics=best_metrics,
                        best_epoch=best_epoch,
                        best_stage=best_stage,
                        best_rank=best_rank,
                        validation_detail=validation_detail,
                        best_validation_detail=best_validation_detail,
                        early_stopping_best=(
                            early_stopping_best if stage_index == len(stages) - 1 else None
                        ),
                        early_stopping_epochs_without_improvement=(
                            epochs_without_improvement if stage_index == len(stages) - 1 else None
                        ),
                    )
                metrics_file.write(json.dumps(row, allow_nan=False) + "\n")
                metrics_file.flush()
                LOGGER.info(
                    "epoch=%d stage=%s train_loss=%.4f val_loss=%.4f "
                    "selected_recall=%.3f selected_threshold=%.2f false/hour=%.2f "
                    "worst_video=%.3f median_video=%.3f samples/s=%.1f",
                    epoch_number,
                    stage_name,
                    train_loss,
                    validation_metrics["val_loss"],
                    validation_metrics.get(
                        "validation_selected_recall",
                        validation_metrics.get("validation_event_recall", 0.0),
                    ),
                    validation_metrics.get("validation_selected_threshold", 0.5),
                    validation_metrics.get(
                        "validation_selected_false_events_per_hour",
                        validation_metrics.get("validation_false_events_per_hour", 0.0),
                    ),
                    validation_metrics.get(
                        "validation_recall_min_video",
                        validation_metrics.get("validation_event_recall", 0.0),
                    ),
                    validation_metrics.get(
                        "validation_recall_median_video",
                        validation_metrics.get("validation_event_recall", 0.0),
                    ),
                    row["train_samples_per_s"],
                )
                if stage_index < len(stages) - 1:
                    continue
                if early_stopping_triggered:
                    LOGGER.info(
                        "Early stopping after %d epochs without %s improvement.",
                        epochs_without_improvement,
                        config.training.early_stopping.metric,
                    )
                    stop_training = True
                    break

    if best_metrics is None:
        raise TrainingError("Training completed without producing a checkpoint.")

    training_rows = [
        json.loads(line)
        for line in (run_path / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    plot_paths: dict[str, str] = {}
    try:
        plot_paths["training_history"] = str(
            save_training_history_plot(
                training_rows,
                output_path=run_path / "training-history.png",
            )
        )
    except EvaluationError as exc:
        LOGGER.warning("Could not save the training history plot: %s", exc)

    if best_validation_detail is not None:
        try:
            selection = ThresholdSelection(
                threshold=float(best_validation_detail["selected_threshold"]),
                metrics=dict(best_validation_detail["selected_metrics"]),
                candidates=tuple(
                    dict(candidate) for candidate in best_validation_detail["threshold_candidates"]
                ),
                max_f1=float(best_validation_detail.get("max_f1", 0.0)),
                max_f1_threshold=float(best_validation_detail.get("max_f1_threshold", 0.0)),
                target_recall_met=bool(
                    best_metrics.get("validation_target_recall_met", False)
                ),
                maximum_attainable_recall=float(
                    best_metrics.get("validation_maximum_attainable_recall", 0.0)
                ),
                selection_reason=str(
                    best_metrics.get("validation_threshold_selection_reason", "legacy")
                ),
            )
            save_threshold_selection(
                run_path / "best.pt",
                selection,
                merge_window_s=config.inference.merge_window_s,
                event_match_tolerance_s=config.metrics.event_match_tolerance_s,
                target_recall=config.metrics.target_recall,
            )
            if selection.candidates:
                plot_paths.update(
                    {
                        name: str(path)
                        for name, path in save_operating_plots(
                            selection.candidates,
                            selected_threshold=selection.threshold,
                            max_f1_threshold=selection.max_f1_threshold,
                            output_dir=run_path / "diagnostics",
                        ).items()
                    }
                )
        except (EvaluationError, KeyError, TypeError, ValueError) as exc:
            LOGGER.warning("Could not save the validation threshold artifacts: %s", exc)

    summary: dict[str, Any] = {
        "best_epoch": best_epoch,
        "best_stage": best_stage,
        "best_metrics": best_metrics,
        "device": str(device),
        "runtime": runtime.to_mapping(),
        "seed": config.seed,
        "config": config.to_dict(),
        "split": split.to_mapping(),
        "environment": environment,
        "git_commit": environment["git_commit"],
        "python_version": environment["python_version"],
        "torch_version": environment["torch_version"],
        "torchvision_version": environment["torchvision_version"],
        "cuda_version": environment["cuda_version"],
        "cudnn_version": environment["cudnn_version"],
        "gpu_name": environment["gpu_name"],
        "gpu_count": environment["gpu_count"],
        "gpu_total_memory": environment["gpu_total_memory"],
        "hard_negative_manifest": (
            str(hard_negative_manifest) if hard_negative_manifest is not None else None
        ),
        "sample_counts_by_label_state": {
            state: sum(sample.label_state == state for sample in train_samples)
            for state in ("positive", "negative", "confirmed_hard_negative", "ignore")
        },
        "effective_positive_fraction": (
            sum(sample.label == 1.0 for sample in train_samples) / len(train_samples)
        ),
        "target_recall_status": {
            "target_recall": config.metrics.target_recall,
            "target_recall_met": bool(
                best_metrics.get("validation_target_recall_met", False)
            ),
            "maximum_attainable_recall": best_metrics.get(
                "validation_maximum_attainable_recall", 0.0
            ),
            "selection_reason": best_metrics.get(
                "validation_threshold_selection_reason", "legacy"),
        },
        "plots": plot_paths,
    }
    _atomic_write_text(
        run_path / "summary.json",
        json.dumps(summary, indent=2, allow_nan=False) + "\n",
    )
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
    batch_size: int | None = None,
    num_workers: int | None = None,
    precision: str | None = None,
    resume_path: str | Path | None = None,
) -> TrainingResult:
    try:
        config = load_config(config_path)
        split = load_split(split_path)
    except (OSError, RuntimeError, SplitError, ValueError) as exc:
        raise TrainingError(f"Could not load training inputs: {exc}") from exc
    if resume_path is not None:
        if run_name is not None:
            raise TrainingError("--resume cannot be combined with --run-name.")
        resume_file = Path(resume_path)
        if resume_file.is_dir():
            run_dir = resume_file
            checkpoint_path = resume_file / "last.pt"
        else:
            checkpoint_path = resume_file
            run_dir = resume_file.parent
        if not run_dir.is_dir():
            raise TrainingError(f"Resume run directory does not exist: {run_dir}")
        if not checkpoint_path.is_file():
            raise TrainingError(f"Resume checkpoint does not exist: {checkpoint_path}")
    else:
        run_dir = _new_run_dir(Path(output_dir), run_name)
        checkpoint_path = None
    return train_model(
        config,
        split,
        run_dir=run_dir,
        cache_dir=cache_dir,
        annotations_dir=annotations_dir,
        max_samples=max_samples,
        device_override=device_override,
        hard_negative_manifest=hard_negative_manifest,
        batch_size=batch_size,
        num_workers=num_workers,
        precision=precision,
        resume_path=checkpoint_path,
    )
