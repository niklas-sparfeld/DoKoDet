from __future__ import annotations

from pathlib import Path

import pytest
from game_engine import (
    ReconstructionInput,
    load_round_scenario,
    parse_observation_bytes,
    parse_reconstruction_input_bytes,
    reconstruct_manual_sequence,
    reconstruct_round,
)
from game_engine import (
    canonical_json_bytes as canonical_engine_json_bytes,
)
from table_evidence_analyzer import (
    TableObservation as PublishedTableObservation,
)
from table_evidence_analyzer import (
    canonical_json_bytes as canonical_published_observation_bytes,
)

from doko_operations.round_reconstruction_contract import (
    ROUND_RECONSTRUCTION_RESULT_SCHEMA_VERSION,
    ReconstructionDiagnosticsRecord,
)
from doko_operations.round_reconstruction_execution import _serialize_engine_diagnostics


def pile_publisher_payload(*, include_card: bool) -> dict[str, object]:
    card = {
        "observed_card_id": "observed-card-01",
        "side": "face_up",
        "identity_status": "classified",
        "identity_candidates": [{"card": "HEARTS_TEN", "probability": 1.0}],
    }
    return {
        "schema_version": "table-observation/v2",
        "observation_id": "observation-pile-01",
        "source": {"package_id": "package-01"},
        "session": {"session_id": "session-01", "event_sequence": 1},
        "observed_at_ms": 1000,
        "status": "observed",
        "capabilities": ["identity_candidates"],
        "cards": [card] if include_card else [],
        "piles": [
            {
                "pile_id": "pile-01",
                "geometry": {
                    "kind": "pile-region/v1",
                    "polygons": [
                        [{"x": 100, "y": 200}, {"x": 300, "y": 200}, {"x": 200, "y": 400}]
                    ],
                },
                "normalization": {
                    "width": 1920,
                    "height": 1080,
                    "policy_id": "full-frame-0-1000/v1",
                },
                "source_candidates": [],
                "grouped_candidates": [],
                "grouped_card_states": [],
                "grouped_scene_decision": None,
                "origin": "reviewed",
                "confidence": None,
                "model_lineage": None,
            }
        ],
        "calibration": "uncalibrated",
        "analyzer": {"name": "observation-assembler", "version": "v1"},
        "diagnostics": {},
    }


@pytest.mark.parametrize("include_card", [True, False], ids=["mixed", "pile-only"])
def test_publisher_v2_observation_round_trips_through_engine_without_gameplay_claims(
    include_card: bool,
) -> None:
    published = PublishedTableObservation.model_validate(
        pile_publisher_payload(include_card=include_card)
    )
    published_bytes = canonical_published_observation_bytes(published)

    engine_observation = parse_observation_bytes(published_bytes)

    assert canonical_engine_json_bytes(engine_observation) == published_bytes
    assert engine_observation.schema_version == "table-observation/v2"
    assert [pile.pile_id for pile in engine_observation.piles or []] == ["pile-01"]
    assert len(engine_observation.cards) == int(include_card)

    reconstruction_input = ReconstructionInput.model_validate(
        {
            "schema_version": "round-reconstruction-input/v1",
            "game_id": "game-01",
            "round_id": "round-01",
            "ruleset": {"name": "doko-normal", "version": "v1"},
            "deck_variant": "doko-40-v1",
            "active_players": ["player-01", "player-02", "player-03", "player-04"],
            "dealer": "player-04",
            "first_trick_leader": "player-01",
            "observations": [engine_observation],
        }
    )
    input_bytes = canonical_engine_json_bytes(reconstruction_input)
    input_round_trip = parse_reconstruction_input_bytes(input_bytes)
    assert canonical_engine_json_bytes(input_round_trip) == input_bytes

    result = reconstruct_round(input_round_trip)
    assert result.diagnostics.pile_observations_seen == 1
    assert result.diagnostics.pile_regions_seen == 1
    assert result.diagnostics.pile_search_status == "retained_not_used"
    assert result.diagnostics.card_proposals_seen == int(include_card)
    assert result.status == "incomplete"
    assert not result.hypotheses
    diagnostics_mapping = _serialize_engine_diagnostics(result.diagnostics).to_mapping()
    validated_diagnostics = ReconstructionDiagnosticsRecord.from_mapping(diagnostics_mapping)
    assert validated_diagnostics.pile_regions_seen == 1
    assert ROUND_RECONSTRUCTION_RESULT_SCHEMA_VERSION == "round-reconstruction-result/v3"


def test_piles_do_not_change_card_search_or_replay() -> None:
    fixture = (
        Path(__file__).parents[2]
        / "fixtures"
        / "game-engine"
        / "v1"
        / "rounds"
        / "unambiguous.json"
    )
    scenario = load_round_scenario(fixture)
    pile_observation = parse_observation_bytes(
        canonical_published_observation_bytes(
            PublishedTableObservation.model_validate(pile_publisher_payload(include_card=False))
        )
    )
    first = scenario.input.observations[0].model_copy(
        update={"schema_version": "table-observation/v2", "piles": pile_observation.piles}
    )
    with_pile = scenario.input.model_copy(
        update={"observations": [first, *scenario.input.observations[1:]]}
    )

    without_pile_result = reconstruct_round(scenario.input)
    with_pile_result = reconstruct_round(with_pile)

    assert with_pile_result.status == without_pile_result.status == "resolved"
    assert with_pile_result.best_hypothesis is not None
    assert without_pile_result.best_hypothesis is not None
    assert with_pile_result.best_hypothesis.plays == without_pile_result.best_hypothesis.plays
    assert with_pile_result.best_hypothesis.actions == without_pile_result.best_hypothesis.actions
    assert with_pile_result.diagnostics.pile_regions_seen == 1
    assert with_pile_result.diagnostics.pile_search_status == "retained_not_used"

    manual_result = reconstruct_manual_sequence(
        with_pile,
        with_pile_result.best_hypothesis.plays,
    )
    assert manual_result.best_hypothesis is not None
    assert manual_result.best_hypothesis.plays == with_pile_result.best_hypothesis.plays
    assert manual_result.diagnostics.pile_regions_seen == 1
    assert manual_result.diagnostics.pile_search_status == "retained_not_used"
