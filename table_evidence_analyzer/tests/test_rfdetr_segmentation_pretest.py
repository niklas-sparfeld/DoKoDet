from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import table_evidence_analyzer.rfdetr_segmentation_evaluation as evaluation
import table_evidence_analyzer.rfdetr_segmentation_pretest as pretest


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[pretest.RfdetrSegmentationPretestConfig, dict[str, object]]:
    gates = {
        "visible_card_mask_ap_50_95": "strictly_greater_than_0087_candidate_validation",
        "visible_card_recall": "strictly_greater_than_0087_candidate_validation",
        "card_pile_mask_ap_50_95": "strictly_greater_than_0087_candidate_validation",
        "card_pile_recall": "strictly_greater_than_0087_candidate_validation",
        "false_detections": "no_worse_than_0087_candidate_validation",
        "duplicate_detections": "no_worse_than_0087_candidate_validation",
        "empty_prediction_rate": "no_worse_than_0087_candidate_validation",
    }
    manifest = {
        "campaign_id": pretest.CAMPAIGN_ID,
        "quality_gates": gates,
        "minimum_support": {
            "sealed_test": {
                "retained_frames": 30,
                "visible_card_targets": 100,
                "pile_targets": 30,
            }
        },
        "partitions": {
            "sealed_test": {
                "counts": {"retained_frames": 40, "visible_card_targets": 120, "pile_targets": 35},
                "recordings": [
                    {
                        "recording_id": "recording-1",
                        "permission_allowed_uses": ["test", "evaluation"],
                        "recorded_allowed_uses": ["test", "evaluation"],
                    }
                ],
            }
        },
    }
    classes = {
        "visible_card": {"mask_ap_50_95": 0.8, "recall": 0.9},
        "card_pile": {"mask_ap_50_95": 0.7, "recall": 0.8},
    }
    validation = {
        "status": "completed",
        "materialization_digest": "materialization",
        "gate": {"validation": {"passes": True}},
        "metrics": {
            "validation": {
                "baseline": {
                    "overall": {
                        "by_class": {
                            "visible_card": {"mask_ap_50_95": 0.7, "recall": 0.8},
                            "card_pile": {"mask_ap_50_95": 0.6, "recall": 0.7},
                        },
                        "false_predictions": 5,
                        "duplicate_predictions": 1,
                        "empty_prediction_rate": 0.2,
                    }
                },
                "candidate": {
                    "overall": {
                        "by_class": classes,
                        "false_predictions": 4,
                        "duplicate_predictions": 1,
                        "empty_prediction_rate": 0.1,
                    }
                },
            },
            "sealed_test": None,
        },
        "candidate_bundle": {"bundle_digest": "bundle-digest"},
    }
    training = {"status": "completed", "bundle": {"bundle_digest": "bundle-digest"}}
    manifest_path = tmp_path / "manifest.json"
    validation_path = tmp_path / "validation.json"
    training_path = tmp_path / "run.json"
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    (bundle_path / "manifest.json").write_text("{}", encoding="utf-8")
    _write(manifest_path, manifest)
    _write(validation_path, validation)
    _write(training_path, training)
    config = pretest.RfdetrSegmentationPretestConfig(
        campaign_manifest=manifest_path,
        validation_report=validation_path,
        training_run=training_path,
        candidate_bundle=bundle_path,
        output_path=tmp_path / "decision.json",
    )
    return config, manifest


def test_lock_requires_frozen_gates_support_and_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _fixture(tmp_path)
    monkeypatch.setattr(
        pretest,
        "load_rfdetr_segmentation_bundle",
        lambda _path: SimpleNamespace(manifest={"bundle_digest": "bundle-digest"}),
    )

    lock = pretest.lock_rfdetr_segmentation_pretest(config)

    assert lock["state"] == "locked_before_sealed_test"
    assert lock["validation_gates"]["card_pile_recall_strictly_greater"] is True
    unsigned = {key: value for key, value in lock.items() if key != "decision_sha256"}
    digest = hashlib.sha256(pretest._canonical(unsigned)).hexdigest()
    assert digest == lock["decision_sha256"]
    assert pretest.lock_rfdetr_segmentation_pretest(config) == lock


def test_lock_rejects_missing_sealed_test_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, manifest = _fixture(tmp_path)
    manifest["partitions"]["sealed_test"]["recordings"][0]["permission_allowed_uses"] = ["test"]
    _write(config.campaign_manifest, manifest)
    monkeypatch.setattr(
        pretest,
        "load_rfdetr_segmentation_bundle",
        lambda _path: SimpleNamespace(manifest={"bundle_digest": "bundle-digest"}),
    )

    with pytest.raises(pretest.RfdetrSegmentationPretestError, match="permissions"):
        pretest.lock_rfdetr_segmentation_pretest(config)


def test_0092_sealed_evaluation_accepts_its_frozen_pretest_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, manifest = _fixture(tmp_path)
    manifest["manifest_sha256"] = "frozen-m0-digest"
    manifest["partitions"]["train"] = {"recordings": [{"recording_id": "train-1"}]}
    _write(config.campaign_manifest, manifest)
    _write(
        config.validation_report,
        {
            "status": "completed",
            "materialization_digest": "materialization",
            "gate": {"validation": {"passes": True}},
            "metrics": {
                "validation": {
                    "baseline": {
                        "overall": {
                            "by_class": {
                                "visible_card": {"mask_ap_50_95": 0.7, "recall": 0.8},
                                "card_pile": {"mask_ap_50_95": 0.6, "recall": 0.7},
                            },
                            "false_predictions": 5,
                            "duplicate_predictions": 1,
                            "empty_prediction_rate": 0.2,
                        }
                    },
                    "candidate": {
                        "overall": {
                            "by_class": {
                                "visible_card": {"mask_ap_50_95": 0.8, "recall": 0.9},
                                "card_pile": {"mask_ap_50_95": 0.7, "recall": 0.8},
                            },
                            "false_predictions": 4,
                            "duplicate_predictions": 1,
                            "empty_prediction_rate": 0.1,
                        }
                    },
                },
                "sealed_test": None,
            },
            "candidate_bundle": {"bundle_digest": "bundle-digest"},
        },
    )
    _write(
        config.training_run, {"status": "completed", "bundle": {"bundle_digest": "bundle-digest"}}
    )
    (config.candidate_bundle / "checkpoint.pth").write_bytes(b"candidate")
    (tmp_path / "pretrained.pth").write_bytes(b"pretrained")
    candidate_bundle = SimpleNamespace(
        root=config.candidate_bundle,
        checkpoint_path=config.candidate_bundle / "checkpoint.pth",
        manifest={
            "bundle_digest": "bundle-digest",
            "checkpoint_sha256": "checkpoint-digest",
            "materialization_digest": "materialization",
            "schema_version": "test-bundle",
            "run_id": "test-run",
        },
    )
    monkeypatch.setattr(
        pretest,
        "load_rfdetr_segmentation_bundle",
        lambda _path: candidate_bundle,
    )
    lock = pretest.lock_rfdetr_segmentation_pretest(config)
    decision_path = tmp_path / "decision.json"
    _write(decision_path, lock)
    monkeypatch.setattr(
        evaluation, "load_rfdetr_segmentation_bundle", lambda _path: candidate_bundle
    )
    monkeypatch.setattr(
        evaluation,
        "_load_materialization_view",
        lambda _path: {"root": tmp_path, "manifest": {"materialization_digest": "materialization"}},
    )
    monkeypatch.setattr(
        evaluation, "_verify_campaign_manifest", lambda *_args: {"campaign_id": pretest.CAMPAIGN_ID}
    )
    monkeypatch.setattr(
        evaluation,
        "_timed_evaluate_model",
        lambda *_args, model_id, **_kwargs: (
            {
                "model_id": model_id,
                "metrics": {
                    "overall": {"frame_count": 1, "target_count": 1},
                    "by_recording": {"sealed-1": {"by_class": {"visible_card": {"recall": 1.0}}}},
                },
                "frames": [],
            },
            {"frame_count": 1, "inference_mean_ms_per_frame": 1.0},
        ),
    )
    sealed_config = evaluation.RfdetrSegmentationSealedTestConfig(
        dataset_dir=tmp_path / "dataset",
        campaign_manifest=config.campaign_manifest,
        pretrained_checkpoint=tmp_path / "pretrained.pth",
        training_run=config.training_run,
        validation_report=config.validation_report,
        candidate_bundle=config.candidate_bundle,
        pretest_decision=decision_path,
        output_dir=tmp_path / "sealed-output",
        device="cpu",
    )

    result = evaluation.run_rfdetr_segmentation_sealed_test(sealed_config)

    assert result["schema_version"] == "0092-m3-sealed-test-report/v1"
    assert result["decision"] == "selected_selectable_candidate"
    assert result["sealed_test_gate"]["passes"] is True
