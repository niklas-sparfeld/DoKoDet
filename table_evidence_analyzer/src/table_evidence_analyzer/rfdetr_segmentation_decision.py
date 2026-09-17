"""Decide and register the reviewed RF-DETR visible-card candidate."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .rfdetr_segmentation_training import load_rfdetr_segmentation_bundle
from .visible_cards import GEMINI_PROVIDER_NAME

RFDETR_SEGMENTATION_DECISION_SCHEMA = "rfdetr-visible-card-detector-decision/v1"
VISIBLE_CARD_PROVIDER_REGISTRY_SCHEMA = "visible-card-provider-registry/v1"
REVIEWED_SEGMENTATION_PROVIDER = "local-rfdetr-segmentation"
DEFAULT_VISIBLE_CARD_PROVIDER = "gemini"
LEGACY_LOCAL_VISIBLE_CARD_PROVIDER = "local"


class RfdetrSegmentationDecisionError(ValueError):
    """The RF-DETR local availability decision cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class RfdetrSegmentationDecisionConfig:
    """Inputs for one M4 decision and local-provider registration receipt."""

    validation_report: Path
    training_run: Path
    candidate_bundle: Path
    output_dir: Path


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RfdetrSegmentationDecisionError("decision values must be finite JSON") from error


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise RfdetrSegmentationDecisionError(f"could not read decision input: {path}") from error


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RfdetrSegmentationDecisionError(f"could not read {context}: {path}") from error
    if not isinstance(value, dict):
        raise RfdetrSegmentationDecisionError(f"{context} must be a JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical(value) + b"\n")
    temporary.replace(path)


def _required_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RfdetrSegmentationDecisionError(f"{field} must be an object")
    return value


def _validate_inputs(
    report: Mapping[str, Any], training_run: Mapping[str, Any], bundle: Any
) -> tuple[bool, Mapping[str, Any], Mapping[str, Any]]:
    if report.get("schema_version") != "rfdetr-segmentation-campaign-validation/v1":
        raise RfdetrSegmentationDecisionError("M3 report schema is unsupported")
    if report.get("status") != "completed":
        raise RfdetrSegmentationDecisionError("M3 report is not completed")
    gate = _required_mapping(report.get("gate"), "M3 gate")
    gate_passes = gate.get("passes")
    if not isinstance(gate_passes, bool):
        raise RfdetrSegmentationDecisionError("M3 gate.passes must be boolean")
    if training_run.get("status") != "completed":
        raise RfdetrSegmentationDecisionError("M2 training run is not completed")
    run_bundle = _required_mapping(training_run.get("bundle"), "M2 bundle")
    manifest = _required_mapping(getattr(bundle, "manifest", None), "candidate bundle manifest")
    if run_bundle.get("bundle_digest") != manifest.get("bundle_digest"):
        raise RfdetrSegmentationDecisionError("M2 and candidate bundle digests do not match")
    report_bundle = _required_mapping(report.get("candidate_bundle"), "M3 candidate bundle")
    if report_bundle.get("bundle_digest") != manifest.get("bundle_digest"):
        raise RfdetrSegmentationDecisionError("M3 and candidate bundle digests do not match")
    return gate_passes, gate, manifest


def _mismatch_examples(report: Mapping[str, Any], report_root: Path) -> list[dict[str, Any]]:
    artifacts = _required_mapping(report.get("artifacts"), "M3 artifacts")
    examples: list[dict[str, Any]] = []
    for artifact_key in ("validation_candidate", "sealed_test_candidate"):
        metadata = artifacts.get(artifact_key)
        if not isinstance(metadata, Mapping) or not isinstance(metadata.get("path"), str):
            continue
        artifact = _read_json(report_root / metadata["path"], f"{artifact_key} predictions")
        frames = artifact.get("frames")
        if not isinstance(frames, Sequence) or isinstance(frames, (str, bytes)):
            continue
        for frame in frames:
            if not isinstance(frame, Mapping):
                continue
            targets = frame.get("targets")
            predictions = frame.get("predictions")
            if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)):
                continue
            if not isinstance(predictions, Sequence) or isinstance(predictions, (str, bytes)):
                continue
            target_count = len(targets)
            prediction_count = len(predictions)
            if target_count == prediction_count:
                continue
            examples.append(
                {
                    "partition": artifact.get("partition"),
                    "recording_id": frame.get("recording_id"),
                    "event_id": frame.get("event_id"),
                    "image_id": frame.get("image_id"),
                    "image_sha256": frame.get("image_sha256"),
                    "target_count": target_count,
                    "prediction_count": prediction_count,
                    "count_delta": prediction_count - target_count,
                    "failure_type": (
                        "overprediction" if prediction_count > target_count else "underdetection"
                    ),
                }
            )
    examples.sort(
        key=lambda item: (
            -abs(int(item["count_delta"])),
            str(item.get("partition")),
            str(item.get("recording_id")),
            str(item.get("event_id")),
        )
    )
    return examples[:8]


def _summary_metrics(report: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _required_mapping(report.get("metrics"), "M3 metrics")
    result: dict[str, Any] = {}
    for partition in ("validation", "sealed_test"):
        partition_metrics = metrics.get(partition)
        if not isinstance(partition_metrics, Mapping):
            continue
        row: dict[str, Any] = {}
        for model_id in ("baseline", "candidate"):
            model_metrics = _required_mapping(
                partition_metrics.get(model_id), f"{partition}.{model_id}"
            )
            overall = _required_mapping(
                model_metrics.get("overall"), f"{partition}.{model_id}.overall"
            )
            row[model_id] = {
                field: overall[field]
                for field in (
                    "frame_count",
                    "target_count",
                    "prediction_count",
                    "mask_ap_50_95",
                    "mask_ap50",
                    "box_ap50_95",
                    "recall",
                    "false_predictions",
                    "duplicate_predictions",
                    "empty_prediction_rate",
                )
                if field in overall
            }
        result[partition] = row
    return result


def _corpus_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    campaign = report.get("campaign_manifest")
    if isinstance(campaign, Mapping) and isinstance(campaign.get("path"), str):
        manifest_path = Path(campaign["path"])
        if manifest_path.is_file():
            manifest = _read_json(manifest_path, "M0 manifest")
            inventory = manifest.get("inventory")
            if isinstance(inventory, Mapping):
                summary["m0_inventory"] = dict(inventory)
    partitions = report.get("partitions")
    if isinstance(partitions, Mapping):
        summary["evaluated_partitions"] = {
            str(name): {
                field: value
                for field in (
                    "prediction_frame_count",
                    "target_count",
                    "excluded_frame_count",
                    "ineligible_outcome_count",
                )
                if (value := partition.get(field)) is not None
            }
            for name, partition in partitions.items()
            if isinstance(partition, Mapping)
        }
    return summary


def _provider_registry(
    *, bundle_path: Path, manifest: Mapping[str, Any], decision_report: str
) -> dict[str, Any]:
    bundle_identity = {
        "schema_version": manifest.get("schema_version"),
        "bundle_digest": manifest.get("bundle_digest"),
        "checkpoint_sha256": manifest.get("checkpoint_sha256"),
        "run_id": manifest.get("run_id"),
    }
    return {
        "schema_version": VISIBLE_CARD_PROVIDER_REGISTRY_SCHEMA,
        "registry_version": 1,
        "default_provider": DEFAULT_VISIBLE_CARD_PROVIDER,
        "providers": [
            {
                "name": GEMINI_PROVIDER_NAME,
                "selection": "VISIBLE_CARD_PROVIDER=gemini",
                "default": True,
                "selectable": True,
            },
            {
                "name": LEGACY_LOCAL_VISIBLE_CARD_PROVIDER,
                "selection": "VISIBLE_CARD_PROVIDER=local",
                "default": False,
                "selectable": True,
                "contract": "visible-card-bundle/v1",
            },
            {
                "name": REVIEWED_SEGMENTATION_PROVIDER,
                "selection": "VISIBLE_CARD_PROVIDER=local-rfdetr-segmentation",
                "default": False,
                "selectable": True,
                "bundle_path": str(bundle_path),
                "bundle_identity": bundle_identity,
                "decision_report": decision_report,
            },
        ],
        "rollback": {
            "action": "remove_provider",
            "provider": REVIEWED_SEGMENTATION_PROVIDER,
            "preserve_default_provider": DEFAULT_VISIBLE_CARD_PROVIDER,
        },
    }


def run_rfdetr_segmentation_decision(
    config: RfdetrSegmentationDecisionConfig,
) -> dict[str, Any]:
    """Write the bounded M4 decision and, only on a passing gate, a provider registry."""

    output = config.output_dir.expanduser().resolve()
    report_path = output / "decision.json"
    registry_path = output / "provider-registry.json"
    if report_path.is_file() and registry_path.is_file():
        report = _read_json(report_path, "M4 decision report")
        registry = _read_json(registry_path, "visible-card provider registry")
        if report.get("registry_sha256") == _file_digest(registry_path):
            report["registry"] = registry
            return report
        raise RfdetrSegmentationDecisionError("completed M4 registry has drifted")
    if report_path.is_file() and not registry_path.exists():
        report = _read_json(report_path, "M4 decision report")
        if report.get("status") == "completed" and report.get("registry_sha256") is None:
            report["registry"] = None
            return report
    if output.exists() and any(output.iterdir()):
        raise RfdetrSegmentationDecisionError("M4 output directory is not empty")

    validation_path = config.validation_report.expanduser().resolve()
    training_path = config.training_run.expanduser().resolve()
    bundle_path = config.candidate_bundle.expanduser().resolve()
    report = _read_json(validation_path, "M3 validation report")
    training_run = _read_json(training_path, "M2 training run")
    try:
        bundle = load_rfdetr_segmentation_bundle(bundle_path)
    except Exception as error:
        raise RfdetrSegmentationDecisionError(
            f"candidate bundle is not loadable: {error}"
        ) from error
    gate_passes, gate, manifest = _validate_inputs(report, training_run, bundle)
    metrics = _summary_metrics(report)
    resource_facts = training_run.get("resource_facts")
    if not isinstance(resource_facts, Mapping):
        resource_facts = {}
    decision = "registered_selectable_candidate" if gate_passes else "retained_experiment"
    registry: dict[str, Any] | None = None
    if gate_passes:
        registry = _provider_registry(
            bundle_path=bundle_path,
            manifest=manifest,
            decision_report=str(report_path),
        )
        _write_json(registry_path, registry)

    corpus = _corpus_summary(report)
    decision_report: dict[str, Any] = {
        "schema_version": RFDETR_SEGMENTATION_DECISION_SCHEMA,
        "status": "completed",
        "decision": decision,
        "candidate_provider": REVIEWED_SEGMENTATION_PROVIDER,
        "default_provider": DEFAULT_VISIBLE_CARD_PROVIDER,
        "legacy_local_provider_unchanged": True,
        "inputs": {
            "validation_report": {
                "path": str(validation_path),
                "sha256": _file_digest(validation_path),
            },
            "training_run": {
                "path": str(training_path),
                "sha256": _file_digest(training_path),
            },
            "candidate_bundle": {
                "path": str(bundle_path),
                "bundle_digest": manifest.get("bundle_digest"),
                "checkpoint_sha256": manifest.get("checkpoint_sha256"),
            },
        },
        "corpus": corpus,
        "metrics": metrics,
        "gate": dict(gate),
        "failure_examples": _mismatch_examples(report, validation_path.parent),
        "resource_cost": {
            "training_duration_seconds": training_run.get("duration_seconds"),
            "training_budget_seconds": training_run.get("budget_seconds"),
            "requested_device": resource_facts.get("requested_device"),
            "selected_device": resource_facts.get("selected_device"),
            "resumed_from": training_run.get("resumed_from"),
            "runtime_memory_guard": training_run.get("runtime_memory_guard"),
        },
        "limits": {
            "background_only_precision_measured": False,
            "production_readiness_claimed": False,
            "note": (
                "The reviewed corpus has no empty-background frames. The measured result covers "
                "positive reviewed frames only; excluded frames remain outside the score."
            ),
        },
        "rollback": (
            "Remove the local-rfdetr-segmentation provider entry from provider-registry.json; "
            "keep VISIBLE_CARD_PROVIDER=gemini."
        ),
    }
    if registry is not None:
        decision_report["registry_sha256"] = _file_digest(registry_path)
    else:
        decision_report["registry_sha256"] = None
    _write_json(report_path, decision_report)
    decision_report["registry"] = registry
    return decision_report


__all__ = [
    "DEFAULT_VISIBLE_CARD_PROVIDER",
    "LEGACY_LOCAL_VISIBLE_CARD_PROVIDER",
    "REVIEWED_SEGMENTATION_PROVIDER",
    "RFDETR_SEGMENTATION_DECISION_SCHEMA",
    "RfdetrSegmentationDecisionConfig",
    "RfdetrSegmentationDecisionError",
    "VISIBLE_CARD_PROVIDER_REGISTRY_SCHEMA",
    "run_rfdetr_segmentation_decision",
]
