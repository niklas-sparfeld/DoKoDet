from copy import deepcopy
from pathlib import Path

import pytest
from table_evidence_analyzer.pipeline_data import VisualIdentityData

from dokodetector_backend.pipeline_identity_review import (
    IDENTITY_QUESTION,
    IdentityReviewRefresh,
    crop_evidence,
)
from dokodetector_backend.pipeline_item_provenance import ItemProvenanceService
from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
from dokodetector_backend.pipeline_node_store import PipelineNodeStore

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10000000,
}
HUMAN = {"kind": "human", "id": "reviewer"}
PROCESSOR = {"kind": "processor", "id": "model"}


def outcome(card: str, digest: str, prediction: str = "CLUBS_NINE") -> dict:
    frame = {
        "schema_version": "exact-event/v1",
        "source_video_sha256": "a" * 64,
        "requested_time_us": 1000000,
        "frame_index": 0,
        "presentation_timestamp_us": 1000000,
        "width": 100,
        "height": 100,
        "decoder_version": "decoder.v1",
        "transform_version": "transform.v1",
        "output_encoding": "png",
        "content_type": "image/png",
        "image_sha256": "b" * 64,
        "policy": "exact-event/v1",
    }
    geometry = {
        "kind": "detector-box/v1",
        "box_2d": {"x_min": 1, "y_min": 1, "x_max": 50, "y_max": 50},
    }
    crop = {
        "schema_version": "visible-region-crop/v1",
        "status": "usable",
        "frame_identity": frame,
        "geometry": geometry,
        "pixel_bounds": {"x_min": 1, "y_min": 1, "x_max": 50, "y_max": 50},
        "crop_policy": "crop.v1",
        "output_encoding": "png",
        "content_type": "image/png",
        "decoder_version": "decoder.v1",
        "transform_version": "transform.v1",
        "image_sha256": digest * 64,
        "unusable_reason": None,
    }
    return {
        "card_id": card,
        "frame_identity": frame,
        "geometry": geometry,
        "crop_identity": crop,
        "classifier": {
            "provider": "fixture.identity",
            "implementation": {"name": "fixture", "version": "v1"},
            "model": {"name": "model", "version": "v1"},
        },
        "status": "classified",
        "candidates": [
            {
                "identity": prediction,
                "score": 0.8,
                "score_meaning": "probability",
                "producer_id": "model",
            }
        ],
        "unusable_reason": None,
        "error": None,
    }


def create(store, node, outcomes):
    data = VisualIdentityData.from_mapping(
        {"schema_version": "visual-identity-data/v2", "outcomes": outcomes}
    ).to_mapping()
    return ItemProvenanceService(store).create(
        node,
        node,
        "visual_identities",
        SOURCE,
        data,
        {o["card_id"]: f"/outcomes/{i}" for i, o in enumerate(outcomes)},
        PROCESSOR,
    )


def test_refresh_preserves_human_correction_only_for_unchanged_crop(tmp_path: Path):
    store = PipelineNodeStore(tmp_path)
    source = create(
        store, "old", [outcome("card-100", "c"), outcome("other", "d"), outcome("deleted", "e")]
    )
    reviews = PipelineNodeReviews(store)
    for i, item in enumerate(source.content["outcomes"]):
        reviews.item(
            f"r{i}",
            "old",
            source.revision_id,
            item["card_id"],
            IDENTITY_QUESTION,
            "HEARTS_QUEEN",
            HUMAN,
            crop_evidence(item),
        )
    # A scene edit changes the other card's visible crop; the first prediction changes on rerun.
    target = create(
        store, "new", [outcome("new-100", "c", "SPADES_QUEEN"), outcome("other-new", "f")]
    )
    result = IdentityReviewRefresh(store).refresh(
        "old",
        source.revision_id,
        "new",
        target.revision_id,
        [("card-100", "new-100"), ("other", "other-new")],
        ["r0", "r1", "r2"],
    )
    assert result["new-100"] == {
        "status": "applicable",
        "decision": "HEARTS_QUEEN",
        "review_id": "r0",
    }
    assert result["other-new"]["status"] == "inapplicable"
    assert target.content["outcomes"][0]["candidates"][0]["identity"] == "SPADES_QUEEN"
    assert reviews.get("r2")["decision"] == "HEARTS_QUEEN"


def test_policy_ambiguity_and_duplicate_card_labels(tmp_path: Path):
    store = PipelineNodeStore(tmp_path)
    old = create(store, "old", [outcome("a", "c"), outcome("b", "c")])
    reviews = PipelineNodeReviews(store)
    for index, item in enumerate(old.content["outcomes"]):
        reviews.item(
            f"r{index}",
            "old",
            old.revision_id,
            item["card_id"],
            IDENTITY_QUESTION,
            "CLUBS_NINE",
            HUMAN,
            crop_evidence(item),
        )
    changed = deepcopy(outcome("x", "c"))
    changed["crop_identity"]["crop_policy"] = "crop.v2"
    new = create(store, "new", [changed, outcome("y", "c"), outcome("z", "c")])
    service = IdentityReviewRefresh(store)
    result = service.refresh(
        "old", old.revision_id, "new", new.revision_id, [("a", "x"), ("b", "y")], ["r0", "r1"]
    )
    assert result["x"]["status"] == "inapplicable"
    assert result["y"]["status"] == "applicable"
    assert result["z"]["status"] == "unknown"
    ambiguous = service.refresh(
        "old", old.revision_id, "new", new.revision_id, [("a", "y"), ("b", "y")], ["r0", "r1"]
    )
    assert ambiguous["y"]["reason"] == "ambiguous correspondence"
    with pytest.raises(ValueError, match="absent item"):
        service.refresh("old", old.revision_id, "new", new.revision_id, [("deleted", "y")], [])


def test_review_evidence_and_question_must_match(tmp_path: Path):
    store = PipelineNodeStore(tmp_path)
    old = create(store, "old", [outcome("a", "c")])
    new = create(store, "new", [outcome("b", "c")])
    reviews = PipelineNodeReviews(store)
    reviews.item(
        "wrong-evidence",
        "old",
        old.revision_id,
        "a",
        IDENTITY_QUESTION,
        "CLUBS_NINE",
        HUMAN,
        {"policy": "other", "crop_sha256": "c" * 64},
    )
    reviews.item(
        "wrong-question",
        "old",
        old.revision_id,
        "a",
        "another question",
        "CLUBS_NINE",
        HUMAN,
        crop_evidence(old.content["outcomes"][0]),
    )
    service = IdentityReviewRefresh(store)
    result = service.refresh(
        "old", old.revision_id, "new", new.revision_id, [("a", "b")], ["wrong-evidence"]
    )
    assert result["b"]["status"] == "inapplicable"
    assert (
        service.refresh("old", old.revision_id, "new", new.revision_id, [("a", "b")], [])["b"][
            "status"
        ]
        == "unknown"
    )
    with pytest.raises(ValueError, match="not a visual identity decision"):
        service.refresh(
            "old", old.revision_id, "new", new.revision_id, [("a", "b")], ["wrong-question"]
        )
