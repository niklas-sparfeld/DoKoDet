from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from table_evidence_analyzer.cards import CARD_IDENTITIES
from table_evidence_analyzer.local_identity import (
    DINOV3_LICENSE_ID,
    DINOV3_MODEL_ID,
    DINOV3_PROCESSOR_CONFIG,
    DinoV3IdentityConfig,
    LocalIdentityContractError,
    MaterializedDinoV3Weights,
    build_dinov3_identity_config,
    canonical_identity_target_map,
    materialize_dinov3_weights,
    transform_identity_crop,
    validate_identity_target_map,
    verify_materialized_dinov3_weights,
)


def _license() -> dict[str, object]:
    return {
        "license_id": DINOV3_LICENSE_ID,
        "name": "DINOv3 License",
        "version": "2025-08-19",
        "url": "https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md",
        "accepted": True,
        "accepted_at_utc": "2026-09-01T12:00:00Z",
    }


def _write_materialized_weights(root: Path) -> tuple[Path, str, str, str]:
    root.mkdir()
    (root / "config.json").write_text(
        json.dumps({"model_type": "dinov3", "hidden_size": 384}), encoding="utf-8"
    )
    (root / "preprocessor_config.json").write_text(
        json.dumps({"do_resize": True, "size": {"height": 224, "width": 224}}),
        encoding="utf-8",
    )
    weights = b"generated local DINOv3 safetensors double"
    (root / "model.safetensors").write_bytes(weights)
    return (
        root,
        hashlib.sha256(weights).hexdigest(),
        hashlib.sha256((root / "config.json").read_bytes()).hexdigest(),
        hashlib.sha256((root / "preprocessor_config.json").read_bytes()).hexdigest(),
    )


def test_target_map_is_the_canonical_24_identity_order() -> None:
    target_map = canonical_identity_target_map()

    assert list(target_map) == [str(index) for index in range(24)]
    assert list(target_map.values()) == list(CARD_IDENTITIES)
    assert validate_identity_target_map(target_map) == target_map


def test_target_map_rejects_unknown_or_reordered_identity() -> None:
    target_map = canonical_identity_target_map()
    target_map["0"] = "UNKNOWN"

    with pytest.raises(LocalIdentityContractError, match="target map"):
        validate_identity_target_map(target_map)


def test_transform_is_repeatable_and_letterboxes_the_ppm_crop() -> None:
    crop = b"P6\n8 4\n255\n" + bytes((255, 0, 0) * 32)

    first = transform_identity_crop(crop)
    second = transform_identity_crop(crop)

    assert first == second
    assert first.shape == (3, 224, 224)
    assert first.tensor_digest == hashlib.sha256(first.tensor_bytes).hexdigest()
    assert first.transformed_ppm.startswith(b"P6\n224 224\n255\n")
    # The top-left pixel is neutral padding, while the center is the red crop.
    assert first.pixel_rgb(0, 0) == (128, 128, 128)
    assert first.pixel_rgb(112, 112) == (255, 0, 0)


def test_transform_rejects_invalid_ppm_bytes() -> None:
    with pytest.raises(LocalIdentityContractError, match="PPM"):
        transform_identity_crop(b"not an image")


def test_materialization_records_and_rechecks_all_frozen_file_digests(tmp_path: Path) -> None:
    root, weight_digest, config_digest, processor_digest = _write_materialized_weights(
        tmp_path / "weights"
    )
    weights = materialize_dinov3_weights(
        root,
        model_revision="revision-abc123",
        license_record=_license(),
        expected_weight_sha256=weight_digest,
        expected_config_sha256=config_digest,
        expected_processor_sha256=processor_digest,
    )

    assert weights.weight_sha256 == weight_digest
    assert weights.model_revision == "revision-abc123"
    verify_materialized_dinov3_weights(weights)

    (root / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(LocalIdentityContractError, match="processor"):
        verify_materialized_dinov3_weights(weights)


def test_materialization_requires_explicit_license_acceptance(tmp_path: Path) -> None:
    root, *_ = _write_materialized_weights(tmp_path / "weights")
    license_record = _license()
    license_record["accepted"] = False
    license_record["accepted_at_utc"] = None

    with pytest.raises(LocalIdentityContractError, match="license"):
        materialize_dinov3_weights(
            root,
            model_revision="revision-abc123",
            license_record=license_record,
        )


def test_config_identity_contains_pretrained_revision_digest_processor_and_dependencies(
    tmp_path: Path,
) -> None:
    root, weight_digest, config_digest, processor_digest = _write_materialized_weights(
        tmp_path / "weights"
    )
    weights = materialize_dinov3_weights(
        root,
        model_revision="revision-abc123",
        license_record=_license(),
    )
    config = build_dinov3_identity_config(weights, license_record=_license())
    mapping = config.to_mapping()

    assert mapping["model"]["id"] == DINOV3_MODEL_ID
    assert mapping["model"]["revision"] == "revision-abc123"
    assert mapping["model"]["weights"]["sha256"] == weight_digest
    assert mapping["model"]["config_sha256"] == config_digest
    assert mapping["model"]["processor_sha256"] == processor_digest
    assert mapping["processor"] == DINOV3_PROCESSOR_CONFIG
    assert mapping["target"]["class_count"] == 24
    assert mapping["license"]["license_id"] == DINOV3_LICENSE_ID
    assert mapping["quality_state"] == "unusable_smoke_artifact"
    assert config.identity_digest

    restored = DinoV3IdentityConfig.from_mapping(mapping, root=root)
    assert restored.identity_digest == config.identity_digest

    changed = json.loads(json.dumps(mapping))
    changed["processor"]["padding"]["fill_rgb"][0] = 127
    with pytest.raises(LocalIdentityContractError, match="processor"):
        DinoV3IdentityConfig.from_mapping(changed, root=root)


def test_materialized_weights_mapping_round_trips_without_a_local_path(tmp_path: Path) -> None:
    root, *_ = _write_materialized_weights(tmp_path / "weights")
    weights = materialize_dinov3_weights(
        root,
        model_revision="revision-abc123",
        license_record=_license(),
    )

    restored = MaterializedDinoV3Weights.from_mapping(weights.to_mapping(), root=root)

    assert restored == weights
