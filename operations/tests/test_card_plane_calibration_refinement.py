from __future__ import annotations

from pathlib import Path

import numpy as np
from table_evidence_analyzer.card_scene_contract import (
    AnchorCommand,
    AnchorObservation,
    CardReviewState,
    CardSceneDraft,
    FrameReviewCompletion,
    ReviewedCardSceneRecord,
)

from doko_operations.card_plane_calibration import calibrate_recording
from doko_operations.card_plane_calibration_refinement import (
    CalibrationDraftStore,
    apply_anchor_command_to_draft,
    build_calibration_draft,
    build_calibration_preview,
    reflow_card_scene_draft,
)
from doko_operations.card_plane_geometry import project_fixed_card
from doko_operations.proposed_card_scene_processor import build_proposed_card_scene_data

TABLE_TO_IMAGE = np.asarray(
    [[120.0, 20.0, 420.0], [15.0, 100.0, 240.0], [0.0002, 0.0004, 1.0]],
    dtype=np.float64,
)


def _result() -> dict[str, object]:
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
    frames = []
    for index, center in enumerate(positions):
        frames.append(
            {
                "frame_id": f"frame-{index:03d}",
                "timestamp_us": index * 1_000_000,
                "frame_index": index * 30,
                "width": 1920,
                "height": 1080,
                "source_transform": "camera-1",
                "predictions": [
                    {
                        "candidate_id": f"anchor-{index:03d}",
                        "confidence": 0.99,
                        "polygon": project_fixed_card(
                            TABLE_TO_IMAGE, center, (index % 3) * 8.0, 1.0, 1.5
                        ).tolist(),
                    }
                ],
            }
        )
    return {"recording_id": "recording-1", "source_revision": "detector-1", "frames": frames}


def _draft() -> tuple[object, object]:
    result = _result()
    run = calibrate_recording(result)
    assert run.calibration is not None
    anchors = tuple(
        AnchorObservation.create(
            anchor_id=f"anchor-{index:03d}",
            card_id=f"card-{index:03d}",
            source_frame_id=f"frame-{index:03d}",
            source_frame_digest=f"{index + 1:064x}",
            detector_revision_id="detector-1",
            quadrilateral=frame["predictions"][0]["polygon"],
            confidence=0.99,
            temporal_bin=f"t-{index}",
            table_region_bin=f"r-{index}",
            scale_bin="s-1",
            orientation_bin=f"o-{index % 3}",
            eligible=True,
            eligibility_reason=None,
        )
        for index, frame in enumerate(result["frames"])
    )
    draft = build_calibration_draft(
        draft_id="draft-1",
        recording_id="recording-1",
        detector_revision_id="detector-1",
        detector_revision_digest="a" * 64,
        base_calibration=run.calibration,
        anchors=anchors,
        source_frame_digests={
            anchor.source_frame_id: anchor.source_frame_digest for anchor in anchors
        },
    )
    return draft, run.calibration


def test_preview_is_repeatable_and_reports_recording_impact() -> None:
    draft, calibration = _draft()
    scenes = [
        {
            "frame_id": "frame-000",
            "card_scene": {
                "proposal": {
                    "initialized_scene": {
                        "poses": [
                            {
                                "card_id": "card-000",
                                "center": [2.0, 2.0],
                                "rotation_degrees": 0.0,
                            }
                        ]
                    }
                }
            },
        }
    ]

    first = build_calibration_preview(draft, calibration, frame_scenes=scenes)
    second = build_calibration_preview(draft, calibration, frame_scenes=scenes)

    assert first.to_mapping() == second.to_mapping()
    assert first.candidate_calibration is not None
    assert first.accepted_anchor_count == 0
    assert first.changed_frame_ids == ("frame-000",)
    assert first.most_affected_frame_ids == ("frame-000",)


def test_anchor_decision_changes_fit_influence_and_draft_digest() -> None:
    draft, _calibration = _draft()
    command = AnchorCommand.create(
        command_id="command-1",
        sequence=1,
        expected_draft_revision=0,
        anchor_id="anchor-000",
        operation="set_state",
        state="accepted",
        operator_id="operator-1",
    )
    updated = apply_anchor_command_to_draft(draft, command)

    before = {item.anchor_id: item.base_weight for item in draft.anchors}
    after = {item.anchor_id: item.base_weight for item in updated.anchors}
    assert before["anchor-000"] == 1.0
    assert after["anchor-000"] == 4.0
    assert updated.revision == 1
    assert updated.draft_digest != draft.draft_digest


def test_duplicate_anchor_command_is_idempotent() -> None:
    draft, _calibration = _draft()
    command = AnchorCommand.create(
        command_id="command-1",
        sequence=1,
        expected_draft_revision=0,
        anchor_id="anchor-000",
        operation="set_state",
        state="accepted",
        operator_id="operator-1",
    )

    updated = apply_anchor_command_to_draft(draft, command)

    assert apply_anchor_command_to_draft(updated, command) == updated


def test_pinned_conflict_blocks_preview() -> None:
    draft, calibration = _draft()
    first = draft.anchors[0]
    second = AnchorObservation.create(
        anchor_id="anchor-conflict",
        card_id="card-conflict",
        source_frame_id=first.source_frame_id,
        source_frame_digest=first.source_frame_digest,
        detector_revision_id=first.detector_revision_id,
        quadrilateral=[
            [point[0] + 30.0, point[1] + 30.0] for point in first.quadrilateral
        ],
        confidence=0.99,
        temporal_bin=first.temporal_bin,
        table_region_bin=first.table_region_bin,
        scale_bin=first.scale_bin,
        orientation_bin=first.orientation_bin,
        eligible=True,
        eligibility_reason=None,
        state="pinned",
        weight_class="accepted",
    )
    first_pinned = AnchorObservation.create(
        anchor_id=first.anchor_id,
        card_id=first.card_id,
        source_frame_id=first.source_frame_id,
        source_frame_digest=first.source_frame_digest,
        detector_revision_id=first.detector_revision_id,
        quadrilateral=first.quadrilateral,
        confidence=first.confidence,
        temporal_bin=first.temporal_bin,
        table_region_bin=first.table_region_bin,
        scale_bin=first.scale_bin,
        orientation_bin=first.orientation_bin,
        eligible=True,
        eligibility_reason=None,
        state="pinned",
        weight_class="accepted",
    )
    conflicted = type(draft).create(
        draft_id=draft.draft_id,
        recording_id=draft.recording_id,
        detector_revision_id=draft.detector_revision_id,
        detector_revision_digest=draft.detector_revision_digest,
        base_calibration_revision_id=draft.base_calibration_revision_id,
        base_calibration_digest=draft.base_calibration_digest,
        source_frame_digests=draft.source_frame_digests,
        anchors=(first_pinned, second, *draft.anchors[1:]),
        commands=(),
    )

    preview = build_calibration_preview(conflicted, calibration)

    assert preview.status == "blocked"
    assert preview.failure is not None
    assert preview.failure.code == "conflicting_pinned_anchors"


def test_draft_store_round_trips(tmp_path: Path) -> None:
    draft, _calibration = _draft()
    store = CalibrationDraftStore(tmp_path)

    path = store.publish(draft)

    assert path.is_file()
    assert store.load("recording-1", "draft-1") == draft


def test_reflow_refits_reviewed_scene_under_new_calibration() -> None:
    result = _result()
    for frame in result["frames"]:
        frame["source_frame_digest"] = "a" * 64
    run = calibrate_recording(result)
    assert run.calibration is not None
    data = build_proposed_card_scene_data(
        result,
        detector_revision_id="detector-1",
        detector_revision_digest="a" * 64,
        calibration=run.calibration,
        calibration_diagnostics={"source": "test"},
    )
    source_frame = data.frames[0]
    assert source_frame.proposal is not None
    initial = source_frame.proposal
    assert initial.initialized_scene is not None
    scene = initial.initialized_scene
    scene_ids = [pose["card_id"] for pose in scene["poses"]]
    reviewed = ReviewedCardSceneRecord.create(
        proposal_id=initial.proposal_id,
        scene=scene,
        decision="accepted",
    )
    current = CardSceneDraft.create(
        proposal=initial,
        reviewed=reviewed,
        card_states=tuple(
            CardReviewState.create(
                card_id=card_id,
                source="proposal",
                proposal_id=initial.proposal_id,
                state="accepted",
            )
            for card_id in scene_ids
        ),
        completion=FrameReviewCompletion.create(state="complete", unresolved_card_ids=()),
        proposal_revision_id="proposal-old",
        proposal_data_digest=data.data_digest,
        projection={
            "table_to_image_homography": [list(row) for row in run.calibration.table_to_image],
            "card_short_size": run.calibration.card_short_size,
            "card_long_size": run.calibration.card_long_size,
        },
    )
    target = type(run.calibration).create(
        calibration_revision_id="calibration-target",
        recording_id=run.calibration.recording_id,
        source_revision=run.calibration.source_revision,
        frame_width=run.calibration.frame_width,
        frame_height=run.calibration.frame_height,
        image_to_table=run.calibration.image_to_table,
        table_to_image=run.calibration.table_to_image,
        card_short_size=run.calibration.card_short_size,
        card_long_size=run.calibration.card_long_size,
        candidate_receipt_digests=run.calibration.candidate_receipt_digests,
        diagnostics=run.calibration.diagnostics,
    )
    target_data = build_proposed_card_scene_data(
        result,
        detector_revision_id="detector-1",
        detector_revision_digest="a" * 64,
        calibration=target,
        calibration_diagnostics={"source": "test"},
    )
    target_proposal = target_data.frames[0].proposal
    assert target_proposal is not None
    reflowed = reflow_card_scene_draft(
        current,
        target_proposal,
        {
            "table_to_image_homography": [list(row) for row in target.table_to_image],
            "card_short_size": target.card_short_size,
            "card_long_size": target.card_long_size,
        },
        run.calibration,
        target,
        target_proposal_revision_id="proposal-target",
        target_proposal_data_digest=target_data.data_digest,
    )

    assert reflowed.draft.proposal.calibration_revision_id == "calibration-target"
    assert reflowed.draft.proposal_revision_id == "proposal-target"
    assert reflowed.draft.reviewed is not None
    assert (
        reflowed.draft.reviewed.scene["calibration_revision_id"] == "calibration-target"
    )
    assert reflowed.draft.completion.state == "complete"
