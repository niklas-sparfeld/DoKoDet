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
from .local_identity import FACE_DOWN_TARGET, VISUAL_IDENTITY_TARGETS

DINOV3_EVALUATION_SCHEMA = "dinov3-identity-bundle-evaluation/v1"
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
    device: str = "cpu"
    probability_tolerance: float = DINOV3_REPRODUCTION_TOLERANCE

    def __post_init__(self) -> None:
        if self.device not in {"cpu", "mps", "cuda"}:
            raise DinoV3EvaluationError(f"unsupported DINOv3 evaluation device: {self.device}")
        if (
            not math.isfinite(self.probability_tolerance)
            or self.probability_tolerance <= 0
        ):
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
        if not isinstance(probabilities, list) or len(probabilities) != len(
            right["probabilities"]
        ):
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
                mismatches.append(
                    {"sample_id": sample_id, "kind": "probability", "index": index}
                )
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
    if run.get("task") != "dinov3-frozen-linear-v1":
        raise DinoV3EvaluationError("run is not the frozen DINOv3 identity task")
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
    classifier = DinoV3IdentityClassifier(
        bundle,
        device=config.device,
        encoder_loader=encoder_loader,
        torch_module=torch_module,
    )
    actual_rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    confusion: dict[str, Counter[str]] = {}
    for sample in validation_samples:
        result = classifier.classify_ppm(sample.crop_bytes)
        prediction, ranked, _probabilities, ranked_probabilities = _runtime_prediction(result)
        latencies.append(float(result.latency_ms))
        confusion.setdefault(sample.target, Counter())[prediction] += 1
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

    labels = tuple(sorted({row["target"] for row in actual_rows}))
    sample_count = len(actual_rows)
    top_1 = sum(row["top_1_correct"] for row in actual_rows) / sample_count
    top_3 = sum(row["top_3_correct"] for row in actual_rows) / sample_count
    per_class: dict[str, dict[str, Any]] = {}
    f1_values: list[float] = []
    for label in labels:
        true_positive = sum(
            row["target"] == label and row["prediction"] == label for row in actual_rows
        )
        false_positive = sum(
            row["target"] != label and row["prediction"] == label for row in actual_rows
        )
        false_negative = sum(
            row["target"] == label and row["prediction"] != label for row in actual_rows
        )
        f1 = _f1(true_positive, false_positive, false_negative)
        f1_values.append(f1)
        per_class[label] = {
            "support": sum(row["target"] == label for row in actual_rows),
            "top_1_correct": true_positive,
            "top_1_accuracy": true_positive
            / sum(row["target"] == label for row in actual_rows),
            "precision": true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0,
            "recall": true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0,
            "f1": f1,
        }
    unsupported = {
        identity: {
            "support": 0,
            "measured": False,
            "reason": "absent from the frozen train and validation corpus",
        }
        for identity in campaign.get("unsupported_identities", [])
    }
    unsupported.pop(FACE_DOWN_TARGET, None)
    excluded = {
        FACE_DOWN_TARGET: {
            "support": 0,
            "measured": False,
            "reason": "intentionally excluded from the first campaign",
        }
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
            "sample_count": sample_count,
            "top_1_accuracy": top_1,
            "top_3_accuracy": top_3,
            "macro_f1": statistics.fmean(f1_values) if f1_values else 0.0,
            "scored_classes": list(labels),
            "unsupported_class_count": len(unsupported),
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
        "per_class": per_class,
        "confusion_matrix": {
            target: dict(sorted(confusion.get(target, Counter()).items()))
            for target in labels
        },
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
