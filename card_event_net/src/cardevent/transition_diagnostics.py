from __future__ import annotations

import gzip
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evaluation import ScoredVideo
from .events import ProbabilitySample


class TransitionDiagnosticError(ValueError):
    """Raised when a saved validation stream cannot be diagnosed."""


TAIL_START_S = 0.50
TAIL_END_S = 1.00
NEXT_EVENT_PRE_EXCLUSION_S = 0.10


def _require_number(value: Any, *, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransitionDiagnosticError(f"{context} must be a number.")
    result = float(value)
    if not isfinite(result):
        raise TransitionDiagnosticError(f"{context} must be finite.")
    return result


def load_validation_stream(path: str | Path) -> tuple[ScoredVideo, ...]:
    """Load the saved validation-stream format without model inference."""
    stream_path = Path(path)
    try:
        with gzip.open(stream_path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise TransitionDiagnosticError(
            f"Could not read validation stream {stream_path}: {exc}"
        ) from exc
    if (
        not isinstance(payload, Mapping)
        or payload.get("format") != "cardevent-validation-stream-v1"
    ):
        raise TransitionDiagnosticError("Unsupported validation stream format.")
    video_payloads = payload.get("videos")
    if not isinstance(video_payloads, list):
        raise TransitionDiagnosticError("Validation stream videos must be a list.")

    videos: list[ScoredVideo] = []
    for index, video_payload in enumerate(video_payloads):
        if not isinstance(video_payload, Mapping):
            raise TransitionDiagnosticError(f"Validation stream video {index} must be a mapping.")
        name = video_payload.get("video")
        timestamps = video_payload.get("decision_timestamps_s")
        probabilities = video_payload.get("probabilities")
        events = video_payload.get("ground_truth_events_s")
        if not isinstance(name, str) or not name:
            raise TransitionDiagnosticError(f"Validation stream video {index} has an invalid name.")
        if not isinstance(timestamps, list) or not isinstance(probabilities, list):
            raise TransitionDiagnosticError(f"Validation stream video {name} has invalid scores.")
        if len(timestamps) != len(probabilities):
            raise TransitionDiagnosticError(f"Validation stream video {name} score lengths differ.")
        if not isinstance(events, list):
            raise TransitionDiagnosticError(f"Validation stream video {name} has invalid events.")
        samples = tuple(
            ProbabilitySample(
                _require_number(time_s, context=f"timestamp for {name}"),
                _require_number(probability, context=f"probability for {name}"),
            )
            for time_s, probability in zip(timestamps, probabilities, strict=True)
        )
        event_times = tuple(
            _require_number(time_s, context=f"event time for {name}") for time_s in events
        )
        videos.append(
            ScoredVideo(
                name=name,
                duration_s=max((sample.time_s for sample in samples), default=0.0),
                ground_truth_times_s=event_times,
                probabilities=samples,
            )
        )
    return tuple(videos)


def _load_reviewed_hard_negatives(
    path: str | Path,
    video_names: set[str],
) -> dict[str, tuple[float, ...]]:
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransitionDiagnosticError(
            f"Could not read reviewed hard-negative manifest {manifest_path}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise TransitionDiagnosticError("Reviewed hard-negative manifest must be a mapping.")
    if payload.get("format") != "cardevent-review-hard-negatives-v1":
        raise TransitionDiagnosticError("Unsupported reviewed hard-negative manifest format.")
    if payload.get("partition") != "val" or payload.get("training_input") is not False:
        raise TransitionDiagnosticError(
            "Transition diagnostics require a validation-scoped, non-training manifest."
        )
    items = payload.get("items")
    if not isinstance(items, list):
        raise TransitionDiagnosticError("Reviewed hard-negative manifest items must be a list.")
    result: dict[str, list[float]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise TransitionDiagnosticError(
                f"Reviewed hard-negative item {index} must be a mapping."
            )
        name = item.get("video")
        if not isinstance(name, str) or name not in video_names:
            raise TransitionDiagnosticError(
                f"Reviewed hard-negative item {index} does not belong to the validation stream."
            )
        result.setdefault(name, []).append(
            _require_number(item.get("time_s"), context=f"hard-negative time for {name}")
        )
    return {name: tuple(sorted(times)) for name, times in result.items()}


def _tail_samples(video: ScoredVideo) -> tuple[ProbabilitySample, ...]:
    events = tuple(sorted(video.ground_truth_times_s))
    selected: dict[float, ProbabilitySample] = {}
    for event_index, event_time_s in enumerate(events):
        next_event_s = events[event_index + 1] if event_index + 1 < len(events) else None
        for sample in video.probabilities:
            if not event_time_s + TAIL_START_S <= sample.time_s <= event_time_s + TAIL_END_S:
                continue
            if (
                next_event_s is not None
                and next_event_s - NEXT_EVENT_PRE_EXCLUSION_S <= sample.time_s < next_event_s
            ):
                continue
            selected[sample.time_s] = sample
    return tuple(selected[time_s] for time_s in sorted(selected))


def transition_diagnostics(
    videos: Sequence[ScoredVideo],
    *,
    threshold: float,
    reviewed_hard_negative_manifest: str | Path | None = None,
) -> dict[str, Any]:
    """Score post-event probability tails and reviewed validation negatives."""
    if not isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise TransitionDiagnosticError("threshold must be finite and between 0 and 1.")
    names = {video.name for video in videos}
    if len(names) != len(videos):
        raise TransitionDiagnosticError("Validation stream video names must be unique.")
    reviewed = (
        _load_reviewed_hard_negatives(reviewed_hard_negative_manifest, names)
        if reviewed_hard_negative_manifest is not None
        else {}
    )

    per_video: list[dict[str, Any]] = []
    all_tail_samples: list[ProbabilitySample] = []
    reviewed_scores: list[dict[str, float | str]] = []
    for video in videos:
        tail_samples = _tail_samples(video)
        all_tail_samples.extend(tail_samples)
        video_scores: list[dict[str, float | str]] = []
        for review_time_s in reviewed.get(video.name, ()):
            if not video.probabilities:
                raise TransitionDiagnosticError(f"Validation stream {video.name} has no scores.")
            nearest = min(
                video.probabilities,
                key=lambda sample: (abs(sample.time_s - review_time_s), sample.time_s),
            )
            score = {
                "video": video.name,
                "reviewed_time_s": review_time_s,
                "nearest_decision_time_s": nearest.time_s,
                "probability": nearest.probability,
            }
            video_scores.append(score)
            reviewed_scores.append(score)
        per_video.append(
            {
                "video": video.name,
                "post_event_tail": {
                    "eligible_sample_count": len(tail_samples),
                    "threshold_exceedance_count": sum(
                        sample.probability >= threshold for sample in tail_samples
                    ),
                },
                "reviewed_hard_negatives": {
                    "count": len(video_scores),
                    "at_or_above_threshold_count": sum(
                        score["probability"] >= threshold for score in video_scores
                    ),
                    "nearest_stream_scores": video_scores,
                },
            }
        )

    return {
        "method": "cardevent-transition-diagnostics-v1",
        "threshold": threshold,
        "post_event_tail_definition": {
            "start_after_event_s": TAIL_START_S,
            "end_after_event_s": TAIL_END_S,
            "exclude_before_next_event_s": NEXT_EVENT_PRE_EXCLUSION_S,
            "boundaries": "inclusive tail bounds; next-event exclusion includes its start",
        },
        "reviewed_hard_negative_manifest": (
            str(reviewed_hard_negative_manifest)
            if reviewed_hard_negative_manifest is not None
            else None
        ),
        "aggregate": {
            "post_event_tail": {
                "eligible_sample_count": len(all_tail_samples),
                "threshold_exceedance_count": sum(
                    sample.probability >= threshold for sample in all_tail_samples
                ),
            },
            "reviewed_hard_negatives": {
                "count": len(reviewed_scores),
                "at_or_above_threshold_count": sum(
                    score["probability"] >= threshold for score in reviewed_scores
                ),
                "nearest_stream_scores": reviewed_scores,
            },
        },
        "videos": per_video,
    }


def diagnose_saved_validation_stream(
    stream_path: str | Path,
    *,
    threshold: float,
    output_path: str | Path,
    reviewed_hard_negative_manifest: str | Path | None = None,
) -> dict[str, Any]:
    """Write pure transition diagnostics from an existing validation stream."""
    payload = transition_diagnostics(
        load_validation_stream(stream_path),
        threshold=threshold,
        reviewed_hard_negative_manifest=reviewed_hard_negative_manifest,
    )
    payload["validation_stream"] = str(stream_path)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload
