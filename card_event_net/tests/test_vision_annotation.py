from __future__ import annotations

import json
from pathlib import Path

import pytest

from cardevent.vision_annotation import (
    TABLE_OBSERVATION_SCHEMA_VERSION,
    FrameObservation,
    ObservedCard,
    TableObservationAnnotation,
    VisionAnnotationError,
    VisionSource,
)

VISION_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "vision_annotation"


def test_table_observation_round_trip_and_schema_rules() -> None:
    annotation = TableObservationAnnotation.from_mapping(
        json.loads((VISION_FIXTURE_ROOT / "table-observation.json").read_text())
    )

    restored = TableObservationAnnotation.from_mapping(annotation.to_mapping())

    assert restored == annotation
    assert restored.to_mapping()["schema_version"] == TABLE_OBSERVATION_SCHEMA_VERSION
    assert restored.observed_cards[0].visual_card_identity == "HEARTS_QUEEN"


def test_non_identifiable_observed_card_cannot_have_a_card_label() -> None:
    with pytest.raises(VisionAnnotationError, match="must not have a card identity"):
        ObservedCard(
            observed_card_id="observed-card-001",
            visual_card_identity="HEARTS_QUEEN",
            visibility="ambiguous_card",
            frame_observations=(FrameObservation("frame_04", None, False),),
            became_newly_visible=False,
            active_area_class="uncertain",
        )


def test_confirmed_card_play_cannot_be_created_as_a_draft() -> None:
    with pytest.raises(VisionAnnotationError, match="review_state reviewed"):
        TableObservationAnnotation(
            annotation_set_id="annotation-set-001",
            source=VisionSource(package_id="package-001"),
            observed_cards=(),
            event_review="confirmed_card_play",
            review_state="draft",
        )


@pytest.mark.parametrize(
    "fixture_name",
    ("malformed-unknown-field.json", "malformed-card-label.json"),
)
def test_malformed_table_observation_fixture_is_rejected(fixture_name: str) -> None:
    payload = json.loads((VISION_FIXTURE_ROOT / fixture_name).read_text())

    with pytest.raises(VisionAnnotationError):
        TableObservationAnnotation.from_mapping(payload)
