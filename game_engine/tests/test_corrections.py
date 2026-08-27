from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from game_engine.contract import canonical_json_bytes, load_reconstruction_input_file
from game_engine.corrections import (
    CorrectionDocument,
    apply_corrections,
    load_correction_document,
)
from game_engine.reconstruction import reconstruct_round

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "game-engine" / "v1"


def test_focused_identity_correction_resolves_ambiguous_fixture_without_mutating_source() -> None:
    scenario_payload = json.loads(
        (FIXTURE_ROOT / "rounds" / "ambiguous.json").read_text(encoding="utf-8")
    )
    reconstruction_input = load_reconstruction_input_file(
        FIXTURE_ROOT / "rounds" / "ambiguous.json"
    )
    source_bytes = canonical_json_bytes(reconstruction_input)
    source_result = reconstruct_round(reconstruction_input)
    correction_document = load_correction_document(
        FIXTURE_ROOT / "corrections" / "ambiguous-focused.json"
    )

    application = apply_corrections(
        reconstruction_input,
        correction_document,
        source_result=source_result,
    )

    assert source_result.status == "ambiguous"
    assert application.conflicts == ()
    assert application.reviewed_result is not None
    assert application.reviewed_result.status == "resolved"
    assert application.reviewed_result.best_hypothesis is not None
    assert [play.card for play in application.reviewed_result.best_hypothesis.plays] == [
        play["card"] for play in scenario_payload["ground_truth"]["card_plays"]
    ]
    assert canonical_json_bytes(reconstruction_input) == source_bytes
    assert application.source_result is source_result
    assert application.constraints == correction_document.constraints


def test_conflicting_identity_correction_reports_exact_deck_conflict() -> None:
    reconstruction_input = load_reconstruction_input_file(
        FIXTURE_ROOT / "rounds" / "ambiguous.json"
    )
    correction_document = CorrectionDocument.model_validate(
        {
            "schema_version": "reconstruction-corrections/v1",
            "round_id": reconstruction_input.round_id,
            "constraints": [
                {
                    "schema_version": "reconstruction-correction/v1",
                    "constraint_id": "correction-conflicting-card",
                    "kind": "select_identity",
                    "reviewer_id": "reviewer-01",
                    "created_at_ms": 1,
                    "observed_card_id": "observation-041-card-01",
                    "selected_card": "HEARTS_NINE",
                }
            ],
        }
    )

    application = apply_corrections(reconstruction_input, correction_document)

    assert application.reviewed_result is None
    assert len(application.conflicts) == 1
    conflict = application.conflicts[0]
    assert conflict.kind == "deck_conflict"
    assert conflict.constraint_id == "correction-conflicting-card"
    assert conflict.message == ("selected card HEARTS_NINE is outside selected deck doko-40-v1")


def test_complete_manual_sequence_produces_reviewed_reconstruction() -> None:
    reconstruction_input = load_reconstruction_input_file(
        FIXTURE_ROOT / "rounds" / "ambiguous.json"
    )
    source_result = reconstruct_round(reconstruction_input)
    payload = json.loads((FIXTURE_ROOT / "rounds" / "ambiguous.json").read_text(encoding="utf-8"))
    correction_document = CorrectionDocument.model_validate(
        {
            "schema_version": "reconstruction-corrections/v1",
            "round_id": reconstruction_input.round_id,
            "constraints": [
                {
                    "schema_version": "reconstruction-correction/v1",
                    "constraint_id": "correction-complete-sequence",
                    "kind": "complete_sequence",
                    "reviewer_id": "reviewer-01",
                    "created_at_ms": 2,
                    "card_plays": [
                        {"player": play["player"], "card": play["card"]}
                        for play in payload["ground_truth"]["card_plays"]
                    ],
                }
            ],
        }
    )

    application = apply_corrections(
        reconstruction_input,
        correction_document,
        source_result=source_result,
    )

    assert source_result.status == "ambiguous"
    assert application.reviewed_result is not None
    assert application.reviewed_result.status == "resolved"
    assert application.reviewed_result.best_hypothesis is not None
    assert [play.card for play in application.reviewed_result.best_hypothesis.plays] == [
        play["card"] for play in payload["ground_truth"]["card_plays"]
    ]


def test_correction_constraints_are_closed_and_immutable() -> None:
    with pytest.raises(ValidationError):
        CorrectionDocument.model_validate(
            {
                "schema_version": "reconstruction-corrections/v1",
                "round_id": "round-01",
                "constraints": [
                    {
                        "schema_version": "reconstruction-correction/v1",
                        "constraint_id": "correction-01",
                        "kind": "select_identity",
                        "reviewer_id": "reviewer-01",
                        "created_at_ms": 1,
                        "observed_card_id": "observation-01-card-01",
                        "selected_card": "CLUBS_JACK",
                        "unknown": True,
                    }
                ],
            }
        )

    document = CorrectionDocument.model_validate(
        {
            "schema_version": "reconstruction-corrections/v1",
            "round_id": "round-01",
            "constraints": [
                {
                    "schema_version": "reconstruction-correction/v1",
                    "constraint_id": "correction-01",
                    "kind": "mark_observation_irrelevant",
                    "reviewer_id": "reviewer-01",
                    "created_at_ms": 1,
                    "observation_id": "observation-01",
                }
            ],
        }
    )

    with pytest.raises(ValidationError):
        document.constraints[0].observation_id = "observation-02"
