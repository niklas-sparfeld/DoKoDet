from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from table_evidence_analyzer.pipeline_data import VisibleCardData

from doko_operations.card_plane_calibration import calibrate_recording
from doko_operations.card_plane_geometry import project_fixed_card
from doko_operations.card_plane_initialization import PoseFitRecipe
from doko_operations.proposed_card_scene_processor import (
    ProposedCardSceneProcessorError,
    build_proposed_card_scene_data,
    build_proposed_card_scenes,
    visible_card_data_to_local_result,
)

TABLE_TO_IMAGE = np.asarray(
    [[120.0, 20.0, 420.0], [15.0, 100.0, 240.0], [0.0002, 0.0004, 1.0]],
    dtype=np.float64,
)
DIGEST = "a" * 64


def test_parallel_frames_match_serial_results_and_failures() -> None:
    local_result = _local_result()
    calibration = calibrate_recording(local_result).calibration
    assert calibration is not None
    local_result["frames"] = local_result["frames"][:3]
    local_result["frames"][1]["predictions"][0]["polygon"] = []
    updates = []
    args = dict(
        detector_revision_id="visible-cards-001",
        detector_revision_digest=DIGEST,
        calibration=calibration,
        calibration_diagnostics={"status": "published"},
        pose_recipe=PoseFitRecipe(center_steps=3, angle_steps=3, refinement_stages=0),
    )
    serial = build_proposed_card_scene_data(local_result, max_workers=1, **args)
    parallel = build_proposed_card_scene_data(
        local_result, max_workers=2, progress_callback=lambda *args: updates.append(args), **args
    )
    assert parallel.to_mapping() == serial.to_mapping()
    assert parallel.frames[1].status == "unsupported"
    assert [item[1] for item in updates] == [1, 2, 3]


def _local_result(*, include_unresolvable: bool = False) -> dict[str, object]:
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
    frames = []
    for index, center in enumerate(positions):
        outline = project_fixed_card(TABLE_TO_IMAGE, center, (index % 3) * 8.0, 1.0, 1.5)
        frames.append(
            {
                "frame_id": f"frame-{index:03d}",
                "source_frame_digest": DIGEST,
                "frame_index": index * 30,
                "timestamp_us": index * 1_000_000,
                "width": 1920,
                "height": 1080,
                "source_transform": "fixture-transform/v1",
                "predictions": [
                    {
                        "candidate_id": f"candidate-{index:03d}",
                        "confidence": 0.98,
                        "polygon": outline.tolist(),
                        "full_card_outline_reference": outline.tolist(),
                    }
                ],
            }
        )
    result: dict[str, object] = {
        "recording_id": "recording-0073",
        "source_revision": "visible-cards-001",
        "frames": frames,
    }
    if include_unresolvable:
        result["unresolvable_frames"] = [
            {"frame_id": "event-without-frame", "reason": "source_frame_unavailable"}
        ]
    return result


def _size_reference(result: dict[str, object]) -> dict[str, list[list[float]]]:
    return {
        prediction["candidate_id"]: prediction["full_card_outline_reference"]
        for frame in result["frames"]
        for prediction in frame["predictions"]
    }


def _identity(frame_id: int = 0) -> dict[str, object]:
    return {
        "schema_version": "exact-event/v1",
        "source_video_sha256": DIGEST,
        "requested_time_us": frame_id * 1_000_000,
        "frame_index": frame_id * 30,
        "presentation_timestamp_us": frame_id * 1_000_000,
        "width": 1920,
        "height": 1080,
        "decoder_version": "decoder/v1",
        "transform_version": "fixture-transform/v1",
        "output_encoding": "jpeg",
        "content_type": "image/jpeg",
        "image_sha256": DIGEST,
        "policy": "exact-event/v1",
    }


def _pile() -> dict[str, object]:
    return {
        "pile_id": "pile-001",
        "geometry": {
            "kind": "pile-region/v1",
            "polygons": [
                [
                    {"x": 100, "y": 100},
                    {"x": 300, "y": 100},
                    {"x": 300, "y": 250},
                    {"x": 100, "y": 250},
                ]
            ],
        },
        "normalization": {"width": 1920, "height": 1080, "policy_id": "full-frame-0-1000/v1"},
        "source_candidates": [],
    }


def test_zero_card_recording_skips_calibration_and_preserves_piles() -> None:
    local_result = {
        "recording_id": "recording-0073",
        "source_revision": "visible-cards-001",
        "frames": [
            {
                "frame_id": "event-pile",
                "source_frame_digest": DIGEST,
                "source_identity": _identity(1),
                "outcome_status": "detected",
                "predictions": [],
                "pile_regions": [_pile()],
            },
            {
                "frame_id": "event-empty",
                "source_frame_digest": DIGEST,
                "source_identity": _identity(2),
                "outcome_status": "empty",
                "predictions": [],
                "pile_regions": [],
            },
        ],
    }

    result = build_proposed_card_scenes(
        local_result,
        detector_revision_id="visible-cards-001",
        detector_revision_digest=DIGEST,
    )

    assert result.status == "complete"
    assert result.calibration_run is None
    assert result.data is not None
    assert result.data.calibration is None
    assert result.data.calibration_revision_id is None
    assert result.data.calibration_diagnostics == {
        "status": "skipped",
        "reason": "no_card_candidates",
    }
    pile_frame, empty_frame = result.data.frames
    assert pile_frame.status == "no_cards_detected"
    assert pile_frame.proposal is None
    assert pile_frame.source_identity is not None
    assert pile_frame.source_identity.frame_index == 30
    assert pile_frame.detector_status == "detected"
    assert [item.pile_id for item in pile_frame.pile_regions] == ["pile-001"]
    assert empty_frame.status == "no_cards_detected"
    assert empty_frame.detector_status == "empty"
    assert empty_frame.pile_regions == ()


def test_mixed_recording_skips_pose_fit_only_for_zero_card_frame() -> None:
    local_result = _local_result()
    local_result["frames"].append(  # type: ignore[union-attr]
        {
            "frame_id": "event-pile-only",
            "source_frame_digest": DIGEST,
            "frame_index": 600,
            "timestamp_us": 20_000_000,
            "width": 1920,
            "height": 1080,
            "source_transform": "fixture-transform/v1",
            "source_identity": _identity(20),
            "outcome_status": "detected",
            "predictions": [],
            "pile_regions": [_pile()],
        }
    )

    result = build_proposed_card_scenes(
        local_result,
        detector_revision_id="visible-cards-001",
        detector_revision_digest=DIGEST,
    )

    assert result.status == "complete"
    assert result.calibration_run is not None
    assert result.data is not None
    assert result.data.calibration_revision_id is not None
    assert result.data.frames[0].status == "supported"
    assert result.data.frames[-1].status == "no_cards_detected"
    assert result.data.frames[-1].proposal is None
    assert [item.pile_id for item in result.data.frames[-1].pile_regions] == ["pile-001"]


def test_mixed_recording_keeps_a_real_pose_fit_failure_unsupported() -> None:
    local_result = _local_result()
    local_result["frames"].append(  # type: ignore[union-attr]
        {
            "frame_id": "event-bad-fit",
            "source_frame_digest": DIGEST,
            "frame_index": 600,
            "timestamp_us": 20_000_000,
            "width": 1920,
            "height": 1080,
            "source_transform": "fixture-transform/v1",
            "outcome_status": "detected",
            "predictions": [
                {
                    "candidate_id": "candidate-too-small",
                    "confidence": 0.98,
                }
            ],
        }
    )

    result = build_proposed_card_scenes(
        local_result,
        detector_revision_id="visible-cards-001",
        detector_revision_digest=DIGEST,
    )

    assert result.status == "partial"
    assert result.calibration_run is not None
    assert result.calibration_run.status == "published"
    assert result.data is not None
    frame = result.data.frames[-1]
    assert frame.frame_id == "event-bad-fit"
    assert frame.status == "unsupported"
    assert frame.proposal is not None
    assert frame.proposal.status == "unsupported"
    assert frame.unsupported_reason is not None


def test_real_calibration_gate_failure_stops_scene_publication() -> None:
    local_result = _local_result()
    local_result["frames"][-1]["source_transform"] = "changed-transform/v1"  # type: ignore[index]

    result = build_proposed_card_scenes(
        local_result,
        detector_revision_id="visible-cards-001",
        detector_revision_digest=DIGEST,
    )

    assert result.status == "failed"
    assert result.data is None
    assert result.calibration_run is not None
    assert result.calibration_run.failure is not None
    assert result.calibration_run.failure.code == "changed_source_transform"


def test_failed_detector_outcome_does_not_become_zero_card_success() -> None:
    with pytest.raises(ProposedCardSceneProcessorError, match="detector outcome event-001 failed"):
        visible_card_data_to_local_result(
            VisibleCardData.from_mapping(
                {
                    "schema_version": "visible-card-data/v2",
                    "outcomes": [
                        {
                            "event_id": "event-001",
                            "frame_identity": None,
                            "status": "failed",
                            "candidates": [],
                            "ignored_regions": [],
                            "pile_regions": [],
                            "pile_detection_status": "unsupported",
                            "error": "decoder failed",
                        }
                    ],
                }
            ),
            recording_id="recording-0073",
            source_revision="visible-cards-001",
        )


def test_unusable_detector_geometry_does_not_become_zero_card_success() -> None:
    content = VisibleCardData.from_mapping(
        {
            "schema_version": "visible-card-data/v2",
            "outcomes": [
                {
                    "event_id": "event-001",
                    "frame_identity": _identity(),
                    "status": "detected",
                    "candidates": [
                        {
                            "card_id": "card-001",
                            "geometry": {
                                "kind": "detector-box/v1",
                                "box_2d": {"x_min": 100, "y_min": 100, "x_max": 300, "y_max": 300},
                            },
                            "normalization": {
                                "width": 1920,
                                "height": 1080,
                                "policy_id": "full-frame-0-1000/v1",
                            },
                            "side": "unknown",
                            "model_scores": [],
                        }
                    ],
                    "ignored_regions": [],
                    "pile_regions": [],
                    "pile_detection_status": "unsupported",
                    "error": None,
                }
            ],
        }
    )

    with pytest.raises(ProposedCardSceneProcessorError, match="card-001 has unusable geometry"):
        visible_card_data_to_local_result(
            content, recording_id="recording-0073", source_revision="visible-cards-001"
        )


def test_proposals_are_repeatable_and_publish_one_calibration_revision(tmp_path: Path) -> None:
    local_result = _local_result()
    first = build_proposed_card_scenes(
        local_result,
        detector_revision_id="visible-cards-001",
        detector_revision_digest=DIGEST,
        calibration_size_reference=_size_reference(local_result),
        calibration_size_reference_revision="reviewed-full-card-outlines/v1",
    )
    repeated_result = _local_result()
    second = build_proposed_card_scenes(
        repeated_result,
        detector_revision_id="visible-cards-001",
        detector_revision_digest=DIGEST,
        calibration_size_reference=_size_reference(repeated_result),
        calibration_size_reference_revision="reviewed-full-card-outlines/v1",
    )

    assert first.status == "complete"
    assert first.data is not None
    assert first.to_mapping() == second.to_mapping()
    assert first.data.frames[0].status == "supported"
    assert first.data.frames[0].proposal is not None
    assert first.data.frames[0].proposal.detector_revision_id == "visible-cards-001"

    from doko_operations.card_plane_calibration import CalibrationRevisionStore

    stored = CalibrationRevisionStore(tmp_path)
    run = first.calibration_run
    stored.publish(run)
    assert stored.load("recording-0073", run.calibration.calibration_revision_id).to_mapping() == (
        run.to_mapping()
    )


def test_proposal_progress_reports_calibration_steps_and_each_frame() -> None:
    local_result = _local_result(include_unresolvable=True)
    updates: list[tuple[str, int, int, str, int, int]] = []

    result = build_proposed_card_scenes(
        local_result,
        detector_revision_id="visible-cards-001",
        detector_revision_digest=DIGEST,
        progress_callback=lambda *update: updates.append(update),
    )

    assert result.status == "partial"
    assert updates[0] == ("calibration", 0, 3, "Calibrating virtual cards", 1, 3)
    assert updates[1] == ("initialization", 0, 13, "Initializing virtual cards", 2, 3)
    assert updates[-2] == (
        "initialization",
        13,
        13,
        "Initializing virtual card frame event-without-frame",
        2,
        3,
    )
    assert updates[-1] == ("publishing", 2, 3, "Publishing proposed card scenes", 3, 3)


def test_proposal_uses_calibration_without_independent_size_reference() -> None:
    result = build_proposed_card_scenes(
        _local_result(),
        detector_revision_id="visible-cards-001",
        detector_revision_digest=DIGEST,
    )

    assert result.status == "complete"
    assert result.data is not None
    assert result.calibration_run.calibration is not None
    assert result.calibration_run.calibration_fit_candidate is not None
    assert result.calibration_run.failure is None
    assert result.calibration_run.diagnostics["validation"]["held_out_summary"]["count"] >= 2


def test_unresolvable_source_frame_is_explicitly_unsupported() -> None:
    local_result = _local_result(include_unresolvable=True)
    result = build_proposed_card_scenes(
        local_result,
        detector_revision_id="visible-cards-001",
        detector_revision_digest=DIGEST,
        calibration_size_reference=_size_reference(local_result),
        calibration_size_reference_revision="reviewed-full-card-outlines/v1",
    )

    assert result.status == "partial"
    assert result.data is not None
    frame = result.data.frames[-1]
    assert frame.frame_id == "event-without-frame"
    assert frame.status == "unsupported"
    assert frame.proposal is None
    assert frame.source_frame_digest is None


def test_generated_revision_and_candidate_identifiers_with_underscores_are_supported() -> None:
    result = _local_result()
    result["source_revision"] = "visible-cards_visible_cards-run-0073-attempt-1"
    result["frames"][0]["predictions"][0]["candidate_id"] = (
        "visible_cards-run-0073-event-000000-card-0000"
    )

    proposal = build_proposed_card_scenes(
        result,
        detector_revision_id="visible-cards_visible_cards-run-0073-attempt-1",
        detector_revision_digest=DIGEST,
        calibration_size_reference=_size_reference(result),
        calibration_size_reference_revision="reviewed-full-card-outlines/v1",
    )

    assert proposal.status == "complete"
    assert proposal.data is not None
    assert proposal.data.frames[0].status == "supported"


def test_changed_initializer_recipe_publishes_changed_proposal_with_same_lineage() -> None:
    local_result = _local_result()
    baseline = build_proposed_card_scenes(
        local_result,
        detector_revision_id="visible-cards-001",
        detector_revision_digest=DIGEST,
        calibration_size_reference=_size_reference(local_result),
        calibration_size_reference_revision="reviewed-full-card-outlines/v1",
    )
    changed_result = _local_result()
    changed = build_proposed_card_scenes(
        changed_result,
        detector_revision_id="visible-cards-001",
        detector_revision_digest=DIGEST,
        calibration_size_reference=_size_reference(changed_result),
        calibration_size_reference_revision="reviewed-full-card-outlines/v1",
        pose_recipe=PoseFitRecipe(center_search_radius=0.30),
    )

    assert baseline.data is not None
    assert changed.data is not None
    assert baseline.data.detector_revision_id == changed.data.detector_revision_id
    assert baseline.data.detector_revision_digest == changed.data.detector_revision_digest
    assert baseline.data.data_digest != changed.data.data_digest
    assert baseline.data.frames[0].proposal is not None
    assert changed.data.frames[0].proposal is not None
    assert (
        baseline.data.frames[0].proposal.proposal_digest
        != changed.data.frames[0].proposal.proposal_digest
    )


def test_visible_card_revision_conversion_preserves_frame_and_detector_lineage() -> None:
    content = VisibleCardData.from_mapping(
        {
            "schema_version": "visible-card-data/v1",
            "outcomes": [
                {
                    "event_id": "event-001",
                    "frame_identity": {
                        "schema_version": "exact-event/v1",
                        "source_video_sha256": DIGEST,
                        "requested_time_us": 1_000_000,
                        "frame_index": 30,
                        "presentation_timestamp_us": 1_000_000,
                        "width": 1920,
                        "height": 1080,
                        "decoder_version": "decoder/v1",
                        "transform_version": "transform/v1",
                        "output_encoding": "jpeg",
                        "content_type": "image/jpeg",
                        "image_sha256": DIGEST,
                        "policy": "exact-event/v1",
                    },
                    "status": "detected",
                    "candidates": [
                        {
                            "card_id": "card-001",
                            "geometry": {
                                "kind": "visible-region/v1",
                                "visible_region": {
                                    "polygons": [
                                        [
                                            {"x": 100, "y": 100},
                                            {"x": 500, "y": 100},
                                            {"x": 500, "y": 500},
                                            {"x": 100, "y": 500},
                                        ]
                                    ]
                                },
                            },
                            "normalization": {
                                "width": 1920,
                                "height": 1080,
                                "policy_id": "full-frame-0-1000/v1",
                            },
                            "side": "unknown",
                            "model_scores": [
                                {"producer_id": "local-rfdetr-fine-frame", "score": 0.97}
                            ],
                        }
                    ],
                    "ignored_regions": [],
                    "error": None,
                }
            ],
        }
    )
    local = visible_card_data_to_local_result(
        content, recording_id="recording-0073", source_revision="visible-cards-001"
    )

    assert local["recording_id"] == "recording-0073"
    assert local["source_revision"] == "visible-cards-001"
    assert local["frames"][0]["source_frame_digest"] == DIGEST  # type: ignore[index]
    assert local["frames"][0]["predictions"][0]["confidence"] == 0.97  # type: ignore[index]
