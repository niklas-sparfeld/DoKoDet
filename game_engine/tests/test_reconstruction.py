from __future__ import annotations

from pathlib import Path

import pytest

from game_engine.contract import load_round_scenario
from game_engine.reconstruction import reconstruct_round
from game_engine.synthetic import DropObservations, generate_observations, generate_round

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
