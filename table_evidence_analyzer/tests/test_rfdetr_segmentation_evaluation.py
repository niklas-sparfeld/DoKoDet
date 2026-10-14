from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import table_evidence_analyzer.rfdetr_segmentation_evaluation as evaluation


def _artifact(partition: str, model_id: str, recall: float) -> dict[str, object]:
    overall = {
        "frame_count": 1,
        "target_count": 1,
        "prediction_count": 1,
        "mask_ap_50_95": recall,
        "mask_ap50": recall,
        "box_ap50_95": recall,
        "recall": recall,
        "false_predictions": 0,
        "duplicate_predictions": 0,
        "empty_prediction_rate": 0.0,
    }
    return {
        "schema_version": "rfdetr-segmentation-validation-predictions/v1",
        "model_id": model_id,
        "partition": "validation" if partition == "valid" else partition,
        "confidence_threshold": 0.5,
        "frames": [],
        "metrics": {
            "overall": overall,
            "by_recording": {"recording-1": overall},
            "by_side": {"face_up": overall},
            "by_visible_card_count_bucket": {"1": overall},
            "by_recording_side_bucket": {"recording-1|face_up|1": overall},
        },
    }


def test_validation_runs_sealed_test_once_and_reuses_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    materialization = "m" * 64
    manifest_digest = "a" * 64
    view = {"root": tmp_path / "view", "manifest": {"materialization_digest": materialization}}
    candidate = SimpleNamespace(
        checkpoint_path=tmp_path / "candidate.pth",
        manifest={
            "materialization_digest": materialization,
            "campaign_manifest": {"manifest_digest": manifest_digest},
            "bundle_digest": "b" * 64,
            "checkpoint_sha256": "c" * 64,
        },
    )
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(evaluation, "_load_materialization_view", lambda _path: view)
    monkeypatch.setattr(
        evaluation,
        "_verify_campaign_manifest",
        lambda _view, _manifest, _checkpoint: {
            "campaign_id": "0068-m0-reviewed-rfdetr-local-visible-card-detector",
            "manifest_digest": manifest_digest,
        },
    )
    monkeypatch.setattr(evaluation, "load_rfdetr_segmentation_bundle", lambda _path: candidate)
    monkeypatch.setattr(
        evaluation,
        "_exclusion_artifact",
        lambda _view, partition: {
            "excluded_frames": [],
            "ineligible_outcomes": [],
            "excluded_frame_count": 0 if partition == "valid" else 1,
            "ineligible_outcome_count": 0,
        },
    )

    def fake_evaluate(_checkpoint, _view, _device, *, model_id, pretrained, partition):
        del pretrained
        calls.append((model_id, partition))
        return _artifact(partition, model_id, 0.2 if model_id == "candidate" else 0.1)

    monkeypatch.setattr(evaluation, "_evaluate_model", fake_evaluate)

    config = evaluation.RfdetrSegmentationEvaluationConfig(
        dataset_dir=tmp_path / "dataset",
        campaign_manifest=tmp_path / "manifest.json",
        pretrained_checkpoint=tmp_path / "pretrained.pt",
        candidate_bundle=tmp_path / "bundle",
        output_dir=tmp_path / "evaluation",
        device="cpu",
    )
    config.pretrained_checkpoint.write_bytes(b"pretrained")
    report = evaluation.run_rfdetr_segmentation_campaign_validation(config)

    assert calls == [
        ("pretrained-baseline", "valid"),
        ("candidate", "valid"),
        ("pretrained-baseline", "sealed_test"),
        ("candidate", "sealed_test"),
    ]
    assert report["gate"]["sealed_test"]["evaluated"] is True
    assert report["gate"]["passes"] is True
    assert report["partitions"]["sealed_test"]["excluded_frame_count"] == 1
    assert len(report["artifacts"]) == 4

    reused = evaluation.run_rfdetr_segmentation_campaign_validation(config)

    assert reused == report
    assert calls == [
        ("pretrained-baseline", "valid"),
        ("candidate", "valid"),
        ("pretrained-baseline", "sealed_test"),
        ("candidate", "sealed_test"),
    ]
    json.loads((config.output_dir / "report.json").read_text())


@pytest.mark.parametrize(
    ("count", "bucket"),
    [(1, "1"), (2, "2"), (3, "3-4"), (4, "3-4"), (5, "5+"), (12, "5+")],
)
def test_visible_card_count_bucket(count: int, bucket: str) -> None:
    assert evaluation._visible_card_count_bucket(count) == bucket


def test_two_class_metrics_report_each_class_and_cross_class_confusion() -> None:
    frame = {
        "image_id": "mixed-1",
        "width": 10,
        "height": 10,
        "targets": [
            {
                "category_id": 1,
                "width": 10,
                "height": 10,
                "polygons": [[[1, 1], [4, 1], [4, 4], [1, 4]]],
                "box_xywh": [1, 1, 3, 3],
            },
            {
                "category_id": 2,
                "width": 10,
                "height": 10,
                "rle": {"size": [10, 10], "counts": [55, 4, 6, 4, 6, 4, 6, 4, 11]},
                "box_xywh": [5, 5, 4, 4],
            },
        ],
        "predictions": [
            {
                "category_id": 1,
                "class_id": 0,
                "score": 0.9,
                "width": 10,
                "height": 10,
                "polygons": [[[1, 1], [4, 1], [4, 4], [1, 4]]],
                "box_xywh": [1, 1, 3, 3],
            },
            {
                "category_id": 1,
                "class_id": 0,
                "score": 0.8,
                "width": 10,
                "height": 10,
                "polygons": [[[5, 5], [9, 5], [9, 9], [5, 9]]],
                "box_xywh": [5, 5, 4, 4],
            },
        ],
    }

    metrics = evaluation.calculate_metrics([frame])

    assert metrics["by_class"]["visible_card"]["recall"] == 1.0
    assert metrics["by_class"]["card_pile"]["recall"] == 0.0
    assert metrics["class_confusion_at_mask_iou_50"]["visible_card_to_card_pile"] == 1
    assert metrics["visible_card_fragments_inside_piles"] == 1


def test_expanded_validation_gates_apply_frozen_0087_comparison() -> None:
    baseline = {
        "by_class": {
            "visible_card": {"mask_ap_50_95": 0.4, "recall": 0.5},
            "card_pile": {"mask_ap_50_95": 0.1, "recall": 0.2},
        },
        "false_predictions": 4,
        "duplicate_predictions": 2,
        "empty_prediction_rate": 0.1,
    }
    candidate = {
        "by_class": {
            "visible_card": {"mask_ap_50_95": 0.5, "recall": 0.6},
            "card_pile": {"mask_ap_50_95": 0.2, "recall": 0.3},
        },
        "false_predictions": 4,
        "duplicate_predictions": 1,
        "empty_prediction_rate": 0.1,
    }

    assert all(evaluation._expanded_validation_gates(candidate, baseline).values())
    candidate["by_class"]["card_pile"]["recall"] = 0.2
    assert not evaluation._expanded_validation_gates(candidate, baseline)[
        "card_pile_recall_strictly_greater"
    ]


def test_pile_validation_reports_metrics_without_a_sealed_test_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    materialization = "m" * 64
    manifest_digest = "a" * 64
    class_map = {"1": "visible_card", "2": "card_pile"}
    view = {
        "root": tmp_path / "view",
        "manifest": {"materialization_digest": materialization},
        "class_map": class_map,
        "partitions": {"train": [], "valid": [{}]},
    }
    candidate = SimpleNamespace(
        checkpoint_path=tmp_path / "candidate.pth",
        manifest={
            "materialization_digest": materialization,
            "campaign_manifest": {"manifest_digest": manifest_digest},
            "bundle_digest": "b" * 64,
            "checkpoint_sha256": "c" * 64,
            "class_map": class_map,
        },
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(evaluation, "_load_materialization_view", lambda _path: view)
    monkeypatch.setattr(
        evaluation,
        "_verify_campaign_manifest",
        lambda *_args: {
            "campaign_id": "0091-m2-reviewed-two-class-pile-export",
            "manifest_digest": manifest_digest,
        },
    )
    monkeypatch.setattr(evaluation, "load_rfdetr_segmentation_bundle", lambda _path: candidate)
    monkeypatch.setattr(
        evaluation,
        "_exclusion_artifact",
        lambda _view, _partition: {
            "excluded_frames": [],
            "ineligible_outcomes": [],
            "excluded_frame_count": 0,
            "ineligible_outcome_count": 0,
        },
    )

    def fake_evaluate(_checkpoint, _view, _device, *, model_id, pretrained, partition):
        del pretrained
        calls.append((model_id, partition))
        return _artifact(partition, model_id, 0.0)

    monkeypatch.setattr(evaluation, "_evaluate_model", fake_evaluate)
    config = evaluation.RfdetrSegmentationEvaluationConfig(
        dataset_dir=tmp_path / "dataset",
        campaign_manifest=tmp_path / "manifest.json",
        pretrained_checkpoint=tmp_path / "pretrained.pt",
        candidate_bundle=tmp_path / "bundle",
        output_dir=tmp_path / "pile-evaluation",
        device="cpu",
    )
    config.pretrained_checkpoint.write_bytes(b"pretrained")

    report = evaluation.run_rfdetr_segmentation_campaign_validation(config)

    assert calls == [("pretrained-baseline", "valid"), ("candidate", "valid")]
    assert report["quality_state"] == "not_assessed_by_0091_m3"
    assert report["gate"]["passes"] is True
    assert report["gate"]["sealed_test"]["evaluated"] is False
