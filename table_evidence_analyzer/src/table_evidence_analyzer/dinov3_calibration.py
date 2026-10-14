"""Fit a scalar DINOv3 confidence calibration from an explicit, disjoint logit view."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .local_identity import VISUAL_IDENTITY_TARGETS

CALIBRATION_SCHEMA = "dinov3-confidence-calibration/v1"
CALIBRATION_VIEW_SCHEMA = "dinov3-calibration-view/v1"
SCORE_SCHEMA = "dinov3-visual-score/v1"
TEMPERATURE_BOUNDS = (0.05, 20.0)


class DinoV3CalibrationError(ValueError):
    """Raised when a calibration view is invalid or overlaps campaign data."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _nll(rows: Sequence[Mapping[str, Any]], temperature: float) -> float:
    losses = []
    for row in rows:
        logits = row["logits"]
        target = VISUAL_IDENTITY_TARGETS.index(row["target"])
        scaled = [float(value) / temperature for value in logits]
        maximum = max(scaled)
        log_partition = maximum + math.log(sum(math.exp(value - maximum) for value in scaled))
        losses.append(log_partition - scaled[target])
    return sum(losses) / len(losses)


def fit_temperature(rows: Sequence[Mapping[str, Any]]) -> tuple[float, float, float]:
    """Fit positive temperature by deterministic golden-section search in log space."""

    if not rows:
        raise DinoV3CalibrationError("calibration view has no rows")
    low, high = (math.log(value) for value in TEMPERATURE_BOUNDS)
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    left = high - ratio * (high - low)
    right = low + ratio * (high - low)
    for _ in range(160):
        if _nll(rows, math.exp(left)) <= _nll(rows, math.exp(right)):
            high, right = right, left
            left = high - ratio * (high - low)
        else:
            low, left = left, right
            right = low + ratio * (high - low)
    temperature = min(TEMPERATURE_BOUNDS[1], max(TEMPERATURE_BOUNDS[0], math.exp((low + high) / 2)))
    return temperature, _nll(rows, 1.0), _nll(rows, temperature)


def _probabilities(logits: Sequence[float], temperature: float) -> list[float]:
    scaled = [value / temperature for value in logits]
    maximum = max(scaled)
    exponentials = [math.exp(value - maximum) for value in scaled]
    total = sum(exponentials)
    return [value / total for value in exponentials]


def _confidence_report(
    rows: Sequence[Mapping[str, Any]], temperature: float, precision_target: float | None
) -> dict[str, Any]:
    scored = []
    for row in rows:
        probabilities = _probabilities(row["logits"], temperature)
        prediction = max(
            range(len(probabilities)), key=lambda index: (probabilities[index], -index)
        )
        confidence = probabilities[prediction]
        scored.append((confidence, VISUAL_IDENTITY_TARGETS[prediction] == row["target"]))
    bins = []
    for index in range(10):
        lower, upper = index / 10, (index + 1) / 10
        members = [
            (confidence, correct)
            for confidence, correct in scored
            if lower <= confidence < upper or (index == 9 and confidence == 1.0)
        ]
        bins.append(
            {
                "lower": lower,
                "upper": upper,
                "count": len(members),
                "mean_confidence": sum(score for score, _ in members) / len(members)
                if members
                else None,
                "accuracy": sum(correct for _, correct in members) / len(members)
                if members
                else None,
            }
        )
    thresholds = []
    for threshold in sorted({confidence for confidence, _ in scored}):
        selected = [(score, correct) for score, correct in scored if score >= threshold]
        thresholds.append(
            {
                "threshold": threshold,
                "selected_count": len(selected),
                "coverage": len(selected) / len(scored),
                "precision": sum(correct for _, correct in selected) / len(selected),
            }
        )
    eligible = [
        row
        for row in thresholds
        if precision_target is not None and row["precision"] >= precision_target
    ]
    selected_threshold = min(eligible, key=lambda row: row["threshold"]) if eligible else None
    return {
        "schema_version": SCORE_SCHEMA,
        "reliability_bins": bins,
        "precision_coverage": thresholds,
        "review_threshold_selection": {
            "precision_target": precision_target,
            "selected_threshold": selected_threshold,
            "applies_to": "human_review_routing_only",
            "candidates_preserved": True,
        },
    }


def _validate_view(
    path: Path, run: Mapping[str, Any], checkpoint_digest: str
) -> tuple[dict[str, Any], bytes]:
    try:
        raw_bytes = path.read_bytes()
        view = json.loads(raw_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DinoV3CalibrationError("calibration view is not readable JSON") from error
    if not isinstance(view, dict) or set(view) != {
        "schema_version",
        "view_id",
        "run_id",
        "source_checkpoint_sha256",
        "rows",
    }:
        raise DinoV3CalibrationError("calibration view has unexpected fields")
    if view["schema_version"] != CALIBRATION_VIEW_SCHEMA:
        raise DinoV3CalibrationError("calibration view schema is unsupported")
    if not isinstance(view["view_id"], str) or not view["view_id"].strip():
        raise DinoV3CalibrationError("calibration view ID is missing")
    if view["run_id"] != run.get("run_id"):
        raise DinoV3CalibrationError("calibration view belongs to a different DINOv3 run")
    if view["source_checkpoint_sha256"] != checkpoint_digest:
        raise DinoV3CalibrationError("calibration view belongs to a different model checkpoint")
    rows = view["rows"]
    if not isinstance(rows, list) or not rows:
        raise DinoV3CalibrationError("calibration view has no rows")
    sample_ids: set[str] = set()
    groups: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "sample_id",
            "source_lineage_group",
            "target",
            "logits",
        }:
            raise DinoV3CalibrationError("calibration row has unexpected fields")
        sample_id = row["sample_id"]
        group = row["source_lineage_group"]
        logits = row["logits"]
        if not isinstance(sample_id, str) or not sample_id.strip() or sample_id in sample_ids:
            raise DinoV3CalibrationError("calibration sample IDs must be non-empty and unique")
        if not isinstance(group, dict) or not group:
            raise DinoV3CalibrationError(f"calibration row {sample_id} has no source lineage group")
        if row["target"] not in VISUAL_IDENTITY_TARGETS:
            raise DinoV3CalibrationError(f"calibration row {sample_id} has an invalid target")
        if (
            not isinstance(logits, list)
            or len(logits) != len(VISUAL_IDENTITY_TARGETS)
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in logits
            )
        ):
            raise DinoV3CalibrationError(
                f"calibration row {sample_id} must contain 25 finite logits"
            )
        sample_ids.add(sample_id)
        groups.add(_digest(group))
    return {"view": view, "sample_ids": sample_ids, "groups": groups}, raw_bytes


def fit_dinov3_confidence_calibration(
    run_dir: str | Path,
    view_path: str | Path,
    output: str | Path,
    *,
    review_precision_target: float | None = None,
) -> Path:
    """Fit and retain calibration from an explicit view disjoint from all campaign groups."""

    run_root = Path(run_dir).expanduser().resolve()
    try:
        run = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DinoV3CalibrationError("DINOv3 run record is not readable") from error
    if not isinstance(run, dict) or run.get("status") != "completed":
        raise DinoV3CalibrationError("only a completed DINOv3 run can be calibrated")
    if review_precision_target is not None and (
        isinstance(review_precision_target, bool)
        or not isinstance(review_precision_target, (int, float))
        or not math.isfinite(review_precision_target)
        or not 0 <= review_precision_target <= 1
    ):
        raise DinoV3CalibrationError("review precision target must be in [0, 1]")
    checkpoints = run.get("checkpoints", {})
    checkpoint_name = checkpoints.get("best") if isinstance(checkpoints, dict) else None
    if not isinstance(checkpoint_name, str):
        raise DinoV3CalibrationError("DINOv3 run has no best checkpoint")
    checkpoint_path = run_root / checkpoint_name
    try:
        source_checkpoint_sha256 = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    except OSError as error:
        raise DinoV3CalibrationError("DINOv3 best checkpoint is not readable") from error
    validated, raw_bytes = _validate_view(
        Path(view_path).expanduser().resolve(), run, source_checkpoint_sha256
    )
    config = run.get("config", {})
    campaign_path = Path(config.get("campaign_manifest", "")).expanduser().resolve()
    try:
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DinoV3CalibrationError("frozen campaign manifest is not readable") from error
    if not isinstance(campaign, dict) or campaign.get("state") != "frozen":
        raise DinoV3CalibrationError("DINOv3 campaign is not frozen")
    split_path = Path(config.get("split", "")).expanduser().resolve()
    try:
        from .data import load_dataset_manifest, load_split_manifest

        dataset = load_dataset_manifest(Path(config.get("dataset", "")).expanduser().resolve())
        split = load_split_manifest(split_path)
    except (OSError, ValueError) as error:
        raise DinoV3CalibrationError("DINOv3 split manifest is not readable") from error
    used_ids = set((*split.train, *split.validation, *split.test))
    if validated["sample_ids"] & used_ids:
        raise DinoV3CalibrationError("calibration sample IDs overlap the frozen data split")
    dataset_groups = {_digest(dict(entry.group_keys)) for entry in dataset.entries}
    if validated["groups"] & dataset_groups:
        raise DinoV3CalibrationError("calibration source lineage overlaps the frozen campaign")
    rows = validated["view"]["rows"]
    temperature, nll_before, nll_after = fit_temperature(rows)
    result = {
        "schema_version": CALIBRATION_SCHEMA,
        "score_schema_version": SCORE_SCHEMA,
        "method": "scalar_temperature_scaling",
        "temperature": temperature,
        "temperature_bounds": list(TEMPERATURE_BOUNDS),
        "run_id": run["run_id"],
        "source_checkpoint_sha256": source_checkpoint_sha256,
        "view_id": validated["view"]["view_id"],
        "view_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "sample_ids_sha256": _digest(sorted(validated["sample_ids"])),
        "source_lineage_groups_sha256": _digest(sorted(validated["groups"])),
        "sample_count": len(rows),
        "nll_before": nll_before,
        "nll_after": nll_after,
        "confidence_report": _confidence_report(rows, temperature, review_precision_target),
    }
    destination = Path(output).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


__all__ = [
    "CALIBRATION_SCHEMA",
    "CALIBRATION_VIEW_SCHEMA",
    "DinoV3CalibrationError",
    "SCORE_SCHEMA",
    "fit_dinov3_confidence_calibration",
    "fit_temperature",
]
