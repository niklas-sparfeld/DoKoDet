from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch.utils.data import DataLoader

from .cache import (
    FULL_FRAME_LETTERBOX_V1,
    CacheError,
    cache_path_for_video,
    load_cache_metadata,
    prepare_inference_cache,
    require_cache_preprocessing,
)
from .config import Config
from .dataset import CausalClipDataset, DatasetSample, inference_samples_for_cache
from .device import resolve_device
from .events import CARD_STATE_CHANGED_EVENT_TYPE, ProbabilitySample, probabilities_to_events
from .model import CardEventNet, build_model
from .paths import DEFAULT_CACHE_DIR
from .transforms import ClipTransform
from .video import VideoError


class InferenceError(RuntimeError):
    """Raised when a checkpoint or cached video cannot be used for inference."""


@dataclass(frozen=True, slots=True)
class LoadedCheckpoint:
    model: CardEventNet
    config: Config
    checkpoint: Mapping[str, Any]
    device: torch.device


def _load_checkpoint_data(checkpoint_path: Path) -> Mapping[str, Any]:
    if not checkpoint_path.is_file():
        raise InferenceError(f"Checkpoint does not exist: {checkpoint_path}")
    try:
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise InferenceError(f"Could not load checkpoint {checkpoint_path}: {exc}") from exc
    if not isinstance(checkpoint, Mapping):
        raise InferenceError(f"Checkpoint must contain a mapping: {checkpoint_path}")
    return checkpoint


def load_checkpoint(
    checkpoint_path: str | Path,
    *,
    device_override: str | None = None,
) -> LoadedCheckpoint:
    """Load a Phase 4 checkpoint without downloading pretrained weights."""
    checkpoint_file = Path(checkpoint_path)
    checkpoint = _load_checkpoint_data(checkpoint_file)
    config_mapping = checkpoint.get("config")
    state_dict = checkpoint.get("model_state")
    if not isinstance(config_mapping, Mapping) or not isinstance(state_dict, Mapping):
        raise InferenceError(
            f"Checkpoint is missing the Phase 4 'config' or 'model_state' fields: {checkpoint_file}"
        )

    try:
        config = Config.from_mapping(config_mapping)
        device = resolve_device(device_override or config.training.device)
        # The checkpoint already contains the weights. Avoid a network request when the
        # original config used ImageNet-pretrained initialization.
        model_config = replace(config.model, pretrained=False)
        model = build_model(model_config).to(device)
        model.load_state_dict(state_dict)
        model.eval()
    except (RuntimeError, ValueError, TypeError) as exc:
        raise InferenceError(f"Could not build the model from {checkpoint_file}: {exc}") from exc

    return LoadedCheckpoint(model=model, config=config, checkpoint=checkpoint, device=device)


@torch.inference_mode()
def predict_cached_samples(
    model: CardEventNet,
    samples: Sequence[DatasetSample],
    *,
    offsets_s: Sequence[float],
    batch_size: int,
    device: torch.device,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[ProbabilitySample]:
    """Run causal inference on cached samples in timestamp order."""
    if batch_size <= 0:
        raise InferenceError("batch_size must be positive.")
    if not samples:
        if progress_callback is not None:
            progress_callback(0, 0)
        return []

    dataset = CausalClipDataset(samples, offsets_s=offsets_s)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    transform = ClipTransform(training=False)
    predictions: list[ProbabilitySample] = []
    sample_offset = 0
    model.eval()
    total = len(samples)
    if progress_callback is not None:
        progress_callback(0, total)
    for clips, _labels in loader:
        clips = clips.to(device=device)
        logits = model(transform(clips)).float()
        logits_values = logits.detach().cpu().tolist()
        probabilities = torch.sigmoid(logits).detach().cpu().tolist()
        for logit, probability in zip(logits_values, probabilities, strict=True):
            predictions.append(
                ProbabilitySample(
                    time_s=samples[sample_offset].decision_time_s,
                    probability=float(probability),
                    logit=float(logit),
                )
            )
            sample_offset += 1
        if progress_callback is not None:
            progress_callback(sample_offset, total)
    return predictions


def infer_cached_video(
    loaded: LoadedCheckpoint,
    cache_dir: str | Path,
    *,
    batch_size: int | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[ProbabilitySample]:
    """Run full-video causal inference using a prepared cache."""
    cache_path = Path(cache_dir)
    try:
        require_cache_preprocessing(cache_path, loaded.config.input.preprocessing)
        samples = inference_samples_for_cache(
            cache_path,
            stride_s=loaded.config.input.inference_stride_s,
        )
    except (CacheError, ValueError) as exc:
        raise InferenceError(f"Could not build inference samples for {cache_path}: {exc}") from exc
    return predict_cached_samples(
        loaded.model,
        samples,
        offsets_s=loaded.config.input.clip_offsets_s,
        batch_size=batch_size or loaded.config.training.batch_size,
        device=loaded.device,
        progress_callback=progress_callback,
    )


def _prediction_payload(
    predictions: Sequence[ProbabilitySample],
    *,
    source_video: str,
    checkpoint: str,
    device: str,
    threshold: float | None,
    merge_window_s: float,
    preprocessing: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_video": source_video,
        "checkpoint": checkpoint,
        "device": device,
        "preprocessing": preprocessing,
        "event_type": CARD_STATE_CHANGED_EVENT_TYPE,
        "probabilities": [prediction.to_mapping() for prediction in predictions],
    }
    if threshold is not None:
        events = probabilities_to_events(
            predictions,
            threshold=threshold,
            merge_window_s=merge_window_s,
        )
        payload["threshold"] = threshold
        payload["merge_window_s"] = merge_window_s
        payload["min_event_gap_s"] = merge_window_s
        payload["events"] = [
            {**event.to_mapping(), "event_type": CARD_STATE_CHANGED_EVENT_TYPE} for event in events
        ]
    return payload


def infer_from_files(
    checkpoint_path: str | Path,
    video_path: str | Path,
    *,
    out_path: str | Path,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    device_override: str | None = None,
    batch_size: int | None = None,
    threshold: float | None = None,
    merge_window_s: float | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Run inference for one source video and save its raw probability stream."""
    video = Path(video_path)
    loaded = load_checkpoint(checkpoint_path, device_override=device_override)
    cache_path = cache_path_for_video(video, cache_root=cache_dir)
    prepare_total = 0

    def report(completed: int, total: int) -> None:
        if progress_callback is not None:
            progress_callback(completed, total)

    def cache_progress(current: int, total: int) -> None:
        nonlocal prepare_total
        prepare_total = total
        report(current, total)

    try:
        if loaded.config.input.preprocessing == FULL_FRAME_LETTERBOX_V1:
            prepare_inference_cache(
                video,
                cache_root=cache_dir,
                cache_fps=loaded.config.input.cache_fps,
                size=loaded.config.input.size,
                progress_callback=cache_progress if progress_callback is not None else None,
            )
        metadata = load_cache_metadata(cache_path)
    except (CacheError, VideoError, RuntimeError) as exc:
        raise InferenceError(
            f"Could not load the prepared cache for {video}: {exc}. "
            "The inference cache could not be prepared."
        ) from exc
    if Path(metadata.source_video).name != video.name:
        raise InferenceError(
            "The cache source video does not match the requested video: "
            f"{metadata.source_video} != {video.name}"
        )

    def infer_progress(current: int, total: int) -> None:
        report(prepare_total + current, prepare_total + total)

    predictions = infer_cached_video(
        loaded,
        cache_path,
        batch_size=batch_size,
        progress_callback=infer_progress if progress_callback is not None else None,
    )
    selected_merge_window = (
        loaded.config.inference.merge_window_s if merge_window_s is None else merge_window_s
    )
    payload = _prediction_payload(
        predictions,
        source_video=metadata.source_video,
        checkpoint=str(Path(checkpoint_path)),
        device=str(loaded.device),
        threshold=threshold,
        merge_window_s=selected_merge_window,
        preprocessing=metadata.preprocessing,
    )
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload
