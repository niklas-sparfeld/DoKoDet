from __future__ import annotations

import numpy as np
import pytest

from doko_operations.card_plane_geometry import (
    DERIVATION_RECIPE_VERSION,
    CalibrationCandidateReceipt,
    CardPlaneGeometryError,
    CardPose,
    CardStackingOrder,
    DerivedRegionReceipt,
    PoseFitDiagnostics,
    ReviewedCardScene,
    TablePlaneCalibration,
    apply_homography,
    card_quad_from_pose,
    derive_visible_masks,
    geometry_contract_manifest,
    invert_homography,
    mask_to_polygons,
    project_fixed_card,
    validate_derived_region_receipt,
)


def _digest(fill: str = "a") -> str:
    return fill * 64


def test_geometry_contract_manifest_freezes_the_numeric_boundary() -> None:
    contract = geometry_contract_manifest()

    assert contract["numeric_precision_decimals"] == 6
    assert contract["mask_threshold"] == 128
    assert contract["derivation_recipe_version"] == DERIVATION_RECIPE_VERSION
    assert contract["card_aspect_ratio"] == 1.5


def test_calibration_and_scene_contracts_round_trip_with_digests() -> None:
    candidate = CalibrationCandidateReceipt.create(
        candidate_id="candidate-1",
        source_revision="generated-1",
        source_frame_id="frame-1",
        confidence=0.987654321,
        quadrilateral=[[0, 0], [1, 0], [1, 1.5], [0, 1.5]],
        temporal_bin="t-1",
        table_position_bin="p-1",
        scale_bin="s-1",
        orientation_bin="o-1",
        accepted=True,
    )
    assert CalibrationCandidateReceipt.from_mapping(candidate.to_mapping()) == candidate

    diagnostics = PoseFitDiagnostics(
        card_id="card-a",
        source_suggestion_id="suggestion-a",
        residual=0.123456789,
        accepted=True,
        failure_reason=None,
        diagnostics_digest="",
    )
    restored_diagnostics = PoseFitDiagnostics.from_mapping(diagnostics.to_mapping())
    assert restored_diagnostics.to_mapping() == diagnostics.to_mapping()

    calibration = TablePlaneCalibration.create(
        calibration_revision_id="calibration-1",
        recording_id="recording-1",
        source_revision="generated-1",
        frame_width=640,
        frame_height=480,
        image_to_table=np.eye(3),
        table_to_image=np.eye(3),
        card_short_size=1.0,
        card_long_size=1.5,
        candidate_receipt_digests=(),
        diagnostics={"accepted": 3},
    )
    restored_calibration = TablePlaneCalibration.from_mapping(calibration.to_mapping())
    assert restored_calibration == calibration

    poses = (
        CardPose.from_mapping(
            {
                "schema_version": "card-pose/v1",
                "card_id": "card-a",
                "center": [0.0, 0.0],
                "rotation_degrees": 0.0,
                "source_suggestion_id": "suggestion-a",
                "fit_diagnostics_digest": None,
            }
        ),
        CardPose.from_mapping(
            {
                "schema_version": "card-pose/v1",
                "card_id": "card-b",
                "center": [2.0, 1.0],
                "rotation_degrees": 12.0,
                "source_suggestion_id": None,
                "fit_diagnostics_digest": None,
            }
        ),
    )
    order = CardStackingOrder.from_mapping(
        {
            "schema_version": "card-stacking-order/v1",
            "card_ids": ["card-a", "card-b"],
            "uncertain_edges": [],
            "contradictions": [],
        }
    )
    scene = ReviewedCardScene.create(
        source_frame_id="frame-1",
        source_frame_width=640,
        source_frame_height=480,
        calibration_revision_id=calibration.calibration_revision_id,
        calibration_digest=calibration.calibration_digest,
        poses=poses,
        stacking_order=order,
    )

    assert ReviewedCardScene.from_mapping(scene.to_mapping()) == scene
    tampered = scene.to_mapping()
    tampered["calibration_digest"] = _digest("b")
    with pytest.raises(CardPlaneGeometryError, match="scene digest"):
        ReviewedCardScene.from_mapping(tampered)


def test_derived_regions_reject_a_different_scene_or_calibration() -> None:
    receipt = DerivedRegionReceipt.create(
        source_frame_id="frame-1",
        scene_digest=_digest("a"),
        calibration_digest=_digest("b"),
        region_digests=[_digest("c")],
    )

    assert (
        validate_derived_region_receipt(
            receipt.to_mapping(), scene_digest=_digest("a"), calibration_digest=_digest("b")
        )
        == receipt
    )
    with pytest.raises(CardPlaneGeometryError, match="different scene"):
        validate_derived_region_receipt(
            receipt, scene_digest=_digest("d"), calibration_digest=_digest("b")
        )
    with pytest.raises(CardPlaneGeometryError, match="different calibration"):
        validate_derived_region_receipt(
            receipt, scene_digest=_digest("a"), calibration_digest=_digest("d")
        )


def test_fixed_card_projection_round_trips_through_one_homography() -> None:
    table_to_image = np.asarray(
        [[740.0, 95.0, 810.0], [30.0, 590.0, 240.0], [0.00035, 0.0007, 1.0]],
        dtype=np.float64,
    )
    table_quad = card_quad_from_pose((1.4, 0.8), 23.0, 1.0, 1.5)
    image_quad = project_fixed_card(table_to_image, (1.4, 0.8), 23.0, 1.0, 1.5)

    assert np.allclose(apply_homography(invert_homography(table_to_image), image_quad), table_quad)


def test_visible_mask_occlusion_preserves_disconnected_back_components() -> None:
    back = np.zeros((12, 14), dtype=np.uint8)
    back[2:10, 2:12] = 255
    front = np.zeros_like(back)
    front[2:10, 6:8] = 255

    visible_back, visible_front = derive_visible_masks([back, front], [1, 0])

    assert np.count_nonzero(visible_front) == np.count_nonzero(front)
    assert len(mask_to_polygons(visible_back)) == 2


def test_homography_rejects_singular_transforms() -> None:
    with pytest.raises(CardPlaneGeometryError, match="invertible"):
        apply_homography(np.zeros((3, 3)), np.zeros((1, 2)))
