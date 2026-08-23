from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .annotation import (
    EVENT_TYPES,
    AnnotationError,
    AnnotationEvent,
    VideoAnnotation,
    load_annotation,
    save_annotation,
    validate_annotation,
)
from .evaluate import load_model_streams
from .evaluation import ScoredVideo, select_threshold
from .events import DetectedEvent, match_events, probabilities_to_events
from .infer import InferenceError, load_checkpoint
from .splits import SplitError, load_split
from .video import VideoError, VideoMetadata, read_video_metadata

REVIEW_QUEUE_FORMAT = "cardevent-review-queue-v1"
REVIEW_APPLICATION_FORMAT = "cardevent-review-application-v1"
REVIEW_OUTCOMES = frozenset(
    {
        "confirmed_positive",
        "confirmed_hard_negative",
        "annotation_timestamp_corrected",
        "ignore",
        "unreviewed",
    }
)
REVIEW_STATUSES = frozenset({"unreviewed", "reviewed"})
REVIEW_CATEGORIES = frozenset(
    {
        "unmatched_model_candidate",
        "missed_annotation",
        "low_confidence_match",
        "merged_event_candidate",
        "model_version_disagreement",
        "empty_interval",
    }
)


class ReviewQueueError(RuntimeError):
    """Raised when a review queue cannot be built or applied safely."""


def _finite_non_negative(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReviewQueueError(f"{name} must be a number.")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ReviewQueueError(f"{name} must be finite and non-negative.")
    return result


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def _nearest_annotation(
    video: ScoredVideo,
    time_s: float,
) -> tuple[dict[str, Any] | None, float | None]:
    if not video.ground_truth_times_s:
        return None, None
    index = min(
        range(len(video.ground_truth_times_s)),
        key=lambda item: (abs(video.ground_truth_times_s[item] - time_s), item),
    )
    annotation_time = float(video.ground_truth_times_s[index])
    event_type = (
        video.ground_truth_types[index] if index < len(video.ground_truth_types) else "card_played"
    )
    return (
        {"time_s": annotation_time, "type": event_type, "confidence": "confirmed"},
        abs(annotation_time - time_s),
    )


def _score_near(video: ScoredVideo, time_s: float, radius_s: float) -> float | None:
    scores = [
        sample.probability
        for sample in video.probabilities
        if abs(sample.time_s - time_s) <= radius_s
    ]
    if scores:
        return float(max(scores))
    if not video.probabilities:
        return None
    nearest = min(video.probabilities, key=lambda sample: abs(sample.time_s - time_s))
    return float(nearest.probability)


def _preview(video: ScoredVideo, time_s: float, preview_half_window_s: float) -> dict[str, Any]:
    """Return a reproducible preview window without extracting media files."""
    return {
        "kind": "timestamp_window",
        "source_video": video.name,
        "start_s": max(0.0, time_s - preview_half_window_s),
        "end_s": min(video.duration_s, time_s + preview_half_window_s),
    }


def _item(
    video: ScoredVideo,
    *,
    category: str,
    time_s: float,
    score: float | None,
    nearest: Mapping[str, Any] | None,
    distance_s: float | None,
    preview_half_window_s: float,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if category not in REVIEW_CATEGORIES:
        raise ReviewQueueError(f"Unknown review category: {category}")
    item: dict[str, Any] = {
        "id": hashlib.sha256(
            json.dumps(
                {
                    "video": video.name,
                    "category": category,
                    "timestamp_s": round(time_s, 6),
                    "score": score,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16],
        "video": video.name,
        "timestamp_s": float(time_s),
        "category": category,
        "score": score,
        "nearest_annotation": dict(nearest) if nearest is not None else None,
        "distance_s": distance_s,
        "event_type": None,
        "preview": _preview(video, time_s, preview_half_window_s),
        "status": "unreviewed",
        "outcome": "unreviewed",
    }
    if details:
        item.update(details)
    return item


def _events_for_review(
    video: ScoredVideo,
    *,
    threshold: float,
    merge_window_s: float,
    peak_confirmation_s: float,
) -> list[DetectedEvent]:
    return probabilities_to_events(
        video.probabilities,
        threshold=threshold,
        merge_window_s=merge_window_s,
        peak_confirmation_s=peak_confirmation_s,
    )


def _empty_items(
    video: ScoredVideo,
    *,
    predicted_events: Sequence[DetectedEvent],
    count: int,
    threshold: float,
    exclusion_s: float,
    preview_half_window_s: float,
    seed: int,
) -> list[dict[str, Any]]:
    if count <= 0 or not video.probabilities:
        return []
    eligible = [
        sample
        for sample in video.probabilities
        if sample.probability < threshold
        and all(abs(sample.time_s - event.time_s) > exclusion_s for event in predicted_events)
        and all(
            abs(sample.time_s - event_time) > exclusion_s
            for event_time in video.ground_truth_times_s
        )
    ]
    if len(eligible) < count:
        eligible = [
            sample
            for sample in video.probabilities
            if all(abs(sample.time_s - event.time_s) > exclusion_s for event in predicted_events)
            and all(
                abs(sample.time_s - event_time) > exclusion_s
                for event_time in video.ground_truth_times_s
            )
        ]
    rng = random.Random(
        int.from_bytes(hashlib.sha256(f"{seed}:{video.name}".encode("utf-8")).digest()[:8], "big")
    )
    selected = rng.sample(eligible, min(count, len(eligible)))
    selected.sort(key=lambda sample: sample.time_s)
    items: list[dict[str, Any]] = []
    for sample in selected:
        nearest, distance = _nearest_annotation(video, sample.time_s)
        items.append(
            _item(
                video,
                category="empty_interval",
                time_s=sample.time_s,
                score=float(sample.probability),
                nearest=nearest,
                distance_s=distance,
                preview_half_window_s=preview_half_window_s,
                details={"selection_seed": seed},
            )
        )
    return items


def _queue_items_for_video(
    video: ScoredVideo,
    *,
    threshold: float,
    merge_window_s: float,
    event_match_tolerance_s: float,
    peak_confirmation_s: float,
    low_confidence_margin: float,
    empty_count: int,
    empty_exclusion_s: float,
    preview_half_window_s: float,
    seed: int,
) -> list[dict[str, Any]]:
    predicted = _events_for_review(
        video,
        threshold=threshold,
        merge_window_s=merge_window_s,
        peak_confirmation_s=peak_confirmation_s,
    )
    match = match_events(predicted, video.ground_truth_times_s, tolerance_s=event_match_tolerance_s)
    items: list[dict[str, Any]] = []
    matched_prediction_times = {matched.predicted_time_s for matched in match.matches}
    matched_ground_truth_times = {matched.ground_truth_time_s for matched in match.matches}

    for event in predicted:
        if event.time_s in matched_prediction_times:
            nearest, distance = _nearest_annotation(video, event.time_s)
            if event.probability <= threshold + low_confidence_margin:
                items.append(
                    _item(
                        video,
                        category="low_confidence_match",
                        time_s=event.time_s,
                        score=event.probability,
                        nearest=nearest,
                        distance_s=distance,
                        preview_half_window_s=preview_half_window_s,
                        details={
                            "event_type": (nearest.get("type") if nearest is not None else None)
                        },
                    )
                )
        else:
            nearest, distance = _nearest_annotation(video, event.time_s)
            items.append(
                _item(
                    video,
                    category="unmatched_model_candidate",
                    time_s=event.time_s,
                    score=event.probability,
                    nearest=nearest,
                    distance_s=distance,
                    preview_half_window_s=preview_half_window_s,
                )
            )

    for ground_truth_time in video.ground_truth_times_s:
        if ground_truth_time in matched_ground_truth_times:
            continue
        nearby_predictions = [
            event
            for event in predicted
            if abs(event.time_s - ground_truth_time) <= event_match_tolerance_s
        ]
        nearby_ground_truth = [
            other_time
            for other_time in video.ground_truth_times_s
            if other_time != ground_truth_time
            and abs(other_time - ground_truth_time) <= merge_window_s
        ]
        category = (
            "merged_event_candidate"
            if nearby_predictions or nearby_ground_truth
            else "missed_annotation"
        )
        nearest, distance = _nearest_annotation(video, ground_truth_time)
        items.append(
            _item(
                video,
                category=category,
                time_s=ground_truth_time,
                score=_score_near(video, ground_truth_time, event_match_tolerance_s),
                nearest=nearest,
                distance_s=distance,
                preview_half_window_s=preview_half_window_s,
                details={
                    "event_type": (
                        nearest.get("type", "card_played") if nearest is not None else "card_played"
                    )
                },
            )
        )

    items.extend(
        _empty_items(
            video,
            predicted_events=predicted,
            count=empty_count,
            threshold=threshold,
            exclusion_s=empty_exclusion_s,
            preview_half_window_s=preview_half_window_s,
            seed=seed,
        )
    )
    return items


def _model_disagreement_items(
    primary: ScoredVideo,
    comparison: ScoredVideo,
    *,
    primary_events: Sequence[DetectedEvent],
    comparison_events: Sequence[DetectedEvent],
    tolerance_s: float,
    preview_half_window_s: float,
    primary_version: str,
    comparison_version: str,
) -> list[dict[str, Any]]:
    match = match_events(
        primary_events,
        tuple(event.time_s for event in comparison_events),
        tolerance_s=tolerance_s,
    )
    items: list[dict[str, Any]] = []
    matched_primary = {item.predicted_time_s for item in match.matches}
    matched_comparison = {item.ground_truth_time_s for item in match.matches}
    for event in primary_events:
        if event.time_s in matched_primary:
            continue
        nearest, distance = _nearest_annotation(primary, event.time_s)
        items.append(
            _item(
                primary,
                category="model_version_disagreement",
                time_s=event.time_s,
                score=event.probability,
                nearest=nearest,
                distance_s=distance,
                preview_half_window_s=preview_half_window_s,
                details={
                    "model_versions": {
                        "primary": primary_version,
                        "comparison": comparison_version,
                    },
                    "disagreement": "primary_only",
                },
            )
        )
    for event in comparison_events:
        if event.time_s in matched_comparison:
            continue
        nearest, distance = _nearest_annotation(primary, event.time_s)
        items.append(
            _item(
                primary,
                category="model_version_disagreement",
                time_s=event.time_s,
                score=event.probability,
                nearest=nearest,
                distance_s=distance,
                preview_half_window_s=preview_half_window_s,
                details={
                    "model_versions": {
                        "primary": primary_version,
                        "comparison": comparison_version,
                    },
                    "disagreement": "comparison_only",
                },
            )
        )
    return items


def build_review_queue(
    videos: Sequence[ScoredVideo],
    *,
    checkpoint: str = "",
    split: str = "",
    partition: str,
    threshold: float,
    merge_window_s: float,
    event_match_tolerance_s: float,
    peak_confirmation_s: float = 0.125,
    low_confidence_margin: float = 0.05,
    empty_count: int = 2,
    empty_exclusion_s: float | None = None,
    preview_half_window_s: float = 1.0,
    seed: int = 42,
    comparison_videos: Sequence[ScoredVideo] | None = None,
    model_version: str = "primary",
    comparison_model_version: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic queue. All generated outcomes stay ``unreviewed``."""
    if partition not in {"train", "val", "test"}:
        raise ReviewQueueError("partition must be one of: train, val, test")
    threshold = _finite_non_negative(threshold, "threshold")
    merge_window_s = _finite_non_negative(merge_window_s, "merge_window_s")
    event_match_tolerance_s = _finite_non_negative(
        event_match_tolerance_s, "event_match_tolerance_s"
    )
    low_confidence_margin = _finite_non_negative(low_confidence_margin, "low_confidence_margin")
    preview_half_window_s = _finite_non_negative(preview_half_window_s, "preview_half_window_s")
    if isinstance(empty_count, bool) or not isinstance(empty_count, int) or empty_count < 0:
        raise ReviewQueueError("empty_count must be a non-negative integer.")
    exclusion_s = (
        max(event_match_tolerance_s, merge_window_s)
        if empty_exclusion_s is None
        else _finite_non_negative(empty_exclusion_s, "empty_exclusion_s")
    )
    if not videos:
        raise ReviewQueueError("No videos were provided for review.")

    comparison_by_name = {video.name: video for video in (comparison_videos or ())}
    items: list[dict[str, Any]] = []
    for video in sorted(videos, key=lambda item: item.name):
        primary_items = _queue_items_for_video(
            video,
            threshold=threshold,
            merge_window_s=merge_window_s,
            event_match_tolerance_s=event_match_tolerance_s,
            peak_confirmation_s=peak_confirmation_s,
            low_confidence_margin=low_confidence_margin,
            empty_count=empty_count,
            empty_exclusion_s=exclusion_s,
            preview_half_window_s=preview_half_window_s,
            seed=seed,
        )
        items.extend(primary_items)
        comparison_video = comparison_by_name.get(video.name)
        if comparison_video is not None:
            primary_events = _events_for_review(
                video,
                threshold=threshold,
                merge_window_s=merge_window_s,
                peak_confirmation_s=peak_confirmation_s,
            )
            comparison_events = _events_for_review(
                comparison_video,
                threshold=threshold,
                merge_window_s=merge_window_s,
                peak_confirmation_s=peak_confirmation_s,
            )
            items.extend(
                _model_disagreement_items(
                    video,
                    comparison_video,
                    primary_events=primary_events,
                    comparison_events=comparison_events,
                    tolerance_s=event_match_tolerance_s,
                    preview_half_window_s=preview_half_window_s,
                    primary_version=model_version,
                    comparison_version=comparison_model_version or "comparison",
                )
            )

    items.sort(key=lambda item: (item["video"], item["timestamp_s"], item["category"], item["id"]))
    return {
        "format": REVIEW_QUEUE_FORMAT,
        "checkpoint": checkpoint,
        "split": split,
        "partition": partition,
        "model_version": model_version,
        "comparison_model_version": comparison_model_version,
        "threshold": threshold,
        "merge_window_s": merge_window_s,
        "event_match_tolerance_s": event_match_tolerance_s,
        "peak_confirmation_s": peak_confirmation_s,
        "low_confidence_margin": low_confidence_margin,
        "empty_count_per_video": empty_count,
        "empty_exclusion_s": exclusion_s,
        "preview_half_window_s": preview_half_window_s,
        "selection_seed": seed,
        "items": items,
        "reviewer": None,
    }


def _threshold_for_checkpoint(
    checkpoint_file: Path,
    videos: Sequence[ScoredVideo],
    *,
    loaded: Any,
    partition: str,
) -> float:
    threshold_path = checkpoint_file.with_name("threshold.json")
    try:
        payload = json.loads(threshold_path.read_text(encoding="utf-8"))
        return _finite_non_negative(payload["threshold"], "threshold")
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    if not videos:
        raise ReviewQueueError("Cannot select a review threshold without validation videos.")
    selection = select_threshold(
        videos,
        merge_window_s=loaded.config.inference.merge_window_s,
        event_match_tolerance_s=loaded.config.metrics.event_match_tolerance_s,
        target_recall=loaded.config.metrics.target_recall,
        peak_confirmation_s=getattr(loaded.config.inference, "peak_confirmation_s", 0.125),
    )
    return selection.threshold


def review_queue_from_files(
    checkpoint_path: str | Path,
    split_path: str | Path,
    *,
    partition: str,
    out_path: str | Path,
    cache_dir: str | Path = "data/cache",
    annotations_dir: str | Path = "data/annotations",
    device_override: str | None = None,
    threshold: float | None = None,
    low_confidence_margin: float = 0.05,
    empty_count: int = 2,
    seed: int = 42,
    preview_half_window_s: float = 1.0,
    compare_checkpoint_path: str | Path | None = None,
) -> dict[str, Any]:
    checkpoint_file = Path(checkpoint_path)
    try:
        split = load_split(split_path)
        loaded = load_checkpoint(checkpoint_file, device_override=device_override)
        validation_videos = load_model_streams(
            loaded,
            split,
            "val",
            cache_dir=cache_dir,
            annotations_dir=annotations_dir,
        )
        selected_videos = load_model_streams(
            loaded,
            split,
            partition,
            cache_dir=cache_dir,
            annotations_dir=annotations_dir,
        )
    except (OSError, SplitError, ValueError, InferenceError, RuntimeError) as exc:
        raise ReviewQueueError(f"Could not load review inputs: {exc}") from exc
    selected_threshold = (
        _finite_non_negative(threshold, "threshold")
        if threshold is not None
        else _threshold_for_checkpoint(
            checkpoint_file,
            validation_videos,
            loaded=loaded,
            partition=partition,
        )
    )
    comparison_videos: Sequence[ScoredVideo] | None = None
    comparison_version: str | None = None
    if compare_checkpoint_path is not None:
        comparison_file = Path(compare_checkpoint_path)
        try:
            comparison_loaded = load_checkpoint(comparison_file, device_override=device_override)
            comparison_videos = load_model_streams(
                comparison_loaded,
                split,
                partition,
                cache_dir=cache_dir,
                annotations_dir=annotations_dir,
            )
        except (OSError, SplitError, ValueError, InferenceError, RuntimeError) as exc:
            raise ReviewQueueError(f"Could not load comparison checkpoint: {exc}") from exc
        comparison_version = _sha256(comparison_file) or str(comparison_file)

    payload = build_review_queue(
        selected_videos,
        checkpoint=str(checkpoint_file),
        split=str(Path(split_path)),
        partition=partition,
        threshold=selected_threshold,
        merge_window_s=loaded.config.inference.merge_window_s,
        event_match_tolerance_s=loaded.config.metrics.event_match_tolerance_s,
        peak_confirmation_s=getattr(loaded.config.inference, "peak_confirmation_s", 0.125),
        low_confidence_margin=low_confidence_margin,
        empty_count=empty_count,
        preview_half_window_s=preview_half_window_s,
        seed=seed,
        comparison_videos=comparison_videos,
        model_version=_sha256(checkpoint_file) or str(checkpoint_file),
        comparison_model_version=comparison_version,
    )
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def _load_queue(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewQueueError(f"Could not read review queue {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("format") != REVIEW_QUEUE_FORMAT:
        raise ReviewQueueError(f"Unsupported review queue format: {path}")
    items = payload.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ReviewQueueError("Review queue items must be a list of mappings.")
    for item in items:
        if not isinstance(item.get("id"), str) or not item["id"]:
            raise ReviewQueueError("Each review item needs a non-empty id.")
        if item.get("status") not in REVIEW_STATUSES:
            raise ReviewQueueError("Review item status must be unreviewed or reviewed.")
        if item.get("outcome") not in REVIEW_OUTCOMES:
            raise ReviewQueueError("Review item outcome is invalid.")
        if item["status"] == "unreviewed" and item["outcome"] != "unreviewed":
            raise ReviewQueueError(f"An unreviewed item has an outcome: {item['id']}")
        if item["status"] == "reviewed" and item["outcome"] == "unreviewed":
            raise ReviewQueueError(f"Reviewed item has no outcome: {item['id']}")
        if not isinstance(item.get("video"), str) or not item["video"]:
            raise ReviewQueueError("Each review item needs a video name.")
        _finite_non_negative(item.get("timestamp_s"), "review timestamp")
    return payload


def _video_for_annotation(videos_dir: Path | None, video_name: str) -> Path | None:
    if videos_dir is None or not videos_dir.is_dir():
        return None
    stem = Path(video_name).stem
    matches = sorted(path for path in videos_dir.iterdir() if path.is_file() and path.stem == stem)
    return matches[0] if matches else None


def _annotation_metadata(
    annotation: VideoAnnotation,
    *,
    video_path: Path | None,
) -> VideoMetadata:
    if video_path is not None:
        try:
            return read_video_metadata(video_path)
        except (VideoError, RuntimeError) as exc:
            raise ReviewQueueError(f"Could not inspect source video {video_path}: {exc}") from exc
    max_time = max((event.time_s for event in annotation.events), default=0.0)
    return VideoMetadata(
        path=Path(annotation.video),
        width=1,
        height=1,
        fps=1.0,
        frame_count=max(1, math.ceil(max_time) + 1),
        duration_s=max(1.0, max_time + 1.0),
    )


def _provenance_note(item_id: str, reviewer: str) -> str:
    return f"review_queue={item_id}; reviewer={reviewer}"


def apply_review_queue(
    queue_path: str | Path,
    *,
    annotations_dir: str | Path,
    out_dir: str | Path,
    reviewer: str,
    videos_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Apply explicit human outcomes into a new annotation directory.

    The source directory is read only. The target must be empty or absent.
    """
    if not reviewer or not reviewer.strip():
        raise ReviewQueueError("A non-empty reviewer name is required.")
    queue_file = Path(queue_path)
    payload = _load_queue(queue_file)
    source_dir = Path(annotations_dir).resolve()
    destination = Path(out_dir).resolve()
    if source_dir == destination:
        raise ReviewQueueError("The output annotation directory must differ from the source.")
    if destination.exists() and any(destination.iterdir()):
        raise ReviewQueueError(f"Output annotation directory is not empty: {destination}")

    items = payload["items"]
    review_names = sorted({item["video"] for item in items})
    if any(Path(name).name != name for name in review_names):
        raise ReviewQueueError("Review items must use simple video names.")
    source_paths = sorted(source_dir.glob("*.json"))
    if not source_paths:
        raise ReviewQueueError(f"No source annotations found in {source_dir}")
    names = [path.stem for path in source_paths]
    missing_names = sorted(set(review_names) - set(names))
    if missing_names:
        raise ReviewQueueError(
            "Review items have no source annotation: " + ", ".join(missing_names)
        )
    annotations: dict[str, VideoAnnotation] = {}
    source_hashes: dict[str, str | None] = {}
    metadata_by_name: dict[str, VideoMetadata] = {}
    for name in names:
        source_path = source_dir / f"{name}.json"
        try:
            annotation = load_annotation(source_path)
        except AnnotationError as exc:
            raise ReviewQueueError(
                f"Could not load source annotation {source_path}: {exc}"
            ) from exc
        video_path = _video_for_annotation(Path(videos_dir) if videos_dir else None, name)
        metadata = _annotation_metadata(annotation, video_path=video_path)
        try:
            validate_annotation(annotation, metadata)
        except AnnotationError as exc:
            raise ReviewQueueError(f"Source annotation is invalid for {name}: {exc}") from exc
        annotations[name] = annotation
        metadata_by_name[name] = metadata
        source_hashes[name] = _sha256(source_path)

    updated_annotations = dict(annotations)
    changes: list[dict[str, Any]] = []
    outcome_counts = {outcome: 0 for outcome in REVIEW_OUTCOMES}
    added_count = 0
    corrected_count = 0
    hard_negatives: list[dict[str, Any]] = []
    for item in items:
        outcome = item["outcome"]
        outcome_counts[outcome] += 1
        if outcome in {"unreviewed", "ignore", "confirmed_hard_negative"}:
            if outcome == "confirmed_hard_negative":
                hard_negatives.append(
                    {
                        "video": item["video"],
                        "time_s": item["timestamp_s"],
                        "probability": item.get("score"),
                        "review_item_id": item["id"],
                        "reviewer": reviewer,
                    }
                )
            continue
        annotation = updated_annotations[item["video"]]
        events = list(annotation.events)
        timestamp = float(item["timestamp_s"])
        note = _provenance_note(item["id"], reviewer)
        nearest = item.get("nearest_annotation")
        nearest_time = (
            float(nearest["time_s"])
            if isinstance(nearest, Mapping) and isinstance(nearest.get("time_s"), (int, float))
            else None
        )
        if outcome == "annotation_timestamp_corrected":
            if nearest_time is None:
                raise ReviewQueueError(
                    f"Timestamp correction needs nearest_annotation: {item['id']}"
                )
            matches = [
                index
                for index, event in enumerate(events)
                if abs(event.time_s - nearest_time) <= 1e-6
            ]
            if len(matches) != 1:
                raise ReviewQueueError(
                    f"Timestamp correction does not identify one source event: {item['id']}"
                )
            index = matches[0]
            event = events[index]
            events[index] = AnnotationEvent(
                time_s=timestamp,
                type=event.type,
                confidence=event.confidence,
                notes=f"{event.notes}; {note}" if event.notes else note,
            )
            corrected_count += 1
            changes.append(
                {
                    "review_item_id": item["id"],
                    "video": item["video"],
                    "change": "timestamp_corrected",
                    "from_time_s": event.time_s,
                    "to_time_s": timestamp,
                }
            )
        elif outcome == "confirmed_positive":
            already_present = any(abs(event.time_s - timestamp) <= 0.01 for event in events)
            if not already_present:
                event_type = item.get("event_type")
                if event_type not in EVENT_TYPES:
                    raise ReviewQueueError(
                        f"Confirmed positive needs a valid event_type: {item['id']}"
                    )
                events.append(
                    AnnotationEvent(
                        time_s=timestamp,
                        type=event_type,
                        confidence="confirmed",
                        notes=note,
                    )
                )
                added_count += 1
                changes.append(
                    {
                        "review_item_id": item["id"],
                        "video": item["video"],
                        "change": "event_added",
                        "time_s": timestamp,
                        "type": event_type,
                    }
                )
        updated_annotations[item["video"]] = VideoAnnotation(
            video=annotation.video,
            events=tuple(events),
            legacy_roi=annotation.legacy_roi,
        )

    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        output_path = destination / f"{name}.json"
        save_annotation(updated_annotations[name], output_path, metadata=metadata_by_name[name])

    applied_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary: dict[str, Any] = {
        "format": REVIEW_APPLICATION_FORMAT,
        "queue": str(queue_file),
        "queue_sha256": _sha256(queue_file),
        "source_annotations_dir": str(source_dir),
        "output_annotations_dir": str(destination),
        "reviewer": reviewer,
        "applied_at": applied_at,
        "video_count": len(names),
        "reviewed_video_count": len(review_names),
        "item_count": len(items),
        "outcome_counts": outcome_counts,
        "annotations_added": added_count,
        "timestamps_corrected": corrected_count,
        "hard_negative_count": len(hard_negatives),
        "source_annotation_sha256": source_hashes,
        "changes": changes,
    }
    # Keep the exact reviewed input beside the derived annotations. This keeps
    # per-item status, outcome, and any reviewer timestamps auditable.
    (destination / "reviewed-queue.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (destination / "review-application.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (destination / "review-hard-negatives.json").write_text(
        json.dumps(
            {
                "format": "cardevent-review-hard-negatives-v1",
                "queue": str(queue_file),
                "reviewer": reviewer,
                "items": hard_negatives,
            },
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary
