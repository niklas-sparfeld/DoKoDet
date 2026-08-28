"""Portable, training-free capability bundle export and inference."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .table_observation import IdentityCandidate

BUNDLE_SCHEMA = "table-analyzer-bundle/v1"


def _feature(raw: bytes) -> tuple[float, float, float]:
    if not raw.startswith(b"P6\n"):
        raise ValueError("bundle classifier expects a binary PPM crop")
    header_end = raw.find(b"\n255\n")
    if header_end < 0:
        raise ValueError("invalid PPM crop header")
    pixels = raw[header_end + len(b"\n255\n") :]
    if not pixels or len(pixels) % 3:
        raise ValueError("invalid PPM pixel payload")
    return tuple(sum(pixels[i::3]) / (len(pixels) // 3) for i in range(3))  # type: ignore[return-value]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class CapabilityBundle:
    root: Path
    manifest: dict[str, Any]
    centroids: dict[str, list[float]]

    def classify(self, image: str | Path) -> list[IdentityCandidate]:
        point = _feature(Path(image).read_bytes())
        distances = {
            label: sum((point[i] - centroid[i]) ** 2 for i in range(3))
            for label, centroid in self.centroids.items()
        }
        weights = {label: math.exp(-distance) for label, distance in distances.items()}
        total = sum(weights.values())
        return [
            IdentityCandidate(card=label, probability=weight / total)
            for label, weight in sorted(weights.items(), key=lambda pair: pair[1], reverse=True)
        ]


def export_bundle(run_dir: str | Path, output: str | Path) -> Path:
    run_root = Path(run_dir)
    run = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    model = {"schema_version": "rgb-nearest-centroid-v1", "centroids": run["centroids"]}
    model_path = destination / "model.json"
    model_path.write_text(json.dumps(model, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": BUNDLE_SCHEMA,
        "capabilities": ["identity_candidates"],
        "calibration": "uncalibrated",
        "card_set_version": "doko-german-suited-v1",
        "run_id": run["run_id"],
        "dataset_version_digest": run["dataset_version_digest"],
        "split_version_digest": run["split_version_digest"],
        "model_file": model_path.name,
        "model_sha256": _digest(model_path),
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


def load_bundle(path: str | Path) -> CapabilityBundle:
    root = Path(path)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != BUNDLE_SCHEMA:
        raise ValueError("unsupported analyzer bundle format")
    if manifest.get("capabilities") != ["identity_candidates"]:
        raise ValueError("bundle must declare only identity_candidates")
    model_path = root / str(manifest.get("model_file", ""))
    if not model_path.is_file() or _digest(model_path) != manifest.get("model_sha256"):
        raise ValueError("analyzer bundle model hash does not match its manifest")
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if model.get("schema_version") != "rgb-nearest-centroid-v1":
        raise ValueError("unsupported analyzer model format")
    return CapabilityBundle(root, manifest, model["centroids"])


__all__ = ["BUNDLE_SCHEMA", "CapabilityBundle", "export_bundle", "load_bundle"]
