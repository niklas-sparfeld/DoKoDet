from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from doko_operations.rfdetr_segmentation_materialization import (
    validate_rfdetr_coco_annotations,
)
from doko_operations.synthetic_visible_region_planar_geometry import (
    SCANNED_DECK_SOURCE_DEFAULT,
    _apply_homography,
    _scanned_deck_assets,
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
    assert all(np.all(asset["alpha"] == 255) for asset in assets)


def test_planar_geometry_samples_use_empty_background_and_no_photometric_effects(
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
    assert all(scene["photometric_effects"] == {} for scene in manifest["scenes"])
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
