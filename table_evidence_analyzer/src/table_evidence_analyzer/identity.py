"""Deterministic oracle-crop identity feasibility baselines."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .data import (
    DatasetManifest,
    LoadedCrop,
    MaterializedCropDataset,
    _ppm_tokens,
    assert_valid_dataset,
    load_artifact_index,
    load_dataset_manifest,
    load_split_manifest,
    materialize_crops,
)

IDENTITY_EVALUATION_SCHEMA = "table-analyzer-identity-evaluation/v1"
IDENTITY_FEATURE_SCHEMA = "ppm-grid-4/v1"
IDENTITY_METHODS = ("rgb-centroid", "rgb-prototype")
IdentityMethod = Literal["rgb-centroid", "rgb-prototype"]


class IdentityEvaluationError(ValueError):
    """Raised when an identity feasibility run cannot use its frozen inputs."""


@dataclass(frozen=True, slots=True)
class IdentityEvaluationConfig:
    """Inputs for one deterministic oracle-crop identity evaluation."""

    dataset: Path
    split: Path
    artifacts: Path
    output: Path
    partition: str = "validation"
    methods: tuple[IdentityMethod, ...] = IDENTITY_METHODS
    top_k: tuple[int, ...] = (1, 3, 5)
    cache_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.partition not in {"train", "validation", "test", "unassigned"}:
            raise IdentityEvaluationError(f"unknown evaluation partition: {self.partition}")
        if not self.methods:
            raise IdentityEvaluationError("at least one identity method is required")
        if any(method not in IDENTITY_METHODS for method in self.methods):
            raise IdentityEvaluationError("unknown identity method")
        if len(set(self.methods)) != len(self.methods):
            raise IdentityEvaluationError("identity methods must be unique")
        if not self.top_k or any(k <= 0 for k in self.top_k):
            raise IdentityEvaluationError("top_k values must be positive")
        if tuple(sorted(set(self.top_k))) != self.top_k:
            raise IdentityEvaluationError("top_k values must be sorted and unique")


@dataclass(frozen=True, slots=True)
class _IdentityModel:
    method: IdentityMethod
    labels: tuple[str, ...]
    centroids: dict[str, tuple[float, ...]]
    prototypes: dict[str, tuple[tuple[float, ...], ...]]
    training_sample_count: int


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _ppm_feature(raw: bytes) -> tuple[float, ...]:
    """Return mean RGB plus a 4x4 grid of mean RGB values from a PPM crop."""

    width, height, _max_value, offset = _ppm_tokens(raw)
    if width < 4 or height < 4:
        raise IdentityEvaluationError("oracle crop must be at least 4x4 pixels")
    pixels = memoryview(raw)[offset:]
    features: list[float] = []
    for grid_y in range(4):
        y_min = grid_y * height // 4
        y_max = (grid_y + 1) * height // 4
        for grid_x in range(4):
            x_min = grid_x * width // 4
            x_max = (grid_x + 1) * width // 4
            count = (x_max - x_min) * (y_max - y_min)
            totals = [0, 0, 0]
            for y in range(y_min, y_max):
                row = (y * width + x_min) * 3
                for _x in range(x_min, x_max):
                    totals[0] += pixels[row]
                    totals[1] += pixels[row + 1]
                    totals[2] += pixels[row + 2]
                    row += 3
            features.extend(total / count for total in totals)
    return tuple(features)


def _distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum((a - b) ** 2 for a, b in zip(left, right, strict=True))


def _fit(samples: list[LoadedCrop], method: IdentityMethod) -> _IdentityModel:
    if not samples:
        raise IdentityEvaluationError("identity evaluation requires at least one train crop")
    by_label: dict[str, list[tuple[float, ...]]] = defaultdict(list)
    for sample in samples:
        by_label[sample.target].append(_ppm_feature(sample.crop_bytes))
    labels = tuple(sorted(by_label))
    if method == "rgb-centroid":
        centroids = {
            label: tuple(
                sum(point[index] for point in points) / len(points)
                for index in range(len(points[0]))
            )
            for label, points in by_label.items()
        }
        return _IdentityModel(method, labels, centroids, {}, len(samples))
    return _IdentityModel(
        method,
        labels,
        {},
        {label: tuple(points) for label, points in by_label.items()},
        len(samples),
    )


def _rank(model: _IdentityModel, feature: tuple[float, ...]) -> list[str]:
    if model.method == "rgb-centroid":
        distances = {label: _distance(feature, point) for label, point in model.centroids.items()}
    else:
        distances = {
            label: min(_distance(feature, point) for point in points)
            for label, points in model.prototypes.items()
        }
    return [
        label
        for label, _distance_value in sorted(distances.items(), key=lambda item: (item[1], item[0]))
    ]


def _accuracy_by_tag(
    predictions: list[dict[str, Any]], top_k: tuple[int, ...]
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for prediction in predictions:
        tags = prediction["quality_tags"] or ["__untagged__"]
        for tag in tags:
            grouped[tag].append(prediction)
    result: dict[str, dict[str, Any]] = {}
    for tag in sorted(grouped):
        rows = grouped[tag]
        result[tag] = {
            "sample_count": len(rows),
            "top_1_accuracy": sum(row["prediction"] == row["target"] for row in rows) / len(rows),
            "top_k_accuracy": {
                str(k): sum(row["target"] in row["top_k"][:k] for row in rows) / len(rows)
                for k in top_k
            },
        }
    return result


def _method_report(
    model: _IdentityModel,
    samples: list[LoadedCrop],
    dataset: DatasetManifest,
    top_k: tuple[int, ...],
) -> dict[str, Any]:
    entries = {entry.dataset_item_id: entry for entry in dataset.entries}
    predictions: list[dict[str, Any]] = []
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for sample in samples:
        entry = entries[sample.dataset_item_id]
        ranked = _rank(model, _ppm_feature(sample.crop_bytes))
        prediction = ranked[0]
        confusion[sample.target][prediction] += 1
        predictions.append(
            {
                "sample_id": sample.dataset_item_id,
                "target": sample.target,
                "prediction": prediction,
                "top_k": ranked,
                "quality_tags": list(entry.quality_tags),
                "source_frame_sha256": sample.source_frame_sha256,
            }
        )
    predictions.sort(key=lambda row: row["sample_id"])
    count = len(predictions)
    return {
        "method": model.method,
        "feature_schema": IDENTITY_FEATURE_SCHEMA,
        "class_count": len(model.labels),
        "classes": list(model.labels),
        "training_sample_count": model.training_sample_count,
        "sample_count": count,
        "top_1_accuracy": sum(row["prediction"] == row["target"] for row in predictions) / count
        if count
        else 0.0,
        "top_k_accuracy": {
            str(k): sum(row["target"] in row["top_k"][:k] for row in predictions) / count
            if count
            else 0.0
            for k in top_k
        },
        "confusion_matrix": {
            target: dict(sorted(predicted.items()))
            for target, predicted in sorted(confusion.items())
        },
        "by_quality_tag": _accuracy_by_tag(predictions, top_k),
        "predictions": predictions,
    }


def evaluate_identity_crops(config: IdentityEvaluationConfig) -> dict[str, Any]:
    """Evaluate local identity baselines on one frozen dataset partition."""

    dataset = load_dataset_manifest(config.dataset)
    split = load_split_manifest(config.split)
    artifacts = load_artifact_index(config.artifacts)
    assert_valid_dataset(dataset, split=split, artifacts=artifacts)
    cache_dir = config.cache_dir or config.output.parent / f".{config.output.stem}-crop-cache"
    cache = materialize_crops(dataset, split, artifacts, cache_dir)
    train_samples = list(MaterializedCropDataset(cache, partition="train"))
    evaluation_samples = list(MaterializedCropDataset(cache, partition=config.partition))
    if not evaluation_samples:
        raise IdentityEvaluationError(f"evaluation partition is empty: {config.partition}")
    models = {method: _fit(train_samples, method) for method in config.methods}
    report = {
        "schema_version": IDENTITY_EVALUATION_SCHEMA,
        "task": "oracle_crop_identity_feasibility",
        "dataset_version_digest": dataset.digest,
        "split_version_digest": split.digest,
        "crop_cache_digest": cache.digest,
        "partition": config.partition,
        "feature_schema": IDENTITY_FEATURE_SCHEMA,
        "top_k": list(config.top_k),
        "methods": {
            method: _method_report(model, evaluation_samples, dataset, config.top_k)
            for method, model in models.items()
        },
        "selection_note": (
            "This report measures oracle-crop identity feasibility. It does not select a "
            "production "
            "model and does not measure visible-card localization."
        ),
    }
    _write_json(config.output, report)
    return report


__all__ = [
    "IDENTITY_EVALUATION_SCHEMA",
    "IDENTITY_FEATURE_SCHEMA",
    "IDENTITY_METHODS",
    "IdentityEvaluationConfig",
    "IdentityEvaluationError",
    "evaluate_identity_crops",
]
