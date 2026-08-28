from __future__ import annotations

import json
from pathlib import Path

from table_evidence_analyzer.data import build_smoke_fixture
from table_evidence_analyzer.training import TrainConfig, evaluate, train


def test_smoke_train_and_evaluate_writes_predictions_and_expected_metric(tmp_path: Path) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    config = TrainConfig(
        dataset=fixture.dataset_path,
        split=fixture.split_path,
        artifacts=fixture.artifact_index_path,
        output=tmp_path / "run",
    )
    train(config)
    report = evaluate(config.output, "train")

    assert report["sample_count"] == 1
    assert report["top_1_accuracy"] == 1.0
    assert (config.output / "checkpoint-last.json").exists()
    run = json.loads((config.output / "run.json").read_text())
    assert run["status"] == "completed"
    assert (
        run["dataset_version_digest"]
        == json.loads(fixture.dataset_path.read_text())["dataset_version_digest"]
    )
