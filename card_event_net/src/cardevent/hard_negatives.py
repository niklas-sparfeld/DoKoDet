from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evaluate import load_model_streams, select_threshold
from .events import DetectedEvent, match_events, probabilities_to_events
from .infer import InferenceError, load_checkpoint
from .splits import SplitError, VideoSplit, load_split


class HardNegativeError(RuntimeError):
    """Raised when hard-negative mining or loading cannot be completed."""


@dataclass(frozen=True, slots=True)
class HardNegativeSample:
    """One false trigger that can be used as a negative training timestamp."""

    video: str
    time_s: float
    probability: float

    def __post_init__(self) -> None:
        if not self.video:
            raise HardNegativeError("Hard-negative video names must not be empty.")
        if not isfinite(self.time_s) or self.time_s < 0.0:
            raise HardNegativeError("Hard-negative times must be finite and non-negative.")
        if not isfinite(self.probability):
            raise HardNegativeError("Hard-negative probabilities must be finite.")

    def to_mapping(self) -> dict[str, float]:
        return {"time_s": self.time_s, "probability": self.probability}


def false_triggers(
    predicted_events: Sequence[DetectedEvent],
    ground_truth_times_s: Sequence[float],
    *,
    tolerance_s: float,
) -> tuple[DetectedEvent, ...]:
    """Return predicted events that do not match an annotation."""
    match = match_events(predicted_events, ground_truth_times_s, tolerance_s=tolerance_s)
    unmatched = list(predicted_events)
    for matched in match.matches:
        match_index = next(
            (
                index
                for index, event in enumerate(unmatched)
                if event.time_s == matched.predicted_time_s
            ),
            None,
        )
        if match_index is not None:
            unmatched.pop(match_index)
    return tuple(sorted(unmatched, key=lambda event: event.time_s))


def _validate_probability_threshold(threshold: float) -> float:
    if not isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise HardNegativeError("threshold must be finite and between 0 and 1.")
    return float(threshold)


def _validate_non_negative(value: float, name: str) -> float:
    if not isfinite(value) or value < 0.0:
        raise HardNegativeError(f"{name} must be finite and non-negative.")
    return float(value)


def _threshold_sidecar(checkpoint_path: Path) -> float | None:
    path = checkpoint_path.with_name("threshold.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _validate_probability_threshold(float(payload["threshold"]))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, HardNegativeError):
        return None


def _select_mining_threshold(
    checkpoint_path: Path,
    loaded: Any,
    split: VideoSplit,
    *,
    explicit_threshold: float | None,
    cache_dir: str | Path,
    annotations_dir: str | Path,
) -> float:
    if explicit_threshold is not None:
        return _validate_probability_threshold(explicit_threshold)

    persisted = _threshold_sidecar(checkpoint_path)
    if persisted is not None:
        return persisted

    if not split.val:
        raise HardNegativeError(
            "No validation threshold is available. Run evaluation on val first or pass --threshold."
        )
    try:
        validation_videos = load_model_streams(
            loaded,
            split,
            "val",
            cache_dir=cache_dir,
            annotations_dir=annotations_dir,
        )
        selection = select_threshold(
            validation_videos,
            merge_window_s=loaded.config.inference.merge_window_s,
            event_match_tolerance_s=loaded.config.metrics.event_match_tolerance_s,
            target_recall=loaded.config.metrics.target_recall,
        )
    except (InferenceError, ValueError, RuntimeError) as exc:
        raise HardNegativeError(
            f"Could not select a mining threshold from validation: {exc}"
        ) from exc
    return _validate_probability_threshold(selection.threshold)


def _manifest_payload(
    *,
    checkpoint_path: Path,
    split_path: Path,
    threshold: float,
    merge_window_s: float,
    event_match_tolerance_s: float,
    videos: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "format": "cardevent-hard-negatives-v1",
        "checkpoint": str(checkpoint_path),
        "split": str(split_path),
        "partition": "train",
        "threshold": threshold,
        "merge_window_s": merge_window_s,
        "event_match_tolerance_s": event_match_tolerance_s,
        "hard_negative_count": sum(len(video["hard_negatives"]) for video in videos),
        "videos": [dict(video) for video in videos],
    }


def mine_hard_negatives_from_files(
    checkpoint_path: str | Path,
    split_path: str | Path,
    *,
    out_path: str | Path = "data/outputs/hard-negatives.json",
    cache_dir: str | Path = "data/cache",
    annotations_dir: str | Path = "data/annotations",
    device_override: str | None = None,
    batch_size: int | None = None,
    threshold: float | None = None,
    merge_window_s: float | None = None,
    event_match_tolerance_s: float | None = None,
) -> dict[str, Any]:
    """Mine false triggers from the training partition and save a manifest."""
    checkpoint_file = Path(checkpoint_path)
    split_file = Path(split_path)
    try:
        split = load_split(split_file)
        loaded = load_checkpoint(checkpoint_file, device_override=device_override)
    except (OSError, SplitError, ValueError, InferenceError, RuntimeError) as exc:
        raise HardNegativeError(f"Could not load mining inputs: {exc}") from exc
    if not split.train:
        raise HardNegativeError("The train split is empty.")

    selected_threshold = _select_mining_threshold(
        checkpoint_file,
        loaded,
        split,
        explicit_threshold=threshold,
        cache_dir=cache_dir,
        annotations_dir=annotations_dir,
    )
    selected_merge_window = _validate_non_negative(
        loaded.config.inference.merge_window_s if merge_window_s is None else merge_window_s,
        "merge_window_s",
    )
    selected_tolerance = _validate_non_negative(
        loaded.config.metrics.event_match_tolerance_s
        if event_match_tolerance_s is None
        else event_match_tolerance_s,
        "event_match_tolerance_s",
    )
    try:
        scored_videos = load_model_streams(
            loaded,
            split,
            "train",
            cache_dir=cache_dir,
            annotations_dir=annotations_dir,
        )
    except (InferenceError, ValueError, RuntimeError) as exc:
        raise HardNegativeError(f"Could not run inference on the train split: {exc}") from exc

    manifest_videos: list[dict[str, Any]] = []
    for video in scored_videos:
        predicted_events = probabilities_to_events(
            video.probabilities,
            threshold=selected_threshold,
            merge_window_s=selected_merge_window,
        )
        hard_events = false_triggers(
            predicted_events,
            video.ground_truth_times_s,
            tolerance_s=selected_tolerance,
        )
        manifest_videos.append(
            {
                "video": video.name,
                "duration_s": video.duration_s,
                "ground_truth_events_s": list(video.ground_truth_times_s),
                "predicted_events": [event.to_mapping() for event in predicted_events],
                "hard_negatives": [
                    HardNegativeSample(
                        video=video.name,
                        time_s=event.time_s,
                        probability=event.probability,
                    ).to_mapping()
                    for event in hard_events
                ],
            }
        )

    payload = _manifest_payload(
        checkpoint_path=checkpoint_file,
        split_path=split_file,
        threshold=selected_threshold,
        merge_window_s=selected_merge_window,
        event_match_tolerance_s=selected_tolerance,
        videos=manifest_videos,
    )
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def _mapping_list(value: Any, *, context: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise HardNegativeError(f"{context} must be a list of mappings.")
    return list(value)


def load_hard_negative_times(
    manifest_path: str | Path,
    video_names: Sequence[str],
) -> dict[str, tuple[float, ...]]:
    """Load mined timestamps for the requested training videos."""
    path = Path(manifest_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HardNegativeError(f"Could not read hard-negative manifest {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise HardNegativeError("Hard-negative manifest must contain a JSON object.")
    if payload.get("format") != "cardevent-hard-negatives-v1":
        raise HardNegativeError("Unsupported hard-negative manifest format.")
    if payload.get("partition") != "train":
        raise HardNegativeError("Hard-negative manifests must come from the train partition.")

    requested = set(video_names)
    result: dict[str, tuple[float, ...]] = {name: () for name in video_names}
    seen: set[str] = set()
    for video_mapping in _mapping_list(payload.get("videos"), context="videos"):
        name = video_mapping.get("video")
        if not isinstance(name, str) or not name:
            raise HardNegativeError("Each hard-negative video must have a non-empty video name.")
        if name in seen:
            raise HardNegativeError(f"Hard-negative manifest repeats video {name}.")
        seen.add(name)
        if name not in requested:
            continue
        duration = video_mapping.get("duration_s")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool):
            raise HardNegativeError(f"Invalid duration for hard-negative video {name}.")
        duration_s = float(duration)
        if not isfinite(duration_s) or duration_s < 0.0:
            raise HardNegativeError(f"Invalid duration for hard-negative video {name}.")
        times: list[float] = []
        for sample in _mapping_list(
            video_mapping.get("hard_negatives"),
            context=f"hard_negatives for {name}",
        ):
            time_s = sample.get("time_s")
            probability = sample.get("probability")
            if (
                isinstance(time_s, bool)
                or not isinstance(time_s, (int, float))
                or not isfinite(float(time_s))
                or float(time_s) < 0.0
                or float(time_s) > duration_s + 1e-6
            ):
                raise HardNegativeError(f"Invalid hard-negative time for {name}.")
            if (
                isinstance(probability, bool)
                or not isinstance(probability, (int, float))
                or not isfinite(float(probability))
            ):
                raise HardNegativeError(f"Invalid hard-negative probability for {name}.")
            times.append(float(time_s))
        result[name] = tuple(sorted(set(times)))
    return result
