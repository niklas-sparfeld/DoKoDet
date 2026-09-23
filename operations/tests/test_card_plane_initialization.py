from __future__ import annotations

from copy import deepcopy

import numpy as np

from doko_operations.card_plane_calibration import calibrate_recording
from doko_operations.card_plane_geometry import project_fixed_card
from doko_operations.card_plane_initialization import (
    PoseFitRecipe,
    initialize_card_scene,
)

TABLE_TO_IMAGE = np.asarray(
    [[120.0, 20.0, 420.0], [15.0, 100.0, 240.0], [0.0002, 0.0004, 1.0]],
    dtype=np.float64,
)


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
    assert run.diagnostics["recipe"]["recipe_version"] == "fixed-card-pose-grid-search/v1"


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


def test_duplicate_predictions_are_stable_and_overlapping_evidence_is_uncertain() -> None:
    result, calibration = _calibration_result()
    selected = _frame_result(result)
    frame = selected["frames"][0]  # type: ignore[index]
    original = frame["predictions"][0]  # type: ignore[index]
    duplicate = deepcopy(original)
    duplicate["candidate_id"] = "candidate-duplicate"
    frame["predictions"] = [original, duplicate]  # type: ignore[index]

    run = initialize_card_scene(selected, calibration)

    assert run.scene is not None
    assert run.scene.stacking_order.uncertain_edges == (
        ("pose-candidate-000", "pose-candidate-duplicate"),
    )
    assert run.scene.stacking_order.contradictions == ()
    assert run.diagnostics["order"]["edges"][0]["decision"] == "uncertain"


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
