from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from doko_operations.rfdetr_segmentation_materialization import (
    validate_rfdetr_coco_annotations,
)
from doko_operations.synthetic_visible_region_empty_table_synthesis import (
    _apply_scene_lighting,
    _scene_lighting_parameters,
    _white_balance_cutout,
    build_synthetic_visible_region_empty_table_samples,
)


def test_white_balance_removes_cutout_channel_cast() -> None:
    rgba = np.zeros((32, 48, 4), dtype=np.uint8)
    rgba[:, :, :3] = (170, 190, 220)
    rgba[:, :, 3] = 255
    alpha = rgba[:, :, 3]

    balanced, profile = _white_balance_cutout(rgba, alpha)

    pixels = balanced[:, :, :3][alpha > 0]
    medians = np.median(pixels, axis=0)
    assert max(medians) - min(medians) <= 2.0
    assert profile["method"] == "neutral-highlight-gray-world-v1"


def test_scene_lighting_is_deterministic_and_applies_to_all_pixels() -> None:
    first = _scene_lighting_parameters(7001)
    second = _scene_lighting_parameters(7001)
    assert first == second
    assert set(first) >= {"exposure", "contrast", "color_gains_bgr", "vignette"}

    scene = np.full((16, 16, 3), 128, dtype=np.uint8)
    transformed = _apply_scene_lighting(scene.copy(), first)
    assert not np.array_equal(scene, transformed)
    assert transformed.shape == scene.shape
    assert np.all(transformed[8, 8] >= transformed[0, 0])


def test_empty_table_samples_use_only_reviewed_empty_backgrounds(tmp_path: Path) -> None:
    repository = Path(__file__).parents[2]
    manifest = build_synthetic_visible_region_empty_table_samples(
        repository,
        output_directory=tmp_path / "empty-table-samples",
        scene_limit=3,
    )

    assert manifest["policy"]["background_strategy"] == (
        "explicit-reviewed-empty-table-only-v1"
    )
    assert manifest["inventory"]["synthesized_scene_count"] == 3
    assert manifest["inventory"]["empty_background_count"] == 1
    assert all(
        scene["background"]["reviewed_decision"]["contains_visible_card"] is False
        for scene in manifest["scenes"]
    )
    assert all(
        scene["background"]["strategy"] == "explicit-reviewed-empty-table-only-v1"
        for scene in manifest["scenes"]
    )
    assert all(
        "inpaint" not in json.dumps(scene).lower() for scene in manifest["scenes"]
    )

    coco = json.loads(
        (tmp_path / "empty-table-samples" / "_annotations.coco.json").read_text(
            encoding="utf-8"
        )
    )
    validate_rfdetr_coco_annotations(coco)
    assert len(coco["images"]) == 3
    assert len(coco["annotations"]) >= 3
    assert len(list((tmp_path / "empty-table-samples" / "cutouts").glob("*.png"))) > 0
