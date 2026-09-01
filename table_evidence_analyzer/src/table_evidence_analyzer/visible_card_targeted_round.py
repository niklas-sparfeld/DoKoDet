"""Bounded M4 targeted-data round contracts.

This module joins one measured M3 failure tag, a completed review queue from unused source groups,
and one augmented detector run. It evaluates the augmented run on the unchanged M2 validation and
challenge frames. It does not choose a model, run a campaign, or promote a bundle.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .visible_card_comparison import (
    FROZEN_RECIPE_FIELDS,
    VISIBLE_CARD_COMPARISON_SCHEMA,
    _detector_metrics,
    _digest_string,
    _expected_frames,
    _file_digest,
    _identifier,
    _load_candidate,
    _paired_predictions,
    _read_json,
    _recipe_identity,
    _source_key,
)
from .visible_card_review import VISIBLE_CARD_FAILURE_TAGS
from .visible_card_review_freeze import load_frozen_visible_card_review_data
from .visible_card_review_workflow import (
    VisibleCardReviewItem,
    load_visible_card_review_queue,
    validate_completed_visible_card_review_queue,
)
from .visible_card_training import VISIBLE_CARD_BUNDLE_SCHEMA, VISIBLE_CARD_TRAINING_RUN_SCHEMA
from .visible_cards import load_run_artifact

VISIBLE_CARD_TARGETED_BATCH_SCHEMA = "visible-card-targeted-review-batch/v1"
VISIBLE_CARD_TARGETED_CANDIDATE_SCHEMA = "visible-card-targeted-candidate/v1"
VISIBLE_CARD_TARGETED_ROUND_SCHEMA = "visible-card-targeted-round/v1"
VISIBLE_CARD_TARGETED_FAILURE_CATEGORIES = tuple(sorted(VISIBLE_CARD_FAILURE_TAGS))
MAX_TARGETED_BATCH_FRAMES = 40


class VisibleCardTargetedRoundError(ValueError):
    """Raised when an M4 targeted-data round cannot be trusted."""


@dataclass(frozen=True, slots=True)
class VisibleCardTargetedRoundConfig:
    """Inputs for one immutable, bounded M4 evaluation."""

    freeze: Path
    m3_report: Path
    batch: Path
    targeted_candidate: Path
    output: Path


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisibleCardTargetedRoundError(f"{field} must be a non-empty string")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VisibleCardTargetedRoundError(f"{field} must be a positive integer")
    return value


def _read_digest_descriptor(value: Any, field: str) -> tuple[Path, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise VisibleCardTargetedRoundError(f"{field} must contain path and sha256")
    path = Path(_text(value["path"], f"{field}.path")).expanduser().resolve()
    digest = _digest_string(value["sha256"], f"{field}.sha256")
    if digest != _file_digest(path):
        raise VisibleCardTargetedRoundError(f"{field} digest does not match: {path}")
    return path, digest


def _reviewed_card_tags(item: VisibleCardReviewItem) -> set[str]:
    tags = set(item.review.failure_tags)
    for action in item.review.actions:
        if action.reviewed_card is not None:
            tags.update(action.reviewed_card.failure_tags)
    return tags


def _load_m3_report(path: Path, freeze: dict[str, Any]) -> dict[str, Any]:
    report = _read_json(path, "M3 visible-card comparison report")
    if report.get("schema_version") != VISIBLE_CARD_COMPARISON_SCHEMA:
        raise VisibleCardTargetedRoundError("M4 requires a visible-card-comparison/v1 report")
    if (
        report.get("freeze_id") != freeze["freeze_id"]
        or report.get("freeze_digest") != freeze["freeze_digest"]
    ):
        raise VisibleCardTargetedRoundError("M3 report does not use the frozen review")
    candidates = report.get("candidates")
    if not isinstance(candidates, dict) or set(candidates) != {
        "gemini-pseudo-label",
        "reviewed-box",
    }:
        raise VisibleCardTargetedRoundError("M3 report must contain both detector candidates")
    recipe = report.get("recipe_identity")
    if not isinstance(recipe, dict) or set(recipe) != set(FROZEN_RECIPE_FIELDS):
        raise VisibleCardTargetedRoundError("M3 report lacks the frozen recipe identity")
    score_threshold = report.get("score_threshold")
    match_iou_threshold = report.get("match_iou_threshold")
    if not isinstance(score_threshold, (int, float)) or not isinstance(
        match_iou_threshold, (int, float)
    ):
        raise VisibleCardTargetedRoundError("M3 report lacks fixed evaluation thresholds")
    reviewed = candidates["reviewed-box"]
    if not isinstance(reviewed, dict):
        raise VisibleCardTargetedRoundError("M3 reviewed-box candidate is missing")
    candidate_path, candidate_digest = _read_digest_descriptor(
        {
            "path": reviewed.get("candidate_path"),
            "sha256": reviewed.get("candidate_sha256"),
        },
        "M3 reviewed-box candidate",
    )
    loaded = _load_candidate(candidate_path, freeze)
    if loaded["candidate_sha256"] != candidate_digest:
        raise VisibleCardTargetedRoundError("M3 reviewed-box candidate digest is stale")
    expected_metrics = _detector_metrics(
        freeze,
        loaded,
        score_threshold=float(score_threshold),
        iou_threshold=float(match_iou_threshold),
    )
    if reviewed.get("metrics") != expected_metrics:
        raise VisibleCardTargetedRoundError("M3 reviewed-box metrics do not match its artifacts")
    paired = report.get("paired_predictions")
    expected_eval_ids = {
        frame_id
        for frame_id, frame in _expected_frames(freeze).items()
        if frame["partition"] in {"validation", "challenge"}
    }
    if (
        not isinstance(paired, list)
        or {row.get("frame_id") for row in paired if isinstance(row, dict)} != expected_eval_ids
    ):
        raise VisibleCardTargetedRoundError(
            "M3 paired predictions do not cover the frozen evaluation"
        )
    if any(
        not isinstance(row, dict) or row.get("partition") not in {"validation", "challenge"}
        for row in paired
    ):
        raise VisibleCardTargetedRoundError("M3 report contains a non-evaluation partition")
    return {
        "report": report,
        "path": str(path.resolve()),
        "sha256": _file_digest(path),
        "reviewed_candidate": loaded,
        "recipe": recipe,
        "score_threshold": float(score_threshold),
        "match_iou_threshold": float(match_iou_threshold),
    }


def _measured_failure(report: dict[str, Any], category: str) -> dict[str, Any]:
    if category not in VISIBLE_CARD_TARGETED_FAILURE_CATEGORIES:
        raise VisibleCardTargetedRoundError(
            f"failure_category must be one of {VISIBLE_CARD_TARGETED_FAILURE_CATEGORIES}"
        )
    metrics = report["report"]["candidates"]["reviewed-box"]["metrics"]
    measured: dict[str, Any] = {}
    for partition in ("validation", "challenge"):
        row = metrics[partition]["by_failure_tag"].get(category)
        if isinstance(row, dict) and row.get("reference_card_count", 0) > 0:
            measured[partition] = row
    if not measured:
        raise VisibleCardTargetedRoundError(
            f"M3 did not measure failure category '{category}' on validation or challenge"
        )
    return measured


def _load_batch(path: Path, freeze: dict[str, Any], m3: dict[str, Any]) -> dict[str, Any]:
    value = _read_json(path, "targeted review batch")
    required = {
        "schema_version",
        "batch_id",
        "freeze_id",
        "freeze_digest",
        "selection",
        "review_queue",
        "item_ids",
        "system_holdout_groups",
    }
    if set(value) != required or value["schema_version"] != VISIBLE_CARD_TARGETED_BATCH_SCHEMA:
        raise VisibleCardTargetedRoundError("targeted review batch has an invalid schema")
    if (
        value["freeze_id"] != freeze["freeze_id"]
        or value["freeze_digest"] != freeze["freeze_digest"]
    ):
        raise VisibleCardTargetedRoundError("targeted review batch does not use the frozen review")
    batch_id = _identifier(value["batch_id"], "batch_id")
    selection = value["selection"]
    if not isinstance(selection, dict) or set(selection) != {
        "failure_category",
        "item_budget",
        "reason",
        "m3_report_path",
        "m3_report_sha256",
    }:
        raise VisibleCardTargetedRoundError("targeted batch selection is incomplete")
    category = _identifier(selection["failure_category"], "selection.failure_category")
    measured = _measured_failure(m3, category)
    budget = _positive_int(selection["item_budget"], "selection.item_budget")
    if budget > MAX_TARGETED_BATCH_FRAMES:
        raise VisibleCardTargetedRoundError(
            f"selection.item_budget must be at most {MAX_TARGETED_BATCH_FRAMES} frames"
        )
    report_path = (
        Path(_text(selection["m3_report_path"], "selection.m3_report_path")).expanduser().resolve()
    )
    if report_path != Path(m3["path"]):
        raise VisibleCardTargetedRoundError("selection does not name the supplied M3 report")
    if selection["m3_report_sha256"] != m3["sha256"]:
        raise VisibleCardTargetedRoundError("selection M3 report digest does not match")
    _text(selection["reason"], "selection.reason")
    holdout = value["system_holdout_groups"]
    if not isinstance(holdout, list) or any(
        not isinstance(group, str) or not group for group in holdout
    ):
        raise VisibleCardTargetedRoundError("system_holdout_groups must be a list of names")
    expected_holdout = freeze["partition_manifest"]["system_holdout_groups"]
    if sorted(holdout) != sorted(expected_holdout):
        raise VisibleCardTargetedRoundError(
            "targeted batch holdout declaration differs from freeze"
        )
    queue_path, queue_digest = _read_digest_descriptor(value["review_queue"], "review_queue")
    queue = validate_completed_visible_card_review_queue(load_visible_card_review_queue(queue_path))
    item_ids = value["item_ids"]
    if not isinstance(item_ids, list) or not item_ids:
        raise VisibleCardTargetedRoundError("targeted batch must contain item IDs")
    if len(item_ids) > budget or len(item_ids) > MAX_TARGETED_BATCH_FRAMES:
        raise VisibleCardTargetedRoundError("targeted review batch exceeds its fixed item budget")
    if any(not isinstance(item_id, str) for item_id in item_ids) or len(item_ids) != len(
        set(item_ids)
    ):
        raise VisibleCardTargetedRoundError("targeted batch item IDs must be unique strings")
    items_by_id = {item.item_id: item for item in queue.items}
    if set(item_ids) != set(items_by_id):
        raise VisibleCardTargetedRoundError("targeted batch item IDs must cover its review queue")
    expected_frames = _expected_frames(freeze)
    frozen_ids = set(expected_frames)
    frozen_groups = {frame["source"]["source_lineage_group"] for frame in expected_frames.values()}
    batch_items = [items_by_id[item_id] for item_id in sorted(item_ids)]
    for item in batch_items:
        if item.item_id in frozen_ids:
            raise VisibleCardTargetedRoundError(
                f"targeted item is already in the freeze: {item.item_id}"
            )
        if item.source.source_lineage_group in frozen_groups:
            raise VisibleCardTargetedRoundError(
                "targeted review batch must prefer unused source groups: "
                f"{item.source.source_lineage_group}"
            )
        if item.source.source_lineage_group in holdout:
            raise VisibleCardTargetedRoundError("targeted batch contains a system-holdout group")
        if category not in _reviewed_card_tags(item):
            raise VisibleCardTargetedRoundError(
                f"targeted item does not contain the selected failure category: {item.item_id}"
            )
        source_path = Path(item.source.image).expanduser().resolve()
        if not source_path.is_file() or _file_digest(source_path) != item.source.frame_sha256:
            raise VisibleCardTargetedRoundError(
                f"targeted source frame is missing or stale: {item.item_id}"
            )
    return {
        "batch_id": batch_id,
        "path": str(path.resolve()),
        "sha256": _file_digest(path),
        "queue_path": str(queue_path),
        "queue_sha256": queue_digest,
        "item_ids": [item.item_id for item in batch_items],
        "items": batch_items,
        "selection": {
            "failure_category": category,
            "item_budget": budget,
            "reason": selection["reason"],
            "m3_report_path": str(report_path),
            "m3_report_sha256": m3["sha256"],
            "measured_metrics": measured,
        },
    }


def _result_map(
    paths: Any,
    partition: str,
    freeze: dict[str, Any],
    bundle: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    expected = {
        frame_id: frame
        for frame_id, frame in _expected_frames(freeze).items()
        if frame["partition"] == partition
    }
    if not isinstance(paths, list) or not paths:
        raise VisibleCardTargetedRoundError(
            f"targeted {partition} results must be a non-empty list"
        )
    result_map: dict[str, dict[str, Any]] = {}
    descriptors: list[dict[str, str]] = []
    for raw_path in paths:
        result_path = (
            Path(_text(raw_path, f"targeted {partition} result path")).expanduser().resolve()
        )
        result = load_run_artifact(result_path)
        request = result["request"]
        if request["provider"] != "local":
            raise VisibleCardTargetedRoundError(f"targeted result is not local: {result_path}")
        raw = result.get("raw_response")
        identity = raw.get("bundle_identity") if isinstance(raw, dict) else None
        if (
            not isinstance(identity, dict)
            or identity.get("schema_version") != VISIBLE_CARD_BUNDLE_SCHEMA
            or identity.get("bundle_digest") != bundle["bundle_digest"]
            or identity.get("checkpoint_sha256") != bundle["checkpoint_sha256"]
        ):
            raise VisibleCardTargetedRoundError(
                f"targeted result bundle identity is stale: {result_path}"
            )
        key = (
            request["package_id"],
            request["frame_part_name"],
            request["target_offset_ms"],
            request["image_sha256"],
        )
        matching = [frame_id for frame_id, frame in expected.items() if _source_key(frame) == key]
        if len(matching) != 1:
            raise VisibleCardTargetedRoundError(
                f"targeted result does not match one frozen {partition} frame: {result_path}"
            )
        frame_id = matching[0]
        if frame_id in result_map:
            raise VisibleCardTargetedRoundError(f"duplicate targeted result for {frame_id}")
        result_map[frame_id] = result
        descriptors.append({"path": str(result_path), "sha256": _file_digest(result_path)})
    if set(result_map) != set(expected):
        missing = sorted(set(expected) - set(result_map))
        raise VisibleCardTargetedRoundError(f"targeted results miss frozen frame: {missing[0]}")
    return result_map, sorted(descriptors, key=lambda row: row["path"])


def _load_targeted_candidate(
    path: Path,
    freeze: dict[str, Any],
    batch: dict[str, Any],
    m3: dict[str, Any],
) -> dict[str, Any]:
    value = _read_json(path, "targeted candidate")
    required = {
        "schema_version",
        "round_id",
        "batch_id",
        "freeze_id",
        "freeze_digest",
        "run",
        "results",
    }
    if set(value) != required or value["schema_version"] != VISIBLE_CARD_TARGETED_CANDIDATE_SCHEMA:
        raise VisibleCardTargetedRoundError("targeted candidate has an invalid schema")
    if value["batch_id"] != batch["batch_id"]:
        raise VisibleCardTargetedRoundError("targeted candidate does not use the selected batch")
    if (
        value["freeze_id"] != freeze["freeze_id"]
        or value["freeze_digest"] != freeze["freeze_digest"]
    ):
        raise VisibleCardTargetedRoundError("targeted candidate does not use the frozen review")
    round_id = _identifier(value["round_id"], "round_id")
    run_path, run_digest = _read_digest_descriptor(value["run"], "targeted run")
    run = _read_json(run_path, "targeted training run")
    if (
        run.get("schema_version") != VISIBLE_CARD_TRAINING_RUN_SCHEMA
        or run.get("status") != "completed"
    ):
        raise VisibleCardTargetedRoundError("targeted run must be a completed visible-card run")
    dataset = run.get("dataset")
    recipe = run.get("recipe")
    bundle = run.get("bundle")
    if (
        not isinstance(dataset, dict)
        or not isinstance(recipe, dict)
        or not isinstance(bundle, dict)
    ):
        raise VisibleCardTargetedRoundError(
            "targeted run lacks dataset, recipe, or bundle identity"
        )
    if any(field not in recipe for field in FROZEN_RECIPE_FIELDS):
        raise VisibleCardTargetedRoundError("targeted run recipe lacks frozen fields")
    if _recipe_identity(recipe) != m3["recipe"]:
        raise VisibleCardTargetedRoundError("targeted run changed the frozen recipe")
    baseline_dataset = m3["reviewed_candidate"]["run"]["dataset"]
    dataset_digest = _digest_string(dataset.get("dataset_digest"), "targeted dataset_digest")
    split_digest = _digest_string(dataset.get("split_digest"), "targeted split_digest")
    recipe_digest = _digest_string(recipe.get("recipe_digest"), "targeted recipe_digest")
    if recipe_digest != _digest(
        {key: value for key, value in recipe.items() if key != "recipe_digest"}
    ):
        raise VisibleCardTargetedRoundError("targeted run recipe digest is stale")
    if split_digest != baseline_dataset.get("split_digest"):
        raise VisibleCardTargetedRoundError("targeted run changed the frozen evaluation split")
    if dataset_digest == baseline_dataset.get("dataset_digest"):
        raise VisibleCardTargetedRoundError("targeted run does not record an augmented dataset")
    bundle_digest = _digest_string(bundle.get("bundle_digest"), "targeted run.bundle.bundle_digest")
    checkpoint_digest = _digest_string(
        bundle.get("checkpoint_sha256"), "targeted run.bundle.checkpoint_sha256"
    )
    expected_sources = {
        frame_id: frame["source"]["frame_sha256"]
        for frame_id, frame in _expected_frames(freeze).items()
        if frame["partition"] in {"train", "validation"}
    }
    expected_sources.update({item.item_id: item.source.frame_sha256 for item in batch["items"]})
    source_rows = dataset.get("source_frame_digests")
    if not isinstance(source_rows, list):
        raise VisibleCardTargetedRoundError("targeted run lacks source frame digests")
    actual_sources: dict[str, str] = {}
    for row in source_rows:
        if not isinstance(row, dict) or set(row) != {"frame_id", "sha256"}:
            raise VisibleCardTargetedRoundError("targeted source frame digest is invalid")
        frame_id = _identifier(row["frame_id"], "targeted source frame_id")
        if frame_id in actual_sources:
            raise VisibleCardTargetedRoundError("targeted source frame IDs are not unique")
        actual_sources[frame_id] = _digest_string(row["sha256"], "targeted source sha256")
    if actual_sources != expected_sources:
        raise VisibleCardTargetedRoundError(
            "targeted run must contain the frozen train/validation frames plus the batch"
        )
    results = value["results"]
    if not isinstance(results, dict) or set(results) != {"validation", "challenge"}:
        raise VisibleCardTargetedRoundError("targeted candidate results are incomplete")
    result_maps: dict[str, dict[str, dict[str, Any]]] = {}
    result_paths: dict[str, list[dict[str, str]]] = {}
    for partition in ("validation", "challenge"):
        result_maps[partition], result_paths[partition] = _result_map(
            results[partition],
            partition,
            freeze,
            {"bundle_digest": bundle_digest, "checkpoint_sha256": checkpoint_digest},
        )
    return {
        "round_id": round_id,
        "path": str(path.resolve()),
        "sha256": _file_digest(path),
        "run_path": str(run_path),
        "run_sha256": run_digest,
        "run": run,
        "result_map": {**result_maps["validation"], **result_maps["challenge"]},
        "result_paths": result_paths,
    }


def _metric_deltas(baseline: dict[str, Any], targeted: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "box_ap_iou_0_50",
        "box_ap_iou_0_50_to_0_95",
        "instance_recall",
        "false_proposal_count",
        "false_proposals_per_frame",
        "duplicate_proposal_count",
        "duplicate_proposals_per_frame",
        "usable_crop_recall",
        "empty_frame_false_positive_rate",
        "latency_median_ms",
        "latency_p95_ms",
    )
    result: dict[str, Any] = {}
    for field in fields:
        before = baseline[field]
        after = targeted[field]
        result[field] = {"baseline": before, "targeted": after, "delta": after - before}
    return result


def evaluate_visible_card_targeted_round(
    config: VisibleCardTargetedRoundConfig,
) -> dict[str, Any]:
    """Validate and report one bounded M4 round on the frozen evaluation frames."""

    freeze = load_frozen_visible_card_review_data(config.freeze)
    m3 = _load_m3_report(config.m3_report.expanduser().resolve(), freeze)
    batch = _load_batch(config.batch.expanduser().resolve(), freeze, m3)
    targeted = _load_targeted_candidate(
        config.targeted_candidate.expanduser().resolve(), freeze, batch, m3
    )
    baseline = m3["reviewed_candidate"]
    baseline_metrics = _detector_metrics(
        freeze,
        baseline,
        score_threshold=m3["score_threshold"],
        iou_threshold=m3["match_iou_threshold"],
    )
    targeted_metrics = _detector_metrics(
        freeze,
        targeted,
        score_threshold=m3["score_threshold"],
        iou_threshold=m3["match_iou_threshold"],
    )
    metric_deltas = {
        partition: _metric_deltas(baseline_metrics[partition], targeted_metrics[partition])
        for partition in ("validation", "challenge")
    }
    eval_candidate = {"reviewed-box-targeted": targeted, "reviewed-box-baseline": baseline}
    paired = _paired_predictions(freeze, eval_candidate, m3["score_threshold"])
    validation_delta = metric_deltas["validation"]
    ap_delta = validation_delta["box_ap_iou_0_50_to_0_95"]["delta"]
    recall_delta = validation_delta["instance_recall"]["delta"]
    if ap_delta > 1e-12 and recall_delta >= -1e-12 or recall_delta > 1e-12 and ap_delta >= -1e-12:
        direction = "improves"
    elif ap_delta < -1e-12 and recall_delta <= 1e-12 or recall_delta < -1e-12 and ap_delta <= 1e-12:
        direction = "harms"
    else:
        direction = "does_not_clearly_change"
    expected_frames = _expected_frames(freeze)
    report = {
        "schema_version": VISIBLE_CARD_TARGETED_ROUND_SCHEMA,
        "freeze_id": freeze["freeze_id"],
        "freeze_digest": freeze["freeze_digest"],
        "m3_report": {"path": m3["path"], "sha256": m3["sha256"]},
        "batch": {
            "path": batch["path"],
            "sha256": batch["sha256"],
            "batch_id": batch["batch_id"],
            "queue_path": batch["queue_path"],
            "queue_sha256": batch["queue_sha256"],
            "item_ids": batch["item_ids"],
            "source_lineage_groups": sorted(
                {item.source.source_lineage_group for item in batch["items"]}
            ),
            "selection": batch["selection"],
        },
        "targeted_candidate": {
            "path": targeted["path"],
            "sha256": targeted["sha256"],
            "round_id": targeted["round_id"],
            "run_path": targeted["run_path"],
            "run_sha256": targeted["run_sha256"],
            "dataset_digest": targeted["run"]["dataset"]["dataset_digest"],
            "split_digest": targeted["run"]["dataset"]["split_digest"],
            "result_paths": targeted["result_paths"],
        },
        "evaluation": {
            "score_threshold": m3["score_threshold"],
            "match_iou_threshold": m3["match_iou_threshold"],
            "unchanged_freeze": True,
            "frame_counts": {
                partition: sum(
                    frame["partition"] == partition for frame in expected_frames.values()
                )
                for partition in ("validation", "challenge")
            },
        },
        "metrics": {
            "baseline_reviewed_box": baseline_metrics,
            "targeted_reviewed_box": targeted_metrics,
            "delta_targeted_minus_baseline": metric_deltas,
        },
        "paired_predictions": paired,
        "conclusion": {
            "localization": {
                "validation_direction": direction,
                "validation_box_ap_delta": ap_delta,
                "validation_instance_recall_delta": recall_delta,
            },
            "targeted_data_effect": (
                "The selected failure category was measured by M3 and the augmented run was "
                "evaluated on unchanged validation and challenge frames."
            ),
            "next_step": (
                "Any further data addition must be a new bounded recipe with a new measured "
                "failure selection; this report does not start an open-ended loop."
            ),
        },
        "selection_note": (
            "This is a bounded data-effect report. It does not select, lock, or promote a model, "
            "change thresholds, run a model campaign, or use test or system-holdout results."
        ),
    }
    output = config.output.expanduser().resolve()
    if output.exists():
        raise VisibleCardTargetedRoundError(f"targeted round output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    return report


__all__ = [
    "MAX_TARGETED_BATCH_FRAMES",
    "VISIBLE_CARD_TARGETED_BATCH_SCHEMA",
    "VISIBLE_CARD_TARGETED_CANDIDATE_SCHEMA",
    "VISIBLE_CARD_TARGETED_FAILURE_CATEGORIES",
    "VISIBLE_CARD_TARGETED_ROUND_SCHEMA",
    "VisibleCardTargetedRoundConfig",
    "VisibleCardTargetedRoundError",
    "evaluate_visible_card_targeted_round",
]
