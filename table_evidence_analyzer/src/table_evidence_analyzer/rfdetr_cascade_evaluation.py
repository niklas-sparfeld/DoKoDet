"""Source-linked validation and decision reporting for the M6 cascade."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .visible_card_cascade import PixelBox
from .visible_cards import ProviderResult, VisibleCardRequest

RFDETR_CASCADE_EVALUATION_SCHEMA = "rfdetr-cascade-validation/v1"
RFDETR_CASCADE_DECISION_SCHEMA = "rfdetr-cascade-decision/v1"


class RfdetrCascadeEvaluationError(ValueError):
    """The source-linked cascade validation cannot produce a trusted report."""


@dataclass(frozen=True, slots=True)
class RfdetrCascadeValidationCase:
    """One exact source frame and its reviewed visible-card boxes."""

    request: VisibleCardRequest
    target_boxes: tuple[PixelBox, ...]
    target_ids: tuple[str, ...] = ()
    source_group: str = "fixture"

    def __post_init__(self) -> None:
        if self.target_ids and len(self.target_ids) != len(self.target_boxes):
            raise RfdetrCascadeEvaluationError("target_ids must match target_boxes")
        if not self.source_group:
            raise RfdetrCascadeEvaluationError("source_group must not be empty")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical(value) + b"\n")
    temporary.replace(path)


def _box(value: Any) -> PixelBox:
    if not isinstance(value, dict):
        raise RfdetrCascadeEvaluationError("reported box must be an object")
    try:
        return PixelBox(
            float(value["x_min"]),
            float(value["y_min"]),
            float(value["x_max"]),
            float(value["y_max"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RfdetrCascadeEvaluationError("reported box is malformed") from error


def _iou(left: PixelBox, right: PixelBox) -> float:
    intersection = left.intersection(right)
    if intersection is None:
        return 0.0
    intersection_area = intersection.width * intersection.height
    union_area = left.width * left.height + right.width * right.height - intersection_area
    return intersection_area / union_area if union_area else 0.0


def _contains(outer: PixelBox, inner: PixelBox) -> bool:
    return outer.contains(inner)


def _matches(
    targets: Sequence[PixelBox], predictions: Sequence[PixelBox]
) -> list[tuple[int, int, float]]:
    candidates = sorted(
        (
            _iou(target, prediction),
            target_index,
            prediction_index,
        )
        for target_index, target in enumerate(targets)
        for prediction_index, prediction in enumerate(predictions)
        if _iou(target, prediction) >= 0.5
    )
    matches: list[tuple[int, int, float]] = []
    used_targets: set[int] = set()
    used_predictions: set[int] = set()
    for score, target_index, prediction_index in reversed(candidates):
        if target_index in used_targets or prediction_index in used_predictions:
            continue
        used_targets.add(target_index)
        used_predictions.add(prediction_index)
        matches.append((target_index, prediction_index, score))
    return sorted(matches)


def _coarse_metrics(case: RfdetrCascadeValidationCase, raw: dict[str, Any]) -> dict[str, Any]:
    coarse = raw.get("coarse") if isinstance(raw.get("coarse"), dict) else {}
    layout = coarse.get("layout") if isinstance(coarse.get("layout"), dict) else {}
    clusters = layout.get("clusters") if isinstance(layout.get("clusters"), list) else []
    crop_boxes = [
        _box(cluster["padded_square_box"])
        for cluster in clusters
        if isinstance(cluster, dict) and isinstance(cluster.get("padded_square_box"), dict)
    ]
    misses = [
        index
        for index, target in enumerate(case.target_boxes)
        if not any(_contains(crop_box, target) for crop_box in crop_boxes)
    ]
    detections = coarse.get("detections") if isinstance(coarse.get("detections"), list) else []
    return {
        "status": coarse.get("status", "unavailable"),
        "detection_count": len(detections),
        "cluster_count": len(clusters),
        "target_count": len(case.target_boxes),
        "missed_target_indexes": misses,
        "coarse_stage_miss_count": len(misses),
        "latency_ms": coarse.get("latency_ms"),
    }


def _fine_metrics(case: RfdetrCascadeValidationCase, raw: dict[str, Any]) -> dict[str, Any]:
    mapping = raw.get("mapping") if isinstance(raw.get("mapping"), dict) else {}
    predictions_raw = mapping.get("predictions")
    predictions_raw = predictions_raw if isinstance(predictions_raw, list) else []
    predictions = [
        _box(prediction["box"])
        for prediction in predictions_raw
        if isinstance(prediction, dict) and isinstance(prediction.get("box"), dict)
    ]
    matches = _matches(case.target_boxes, predictions)
    overlapping_pairs = [
        (left, right)
        for left_index, left in enumerate(case.target_boxes)
        for right in case.target_boxes[left_index + 1 :]
        if _iou(left, right) > 0
    ]
    separated_pairs = sum(
        any(
            left_target == left_index
            and right_target == right_index
            and left_prediction != right_prediction
            for left_target, left_prediction, _ in matches
            for right_target, right_prediction, _ in matches
        )
        for left_index, right_index in (
            (case.target_boxes.index(left), case.target_boxes.index(right))
            for left, right in overlapping_pairs
        )
    )
    reconciliation = raw.get("reconciliation")
    discarded = (
        reconciliation.get("discarded_prediction_ids", [])
        if isinstance(reconciliation, dict)
        else []
    )
    return {
        "prediction_count": len(predictions),
        "matched_target_count": len(matches),
        "false_prediction_count": max(0, len(predictions) - len(matches)),
        "missed_target_count": max(0, len(case.target_boxes) - len(matches)),
        "box_iou_mean": round(sum(score for _, _, score in matches) / len(matches), 6)
        if matches
        else 0.0,
        "overlapping_target_pairs": len(overlapping_pairs),
        "separated_overlapping_target_pairs": separated_pairs,
        "fine_stage_instance_separation_failures": len(overlapping_pairs) - separated_pairs,
        "discarded_duplicate_count": len(discarded),
        "clusters": len((raw.get("fine") or {}).get("clusters", []))
        if isinstance(raw.get("fine"), dict)
        else 0,
        "fine_latency_ms": (raw.get("fine") or {}).get("latency_ms")
        if isinstance(raw.get("fine"), dict)
        else None,
    }


def run_rfdetr_cascade_validation(
    provider: Any,
    cases: Sequence[RfdetrCascadeValidationCase],
    *,
    output: str | Path,
) -> dict[str, Any]:
    """Run exact source frames through the backend provider and write M6 diagnostics."""

    if not cases:
        raise RfdetrCascadeEvaluationError("M6 validation has no source frames")
    frame_reports: list[dict[str, Any]] = []
    total_started = time.monotonic()
    for case in cases:
        result: ProviderResult = provider.propose(case.request)
        raw = result.raw_response if isinstance(result.raw_response, dict) else {}
        coarse = _coarse_metrics(case, raw)
        fine = _fine_metrics(case, raw)
        frame_reports.append(
            {
                "source_group": case.source_group,
                "source_frame": {
                    "package_id": case.request.package_id,
                    "frame_part_name": case.request.frame_part_name,
                    "image_sha256": case.request.image_sha256,
                },
                "target_ids": list(case.target_ids)
                or [f"target-{index:04d}" for index in range(len(case.target_boxes))],
                "status": result.status,
                "coarse": coarse,
                "fine": fine,
                "total_latency_ms": result.latency_ms,
                "retained_prediction_ids": (
                    raw.get("reconciliation", {}).get("retained_prediction_ids", [])
                    if isinstance(raw.get("reconciliation"), dict)
                    else []
                ),
            }
        )
    coarse_misses = sum(frame["coarse"]["coarse_stage_miss_count"] for frame in frame_reports)
    fine_failures = sum(
        frame["fine"]["fine_stage_instance_separation_failures"] for frame in frame_reports
    )
    target_count = sum(len(frame["target_ids"]) for frame in frame_reports)
    matched_count = sum(frame["fine"]["matched_target_count"] for frame in frame_reports)
    report: dict[str, Any] = {
        "schema_version": RFDETR_CASCADE_DECISION_SCHEMA,
        "evaluation_schema_version": RFDETR_CASCADE_EVALUATION_SCHEMA,
        "status": "completed",
        "provider": getattr(provider, "name", None),
        "bundle_identity": getattr(provider, "bundle_identity", None),
        "frame_count": len(frame_reports),
        "metrics": {
            "coarse_stage": {
                "target_count": target_count,
                "coarse_stage_miss_count": coarse_misses,
                "coarse_stage_miss_rate": round(coarse_misses / target_count, 6)
                if target_count
                else 0.0,
            },
            "crop_diagnostics": {
                "cluster_count": sum(frame["coarse"]["cluster_count"] for frame in frame_reports),
                "fine_cluster_count": sum(frame["fine"]["clusters"] for frame in frame_reports),
                "duplicate_count": sum(
                    frame["fine"]["discarded_duplicate_count"] for frame in frame_reports
                ),
            },
            "fine_stage": {
                "instance_separation_failure_count": fine_failures,
                "mapped_prediction_count": sum(
                    frame["fine"]["prediction_count"] for frame in frame_reports
                ),
            },
            "mapped_visible_card": {
                "matched_target_count": matched_count,
                "target_count": target_count,
                "recall": round(matched_count / target_count, 6) if target_count else 0.0,
                "false_prediction_count": sum(
                    frame["fine"]["false_prediction_count"] for frame in frame_reports
                ),
            },
            "latency": {
                "provider_load_latency_ms": getattr(provider, "load_latency_ms", None),
                "mean_request_latency_ms": round(
                    sum(frame["total_latency_ms"] for frame in frame_reports) / len(frame_reports),
                    6,
                ),
                "wall_clock_validation_ms": round(
                    max(0.0, time.monotonic() - total_started) * 1000.0, 3
                ),
            },
        },
        "frames": frame_reports,
        "limits": {
            "background_only_precision_measured": False,
            "real_production_bundle_executed": bool(getattr(provider, "_cascade_bundle", None)),
            "note": (
                "This report separates coarse crop misses from fine instance-separation errors. "
                "It does not establish production readiness without untouched real recordings."
            ),
        },
    }
    report["report_digest"] = _digest(report)
    _write_json(Path(output), report)
    return report


__all__ = [
    "RFDETR_CASCADE_DECISION_SCHEMA",
    "RFDETR_CASCADE_EVALUATION_SCHEMA",
    "RfdetrCascadeEvaluationError",
    "RfdetrCascadeValidationCase",
    "run_rfdetr_cascade_validation",
]
