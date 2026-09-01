"""Strict paired comparison contracts for the visible-card M3 experiment."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .visible_card_review import ReviewedVisibleCard
from .visible_card_review_freeze import load_frozen_visible_card_review_data
from .visible_card_training import VISIBLE_CARD_BUNDLE_SCHEMA, VISIBLE_CARD_TRAINING_RUN_SCHEMA
from .visible_cards import load_run_artifact

VISIBLE_CARD_COMPARISON_CANDIDATE_SCHEMA = "visible-card-comparison-candidate/v1"
VISIBLE_CARD_CROP_EVALUATION_SCHEMA = "visible-card-crop-evaluation/v1"
VISIBLE_CARD_COMPARISON_SCHEMA = "visible-card-comparison/v1"
VISIBLE_CARD_COMPARISON_CANDIDATES = ("gemini-pseudo-label", "reviewed-box")
VISIBLE_CARD_COMPARISON_POLICIES = (
    "raw_rectangular",
    "oracle_visible_region",
    "conservative_box_only",
)
VISIBLE_CARD_COMPARISON_IOU_THRESHOLDS = tuple(round(0.50 + 0.05 * index, 2) for index in range(10))
FROZEN_RECIPE_FIELDS = (
    "model_variant",
    "package",
    "class_map",
    "input_size",
    "preprocessing",
    "device",
    "seed",
    "epochs",
    "confidence_threshold",
    "non_maximum_suppression",
    "augmentation",
    "final_checkpoint",
)


class VisibleCardComparisonError(ValueError):
    """Raised when a paired visible-card comparison cannot be trusted."""


@dataclass(frozen=True, slots=True)
class VisibleCardComparisonConfig:
    """Inputs for one immutable paired detector and crop comparison."""

    freeze: Path
    gemini_candidate: Path
    reviewed_candidate: Path
    crop_evaluation: Path
    output: Path
    score_threshold: float = 0.5
    match_iou_threshold: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.score_threshold <= 1.0:
            raise VisibleCardComparisonError("score_threshold must be between 0 and 1")
        if not 0.0 < self.match_iou_threshold <= 1.0:
            raise VisibleCardComparisonError("match_iou_threshold must be greater than 0")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise VisibleCardComparisonError(f"could not read comparison input: {path}") from error


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardComparisonError(f"could not read {context}: {path}") from error
    if not isinstance(value, dict):
        raise VisibleCardComparisonError(f"{context} must be a JSON object: {path}")
    return value


def _digest_string(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise VisibleCardComparisonError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(
            c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
            for c in value
        )
    ):
        raise VisibleCardComparisonError(f"{field} must be a simple non-empty identifier")
    return value


def _expected_frames(freeze: dict[str, Any]) -> dict[str, dict[str, Any]]:
    expected: dict[str, dict[str, Any]] = {}
    for partition in ("train", "validation", "challenge"):
        for frame in freeze["partition_manifests"][partition]["frames"]:
            frame_id = frame["frame_id"]
            if frame_id in expected:
                raise VisibleCardComparisonError("frozen frame IDs are not unique")
            expected[frame_id] = frame
    return expected


def _source_key(frame: dict[str, Any]) -> tuple[str, str, int, str]:
    source = frame["source"]
    return (
        source["package_id"],
        source["frame_part_name"],
        source["target_offset_ms"],
        source["frame_sha256"],
    )


def _load_candidate(path: Path, freeze: dict[str, Any]) -> dict[str, Any]:
    value = _read_json(path, "comparison candidate")
    required = {
        "schema_version",
        "candidate_id",
        "label_source",
        "freeze_id",
        "freeze_digest",
        "run",
        "results",
    }
    if set(value) != required:
        raise VisibleCardComparisonError("comparison candidate has unexpected fields")
    if value["schema_version"] != VISIBLE_CARD_COMPARISON_CANDIDATE_SCHEMA:
        raise VisibleCardComparisonError("unsupported comparison candidate schema")
    candidate_id = _identifier(value["candidate_id"], "candidate_id")
    if candidate_id not in VISIBLE_CARD_COMPARISON_CANDIDATES:
        raise VisibleCardComparisonError(f"unsupported comparison candidate: {candidate_id}")
    expected_source = {
        "gemini-pseudo-label": "gemini_pseudo_label",
        "reviewed-box": "reviewed_visible_region",
    }[candidate_id]
    if value["label_source"] != expected_source:
        raise VisibleCardComparisonError("candidate label_source does not match candidate_id")
    if (
        value["freeze_id"] != freeze["freeze_id"]
        or value["freeze_digest"] != freeze["freeze_digest"]
    ):
        raise VisibleCardComparisonError("comparison candidate does not use the frozen review")

    run_descriptor = value["run"]
    if not isinstance(run_descriptor, dict) or set(run_descriptor) != {"path", "sha256"}:
        raise VisibleCardComparisonError("comparison candidate run descriptor is invalid")
    run_path = Path(run_descriptor["path"]).expanduser().resolve()
    if _digest_string(run_descriptor["sha256"], "run.sha256") != _file_digest(run_path):
        raise VisibleCardComparisonError("comparison candidate run digest does not match")
    run = _read_json(run_path, "comparison training run")
    if (
        run.get("schema_version") != VISIBLE_CARD_TRAINING_RUN_SCHEMA
        or run.get("status") != "completed"
    ):
        raise VisibleCardComparisonError(
            "comparison training run must be a completed visible-card run"
        )
    dataset = run.get("dataset")
    recipe = run.get("recipe")
    if not isinstance(dataset, dict) or not isinstance(recipe, dict):
        raise VisibleCardComparisonError("comparison training run lacks dataset or recipe identity")
    for field in ("dataset_digest", "split_digest"):
        _digest_string(dataset.get(field), f"run.dataset.{field}")
    recipe_digest = recipe.get("recipe_digest")
    _digest_string(recipe_digest, "run.recipe.recipe_digest")
    if recipe_digest != _digest(
        {key: item for key, item in recipe.items() if key != "recipe_digest"}
    ):
        raise VisibleCardComparisonError("comparison training recipe digest is stale")
    bundle = run.get("bundle")
    if not isinstance(bundle, dict):
        raise VisibleCardComparisonError("comparison training run lacks native bundle identity")
    bundle_digest = _digest_string(bundle.get("bundle_digest"), "run.bundle.bundle_digest")
    checkpoint_digest = _digest_string(
        bundle.get("checkpoint_sha256"), "run.bundle.checkpoint_sha256"
    )
    source_digests = dataset.get("source_frame_digests")
    if not isinstance(source_digests, list) or not source_digests:
        raise VisibleCardComparisonError("comparison training run lacks source frame digests")
    actual_sources: dict[str, str] = {}
    for row in source_digests:
        if not isinstance(row, dict) or set(row) != {"frame_id", "sha256"}:
            raise VisibleCardComparisonError("comparison training source frame digest is invalid")
        frame_id = _identifier(row["frame_id"], "source frame_id")
        if frame_id in actual_sources:
            raise VisibleCardComparisonError("comparison training frame IDs are not unique")
        actual_sources[frame_id] = _digest_string(row["sha256"], "source frame sha256")
    expected_sources = {
        frame_id: frame["source"]["frame_sha256"]
        for frame_id, frame in _expected_frames(freeze).items()
        if frame["partition"] in {"train", "validation"}
    }
    if actual_sources != expected_sources:
        raise VisibleCardComparisonError(
            "candidate training frames do not match frozen teacher frames"
        )
    if any(field not in recipe for field in FROZEN_RECIPE_FIELDS):
        raise VisibleCardComparisonError("comparison training recipe lacks frozen fields")

    results = value["results"]
    if not isinstance(results, dict) or set(results) != {"validation", "challenge"}:
        raise VisibleCardComparisonError(
            "comparison candidate results must contain validation and challenge"
        )
    result_map: dict[str, dict[str, Any]] = {}
    result_paths: dict[str, list[dict[str, str]]] = {}
    expected = _expected_frames(freeze)
    for partition in ("validation", "challenge"):
        paths = results[partition]
        if not isinstance(paths, list) or not paths:
            raise VisibleCardComparisonError(
                f"candidate {partition} results must be a non-empty list"
            )
        descriptors: list[dict[str, str]] = []
        expected_partition = {
            frame_id: frame
            for frame_id, frame in expected.items()
            if frame["partition"] == partition
        }
        seen: set[str] = set()
        for raw_path in paths:
            result_path = Path(raw_path).expanduser().resolve()
            run_result = load_run_artifact(result_path)
            request = run_result["request"]
            if request["provider"] != "local":
                raise VisibleCardComparisonError(
                    f"comparison result is not from the local detector: {result_path}"
                )
            raw_response = run_result.get("raw_response")
            bundle_identity = (
                raw_response.get("bundle_identity") if isinstance(raw_response, dict) else None
            )
            if (
                not isinstance(bundle_identity, dict)
                or bundle_identity.get("schema_version") != VISIBLE_CARD_BUNDLE_SCHEMA
                or bundle_identity.get("bundle_digest") != bundle_digest
                or bundle_identity.get("checkpoint_sha256") != checkpoint_digest
            ):
                raise VisibleCardComparisonError(
                    "comparison result bundle identity does not match the training run: "
                    f"{result_path}"
                )
            key = (
                request["package_id"],
                request["frame_part_name"],
                request["target_offset_ms"],
                request["image_sha256"],
            )
            matching = [
                frame_id
                for frame_id, frame in expected_partition.items()
                if _source_key(frame) == key
            ]
            if len(matching) != 1:
                raise VisibleCardComparisonError(
                    f"result does not match one frozen {partition} frame: {result_path}"
                )
            frame_id = matching[0]
            if frame_id in seen:
                raise VisibleCardComparisonError(f"duplicate {partition} result for {frame_id}")
            seen.add(frame_id)
            result_map[frame_id] = run_result
            descriptors.append({"path": str(result_path), "sha256": _file_digest(result_path)})
        if seen != set(expected_partition):
            missing = sorted(set(expected_partition) - seen)
            raise VisibleCardComparisonError(
                f"candidate {partition} results do not cover frozen frames: {missing[0]}"
            )
        result_paths[partition] = sorted(descriptors, key=lambda row: row["path"])
    return {
        "candidate_id": candidate_id,
        "label_source": value["label_source"],
        "candidate_path": str(path.resolve()),
        "candidate_sha256": _file_digest(path),
        "run_path": str(run_path),
        "run_sha256": _file_digest(run_path),
        "run": run,
        "result_map": result_map,
        "result_paths": result_paths,
    }


def _recipe_identity(recipe: dict[str, Any]) -> dict[str, Any]:
    return {field: recipe[field] for field in FROZEN_RECIPE_FIELDS}


def _box(value: Any, field: str) -> tuple[float, float, float, float]:
    if not isinstance(value, dict) or set(value) != {"y_min", "x_min", "y_max", "x_max"}:
        raise VisibleCardComparisonError(f"{field} is not a normalized box")
    try:
        y_min, x_min, y_max, x_max = (
            float(value[key]) for key in ("y_min", "x_min", "y_max", "x_max")
        )
    except (TypeError, ValueError) as error:
        raise VisibleCardComparisonError(f"{field} is not numeric") from error
    if not all(math.isfinite(item) and 0 <= item <= 1000 for item in (y_min, x_min, y_max, x_max)):
        raise VisibleCardComparisonError(f"{field} is outside normalized bounds")
    if x_min >= x_max or y_min >= y_max:
        raise VisibleCardComparisonError(f"{field} has no positive area")
    return x_min, y_min, x_max, y_max


def _box_iou(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> float:
    x_min = max(left[0], right[0])
    y_min = max(left[1], right[1])
    x_max = min(left[2], right[2])
    y_max = min(left[3], right[3])
    intersection = max(0.0, x_max - x_min) * max(0.0, y_max - y_min)
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def _reference_cards(frame: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for label in frame["labels"]:
        card = ReviewedVisibleCard.from_mapping(label["card"])
        cards.append(
            {
                "card_id": card.card_id,
                "box": _box(card.derived_box.box_2d.to_mapping(), "reviewed derived box"),
                "box_2d": card.derived_box.box_2d.to_mapping(),
                "side": card.side,
                "identity_usable": card.identity_usability.usable,
                "failure_tags": list(card.failure_tags),
            }
        )
    return cards


def _scores(run: dict[str, Any]) -> list[float]:
    if run["status"] != "ok":
        return []
    raw = run.get("raw_response")
    scores = raw.get("detector_scores") if isinstance(raw, dict) else None
    proposals = run["prediction"]["cards"]
    if not isinstance(scores, list) or len(scores) != len(proposals):
        raise VisibleCardComparisonError("detector result lacks one score per proposal")
    values: list[float] = []
    for score in scores:
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            raise VisibleCardComparisonError("detector scores must be finite numbers in [0, 1]")
        values.append(float(score))
    return values


def _predictions(run: dict[str, Any], score_threshold: float) -> list[dict[str, Any]]:
    scores = _scores(run)
    if run["status"] != "ok":
        return []
    rows = []
    for index, (proposal, score) in enumerate(zip(run["prediction"]["cards"], scores, strict=True)):
        if score >= score_threshold:
            rows.append(
                {
                    "index": index,
                    "score": score,
                    "box": _box(proposal["box_2d"], "detector box"),
                    "box_2d": proposal["box_2d"],
                }
            )
    return rows


def _matches(
    predictions: list[dict[str, Any]], references: list[dict[str, Any]], threshold: float
) -> tuple[list[tuple[int, int, float]], set[int], set[int]]:
    candidates = sorted(
        (
            _box_iou(prediction["box"], reference["box"]),
            prediction_index,
            reference_index,
        )
        for prediction_index, prediction in enumerate(predictions)
        for reference_index, reference in enumerate(references)
        if _box_iou(prediction["box"], reference["box"]) >= threshold
    )
    used_predictions: set[int] = set()
    used_references: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for iou, prediction_index, reference_index in sorted(
        candidates, key=lambda item: (-item[0], item[1], item[2])
    ):
        if prediction_index in used_predictions or reference_index in used_references:
            continue
        used_predictions.add(prediction_index)
        used_references.add(reference_index)
        matches.append((prediction_index, reference_index, iou))
    return matches, used_predictions, used_references


def _average_precision(rows: list[tuple[float, str, int, bool]], reference_count: int) -> float:
    if not reference_count or not rows:
        return 0.0
    ordered = sorted(rows, key=lambda row: (-row[0], row[1], row[2]))
    true_positive = 0
    false_positive = 0
    points: list[tuple[float, float]] = []
    for _score, _frame_id, _index, is_true_positive in ordered:
        true_positive += int(is_true_positive)
        false_positive += int(not is_true_positive)
        points.append(
            (true_positive / reference_count, true_positive / (true_positive + false_positive))
        )
    area = 0.0
    previous_recall = 0.0
    for recall, _precision in sorted(set(points)):
        maximum_precision = max(
            precision for point_recall, precision in points if point_recall >= recall
        )
        area += max(0.0, recall - previous_recall) * maximum_precision
        previous_recall = recall
    return area


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))]


def _frame_metrics(
    frames: list[tuple[str, dict[str, Any], dict[str, Any]]],
    *,
    score_threshold: float,
    iou_threshold: float,
) -> dict[str, Any]:
    references_total = 0
    predictions_total = 0
    matched_total = 0
    false_total = 0
    duplicate_total = 0
    usable_total = 0
    usable_matched = 0
    empty_frames = 0
    empty_false_frames = 0
    latency: list[float] = []
    load_latency: list[float] = []
    by_group: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    by_side: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_card_count: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_tag: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    ap_rows: dict[float, list[tuple[float, str, int, bool]]] = {
        threshold: [] for threshold in VISIBLE_CARD_COMPARISON_IOU_THRESHOLDS
    }
    for frame_id, frame, run in frames:
        references = _reference_cards(frame)
        predictions = _predictions(run, score_threshold)
        references_total += len(references)
        predictions_total += len(predictions)
        latency.append(float(run["latency_ms"]))
        raw = run.get("raw_response")
        if isinstance(raw, dict) and isinstance(raw.get("load_latency_ms"), (int, float)):
            load_latency.append(float(raw["load_latency_ms"]))
        if not references:
            empty_frames += 1
            if predictions:
                empty_false_frames += 1
        matches, used_predictions, used_references = _matches(
            predictions, references, iou_threshold
        )
        duplicate_indices = {
            prediction_index
            for prediction_index in range(len(predictions))
            if prediction_index not in used_predictions
            and any(
                _box_iou(predictions[prediction_index]["box"], reference["box"]) >= iou_threshold
                for reference in references
            )
        }
        false_count = len(predictions) - len(used_predictions) - len(duplicate_indices)
        references_total_for_group = len(references)
        matched_count = len(matches)
        matched_total += matched_count
        false_total += false_count
        duplicate_total += len(duplicate_indices)
        usable_total += sum(card["identity_usable"] for card in references)
        usable_matched += sum(
            references[reference_index]["identity_usable"]
            for _prediction_index, reference_index, _iou in matches
        )
        group = frame["source"]["source_lineage_group"]
        by_group[group].append(
            (references_total_for_group, matched_count, false_count + len(duplicate_indices))
        )
        for card in references:
            by_side[card["side"]][1] += 1
        for _prediction_index, reference_index, _iou in matches:
            by_side[references[reference_index]["side"]][0] += 1
        by_card_count[str(len(references))][0] += matched_count
        by_card_count[str(len(references))][1] += len(references)
        tags = set(frame["review"].get("failure_tags", []))
        for card in references:
            tags.update(card["failure_tags"])
        for tag in tags:
            by_tag[tag][0] += matched_count
            by_tag[tag][1] += len(references)
        for threshold in VISIBLE_CARD_COMPARISON_IOU_THRESHOLDS:
            threshold_matches, threshold_used_predictions, _threshold_used_references = _matches(
                predictions, references, threshold
            )
            true_positive_indices = {
                prediction_index for prediction_index, _reference_index, _iou in threshold_matches
            }
            for prediction_index, prediction in enumerate(predictions):
                ap_rows[threshold].append(
                    (
                        prediction["score"],
                        frame_id,
                        prediction_index,
                        prediction_index in true_positive_indices,
                    )
                )
        # Keep a frame-level result in the caller. The aggregate metrics are below.
    group_metrics = {
        group: {
            "reference_card_count": sum(row[0] for row in values),
            "matched_card_count": sum(row[1] for row in values),
            "false_or_duplicate_count": sum(row[2] for row in values),
            "instance_recall": sum(row[1] for row in values) / sum(row[0] for row in values)
            if sum(row[0] for row in values)
            else 0.0,
        }
        for group, values in sorted(by_group.items())
    }
    side_metrics = {
        side: {
            "matched_card_count": values[0],
            "reference_card_count": values[1],
            "instance_recall": values[0] / values[1] if values[1] else 0.0,
        }
        for side, values in sorted(by_side.items())
    }
    return {
        "frame_count": len(frames),
        "reference_card_count": references_total,
        "proposal_count": predictions_total,
        "matched_card_count": matched_total,
        "instance_recall": matched_total / references_total if references_total else 0.0,
        "false_proposal_count": false_total,
        "false_proposals_per_frame": false_total / len(frames) if frames else 0.0,
        "duplicate_proposal_count": duplicate_total,
        "duplicate_proposals_per_frame": duplicate_total / len(frames) if frames else 0.0,
        "usable_reference_count": usable_total,
        "usable_crop_recall": usable_matched / usable_total if usable_total else 0.0,
        "empty_frame_count": empty_frames,
        "empty_frame_false_positive_rate": empty_false_frames / empty_frames
        if empty_frames
        else 0.0,
        "box_ap_iou_0_50": _average_precision(ap_rows[0.5], references_total),
        "box_ap_iou_0_50_to_0_95": statistics.mean(
            _average_precision(ap_rows[threshold], references_total)
            for threshold in VISIBLE_CARD_COMPARISON_IOU_THRESHOLDS
        ),
        "box_ap_by_iou": {
            f"{threshold:.2f}": _average_precision(ap_rows[threshold], references_total)
            for threshold in VISIBLE_CARD_COMPARISON_IOU_THRESHOLDS
        },
        "by_source_lineage_group": group_metrics,
        "by_side": side_metrics,
        "by_visible_card_count": {
            key: {
                "matched_card_count": value[0],
                "reference_card_count": value[1],
                "instance_recall": value[0] / value[1] if value[1] else 0.0,
            }
            for key, value in sorted(by_card_count.items(), key=lambda item: int(item[0]))
        },
        "by_failure_tag": {
            key: {
                "matched_card_count": value[0],
                "reference_card_count": value[1],
                "instance_recall": value[0] / value[1] if value[1] else 0.0,
            }
            for key, value in sorted(by_tag.items())
        },
        "latency_median_ms": statistics.median(latency) if latency else 0.0,
        "latency_p95_ms": _percentile(latency, 0.95),
        "load_latency_median_ms": statistics.median(load_latency) if load_latency else 0.0,
        "load_latency_p95_ms": _percentile(load_latency, 0.95),
    }


def _detector_metrics(
    freeze: dict[str, Any],
    candidate: dict[str, Any],
    *,
    score_threshold: float,
    iou_threshold: float,
) -> dict[str, Any]:
    frames = _expected_frames(freeze)
    reports: dict[str, Any] = {}
    for partition in ("validation", "challenge"):
        rows = [
            (frame_id, frames[frame_id], candidate["result_map"][frame_id])
            for frame_id in sorted(frames)
            if frames[frame_id]["partition"] == partition
        ]
        reports[partition] = _frame_metrics(
            rows, score_threshold=score_threshold, iou_threshold=iou_threshold
        )
    return reports


def _paired_predictions(
    freeze: dict[str, Any], candidates: dict[str, dict[str, Any]], score_threshold: float
) -> list[dict[str, Any]]:
    frames = _expected_frames(freeze)
    rows: list[dict[str, Any]] = []
    for frame_id in sorted(frames):
        frame = frames[frame_id]
        if frame["partition"] == "train":
            continue
        candidate_predictions: dict[str, Any] = {}
        for candidate_id, candidate in candidates.items():
            run = candidate["result_map"][frame_id]
            raw = run.get("raw_response")
            candidate_predictions[candidate_id] = {
                "status": run["status"],
                "predictions": [
                    {"index": row["index"], "score": row["score"], "box_2d": row["box_2d"]}
                    for row in _predictions(run, score_threshold)
                ],
                "inference_latency_ms": run["latency_ms"],
                "load_latency_ms": raw.get("load_latency_ms") if isinstance(raw, dict) else None,
            }
        rows.append(
            {
                "frame_id": frame_id,
                "partition": frame["partition"],
                "source_lineage_group": frame["source"]["source_lineage_group"],
                "failure_tags": sorted(set(frame["review"].get("failure_tags", []))),
                "references": [
                    {
                        "card_id": card["card_id"],
                        "box_2d": card["box_2d"],
                        "side": card["side"],
                        "identity_usable": card["identity_usable"],
                        "failure_tags": card["failure_tags"],
                    }
                    for card in _reference_cards(frame)
                ],
                "candidates": candidate_predictions,
            }
        )
    return rows


def _load_crop_evaluation(
    path: Path, freeze: dict[str, Any], candidate_ids: set[str]
) -> dict[str, Any]:
    value = _read_json(path, "visible-card crop evaluation")
    required = {
        "schema_version",
        "freeze_id",
        "freeze_digest",
        "partitions",
        "classifier_bundle_sha256",
    }
    if set(value) != required or value["schema_version"] != VISIBLE_CARD_CROP_EVALUATION_SCHEMA:
        raise VisibleCardComparisonError("visible-card crop evaluation has an invalid schema")
    if (
        value["freeze_id"] != freeze["freeze_id"]
        or value["freeze_digest"] != freeze["freeze_digest"]
    ):
        raise VisibleCardComparisonError(
            "visible-card crop evaluation does not use the frozen review"
        )
    partitions = value["partitions"]
    if not isinstance(partitions, dict) or set(partitions) != {"validation", "challenge"}:
        raise VisibleCardComparisonError(
            "crop evaluation must contain validation and challenge partitions"
        )
    _digest_string(value["classifier_bundle_sha256"], "classifier_bundle_sha256")
    if not isinstance(value["partitions"], dict):
        raise VisibleCardComparisonError("crop evaluation partitions must be an object")
    loaded: dict[str, Any] = {}
    identity_targets: dict[tuple[str, str], str] = {}
    for partition in ("validation", "challenge"):
        partition_value = partitions[partition]
        if not isinstance(partition_value, dict) or set(partition_value) != {"candidates"}:
            raise VisibleCardComparisonError("crop evaluation partition must contain candidates")
        candidates = partition_value["candidates"]
        if not isinstance(candidates, dict) or set(candidates) != candidate_ids:
            raise VisibleCardComparisonError(
                "crop evaluation candidates do not match detector candidates"
            )
        expected_cards = {
            (frame_id, card["card_id"]): card
            for frame_id, frame in _expected_frames(freeze).items()
            if frame["partition"] == partition
            for card in _reference_cards(frame)
        }
        for candidate_id in sorted(candidate_ids):
            candidate = candidates[candidate_id]
            if not isinstance(candidate, dict) or set(candidate) != {"policies"}:
                raise VisibleCardComparisonError("crop evaluation candidate has unexpected fields")
            policies = candidate["policies"]
            if not isinstance(policies, dict) or set(policies) != set(
                VISIBLE_CARD_COMPARISON_POLICIES
            ):
                raise VisibleCardComparisonError(
                    "crop evaluation must contain all frozen crop policies"
                )
            loaded.setdefault(candidate_id, {})[partition] = {}
            for policy in VISIBLE_CARD_COMPARISON_POLICIES:
                policy_value = policies[policy]
                if (
                    not isinstance(policy_value, dict)
                    or set(policy_value) != {"rows"}
                    or not isinstance(policy_value["rows"], list)
                ):
                    raise VisibleCardComparisonError(f"crop evaluation policy is invalid: {policy}")
                seen: set[tuple[str, str]] = set()
                rows: list[dict[str, Any]] = []
                for row in policy_value["rows"]:
                    fields = {
                        "frame_id",
                        "card_id",
                        "crop_accepted",
                        "detected",
                        "identity_prediction",
                        "identity_target",
                        "identity_correct",
                    }
                    if not isinstance(row, dict) or set(row) != fields:
                        raise VisibleCardComparisonError(
                            "crop evaluation row has unexpected fields"
                        )
                    key = (row["frame_id"], row["card_id"])
                    if key in seen or key not in expected_cards:
                        raise VisibleCardComparisonError(
                            "crop evaluation rows do not match frozen reference cards"
                        )
                    seen.add(key)
                    for field in ("crop_accepted", "detected"):
                        if not isinstance(row[field], bool):
                            raise VisibleCardComparisonError(
                                f"crop evaluation {field} must be boolean"
                            )
                    if not isinstance(row["identity_target"], str) or not row["identity_target"]:
                        raise VisibleCardComparisonError(
                            "crop evaluation identity_target must be non-empty"
                        )
                    previous_target = identity_targets.get(key)
                    if previous_target is not None and previous_target != row["identity_target"]:
                        raise VisibleCardComparisonError(
                            "crop evaluation identity target differs across paired rows"
                        )
                    identity_targets[key] = row["identity_target"]
                    if row["identity_prediction"] is not None and not isinstance(
                        row["identity_prediction"], str
                    ):
                        raise VisibleCardComparisonError(
                            "crop evaluation identity_prediction must be a string or null"
                        )
                    if not isinstance(row["identity_correct"], bool):
                        raise VisibleCardComparisonError(
                            "crop evaluation identity_correct must be boolean"
                        )
                    expected_correct = (
                        row["identity_prediction"] is not None
                        and row["identity_prediction"] == row["identity_target"]
                    )
                    if row["identity_correct"] != expected_correct:
                        raise VisibleCardComparisonError(
                            "identity_correct conflicts with prediction and target"
                        )
                    if row["identity_correct"] and not (row["crop_accepted"] and row["detected"]):
                        raise VisibleCardComparisonError(
                            "a correct identity needs an accepted detected crop"
                        )
                    rows.append(row)
                if seen != set(expected_cards):
                    raise VisibleCardComparisonError(
                        "crop evaluation policy does not cover all "
                        f"{partition} reference cards: {policy}"
                    )
                loaded[candidate_id][partition][policy] = rows
    return {
        "path": str(path.resolve()),
        "sha256": _file_digest(path),
        "partitions": ["validation", "challenge"],
        "classifier_bundle_sha256": value["classifier_bundle_sha256"],
        "rows": loaded,
    }


def _crop_metrics(crop: dict[str, Any], freeze: dict[str, Any]) -> dict[str, Any]:
    frames = _expected_frames(freeze)
    result: dict[str, Any] = {}
    for candidate_id, candidate_partitions in crop["rows"].items():
        result[candidate_id] = {}
        for partition, policies in candidate_partitions.items():
            result[candidate_id][partition] = {}
            for policy, rows in policies.items():
                usable = [
                    row
                    for row in rows
                    if next(
                        card
                        for card in _reference_cards(frames[row["frame_id"]])
                        if card["card_id"] == row["card_id"]
                    )["identity_usable"]
                ]
                accepted_usable = [row for row in usable if row["crop_accepted"]]
                evaluated = [row for row in usable if row["crop_accepted"] and row["detected"]]
                correct = [row for row in evaluated if row["identity_correct"]]
                result[candidate_id][partition][policy] = {
                    "reference_usable_card_count": len(usable),
                    "accepted_usable_crop_count": len(accepted_usable),
                    "evaluated_usable_crop_count": len(evaluated),
                    "correct_identity_count": len(correct),
                    "usable_crop_recall": len(accepted_usable) / len(usable) if usable else 0.0,
                    "identity_accuracy_conditional_on_usable_crop": len(correct) / len(evaluated)
                    if evaluated
                    else 0.0,
                    "end_to_end_correct_identity_recall": len(correct) / len(usable)
                    if usable
                    else 0.0,
                }
    return result


def _direction(delta: float, *, epsilon: float = 1e-12) -> str:
    if delta > epsilon:
        return "improves"
    if delta < -epsilon:
        return "harms"
    return "does_not_clearly_change"


def compare_visible_card_detectors(config: VisibleCardComparisonConfig) -> dict[str, Any]:
    """Create one paired, provenance-checked M3 comparison report."""

    freeze = load_frozen_visible_card_review_data(config.freeze)
    candidates = {
        "gemini-pseudo-label": _load_candidate(config.gemini_candidate, freeze),
        "reviewed-box": _load_candidate(config.reviewed_candidate, freeze),
    }
    recipes = {
        candidate_id: _recipe_identity(candidate["run"]["recipe"])
        for candidate_id, candidate in candidates.items()
    }
    if recipes["gemini-pseudo-label"] != recipes["reviewed-box"]:
        raise VisibleCardComparisonError("candidates do not use the same frozen recipe and seed")
    split_digests = {
        candidate["run"]["dataset"]["split_digest"] for candidate in candidates.values()
    }
    if len(split_digests) != 1:
        raise VisibleCardComparisonError("candidates do not use the same frozen split digest")
    crop = _load_crop_evaluation(config.crop_evaluation, freeze, set(candidates))
    detector_metrics = {
        candidate_id: _detector_metrics(
            freeze,
            candidate,
            score_threshold=config.score_threshold,
            iou_threshold=config.match_iou_threshold,
        )
        for candidate_id, candidate in candidates.items()
    }
    validation_baseline = detector_metrics["gemini-pseudo-label"]["validation"]
    validation_reviewed = detector_metrics["reviewed-box"]["validation"]
    ap_delta = (
        validation_reviewed["box_ap_iou_0_50_to_0_95"]
        - validation_baseline["box_ap_iou_0_50_to_0_95"]
    )
    recall_delta = validation_reviewed["instance_recall"] - validation_baseline["instance_recall"]
    if ap_delta > 1e-12 and recall_delta >= -1e-12 or recall_delta > 1e-12 and ap_delta >= -1e-12:
        localization_direction = "improves"
    elif ap_delta < -1e-12 and recall_delta <= 1e-12 or recall_delta < -1e-12 and ap_delta <= 1e-12:
        localization_direction = "harms"
    else:
        localization_direction = "does_not_clearly_change"
    crop_metrics = _crop_metrics(crop, freeze)
    crop_direction: dict[str, dict[str, str]] = {}
    for partition in ("validation", "challenge"):
        crop_direction[partition] = {}
        for policy in VISIBLE_CARD_COMPARISON_POLICIES:
            baseline = crop_metrics["gemini-pseudo-label"][partition][policy][
                "end_to_end_correct_identity_recall"
            ]
            reviewed = crop_metrics["reviewed-box"][partition][policy][
                "end_to_end_correct_identity_recall"
            ]
            crop_direction[partition][policy] = _direction(reviewed - baseline)
    crop_policy_effect = {
        candidate_id: {
            partition: {
                policy: _direction(
                    metrics[partition][policy]["end_to_end_correct_identity_recall"]
                    - metrics[partition]["raw_rectangular"]["end_to_end_correct_identity_recall"]
                )
                for policy in VISIBLE_CARD_COMPARISON_POLICIES
                if policy != "raw_rectangular"
            }
            for partition in ("validation", "challenge")
        }
        for candidate_id, metrics in crop_metrics.items()
    }
    oracle_values = [
        metrics[partition]["oracle_visible_region"]["end_to_end_correct_identity_recall"]
        for metrics in crop_metrics.values()
        for partition in ("validation", "challenge")
    ]
    raw_values = [
        metrics[partition]["raw_rectangular"]["end_to_end_correct_identity_recall"]
        for metrics in crop_metrics.values()
        for partition in ("validation", "challenge")
    ]
    segmentation = (
        "justified"
        if max(oracle_values, default=0.0) > max(raw_values, default=0.0) + 1e-12
        else "not_justified_by_this_comparison"
    )
    report = {
        "schema_version": VISIBLE_CARD_COMPARISON_SCHEMA,
        "freeze_id": freeze["freeze_id"],
        "freeze_digest": freeze["freeze_digest"],
        "recipe_identity": recipes["gemini-pseudo-label"],
        "score_threshold": config.score_threshold,
        "match_iou_threshold": config.match_iou_threshold,
        "iou_thresholds": list(VISIBLE_CARD_COMPARISON_IOU_THRESHOLDS),
        "candidates": {
            candidate_id: {
                "label_source": candidate["label_source"],
                "candidate_path": candidate["candidate_path"],
                "candidate_sha256": candidate["candidate_sha256"],
                "run_path": candidate["run_path"],
                "run_sha256": candidate["run_sha256"],
                "dataset_digest": candidate["run"]["dataset"]["dataset_digest"],
                "split_digest": candidate["run"]["dataset"]["split_digest"],
                "recipe_digest": candidate["run"]["recipe"].get("recipe_digest"),
                "result_paths": candidate["result_paths"],
                "metrics": detector_metrics[candidate_id],
            }
            for candidate_id, candidate in candidates.items()
        },
        "paired_predictions": _paired_predictions(freeze, candidates, config.score_threshold),
        "crop_evaluation": {
            "path": crop["path"],
            "sha256": crop["sha256"],
            "partitions": crop["partitions"],
            "classifier_bundle_sha256": crop["classifier_bundle_sha256"],
            "metrics": crop_metrics,
        },
        "conclusion": {
            "localization": {
                "direction": localization_direction,
                "validation_box_ap_delta": ap_delta,
                "validation_instance_recall_delta": recall_delta,
            },
            "crop_policy_end_to_end_identity": crop_direction,
            "crop_policy_effect": crop_policy_effect,
            "segmentation_experiment": segmentation,
        },
        "stratification_note": (
            "This freeze provides source-lineage group, side, visible-card count, and "
            "failure-tag strata. Session and table-setup fields are not present in the M2 "
            "freeze and are not inferred here."
        ),
        "selection_note": (
            "This is a paired data-quality comparison. It does not select a model, change "
            "thresholds, run a campaign, lock a candidate, or promote a bundle. Load and "
            "inference latency are descriptive."
        ),
    }
    if config.output.exists():
        raise VisibleCardComparisonError(f"comparison output already exists: {config.output}")
    config.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.output.with_name(f".{config.output.name}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(config.output)
    return report


__all__ = [
    "FROZEN_RECIPE_FIELDS",
    "VISIBLE_CARD_COMPARISON_CANDIDATE_SCHEMA",
    "VISIBLE_CARD_COMPARISON_CANDIDATES",
    "VISIBLE_CARD_COMPARISON_IOU_THRESHOLDS",
    "VISIBLE_CARD_COMPARISON_POLICIES",
    "VISIBLE_CARD_COMPARISON_SCHEMA",
    "VISIBLE_CARD_CROP_EVALUATION_SCHEMA",
    "VisibleCardComparisonConfig",
    "VisibleCardComparisonError",
    "compare_visible_card_detectors",
]
