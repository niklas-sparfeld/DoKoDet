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
