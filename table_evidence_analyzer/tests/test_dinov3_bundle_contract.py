from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from table_evidence_analyzer.dinov3_bundle import (
    DINOV3_HEAD_SCHEMA,
    DinoV3BundleError,
    load_dinov3_identity_bundle,
)
from table_evidence_analyzer.local_identity import (
    DINOV3_BUNDLE_SCHEMA,
    DINOV3_LICENSE_ID,
    build_dinov3_identity_config,
    materialize_dinov3_weights,
)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_bundle(root: Path, *, input_size: int) -> None:
    root.mkdir()
    (root / "config.json").write_text(
        json.dumps({"model_type": "dinov3", "hidden_size": 4}), encoding="utf-8"
    )
    (root / "preprocessor_config.json").write_text(
        json.dumps({"do_resize": True, "size": {"height": 224, "width": 224}}),
        encoding="utf-8",
    )
    (root / "model.safetensors").write_bytes(b"locally materialized encoder weights")
    license_record = {
        "license_id": DINOV3_LICENSE_ID,
        "name": "DINOv3 License",
        "version": "2025-08-19",
        "url": "https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md",
        "accepted": True,
        "accepted_at_utc": "2026-09-01T12:00:00Z",
    }
    weights = materialize_dinov3_weights(
        root, model_revision="revision-contract-test", license_record=license_record
    )
    identity = build_dinov3_identity_config(
        weights, license_record=license_record, input_size=input_size
    )
    (root / "target-map.json").write_text(
        json.dumps(identity.to_mapping()["target"], sort_keys=True), encoding="utf-8"
    )
    (root / "head.pt").write_bytes(b"model-free head fixture")
    (root / "encoder-state.pt").write_bytes(b"model-free encoder fixture")
    files = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.iterdir(), key=lambda item: item.name)
    }
    manifest = {
        "schema_version": DINOV3_BUNDLE_SCHEMA,
        "component": "table-evidence-analyzer",
        "capability": "visual-card-identity",
        "capabilities": ["identity_candidates"],
        "quality_state": "unusable_smoke_artifact",
        "calibration": "uncalibrated",
        "identity": identity.to_mapping(),
        "pretrained_provenance": {
            "model_id": identity.weights.model_id,
            "model_revision": identity.weights.model_revision,
            "weight_file": identity.weights.weight_file,
            "weight_sha256": identity.weights.weight_sha256,
        },
        "recipe_digest": identity.recipe_digest,
        "transform_digest": identity.transform_digest,
        "target_map_file": "target-map.json",
        "target_map_sha256": files["target-map.json"],
        "head": {
            "schema_version": DINOV3_HEAD_SCHEMA,
            "adapter": "dinov3-frozen-linear-v1",
            "file": "head.pt",
            "sha256": files["head.pt"],
            "hidden_size": 4,
            "class_count": 25,
            "feature_layout": "cls",
            "input_size": input_size,
            "transform_digest": identity.transform_digest,
        },
        "encoder": {
            "file": "encoder-state.pt",
            "sha256": files["encoder-state.pt"],
            "initialization": "pretrained",
            "training_mode": "frozen",
            "trainable_parameter_names": [],
        },
        "inference_recipe": {
            "feature_layout": "cls",
            "input_size": input_size,
            "transform_digest": identity.transform_digest,
            "class_count": 25,
        },
        "training_recipe": {
            "task_adapter": "dinov3-frozen-linear-v1",
            "identity_digest": identity.identity_digest,
            "feature_layout": identity.recipe["feature_layout"],
            "encoder_training": "frozen",
        },
        "run_id": "fixture-run",
        "source_checkpoint_sha256": "a" * 64,
        "files": files,
    }
    manifest["bundle_digest"] = _digest(manifest)
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize("input_size", [224, 384, 448])
def test_model_free_bundle_loads_each_explicit_input_resolution(
    tmp_path: Path, input_size: int
) -> None:
    bundle_path = tmp_path / "bundle"
    _write_bundle(bundle_path, input_size=input_size)

    bundle = load_dinov3_identity_bundle(bundle_path)

    assert bundle.identity.input_size == input_size
    assert bundle.manifest["head"]["transform_digest"] == bundle.identity.transform_digest


def test_bundle_rejects_head_transform_that_differs_from_identity(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle"
    _write_bundle(bundle_path, input_size=384)
    manifest_path = bundle_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["head"]["transform_digest"] = "0" * 64
    manifest["bundle_digest"] = _digest(
        {key: value for key, value in manifest.items() if key != "bundle_digest"}
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    with pytest.raises(DinoV3BundleError, match="head manifest is invalid"):
        load_dinov3_identity_bundle(bundle_path)
