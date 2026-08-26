import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from vision_detector.cards import CARD_IDENTITIES, load_card_set, load_deck_manifest
from vision_detector.contract import (
    VisionDetectionResult,
    VisionEvidence,
    VisionFrame,
    canonical_json_bytes,
    parse_result_bytes,
)

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "vision" / "v1"


def load_fixture(name: str) -> tuple[bytes, dict[str, object]]:
    raw = (FIXTURE_ROOT / name).read_bytes()
    return raw, json.loads(raw)


def test_shared_result_fixtures_are_valid_and_canonicalizable() -> None:
    ranked_raw, ranked_payload = load_fixture("example-ranked.json")
    abstained_raw, abstained_payload = load_fixture("example-abstained.json")

    ranked = parse_result_bytes(ranked_raw)
    abstained = parse_result_bytes(abstained_raw)

    assert ranked.status == "uncertain"
    assert [candidate.card for candidate in ranked.candidates] == [
        "HEARTS_QUEEN",
        "DIAMONDS_QUEEN",
    ]
    assert abstained.status == "insufficient_evidence"
    assert abstained.candidates == []
    assert json.loads(canonical_json_bytes(ranked)) == ranked_payload
    assert json.loads(canonical_json_bytes(abstained)) == abstained_payload


def test_card_and_deck_manifests_are_shared_and_data_driven() -> None:
    card_set = load_card_set()
    deck_40 = load_deck_manifest("doko-40-v1")
    deck_48 = load_deck_manifest("doko-48-v1")

    assert len(card_set.visual_identities) == len(CARD_IDENTITIES) == 24
    assert deck_40.physical_card_count == deck_40.expected_plays == 40
    assert deck_48.physical_card_count == deck_48.expected_plays == 48
    assert all(card.copies == 2 for card in deck_40.cards + deck_48.cards)


@pytest.mark.parametrize(
    "change",
    [
        lambda payload: payload["candidates"].reverse(),
        lambda payload: payload["candidates"][0].update(probability=0.57),
        lambda payload: payload["candidates"].append(payload["candidates"][0].copy()),
        lambda payload: payload.update(extra="not allowed"),
        lambda payload: payload["detector"].update(extra="not allowed"),
    ],
)
def test_invalid_candidate_ordering_normalization_duplicates_and_unknown_fields(change) -> None:
    _, original = load_fixture("example-ranked.json")
    payload = copy.deepcopy(original)
    change(payload)

    with pytest.raises(ValidationError):
        VisionDetectionResult.model_validate(payload)


@pytest.mark.parametrize(
    ("status", "selected_card", "candidates", "valid"),
    [
        ("confident", "HEARTS_QUEEN", [{"card": "HEARTS_QUEEN", "probability": 1.0}], True),
        ("confident", None, [{"card": "HEARTS_QUEEN", "probability": 1.0}], False),
        ("confident", "DIAMONDS_QUEEN", [{"card": "HEARTS_QUEEN", "probability": 1.0}], False),
        ("uncertain", None, [{"card": "HEARTS_QUEEN", "probability": 1.0}], True),
        ("uncertain", "HEARTS_QUEEN", [{"card": "HEARTS_QUEEN", "probability": 1.0}], False),
        ("uncertain", None, [], False),
        ("no_card_found", None, [], True),
        ("no_card_found", None, [{"card": "HEARTS_QUEEN", "probability": 1.0}], False),
        ("insufficient_evidence", None, [], True),
        ("insufficient_evidence", None, [{"card": "HEARTS_QUEEN", "probability": 1.0}], False),
    ],
)
def test_status_candidate_and_selected_card_rules(status, selected_card, candidates, valid) -> None:
    _, payload = load_fixture("example-ranked.json")
    payload = copy.deepcopy(payload)
    payload.update(status=status, selected_card=selected_card, candidates=candidates)

    if valid:
        result = VisionDetectionResult.model_validate(payload)
        if status == "confident":
            assert result.selected_card == result.candidates[0].card
    else:
        with pytest.raises(ValidationError):
            VisionDetectionResult.model_validate(payload)


def test_unknown_card_and_non_finite_probability_are_rejected() -> None:
    _, payload = load_fixture("example-ranked.json")

    unknown_card = copy.deepcopy(payload)
    unknown_card["candidates"][0]["card"] = "JOKER"
    with pytest.raises(ValidationError):
        VisionDetectionResult.model_validate(unknown_card)

    non_finite = copy.deepcopy(payload)
    non_finite["candidates"][0]["probability"] = float("nan")
    with pytest.raises(ValidationError):
        VisionDetectionResult.model_validate(non_finite)


def test_observations_are_optional_json_objects_with_a_bound() -> None:
    _, payload = load_fixture("example-ranked.json")
    payload = copy.deepcopy(payload)
    payload["observations"] = [{"frame": "frame_00", "score": 0.5}]
    result = VisionDetectionResult.model_validate(payload)
    assert result.observations[0]["frame"] == "frame_00"

    too_many = copy.deepcopy(payload)
    too_many["observations"] = [{}] * 33
    with pytest.raises(ValidationError):
        VisionDetectionResult.model_validate(too_many)


def test_detector_input_has_only_visual_fields_and_one_read_only_source() -> None:
    evidence = VisionEvidence(
        package_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
        event_time_ms=12000,
        frames=[
            VisionFrame(
                part_name="frame_00",
                actual_offset_ms=-802,
                width=1920,
                height=1080,
                jpeg_bytes=b"fixture bytes",
            )
        ],
    )

    assert set(evidence.model_dump()) == {"package_id", "event_time_ms", "frames"}
    assert not hasattr(evidence, "session_id")
    assert not hasattr(evidence, "event_sequence")
    with pytest.raises(ValidationError):
        VisionEvidence.model_validate(
            {
                "package_id": str(evidence.package_id),
                "event_time_ms": evidence.event_time_ms,
                "frames": [],
                "session_id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
            }
        )
    with pytest.raises(ValidationError):
        VisionFrame(
            part_name="frame_00",
            actual_offset_ms=0,
            width=1,
            height=1,
        )


def test_created_at_is_utc_and_serializes_with_milliseconds() -> None:
    _, payload = load_fixture("example-ranked.json")
    payload = copy.deepcopy(payload)
    payload["created_at"] = datetime(2026, 8, 26, 18, 12, tzinfo=timezone.utc)
    result = VisionDetectionResult.model_validate(payload)

    assert result.created_at.tzinfo == timezone.utc
    assert json.loads(canonical_json_bytes(result))["created_at"] == "2026-08-26T18:12:00.000Z"
