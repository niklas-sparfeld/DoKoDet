from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_visible_card_dataset import _write_source_and_results

from table_evidence_analyzer.visible_card_dataset import (
    VisibleCardDatasetConfig,
    materialize_visible_card_dataset,
)
from table_evidence_analyzer.visible_card_training import (
    VISIBLE_CARD_BUNDLE_SCHEMA,
    VisibleCardTrainingConfig,
    VisibleCardTrainingError,
    load_visible_card_detector_bundle,
    run_visible_card_training,
)


def _materialized_fixture(root: Path) -> tuple[Path, Path, Path]:
    evidence_root, results_root = _write_source_and_results(root / "input")
    dataset_root = root / "dataset"
    materialize_visible_card_dataset(
        VisibleCardDatasetConfig(
            evidence_root=evidence_root,
            results_root=results_root,
            output_dir=dataset_root,
        )
    )
    pretrained = root / "rf-detr-large.pth"
    pretrained.write_bytes(b"fixture pretrained weights")
    return dataset_root, evidence_root, pretrained


def test_fixture_training_maps_dataset_and_writes_validated_bundle(tmp_path: Path) -> None:
    dataset_root, evidence_root, pretrained = _materialized_fixture(tmp_path)
    output = tmp_path / "training"

    record = run_visible_card_training(
        VisibleCardTrainingConfig(
            dataset_dir=dataset_root,
            evidence_root=evidence_root,
            pretrained_checkpoint=pretrained,
            output_dir=output,
            runner="fixture",
        )
    )

    assert record["status"] == "completed"
    assert record["loss_confirmation"] == {
        "confirmed": True,
        "finite": True,
        "sample_count": 3,
        "evidence": ["losses.json"],
    }
    assert record["checkpoint"]["weights_differ"] is True
    assert record["training_arguments"]["dataset_file"] == "roboflow"
    assert record["training_arguments"]["epochs"] == 20
    assert record["training_arguments"]["resolution"] == 704
    assert record["training_arguments"]["device"] == "cuda:0"
    assert record["model_arguments"]["pretrain_weights"] == str(pretrained.resolve())

    staged = output / "rfdet-dataset"
    assert (staged / "train/_annotations.coco.json").is_file()
    assert (staged / "valid/_annotations.coco.json").is_file()
    assert next((staged / "train/images").iterdir()).is_symlink()
    train_annotations = json.loads(
        (staged / "train/_annotations.coco.json").read_text(encoding="utf-8")
    )
    valid_annotations = json.loads(
        (staged / "valid/_annotations.coco.json").read_text(encoding="utf-8")
    )
    assert train_annotations["categories"] == [
        {"id": 1, "name": "visible_card", "supercategory": "card"}
    ]
    assert train_annotations["images"]
    assert valid_annotations["images"]

    bundle = load_visible_card_detector_bundle(output / "bundle")
    assert bundle.manifest["schema_version"] == VISIBLE_CARD_BUNDLE_SCHEMA
    assert bundle.manifest["quality_state"] == "unreviewed"
    assert bundle.checkpoint_path.name == "checkpoint_best_total.pth"


def test_bundle_loader_rejects_tampered_checkpoint(tmp_path: Path) -> None:
    dataset_root, evidence_root, pretrained = _materialized_fixture(tmp_path)
    output = tmp_path / "training"
    run_visible_card_training(
        VisibleCardTrainingConfig(
            dataset_dir=dataset_root,
            evidence_root=evidence_root,
            pretrained_checkpoint=pretrained,
            output_dir=output,
            runner="fixture",
        )
    )
    checkpoint = output / "bundle/checkpoint_best_total.pth"
    checkpoint.write_bytes(checkpoint.read_bytes() + b"tampered")

    with pytest.raises(VisibleCardTrainingError, match="hash"):
        load_visible_card_detector_bundle(output / "bundle")


def test_training_failure_writes_complete_failure_record(tmp_path: Path) -> None:
    dataset_root, evidence_root, _ = _materialized_fixture(tmp_path)
    output = tmp_path / "training"
    missing_checkpoint = tmp_path / "missing-rf-detr-large.pth"

    with pytest.raises(VisibleCardTrainingError, match="pretrained checkpoint does not exist"):
        run_visible_card_training(
            VisibleCardTrainingConfig(
                dataset_dir=dataset_root,
                evidence_root=evidence_root,
                pretrained_checkpoint=missing_checkpoint,
                output_dir=output,
                runner="fixture",
            )
        )

    record = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert record["schema_version"] == "visible-card-detector-training-run/v1"
    assert record["status"] == "failed"
    assert record["failure"]["type"] == "VisibleCardTrainingError"
    assert record["failure"]["message"] == "pretrained checkpoint does not exist: " + str(
        missing_checkpoint.resolve()
    )
