from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from doko_operations.reviewed_rfdetr_detector_campaign import canonical_json_bytes
from doko_operations.synthetic_visible_region_rendering import (
    SyntheticVisibleRegionRenderingError,
    build_synthetic_visible_region_scenes,
    validate_synthetic_visible_region_scenes,
)


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _write_fixture_inputs(root: Path) -> tuple[Path, Path]:
    output = root / "m1-output"
    output.mkdir()
    rgba = np.zeros((960, 640, 4), dtype=np.uint8)
    rgba[:, :, :3] = (230, 230, 230)
    rgba[:, :, 3] = 255
    assert cv2.imwrite(str(output / "card.png"), rgba)
    alpha = np.full((960, 640), 255, dtype=np.uint8)
    assert cv2.imwrite(str(output / "card.alpha.png"), alpha)
    background = np.full((360, 480, 3), (55, 70, 90), dtype=np.uint8)
    assert cv2.imwrite(str(output / "background.jpg"), background)
    rgba_digest = hashlib.sha256((output / "card.png").read_bytes()).hexdigest()
    alpha_digest = hashlib.sha256((output / "card.alpha.png").read_bytes()).hexdigest()
    background_digest = hashlib.sha256((output / "background.jpg").read_bytes()).hexdigest()
    source_key = "1" * 64
    source_group = {
        "id": "fixture-source",
        "key": source_key,
        "permission": "training_only",
        "split": "train",
        "table_setup": "fixture-table",
        "source_sha256": "2" * 64,
    }
    cutout = {
        "cutout_id": "fixture-card-01",
        "source_asset_id": "fixture-card",
        "source_frame": {
            "path": "fixture-card.png",
            "source_file_sha256": "3" * 64,
            "decoded_pixel_sha256": "4" * 64,
            "width": 640,
            "height": 960,
        },
        "source_group": source_group,
        "reviewed_decision": {
            "status": "accepted",
            "card_side": "face_up",
            "clipped": False,
            "occluded": False,
        },
        "source_quadrilateral": [
            {"x": 100.0, "y": 80.0},
            {"x": 500.0, "y": 80.0},
            {"x": 500.0, "y": 880.0},
            {"x": 100.0, "y": 880.0},
        ],
        "roundtrip_max_pixel_error": 0.0,
        "files": {
            "rgba": {"path": str(output / "card.png"), "sha256": rgba_digest},
            "alpha": {"path": str(output / "card.alpha.png"), "sha256": alpha_digest},
        },
    }
    second_cutout = json.loads(json.dumps(cutout))
    second_cutout["cutout_id"] = "fixture-card-02"
    background_record = {
        "background_id": "fixture-background",
        "source_group": source_group,
        "reviewed_decision": {
            "status": "accepted",
            "full_frame_review_coverage": True,
            "contains_visible_card": False,
        },
        "frame_identity": {"image_sha256": background_digest, "width": 480, "height": 360},
        "files": {"image": {"path": str(output / "background.jpg"), "sha256": background_digest}},
    }
    m1_core = {
        "schema_version": "synthetic-visible-region-inputs/v1",
        "campaign_id": "0070-m1-synthetic-visible-region-inputs",
        "milestone": "M1",
        "freeze_state": "blocked",
        "source_boundary": {"split": "train"},
        "source_directory": "fixture",
        "sources": [{"source_asset_id": "fixture-card", "source_group": source_group}],
        "cutouts": [cutout, second_cutout],
        "backgrounds": [background_record],
        "occluders": [],
        "operator_review_links": [],
        "excluded_review_inputs": [],
        "perspective_library": {
            "source": "fixture",
            "example_count": 1,
            "examples": [
                {
                    "cutout_id": "fixture-card-01",
                    "table_setup": "fixture-table",
                    "source_width": 480,
                    "source_height": 360,
                    "source_quadrilateral": [
                        {"x": 150.0, "y": 50.0},
                        {"x": 330.0, "y": 50.0},
                        {"x": 330.0, "y": 310.0},
                        {"x": 150.0, "y": 310.0},
                    ],
                }
            ],
        },
        "inventory": {
            "source_count": 1,
            "cutout_count": 2,
            "background_count": 1,
        },
        "materializer": {},
        "table_input_spec": None,
        "coverage_gaps": ["fixture has no face_down card"],
    }
    m1 = {**m1_core, "manifest_digest": _digest(m1_core)}
    m1_path = root / "m1.json"
    m1_path.write_bytes(canonical_json_bytes(m1) + b"\n")
    recipe = {
        "schema_version": "synthetic-visible-region-recipe/v1",
        "seed": 7001,
        "max_scene_count": 2,
        "scene_buckets": [
            "fully_visible_card",
            "separated_cards",
            "overlapping_cards_shallow",
            "overlapping_cards_medium",
            "overlapping_cards_heavy",
            "frame_boundary_clipping",
            "face_down_cards",
            "mixed_card_sides",
            "blur_glare_dark_compressed",
            "reviewed_empty_background",
        ],
    }
    m0_core = {
        "schema_version": "synthetic-visible-region-manifest/v1",
        "campaign_id": "0070-m0-synthetic-visible-region-training-data",
        "milestone": "M0",
        "read_only": True,
        "freeze_state": "blocked",
        "question": "fixture",
        "boundaries": {},
        "inputs": {},
        "baseline": {"proposal_baseline": {"contract_sha256": "5" * 64}, "local_rfdetr_0068": {}},
        "eligibility": {"card_cutouts": [], "backgrounds": [], "occluders": []},
        "recipe": recipe,
        "comparison": {},
        "annotation_pilot": {},
        "stop_rules": {},
        "inventory": {
            "real_training_frame_count": 1,
            "eligible_card_cutout_count": 0,
            "eligible_background_count": 0,
            "eligible_occluder_count": 0,
        },
        "coverage_gaps": ["fixture"],
    }
    m0 = {**m0_core, "manifest_digest": _digest(m0_core)}
    m0_path = root / "m0.json"
    m0_path.write_bytes(canonical_json_bytes(m0) + b"\n")
    return m1_path, m0_path


def test_m2_rendering_is_deterministic_and_records_the_face_down_gap(tmp_path: Path) -> None:
    m1_path, m0_path = _write_fixture_inputs(tmp_path)
    first = build_synthetic_visible_region_scenes(
        tmp_path,
        m1_manifest_path=m1_path,
        m0_manifest_path=m0_path,
        output_directory=tmp_path / "m2",
        scene_count=8,
    )
    second = build_synthetic_visible_region_scenes(
        tmp_path,
        m1_manifest_path=m1_path,
        m0_manifest_path=m0_path,
        output_directory=tmp_path / "m2",
        scene_count=8,
    )

    assert first == second
    assert first["freeze_state"] == "complete_with_gap"
    assert first["outputs"]["scene_count"] == 8
    assert first["outputs"]["annotation_count"] > 0
    assert "face_down_cards" in first["recipe"]["omitted_buckets"]
    assert "mixed_card_sides" in first["recipe"]["omitted_buckets"]
    assert any(scene["bucket"] == "reviewed_empty_background" for scene in first["scenes"])
    assert any(scene["bucket"] == "frame_boundary_clipping" for scene in first["scenes"])
    assert any(scene["bucket"].startswith("overlapping_cards_") for scene in first["scenes"])
    validate_synthetic_visible_region_scenes(first)

    receipts = [
        json.loads((tmp_path / "m2" / "receipts" / f"scene-{index:04d}.json").read_text())
        for index in range(8)
    ]
    assert any(
        item["occlusion_ratio"] > 0
        for receipt in receipts
        for item in receipt["placements"]
    )
    for receipt in receipts:
        masks = []
        for placement in receipt["placements"]:
            path = tmp_path / placement["mask"]["path"]
            masks.append(cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) > 0)
        for index, mask in enumerate(masks):
            assert not any(np.any(mask & other) for other in masks[index + 1 :])


def test_m2_rejects_a_changed_cutout_digest(tmp_path: Path) -> None:
    m1_path, m0_path = _write_fixture_inputs(tmp_path)
    manifest = json.loads(m1_path.read_text())
    manifest["cutouts"][0]["files"]["rgba"]["sha256"] = "f" * 64
    core = {key: manifest[key] for key in manifest if key != "manifest_digest"}
    manifest["manifest_digest"] = _digest(core)
    m1_path.write_bytes(canonical_json_bytes(manifest) + b"\n")

    with pytest.raises(SyntheticVisibleRegionRenderingError, match="RGBA digest differs"):
        build_synthetic_visible_region_scenes(
            tmp_path,
            m1_manifest_path=m1_path,
            m0_manifest_path=m0_path,
            output_directory=tmp_path / "m2",
            scene_count=1,
        )
