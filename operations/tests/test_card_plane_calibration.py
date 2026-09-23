from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from doko_operations.card_plane_calibration import (
    CALIBRATION_RUN_SCHEMA_V2,
    CalibrationFailure,
    CalibrationRecipe,
    CalibrationRevisionStore,
    CalibrationRun,
    calibrate_recording,
)
from doko_operations.card_plane_geometry import project_fixed_card
from doko_operations.pipeline_data import canonical_json_bytes

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from card_plane_calibration_baseline import _synthetic_result  # noqa: E402

TABLE_TO_IMAGE = np.asarray(
    [[120.0, 20.0, 420.0], [15.0, 100.0, 240.0], [0.0002, 0.0004, 1.0]],
    dtype=np.float64,
)


def _size_reference(result: dict[str, object]) -> dict[str, list[list[float]]]:
    return {
        prediction["candidate_id"]: prediction["full_card_outline_reference"]
        for frame in result["frames"]
        for prediction in frame["predictions"]
        if "full_card_outline_reference" in prediction
    }


def _calibrate_with_references(
    result: dict[str, object], *, recipe: CalibrationRecipe | None = None
):
    return calibrate_recording(
        result,
        recipe=recipe,
        size_reference=_size_reference(result),
        size_reference_revision="independent-test-outlines/v1",
    )


def _recording_result(
    *,
    positions: list[tuple[float, float]],
    recording_id: str = "recording-1",
    source_revision: str = "generated-1",
    transform: str = "camera-transform-1",
    duplicate: bool = False,
) -> dict[str, object]:
    frames = []
    for index, center in enumerate(positions):
        quad = project_fixed_card(TABLE_TO_IMAGE, center, (index % 3) * 8.0, 1.0, 1.5)
        frames.append(
            {
                "frame_id": f"frame-{index:03d}",
                "frame_index": index * 30,
                "timestamp_us": index * 1_000_000,
                "width": 1920,
                "height": 1080,
                "source_transform": transform,
                "predictions": [
                    {
                        "candidate_id": f"candidate-{index:03d}",
                        "confidence": 0.98,
                        "polygon": quad.tolist(),
                        "full_card_outline_reference": quad.tolist(),
                    }
                ],
            }
        )
    if duplicate:
        frames[0]["predictions"].append(
            {
                "candidate_id": "candidate-duplicate",
                "confidence": 0.97,
                "polygon": frames[0]["predictions"][0]["polygon"],
            }
        )
    return {
        "recording_id": recording_id,
        "source_revision": source_revision,
        "frames": frames,
    }


def test_calibration_is_repeatable_and_validates_held_out_candidates() -> None:
    result = _recording_result(
        positions=[
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
    )

    first = _calibrate_with_references(result)
    second = _calibrate_with_references(result)

    assert first.status == "published"
    assert first.calibration is not None
    assert first.to_mapping() == second.to_mapping()
    assert first.diagnostics["validation"]["held_out_count"] >= 2
    assert first.diagnostics["gates"]["held_out_boundary"] is True
    assert "absolute_size_reference" not in first.diagnostics["gates"]
    assert first.calibration.card_short_size == 1.0
    assert first.calibration.card_long_size == 1.5
    assert first.calibration_fit_candidate is not None
    assert first.to_mapping()["schema_version"] == "card-plane-calibration-run/v3"


def test_detector_only_fit_publishes_without_independent_size_reference(tmp_path: Path) -> None:
    result = _recording_result(
        positions=[
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
    )

    run = calibrate_recording(result)

    assert run.status == "published"
    assert run.failure is None
    assert run.calibration is not None
    assert run.calibration_fit_candidate is not None
    assert "absolute_size_reference" not in run.diagnostics["gates"]
    assert run.diagnostics["unavailable_gates"] == []
    assert run.diagnostics["processor_schema_version"] == "card-plane-calibration-processor/v10"
    assert run.diagnostics["validation"]["absolute_size"]["status"] == "unavailable"
    assert run.diagnostics["validation"]["absolute_size"]["short_side_bias"] is None
    assert run.diagnostics["fit_candidate_availability"]["available"] is True
    for item in run.diagnostics["candidate_evidence"]:
        assert "quality_weight" in item
        assert "residual" in item
        assert "fit_decision" in item
        assert "boundary_metrics" in item
        assert len(item["projected_full_card_outline"]) == 64
        assert all(len(point) == 2 for point in item["projected_full_card_outline"])
    assert CalibrationRun.from_mapping(run.to_mapping()).to_mapping() == run.to_mapping()

    compared = _calibrate_with_references(result)
    assert compared.status == "published"
    assert compared.calibration is not None
    assert compared.calibration.calibration_revision_id != run.calibration.calibration_revision_id
    store = CalibrationRevisionStore(tmp_path)
    assert store.publish(run).is_file()
    assert store.publish(compared).is_file()


def test_low_candidate_count_keeps_diagnostic_fit_and_distances() -> None:
    result = _recording_result(
        positions=[
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
            (0.0, 6.0),
            (4.0, 6.0),
            (8.0, 6.0),
        ]
    )

    run = _calibrate_with_references(result, recipe=CalibrationRecipe(minimum_candidates=20))

    assert run.status == "failed"
    assert run.failure is not None and run.failure.code == "insufficient_candidates"
    assert run.calibration_fit_candidate is not None
    assert run.diagnostics["validation"]["held_out_summary"]["count"] >= 2
    assert run.diagnostics["failed_gates"]


def test_single_card_returns_finite_diagnostic_candidate_without_holdout() -> None:
    result = _recording_result(positions=[(4.0, 3.0)])

    run = calibrate_recording(result)

    assert run.status == "failed"
    assert run.failure is not None and run.failure.code == "insufficient_candidates"
    assert run.calibration_fit_candidate is not None
    assert run.calibration_fit_candidate.fit_observation_ids == ("candidate-000",)
    assert run.diagnostics["validation"]["held_out_summary"]["count"] == 0
    evidence = run.diagnostics["candidate_evidence"][0]
    assert evidence["residual"]["median_boundary_distance_px"] >= 0


def test_calibration_accepts_generated_revision_identifiers() -> None:
    result = _recording_result(
        positions=[
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
            (0.0, 6.0),
            (4.0, 6.0),
            (8.0, 6.0),
        ],
        source_revision="visible-cards-visible_cards-run-5bd52a7b-3ba-attempt-1",
    )

    run = _calibrate_with_references(result)

    assert run.status == "published"


def test_calibration_tolerates_one_held_out_crop_quality_region() -> None:
    result = _recording_result(
        positions=[
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
    )
    result["frames"][0]["predictions"][0]["polygon"] = [
        [100.0, 100.0],
        [210.0, 100.0],
        [245.0, 310.0],
        [100.0, 310.0],
    ]

    calibration = _calibrate_with_references(result)

    assert calibration.status == "published"
    validation = calibration.diagnostics["validation"]
    assert validation["held_out_summary"]["pass_count"] < validation["held_out_count"]
    assert validation["held_out_summary"]["pass_fraction"] >= 0.60


def test_candidate_selection_rejects_nonstandard_apparent_card_scale() -> None:
    result = _recording_result(
        positions=[
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
        ]
    )
    for index, frame in enumerate(result["frames"]):
        frame["predictions"][0]["polygon"] = project_fixed_card(
            TABLE_TO_IMAGE,
            ((index % 3) * 4.0, (index // 3) * 3.0),
            (index % 3) * 8.0,
            1.0,
            0.5 if index % 2 else 1.5,
        ).tolist()

    calibration = calibrate_recording(result)

    assert calibration.status == "failed"
    assert calibration.failure is not None
    assert calibration.failure.code == "insufficient_candidates"
    evidence = {
        item["candidate_id"]: item for item in calibration.diagnostics["candidate_evidence"]
    }
    assert (
        sum(
            item["rejection_reason"] == "inconsistent_apparent_card_scale"
            for item in evidence.values()
        )
        >= 2
    )


def test_candidate_mining_rejects_overlaps_and_deduplicates_bins() -> None:
    result = _recording_result(
        positions=[(0.0, 0.0), (4.0, 0.0), (8.0, 0.0), (0.0, 3.0), (4.0, 3.0), (8.0, 3.0)],
        duplicate=True,
    )

    calibration = calibrate_recording(
        result,
        recipe=CalibrationRecipe(minimum_candidates=5, minimum_temporal_bins=3),
    )

    receipts = {receipt.candidate_id: receipt for receipt in calibration.candidate_receipts}
    assert receipts["candidate-duplicate"].accepted is False
    assert receipts["candidate-duplicate"].rejection_reason == "overlaps_prediction"
    assert calibration.diagnostics["candidate_yield"]["deduplicated_count"] == 6


def test_projected_card_rejects_overlap_with_other_detected_mask() -> None:
    result = _recording_result(
        positions=[
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
            (0.0, 6.0),
            (4.0, 6.0),
            (8.0, 6.0),
        ]
    )
    quad = np.asarray(result["frames"][0]["predictions"][0]["polygon"])
    edge_midpoint = (quad[1] + quad[2]) / 2
    tangent = (quad[2] - quad[1]) / np.linalg.norm(quad[2] - quad[1])
    inward = np.mean(quad, axis=0) - edge_midpoint
    inward /= np.linalg.norm(inward)
    edge = quad[2] - quad[1]
    incomplete = [
        quad[0].tolist(),
        quad[1].tolist(),
        (quad[1] + 0.05 * edge).tolist(),
        (quad[1] + 0.05 * edge + 12 * inward).tolist(),
        (quad[1] + 0.95 * edge + 12 * inward).tolist(),
        (quad[1] + 0.95 * edge).tolist(),
        quad[2].tolist(),
        quad[3].tolist(),
    ]
    neighbor = edge_midpoint + np.asarray(
        [
            tangent * along + inward * depth
            for along, depth in [(-65, -15), (65, -15), (65, 10), (-45, 10), (-45, 25), (-65, 25)]
        ]
    )
    result["frames"][0]["predictions"].append(
        {"candidate_id": "occluding-neighbor", "confidence": 0.95, "polygon": neighbor.tolist()}
    )

    ambiguous = calibrate_recording(result)
    ambiguous_receipts = {item.candidate_id: item for item in ambiguous.candidate_receipts}
    assert ambiguous_receipts["candidate-000"].accepted is True

    result["frames"][0]["predictions"][0]["polygon"] = incomplete

    run = calibrate_recording(result)
    receipts = {item.candidate_id: item for item in run.candidate_receipts}

    assert run.diagnostics["rejections"]["occluding-neighbor"]
    assert receipts["candidate-000"].rejection_reason == "occluded_by_card"
    assert "candidate-000" not in run.calibration_fit_candidate.fit_observation_ids
    assert "candidate-000" not in run.calibration_fit_candidate.held_out_observation_ids


def test_concave_visible_card_mask_is_not_used_for_calibration() -> None:
    result = _recording_result(
        positions=[
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
            (0.0, 6.0),
            (4.0, 6.0),
            (8.0, 6.0),
        ]
    )
    quad = np.asarray(result["frames"][0]["predictions"][0]["polygon"])
    edge = quad[2] - quad[1]
    center = np.mean(quad, axis=0)
    notch = (quad[1] + quad[2]) / 2
    notch += (center - notch) / np.linalg.norm(center - notch) * 28
    result["frames"][0]["predictions"][0]["polygon"] = [
        quad[0].tolist(),
        quad[1].tolist(),
        (quad[1] + 0.15 * edge).tolist(),
        notch.tolist(),
        (quad[1] + 0.85 * edge).tolist(),
        quad[2].tolist(),
        quad[3].tolist(),
    ]

    run = calibrate_recording(result)
    receipts = {item.candidate_id: item for item in run.candidate_receipts}

    assert receipts["candidate-000"].rejection_reason == "localized_inward_notch"
    assert (
        dict(receipts["candidate-000"].quality_metrics)["maximum_inward_defect_over_short_side"]
        > 0.12
    )
    assert dict(receipts["candidate-000"].quality_metrics)["convexity"] < 0.94
    assert "candidate-000" not in run.calibration_fit_candidate.fit_observation_ids


def test_candidate_evidence_carries_uniform_boundaries_and_quality() -> None:
    result, references, _metadata = _synthetic_result("clean-isolated")

    run = calibrate_recording(
        result,
        size_reference={key: value.tolist() for key, value in references.items()},
        size_reference_revision="synthetic-known-full-card-outlines/v1",
    )

    assert run.status == "published"
    assert len(run.candidate_receipts) == 12
    for receipt in run.candidate_receipts:
        assert len(receipt.boundary_samples) == 64
        assert dict(receipt.quality_metrics)["mask_quad_iou"] > 0.9
        assert dict(receipt.quality_metrics)["boundary_straightness"] > 0.9
        assert receipt.source_revision == result["source_revision"]
        assert receipt.source_frame_id.startswith("frame-")


@pytest.mark.parametrize(
    ("case_id", "candidate_ids", "reason"),
    [
        ("overlapping-pile", ["pile-card-04b"], "overlaps_prediction"),
        ("partial-card", ["card-04"], "inconsistent_apparent_card_scale"),
        ("weak-mask", ["card-05"], "confidence_below_threshold"),
        (
            "outlier",
            ["outlier-card-04", "outlier-card-09"],
            "inconsistent_apparent_card_scale",
        ),
        ("clipped-card", ["card-00"], "frame_boundary"),
    ],
)
def test_candidate_selection_rejects_frozen_m0_evidence_cases(
    case_id: str, candidate_ids: list[str], reason: str
) -> None:
    result, _references, _metadata = _synthetic_result(case_id)

    run = calibrate_recording(result)
    evidence = {item["candidate_id"]: item for item in run.diagnostics["candidate_evidence"]}

    for candidate_id in candidate_ids:
        assert evidence[candidate_id]["accepted"] is False
        assert evidence[candidate_id]["rejection_reason"] == reason
        assert evidence[candidate_id]["source_revision"] == result["source_revision"]
        assert evidence[candidate_id]["source_frame_id"]


def test_candidate_selection_keeps_full_edge_and_uniformly_shrunken_cards() -> None:
    edge_result, _references, _metadata = _synthetic_result("edge-of-view")
    shrink_result, _references, _metadata = _synthetic_result("shrink-10-percent")

    edge_run = calibrate_recording(edge_result)
    shrink_run = calibrate_recording(shrink_result)

    edge_evidence = {
        item["candidate_id"]: item for item in edge_run.diagnostics["candidate_evidence"]
    }
    shrink_evidence = {
        item["candidate_id"]: item for item in shrink_run.diagnostics["candidate_evidence"]
    }
    assert edge_evidence["card-00"]["accepted"] is True
    assert all(item["accepted"] for item in shrink_evidence.values())


def test_candidate_is_rejected_when_projected_full_outline_leaves_frame() -> None:
    result, references, _metadata = _synthetic_result("edge-of-view")
    complete_outline = references["card-00"].copy()
    complete_outline[:, 0] -= float(np.min(complete_outline[:, 0])) + 1.0
    center = np.mean(complete_outline, axis=0)
    partial_outline = center + 0.75 * (complete_outline - center)
    assert np.min(partial_outline[:, 0]) > 0.0

    result["frames"][0]["predictions"][0]["polygons"] = [partial_outline.tolist()]
    run = calibrate_recording(result)

    evidence = {item["candidate_id"]: item for item in run.diagnostics["candidate_evidence"]}[
        "card-00"
    ]
    receipt = {item.candidate_id: item for item in run.candidate_receipts}["card-00"]
    assert evidence["accepted"] is False
    assert evidence["rejection_reason"] == "frame_boundary"
    assert np.min(np.asarray(evidence["projected_full_card_outline"])[:, 0]) < 0.0
    assert receipt.accepted is False
    assert receipt.rejection_reason == "frame_boundary"
    assert run.calibration_fit_candidate is not None
    assert "card-00" not in run.calibration_fit_candidate.fit_observation_ids
    assert "card-00" not in run.calibration_fit_candidate.held_out_observation_ids


def test_candidate_selection_uses_common_local_geometry_and_rejects_fragments() -> None:
    result = _recording_result(
        positions=[
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
            (0.0, 6.0),
            (4.0, 6.0),
            (8.0, 6.0),
        ]
    )
    for frame in result["frames"]:
        prediction = frame["predictions"][0]
        polygon = prediction.pop("polygon")
        prediction["geometry"] = {"visible_region": {"polygons": [polygon]}}
        prediction["score"] = prediction.pop("confidence")
    fragmented = result["frames"][-1]["predictions"][0]
    fragmented["candidate_id"] = "fragmented-card"
    fragmented["geometry"]["visible_region"]["polygons"].append(
        [[1500.0, 800.0], [1540.0, 800.0], [1540.0, 850.0], [1500.0, 850.0]]
    )

    run = calibrate_recording(result)

    evidence = {item["candidate_id"]: item for item in run.diagnostics["candidate_evidence"]}
    assert evidence["fragmented-card"]["accepted"] is False
    assert evidence["fragmented-card"]["rejection_reason"] == "disconnected_components"
    assert all(
        len(receipt.boundary_samples) == 64
        for receipt in run.candidate_receipts
        if receipt.accepted
    )


@pytest.mark.parametrize("confidence", [None, float("nan"), 1.2])
def test_candidate_selection_records_invalid_confidence(confidence: float | None) -> None:
    result = _recording_result(
        positions=[
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
            (0.0, 6.0),
            (4.0, 6.0),
            (8.0, 6.0),
        ]
    )
    result["frames"][0]["predictions"][0]["confidence"] = confidence

    run = calibrate_recording(result)
    evidence = {item["candidate_id"]: item for item in run.diagnostics["candidate_evidence"]}

    assert evidence["candidate-000"]["accepted"] is False
    assert evidence["candidate-000"]["rejection_reason"] == "invalid_confidence"
    assert evidence["candidate-000"]["confidence"] is None


def test_candidate_selection_caps_frame_and_temporal_influence() -> None:
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
    ]
    frame_result = _recording_result(positions=positions)
    first_frame = frame_result["frames"][0]
    for index, frame in enumerate(frame_result["frames"][1:], start=1):
        prediction = dict(frame["predictions"][0])
        prediction["candidate_id"] = f"same-frame-{index:02d}"
        first_frame["predictions"].append(prediction)

    frame_run = calibrate_recording(frame_result)
    accepted_from_first = [
        receipt
        for receipt in frame_run.candidate_receipts
        if receipt.accepted and receipt.source_frame_id == "frame-000"
    ]
    assert len(accepted_from_first) <= 4
    assert any(
        item["rejection_reason"] == "frame_observation_cap"
        for item in frame_run.diagnostics["candidate_evidence"]
    )

    temporal_result = _recording_result(positions=positions)
    for frame in temporal_result["frames"]:
        frame["timestamp_us"] = 0
    temporal_run = calibrate_recording(temporal_result)
    accepted_in_interval = [
        receipt
        for receipt in temporal_run.candidate_receipts
        if receipt.accepted and receipt.temporal_bin == "t-0"
    ]
    assert len(accepted_in_interval) <= 8
    assert any(
        item["rejection_reason"] == "temporal_bin_observation_cap"
        for item in temporal_run.diagnostics["candidate_evidence"]
    )


def test_one_long_lived_card_cannot_satisfy_diversity_gates() -> None:
    result = _recording_result(positions=[(4.0, 3.0)] * 12)

    calibration = calibrate_recording(result)

    assert calibration.status == "failed"
    assert calibration.failure is not None
    assert calibration.failure.code == "insufficient_diversity"
    assert calibration.calibration_fit_candidate is not None
    assert calibration.diagnostics["validation"]["held_out_summary"]["count"] >= 2
    assert "table position" in calibration.failure.message
    accepted = [item for item in calibration.candidate_receipts if item.accepted]
    assert len(accepted) <= 8
    assert any(
        item.rejection_reason == "position_bin_observation_cap"
        for item in calibration.candidate_receipts
    )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("width", 1280, "changed_frame_dimensions"),
        ("source_transform", "camera-transform-2", "changed_source_transform"),
    ],
)
def test_recording_inconsistency_is_an_actionable_failure(
    field: str, value: object, code: str
) -> None:
    result = _recording_result(
        positions=[(0.0, 0.0), (4.0, 0.0), (8.0, 0.0), (0.0, 3.0), (4.0, 3.0), (8.0, 3.0)]
    )
    result["frames"][3][field] = value

    calibration = calibrate_recording(result)

    assert calibration.status == "failed"
    assert calibration.failure is not None
    assert calibration.failure.code == code
    assert calibration.failure.action
    assert calibration.calibration_fit_candidate is None
    assert calibration.diagnostics["fit_candidate_availability"]["reason"] == code


def test_held_out_boundary_warning_publishes_with_regional_metrics() -> None:
    result = _recording_result(
        positions=[
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
            (0.0, 6.0),
            (4.0, 6.0),
            (8.0, 6.0),
        ]
    )
    recipe = CalibrationRecipe(maximum_held_out_median_boundary_error_px=0.000001)

    run = _calibrate_with_references(result, recipe=recipe)

    assert run.status == "published"
    assert run.failure is None
    assert run.diagnostics["gates"]["held_out_boundary"] is False
    assert run.diagnostics["advisory_checks"]["held_out_boundary"] is False
    assert "held_out_boundary" not in run.diagnostics["failed_gates"]
    assert set(run.diagnostics["validation"]["regional_metrics"]) == {"center", "view_edges"}


def test_narrow_image_coverage_is_advisory() -> None:
    result = _recording_result(
        positions=[(0.0, 0.0), (4.0, 0.0), (8.0, 0.0), (0.0, 3.0), (4.0, 3.0), (8.0, 3.0)]
    )
    run = _calibrate_with_references(
        result,
        recipe=CalibrationRecipe(minimum_spatial_coverage_x=0.99),
    )

    assert run.status == "published"
    assert run.diagnostics["gates"]["spatial_coverage"] is False
    assert run.diagnostics["advisory_checks"]["spatial_coverage"] is False
    assert "spatial_coverage" not in run.diagnostics["failed_gates"]


def test_boundary_straightness_cutoff_allows_moderately_noisy_masks() -> None:
    assert CalibrationRecipe().minimum_boundary_straightness == 0.55


def test_inconsistent_fit_keeps_best_finite_candidate() -> None:
    result = _recording_result(
        positions=[
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
            (0.0, 6.0),
            (4.0, 6.0),
            (8.0, 6.0),
        ]
    )
    recipe = CalibrationRecipe(maximum_median_angle_error_degrees=0.000001)

    run = _calibrate_with_references(result, recipe=recipe)

    assert run.status == "failed"
    assert run.failure is not None and run.failure.code == "inconsistent_card_geometry"
    assert run.calibration_fit_candidate is not None
    assert run.diagnostics["gates"]["fit_quality"] is False
    assert run.diagnostics["validation"]["held_out_summary"]["count"] >= 2


def test_uniform_shrink_is_reported_but_does_not_block_publication() -> None:
    result, references, _metadata = _synthetic_result("shrink-10-percent")

    run = calibrate_recording(
        result,
        size_reference={key: value.tolist() for key, value in references.items()},
        size_reference_revision="synthetic-known-full-card-outlines/v1",
    )

    assert run.status == "published"
    assert run.failure is None
    assert run.calibration is not None
    assert run.calibration_fit_candidate is not None
    assert "absolute_size_reference" not in run.diagnostics["gates"]
    size = run.diagnostics["validation"]["absolute_size"]
    assert size["status"] == "failed"
    assert size["short_side_bias"] < -0.08
    assert size["area_bias"] < -0.15


def test_legacy_v2_calibration_run_remains_readable(tmp_path: Path) -> None:
    result = _recording_result(
        positions=[
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
            (0.0, 6.0),
            (4.0, 6.0),
            (8.0, 6.0),
        ]
    )
    mapping = _calibrate_with_references(result).to_mapping()
    legacy = dict(mapping)
    legacy.pop("calibration_fit_candidate")
    legacy["schema_version"] = CALIBRATION_RUN_SCHEMA_V2
    legacy.pop("run_digest")
    legacy["run_digest"] = hashlib.sha256(canonical_json_bytes(legacy)).hexdigest()

    loaded = CalibrationRun.from_mapping(legacy)

    assert loaded.run_schema_version == CALIBRATION_RUN_SCHEMA_V2
    assert loaded.calibration_fit_candidate is None
    assert loaded.to_mapping() == legacy
    assert loaded.run_digest != mapping["run_digest"]
    assert loaded.calibration is not None
    path = (
        tmp_path
        / "recording-1"
        / "table-plane-calibrations"
        / loaded.calibration.calibration_revision_id
        / "manifest.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(legacy), encoding="utf-8")

    restored = CalibrationRevisionStore(tmp_path).load(
        "recording-1", loaded.calibration.calibration_revision_id
    )

    assert restored.to_mapping() == legacy


def test_revision_store_does_not_overwrite_an_immutable_revision(tmp_path: Path) -> None:
    result = _recording_result(
        positions=[
            (0.0, 0.0),
            (4.0, 0.0),
            (8.0, 0.0),
            (0.0, 3.0),
            (4.0, 3.0),
            (8.0, 3.0),
            (0.0, 6.0),
            (4.0, 6.0),
            (8.0, 6.0),
        ]
    )
    run = _calibrate_with_references(result)
    store = CalibrationRevisionStore(tmp_path)

    path = store.publish(run)
    assert path.is_file()
    assert (
        store.load("recording-1", run.calibration.calibration_revision_id).to_mapping()
        == run.to_mapping()
    )

    with pytest.raises(CalibrationFailure, match="immutable"):
        tampered = json.loads(path.read_text(encoding="utf-8"))
        tampered["diagnostics"]["candidate_yield"]["accepted_count"] = 999
        path.write_text(json.dumps(tampered), encoding="utf-8")
        store.publish(run)
