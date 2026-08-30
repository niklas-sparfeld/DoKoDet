from __future__ import annotations

from pathlib import Path

import pytest

from game_engine.contract import ReconstructionInput, load_round_scenario
from game_engine.reconstruction import reconstruct_round, run_ablation
from game_engine.synthetic import (
    DropObservations,
    FalseCardProposal,
    ObservationConfig,
    RepeatObservation,
    RetainedSideCard,
    generate_observations,
    generate_round,
)

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "game-engine" / "v1"


@pytest.mark.parametrize(
    ("scenario_name", "expected_status"),
    (
        ("unambiguous", "resolved"),
        ("late-resolution", "resolved"),
        ("ambiguous", "ambiguous"),
        ("impossible", "impossible"),
        ("incomplete", "incomplete"),
        ("occlusion", "resolved"),
        ("side-card", "resolved"),
        ("human-corrected", "resolved"),
    ),
)
def test_identity_only_oracle_reconstructs_canonical_scenarios(
    scenario_name: str,
    expected_status: str,
) -> None:
    scenario = load_round_scenario(FIXTURE_ROOT / "rounds" / f"{scenario_name}.json")

    result = reconstruct_round(scenario.input)

    assert result.status == expected_status
    assert result.diagnostics.search_nodes > 0
    if expected_status in {"resolved", "ambiguous"}:
        assert result.hypotheses
    else:
        assert not result.hypotheses


@pytest.mark.parametrize(
    ("scenario_name", "expected_status"),
    (
        ("unambiguous", "resolved"),
        ("ambiguous", "ambiguous"),
        ("incomplete", "incomplete"),
        ("impossible", "impossible"),
    ),
)
def test_four_status_scenarios_retain_complete_action_explanations(
    scenario_name: str,
    expected_status: str,
) -> None:
    scenario = load_round_scenario(FIXTURE_ROOT / "rounds" / f"{scenario_name}.json")
    result = reconstruct_round(scenario.input)

    assert result.status == expected_status
    if expected_status in {"incomplete", "impossible"}:
        assert result.hypotheses == ()
        return

    assert result.hypotheses
    for hypothesis in result.hypotheses:
        observed_card_count = sum(
            len(observation.cards) for observation in scenario.input.observations
        )
        assert len(hypothesis.actions) == observed_card_count
        assert {action.play_index for action in hypothesis.actions if action.kind == "selected"} | {
            action.play_index for action in hypothesis.actions if action.kind == "inferred"
        } == set(range(1, len(hypothesis.plays) + 1))
        observed_refs = [
            (action.observation_id, action.observed_card_id)
            for action in hypothesis.actions
            if action.kind in {"selected", "ignored"}
        ]
        assert len(observed_refs) == len(set(observed_refs))
        assert sum(action.score_contribution for action in hypothesis.actions) == pytest.approx(
            hypothesis.total_score, abs=1e-9
        )


def test_lower_ranked_identity_survives_an_illegal_top_candidate() -> None:
    scenario = load_round_scenario(FIXTURE_ROOT / "rounds" / "late-resolution.json")

    result = reconstruct_round(scenario.input)

    assert result.status == "resolved"
    assert result.hypotheses[0].plays[19].card == "HEARTS_QUEEN"
    assert result.hypotheses[0].score_breakdown.identity_candidate_log_score < 0
    assert any("replay" in rejection for rejection in result.diagnostics.rejected_branches)


def test_one_missing_observation_is_inferred_from_the_remaining_deck() -> None:
    synthetic_round = generate_round(20260827)
    observations = generate_observations(
        synthetic_round,
        errors=(DropObservations((18,)),),
    )
    scenario = load_round_scenario(FIXTURE_ROOT / "rounds" / "unambiguous.json")
    reconstruction_input = scenario.input.model_copy(update={"observations": list(observations)})

    result = reconstruct_round(reconstruction_input, missing_play_slots=(19,))

    assert result.status == "resolved"
    assert result.hypotheses[0].missing_play_indices
    assert result.hypotheses[0].plays == synthetic_round.replay.plays
    inferred = [action for action in result.hypotheses[0].actions if action.kind == "inferred"]
    assert len(inferred) == 1
    assert inferred[0].play_index == result.hypotheses[0].missing_play_indices[0]
    assert inferred[0].card == synthetic_round.replay.plays[inferred[0].play_index - 1].card
    assert inferred[0].score_contribution == -0.75


def test_focused_decisions_describe_tied_legal_results() -> None:
    scenario = load_round_scenario(FIXTURE_ROOT / "rounds" / "ambiguous.json")

    result = reconstruct_round(scenario.input)

    assert result.status == "ambiguous"
    assert result.focused_decisions
    decision = result.focused_decisions[0]
    assert decision.play_index >= 1
    assert len(decision.alternatives) >= 2
    assert decision.source_observation_ids


def test_missing_bound_keeps_incomplete_distinct_from_impossible() -> None:
    scenario = load_round_scenario(FIXTURE_ROOT / "rounds" / "incomplete.json")

    result = reconstruct_round(scenario.input)

    assert result.status == "incomplete"
    assert "fewer card proposals" in " ".join(result.diagnostics.rejected_branches)


def test_presence_evidence_ranks_a_low_presence_false_proposal_below_the_source_round() -> None:
    synthetic_round = generate_round(0)
    observations = generate_observations(
        synthetic_round,
        config=ObservationConfig(capabilities=("identity_candidates", "presence_score")),
        errors=(FalseCardProposal(8, "SPADES_TEN", presence_score=0.01),),
    )
    reconstruction_input = _reconstruction_input(synthetic_round, observations)

    ablation = run_ablation(reconstruction_input, family="presence", max_hypotheses=8)

    assert ablation.without_evidence.status == "ambiguous"
    assert ablation.with_evidence.status == "ambiguous"
    assert ablation.with_evidence.best_hypothesis is not None
    assert ablation.with_evidence.best_hypothesis.plays == synthetic_round.card_plays
    assert (
        observations[8].cards[1].observed_card_id
        in ablation.with_evidence.best_hypothesis.ignored_observed_card_ids
    )
    assert (
        ablation.with_evidence.best_hypothesis.score_breakdown.visual_evidence_score.presence > 0.0
    )
    assert ablation.without_evidence.diagnostics.ablated_evidence == ("presence",)


def test_transition_evidence_ranks_a_predecessor_reappearance_below_the_source_round() -> None:
    synthetic_round = generate_round(0)
    observations = generate_observations(
        synthetic_round,
        config=ObservationConfig(
            capabilities=(
                "identity_candidates",
                "newly_visible_score",
                "association_candidates",
            )
        ),
        errors=(RepeatObservation(8),),
    )
    reconstruction_input = _reconstruction_input(synthetic_round, observations)

    ablation = run_ablation(reconstruction_input, family="transition", max_hypotheses=8)

    repeated_card = observations[9].cards[0]
    assert repeated_card.newly_visible_score == 0.0
    assert repeated_card.association_candidates
    assert ablation.without_evidence.status == "ambiguous"
    assert ablation.with_evidence.status == "ambiguous"
    assert ablation.with_evidence.best_hypothesis is not None
    assert ablation.with_evidence.best_hypothesis.plays == synthetic_round.card_plays
    assert (
        repeated_card.observed_card_id
        in ablation.with_evidence.best_hypothesis.ignored_observed_card_ids
    )
    assert (
        ablation.with_evidence.best_hypothesis.score_breakdown.visual_evidence_score.predecessor
        > 0.0
    )


def test_active_area_evidence_ranks_a_side_card_below_the_source_round() -> None:
    synthetic_round = generate_round(0)
    observations = generate_observations(
        synthetic_round,
        config=ObservationConfig(capabilities=("identity_candidates", "active_area_score")),
        errors=(RetainedSideCard(10, "SPADES_KING", active_area_score=0.0),),
    )
    reconstruction_input = _reconstruction_input(synthetic_round, observations)

    ablation = run_ablation(reconstruction_input, family="active_area", max_hypotheses=8)

    assert ablation.without_evidence.status == "ambiguous"
    assert ablation.with_evidence.status == "ambiguous"
    assert ablation.with_evidence.best_hypothesis is not None
    assert ablation.with_evidence.best_hypothesis.plays == synthetic_round.card_plays
    assert (
        observations[10].cards[1].observed_card_id
        in ablation.with_evidence.best_hypothesis.ignored_observed_card_ids
    )


def test_tracklet_evidence_rejects_reusing_one_tracklet_as_two_card_plays() -> None:
    synthetic_round = generate_round(0)
    observations = generate_observations(
        synthetic_round,
        config=ObservationConfig(capabilities=("identity_candidates", "card_tracklets")),
        errors=(RepeatObservation(8),),
    )
    reconstruction_input = _reconstruction_input(synthetic_round, observations)

    ablation = run_ablation(reconstruction_input, family="tracklet", max_hypotheses=8)

    assert ablation.without_evidence.status == "ambiguous"
    assert ablation.with_evidence.status == "resolved"
    assert ablation.with_evidence.best_hypothesis is not None
    assert ablation.with_evidence.best_hypothesis.plays == synthetic_round.card_plays
    assert any(
        "tracklet" in rejection
        for rejection in ablation.with_evidence.diagnostics.rejected_branches
    )


def test_high_presence_evidence_cannot_override_a_ruleset_deck_rejection() -> None:
    synthetic_round = generate_round(0)
    observations = generate_observations(
        synthetic_round,
        config=ObservationConfig(capabilities=("identity_candidates", "presence_score")),
        errors=(FalseCardProposal(8, "HEARTS_NINE", presence_score=1.0),),
    )
    reconstruction_input = _reconstruction_input(synthetic_round, observations)

    result = reconstruct_round(reconstruction_input, max_hypotheses=8)

    assert result.status == "resolved"
    assert result.best_hypothesis is not None
    assert result.best_hypothesis.plays == synthetic_round.card_plays
    assert any(
        "outside the selected deck" in rejection
        for rejection in result.diagnostics.rejected_branches
    )


def _reconstruction_input(synthetic_round, observations) -> ReconstructionInput:
    return ReconstructionInput.model_validate(
        {
            "schema_version": "round-reconstruction-input/v1",
            "game_id": "synthetic-game-m4",
            "round_id": "synthetic-round-m4",
            "ruleset": {"name": "doko-normal", "version": "v1"},
            "deck_variant": "doko-40-v1",
            "active_players": list(synthetic_round.active_players),
            "dealer": synthetic_round.dealer,
            "first_trick_leader": synthetic_round.first_trick_leader,
            "observations": [
                observation.model_dump(mode="json", exclude_none=True)
                for observation in observations
            ],
        }
    )
