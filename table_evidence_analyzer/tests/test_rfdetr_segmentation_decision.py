from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import table_evidence_analyzer.rfdetr_segmentation_decision as decision


def _overall(value: float, *, predictions: int = 1) -> dict[str, object]:
    return {
        "frame_count": 2,
        "target_count": 2,
        "prediction_count": predictions,
        "mask_ap_50_95": value,
        "mask_ap50": value,
        "box_ap50_95": value,
        "recall": value,
        "false_predictions": 0,
        "duplicate_predictions": 0,
        "empty_prediction_rate": 0.0,
    }


def _write_inputs(tmp_path: Path, *, passes: bool) -> tuple[Path, Path, Path]:
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    (bundle_path / "checkpoint.pth").write_bytes(b"checkpoint")
    bundle = {
        "schema_version": "rfdetr-segmentation-bundle/v1",
        "bundle_digest": "b" * 64,
        "checkpoint_sha256": "c" * 64,
        "run_id": "0068-candidate",
    }
    candidate_predictions = {
        "partition": "validation",
        "frames": [
            {
                "image_id": 1,
                "recording_id": "recording-1",
                "event_id": "event-1",
                "image_sha256": "d" * 64,
                "targets": [{"id": 1}],
                "predictions": [{"score": 0.9}, {"score": 0.8}],
            },
            {
                "image_id": 2,
                "recording_id": "recording-1",
                "event_id": "event-2",
                "image_sha256": "e" * 64,
                "targets": [{"id": 2}, {"id": 3}],
                "predictions": [{"score": 0.9}],
            },
        ],
    }
    report_dir = tmp_path / "m3"
    report_dir.mkdir()
    prediction_path = report_dir / "validation-candidate-predictions.json"
    prediction_path.write_text(json.dumps(candidate_predictions), encoding="utf-8")
    candidate_value = 0.8 if passes else 0.0
    baseline_value = 0.0
    report = {
        "schema_version": "rfdetr-segmentation-campaign-validation/v1",
        "status": "completed",
        "campaign_manifest": {},
        "candidate_bundle": {"bundle_digest": bundle["bundle_digest"]},
        "gate": {
            "passes": passes,
            "validation": {"passes": passes},
            "sealed_test": {"evaluated": passes, "passes": passes},
        },
        "partitions": {
            "validation": {
                "prediction_frame_count": 2,
                "target_count": 3,
                "excluded_frame_count": 1,
                "ineligible_outcome_count": 0,
            }
        },
        "metrics": {
            "validation": {
                "baseline": {"overall": _overall(baseline_value)},
                "candidate": {"overall": _overall(candidate_value, predictions=3)},
            }
        },
        "artifacts": {
            "validation_candidate": {
                "path": prediction_path.name,
                "sha256": "not-used-by-m4",
            }
        },
    }
    report_path = report_dir / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    training_path = tmp_path / "run.json"
    training_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "duration_seconds": 123.0,
                "budget_seconds": 7200,
                "resource_facts": {
                    "requested_device": "mps",
                    "selected_device": "mps",
                },
                "bundle": bundle,
                "resumed_from": "rfdetr/last.ckpt",
                "runtime_memory_guard": {"enabled": True},
            }
        ),
        encoding="utf-8",
    )
    return report_path, training_path, bundle_path


@pytest.mark.parametrize("passes", [True, False])
def test_decision_registers_only_a_passing_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, passes: bool
) -> None:
    report_path, training_path, bundle_path = _write_inputs(tmp_path, passes=passes)
    manifest = {
        "schema_version": "rfdetr-segmentation-bundle/v1",
        "bundle_digest": "b" * 64,
        "checkpoint_sha256": "c" * 64,
        "run_id": "0068-candidate",
    }
    checkpoint_path = bundle_path / "checkpoint.pth"
    monkeypatch.setattr(
        decision,
        "load_rfdetr_segmentation_bundle",
        lambda _path: SimpleNamespace(manifest=manifest, checkpoint_path=checkpoint_path),
    )

    output = tmp_path / "m4"
    result = decision.run_rfdetr_segmentation_decision(
        decision.RfdetrSegmentationDecisionConfig(
            validation_report=report_path,
            training_run=training_path,
            candidate_bundle=bundle_path,
            output_dir=output,
        )
    )

    if passes:
        assert result["decision"] == "registered_selectable_candidate"
        assert result["registry"]["default_provider"] == "gemini"
        names = [item["name"] for item in result["registry"]["providers"]]
        assert names == ["gemini", "local", "local-rfdetr-segmentation"]
        assert result["failure_examples"][0]["failure_type"] == "overprediction"
        assert (output / "provider-registry.json").is_file()
    else:
        assert result["decision"] == "retained_experiment"
        assert result["registry"] is None
        assert result["registry_sha256"] is None
        assert not (output / "provider-registry.json").exists()
