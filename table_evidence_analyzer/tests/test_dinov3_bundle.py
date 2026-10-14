from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from table_evidence_analyzer.card_classification import CardIdentityClassifier
from table_evidence_analyzer.data import (
    build_smoke_fixture,
    load_artifact_index,
    load_dataset_manifest,
    load_split_manifest,
    materialize_crops,
)
from table_evidence_analyzer.dinov3_bundle import (
    DINOV3_HEAD_SCHEMA,
    DinoV3BundleError,
    export_dinov3_identity_bundle,
    load_dinov3_identity_bundle,
)
from table_evidence_analyzer.dinov3_calibration import (
    CALIBRATION_VIEW_SCHEMA,
    fit_dinov3_confidence_calibration,
)
from table_evidence_analyzer.dinov3_evaluation import (
    DinoV3EvaluationConfig,
    DinoV3EvaluationError,
    _provider_receipt_index,
    evaluate_dinov3_identity_bundle,
)
from table_evidence_analyzer.dinov3_inference import (
    DinoV3IdentityClassifier,
    DinoV3InferenceError,
)
from table_evidence_analyzer.dinov3_training import (
    DinoV3TrainConfig,
    DinoV3TrainingInterrupted,
    train_dinov3_identity,
)
from table_evidence_analyzer.local_identity import (
    DINOV3_LICENSE_ID,
    VISUAL_IDENTITY_TARGETS,
    build_dinov3_identity_config,
    materialize_dinov3_weights,
)

torch = pytest.importorskip("torch")


def _identity_config(root: Path, *, input_size: int = 224, feature_layout: str = "cls"):
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
    return build_dinov3_identity_config(
        weights,
        license_record=license_record,
        input_size=input_size,
        feature_layout=feature_layout,
    )


class _FakeEncoder(torch.nn.Module):
    def __init__(self, input_size: int | None = None) -> None:
        super().__init__()
        self.config = SimpleNamespace(hidden_size=4, patch_size=16, num_register_tokens=2)
        self.input_size = input_size
        self.scale = torch.nn.Parameter(torch.ones(()))
        self.model = torch.nn.Module()
        self.model.layer = torch.nn.ModuleList([torch.nn.Linear(4, 4) for _ in range(4)])
        self.norm = torch.nn.LayerNorm(4)

    def forward(self, *, pixel_values):
        if self.input_size is not None:
            assert tuple(pixel_values.shape[-2:]) == (self.input_size, self.input_size)
        pooled = pixel_values.mean(dim=(2, 3)) * self.scale
        cls = torch.cat((pooled, pooled[:, :1]), dim=1)
        patch_count = (pixel_values.shape[-1] // self.config.patch_size) ** 2
        patches = cls.unsqueeze(1).expand(-1, patch_count, -1)
        registers = torch.full(
            (len(pooled), self.config.num_register_tokens, 4), 99.0, device=pooled.device
        )
        tokens = torch.cat((cls.unsqueeze(1), registers, patches), dim=1)
        for block in self.model.layer:
            tokens = block(tokens)
        tokens = self.norm(tokens)
        return SimpleNamespace(pooler_output=tokens[:, 0, :], last_hidden_state=tokens)


def _factory(_identity):
    identity = getattr(_identity, "identity", _identity)
    return _FakeEncoder(identity.input_size)


def _train_run(
    tmp_path: Path,
    *,
    input_size: int = 224,
    feature_layout: str = "cls",
    encoder_training: str = "frozen",
):
    fixture = build_smoke_fixture(tmp_path / "fixture")
    identity = _identity_config(tmp_path, input_size=input_size, feature_layout=feature_layout)
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
            encoder_training=encoder_training,
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


@pytest.mark.parametrize("input_size", [224, 384, 448])
def test_exported_bundle_is_self_contained_and_runtime_classifier_is_deterministic(
    tmp_path: Path, input_size: int
) -> None:
    fixture, identity, run = _train_run(tmp_path, input_size=input_size)

    bundle_path = export_dinov3_identity_bundle(
        run,
        tmp_path / "bundle",
        identity_config=identity,
    )
    bundle = load_dinov3_identity_bundle(bundle_path)
    assert bundle.manifest["quality_state"] == "unusable_smoke_artifact"
    assert bundle.manifest["calibration"]["temperature"] == 1.0
    assert bundle.manifest["calibration"]["score_schema_version"] == "dinov3-visual-score/v1"
    assert bundle.manifest["capabilities"] == ["identity_candidates"]
    assert bundle.manifest["head"]["schema_version"] == DINOV3_HEAD_SCHEMA
    assert bundle.manifest["head"]["class_count"] == 25
    assert bundle.identity.input_size == input_size
    assert bundle.manifest["recipe_digest"] == identity.recipe_digest
    assert bundle.manifest["transform_digest"] == identity.transform_digest
    assert bundle.manifest["head"]["input_size"] == input_size
    assert {
        "config.json",
        "model.safetensors",
        "preprocessor_config.json",
        "head.pt",
        "calibration.json",
        "encoder-state.pt",
        "target-map.json",
    } == set(bundle.manifest["files"])

    classifier = DinoV3IdentityClassifier(
        bundle_path,
        device="cpu",
        encoder_loader=lambda _bundle: _FakeEncoder(input_size),
    )
    assert isinstance(classifier, CardIdentityClassifier)
    first = classifier.classify_ppm(fixture.frame_paths[0].read_bytes())
    second = classifier.classify_ppm(fixture.frame_paths[0].read_bytes())

    assert first.status == "ok"
    assert first.candidates == second.candidates
    assert len(first.candidates) == 24
    assert 0 < sum(candidate.probability for candidate in first.candidates) < 1.0
    assert [candidate.card for candidate in first.candidates] == sorted(
        (candidate.card for candidate in first.candidates),
        key=lambda card: (
            -next(candidate.probability for candidate in first.candidates if candidate.card == card)
        ),
    )
    assert first.raw_response["device"] == "cpu"
    assert first.raw_response["bundle_digest"] == bundle.manifest["bundle_digest"]
    assert first.raw_response["ranked_targets"][0] == first.candidates[0].card
    assert first.raw_response["ranked_probabilities"][0] == first.candidates[0].probability
    assert len(first.raw_response["probabilities"]) == 25
    assert first.raw_response["probabilities"] == first.raw_response["raw_probabilities"]
    assert first.raw_response["score_metadata"]["temperature"] == 1.0
    assert 0 <= first.raw_response["score_metadata"]["face_down_probability"] <= 1

    with torch.no_grad():
        classifier._head.weight.zero_()
        classifier._head.bias.zero_()
        classifier._head.bias[24] = 10.0
    face_down = classifier.classify_ppm(fixture.frame_paths[0].read_bytes())
    assert face_down.status == "ok"
    assert face_down.classification == "face_down"
    assert face_down.candidates == ()
    assert face_down.raw_response["score_metadata"]["face_down_probability"] > 0.9


def test_calibrated_bundle_reloads_scores_and_retains_ranked_candidates(tmp_path: Path) -> None:
    fixture, identity, run = _train_run(tmp_path)
    run_record = json.loads((run / "run.json").read_text())
    checkpoint_path = run / run_record["checkpoints"]["best"]
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(
        json.dumps(
            {
                "schema_version": "dinov3-confidence-calibration/v1",
                "score_schema_version": "dinov3-visual-score/v1",
                "method": "scalar_temperature_scaling",
                "temperature": 2.0,
                "temperature_bounds": [0.05, 20.0],
                "run_id": run_record["run_id"],
                "source_checkpoint_sha256": hashlib.sha256(
                    checkpoint_path.read_bytes()
                ).hexdigest(),
                "view_id": "disjoint-calibration-view",
                "view_sha256": "e" * 64,
                "sample_ids_sha256": "f" * 64,
                "source_lineage_groups_sha256": "a" * 64,
                "sample_count": 4,
                "nll_before": 3.0,
                "nll_after": 2.0,
                "confidence_report": {
                    "review_threshold_selection": {"selected_threshold": {"threshold": 0.8}}
                },
            }
        )
    )
    bundle_path = export_dinov3_identity_bundle(
        run,
        tmp_path / "calibrated-bundle",
        identity_config=identity,
        calibration=calibration_path,
    )
    bundle = load_dinov3_identity_bundle(bundle_path)
    classifier = DinoV3IdentityClassifier(
        bundle,
        encoder_loader=lambda _bundle: _FakeEncoder(identity.input_size),
    )
    result = classifier.classify_ppm(fixture.frame_paths[0].read_bytes())
    logits = torch.tensor(result.raw_response["logits"])
    expected_raw = torch.softmax(logits, dim=0).tolist()
    expected_calibrated = torch.softmax(logits / 2.0, dim=0).tolist()

    assert result.status == "ok", result.error
    assert result.raw_response["raw_probabilities"] == pytest.approx(expected_raw)
    assert result.raw_response["probabilities"] == pytest.approx(expected_calibrated)
    expected_ranking = [
        VISUAL_IDENTITY_TARGETS[index]
        for index in sorted(range(25), key=lambda index: (-expected_raw[index], index))
    ]
    assert result.raw_response["ranked_targets"] == expected_ranking
    assert result.raw_response["score_metadata"]["review_threshold"] == 0.8
    assert len(result.candidates) == 24


@pytest.mark.parametrize("input_size", [224, 384, 448])
def test_cls_mean_patch_training_export_reload_and_runtime_agree(
    tmp_path: Path, input_size: int
) -> None:
    fixture, identity, run = _train_run(
        tmp_path, input_size=input_size, feature_layout="cls_mean_patch"
    )
    checkpoint = torch.load(run / "checkpoint-best.pt", map_location="cpu", weights_only=False)
    assert checkpoint["config"]["feature_layout"] == "cls_mean_patch"
    assert checkpoint["model_state"]["head.weight"].shape == (25, 8)

    bundle_path = export_dinov3_identity_bundle(run, tmp_path / "bundle", identity_config=identity)
    bundle = load_dinov3_identity_bundle(bundle_path)
    assert bundle.manifest["head"]["hidden_size"] == 8
    assert bundle.manifest["head"]["feature_layout"] == "cls_mean_patch"
    classifier = DinoV3IdentityClassifier(
        bundle_path, device="cpu", encoder_loader=lambda _bundle: _FakeEncoder(input_size)
    )
    checkpoint_weight = checkpoint["model_state"]["head.weight"]
    checkpoint_bias = checkpoint["model_state"]["head.bias"]
    assert torch.equal(classifier._head.weight.detach().cpu(), checkpoint_weight)
    assert torch.equal(classifier._head.bias.detach().cpu(), checkpoint_bias)
    from table_evidence_analyzer.dinov3_inference import _feature_output
    from table_evidence_analyzer.local_identity import transform_identity_crop

    encoder = _FakeEncoder(input_size)
    transformed = (
        transform_identity_crop(fixture.frame_paths[0].read_bytes(), input_size=input_size)
        .to_torch()
        .unsqueeze(0)
    )
    with torch.no_grad():
        features = _feature_output(
            encoder(pixel_values=transformed), encoder, "cls_mean_patch", input_size
        )
        expected_logits = torch.nn.functional.linear(features, checkpoint_weight, checkpoint_bias)
        reloaded_logits = classifier._head(features)
    assert torch.equal(reloaded_logits, expected_logits)
    result = classifier.classify_ppm(fixture.frame_paths[0].read_bytes())
    assert result.status == "ok"
    assert len(result.raw_response["probabilities"]) == 25


@pytest.mark.parametrize("input_size", [224, 384, 448])
@pytest.mark.parametrize("feature_layout", ["cls", "cls_mean_patch"])
def test_adapted_encoder_bundle_reloads_exact_checkpoint_weights(
    tmp_path: Path, input_size: int, feature_layout: str
) -> None:
    fixture, identity, run = _train_run(
        tmp_path,
        input_size=input_size,
        feature_layout=feature_layout,
        encoder_training="last_two_blocks",
    )
    checkpoint = torch.load(run / "checkpoint-best.pt", map_location="cpu", weights_only=False)
    bundle_path = export_dinov3_identity_bundle(run, tmp_path / "bundle", identity_config=identity)
    bundle = load_dinov3_identity_bundle(bundle_path)
    run_record = json.loads((run / "run.json").read_text(encoding="utf-8"))
    assert bundle.manifest["encoder"]["training_mode"] == "last_two_blocks"
    assert bundle.manifest["encoder"]["initialization"] == "adapted_checkpoint"
    assert (
        bundle.manifest["encoder"]["trainable_parameter_names"]
        == run_record["training"]["trainable_encoder_parameters"]
    )
    classifier = DinoV3IdentityClassifier(
        bundle_path,
        device="cpu",
        encoder_loader=lambda _bundle: _FakeEncoder(input_size),
    )
    for name, value in classifier._encoder.state_dict().items():
        assert torch.equal(value.cpu(), checkpoint["model_state"][f"encoder.{name}"])
    result = classifier.classify_ppm(fixture.frame_paths[0].read_bytes())
    assert result.status == "ok"
    assert len(result.raw_response["probabilities"]) == 25


@pytest.mark.parametrize("encoder_training", ["frozen", "last_two_blocks"])
@pytest.mark.parametrize("feature_layout", ["cls", "cls_mean_patch"])
def test_384_calibrated_recipe_lifecycle_resumes_and_classifies_all_targets(
    tmp_path: Path, encoder_training: str, feature_layout: str
) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    identity = _identity_config(tmp_path, input_size=384, feature_layout=feature_layout)
    run = tmp_path / "run"
    config = DinoV3TrainConfig(
        dataset=fixture.dataset_path,
        split=fixture.split_path,
        artifacts=fixture.artifact_index_path,
        identity_config=identity,
        output=run,
        seed=17,
        epochs=2,
        batch_size=1,
        learning_rate=0.05,
        encoder_training=encoder_training,
        max_steps=1,
    )
    with pytest.raises(DinoV3TrainingInterrupted):
        train_dinov3_identity(config, encoder_factory=_factory)
    train_dinov3_identity(
        replace(config, max_steps=None, resume=run / "checkpoint-last.pt"),
        encoder_factory=_factory,
    )

    run_record = json.loads((run / "run.json").read_text(encoding="utf-8"))
    checkpoint_path = run / run_record["checkpoints"]["best"]
    rows = []
    for index, target in enumerate(VISUAL_IDENTITY_TARGETS):
        logits = [-1.0] * len(VISUAL_IDENTITY_TARGETS)
        logits[index] = 2.0
        rows.append(
            {
                "sample_id": f"calibration-{index:02d}",
                "source_lineage_group": {"recording": "calibration-only"},
                "target": target,
                "logits": logits,
            }
        )
    view = tmp_path / "calibration-view.json"
    view.write_text(
        json.dumps(
            {
                "schema_version": CALIBRATION_VIEW_SCHEMA,
                "view_id": "synthetic-disjoint-25-class-view",
                "run_id": run_record["run_id"],
                "source_checkpoint_sha256": hashlib.sha256(
                    checkpoint_path.read_bytes()
                ).hexdigest(),
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )
    calibration = tmp_path / "calibration.json"
    fit_dinov3_confidence_calibration(run, view, calibration)
    bundle_path = export_dinov3_identity_bundle(
        run,
        tmp_path / "bundle",
        identity_config=identity,
        calibration=calibration,
    )
    bundle = load_dinov3_identity_bundle(bundle_path)
    classifier = DinoV3IdentityClassifier(
        bundle,
        encoder_loader=lambda _bundle: _FakeEncoder(384),
    )

    result = classifier.classify_ppm(fixture.frame_paths[0].read_bytes())

    assert run_record["status"] == "completed"
    assert run_record["progress"]["step"] > 1
    assert bundle.identity.input_size == 384
    assert run_record["training"]["feature_layout"] == feature_layout
    assert run_record["training"]["encoder_training"] == encoder_training
    assert bundle.manifest["head"]["class_count"] == 25
    calibration_record = json.loads(
        (bundle_path / bundle.manifest["calibration"]["file"]).read_text(encoding="utf-8")
    )
    assert calibration_record["sample_count"] == 25
    assert result.status == "ok", result.error
    assert len(result.raw_response["probabilities"]) == 25
    assert "face_down_probability" in result.raw_response["score_metadata"]


def test_export_rejects_head_width_incompatible_with_feature_layout(tmp_path: Path) -> None:
    _fixture, identity, run = _train_run(tmp_path, feature_layout="cls_mean_patch")
    checkpoint_path = run / "checkpoint-best.pt"
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    checkpoint["model_state"]["head.weight"] = checkpoint["model_state"]["head.weight"][:, :4]
    torch.save(checkpoint, checkpoint_path)

    with pytest.raises(DinoV3BundleError, match="feature layout"):
        export_dinov3_identity_bundle(run, tmp_path / "bundle", identity_config=identity)


def test_corrupt_weight_is_rejected_before_encoder_construction(tmp_path: Path) -> None:
    _fixture, identity, run = _train_run(tmp_path)
    bundle_path = export_dinov3_identity_bundle(run, tmp_path / "bundle", identity_config=identity)
    (bundle_path / "model.safetensors").write_bytes(b"corrupt")
    constructed = False

    def loader(_bundle):
        nonlocal constructed
        constructed = True
        return _FakeEncoder(_bundle.identity.input_size)

    with pytest.raises(DinoV3BundleError, match="hash"):
        DinoV3IdentityClassifier(bundle_path, encoder_loader=loader)
    assert constructed is False


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_corrupt_encoder_state_is_rejected_before_encoder_construction(
    tmp_path: Path, change: str
) -> None:
    _fixture, identity, run = _train_run(tmp_path, encoder_training="last_two_blocks")
    bundle_path = export_dinov3_identity_bundle(run, tmp_path / "bundle", identity_config=identity)
    encoder_state = bundle_path / "encoder-state.pt"
    if change == "missing":
        encoder_state.unlink()
    else:
        encoder_state.write_bytes(b"changed adapted encoder")
    constructed = False

    def loader(_bundle):
        nonlocal constructed
        constructed = True
        return _FakeEncoder(_bundle.identity.input_size)

    with pytest.raises(DinoV3BundleError, match="encoder-state.pt"):
        DinoV3IdentityClassifier(bundle_path, encoder_loader=loader)
    assert constructed is False


def test_inference_export_rejects_interrupted_resume_run(tmp_path: Path) -> None:
    _fixture, identity, run = _train_run(tmp_path, encoder_training="last_two_blocks")
    run_record_path = run / "run.json"
    run_record = json.loads(run_record_path.read_text(encoding="utf-8"))
    run_record["status"] = "interrupted"
    run_record_path.write_text(json.dumps(run_record), encoding="utf-8")

    with pytest.raises(DinoV3BundleError, match="completed DINOv3 run"):
        export_dinov3_identity_bundle(run, tmp_path / "bundle", identity_config=identity)


def test_bundle_rejects_transform_digest_mismatch_even_with_rewritten_manifest(
    tmp_path: Path,
) -> None:
    _fixture, identity, run = _train_run(tmp_path, input_size=384)
    bundle_path = export_dinov3_identity_bundle(run, tmp_path / "bundle", identity_config=identity)
    manifest_path = bundle_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["transform_digest"] = "0" * 64
    manifest["bundle_digest"] = _digest(
        {key: value for key, value in manifest.items() if key != "bundle_digest"}
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    with pytest.raises(DinoV3BundleError, match="transform digest"):
        load_dinov3_identity_bundle(bundle_path)


@pytest.mark.parametrize("encoder_training", ["frozen", "last_two_blocks"])
def test_exported_bundle_evaluation_reproduces_checkpoint_predictions(
    tmp_path: Path, encoder_training: str
) -> None:
    fixture, identity, run = _train_run(tmp_path, encoder_training=encoder_training)
    dataset = load_dataset_manifest(fixture.dataset_path)
    split = load_split_manifest(fixture.split_path)
    artifacts = load_artifact_index(fixture.artifact_index_path)
    campaign_root = tmp_path / "campaign"
    cache = materialize_crops(dataset, split, artifacts, campaign_root / "crop-cache")
    campaign_manifest = campaign_root / "manifest.json"
    campaign_manifest.write_text(
        json.dumps(
            {
                "state": "frozen",
                "campaign_id": "campaign-01",
                "manifest_digest": "d" * 64,
                "dataset": {"digest": dataset.digest},
                "split": {"digest": split.digest},
                "crop_inventory": {
                    "path": "crop-cache/crop-manifest.json",
                    "digest": cache.digest,
                },
                "unsupported_identities": ["CLUBS_NINE"],
                "items": [
                    {
                        "sample_id": crop.dataset_item_id,
                        "source_frame_id": crop.source_frame_id,
                        "recording_id": "recording-a",
                        "source_lineage_group": {"session": "session-a"},
                        "card_side": "face_up",
                        "crop_policy": "reviewed_visible_region",
                        "materialized_crop_sha256": crop.sha256,
                    }
                    for crop in cache.crops
                    if crop.partition == "validation"
                ],
            }
        ),
        encoding="utf-8",
    )
    run_path = run / "run.json"
    run_record = json.loads(run_path.read_text(encoding="utf-8"))
    run_record["config"]["campaign_manifest"] = str(campaign_manifest)
    run_record["campaign"] = {"campaign_id": "campaign-01", "manifest_digest": "d" * 64}
    run_path.write_text(json.dumps(run_record), encoding="utf-8")
    bundle_path = export_dinov3_identity_bundle(run, tmp_path / "bundle", identity_config=identity)

    provider_receipts = tmp_path / "gemini-receipts.json"
    validation_crops = [crop for crop in cache.crops if crop.partition == "validation"]
    provider_outcomes = []
    for index, crop in enumerate(validation_crops):
        status = ("classified", "failed", "unusable", "side_bypassed")[index % 4]
        provider_outcomes.append(
            {
                "sample_id": crop.dataset_item_id,
                "crop_sha256": crop.sha256,
                "status": status,
                "prediction": (
                    VISUAL_IDENTITY_TARGETS[
                        0 if crop.visual_card_identity != VISUAL_IDENTITY_TARGETS[0] else 1
                    ]
                    if status == "classified"
                    else None
                ),
                "score_metadata": (
                    {
                        "schema_version": "dinov3-visual-score/v1",
                        "calibrated": False,
                        "method": "provider_reported",
                        "confidence": 0.91,
                        "face_down_confidence": 0.03,
                    }
                    if status == "classified"
                    else None
                ),
                "request_identity": {
                    "request_id": f"request-{index}",
                    "model_id": "gemini-test-model",
                    "prompt_sha256": "a" * 64,
                    "input_sha256": crop.sha256,
                    "generation_config_sha256": "b" * 64,
                },
            }
        )
    provider_receipts.write_text(
        json.dumps(
            {
                "schema_version": "dinov3-paired-provider-receipts/v2",
                "provider": "gemini",
                "outcomes": provider_outcomes,
            }
        ),
        encoding="utf-8",
    )
    if provider_outcomes:
        invalid_receipts = json.loads(provider_receipts.read_text(encoding="utf-8"))
        invalid_receipts["outcomes"][0]["request_identity"]["input_sha256"] = "0" * 64
        invalid_path = tmp_path / "invalid-gemini-receipts.json"
        invalid_path.write_text(json.dumps(invalid_receipts), encoding="utf-8")
        with pytest.raises(DinoV3EvaluationError, match="request input digest"):
            _provider_receipt_index(
                invalid_path,
                expected={
                    crop.dataset_item_id: {"crop_sha256": crop.sha256} for crop in validation_crops
                },
            )

    report = evaluate_dinov3_identity_bundle(
        DinoV3EvaluationConfig(
            run=run,
            bundle=bundle_path,
            output=tmp_path / "evaluation.json",
            provider_receipts=provider_receipts,
        ),
        encoder_loader=_factory,
    )

    assert report["state"] == "completed"
    assert report["checkpoint_reproduction"]["state"] == "passed"
    assert report["schema_version"] == "dinov3-identity-bundle-evaluation/v3"
    assert report["summary"]["sample_count"] > 0
    assert len(report["per_class"]) == 25
    assert report["summary"]["unsupported_class_count"] >= 1
    assert (
        report["slice_summaries"]["source_lineage_group"]["session:session-a"]["sample_count"]
        == report["summary"]["sample_count"]
    )
    assert report["paired_provider"]["outcome_counts"].get("classified", 0) >= 1
    assert report["paired_provider"]["outcome_counts"].get("failed", 0) >= 0
    retained_score = next(
        row["score_metadata"]
        for row in report["paired_provider"]["paired_rows"]
        if row["score_metadata"] is not None
    )
    assert retained_score["face_down_confidence"] == 0.03
    assert retained_score["calibrated"] is False
    assert report["confidence"]["schema_version"] == "dinov3-visual-score/v1"
    corrected_pair = next(
        row
        for row in report["paired_provider"]["paired_rows"]
        if row["gemini_prediction"] is not None
    )
    assert corrected_pair["gemini_prediction"] != corrected_pair["target"]
    assert corrected_pair["score_metadata"]["confidence"] == 0.91
    assert report["paired_provider"]["side_bypassed_excluded_from_classifier_metrics"] >= 0
    assert len(report["paired_provider"]["paired_rows"]) == report["summary"]["sample_count"]
    assert "frame" in report["slice_summaries"]


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
