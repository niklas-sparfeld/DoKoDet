"""Run and retain the epic 0051 paired resilience comparison.

The comparison consumes immutable, retained crop rows.  It does not select a crop policy or
change classifier configuration.  The M0 coverage gate is checked before any row is executed.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .resilience_baseline import CONDITION_IDS, canonical_json_bytes, sha256_json

RESILIENCE_COMPARISON_SCHEMA_VERSION = "visible-region-identity-resilience-comparison/v1"
RESILIENCE_COMPARISON_ROW_SCHEMA_VERSION = "visible-region-identity-resilience-row/v1"
OUTCOME_STATUSES = ("classified", "unusable", "failed")
INPUT_FAMILIES = ("actual_gemini", "synthetic_corruption", "reviewed_upper_bound")


class ResilienceComparisonError(ValueError):
    """Raised when a retained resilience comparison is invalid."""


class ResilienceComparisonBlocked(ResilienceComparisonError):
    """Raised when M0 coverage does not allow the paired comparison."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ResilienceComparisonError(f"{field} must be an object")
    return value


def _strict(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        detail = []
        if missing:
            detail.append(f"missing {', '.join(missing)}")
        if unknown:
            detail.append(f"unknown {', '.join(unknown)}")
        raise ResilienceComparisonError(f"{field} has invalid fields ({'; '.join(detail)})")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ResilienceComparisonError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-/"
        for character in result
    ):
        raise ResilienceComparisonError(f"{field} must be a safe identifier")
    return result


def _digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ResilienceComparisonError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _finite_number(value: Any, field: str, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResilienceComparisonError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ResilienceComparisonError(f"{field} must be a finite number")
    return result


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResilienceComparisonError(f"{field} must be a non-negative integer")
    return value


def _validate_outcome(raw: Any, field: str) -> dict[str, Any]:
    outcome = _mapping(raw, field)
    expected = {
        "status",
        "top1_identity",
        "candidate_count",
        "score",
        "score_calibrated",
        "high_confidence",
        "retry_count",
        "latency_ms",
        "token_count",
        "estimated_cost_usd",
        "error",
    }
    _strict(outcome, expected, field)
    status = outcome["status"]
    if status not in OUTCOME_STATUSES:
        raise ResilienceComparisonError(f"{field}.status is unsupported")
    identity = outcome["top1_identity"]
    if identity is not None:
        _text(identity, f"{field}.top1_identity")
    candidate_count = _non_negative_int(outcome["candidate_count"], f"{field}.candidate_count")
    if status == "classified" and (identity is None or candidate_count == 0):
        raise ResilienceComparisonError(f"{field} classified outcome needs a top-1 candidate")
    if status != "classified" and (identity is not None or candidate_count != 0):
        raise ResilienceComparisonError(f"{field} non-classified outcome cannot have candidates")
    score = _finite_number(outcome["score"], f"{field}.score", allow_none=True)
    if score is not None and not 0 <= score <= 1:
        raise ResilienceComparisonError(f"{field}.score must be between 0 and 1")
    if not isinstance(outcome["score_calibrated"], bool):
        raise ResilienceComparisonError(f"{field}.score_calibrated must be boolean")
    if not isinstance(outcome["high_confidence"], bool) and outcome["high_confidence"] is not None:
        raise ResilienceComparisonError(f"{field}.high_confidence must be boolean or null")
    if outcome["high_confidence"] is not None and not outcome["score_calibrated"]:
        raise ResilienceComparisonError(
            f"{field}.high_confidence cannot be set for an uncalibrated score"
        )
    if outcome["score_calibrated"] and score is None:
        raise ResilienceComparisonError(f"{field}.calibrated score is missing")
    error = outcome["error"]
    if error is not None:
        _text(error, f"{field}.error")
    return dict(outcome)


def _validate_row(raw: Any, index: int, expected_conditions: set[str]) -> dict[str, Any]:
    row = _mapping(raw, f"rows[{index}]")
    expected = {
        "schema_version",
        "sample_id",
        "partition",
        "source_lineage_group",
        "condition_id",
        "input_family",
        "deployable",
        "corruption",
        "reviewed_target_identity",
        "outcome",
        "lineage",
        "dimensions",
        "diagnostics",
    }
    _strict(row, expected, f"rows[{index}]")
    if row["schema_version"] != RESILIENCE_COMPARISON_ROW_SCHEMA_VERSION:
        raise ResilienceComparisonError(f"rows[{index}] has an unsupported schema")
    for field in ("sample_id", "source_lineage_group", "reviewed_target_identity"):
        _identifier(row[field], f"rows[{index}].{field}")
    if row["partition"] not in {"development", "validation"}:
        raise ResilienceComparisonError(f"rows[{index}].partition is unsupported")
    condition_id = _identifier(row["condition_id"], f"rows[{index}].condition_id")
    if condition_id not in expected_conditions:
        raise ResilienceComparisonError(f"rows[{index}].condition_id is not frozen")
    family = row["input_family"]
    if family not in INPUT_FAMILIES:
        raise ResilienceComparisonError(f"rows[{index}].input_family is unsupported")
    if not isinstance(row["deployable"], bool):
        raise ResilienceComparisonError(f"rows[{index}].deployable must be boolean")
    corruption = row["corruption"]
    if family == "synthetic_corruption":
        corruption_data = _mapping(corruption, f"rows[{index}].corruption")
        _strict(
            corruption_data,
            {"family", "severity", "seed", "source_geometry_sha256", "output_geometry_sha256"},
            f"rows[{index}].corruption",
        )
        _identifier(corruption_data["family"], f"rows[{index}].corruption.family")
        _finite_number(corruption_data["severity"], f"rows[{index}].corruption.severity")
        _non_negative_int(corruption_data["seed"], f"rows[{index}].corruption.seed")
        _digest(
            corruption_data["source_geometry_sha256"],
            f"rows[{index}].corruption.source_geometry_sha256",
        )
        _digest(
            corruption_data["output_geometry_sha256"],
            f"rows[{index}].corruption.output_geometry_sha256",
        )
    elif corruption is not None:
        raise ResilienceComparisonError(
            f"rows[{index}].corruption is only valid for synthetic corruptions"
        )
    if family == "reviewed_upper_bound" and row["deployable"]:
        raise ResilienceComparisonError(
            f"rows[{index}] reviewed upper bound must be non-deployable"
        )
    _validate_outcome(row["outcome"], f"rows[{index}].outcome")
    lineage = _mapping(row["lineage"], f"rows[{index}].lineage")
    for field in ("frame_identity_sha256", "reviewed_geometry_sha256", "crop_sha256"):
        _digest(lineage.get(field), f"rows[{index}].lineage.{field}")
    if not isinstance(lineage.get("crop_path"), str) or not lineage["crop_path"]:
        raise ResilienceComparisonError(f"rows[{index}].lineage.crop_path must be a path")
    dimensions = _mapping(row["dimensions"], f"rows[{index}].dimensions")
    _strict(
        dimensions,
        {"visible_card_count", "visible_area_fraction", "neighboring_overlap_fraction"},
        f"rows[{index}].dimensions",
    )
    _non_negative_int(
        dimensions["visible_card_count"], f"rows[{index}].dimensions.visible_card_count"
    )
    for field in ("visible_area_fraction", "neighboring_overlap_fraction"):
        value = _finite_number(dimensions[field], f"rows[{index}].dimensions.{field}")
        assert value is not None
        if not 0 <= value <= 1:
            raise ResilienceComparisonError(
                f"rows[{index}].dimensions.{field} must be between 0 and 1"
            )
    _mapping(row["diagnostics"], f"rows[{index}].diagnostics")
    return dict(row)


def _outcome_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = len(rows)
    classified = [row for row in rows if row["outcome"]["status"] == "classified"]
    unusable = [row for row in rows if row["outcome"]["status"] == "unusable"]
    failed = [row for row in rows if row["outcome"]["status"] == "failed"]
    correct = [
        row
        for row in classified
        if row["outcome"]["top1_identity"] == row["reviewed_target_identity"]
    ]
    calibrated = [
        row
        for row in classified
        if row["outcome"]["score_calibrated"] and row["outcome"]["high_confidence"]
    ]
    high_confidence_errors = [
        row
        for row in calibrated
        if row["outcome"]["top1_identity"] != row["reviewed_target_identity"]
    ]
    retries = sum(row["outcome"]["retry_count"] for row in rows)
    latency = sum(row["outcome"]["latency_ms"] for row in rows)
    tokens = sum(row["outcome"]["token_count"] for row in rows)
    cost = sum(row["outcome"]["estimated_cost_usd"] for row in rows)

    def ratio(numerator: int, denominator: int) -> float | None:
        return None if denominator == 0 else numerator / denominator

    return {
        "eligible_items": eligible,
        "classified_items": len(classified),
        "unusable_items": len(unusable),
        "failed_items": len(failed),
        "classified_top1_accuracy": ratio(len(correct), len(classified)),
        "classified_coverage": ratio(len(classified), eligible),
        "unusable_rate": ratio(len(unusable), eligible),
        "end_to_end_correct_identity_recall": ratio(len(correct), eligible),
        "high_confidence_error_rate_when_calibrated": ratio(
            len(high_confidence_errors), len(calibrated)
        ),
        "calibrated_high_confidence_items": len(calibrated),
        "operational_failure_rate": ratio(len(failed), eligible),
        "retry_count": retries,
        "latency_ms_total": latency,
        "latency_ms_mean": ratio(int(latency), eligible),
        "token_count": tokens,
        "estimated_cost_usd": cost,
    }


def _breakdown(rows: Sequence[Mapping[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if field == "corruption_family":
            corruption = row["corruption"]
            key = "none" if corruption is None else str(corruption["family"])
        elif field == "corruption_severity":
            corruption = row["corruption"]
            key = "none" if corruption is None else str(corruption["severity"])
        else:
            key = str(row[field] if field in row else row["dimensions"][field])
        grouped[key].append(row)
    return [{"value": key, "metrics": _outcome_metrics(grouped[key])} for key in sorted(grouped)]


def _pair_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    corruption = row["corruption"]
    if corruption is None:
        corruption_key = None
    else:
        corruption_key = (
            corruption["family"],
            corruption["severity"],
            corruption["seed"],
        )
    return row["sample_id"], corruption_key


def _paired_effects(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    raw: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    for row in rows:
        if row["condition_id"] == "raw_rectangular":
            key = _pair_key(row)
            if key in raw:
                raise ResilienceComparisonError(f"duplicate raw baseline row for {key[0]}")
            raw[key] = row
    effects: list[dict[str, Any]] = []
    for row in rows:
        if row["condition_id"] == "raw_rectangular":
            continue
        baseline = raw.get(_pair_key(row))
        if baseline is None:
            raise ResilienceComparisonError(
                f"condition {row['condition_id']} has no paired raw row for {row['sample_id']}"
            )
        baseline_correct = (
            baseline["outcome"]["status"] == "classified"
            and baseline["outcome"]["top1_identity"] == baseline["reviewed_target_identity"]
        )
        condition_correct = (
            row["outcome"]["status"] == "classified"
            and row["outcome"]["top1_identity"] == row["reviewed_target_identity"]
        )
        effects.append(
            {
                "sample_id": row["sample_id"],
                "condition_id": row["condition_id"],
                "input_family": row["input_family"],
                "corruption_family": (
                    None if row["corruption"] is None else row["corruption"]["family"]
                ),
                "baseline_status": baseline["outcome"]["status"],
                "condition_status": row["outcome"]["status"],
                "baseline_correct": baseline_correct,
                "condition_correct": condition_correct,
                "recovered": not baseline_correct and condition_correct,
                "harmed": baseline_correct and not condition_correct,
                "row_sha256": sha256_json(row),
            }
        )
    return effects


def _paired_effect_summary(effects: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for effect in effects:
        grouped[(effect["condition_id"], effect["input_family"])].append(effect)
    result = []
    for (condition_id, input_family), values in sorted(grouped.items()):
        baseline_correct = sum(int(value["baseline_correct"]) for value in values)
        baseline_incorrect = len(values) - baseline_correct
        recovered = sum(int(value["recovered"]) for value in values)
        harmed = sum(int(value["harmed"]) for value in values)
        result.append(
            {
                "condition_id": condition_id,
                "input_family": input_family,
                "paired_items": len(values),
                "recovered_identities": recovered,
                "harmed_identities": harmed,
                "recovery_rate": (
                    None if baseline_incorrect == 0 else recovered / baseline_incorrect
                ),
                "harm_rate": None if baseline_correct == 0 else harmed / baseline_correct,
            }
        )
    return result


def _validate_manifest_gate(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    data = _mapping(manifest, "resilience baseline manifest")
    if data.get("validation_classification_allowed") is not True:
        gaps = data.get("coverage_gaps", [])
        gap_text = "; ".join(str(gap) for gap in gaps) or "M0 validation coverage is not complete"
        raise ResilienceComparisonBlocked(f"M3 comparison is blocked by M0 coverage: {gap_text}")
    contract = _mapping(data.get("measurement_contract"), "measurement_contract")
    if contract.get("schema_version") is None:
        raise ResilienceComparisonError("measurement contract is missing")
    return data


def run_resilience_comparison(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    elapsed_wall_clock_seconds: float = 0,
) -> dict[str, Any]:
    """Validate retained M3 rows and calculate deterministic paired metrics."""

    data = _validate_manifest_gate(manifest)
    contract = _mapping(data["measurement_contract"], "measurement_contract")
    if data.get("measurement_contract_sha256") != sha256_json(contract):
        raise ResilienceComparisonError("measurement_contract_sha256 does not match its content")
    conditions = contract.get("conditions")
    if not isinstance(conditions, list):
        raise ResilienceComparisonError("measurement contract conditions are missing")
    condition_map = {
        condition.get("condition_id"): condition
        for condition in conditions
        if isinstance(condition, Mapping)
    }
    if set(condition_map) != set(CONDITION_IDS):
        raise ResilienceComparisonError("measurement contract conditions are incomplete")
    normalized = [_validate_row(row, index, set(condition_map)) for index, row in enumerate(rows)]
    normalized.sort(
        key=lambda row: (
            row["sample_id"],
            row["condition_id"],
            row["input_family"],
            "none" if row["corruption"] is None else row["corruption"]["family"],
            "none" if row["corruption"] is None else row["corruption"]["severity"],
        )
    )
    if not normalized:
        raise ResilienceComparisonError("M3 comparison needs retained paired rows")
    sample_ids = sorted({row["sample_id"] for row in normalized})
    for sample_id in sample_ids:
        sample_rows = [row for row in normalized if row["sample_id"] == sample_id]
        missing = set(condition_map) - {row["condition_id"] for row in sample_rows}
        if missing:
            raise ResilienceComparisonError(
                f"sample {sample_id} is missing frozen condition(s): {', '.join(sorted(missing))}"
            )
    source_groups = _mapping(data.get("partitions"), "partitions")
    development_groups = set(source_groups.get("development_source_lineage_groups", []))
    validation_groups = set(source_groups.get("validation_source_lineage_groups", []))
    holdout_groups = set(source_groups.get("system_holdout_excluded_groups", []))
    for row in normalized:
        group = row["source_lineage_group"]
        if group in holdout_groups:
            raise ResilienceComparisonError(f"row {row['sample_id']} is in the system holdout")
        expected_groups = (
            development_groups if row["partition"] == "development" else validation_groups
        )
        if expected_groups and group not in expected_groups:
            raise ResilienceComparisonError(
                f"row {row['sample_id']} has a source group outside its partition"
            )
        expected_deployable = bool(condition_map[row["condition_id"]].get("deployable"))
        if row["deployable"] != expected_deployable:
            raise ResilienceComparisonError(
                f"row {row['sample_id']} deployability disagrees with the frozen condition"
            )
    families = {row["input_family"] for row in normalized}
    if "actual_gemini" not in families or "synthetic_corruption" not in families:
        raise ResilienceComparisonError(
            "M3 rows must report actual Gemini regions and synthetic corruptions separately"
        )
    budget = _mapping(contract.get("budget"), "measurement_contract.budget")
    max_requests = budget.get("max_classifier_requests")
    if isinstance(max_requests, int) and len(normalized) > max_requests:
        raise ResilienceComparisonError("M0 classifier request budget was exceeded")
    elapsed = _finite_number(elapsed_wall_clock_seconds, "elapsed_wall_clock_seconds")
    max_seconds = budget.get("max_wall_clock_seconds")
    if isinstance(max_seconds, (int, float)) and elapsed is not None and elapsed > max_seconds:
        raise ResilienceComparisonError("M0 wall-clock budget was exceeded")
    total_cost = sum(row["outcome"]["estimated_cost_usd"] for row in normalized)
    max_cost = budget.get("max_estimated_cost_usd")
    if isinstance(max_cost, (int, float)) and total_cost > max_cost:
        raise ResilienceComparisonError("M0 estimated cost budget was exceeded")
    effects = _paired_effects(normalized)
    condition_effects: dict[str, dict[str, int]] = defaultdict(
        lambda: {"recovered": 0, "harmed": 0}
    )
    for effect in effects:
        condition_effects[effect["condition_id"]]["recovered"] += int(effect["recovered"])
        condition_effects[effect["condition_id"]]["harmed"] += int(effect["harmed"])
    for effect in effects:
        counts = condition_effects[effect["condition_id"]]
        effect["condition_recovered_count"] = counts["recovered"]
        effect["condition_harmed_count"] = counts["harmed"]
    core = {
        "schema_version": RESILIENCE_COMPARISON_SCHEMA_VERSION,
        "comparison_state": "complete",
        "measurement_contract_sha256": data.get("measurement_contract_sha256"),
        "classifier": dict(_mapping(contract.get("classifier"), "measurement_contract.classifier")),
        "condition_metadata": [
            {
                "condition_id": condition_id,
                "deployable": bool(condition_map[condition_id].get("deployable")),
                "upper_bound_only": not bool(condition_map[condition_id].get("deployable")),
            }
            for condition_id in CONDITION_IDS
        ],
        "tuning_allowed": False,
        "retained_row_count": len(normalized),
        "retained_sample_count": len(sample_ids),
        "elapsed_wall_clock_seconds": elapsed,
        "metrics": _outcome_metrics(normalized),
        "by_condition": _breakdown(normalized, "condition_id"),
        "by_input_family": _breakdown(normalized, "input_family"),
        "by_corruption_family": _breakdown(normalized, "corruption_family"),
        "by_corruption_severity": _breakdown(normalized, "corruption_severity"),
        "by_source_lineage_group": _breakdown(normalized, "source_lineage_group"),
        "by_visible_card_count": _breakdown(normalized, "visible_card_count"),
        "by_visible_area_fraction": _breakdown(normalized, "visible_area_fraction"),
        "by_neighboring_overlap_fraction": _breakdown(normalized, "neighboring_overlap_fraction"),
        "paired_effects": effects,
        "paired_effects_summary": _paired_effect_summary(effects),
        "rows": normalized,
    }
    core["comparison_sha256"] = sha256_json(core)
    return json.loads(canonical_json_bytes(core).decode("utf-8"))


def write_resilience_comparison(path: str | Path, comparison: Mapping[str, Any]) -> Path:
    """Write one comparison and item-level row artifacts for local UI inspection."""

    data = _mapping(comparison, "resilience comparison")
    if data.get("schema_version") != RESILIENCE_COMPARISON_SCHEMA_VERSION:
        raise ResilienceComparisonError("resilience comparison has an unsupported schema")
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ResilienceComparisonError("resilience comparison has no retained rows")
    destination = Path(path).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    row_directory = destination / "rows"
    row_directory.mkdir(parents=True, exist_ok=True)
    for row in rows:
        row_id = sha256_json(row)
        row_path = row_directory / f"{row_id}.json"
        row_bytes = canonical_json_bytes(row) + b"\n"
        if row_path.exists() and row_path.read_bytes() != row_bytes:
            raise ResilienceComparisonError(f"retained row artifact changed: {row_path}")
        if not row_path.exists():
            row_path.write_bytes(row_bytes)
    comparison_path = destination / "comparison.json"
    comparison_bytes = canonical_json_bytes(data) + b"\n"
    if comparison_path.exists() and comparison_path.read_bytes() != comparison_bytes:
        raise ResilienceComparisonError(f"comparison artifact changed: {comparison_path}")
    if not comparison_path.exists():
        comparison_path.write_bytes(comparison_bytes)
    return comparison_path


def render_resilience_comparison_human(comparison: Mapping[str, Any]) -> str:
    """Render the stable operator summary for one completed comparison."""

    data = _mapping(comparison, "resilience comparison")
    metrics = _mapping(data.get("metrics"), "resilience comparison.metrics")
    lines = [
        "Visible-region identity resilience comparison M3",
        f"rows: {data.get('retained_row_count')}",
        f"samples: {data.get('retained_sample_count')}",
        f"classified coverage: {metrics.get('classified_coverage')}",
        f"end-to-end recall: {metrics.get('end_to_end_correct_identity_recall')}",
        f"unusable rate: {metrics.get('unusable_rate')}",
        f"operational failure rate: {metrics.get('operational_failure_rate')}",
        "validation tuning: disabled",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "INPUT_FAMILIES",
    "OUTCOME_STATUSES",
    "RESILIENCE_COMPARISON_ROW_SCHEMA_VERSION",
    "RESILIENCE_COMPARISON_SCHEMA_VERSION",
    "ResilienceComparisonBlocked",
    "ResilienceComparisonError",
    "render_resilience_comparison_human",
    "run_resilience_comparison",
    "write_resilience_comparison",
]
