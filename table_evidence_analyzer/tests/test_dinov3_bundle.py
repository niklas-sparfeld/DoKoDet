from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from table_evidence_analyzer.card_classification import CardIdentityClassifier
from table_evidence_analyzer.data import build_smoke_fixture
from table_evidence_analyzer.dinov3_bundle import (
    DINOV3_HEAD_SCHEMA,
    DinoV3BundleError,
    export_dinov3_identity_bundle,
    load_dinov3_identity_bundle,
)
from table_evidence_analyzer.dinov3_inference import (
    DinoV3IdentityClassifier,
    DinoV3InferenceError,
)
from table_evidence_analyzer.dinov3_training import DinoV3TrainConfig, train_dinov3_identity
from table_evidence_analyzer.local_identity import (
    DINOV3_LICENSE_ID,
    build_dinov3_identity_config,
    materialize_dinov3_weights,
)

torch = pytest.importorskip("torch")


def _identity_config(root: Path):
    weights_root = root / "weights"
    weights_root.mkdir()
    (weights_root / "config.json").write_text(
        json.dumps({"model_type": "dinov3", "hidden_size": 4}), encoding="utf-8"
    )
    (weights_root / "preprocessor_config.json").write_text(
        json.dumps({"do_resize": True, "size": {"height": 224, "width": 224}}), encoding="utf-8"
    )
    (weights_root / "model.safetensors").write_bytes(b"generated local DINOv3 bundle double")
    license_record = {
        "license_id": DINOV3_LICENSE_ID,
        "name": "DINOv3 License",
        "version": "2025-08-19",
        "url": "https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md",
        "accepted": True,
        "accepted_at_utc": "2026-09-01T12:00:00Z",
    }
    weights = materialize_dinov3_weights(
        weights_root,
        model_revision="revision-bundle-abc123",
        license_record=license_record,
    )
    return build_dinov3_identity_config(weights, license_record=license_record)


class _FakeEncoder(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.config = SimpleNamespace(hidden_size=4)

    def forward(self, *, pixel_values):
        pooled = pixel_values.mean(dim=(2, 3))
        return SimpleNamespace(pooler_output=torch.cat((pooled, pooled[:, :1]), dim=1))


def _factory(_identity):
    return _FakeEncoder()


def _train_run(tmp_path: Path):
    fixture = build_smoke_fixture(tmp_path / "fixture")
    identity = _identity_config(tmp_path)
    run = tmp_path / "run"
    train_dinov3_identity(
        DinoV3TrainConfig(
            dataset=fixture.dataset_path,
            split=fixture.split_path,
            artifacts=fixture.artifact_index_path,
            identity_config=identity,
            output=run,
            seed=17,
            epochs=4,
            batch_size=1,
            learning_rate=0.5,
        ),
        encoder_factory=_factory,
    )
    return fixture, identity, run


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _rewrite_manifest(bundle_path: Path) -> None:
    manifest_path = bundle_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["bundle_digest"] = _digest(
        {key: value for key, value in manifest.items() if key != "bundle_digest"}
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")


def test_exported_bundle_is_self_contained_and_runtime_classifier_is_deterministic(
    tmp_path: Path,
) -> None:
    fixture, identity, run = _train_run(tmp_path)

    bundle_path = export_dinov3_identity_bundle(
        run,
        tmp_path / "bundle",
        identity_config=identity,
    )
    bundle = load_dinov3_identity_bundle(bundle_path)
    assert bundle.manifest["quality_state"] == "unusable_smoke_artifact"
    assert bundle.manifest["calibration"] == "uncalibrated"
    assert bundle.manifest["capabilities"] == ["identity_candidates"]
    assert bundle.manifest["head"]["schema_version"] == DINOV3_HEAD_SCHEMA
    assert {
        "config.json",
        "model.safetensors",
        "preprocessor_config.json",
        "head.pt",
        "target-map.json",
    } == set(bundle.manifest["files"])

    classifier = DinoV3IdentityClassifier(
        bundle_path,
        device="cpu",
        encoder_loader=lambda _bundle: _FakeEncoder(),
    )
    assert isinstance(classifier, CardIdentityClassifier)
    first = classifier.classify_ppm(fixture.frame_paths[0].read_bytes())
    second = classifier.classify_ppm(fixture.frame_paths[0].read_bytes())

    assert first.status == "ok"
    assert first.candidates == second.candidates
    assert len(first.candidates) == 24
    assert sum(candidate.probability for candidate in first.candidates) == pytest.approx(1.0)
    assert [candidate.card for candidate in first.candidates] == sorted(
        (candidate.card for candidate in first.candidates),
        key=lambda card: (
            -next(candidate.probability for candidate in first.candidates if candidate.card == card)
        ),
    )
    assert first.raw_response["device"] == "cpu"
    assert first.raw_response["bundle_digest"] == bundle.manifest["bundle_digest"]


def test_corrupt_weight_is_rejected_before_encoder_construction(tmp_path: Path) -> None:
    _fixture, identity, run = _train_run(tmp_path)
    bundle_path = export_dinov3_identity_bundle(run, tmp_path / "bundle", identity_config=identity)
    (bundle_path / "model.safetensors").write_bytes(b"corrupt")
    constructed = False

    def loader(_bundle):
        nonlocal constructed
        constructed = True
        return _FakeEncoder()

    with pytest.raises(DinoV3BundleError, match="hash"):
        DinoV3IdentityClassifier(bundle_path, encoder_loader=loader)
    assert constructed is False


def test_target_map_mismatch_is_explicit_even_when_file_digests_are_rewritten(
    tmp_path: Path,
) -> None:
    _fixture, identity, run = _train_run(tmp_path)
    bundle_path = export_dinov3_identity_bundle(run, tmp_path / "bundle", identity_config=identity)
    target_path = bundle_path / "target-map.json"
    target = json.loads(target_path.read_text(encoding="utf-8"))
    target["class_map"]["0"], target["class_map"]["1"] = (
        target["class_map"]["1"],
        target["class_map"]["0"],
    )
    target_path.write_text(json.dumps(target, sort_keys=True), encoding="utf-8")
    manifest_path = bundle_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["target-map.json"] = hashlib.sha256(target_path.read_bytes()).hexdigest()
    manifest["target_map_sha256"] = manifest["files"]["target-map.json"]
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    _rewrite_manifest(bundle_path)

    with pytest.raises(DinoV3BundleError, match="target map"):
        load_dinov3_identity_bundle(bundle_path)


def test_invalid_crop_raises_and_encoder_failure_returns_unavailable(tmp_path: Path) -> None:
    _fixture, identity, run = _train_run(tmp_path)
    bundle_path = export_dinov3_identity_bundle(run, tmp_path / "bundle", identity_config=identity)
    classifier = DinoV3IdentityClassifier(
        bundle_path,
        encoder_loader=lambda _bundle: _FakeEncoder(),
    )

    with pytest.raises(DinoV3InferenceError, match="valid binary PPM"):
        classifier.classify_ppm(b"not a crop")

    class BrokenEncoder(_FakeEncoder):
        def forward(self, *, pixel_values):
            del pixel_values
            raise RuntimeError("generated inference failure")

    broken = DinoV3IdentityClassifier(
        bundle_path,
        encoder_loader=lambda _bundle: BrokenEncoder(),
    )
    result = broken.classify_ppm(_fixture.frame_paths[0].read_bytes())
    assert result.status == "unavailable"
    assert result.candidates == ()
    assert result.error == "DINOv3 inference failed: generated inference failure"


@pytest.mark.skipif(not torch.backends.mps.is_available(), reason="MPS is not available")
def test_runtime_classifier_runs_on_mps_without_fallback(tmp_path: Path) -> None:
    fixture, identity, run = _train_run(tmp_path)
    bundle_path = export_dinov3_identity_bundle(run, tmp_path / "bundle", identity_config=identity)
    classifier = DinoV3IdentityClassifier(
        bundle_path,
        device="mps",
        encoder_loader=lambda _bundle: _FakeEncoder(),
    )

    result = classifier.classify_ppm(fixture.frame_paths[0].read_bytes())

    assert result.status == "ok"
    assert result.raw_response["device"] == "mps"
