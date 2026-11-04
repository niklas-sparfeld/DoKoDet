from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from doko_operations.card_plane_calibration import calibrate_recording
from doko_operations.card_plane_geometry import (
    TablePlaneCalibration,
    apply_homography,
    project_fixed_card,
    rasterize_polygon,
)
from doko_operations.card_plane_initialization import (
    PoseFitRecipe,
    _boundary_mask,
    _Candidate,
    _clipped_distances_to_boundary,
    _fit_candidate,
    _fit_evidence_mask,
    _fit_score,
    _fit_score_projected,
    _FittedCandidate,
    _mark_contained_alternatives,
    _mask_area_seed,
    _suppress_contained_fragments,
    initialize_card_scene,
)

TABLE_TO_IMAGE = np.asarray(
    [[120.0, 20.0, 420.0], [15.0, 100.0, 240.0], [0.0002, 0.0004, 1.0]],
    dtype=np.float64,
)


def test_clipped_boundary_distances_match_full_transform() -> None:
    rng = np.random.default_rng(87)
    for tolerance in (0.5, 8.0, 17.5):
        for _ in range(20):
            boundary = np.zeros((120, 160), dtype=np.uint8)
            evidence = np.zeros_like(boundary)
            for mask in (boundary, evidence):
                x, y = rng.integers(0, 130), rng.integers(0, 90)
                mask[y:y + 30, x:x + 30] = (rng.random((30, 30)) > 0.95) * 255
            expected = cv2.distanceTransform(cv2.bitwise_not(boundary), cv2.DIST_L2, 3)
            expected = np.minimum(expected[evidence > 0], tolerance)
            np.testing.assert_array_equal(
                _clipped_distances_to_boundary(boundary, evidence, tolerance), expected
            )


def test_fit_score_matches_boolean_overlap_for_binary_masks() -> None:
    rng = np.random.default_rng(42)
    for density in (0.0, 0.1, 0.5, 1.0):
        source = (rng.random((41, 57)) < density).astype(np.uint8) * 255
        projected = (rng.random((41, 57)) < 0.4).astype(np.uint8) * 255
        intersection = np.count_nonzero((projected > 0) & (source > 0))
        union = np.count_nonzero((projected > 0) | (source > 0))
        source_area = int(np.count_nonzero(source))
        expected = (
            0.0
            if not intersection
            else (
                0.55 * intersection / union
                + 0.30 * intersection / max(source_area, 1)
                + 0.15 * intersection / max(np.count_nonzero(projected), 1)
            )
        )
        assert np.isclose(_fit_score(projected, source, source_area), expected)


def test_projected_pose_score_matches_full_frame_score() -> None:
    width, height = 192, 108
    source = rasterize_polygon(
        np.asarray([[70.2, 20.4], [110.6, 22.1], [108.3, 70.5], [69.8, 68.9]]),
        width,
        height,
    )
    source_area = int(np.count_nonzero(source))
    source_bounds = tuple(int(value) for value in cv2.boundingRect(source))
    for dx, dy in ((0, 0), (-90, 0), (130, 0), (0, -70), (0, 90), (300, 200)):
        projected = np.asarray(
            [
                [65.4 + dx, 18.6 + dy],
                [115.7 + dx, 20.2 + dy],
                [111.8 + dx, 72.3 + dy],
                [67.1 + dx, 69.8 + dy],
            ]
        )
        expected = _fit_score(rasterize_polygon(projected, width, height), source, source_area)
        assert (
            _fit_score_projected(projected, source, source_area, source_bounds, width, height)
            == expected
        )


def test_boundary_mask_matches_binary_erosion_for_mask_types() -> None:
    rng = np.random.default_rng(19)
    for dtype in (np.uint8, np.bool_, np.int64):
        mask = (rng.random((37, 43)) > 0.3).astype(dtype)
        values = np.where(mask > 0, 255, 0).astype(np.uint8)
        eroded = cv2.erode(
            values, np.ones((7, 7), dtype=np.uint8),
            borderType=cv2.BORDER_CONSTANT, borderValue=0,
        )
        expected = np.where((values > 0) & (eroded == 0), 255, 0).astype(np.uint8)
        np.testing.assert_array_equal(_boundary_mask(mask, width=3), expected)


def test_occlusion_evidence_removes_existing_edges_without_inventing_cut_edges() -> None:
    source = np.zeros((64, 64), dtype=np.uint8)
    cv2.rectangle(source, (10, 10), (54, 54), 255, thickness=-1)
    occluder = np.zeros_like(source)
    cv2.rectangle(occluder, (28, 8), (40, 56), 255, thickness=-1)

    original_boundary = _boundary_mask(source, width=3)
    evidence = _fit_evidence_mask(source, occluder, edge_width_pixels=3, occlusion_margin_pixels=0)

    assert np.all((evidence > 0) <= (original_boundary > 0))
    assert not np.any((evidence > 0) & (occluder > 0))
    assert np.count_nonzero(evidence) > 0
    assert not np.any(evidence[:, 28:41] > 0)


def test_frame_border_is_not_counted_as_an_observed_card_edge() -> None:
    source = np.zeros((64, 64), dtype=np.uint8)
    cv2.rectangle(source, (20, 10), (63, 50), 255, thickness=-1)
    evidence = _fit_evidence_mask(source, None, edge_width_pixels=3, occlusion_margin_pixels=0)
    assert not np.any(evidence[:, -3:])
    assert np.any(evidence[10:13, 25:55])


def test_occlusion_mask_removes_hidden_projected_edge_from_fit_score() -> None:
    width, height = 96, 72
    source = np.zeros((height, width), dtype=np.uint8)
    cv2.rectangle(source, (16, 12), (80, 60), 255, thickness=-1)
    projected = np.asarray(
        [[16.0, 12.0], [80.0, 12.0], [80.0, 60.0], [16.0, 60.0]], dtype=np.float64
    )
    occluder = np.zeros_like(source)
    cv2.rectangle(occluder, (48, 8), (88, 64), 255, thickness=-1)
    evidence = _fit_evidence_mask(source, occluder, edge_width_pixels=3, occlusion_margin_pixels=0)
    source_area = int(np.count_nonzero(evidence))
    source_bounds = tuple(int(value) for value in cv2.boundingRect(evidence))

    without_occlusion_geometry = _fit_score_projected(
        projected,
        evidence,
        source_area,
        source_bounds,
        width,
        height,
        edge_only=True,
        edge_width_pixels=3,
    )
    with_occlusion_geometry = _fit_score_projected(
        projected,
        evidence,
        source_area,
        source_bounds,
        width,
        height,
        edge_only=True,
        edge_width_pixels=3,
        occlusion_mask=occluder,
    )
    source_distance_map = cv2.distanceTransform(
        np.where(evidence > 0, 0, 255).astype(np.uint8),
        cv2.DIST_L2,
        3,
    )
    with_cached_source_distance = _fit_score_projected(
        projected,
        evidence,
        source_area,
        source_bounds,
        width,
        height,
        edge_only=True,
        edge_width_pixels=3,
        occlusion_mask=occluder,
        source_distance_map=source_distance_map,
    )

    assert with_occlusion_geometry > without_occlusion_geometry
    assert with_cached_source_distance == with_occlusion_geometry
    for dx, dy in ((-70, 0), (25, 0), (0, -30), (0, 30), (140, 80)):
        shifted = projected + np.asarray([dx, dy], dtype=np.float64)
        uncached_score = _fit_score_projected(
            shifted,
            evidence,
            source_area,
            source_bounds,
            width,
            height,
            edge_only=True,
            edge_width_pixels=3,
            occlusion_mask=occluder,
        )
        cached_score = _fit_score_projected(
            shifted,
            evidence,
            source_area,
            source_bounds,
            width,
            height,
            edge_only=True,
            edge_width_pixels=3,
            occlusion_mask=occluder,
            source_distance_map=source_distance_map,
        )
        assert cached_score == uncached_score


def test_edge_fit_prefers_boundary_alignment_over_enclosing_segment_pixels() -> None:
    width, height = 128, 96
    source = np.zeros((height, width), dtype=np.uint8)
    cv2.line(source, (25, 35), (95, 35), 255, thickness=3)
    aligned = np.asarray(
        [[25.0, 35.0], [95.0, 35.0], [95.0, 85.0], [25.0, 85.0]], dtype=np.float64
    )
    shifted = np.asarray(
        [[25.0, 20.0], [95.0, 20.0], [95.0, 70.0], [25.0, 70.0]], dtype=np.float64
    )
    evidence = source
    source_area = int(np.count_nonzero(evidence))
    source_bounds = tuple(int(value) for value in cv2.boundingRect(evidence))
    occlusion_mask = np.zeros_like(source)

    aligned_score = _fit_score_projected(
        aligned,
        evidence,
        source_area,
        source_bounds,
        width,
        height,
        edge_only=True,
        edge_width_pixels=3,
        occlusion_mask=occlusion_mask,
    )
    shifted_score = _fit_score_projected(
        shifted,
        evidence,
        source_area,
        source_bounds,
        width,
        height,
        edge_only=True,
        edge_width_pixels=3,
        occlusion_mask=occlusion_mask,
    )

    assert aligned_score > shifted_score


def test_occlusion_fit_considers_the_quarter_turn_orientation_family() -> None:
    _, calibration = _calibration_result()
    true_polygon = project_fixed_card(
        calibration.table_to_image,
        (4.0, 0.0),
        0.0,
        calibration.card_short_size,
        calibration.card_long_size,
    )
    source_mask = rasterize_polygon(true_polygon, 1920, 1080)
    candidate = _Candidate(
        suggestion_id="quarter-turn",
        frame_id="frame-000",
        polygons=(true_polygon,),
        source_mask=source_mask,
        confidence=1.0,
        model_identity={},
        table_points=apply_homography(
            np.asarray(calibration.image_to_table), true_polygon
        ),
    )

    without_alternate = _fit_candidate(
        candidate,
        calibration,
        PoseFitRecipe(),
        1920,
        1080,
        occluder_mask=np.zeros_like(source_mask),
        initial_pose=(np.asarray([4.0, 0.0]), 90.0),
    )
    with_alternate = _fit_candidate(
        candidate,
        calibration,
        PoseFitRecipe(),
        1920,
        1080,
        occluder_mask=np.zeros_like(source_mask),
        initial_pose=(np.asarray([4.0, 0.0]), 90.0),
        try_quarter_turn=True,
    )

    assert without_alternate is not None
    assert with_alternate is not None
    assert with_alternate.score > without_alternate.score
    assert with_alternate.pose.rotation_degrees == 0.0
    assert len(with_alternate.search_evidence["orientation_hypotheses"]) == 2
    assert all(
        {"score", "center", "angle"} <= set(hypothesis)
        for hypothesis in with_alternate.search_evidence["orientation_hypotheses"]
    )


def test_half_occluded_card_fit_resolves_a_quarter_turn() -> None:
    _, calibration = _calibration_result()
    width, height = 1920, 1080
    true_polygon = project_fixed_card(
        calibration.table_to_image,
        (4.0, 0.0),
        0.0,
        calibration.card_short_size,
        calibration.card_long_size,
    )
    full_mask = rasterize_polygon(true_polygon, width, height)
    occluder = np.zeros_like(full_mask)
    center_image = apply_homography(
        calibration.table_to_image, np.asarray([[4.0, 0.0]], dtype=np.float64)
    )[0]
    cut_y = round(float(center_image[1]))
    cv2.rectangle(occluder, (0, cut_y), (width - 1, height - 1), 255, thickness=-1)
    visible_mask = np.where((full_mask > 0) & (occluder == 0), 255, 0).astype(np.uint8)
    contours, _ = cv2.findContours(visible_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    polygon = contours[0].reshape(-1, 2).astype(np.float64)
    candidate = _Candidate(
        suggestion_id="partial-quarter-turn",
        frame_id="frame-partial",
        polygons=(polygon,),
        source_mask=visible_mask,
        confidence=1.0,
        model_identity={},
        table_points=apply_homography(np.asarray(calibration.image_to_table), polygon),
    )

    initial_fit = _fit_candidate(candidate, calibration, PoseFitRecipe(), width, height)
    with_quarter_turn = _fit_candidate(
        candidate,
        calibration,
        PoseFitRecipe(),
        width,
        height,
        occluder_mask=occluder,
        initial_pose=(np.asarray([4.2, 0.15]), 90.0),
        try_quarter_turn=True,
    )
    single_orientation = _fit_candidate(
        candidate,
        calibration,
        PoseFitRecipe(),
        width,
        height,
        occluder_mask=occluder,
        initial_pose=(np.asarray([4.2, 0.15]), 90.0),
    )
    without_drift_penalty = _fit_candidate(
        candidate,
        calibration,
        PoseFitRecipe(occlusion_center_drift_penalty=0.0),
        width,
        height,
        occluder_mask=occluder,
        initial_pose=(np.asarray([4.2, 0.15]), 90.0),
        try_quarter_turn=True,
    )

    assert initial_fit is not None
    assert with_quarter_turn is not None
    assert single_orientation is not None
    assert without_drift_penalty is not None
    assert abs(initial_fit.pose.rotation_degrees) < 2.0
    assert with_quarter_turn.pose.rotation_degrees == 0.0
    assert single_orientation.pose.rotation_degrees == 0.0
    assert with_quarter_turn.score < without_drift_penalty.score


def _calibration_result() -> tuple[dict[str, object], object]:
    positions = [
        (0.0, 0.0),
        (4.0, 0.0),
        (8.0, 0.0),
        (0.0, 3.0),
        (4.0, 3.0),
        (8.0, 3.0),
        (0.0, 6.0),
        (4.0, 6.0),
        (8.0, 6.0),
        (2.0, 1.5),
        (6.0, 4.5),
        (10.0, 7.0),
    ]
    frames: list[dict[str, object]] = []
    for index, center in enumerate(positions):
        quad = project_fixed_card(TABLE_TO_IMAGE, center, (index % 3) * 8.0, 1.0, 1.5)
        frames.append(
            {
                "frame_id": f"frame-{index:03d}",
                "frame_index": index * 30,
                "timestamp_us": index * 1_000_000,
                "width": 1920,
                "height": 1080,
                "source_transform": "camera-transform-1",
                "predictions": [
                    {
                        "candidate_id": f"candidate-{index:03d}",
                        "confidence": 0.98,
                        "provider": "local-cascade",
                        "bundle": "bundle-1",
                        "polygon": quad.tolist(),
                        "full_card_outline_reference": quad.tolist(),
                    }
                ],
            }
        )
    result: dict[str, object] = {
        "recording_id": "recording-1",
        "source_revision": "generated-1",
        "frames": frames,
    }
    run = calibrate_recording(
        result,
        size_reference={
            prediction["candidate_id"]: prediction["full_card_outline_reference"]
            for frame in result["frames"]
            for prediction in frame["predictions"]
        },
        size_reference_revision="reviewed-test-outlines/v1",
    )
    assert run.calibration is not None
    return result, run.calibration


def test_event_000012_joint_search_fits_partial_card() -> None:
    fixture_path = Path(__file__).parent / "fixtures/card-scene-event-000012-pose-order.json"
    fixture = json.loads(fixture_path.read_text())
    identity = fixture["frame_identity"]
    width, height = identity["width"], identity["height"]
    predictions = []
    for candidate in fixture["detector_candidates"]:
        polygons = candidate["geometry"]["visible_region"]["polygons"]
        predictions.append(
            {
                "candidate_id": candidate["card_id"],
                "confidence": 1.0,
                "polygons": [
                    [
                        [point["x"] / 1000.0 * width, point["y"] / 1000.0 * height]
                        for point in polygon
                    ]
                    for polygon in polygons
                ],
            }
        )
    result = {
        "recording_id": fixture["lineage"]["recording_id"],
        "source_revision": fixture["calibration"]["source_revision"],
        "frames": [
            {
                "frame_id": fixture["lineage"]["source_frame_id"],
                "width": width,
                "height": height,
                "source_identity": identity,
                "predictions": predictions,
            }
        ],
    }

    run = initialize_card_scene(result, fixture["calibration"])

    saved = fixture["saved_scene"]
    assert run.scene is not None
    order = run.scene.stacking_order.card_ids
    assert [card[-4:] for card in order] == ["0000", "0003", "0002", "0001"]
    actual = {
        pose.source_suggestion_id: (pose.center, pose.rotation_degrees) for pose in run.scene.poses
    }
    expected = {
        pose["source_suggestion_id"]: (tuple(pose["center"]), pose["rotation_degrees"])
        for pose in saved["poses"]
    }
    target = next(key for key in actual if key.endswith("card-0003"))
    assert np.allclose(actual[target][0], (1.203976, 1.047226), atol=0.002)
    assert abs(actual[target][1] - 49.366157) < 0.1
    assert all(actual[key] == expected[key] for key in actual if key != target)
    joint = run.diagnostics["joint_scene_search"]
    assert joint["score"] > joint["baseline_score"]
    assert joint["changed_card_ids"] == [f"pose-{target}"]
    assert joint["margin"] is not None
    assert fixture["lineage"]["source_video_sha256"] == identity["source_video_sha256"]
    assert fixture["lineage"]["calibration_digest"] == fixture["calibration"]["calibration_digest"]
    experiment = fixture["bounded_mask_experiment"]
    assert experiment["limits"] == {
        "orientation_candidates_per_card": 2,
        "order_hypotheses": 2,
        "rendered_scenes": 4,
    }
    assert experiment["metric_scope"].endswith("not reviewed ground truth")
    assert [2, 3] not in experiment["order_hypotheses"]["proposed_edges"]
    hypotheses = experiment["hypotheses"]
    saved = next(
        item
        for item in hypotheses
        if item["orientation_index"] == 0 and item["order_name"] == "saved"
    )
    alternate = next(
        item
        for item in hypotheses
        if item["orientation_index"] == 1 and item["order_name"] == "proposed"
    )
    assert (
        sum(metric["iou"] for metric in alternate["metrics"]) / 4
        > sum(metric["iou"] for metric in saved["metrics"]) / 4
    )


def _frame_result(calibration_result: dict[str, object], frame_index: int = 0) -> dict[str, object]:
    return {
        "recording_id": "recording-1",
        "source_revision": "generated-1",
        "frames": [deepcopy(calibration_result["frames"][frame_index])],  # type: ignore[index]
    }


def test_initialization_is_repeatable_and_retains_model_suggestion_diagnostics() -> None:
    result, calibration = _calibration_result()
    selected = _frame_result(result)

    first = initialize_card_scene(selected, calibration)
    second = initialize_card_scene(selected, calibration)

    assert first.status == "initialized"
    assert first.scene is not None
    assert first.to_mapping() == second.to_mapping()
    assert first.scene.poses[0].source_suggestion_id == "candidate-000"
    assert first.suggestions[0]["model_identity"] == {
        "provider": "local-cascade",
        "bundle": "bundle-1",
    }
    assert first.scene.poses[0].fit_diagnostics_digest is not None
    assert first.diagnostics["initialized_count"] == 1


def test_pose_uses_calibrated_dimensions_and_low_confidence_is_visible() -> None:
    result, calibration = _calibration_result()
    selected = _frame_result(result)
    frame = selected["frames"][0]  # type: ignore[index]
    polygon = frame["predictions"][0]["polygon"]  # type: ignore[index]
    shortened = polygon[:3]
    frame["predictions"][0]["polygon"] = shortened  # type: ignore[index]

    run = initialize_card_scene(
        selected,
        calibration,
        recipe=PoseFitRecipe(low_confidence_score=0.99),
    )

    assert run.status == "initialized"
    assert run.scene is not None
    assert run.diagnostics["low_confidence_suggestion_ids"] == ["candidate-000"]
    pose = run.scene.poses[0]
    assert pose.rotation_degrees == pose.rotation_degrees % 180.0
    assert run.diagnostics["recipe"]["recipe_version"] == "fixed-card-pose-joint-search/v8"


def test_failed_candidate_does_not_block_a_scene_or_manual_addition() -> None:
    result, calibration = _calibration_result()
    selected = _frame_result(result)
    predictions = selected["frames"][0]["predictions"]  # type: ignore[index]
    predictions.append({"candidate_id": "malformed", "confidence": 0.99, "polygon": [[1, 2]]})

    run = initialize_card_scene(selected, calibration)

    assert run.status == "initialized"
    assert run.scene is not None
    assert run.diagnostics["failed_suggestion_ids"] == ["malformed"]
    failed = [item for item in run.fit_diagnostics if item.source_suggestion_id == "malformed"]
    assert len(failed) == 1
    assert failed[0].accepted is False
    assert failed[0].failure_reason


def test_duplicate_predictions_keep_evidence_but_use_one_pose() -> None:
    result, calibration = _calibration_result()
    selected = _frame_result(result)
    frame = selected["frames"][0]  # type: ignore[index]
    original = frame["predictions"][0]  # type: ignore[index]
    duplicate = deepcopy(original)
    duplicate["candidate_id"] = "candidate-duplicate"
    frame["predictions"] = [original, duplicate]  # type: ignore[index]

    run = initialize_card_scene(selected, calibration)

    assert run.scene is not None
    assert len(run.scene.poses) == 1
    assert len(run.suggestions) == 2
    assert run.diagnostics["duplicate_groups"][0]["suppressed_suggestion_ids"] == [
        "candidate-duplicate"
    ]


def test_low_detector_confidence_is_retained_and_cannot_occlude_another_card() -> None:
    result, calibration = _calibration_result()
    selected = _frame_result(result)
    frame = selected["frames"][0]  # type: ignore[index]
    original = frame["predictions"][0]  # type: ignore[index]
    weak = deepcopy(original)
    weak["candidate_id"] = "aaa-weak"
    weak["confidence"] = 0.6
    weak["polygon"] = [[point[0] + 35, point[1]] for point in weak["polygon"]]
    frame["predictions"] = [weak, original]  # type: ignore[index]
    baseline = initialize_card_scene(_frame_result(result), calibration)
    run = initialize_card_scene(selected, calibration)
    assert run.scene is not None and baseline.scene is not None
    assert len(run.scene.poses) == 2
    assert "aaa-weak" in run.diagnostics["low_confidence_suggestion_ids"]
    assert run.diagnostics["occlusion_refit"]["removed_boundary_fractions"]["candidate-000"] == 0
    assert run.scene.stacking_order.uncertain_edges == (("pose-aaa-weak", "pose-candidate-000"),)
    strong = next(p for p in run.scene.poses if p.source_suggestion_id == "candidate-000")
    assert strong.center == baseline.scene.poses[0].center
    assert strong.rotation_degrees == baseline.scene.poses[0].rotation_degrees


def test_contained_mask_is_retained_as_uncertain_evidence() -> None:
    large = np.zeros((100, 100), dtype=np.uint8)
    large[10:90, 10:90] = 255
    small = np.zeros_like(large)
    small[20:80, 20:80] = 255

    def fitted(card_id: str, mask: np.ndarray) -> _FittedCandidate:
        candidate = _Candidate(card_id, "frame", (), mask, 0.9, {}, np.empty((0, 2)))
        return _FittedCandidate(candidate, SimpleNamespace(card_id=card_id), None, 0.9, False, mask)

    result, reasons = _mark_contained_alternatives([fitted("large", large), fitted("small", small)])
    assert [item.low_confidence for item in result] == [False, True]
    assert reasons == [{"suggestion_id": "small", "contained_in_suggestion_id": "large"}]


def test_contained_fragment_requires_an_internal_straight_edge() -> None:
    large = np.zeros((160, 160), dtype=np.uint8)
    large[20:140, 20:140] = 255
    fragment = np.zeros_like(large)
    fragment[65:95, 50:110] = 255
    # An irregular, disconnected partial region remains an uncertain alternative.
    partial = np.zeros_like(large)
    cv2.circle(partial, (55, 55), 7, 255, -1)
    cv2.circle(partial, (75, 70), 6, 255, -1)

    def fitted(card_id: str, mask: np.ndarray) -> _FittedCandidate:
        candidate = _Candidate(card_id, "frame", (), mask, 0.9, {}, np.empty((0, 2)))
        return _FittedCandidate(candidate, SimpleNamespace(card_id=card_id), None, 0.9, False, mask)

    kept, decisions = _suppress_contained_fragments(
        [fitted("large", large), fitted("fragment", fragment), fitted("partial", partial)]
    )
    assert [item.pose.card_id for item in kept] == ["large", "partial"]
    assert decisions[0]["suggestion_id"] == "fragment"
    assert decisions[0]["contained_in_suggestion_id"] == "large"


def test_img_0661_contained_fragment_keeps_source_and_one_pose() -> None:
    path = Path(__file__).parent / "fixtures/card-scene-img-0661-027-fragment.json"
    fixture = json.loads(path.read_text())
    candidates = []
    for suggestion in fixture["suggestions"]:
        polygons = tuple(np.asarray(poly) for poly in suggestion["polygons"])
        mask = np.zeros((fixture["height"], fixture["width"]), dtype=np.uint8)
        for polygon in polygons:
            cv2.fillPoly(mask, [np.rint(polygon).astype(np.int32)], 255)
        card_id = suggestion["source_suggestion_id"]
        candidate = _Candidate(card_id, fixture["source_frame_id"], polygons, mask,
                               suggestion["confidence"], {}, np.empty((0, 2)))
        candidates.append(_FittedCandidate(
            candidate, SimpleNamespace(card_id=card_id), None, 0.9, False, mask,
        ))
    kept, decisions = _suppress_contained_fragments(candidates)
    assert len(kept) == 1 and kept[0].candidate.suggestion_id.endswith("0000")
    assert decisions[0]["suggestion_id"].endswith("0003")
    assert len(fixture["suggestions"]) == 2


def test_mask_area_seed_does_not_depend_on_polygon_vertex_density() -> None:
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:60, 30:70] = 255
    center = _mask_area_seed(mask, np.eye(3))
    np.testing.assert_allclose(center, [49.5, 39.5])


def test_img_0645_offset_uses_area_seed_for_the_real_mask() -> None:
    path = Path(__file__).parent / "fixtures/card-scene-img-0645-006-offset.json"
    fixture = json.loads(path.read_text())
    calibration = TablePlaneCalibration.create(
        calibration_revision_id="fixture-0645", recording_id=fixture["source_recording"],
        source_revision=fixture["detector_revision_id"], frame_width=fixture["width"],
        frame_height=fixture["height"], image_to_table=fixture["image_to_table"],
        table_to_image=fixture["table_to_image"], card_short_size=fixture["card_short_size"],
        card_long_size=fixture["card_long_size"], candidate_receipt_digests=(), diagnostics={},
    )
    suggestion = fixture["suggestion"]
    polygons = tuple(np.asarray(polygon) for polygon in suggestion["polygons"])
    mask = np.zeros((fixture["height"], fixture["width"]), dtype=np.uint8)
    for polygon in polygons:
        cv2.fillPoly(mask, [np.rint(polygon).astype(np.int32)], 255)
    candidate = _Candidate(
        suggestion["source_suggestion_id"], fixture["source_frame_id"], polygons, mask,
        suggestion["confidence"], {},
        apply_homography(calibration.image_to_table, np.concatenate(polygons)),
    )
    fitted = _fit_candidate(
        candidate, calibration, PoseFitRecipe(), fixture["width"], fixture["height"]
    )
    assert fitted is not None
    assert fitted.search_evidence["seed_source"] == "mask_area"
    assert fitted.score > 0.95
    assert abs(fitted.pose.center[0] - (-0.742)) < 0.04


def test_img_0661_partial_card_reports_competing_orientations() -> None:
    path = Path(__file__).parent / "fixtures/card-scene-img-0661-003-occlusion.json"
    fixture = json.loads(path.read_text())
    calibration = TablePlaneCalibration.create(
        calibration_revision_id="fixture-0661", recording_id=fixture["source_recording"],
        source_revision=fixture["detector_revision_id"], frame_width=fixture["width"],
        frame_height=fixture["height"], image_to_table=fixture["image_to_table"],
        table_to_image=fixture["table_to_image"], card_short_size=fixture["card_short_size"],
        card_long_size=fixture["card_long_size"], candidate_receipt_digests=(), diagnostics={},
    )
    suggestion = fixture["suggestion"]
    polygons = tuple(np.asarray(poly) for poly in suggestion["polygons"])
    mask = np.zeros((fixture["height"], fixture["width"]), dtype=np.uint8)
    for polygon in polygons:
        cv2.fillPoly(mask, [np.rint(polygon).astype(np.int32)], 255)
    candidate = _Candidate(
        suggestion["source_suggestion_id"], fixture["source_frame_id"], polygons, mask,
        suggestion["confidence"], {},
        apply_homography(calibration.image_to_table, np.concatenate(polygons)),
    )
    initial = _fit_candidate(
        candidate, calibration, PoseFitRecipe(), fixture["width"], fixture["height"]
    )
    assert initial is not None
    front = fixture["front_pose"]
    occluder = rasterize_polygon(
        project_fixed_card(calibration.table_to_image, front["center"], front["rotation_degrees"],
                           calibration.card_short_size, calibration.card_long_size),
        fixture["width"], fixture["height"],
    )
    refit = _fit_candidate(
        candidate, calibration, PoseFitRecipe(), fixture["width"], fixture["height"],
        occluder_mask=occluder,
        initial_pose=(np.asarray(initial.pose.center), initial.pose.rotation_degrees),
        try_quarter_turn=True,
    )
    assert refit is not None
    assert refit.search_evidence["pose_ambiguous"] is True
    assert len(refit.search_evidence["orientation_hypotheses"]) == 2


def test_all_failed_candidates_return_actionable_failure_without_a_scene() -> None:
    result, calibration = _calibration_result()
    selected = _frame_result(result)
    selected["frames"][0]["predictions"] = [  # type: ignore[index]
        {"candidate_id": "broken", "confidence": 0.99, "polygon": [[1, 2]]}
    ]

    run = initialize_card_scene(selected, calibration)

    assert run.status == "failed"
    assert run.scene is None
    assert run.failure is not None
    assert run.failure.code == "no_initialized_candidates"
