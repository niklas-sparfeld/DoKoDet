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


def test_resume_rejects_changed_dataset_and_preserves_previous_checkpoint(tmp_path: Path) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    output = tmp_path / "run"
    config = TrainConfig(
        dataset=fixture.dataset_path,
        split=fixture.split_path,
        artifacts=fixture.artifact_index_path,
        output=output,
    )
    train(config)
    checkpoint = output / "checkpoint-last.json"
    before = checkpoint.read_text()
    changed = TrainConfig(
        dataset=fixture.dataset_path,
        split=fixture.split_path,
        artifacts=fixture.artifact_index_path,
        output=output,
        task="different-task",
        resume=checkpoint,
    )
    import pytest

    with pytest.raises(ValueError, match="incompatible"):
        train(changed)
    assert checkpoint.read_text() == before
    assert json.loads((output / "run.json").read_text())["status"] == "failed"


def test_training_writes_last_and_validation_selected_best_checkpoint(tmp_path: Path) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    config = TrainConfig(
        dataset=fixture.dataset_path,
        split=fixture.split_path,
        artifacts=fixture.artifact_index_path,
        output=tmp_path / "run",
    )
    train(config)
    last = json.loads((config.output / "checkpoint-last.json").read_text())
    best = json.loads((config.output / "checkpoint-best.json").read_text())
    assert last["best_metric"] == "validation_top_1_accuracy"
    assert best["best_value"] == 0.0
    assert last["centroids"] == best["centroids"]
