"""Freeze the 0092 pretest decision after validation and before sealed inference."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .rfdetr_segmentation_training import load_rfdetr_segmentation_bundle

PRETEST_SCHEMA = "0092-m3-pretest-decision/v1"
CAMPAIGN_ID = "0092-m0-expanded-reviewed-rfdetr-campaign"


class RfdetrSegmentationPretestError(ValueError):
    """The frozen 0092 pretest decision cannot be locked safely."""


@dataclass(frozen=True, slots=True)
class RfdetrSegmentationPretestConfig:
    campaign_manifest: Path
    validation_report: Path
    training_run: Path
    candidate_bundle: Path
    output_path: Path


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RfdetrSegmentationPretestError(f"expected a JSON object: {path}")
    return value


def _validation_gates(report: dict[str, Any], manifest: dict[str, Any]) -> dict[str, bool]:
    models = report.get("metrics", {}).get("validation", {})
    baseline = models.get("baseline", {}).get("overall", {}).get("by_class", {})
    candidate = models.get("candidate", {}).get("overall", {}).get("by_class", {})
    baseline_overall = models.get("baseline", {}).get("overall", {})
    candidate_overall = models.get("candidate", {}).get("overall", {})
    gates = manifest.get("quality_gates", {})
    return {
        "visible_card_mask_ap_50_95_strictly_greater": candidate.get("visible_card", {}).get(
            "mask_ap_50_95", 0
        )
        > baseline.get("visible_card", {}).get("mask_ap_50_95", 0),
        "visible_card_recall_strictly_greater": candidate.get("visible_card", {}).get("recall", 0)
        > baseline.get("visible_card", {}).get("recall", 0),
        "card_pile_mask_ap_50_95_strictly_greater": candidate.get("card_pile", {}).get(
            "mask_ap_50_95", 0
        )
        > baseline.get("card_pile", {}).get("mask_ap_50_95", 0),
        "card_pile_recall_strictly_greater": candidate.get("card_pile", {}).get("recall", 0)
        > baseline.get("card_pile", {}).get("recall", 0),
        "false_detections_no_worse": candidate_overall.get("false_predictions", 0)
        <= baseline_overall.get("false_predictions", 0),
        "duplicate_detections_no_worse": candidate_overall.get("duplicate_predictions", 0)
        <= baseline_overall.get("duplicate_predictions", 0),
        "empty_prediction_rate_no_worse": candidate_overall.get("empty_prediction_rate", 0)
        <= baseline_overall.get("empty_prediction_rate", 0),
        "frozen_gate_declarations_match": all(
            gates.get(key) == value
            for key, value in {
                "visible_card_mask_ap_50_95": "strictly_greater_than_0087_candidate_validation",
                "visible_card_recall": "strictly_greater_than_0087_candidate_validation",
                "card_pile_mask_ap_50_95": "strictly_greater_than_0087_candidate_validation",
                "card_pile_recall": "strictly_greater_than_0087_candidate_validation",
                "false_detections": "no_worse_than_0087_candidate_validation",
                "duplicate_detections": "no_worse_than_0087_candidate_validation",
                "empty_prediction_rate": "no_worse_than_0087_candidate_validation",
            }.items()
        ),
    }


def lock_rfdetr_segmentation_pretest(
    config: RfdetrSegmentationPretestConfig,
) -> dict[str, Any]:
    """Write a digest-pinned M3 lock only when frozen validation and authority gates pass."""

    paths = {
        "campaign_manifest": config.campaign_manifest.expanduser().resolve(),
        "validation_report": config.validation_report.expanduser().resolve(),
        "training_run": config.training_run.expanduser().resolve(),
        "candidate_bundle": config.candidate_bundle.expanduser().resolve(),
        "output_path": config.output_path.expanduser().resolve(),
    }
    if paths["output_path"].exists():
        existing = _read(paths["output_path"])
        digest = existing.get("decision_sha256")
        unsigned = {key: value for key, value in existing.items() if key != "decision_sha256"}
        current_inputs = {
            "campaign_manifest": _file_sha256(paths["campaign_manifest"]),
            "validation_report": _file_sha256(paths["validation_report"]),
            "training_run": _file_sha256(paths["training_run"]),
            "bundle_manifest": _file_sha256(paths["candidate_bundle"] / "manifest.json"),
        }
        if (
            existing.get("state") == "locked_before_sealed_test"
            and digest == hashlib.sha256(_canonical(unsigned)).hexdigest()
            and existing.get("input_sha256") == current_inputs
        ):
            return existing
        raise RfdetrSegmentationPretestError("pretest decision path already exists")
    manifest = _read(paths["campaign_manifest"])
    report = _read(paths["validation_report"])
    training = _read(paths["training_run"])
    if manifest.get("campaign_id") != CAMPAIGN_ID:
        raise RfdetrSegmentationPretestError("manifest is not the frozen 0092 campaign")
    if report.get("status") != "completed" or training.get("status") != "completed":
        raise RfdetrSegmentationPretestError("M2 and M3 must be completed")
    bundle = load_rfdetr_segmentation_bundle(paths["candidate_bundle"])
    bundle_digest = bundle.manifest.get("bundle_digest")
    if (
        training.get("bundle", {}).get("bundle_digest") != bundle_digest
        or report.get("candidate_bundle", {}).get("bundle_digest") != bundle_digest
    ):
        raise RfdetrSegmentationPretestError("M2, M3, and bundle digests do not match")
    gates = _validation_gates(report, manifest)
    report_gate_passes = report.get("gate", {}).get("validation", {}).get("passes") is True
    if not all(gates.values()) or not report_gate_passes:
        raise RfdetrSegmentationPretestError("frozen 0092 validation gates do not pass")
    sealed = manifest.get("partitions", {}).get("sealed_test", {})
    support = sealed.get("counts", {})
    minimum = manifest.get("minimum_support", {}).get("sealed_test", {})
    for key in ("retained_frames", "visible_card_targets", "pile_targets"):
        if support.get(key, 0) < minimum.get(key, 0):
            raise RfdetrSegmentationPretestError(f"sealed-test {key} is below frozen support")
    recordings = sealed.get("recordings", [])
    if not recordings or any(
        not {"test", "evaluation"}.issubset(set(row.get("permission_allowed_uses", [])))
        or not {"test", "evaluation"}.issubset(set(row.get("recorded_allowed_uses", [])))
        for row in recordings
    ):
        raise RfdetrSegmentationPretestError("sealed-test recording permissions are incomplete")
    if report.get("metrics", {}).get("sealed_test") is not None:
        raise RfdetrSegmentationPretestError("validation report already contains sealed metrics")
    inputs = {
        "campaign_manifest": _file_sha256(paths["campaign_manifest"]),
        "validation_report": _file_sha256(paths["validation_report"]),
        "training_run": _file_sha256(paths["training_run"]),
        "bundle_manifest": _file_sha256(paths["candidate_bundle"] / "manifest.json"),
    }
    decision: dict[str, Any] = {
        "schema_version": PRETEST_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "milestone": "M3",
        "action": "evaluate_candidate_and_baseline_once",
        "state": "locked_before_sealed_test",
        "candidate_decision": "eligible_for_conditional_selection",
        "candidate_bundle_digest": bundle_digest,
        "materialization_digest": report.get("materialization_digest"),
        "input_sha256": inputs,
        "frozen_acceptance": manifest.get("quality_gates"),
        "validation_gates": gates,
        "pretest_facts": {
            "sealed_test_recordings": [row["recording_id"] for row in recordings],
            "sealed_test_support": support,
            "sealed_test_minimum": minimum,
            "all_recordings_authorized_for_test_and_evaluation": True,
            "runtime_default": "gemini",
            "nonzero_visible_card_recall_per_sealed_test_recording": True,
        },
    }
    decision["decision_sha256"] = hashlib.sha256(_canonical(decision)).hexdigest()
    paths["output_path"].parent.mkdir(parents=True, exist_ok=True)
    paths["output_path"].write_bytes(_canonical(decision) + b"\n")
    return decision
