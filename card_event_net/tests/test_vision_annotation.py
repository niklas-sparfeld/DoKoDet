from __future__ import annotations

import json
from pathlib import Path

import pytest

from cardevent.vision_annotation import (
    TABLE_OBSERVATION_SCHEMA_VERSION,
    BoundingBox,
    FrameObservation,
    ObservedCard,
    TableObservationAnnotation,
    VideoSnippet,
    VisionAnnotationError,
    VisionSource,
    import_evidence_packages,
    load_vision_annotation,
    save_vision_annotation,
)
from cardevent.vision_review import (
    VisionReviewError,
    apply_table_observation_review,
    build_table_observation_review,
    save_table_observation_review,
)
from cardevent.vision_viewer import VisionAnnotationViewer

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "evidence" / "v2"
VISION_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "vision_annotation"


def _annotation(*, event_review: str = "unreviewed") -> TableObservationAnnotation:
    return TableObservationAnnotation(
        annotation_set_id="annotation-set-001",
        source=VisionSource(package_id="package-001"),
        observed_cards=(
            ObservedCard(
                observed_card_id="observed-card-001",
                visual_card_identity="HEARTS_QUEEN",
                visibility="identifiable",
                frame_observations=(
                    FrameObservation(
                        frame_id="frame_04",
                        bbox=BoundingBox(10, 20, 110, 140),
                        usable_for_identity=True,
                        tags=("glare", "partial_occlusion"),
                    ),
                ),
                became_newly_visible=True,
                active_area_class="inside",
            ),
        ),
        event_review=event_review,
        review_state="draft",
        video_snippet=VideoSnippet("snippet-001", 1000, 2000),
    )


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


def test_evidence_import_keeps_proposals_draft_and_preserves_all_frames() -> None:
    annotations = import_evidence_packages(
        [
            FIXTURE_ROOT / "example-incomplete",
            FIXTURE_ROOT / "example-complete" / "manifest.json",
        ]
    )

    assert len(annotations) == 2
    assert all(annotation.review_state == "draft" for annotation in annotations)
    assert all(annotation.event_review == "unreviewed" for annotation in annotations)
    assert annotations[0].observed_cards[0].frame_observations
    assert annotations[0].observed_cards[0].visual_card_identity is None
    assert annotations[0].observed_cards[0].visibility == "card_not_visible"


def test_review_and_apply_write_new_immutable_artifacts(tmp_path: Path) -> None:
    source_path = tmp_path / "draft.json"
    save_vision_annotation(_annotation(), source_path)
    source_bytes = source_path.read_bytes()
    review = build_table_observation_review(
        load_vision_annotation(source_path),
        reviewer="niklas",
        event_decision="confirm_card_play",
        review_id="review-001",
        reviewed_at="2026-08-27T12:00:00Z",
    )
    review_path = tmp_path / "review.json"
    save_table_observation_review(review, review_path)

    summary = apply_table_observation_review(
        source_path,
        review_path,
        out_dir=tmp_path / "applied",
    )

    assert summary["event_decision"] == "confirm_card_play"
    assert source_path.read_bytes() == source_bytes
    applied = load_vision_annotation(tmp_path / "applied" / "annotation-set-001.json")
    assert applied.review_state == "reviewed"
    assert applied.event_review == "confirmed_card_play"
    assert (tmp_path / "applied" / "table-observation-apply-receipt.json").is_file()
    assert summary["lifecycle_receipt"]["receipt_type"] == "annotation_application"

    with pytest.raises(VisionReviewError, match="not empty"):
        apply_table_observation_review(source_path, review_path, out_dir=tmp_path / "applied")


def test_rejected_event_keeps_visible_card_evidence_but_not_event_label() -> None:
    review = build_table_observation_review(
        _annotation(),
        reviewer="niklas",
        event_decision="reject_event",
    )

    assert review.reviewed_annotation.event_review == "false_event_proposal"
    assert review.reviewed_annotation.observed_cards[0].visual_card_identity == "HEARTS_QUEEN"
    assert review.reviewed_annotation.review_state == "reviewed"


def test_viewer_renders_all_card_boxes_without_opening_a_window(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    frame_path = tmp_path / "frame_04.jpg"
    assert cv2.imwrite(str(frame_path), np.zeros((160, 120, 3), dtype=np.uint8))
    viewer = VisionAnnotationViewer(_annotation(), {"frame_04": frame_path})

    frame = viewer.render_frame(0)

    assert frame.shape == (160, 120, 3)
