from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from doko_operations.rfdetr_segmentation_materialization import (
    validate_rfdetr_coco_annotations,
)
from doko_operations.synthetic_visible_region_planar_geometry import (
    SCANNED_DECK_SOURCE_DEFAULT,
    _apply_homography,
    _reduce_scan_saturation,
    _scanned_deck_assets,
    _shadow_length_scale,
    _warp_soft_card,
    build_synthetic_visible_region_planar_geometry_samples,
    fit_table_plane,
)


def _card_quad(center: tuple[float, float], angle_degrees: float) -> np.ndarray:
    angle = np.deg2rad(angle_degrees)
    short_axis = np.asarray([np.cos(angle), np.sin(angle)])
    long_axis = np.asarray([-np.sin(angle), np.cos(angle)])
    center_array = np.asarray(center)
    short = short_axis * 0.5
    long = long_axis * 0.75
    return np.asarray(
        [
            center_array - short - long,
            center_array + short - long,
            center_array + short + long,
            center_array - short + long,
        ],
        dtype=np.float64,
    )


def test_table_plane_fit_rectifies_rotated_cards_with_one_average_size() -> None:
    table_to_image = np.asarray(
        [[740.0, 95.0, 810.0], [30.0, 590.0, 240.0], [0.00035, 0.0007, 1.0]],
        dtype=np.float64,
    )
    source_quads = [
        _apply_homography(table_to_image, _card_quad((0.0, 0.0), 0.0)),
        _apply_homography(table_to_image, _card_quad((1.8, 0.4), 27.0)),
        _apply_homography(table_to_image, _card_quad((-0.6, 1.5), -36.0)),
        _apply_homography(table_to_image, _card_quad((1.2, 2.0), 58.0)),
    ]

    calibration = fit_table_plane(source_quads)

    assert calibration["accepted_card_count"] == 4
    assert calibration["card_aspect_ratio"] == 1.5
    assert calibration["median_angle_error_degrees"] < 0.05
    assert calibration["median_aspect_error"] < 0.001
    assert abs(calibration["card_short_size"] - 1.0) < 0.01
    assert abs(calibration["card_long_size"] - 1.5) < 0.01


def test_scanned_deck_assets_are_upright_canonical_cards() -> None:
    repository = Path(__file__).parents[2]

    assets = _scanned_deck_assets(repository, SCANNED_DECK_SOURCE_DEFAULT)

    assert [asset["record"]["deck_card_name"] for asset in assets] == [
        "SPADES_ten",
        "DIAMONDS_queen",
        "HEARTS_jack",
        "CLUBS_king",
        "DIAMONDS_ace",
        "HEARTS_ten",
    ]
    assert all(asset["rgba"].shape == (960, 640, 4) for asset in assets)
    assert all(asset["alpha"][480, 320] == 255 for asset in assets)
    assert all(asset["alpha"][0, 0] < 128 for asset in assets)


def test_soft_warp_keeps_scan_bed_transparent() -> None:
    rgba = np.zeros((960, 640, 4), dtype=np.uint8)
    rgba[:, :, :3] = (10, 20, 250)
    alpha = np.zeros((960, 640), dtype=np.uint8)
    alpha[24:-24, 24:-24] = 255
    quad = np.asarray([[30, 20], [150, 30], [140, 210], [20, 200]], dtype=np.float64)

    warped, warped_alpha = _warp_soft_card(rgba, alpha, quad, 200, 240, blur_sigma=0.9)

    assert warped_alpha[0, 0] == 0
    assert warped[0, 0, 3] == 0
    assert warped_alpha[110, 85] > 240
    assert np.any((warped_alpha > 0) & (warped_alpha < 255))


def test_scan_saturation_adjustment_preserves_alpha_and_reduces_chroma() -> None:
    rgba = np.zeros((3, 3, 4), dtype=np.uint8)
    rgba[:, :, :3] = (0, 0, 255)
    alpha = np.full((3, 3), 173, dtype=np.uint8)

    adjusted = _reduce_scan_saturation(rgba, alpha)

    before = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_BGR2HSV)[0, 0, 1]
    after = cv2.cvtColor(adjusted[:, :, :3], cv2.COLOR_BGR2HSV)[0, 0, 1]
    assert after < before
    assert np.array_equal(adjusted[:, :, 3], alpha)


def test_top_card_shadow_is_slightly_longer() -> None:
    assert _shadow_length_scale(1) == 1.0
    assert _shadow_length_scale(3) > _shadow_length_scale(1)


def test_planar_geometry_samples_use_empty_background_and_table_card_appearance(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).parents[2]
    manifest = build_synthetic_visible_region_planar_geometry_samples(
        repository,
        output_directory=tmp_path / "planar-geometry-samples",
        sample_count=3,
        recording_ids=("cardeventnet-IMG_0669",),
    )

    assert manifest["inventory"]["sample_scene_count"] == 3
    assert manifest["inventory"]["calibrated_recording_count"] == 1
    calibration = manifest["calibrations"][0]
    assert calibration["accepted_card_count"] >= 10
    assert calibration["background_strategy"] == "explicit-reviewed-empty-table-only-v1"
    assert all(
        scene["photometric_effects"]["reference_card_count"] >= 1
        for scene in manifest["scenes"]
    )
    assert all(scene["card_count"] in {1, 2, 3} for scene in manifest["scenes"])
    assert manifest["policy"]["card_source"] == "upright-ass-altenburger-romme-french-scans-v1"

    coco = json.loads(
        (tmp_path / "planar-geometry-samples" / "_annotations.coco.json").read_text(
            encoding="utf-8"
        )
    )
    validate_rfdetr_coco_annotations(coco)
    assert len(coco["images"]) == 3
    assert len(coco["annotations"]) == 6
    assert all(
        annotation["source_asset_id"].startswith("ass-altenburger-romme-french-")
        for annotation in coco["annotations"]
    )
