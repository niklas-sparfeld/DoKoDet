from __future__ import annotations

from pathlib import Path

import pytest

from game_engine.contract import canonical_json_bytes, load_round_scenario
from game_engine.replay import replay_round
from game_engine.synthetic import (
    CandidateConfusion,
    CandidateMultiplicityViolation,
    ClearTrick,
    DropObservations,
    DuplicateDetection,
    EmptyObservation,
    FalseCardProposal,
    InsufficientEvidenceObservation,
    MissingIdentityCandidate,
    ObservationConfig,
    ReappearAfterOcclusion,
    RepeatObservation,
    RetainedSideCard,
    generate_observations,
    generate_round,
)

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "game-engine" / "v1"


@pytest.mark.parametrize("seed", range(20))
def test_seeded_rounds_are_legal_and_replayable(seed: int) -> None:
    synthetic_round = generate_round(seed)

    replay = replay_round(
        synthetic_round.card_plays,
        active_players=synthetic_round.active_players,
        first_trick_leader=synthetic_round.first_trick_leader,
        initial_hands=synthetic_round.initial_hands,
    )

    assert replay == synthetic_round.replay
    assert len(synthetic_round.card_plays) == 40
    assert len(synthetic_round.replay.tricks) == 10
    assert sum(len(hand) for hand in synthetic_round.physical_hands.values()) == 40


def test_same_seed_produces_byte_stable_valid_observations() -> None:
    first_round = generate_round(20260827)
    second_round = generate_round(20260827)
    config = ObservationConfig(
        capabilities=(
            "identity_candidates",
            "presence_score",
            "newly_visible_score",
            "active_area_score",
            "association_candidates",
            "card_tracklets",
        )
    )

    first = generate_observations(first_round, config=config)
    second = generate_observations(second_round, config=config)

    assert [canonical_json_bytes(observation) for observation in first] == [
        canonical_json_bytes(observation) for observation in second
    ]
    assert all(observation.capabilities == list(config.capabilities) for observation in first)
    assert all(
        "presence_score" in observation.cards[0].model_fields_set
        and "newly_visible_score" in observation.cards[0].model_fields_set
        and "active_area_score" in observation.cards[0].model_fields_set
        and "association_candidates" in observation.cards[0].model_fields_set
        and "card_tracklet_id" in observation.cards[0].model_fields_set
        for observation in first
    )


def test_clean_observations_preserve_the_source_round() -> None:
    synthetic_round = generate_round(17)
    observations = generate_observations(synthetic_round)

    observed_cards = tuple(
        observation.cards[0].identity_candidates[0].card for observation in observations
    )

    assert observed_cards == tuple(play.card for play in synthetic_round.card_plays)
    assert all(observation.status == "observed" for observation in observations)


def test_repeated_observation_emits_transition_predecessor_evidence() -> None:
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

    repeated_card = observations[9].cards[0]

    assert repeated_card.newly_visible_score == 0.0
    assert repeated_card.association_candidates is not None
    assert repeated_card.association_candidates[0].observed_card_id == ("observation-009-card-01")
    assert repeated_card.association_candidates[0].score == 1.0


def test_error_modules_are_composable_and_keep_contracts_valid() -> None:
    synthetic_round = generate_round(23)
    observations = generate_observations(
        synthetic_round,
        config=ObservationConfig(
            capabilities=(
                "identity_candidates",
                "presence_score",
                "newly_visible_score",
                "active_area_score",
            )
        ),
        errors=(
            EmptyObservation(2),
            ReappearAfterOcclusion(5),
            FalseCardProposal(8, "HEARTS_NINE"),
            DuplicateDetection(9),
            RetainedSideCard(10, "CLUBS_ACE"),
            ClearTrick(1),
            DropObservations((12,)),
            CandidateConfusion(14, ("HEARTS_QUEEN", "HEARTS_KING"), (0.6, 0.4)),
            MissingIdentityCandidate(15, "HEARTS_NINE"),
            CandidateMultiplicityViolation("SPADES_ACE"),
        ),
    )

    assert any(not observation.cards for observation in observations)
    assert any(len(observation.cards) > 1 for observation in observations)
    assert any(
        observation.cards and len(observation.cards[0].identity_candidates) == 2
        for observation in observations
    )
    assert all(observation.observation_id for observation in observations)
    assert [observation.observed_at_ms for observation in observations] == sorted(
        observation.observed_at_ms for observation in observations
    )


def test_missing_evidence_is_distinct_from_an_empty_observation() -> None:
    synthetic_round = generate_round(31)
    observations = generate_observations(
        synthetic_round,
        errors=(EmptyObservation(0),),
    )
    insufficient = generate_observations(
        synthetic_round,
        errors=(InsufficientEvidenceObservation(0),),
    )

    assert observations[0].status == "observed"
    assert observations[0].cards == []
    assert insufficient[0].status == "insufficient_evidence"
    assert insufficient[0].cards == []


def test_canonical_scenarios_are_valid_and_record_their_generator_modules() -> None:
    scenario_names = (
        "unambiguous",
        "late-resolution",
        "ambiguous",
        "impossible",
        "incomplete",
        "occlusion",
        "side-card",
        "human-corrected",
    )

    for name in scenario_names:
        scenario = load_round_scenario(FIXTURE_ROOT / "rounds" / f"{name}.json")
        generator = scenario.ground_truth["generator"]
        assert isinstance(generator, dict)
        assert generator["name"] == "game_engine.synthetic"
        assert scenario.input.trick_count == 10
        assert scenario.enabled_capabilities == scenario.input.observations[0].capabilities


def test_unambiguous_scenario_observations_replay_private_source_truth() -> None:
    scenario = load_round_scenario(FIXTURE_ROOT / "rounds" / "unambiguous.json")
    observed = [
        {
            "player": play["player"],
            "card": play["card"],
        }
        for play in scenario.ground_truth["card_plays"]
    ]
    observation_cards = [
        observation.cards[0].identity_candidates[0].card
        for observation in scenario.input.observations
    ]

    assert len(observed) == 40
    assert [play["card"] for play in observed] == observation_cards
