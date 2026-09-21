from __future__ import annotations

import pytest

from table_evidence_analyzer.card_scene_contract import (
    ANCHOR_BASE_WEIGHTS,
    AnchorCommand,
    AnchorObservation,
    CalibrationDraft,
    CalibrationGate,
    CalibrationPreview,
    CalibrationReflowReceipt,
    CardReviewState,
    CardSceneContractError,
    CardSceneDraft,
    FrameReviewCompletion,
    ProposedCardScene,
    ReviewedCardSceneRecord,
    StaleCalibrationEvidenceError,
    anchor_fit_contributions,
    calibration_refinement_contract_manifest,
    constrain_anchor_quad,
    deduplicate_anchor_observations,
    validate_calibration_draft_lineage,
    validate_pinned_anchor_conflicts,
)


def _scene(*card_ids: str) -> dict[str, object]:
    return {
        "schema_version": "reviewed-card-scene/v1",
        "poses": [{"card_id": card_id} for card_id in card_ids],
    }


def _proposal(*card_ids: str) -> ProposedCardScene:
    return ProposedCardScene.create(
        proposal_id="proposal-1",
        source_frame_id="frame-1",
        source_frame_digest="a" * 64,
        detector_revision_id="detector-1",
        detector_revision_digest="b" * 64,
        calibration_revision_id="calibration-1",
        calibration_digest="c" * 64,
        initializer_recipe_version="initializer/v1",
        status="supported",
        initialized_scene=_scene(*card_ids),
        fit_diagnostics={"residual": 0.12},
    )


def _anchor(
    anchor_id: str,
    *,
    state: str = "candidate",
    weight_class: str = "candidate",
    key: tuple[str, str, str, str] = ("t-1", "r-1", "s-1", "o-1"),
    x: float = 0.0,
    eligible: bool = True,
) -> AnchorObservation:
    return AnchorObservation.create(
        anchor_id=anchor_id,
        card_id=f"card-{anchor_id}",
        source_frame_id=f"frame-{anchor_id}",
        source_frame_digest="a" * 64,
        detector_revision_id="detector-1",
        quadrilateral=[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1]],
        confidence=0.9,
        temporal_bin=key[0],
        table_region_bin=key[1],
        scale_bin=key[2],
        orientation_bin=key[3],
        eligible=eligible,
        eligibility_reason=None if eligible else "clipped at frame boundary",
        state=state,
        weight_class=weight_class,
    )


def test_pending_proposal_is_not_reviewed_geometry() -> None:
    proposal = _proposal("card-1")
    draft = CardSceneDraft.create(
        proposal=proposal,
        reviewed=None,
        card_states=(
            CardReviewState.create(
                card_id="card-1",
                source="proposal",
                proposal_id=proposal.proposal_id,
                state="pending",
            ),
        ),
        completion=FrameReviewCompletion.create(state="pending", unresolved_card_ids=("card-1",)),
    )

    restored = CardSceneDraft.from_mapping(draft.to_mapping())

    assert restored.reviewed is None
    assert restored.card_states[0].state == "pending"
    assert restored.completion.state == "pending"


def test_accepted_adjusted_and_rejected_states_define_reviewed_card_ids() -> None:
    proposal = _proposal("card-1", "card-2", "card-3")
    reviewed = ReviewedCardSceneRecord.create(
        proposal_id=proposal.proposal_id,
        scene=_scene("card-1", "card-2"),
        decision="adjusted",
    )
    draft = CardSceneDraft.create(
        proposal=proposal,
        reviewed=reviewed,
        card_states=(
            CardReviewState.create(
                card_id="card-1",
                source="proposal",
                proposal_id=proposal.proposal_id,
                state="accepted",
            ),
            CardReviewState.create(
                card_id="card-2",
                source="proposal",
                proposal_id=proposal.proposal_id,
                state="adjusted",
            ),
            CardReviewState.create(
                card_id="card-3",
                source="proposal",
                proposal_id=proposal.proposal_id,
                state="rejected",
            ),
        ),
        completion=FrameReviewCompletion.create(state="complete", unresolved_card_ids=()),
        draft_revision=4,
    )

    assert draft.reviewed is reviewed
    assert set(draft.reviewed.card_ids) == {"card-1", "card-2"}
    assert draft.to_mapping()["draft_digest"] == draft.draft_digest


def test_anchor_states_weights_deduplication_and_exclusion_are_deterministic() -> None:
    anchors = (
        _anchor("candidate-low", key=("t-1", "r-1", "s-1", "o-1")),
        _anchor("candidate-high", key=("t-1", "r-1", "s-1", "o-1")),
        _anchor(
            "accepted", state="accepted", weight_class="accepted", key=("t-2", "r-1", "s-1", "o-1")
        ),
        _anchor(
            "adjusted", state="adjusted", weight_class="adjusted", key=("t-3", "r-1", "s-1", "o-1")
        ),
        _anchor(
            "pinned", state="pinned", weight_class="accepted", key=("t-4", "r-1", "s-1", "o-1")
        ),
        _anchor("excluded", state="excluded", eligible=False, key=("t-5", "r-1", "s-1", "o-1")),
    )
    selected, rejected = deduplicate_anchor_observations(anchors)
    contributions = anchor_fit_contributions(anchors)

    assert {item.anchor_id for item in selected} == {
        "candidate-high",
        "accepted",
        "adjusted",
        "pinned",
    }
    assert rejected == ("candidate-low",)
    assert {item.anchor_id: item.base_weight for item in contributions} == {
        "candidate-high": ANCHOR_BASE_WEIGHTS["candidate"],
        "accepted": ANCHOR_BASE_WEIGHTS["accepted"],
        "adjusted": ANCHOR_BASE_WEIGHTS["adjusted"],
        "pinned": ANCHOR_BASE_WEIGHTS["accepted"],
    }


def test_conflicting_pins_and_stale_lineage_are_actionable() -> None:
    pins = (
        _anchor("pin-a", state="pinned", weight_class="accepted", x=0.0),
        _anchor("pin-b", state="pinned", weight_class="accepted", x=10.0),
    )
    with pytest.raises(CardSceneContractError, match="conflicting pinned anchors"):
        validate_pinned_anchor_conflicts(pins)

    command = AnchorCommand.create(
        command_id="command-1",
        sequence=1,
        expected_draft_revision=0,
        anchor_id="pin-a",
        operation="set_state",
        state="accepted",
        operator_id="operator-1",
    )
    draft = CalibrationDraft.create(
        draft_id="draft-1",
        recording_id="recording-1",
        detector_revision_id="detector-1",
        detector_revision_digest="b" * 64,
        base_calibration_revision_id="calibration-1",
        base_calibration_digest="c" * 64,
        source_frame_digests={"frame-pin-a": "a" * 64},
        anchors=(pins[0],),
        commands=(command,),
    )
    with pytest.raises(StaleCalibrationEvidenceError, match="stale_detector_revision"):
        validate_calibration_draft_lineage(
            draft,
            detector_revision_id="detector-2",
            detector_revision_digest="d" * 64,
            calibration_revision_id="calibration-1",
            calibration_digest="c" * 64,
            source_frame_digests={"frame-pin-a": "a" * 64},
        )


def test_corner_constraints_keep_the_opposite_corner_and_command_is_one_gesture() -> None:
    corners = ((0.0, 0.0), (1.5, 0.0), (1.5, 1.0), (0.0, 1.0))
    for constraint in ("diagonal", "card_x", "card_y"):
        result = constrain_anchor_quad(
            corners, moved_corner=0, pointer=(-1.5, -1.0), constraint=constraint
        )
        assert result[2] == corners[2]
        assert len(result) == 4

    command = AnchorCommand.create(
        command_id="command-corner-1",
        sequence=1,
        expected_draft_revision=0,
        anchor_id="anchor-1",
        operation="set_corners",
        state="adjusted",
        moved_corner=0,
        constraint="diagonal",
        corners=corners,
        operator_id="operator-1",
    )
    assert AnchorCommand.from_mapping(command.to_mapping()) == command


def test_preview_and_reflow_receipts_round_trip_and_manifest_freezes_policy() -> None:
    gate = CalibrationGate.create(
        gate_id="fit_quality",
        passed=True,
        observed=0.02,
        threshold=0.08,
        message="fit residual is within the frozen gate",
    )
    preview = CalibrationPreview.create(
        preview_id="preview-1",
        draft_id="draft-1",
        base_calibration_revision_id="calibration-1",
        base_calibration_digest="c" * 64,
        candidate_calibration={"matrix": [[1, 0], [0, 1]]},
        gates=(gate,),
        status="pass",
        failure=None,
        fit_residual=0.02,
        accepted_anchor_count=3,
        rejected_candidate_count=1,
        held_out_alignment_change_px=0.5,
        changed_frame_ids=("frame-1",),
        changed_card_ids=("card-1",),
        max_source_pixel_displacement=4.0,
        most_affected_frame_ids=("frame-1",),
    )
    receipt = CalibrationReflowReceipt.create(
        receipt_id="receipt-1",
        draft_id="draft-1",
        preview_digest=preview.preview_digest,
        source_calibration_revision_id="calibration-1",
        source_calibration_digest="c" * 64,
        target_calibration_revision_id="calibration-2",
        target_calibration_digest="d" * 64,
        proposal_revision_id="proposal-revision-1",
        anchor_command_digests=("a" * 64,),
        reinitialized_card_ids=("card-pending",),
        rebased_card_ids=("card-accepted",),
        affected_frame_ids=("frame-1",),
        affected_card_ids=("card-accepted",),
        preserved_anchor_ids=("anchor-1",),
    )

    assert CalibrationPreview.from_mapping(preview.to_mapping()) == preview
    assert CalibrationReflowReceipt.from_mapping(receipt.to_mapping()) == receipt
    manifest = calibration_refinement_contract_manifest()
    assert manifest["anchor_base_weights"] == ANCHOR_BASE_WEIGHTS
    assert manifest["max_reviewed_source_displacement_px"] == 12.0
