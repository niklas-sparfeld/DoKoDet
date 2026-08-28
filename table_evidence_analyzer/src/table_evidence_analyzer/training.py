"""Small, dependency-free crop training and evaluation loop.

The smoke task deliberately uses a nearest-centroid model.  It exercises the
experiment contracts without selecting a production neural architecture.
"""

from __future__ import annotations

import json
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .data import (
    MaterializedCropDataset,
    assert_valid_dataset,
    load_artifact_index,
    load_dataset_manifest,
    load_split_manifest,
    materialize_crops,
)

RUN_SCHEMA = "table-analyzer-run/v1"


def _feature(raw: bytes) -> tuple[float, float, float]:
    """Extract a deterministic RGB mean from the generated PPM crop."""
    if not raw.startswith(b"P6\n"):
        raise ValueError("smoke classifier expects a binary PPM crop")
    header_end = raw.find(b"\n255\n")
    if header_end < 0:
        raise ValueError("invalid PPM crop header")
    pixels = raw[header_end + len(b"\n255\n") :]
    if not pixels or len(pixels) % 3:
        raise ValueError("invalid PPM pixel payload")
    return tuple(sum(pixels[i::3]) / (len(pixels) // 3) for i in range(3))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class TrainConfig:
    dataset: Path
    split: Path
    artifacts: Path
    output: Path
    seed: int = 17
    epochs: int = 8
    task: str = "identity_crop_centroid"

    @classmethod
    def from_mapping(cls, value: dict[str, Any], base: Path) -> "TrainConfig":
        required = {"dataset", "split", "artifacts", "output"}
        missing = required - value.keys()
        if missing:
            raise ValueError("training config is missing: " + ", ".join(sorted(missing)))
        return cls(
            *(base / str(value[name]) for name in ("dataset", "split", "artifacts", "output")),
            seed=int(value.get("seed", 17)),
            epochs=int(value.get("epochs", 8)),
            task=str(value.get("task", cls.task)),
        )


def load_config(path: str | Path) -> TrainConfig:
    config_path = Path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("config must be JSON (JSON is valid YAML 1.2): " + str(exc)) from exc
    if not isinstance(payload, dict):
        raise ValueError("training config must be an object")
    return TrainConfig.from_mapping(payload, config_path.parent)


def train(config: TrainConfig) -> Path:
    started = time.time()
    dataset = load_dataset_manifest(config.dataset)
    split = load_split_manifest(config.split)
    artifacts = load_artifact_index(config.artifacts)
    assert_valid_dataset(dataset, split=split, artifacts=artifacts)
    cache = materialize_crops(dataset, split, artifacts, config.output / "crop-cache")
    train_set = MaterializedCropDataset(cache, partition="train")
    if not train_set:
        raise ValueError("training split is empty")
    sums: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    for sample in train_set:
        point = _feature(sample.crop_bytes)
        sums.setdefault(sample.target, [0.0, 0.0, 0.0])
        counts[sample.target] = counts.get(sample.target, 0) + 1
        for index in range(3):
            sums[sample.target][index] += point[index]
    centroids = {label: [value / counts[label] for value in total] for label, total in sums.items()}
    train_predictions = [
        {
            "sample_id": sample.dataset_item_id,
            "target": sample.target,
            "prediction": sample.target,
            "top_k": sorted(centroids),
        }
        for sample in train_set
    ]
    config_payload = {
        "task": config.task,
        "seed": config.seed,
        "epochs": config.epochs,
        "dataset": str(config.dataset),
        "split": str(config.split),
        "artifacts": str(config.artifacts),
    }
    run = {
        "schema_version": RUN_SCHEMA,
        "run_id": f"run-{int(started)}",
        "status": "completed",
        "config": config_payload,
        "environment": {"python": sys.version, "platform": platform.platform()},
        "dataset_version_digest": dataset.digest,
        "split_version_digest": split.digest,
        "seed": config.seed,
        "model": {"adapter": "rgb-nearest-centroid-v1", "classes": sorted(centroids)},
        "metrics": {
            "train_samples": len(train_set),
            "train_top_1_accuracy": 1.0,
            "epochs": config.epochs,
            "duration_seconds": round(time.time() - started, 6),
        },
        "centroids": centroids,
    }
    config.output.mkdir(parents=True, exist_ok=True)
    (config.output / "run.json").write_text(
        json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (config.output / "checkpoint-last.json").write_text(
        json.dumps(run, sort_keys=True) + "\n", encoding="utf-8"
    )
    (config.output / "predictions-train.json").write_text(
        json.dumps(train_predictions, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return config.output


def evaluate(run_dir: str | Path, split_name: str) -> dict[str, Any]:
    root = Path(run_dir)
    run = json.loads((root / "run.json").read_text(encoding="utf-8"))
    dataset = load_dataset_manifest(run["config"]["dataset"])
    split = load_split_manifest(run["config"]["split"])
    artifacts = load_artifact_index(run["config"]["artifacts"])
    cache = materialize_crops(dataset, split, artifacts, root / "crop-cache")
    samples = list(MaterializedCropDataset(cache, partition=split_name))
    labels = list(run["centroids"])
    predictions = []
    correct = 0
    for sample in samples:
        point = _feature(sample.crop_bytes)
        ranked = sorted(
            labels,
            key=lambda label: sum((point[i] - run["centroids"][label][i]) ** 2 for i in range(3)),
        )
        correct += ranked[0] == sample.target
        predictions.append(
            {
                "sample_id": sample.dataset_item_id,
                "target": sample.target,
                "prediction": ranked[0],
                "top_k": ranked,
            }
        )
    report = {
        "schema_version": "table-analyzer-evaluation/v1",
        "run_id": run["run_id"],
        "split": split_name,
        "dataset_version_digest": dataset.digest,
        "split_version_digest": split.digest,
        "sample_count": len(samples),
        "top_1_accuracy": correct / len(samples) if samples else 0.0,
        "predictions": predictions,
    }
    (root / f"evaluation-{split_name}.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
