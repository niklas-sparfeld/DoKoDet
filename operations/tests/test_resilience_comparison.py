from __future__ import annotations

import json
from pathlib import Path

import pytest

from doko_operations.resilience_baseline import (
    CONDITION_IDS,
    default_measurement_contract,
    sha256_json,
)
from doko_operations.resilience_comparison import (
    RESILIENCE_COMPARISON_ROW_SCHEMA_VERSION,
    ResilienceComparisonBlocked,
    ResilienceComparisonError,
    run_resilience_comparison,
    write_resilience_comparison,
)


def _outcome(
    status: str,
    identity: str | None,
    *,
    retry_count: int = 0,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "top1_identity": identity,
        "candidate_count": 1 if identity is not None else 0,
        "score": 0.91 if identity is not None else None,
        "score_calibrated": False,
        "high_confidence": None,
        "retry_count": retry_count,
        "latency_ms": 12.5,
        "token_count": 100,
        "estimated_cost_usd": 0.01,
        "error": error,
    }


def _row(
    sample_id: str,
    condition_id: str,
    family: str,
    target: str,
    outcome: dict[str, object],
    *,
    corruption: dict[str, object] | None = None,
    deployable: bool | None = None,
) -> dict[str, object]:
    if deployable is None:
        deployable = condition_id not in {
            "reviewed_other_region_exclusion",
            "oracle_visible_region",
        }
    return {
        "schema_version": RESILIENCE_COMPARISON_ROW_SCHEMA_VERSION,
        "sample_id": sample_id,
        "partition": "development",
        "source_lineage_group": "group-01",
        "condition_id": condition_id,
        "input_family": family,
        "deployable": deployable,
        "corruption": corruption,
        "reviewed_target_identity": target,
        "outcome": outcome,
        "lineage": {
            "frame_identity_sha256": "a" * 64,
            "reviewed_geometry_sha256": "b" * 64,
            "crop_sha256": sha256_json({"sample_id": sample_id, "condition_id": condition_id}),
            "crop_path": f"crops/{sample_id}-{condition_id}.ppm",
        },
        "dimensions": {
            "visible_card_count": 3,
            "visible_area_fraction": 0.25,
            "neighboring_overlap_fraction": 0.10,
        },
        "diagnostics": {"cache_hit": False},
    }


def _ready_manifest() -> dict[str, object]:
    contract = default_measurement_contract()
    return {
        "validation_classification_allowed": True,
        "measurement_contract": contract,
        "measurement_contract_sha256": sha256_json(contract),
        "partitions": {
            "development_source_lineage_groups": ["group-01"],
            "validation_source_lineage_groups": [],
            "system_holdout_excluded_groups": [],
        },
    }


def _complete_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    corruption = {
        "family": "position_shift",
        "severity": 0.1,
        "seed": 5103,
        "source_geometry_sha256": "c" * 64,
        "output_geometry_sha256": "d" * 64,
    }
    for sample_id, family, target, raw_outcome in (
        ("sample-actual", "actual_gemini", "HEARTS_QUEEN", _outcome("classified", "SPADES_ACE")),
        (
            "sample-synthetic",
            "synthetic_corruption",
            "HEARTS_KING",
            _outcome("classified", "HEARTS_KING"),
        ),
    ):
        for condition_id in CONDITION_IDS:
            if condition_id == "raw_rectangular":
                outcome = raw_outcome
            elif sample_id == "sample-actual":
                outcome = (
                    _outcome("failed", None, error="classifier unavailable")
                    if condition_id == "generated_other_region_exclusion"
                    else _outcome("classified", target)
                )
            elif condition_id == "generated_other_region_exclusion":
                outcome = _outcome("unusable", None, error="no reliable identity")
            elif condition_id == "predicted_visible_region":
                outcome = _outcome("classified", "SPADES_ACE")
            else:
                outcome = _outcome("classified", target)
            rows.append(
                _row(
                    sample_id,
                    condition_id,
                    (
                        "reviewed_upper_bound"
                        if sample_id == "sample-actual"
                        and condition_id
                        in {"reviewed_other_region_exclusion", "oracle_visible_region"}
                        else family
                    ),
                    target,
                    outcome,
                    corruption=(
                        corruption
                        if family == "synthetic_corruption"
                        and not (
                            sample_id == "sample-actual"
                            and condition_id
                            in {"reviewed_other_region_exclusion", "oracle_visible_region"}
                        )
                        else None
                    ),
                )
            )
    return rows


def test_m3_refuses_to_classify_when_m0_coverage_is_blocked() -> None:
    manifest = _ready_manifest()
    manifest["validation_classification_allowed"] = False
    manifest["coverage_gaps"] = ["need paired completed maintained references"]

    with pytest.raises(
        ResilienceComparisonBlocked, match="M3 comparison is blocked by M0 coverage"
    ):
        run_resilience_comparison(manifest, [])


def test_m3_metrics_keep_unusable_and_failed_rows_in_recall_denominator() -> None:
    rows = _complete_rows()
    rows.append(
        _row(
            "sample-actual",
            "raw_rectangular",
            "actual_gemini",
            "HEARTS_QUEEN",
            _outcome("failed", None, error="timeout"),
        )
    )
    with pytest.raises(ResilienceComparisonError, match="duplicate raw baseline"):
        run_resilience_comparison(_ready_manifest(), rows)

    result = run_resilience_comparison(_ready_manifest(), _complete_rows())

    assert result["tuning_allowed"] is False
    assert result["metrics"]["eligible_items"] == 12
    assert result["metrics"]["classified_items"] == 10
    assert result["metrics"]["unusable_items"] == 1
    assert result["metrics"]["failed_items"] == 1
    assert result["metrics"]["operational_failure_rate"] == pytest.approx(1 / 12)
    assert result["metrics"]["end_to_end_correct_identity_recall"] == pytest.approx(8 / 12)
    assert result["metrics"]["high_confidence_error_rate_when_calibrated"] is None
    assert {item["value"] for item in result["by_input_family"]} == {
        "actual_gemini",
        "reviewed_upper_bound",
        "synthetic_corruption",
    }
    assert any(effect["recovered"] for effect in result["paired_effects"])
    assert any(effect["harmed"] for effect in result["paired_effects"])
    assert all(
        item["upper_bound_only"] is (not item["deployable"])
        for item in result["condition_metadata"]
    )


def test_m3_retention_is_deterministic_and_writes_item_rows(tmp_path: Path) -> None:
    rows = _complete_rows()
    first = run_resilience_comparison(_ready_manifest(), rows)
    second = run_resilience_comparison(_ready_manifest(), list(reversed(rows)))

    assert first == second
    path = write_resilience_comparison(tmp_path / "comparison", first)
    assert path.is_file()
    retained = list((tmp_path / "comparison" / "rows").glob("*.json"))
    assert len(retained) == len(rows)
    assert (
        json.loads(path.read_text(encoding="utf-8"))["comparison_sha256"]
        == first["comparison_sha256"]
    )


def test_m3_requires_actual_and_synthetic_families() -> None:
    rows = _complete_rows()
    for row in rows:
        if row["input_family"] == "synthetic_corruption":
            row["input_family"] = "actual_gemini"
            row["corruption"] = None

    with pytest.raises(ResilienceComparisonError, match="actual Gemini regions and synthetic"):
        run_resilience_comparison(_ready_manifest(), rows)
