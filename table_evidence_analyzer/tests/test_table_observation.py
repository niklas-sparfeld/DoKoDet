from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from table_evidence_analyzer.table_observation import (
    TableObservation,
    canonical_json_bytes,
    parse_observation_bytes,
)

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "game-engine" / "v1"


def load_fixture(name: str) -> tuple[bytes, dict[str, object]]:
    raw = (FIXTURE_ROOT / name).read_bytes()
    return raw, json.loads(raw)


def test_minimal_observation_crosses_the_analyzer_boundary_unchanged() -> None:
    raw, payload = load_fixture("observations/minimal.json")

    observation = parse_observation_bytes(raw)

    assert json.loads(canonical_json_bytes(observation)) == payload
    assert observation.cards[0].identity_candidates[0].card == "HEARTS_TEN"
    assert observation.cards[0].presence_score is None
    assert "player" not in payload
    assert "turn" not in payload
    assert "game_state" not in payload


def test_absent_optional_score_is_not_zero() -> None:
    _, payload = load_fixture("observations/minimal.json")
    with_presence = copy.deepcopy(payload)
    with_presence["capabilities"] = ["identity_candidates", "presence_score"]
    with_presence["cards"][0]["presence_score"] = 0.0

    observation = TableObservation.model_validate(with_presence)

    assert observation.cards[0].presence_score == 0.0
    assert TableObservation.model_validate(payload).cards[0].presence_score is None


def test_optional_field_requires_a_declared_capability() -> None:
    _, payload = load_fixture("observations/minimal.json")
    invalid = copy.deepcopy(payload)
    invalid["cards"][0]["active_area_score"] = 0.0

    with pytest.raises(ValidationError, match="active_area_score field requires"):
        TableObservation.model_validate(invalid)


def test_explicit_null_is_not_an_absent_optional_field() -> None:
    _, payload = load_fixture("observations/minimal.json")
    invalid = copy.deepcopy(payload)
    invalid["cards"][0]["presence_score"] = None

    with pytest.raises(ValidationError, match="presence_score field requires"):
        TableObservation.model_validate(invalid)


def test_observed_and_insufficient_evidence_are_distinct() -> None:
    _, payload = load_fixture("observations/minimal.json")
    insufficient = copy.deepcopy(payload)
    insufficient.update(status="insufficient_evidence", cards=[])

    result = TableObservation.model_validate(insufficient)

    assert result.status == "insufficient_evidence"
    assert result.cards == []
    assert TableObservation.model_validate(payload).status == "observed"


@pytest.mark.parametrize(
    "change",
    [
        lambda payload: payload.update(player="player-01"),
        lambda payload: payload["cards"][0]["identity_candidates"].append(
            {"card": "CLUBS_ACE", "probability": 0.5}
        ),
        lambda payload: payload["cards"][0]["identity_candidates"][0].update(probability=0.4),
        lambda payload: payload["cards"][0].update(extra="not allowed"),
    ],
)
def test_invalid_observation_shape_is_rejected(change) -> None:
    _, original = load_fixture("observations/minimal.json")
    payload = copy.deepcopy(original)
    change(payload)

    with pytest.raises(ValidationError):
        TableObservation.model_validate(payload)
