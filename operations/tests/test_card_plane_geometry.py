from __future__ import annotations

import hashlib

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
    derive_pose_scene_visible_regions,
    derive_visible_masks,
    geometry_contract_manifest,
    invert_homography,
    mask_to_polygons,
    project_fixed_card,
    validate_derived_region_receipt,
    validate_pose_scene_candidate_view,
)
from doko_operations.pipeline_data import canonical_json_bytes


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


def _derived_scene(*, poses: tuple[CardPose, ...], order: tuple[str, ...]) -> ReviewedCardScene:
    return ReviewedCardScene.create(
        source_frame_id="frame-1",
        source_frame_width=24,
        source_frame_height=24,
        calibration_revision_id="calibration-1",
        calibration_digest=_digest("a"),
        poses=poses,
        stacking_order=CardStackingOrder(
            card_ids=order,
            uncertain_edges=(),
            contradictions=(),
        ),
    )


def test_pose_scene_derivation_clips_cards_and_keeps_ordered_regions_deterministic() -> None:
    scene = _derived_scene(
        poses=(
            CardPose("card-front", (8.0, 12.0), 0.0, None, None),
            CardPose("card-back", (-1.0, 12.0), 0.0, None, None),
        ),
        order=("card-front", "card-back"),
    )
    projection = {
        "table_to_image_homography": np.eye(3).tolist(),
        "card_short_size": 6.0,
        "card_long_size": 10.0,
    }

    first = derive_pose_scene_visible_regions(scene, projection)
    second = derive_pose_scene_visible_regions(scene.to_mapping(), projection)

    assert first.to_mapping() == second.to_mapping()
    assert [region["card_id"] for region in first.regions] == ["card-front", "card-back"]
    assert first.hidden_card_ids == ()
    assert all(
        0 <= point[axis] <= 1000
        for region in first.regions
        for polygon in region["geometry"]["visible_region"]["polygons"]
        for point in polygon
        for axis in ("x", "y")
    )
    assert first.receipt.region_digests == tuple(
        hashlib.sha256(canonical_json_bytes(region)).hexdigest() for region in first.regions
    )


def test_pose_scene_candidate_view_rejects_hidden_cards_and_stale_geometry() -> None:
    scene = _derived_scene(
        poses=(
            CardPose("card-front", (8.0, 12.0), 0.0, None, None),
            CardPose("card-back", (8.0, 12.0), 0.0, None, None),
        ),
        order=("card-front", "card-back"),
    )
    projection = {
        "table_to_image_homography": np.eye(3).tolist(),
        "card_short_size": 6.0,
        "card_long_size": 10.0,
    }
    derivation = derive_pose_scene_visible_regions(scene, projection)
    assert derivation.hidden_card_ids == ("card-back",)
    with pytest.raises(CardPlaneGeometryError, match="fully hidden"):
        validate_pose_scene_candidate_view(
            scene,
            projection,
            list(derivation.regions),
            receipt=derivation.receipt.to_mapping(),
        )

    visible_scene = _derived_scene(
        poses=(CardPose("card-front", (8.0, 12.0), 0.0, None, None),),
        order=("card-front",),
    )
    visible = derive_pose_scene_visible_regions(visible_scene, projection)
    candidates = [
        {
            "card_id": region["card_id"],
            "geometry": region["geometry"],
            "normalization": region["normalization"],
        }
        for region in visible.regions
    ]
    candidates[0]["geometry"] = {
        "kind": "reviewed-visible-region/v1",
        "visible_region": {"polygons": []},
    }
    with pytest.raises(CardPlaneGeometryError, match="do not match"):
        validate_pose_scene_candidate_view(
            visible_scene,
            projection,
            candidates,
            receipt=visible.receipt.to_mapping(),
        )


def test_scene_pose_storage_order_can_differ_from_front_to_back_order() -> None:
    scene = _derived_scene(
        poses=(
            CardPose("card-a", (8.0, 8.0), 0.0, None, None),
            CardPose("card-b", (16.0, 16.0), 0.0, None, None),
        ),
        order=("card-b", "card-a"),
    )

    assert scene.stacking_order.card_ids == ("card-b", "card-a")
    assert ReviewedCardScene.from_mapping(scene.to_mapping()) == scene
