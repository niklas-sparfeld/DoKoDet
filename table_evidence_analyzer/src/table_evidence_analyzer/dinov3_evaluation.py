"""Evaluate one exported local DINOv3 identity bundle against its frozen validation crops."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .data import (
    CropCache,
    MaterializedCropDataset,
    assert_valid_dataset,
    load_artifact_index,
    load_dataset_manifest,
    load_split_manifest,
)
from .dinov3_bundle import DinoV3IdentityBundle, load_dinov3_identity_bundle
from .dinov3_inference import DinoV3IdentityClassifier
from .local_identity import VISUAL_IDENTITY_TARGETS

DINOV3_EVALUATION_SCHEMA = "dinov3-identity-bundle-evaluation/v2"
DINOV3_REPRODUCTION_TOLERANCE = 1e-5
_UNAVAILABLE_TARGET = "__UNAVAILABLE__"


class DinoV3EvaluationError(ValueError):
    """Raised when a DINOv3 bundle cannot be evaluated against its frozen run."""


@dataclass(frozen=True, slots=True)
class DinoV3EvaluationConfig:
    """Inputs for one deterministic exported-bundle validation run."""

    run: Path
    bundle: Path
    output: Path
    provider_receipts: Path | None = None
    device: str = "cpu"
    probability_tolerance: float = DINOV3_REPRODUCTION_TOLERANCE

    def __post_init__(self) -> None:
        if self.device not in {"cpu", "mps", "cuda"}:
            raise DinoV3EvaluationError(f"unsupported DINOv3 evaluation device: {self.device}")
        if not math.isfinite(self.probability_tolerance) or self.probability_tolerance <= 0:
            raise DinoV3EvaluationError("probability_tolerance must be finite and positive")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise DinoV3EvaluationError(f"could not read evaluation file: {path}") from error
    return digest.hexdigest()


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DinoV3EvaluationError(f"{field} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise DinoV3EvaluationError(f"{field} must be a JSON object")
    return value


def _required_path(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise DinoV3EvaluationError(f"{field} is missing")
    return Path(value).expanduser().resolve()


def _campaign_path(campaign_root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise DinoV3EvaluationError(f"{field} is missing")
    path = (campaign_root / value).resolve()
    if campaign_root not in path.parents:
        raise DinoV3EvaluationError(f"{field} escapes the campaign root")
    return path


def _f1(true_positive: int, false_positive: int, false_negative: int) -> float:
    denominator = 2 * true_positive + false_positive + false_negative
    return 2 * true_positive / denominator if denominator else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 6)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical(value) + b"\n")
    temporary.replace(path)


def _load_campaign_inputs(
    run: Mapping[str, Any], run_root: Path
) -> tuple[dict[str, Any], list[Any], list[Any]]:
    config = run.get("config")
    if not isinstance(config, Mapping):
        raise DinoV3EvaluationError("DINOv3 run has no config record")
    campaign_manifest_path = _required_path(config.get("campaign_manifest"), "campaign manifest")
    campaign = _read_json(campaign_manifest_path, "campaign manifest")
    if campaign.get("state") != "frozen":
        raise DinoV3EvaluationError("DINOv3 campaign is not frozen")
    if campaign.get("campaign_id") != run.get("campaign", {}).get("campaign_id"):
        raise DinoV3EvaluationError("run and campaign IDs do not match")
    if campaign.get("manifest_digest") != run.get("campaign", {}).get("manifest_digest"):
        raise DinoV3EvaluationError("run and campaign manifest digests do not match")

    dataset_path = _required_path(config.get("dataset"), "dataset")
    split_path = _required_path(config.get("split"), "split")
    artifacts_path = _required_path(config.get("artifacts"), "artifact index")
    dataset = load_dataset_manifest(dataset_path)
    split = load_split_manifest(split_path)
    artifacts = load_artifact_index(artifacts_path)
    assert_valid_dataset(dataset, split=split, artifacts=artifacts)
    if campaign.get("dataset", {}).get("digest") != dataset.digest:
        raise DinoV3EvaluationError("campaign dataset digest does not match the run input")
    if campaign.get("split", {}).get("digest") != split.digest:
        raise DinoV3EvaluationError("campaign split digest does not match the run input")

    crop_inventory_path = _campaign_path(
        campaign_manifest_path.parent,
        campaign.get("crop_inventory", {}).get("path"),
        "campaign crop inventory",
    )
    cache_data = _read_json(crop_inventory_path, "campaign crop inventory")
    cache = CropCache.from_mapping(cache_data, root=crop_inventory_path.parent)
    expected_cache_digest = campaign.get("crop_inventory", {}).get("digest")
    if cache.digest != expected_cache_digest:
        raise DinoV3EvaluationError("campaign crop cache digest does not match its manifest")
    for crop in cache.crops:
        cache.read(crop)
    validation_samples = list(MaterializedCropDataset(cache, partition="validation"))
    if not validation_samples:
        raise DinoV3EvaluationError("DINOv3 validation partition is empty")

    prediction_path = run_root / "predictions-validation.json"
    prediction_data = _read_json(prediction_path, "checkpoint validation predictions")
    expected_rows = prediction_data.get("predictions")
    if not isinstance(expected_rows, list) or not expected_rows:
        raise DinoV3EvaluationError("checkpoint validation predictions are empty")
    return campaign, [*validation_samples], expected_rows


def _campaign_item_index(campaign: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    items = campaign.get("items")
    if not isinstance(items, list):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        sample_id = item.get("sample_id")
        if isinstance(sample_id, str):
            if sample_id in result:
                raise DinoV3EvaluationError("campaign contains duplicate sample IDs")
            result[sample_id] = item
    return result


def _provider_receipt_index(
    path: Path,
    *,
    expected: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Any]]:
    receipt = _read_json(path.expanduser().resolve(), "provider receipts")
    if set(receipt) != {"schema_version", "provider", "outcomes"}:
        raise DinoV3EvaluationError("provider receipt has unexpected fields")
    if receipt.get("schema_version") != "dinov3-paired-provider-receipts/v1":
        raise DinoV3EvaluationError("provider receipt schema is unsupported")
    if receipt.get("provider") != "gemini":
        raise DinoV3EvaluationError("provider receipts must identify Gemini")
    rows = receipt.get("outcomes")
    if not isinstance(rows, list):
        raise DinoV3EvaluationError("provider receipt outcomes must be a list")
    indexed: dict[str, Mapping[str, Any]] = {}
    allowed_statuses = {"classified", "unusable", "failed", "side_bypassed"}
    for row in rows:
        if not isinstance(row, Mapping):
            raise DinoV3EvaluationError("provider receipt outcome must be an object")
        if set(row) != {"sample_id", "crop_sha256", "status", "prediction", "request_identity"}:
            raise DinoV3EvaluationError("provider receipt outcome has unexpected fields")
        sample_id = row.get("sample_id")
        if not isinstance(sample_id, str) or sample_id not in expected:
            raise DinoV3EvaluationError("provider receipt contains an unknown sample ID")
        if sample_id in indexed:
            raise DinoV3EvaluationError("provider receipt contains duplicate sample IDs")
        expected_digest = expected[sample_id].get("crop_sha256")
        if not isinstance(expected_digest, str) or row.get("crop_sha256") != expected_digest:
            raise DinoV3EvaluationError(
                f"provider receipt crop digest does not match sample {sample_id}"
            )
        status = row.get("status")
        if status not in allowed_statuses:
            raise DinoV3EvaluationError(f"provider receipt has unsupported status for {sample_id}")
        request_identity = row.get("request_identity")
        required_request_fields = {
            "request_id",
            "model_id",
            "prompt_sha256",
            "input_sha256",
            "generation_config_sha256",
        }
        if (
            not isinstance(request_identity, Mapping)
            or set(request_identity) != required_request_fields
        ):
            raise DinoV3EvaluationError(
                f"provider receipt has no exact request identity for {sample_id}"
            )
        if any(
            not isinstance(request_identity[field], str) or not request_identity[field]
            for field in required_request_fields
        ):
            raise DinoV3EvaluationError(
                f"provider receipt request identity is incomplete for {sample_id}"
            )
        for field in ("prompt_sha256", "input_sha256", "generation_config_sha256"):
            digest = request_identity[field]
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise DinoV3EvaluationError(
                    f"provider receipt {field} is not a SHA-256 digest for {sample_id}"
                )
        if request_identity["input_sha256"] != expected_digest:
            raise DinoV3EvaluationError(
                f"provider request input digest does not match sample {sample_id}"
            )
        prediction = row.get("prediction")
        if status == "classified" and prediction not in VISUAL_IDENTITY_TARGETS:
            raise DinoV3EvaluationError(
                f"provider receipt has an invalid prediction for {sample_id}"
            )
        if status != "classified" and prediction is not None:
            raise DinoV3EvaluationError(
                f"non-classified provider outcome has a prediction for {sample_id}"
            )
        indexed[sample_id] = row
    return indexed, receipt


def _classification_metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    targets = tuple(VISUAL_IDENTITY_TARGETS)
    classified = [row for row in rows if row.get("status", "classified") == "classified"]
    per_class: dict[str, dict[str, Any]] = {}
    confusion: dict[str, dict[str, int]] = {}
    for target in targets:
        support = sum(row.get("target") == target for row in rows)
        tp = sum(row.get("target") == target and row.get("prediction") == target for row in rows)
        fp = sum(row.get("target") != target and row.get("prediction") == target for row in rows)
        fn = sum(row.get("target") == target and row.get("prediction") != target for row in rows)
        f1 = _f1(tp, fp, fn)
        per_class[target] = {
            "support": support,
            "measured": support > 0,
            "top_1_correct": tp,
            "top_1_accuracy": tp / support if support else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": f1 if support else None,
        }
        confusion[target] = dict(
            sorted(
                Counter(
                    str(row["prediction"])
                    for row in rows
                    if row.get("target") == target and isinstance(row.get("prediction"), str)
                ).items()
            )
        )
    total = len(rows)
    top_1 = sum(row.get("prediction") == row.get("target") for row in classified)
    top_3 = sum(
        row.get("target") in row.get("top_k", [])[:3]
        for row in classified
        if isinstance(row.get("top_k"), list)
    )
    scored_classes = [target for target in targets if per_class[target]["measured"]]
    f1_values = [per_class[target]["f1"] for target in scored_classes]
    return {
        "sample_count": total,
        "classified_count": len(classified),
        "coverage": len(classified) / total if total else 0.0,
        "top_1_accuracy": top_1 / len(classified) if classified else 0.0,
        "top_3_accuracy": top_3 / len(classified) if classified else 0.0,
        "macro_f1": statistics.fmean(f1_values) if f1_values else 0.0,
        "scored_classes": scored_classes,
        "unsupported_class_count": len(targets) - len(scored_classes),
        "per_class": per_class,
        "confusion_matrix": confusion,
    }


def _runtime_prediction(result: Any) -> tuple[str, list[str], list[float], list[float]]:
    if result.status != "ok":
        raise DinoV3EvaluationError(f"bundle inference failed: {result.error or 'unknown error'}")
    raw = result.raw_response
    if not isinstance(raw, Mapping):
        raise DinoV3EvaluationError("bundle inference returned no prediction metadata")
    targets = raw.get("ranked_targets")
    probabilities = raw.get("probabilities")
    ranked_probabilities = raw.get("ranked_probabilities")
    if (
        not isinstance(targets, list)
        or len(targets) != len(VISUAL_IDENTITY_TARGETS)
        or any(not isinstance(item, str) for item in targets)
        or not isinstance(probabilities, list)
        or len(probabilities) != len(VISUAL_IDENTITY_TARGETS)
        or not isinstance(ranked_probabilities, list)
        or len(ranked_probabilities) != len(VISUAL_IDENTITY_TARGETS)
        or any(
            not isinstance(item, (int, float)) or not math.isfinite(float(item)) or item <= 0
            for item in probabilities
        )
        or any(
            not isinstance(item, (int, float)) or not math.isfinite(float(item)) or item <= 0
            for item in ranked_probabilities
        )
    ):
        raise DinoV3EvaluationError("bundle inference returned incomplete ranked probabilities")
    if set(targets) != set(VISUAL_IDENTITY_TARGETS):
        raise DinoV3EvaluationError("bundle inference returned an invalid target ranking")
    return (
        targets[0],
        targets,
        [float(item) for item in probabilities],
        [float(item) for item in ranked_probabilities],
    )


def _reproduction_report(
    expected_rows: list[Any],
    actual_rows: list[dict[str, Any]],
    tolerance: float,
) -> dict[str, Any]:
    expected = {
        row.get("sample_id"): row
        for row in expected_rows
        if isinstance(row, Mapping) and isinstance(row.get("sample_id"), str)
    }
    actual = {row["sample_id"]: row for row in actual_rows}
    mismatches: list[dict[str, Any]] = []
    max_delta = 0.0
    if set(expected) != set(actual):
        mismatches.append(
            {
                "kind": "sample_ids",
                "expected_count": len(expected),
                "actual_count": len(actual),
            }
        )
    for sample_id in sorted(set(expected).intersection(actual)):
        left = expected[sample_id]
        right = actual[sample_id]
        if left.get("target") != right["target"]:
            mismatches.append({"sample_id": sample_id, "kind": "target"})
        if left.get("prediction") != right["prediction"]:
            mismatches.append({"sample_id": sample_id, "kind": "prediction"})
        if left.get("top_k", [])[:3] != right["top_k"][:3]:
            mismatches.append({"sample_id": sample_id, "kind": "top_3"})
        probabilities = left.get("probabilities")
        if not isinstance(probabilities, list) or len(probabilities) != len(right["probabilities"]):
            mismatches.append({"sample_id": sample_id, "kind": "probabilities"})
            continue
        for index, (expected_value, actual_value) in enumerate(
            zip(probabilities, right["probabilities"], strict=True)
        ):
            if not isinstance(expected_value, (int, float)):
                mismatches.append({"sample_id": sample_id, "kind": "probabilities"})
                break
            delta = abs(float(expected_value) - actual_value)
            max_delta = max(max_delta, delta)
            if delta > tolerance:
                mismatches.append({"sample_id": sample_id, "kind": "probability", "index": index})
                break
    return {
        "state": "passed" if not mismatches else "failed",
        "tolerance": {"probability_abs": tolerance},
        "expected_sample_count": len(expected),
        "actual_sample_count": len(actual),
        "max_probability_abs_delta": round(max_delta, 12),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
    }


def evaluate_dinov3_identity_bundle(
    config: DinoV3EvaluationConfig,
    *,
    encoder_loader: Callable[[DinoV3IdentityBundle], Any] | None = None,
    torch_module: Any | None = None,
) -> dict[str, Any]:
    """Re-run every frozen validation crop through one exported DINOv3 bundle."""

    run_root = config.run.expanduser().resolve()
    run = _read_json(run_root / "run.json", "DINOv3 training run")
    if run.get("status") != "completed":
        raise DinoV3EvaluationError("only a completed DINOv3 run can be evaluated")
    if run.get("task") not in {
        "dinov3-frozen-linear-v1",
        "dinov3-last-two-blocks-v1",
    }:
        raise DinoV3EvaluationError("run is not a supported DINOv3 identity task")
    bundle = load_dinov3_identity_bundle(config.bundle)
    if bundle.manifest.get("run_id") != run.get("run_id"):
        raise DinoV3EvaluationError("bundle and run IDs do not match")
    checkpoint_name = run.get("checkpoints", {}).get("best")
    if not isinstance(checkpoint_name, str):
        raise DinoV3EvaluationError("completed DINOv3 run has no best checkpoint")
    checkpoint_path = run_root / checkpoint_name
    if _file_digest(checkpoint_path) != bundle.manifest.get("source_checkpoint_sha256"):
        raise DinoV3EvaluationError("bundle does not contain the recorded best checkpoint")

    campaign, validation_samples, expected_rows = _load_campaign_inputs(run, run_root)
    campaign_items = _campaign_item_index(campaign)
    missing_items = [
        sample.dataset_item_id
        for sample in validation_samples
        if sample.dataset_item_id not in campaign_items
        or not isinstance(
            campaign_items[sample.dataset_item_id].get("materialized_crop_sha256"), str
        )
        or campaign_items[sample.dataset_item_id].get("materialized_crop_sha256")
        != hashlib.sha256(sample.crop_bytes).hexdigest()
    ]
    if missing_items:
        raise DinoV3EvaluationError(
            "frozen campaign item metadata is missing for validation sample(s): "
            + ", ".join(missing_items[:10])
        )
    classifier = DinoV3IdentityClassifier(
        bundle,
        device=config.device,
        encoder_loader=encoder_loader,
        torch_module=torch_module,
    )
    actual_rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    for sample in validation_samples:
        result = classifier.classify_ppm(sample.crop_bytes)
        prediction, ranked, _probabilities, ranked_probabilities = _runtime_prediction(result)
        latencies.append(float(result.latency_ms))
        item = campaign_items.get(sample.dataset_item_id, {})
        actual_rows.append(
            {
                "sample_id": sample.dataset_item_id,
                "target": sample.target,
                "prediction": prediction,
                "top_k": ranked,
                "top_1_correct": prediction == sample.target,
                "top_3_correct": sample.target in ranked[:3],
                "top_1_probability": ranked_probabilities[0],
                "latency_ms": float(result.latency_ms),
                "source_frame_sha256": sample.source_frame_sha256,
                "source_frame_id": item.get("source_frame_id"),
                "crop_sha256": item.get("materialized_crop_sha256"),
                "recording_id": item.get("recording_id"),
                "source_lineage_group": item.get("source_lineage_group", {}),
                "card_side": item.get("card_side", "unknown"),
                "crop_policy": item.get("crop_policy"),
                "probabilities": ranked_probabilities,
            }
        )
    actual_rows.sort(key=lambda row: row["sample_id"])
    reproduction = _reproduction_report(expected_rows, actual_rows, config.probability_tolerance)
    if reproduction["state"] != "passed":
        raise DinoV3EvaluationError(
            "exported-bundle predictions do not reproduce checkpoint predictions: "
            f"{reproduction['mismatch_count']} mismatch(es)"
        )

    metrics = _classification_metrics(actual_rows)
    unsupported = {
        identity: {
            "support": 0,
            "measured": False,
            "reason": "absent from the frozen validation corpus",
        }
        for identity in VISUAL_IDENTITY_TARGETS
        if not any(row["target"] == identity for row in actual_rows)
    }
    excluded: dict[str, dict[str, Any]] = {}
    if config.provider_receipts is None:
        provider_report = None
    else:
        expected_provider_rows = {
            row["sample_id"]: row for row in actual_rows if isinstance(row.get("crop_sha256"), str)
        }
        provider_rows, provider_manifest = _provider_receipt_index(
            config.provider_receipts,
            expected=expected_provider_rows,
        )
        paired = [
            (row, provider_rows.get(row["sample_id"]))
            for row in actual_rows
            if row["sample_id"] in expected_provider_rows
        ]
        status_counts = Counter(
            "missing" if provider_row is None else str(provider_row["status"])
            for _, provider_row in paired
        )
        comparable = [
            (row, provider_row)
            for row, provider_row in paired
            if provider_row is not None and provider_row["status"] == "classified"
        ]
        provider_report = {
            "schema_version": provider_manifest["schema_version"],
            "provider": "gemini",
            "request_identity_count": len(provider_rows),
            "paired_sample_count": len(paired),
            "outcome_counts": dict(sorted(status_counts.items())),
            "classified_count": len(comparable),
            "coverage": len(comparable) / len(paired) if paired else 0.0,
            "human_target_top_1_accuracy": (
                sum(provider_row["prediction"] == row["target"] for row, provider_row in comparable)
                / len(comparable)
                if comparable
                else 0.0
            ),
            "dino_agreement": (
                sum(
                    provider_row["prediction"] == row["prediction"]
                    for row, provider_row in comparable
                )
                / len(comparable)
                if comparable
                else 0.0
            ),
            "side_bypassed_excluded_from_classifier_metrics": status_counts["side_bypassed"],
            "paired_rows": [
                {
                    "sample_id": row["sample_id"],
                    "target": row["target"],
                    "dino_prediction": row["prediction"],
                    "gemini_status": "missing" if provider_row is None else provider_row["status"],
                    "gemini_prediction": (
                        None if provider_row is None else provider_row.get("prediction")
                    ),
                    "request_identity": (
                        None if provider_row is None else provider_row.get("request_identity")
                    ),
                }
                for row, provider_row in paired
            ],
        }

    def grouped_metrics(field: str) -> dict[str, Any]:
        groups: dict[str, list[Mapping[str, Any]]] = {}
        for row in actual_rows:
            raw = row.get(field)
            if field == "source_lineage_group" and isinstance(raw, Mapping):
                values = [f"{key}:{value}" for key, value in sorted(raw.items())]
                keys = values or ["unassigned"]
            else:
                keys = [str(raw) if raw is not None else "unknown"]
            for key in keys:
                groups.setdefault(key, []).append(row)
        return {key: _classification_metrics(rows) for key, rows in sorted(groups.items())}

    slice_report = {
        "source_lineage_group": grouped_metrics("source_lineage_group"),
        "recording": grouped_metrics("recording_id"),
        "frame": grouped_metrics("source_frame_id"),
        "card_side": grouped_metrics("card_side"),
        "crop_policy": grouped_metrics("crop_policy"),
    }
    report = {
        "schema_version": DINOV3_EVALUATION_SCHEMA,
        "state": "completed",
        "run_id": run["run_id"],
        "campaign_id": campaign["campaign_id"],
        "bundle_digest": bundle.bundle_digest,
        "quality_state": bundle.manifest["quality_state"],
        "calibration": bundle.manifest["calibration"],
        "device": config.device,
        "precision": run.get("precision"),
        "dataset_version_digest": campaign["dataset"]["digest"],
        "split_version_digest": campaign["split"]["digest"],
        "crop_cache_digest": campaign["crop_inventory"]["digest"],
        "summary": {
            **{
                key: value
                for key, value in metrics.items()
                if key not in {"per_class", "confusion_matrix"}
            },
            "excluded_class_count": len(excluded),
        },
        "latency": {
            "sample_count": len(latencies),
            "load_latency_ms": round(float(classifier.load_latency_ms), 6),
            "mean_ms": round(statistics.fmean(latencies), 6),
            "median_ms": round(statistics.median(latencies), 6),
            "p95_ms": _percentile(latencies, 0.95),
            "min_ms": round(min(latencies), 6),
            "max_ms": round(max(latencies), 6),
        },
        "per_class": metrics["per_class"],
        "confusion_matrix": metrics["confusion_matrix"],
        "slice_summaries": slice_report,
        "paired_provider": provider_report,
        "face_down_errors": [
            {
                "sample_id": row["sample_id"],
                "recording_id": row["recording_id"],
                "source_frame_id": row["source_frame_id"],
                "prediction": row["prediction"],
                "top_1_probability": row["top_1_probability"],
            }
            for row in actual_rows
            if row["target"] == "FACE_DOWN" and row["prediction"] != "FACE_DOWN"
        ],
        "unsupported_class_coverage": unsupported,
        "excluded_class_coverage": excluded,
        "checkpoint_reproduction": reproduction,
        "predictions": [
            {key: value for key, value in row.items() if key != "probabilities"}
            for row in actual_rows
        ],
    }
    _write_json(config.output.expanduser().resolve(), report)
    return report


__all__ = [
    "DINOV3_EVALUATION_SCHEMA",
    "DINOV3_REPRODUCTION_TOLERANCE",
    "DinoV3EvaluationConfig",
    "DinoV3EvaluationError",
    "evaluate_dinov3_identity_bundle",
]
