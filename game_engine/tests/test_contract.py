from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from game_engine.cards import load_card_set, load_deck_manifest
from game_engine.contract import (
    ReconstructionInput,
    canonical_json_bytes,
    load_round_scenario,
    parse_observation_bytes,
    parse_reconstruction_input_bytes,
)

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "game-engine" / "v1"


def load_fixture(name: str) -> tuple[bytes, dict[str, object]]:
    raw = (FIXTURE_ROOT / name).read_bytes()
    return raw, json.loads(raw)


def test_minimal_observation_crosses_the_reconstruction_boundary_unchanged() -> None:
    raw, payload = load_fixture("observations/minimal.json")

    observation = parse_observation_bytes(raw)

    assert json.loads(canonical_json_bytes(observation)) == payload
    assert observation.cards[0].identity_candidates[0].card == "HEARTS_TEN"


def test_card_set_and_round_manifest_derive_the_canonical_trick_count() -> None:
    card_set = load_card_set()
    deck = load_deck_manifest("doko-40-v1")

    assert len(card_set.visual_identities) == 24
    assert deck.physical_card_count == deck.expected_plays == 40
    assert deck.trick_count == 10


def test_complete_exact_observation_scenario_is_strict_and_complete() -> None:
    scenario = load_round_scenario(FIXTURE_ROOT / "rounds" / "unambiguous.json")

    assert scenario.input.trick_count == 10
    assert len(scenario.input.observations) == 40
    assert scenario.expected.status == "resolved"
    assert scenario.enabled_capabilities == ["identity_candidates"]
    assert len(scenario.ground_truth["card_plays"]) == 40

    input_payload = canonical_json_bytes(scenario.input)
    reconstruction_input = parse_reconstruction_input_bytes(input_payload)
    assert len(reconstruction_input.observations) == 40
    assert "physical_card" not in input_payload.decode()


def test_reconstruction_input_keeps_game_claims_out_of_observations() -> None:
    _, scenario_payload = load_fixture("rounds/unambiguous.json")
    input_payload = copy.deepcopy(scenario_payload["input"])
    input_payload["observations"][0]["player"] = "player-01"

    with pytest.raises(ValidationError):
        ReconstructionInput.model_validate(input_payload)


def test_reconstruction_input_requires_four_active_players_and_an_active_leader() -> None:
    _, scenario_payload = load_fixture("rounds/unambiguous.json")

    too_few_players = copy.deepcopy(scenario_payload["input"])
    too_few_players["active_players"] = ["player-01", "player-02", "player-03"]
    with pytest.raises(ValidationError):
        ReconstructionInput.model_validate(too_few_players)

    inactive_leader = copy.deepcopy(scenario_payload["input"])
    inactive_leader["first_trick_leader"] = "dealer-01"
    with pytest.raises(ValidationError):
        ReconstructionInput.model_validate(inactive_leader)
