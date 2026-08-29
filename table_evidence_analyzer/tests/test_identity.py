from __future__ import annotations

import json
from pathlib import Path

import pytest

from table_evidence_analyzer.data import build_smoke_fixture
from table_evidence_analyzer.identity import (
    IDENTITY_FEATURE_SCHEMA,
    IdentityEvaluationConfig,
    IdentityEvaluationError,
    evaluate_identity_crops,
)


def test_identity_evaluation_reports_deterministic_baselines_and_predictions(
    tmp_path: Path,
) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    output = tmp_path / "identity-evaluation.json"
    report = evaluate_identity_crops(
        IdentityEvaluationConfig(
            dataset=fixture.dataset_path,
            split=fixture.split_path,
            artifacts=fixture.artifact_index_path,
            output=output,
            partition="train",
        )
    )

    assert report["schema_version"] == "table-analyzer-identity-evaluation/v1"
    assert report["feature_schema"] == IDENTITY_FEATURE_SCHEMA
    assert set(report["methods"]) == {"rgb-centroid", "rgb-prototype"}
    for method_report in report["methods"].values():
        assert method_report["sample_count"] == 1
        assert method_report["top_1_accuracy"] == 1.0
        assert method_report["top_k_accuracy"] == {"1": 1.0, "3": 1.0, "5": 1.0}
        assert method_report["predictions"][0]["sample_id"] == "smoke-item-a"
        assert method_report["by_quality_tag"]["__untagged__"]["sample_count"] == 1
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_identity_evaluation_uses_only_train_for_unknown_validation_identity(
    tmp_path: Path,
) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    report = evaluate_identity_crops(
        IdentityEvaluationConfig(
            dataset=fixture.dataset_path,
            split=fixture.split_path,
            artifacts=fixture.artifact_index_path,
            output=tmp_path / "identity-evaluation.json",
        )
    )

    for method_report in report["methods"].values():
        assert method_report["sample_count"] == 1
        assert method_report["classes"] == ["CLUBS_NINE"]
        assert method_report["top_1_accuracy"] == 0.0
        assert method_report["predictions"][0]["target"] == "SPADES_JACK"


def test_identity_config_rejects_duplicate_methods_and_unsorted_top_k() -> None:
    common = {
        "dataset": Path("dataset.json"),
        "split": Path("split.json"),
        "artifacts": Path("artifacts.json"),
        "output": Path("report.json"),
    }
    with pytest.raises(IdentityEvaluationError, match="methods must be unique"):
        IdentityEvaluationConfig(**common, methods=("rgb-centroid", "rgb-centroid"))
    with pytest.raises(IdentityEvaluationError, match="sorted and unique"):
        IdentityEvaluationConfig(**common, top_k=(3, 1))


def test_identity_evaluation_rejects_empty_partition_without_report(tmp_path: Path) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    output = tmp_path / "identity-evaluation.json"

    with pytest.raises(IdentityEvaluationError, match="partition is empty"):
        evaluate_identity_crops(
            IdentityEvaluationConfig(
                dataset=fixture.dataset_path,
                split=fixture.split_path,
                artifacts=fixture.artifact_index_path,
                output=output,
                partition="unassigned",
            )
        )
    assert not output.exists()
