from copy import deepcopy
from pathlib import Path

import pytest
from doko_operations.card_plane_geometry import (
    CardPose,
    CardStackingOrder,
    ReviewedCardScene,
    derive_pose_scene_visible_regions,
)
from table_evidence_analyzer.card_scene_contract import (
    CardReviewState,
    CardSceneDraft,
    FrameReviewCompletion,
    ProposedCardScene,
    ReviewedCardSceneRecord,
)
from table_evidence_analyzer.pipeline_data import (
    ProposedCardSceneData,
    ProposedCardSceneFrame,
    VisibleCardFrameIdentity,
)

from dokodetector_backend.pipeline_item_provenance import ItemProvenanceService
from dokodetector_backend.pipeline_node_edits import PipelineNodeEdits
from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.virtual_scene_data import (
    from_draft,
    from_proposed,
    validate_virtual_scenes,
)

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10000000,
}
HUMAN = {"kind": "human", "id": "reviewer"}
PROCESSOR = {"kind": "processor", "id": "initializer"}
FRAME = {
    "schema_version": "exact-event/v1",
    "source_video_sha256": "a" * 64,
    "requested_time_us": 1000000,
    "frame_index": 0,
    "presentation_timestamp_us": 1000000,
    "width": 24,
    "height": 24,
    "decoder_version": "decoder.v1",
    "transform_version": "transform.v1",
    "output_encoding": "png",
    "content_type": "image/png",
    "image_sha256": "b" * 64,
    "policy": "exact-event/v1",
}


def scene(poses, order, calibration="calibration-1", digest="c" * 64):
    return ReviewedCardScene.create(
        source_frame_id="frame-1",
        source_frame_width=24,
        source_frame_height=24,
        calibration_revision_id=calibration,
        calibration_digest=digest,
        poses=poses,
        stacking_order=CardStackingOrder(tuple(order), (), ()),
    )


def pose(card, x=12.0):
    return CardPose(card, (x, 12.0), 0, None, None)


def proposal(geometry):
    return ProposedCardScene.create(
        proposal_id="proposal-1",
        source_frame_id="frame-1",
        source_frame_digest="b" * 64,
        detector_revision_id="detector-1",
        detector_revision_digest="d" * 64,
        calibration_revision_id="calibration-1",
        calibration_digest="c" * 64,
        initializer_recipe_version="initializer/v1",
        status="supported",
        initialized_scene=geometry.to_mapping(),
        fit_diagnostics={},
    )


def regions():
    polygon = [[{"x": 100, "y": 100}, {"x": 200, "y": 100}, {"x": 200, "y": 200}]]
    norm = {"width": 24, "height": 24, "policy_id": "full-frame-0-1000/v1"}
    pile = {
        "pile_id": "pile",
        "geometry": {"kind": "pile-region/v1", "polygons": polygon},
        "normalization": norm,
        "source_candidates": [],
    }
    ignored = {
        "region_id": "ignore",
        "geometry": {"kind": "reviewed-ignore-region/v1", "polygons": polygon},
        "normalization": norm,
        "reason": "untidy_stack",
        "source_candidates": [],
    }
    return pile, ignored


def test_mapping_round_trip_review_provenance_and_hidden_card(tmp_path: Path):
    initial = scene([pose("front"), pose("back")], ["front", "back"])
    proposed = proposal(initial)
    frame = ProposedCardSceneFrame(
        "frame-1",
        "b" * 64,
        "supported",
        proposed,
        None,
        VisibleCardFrameIdentity.from_mapping(FRAME),
    )
    data = ProposedCardSceneData.create(
        detector_revision_id="detector-1",
        detector_revision_digest="d" * 64,
        calibration_revision_id="calibration-1",
        calibration_digest="c" * 64,
        calibration={"value": "fixture"},
        calibration_diagnostics={"status": "pass"},
        frames=[frame],
    )
    mapped = from_proposed(data)
    content = mapped["content"]
    assert mapped["source_proposal"]["data_digest"] == data.data_digest
    store = PipelineNodeStore(tmp_path)
    first = ItemProvenanceService(store).create(
        "node",
        "Scenes",
        "virtual_scenes",
        SOURCE,
        content,
        {
            "front": "/frames/0/scene/poses/0",
            "back": "/frames/0/scene/poses/1",
            "order": "/frames/0/scene/stacking_order",
        },
        PROCESSOR,
    )
    view = derive_pose_scene_visible_regions(
        first.content["frames"][0]["scene"],
        {
            "table_to_image_homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "card_short_size": 6,
            "card_long_size": 10,
        },
    )
    assert view.hidden_card_ids == ("back",)
    reviews = PipelineNodeReviews(store)
    reviews.item(
        "review",
        "node",
        first.revision_id,
        "front",
        "pose correct?",
        "yes",
        HUMAN,
        {"policy": "frame/v1", "frame_sha256": "b" * 64},
    )
    reviews.coverage(
        "coverage",
        "node",
        first.revision_id,
        "missing cards?",
        {"frame": "frame-1", "result": "inspected"},
        HUMAN,
        {"policy": "frame/v1", "frame_sha256": "b" * 64},
    )
    new_scene = scene([pose("front", 11), pose("back")], ["back", "front"])
    pile, ignored = regions()
    changed = deepcopy(first.content)
    changed["frames"][0].update(
        scene=new_scene.to_mapping(), pile_regions=[pile], ignore_regions=[ignored]
    )
    revision = PipelineNodeEdits(store).edit(
        "node",
        first.revision_id,
        changed,
        "edit",
        HUMAN,
        pointers={
            "front": "/frames/0/scene/poses/0",
            "back": "/frames/0/scene/poses/1",
            "order": "/frames/0/scene/stacking_order",
            "pile": "/frames/0/pile_regions/0",
            "ignore": "/frames/0/ignore_regions/0",
        },
        operations=[
            {"kind": "replace", "before": ["front"], "after": ["front"]},
            {"kind": "replace", "before": ["order"], "after": ["order"]},
            {"kind": "insert", "before": [], "after": ["pile"]},
            {"kind": "insert", "before": [], "after": ["ignore"]},
        ],
    )
    loaded = PipelineNodeStore(tmp_path).read_revision("node", revision["revision_id"])
    assert loaded.content["frames"][0]["scene"]["stacking_order"]["card_ids"] == ["back", "front"]
    assert loaded.content["frames"][0]["pile_regions"][0]["pile_id"] == "pile"
    assert loaded.content["frames"][0]["ignore_regions"][0]["region_id"] == "ignore"
    changes = loaded.metadata["item_provenance"]["changes"]
    assert any(c["actor"] == PROCESSOR for c in changes)
    assert any(c["actor"] == HUMAN for c in changes)
    assert reviews.get("review")["decision"] == "yes"
    assert reviews.get("coverage")["coverage"]["result"] == "inspected"
    assert store.read_revision("node", first.revision_id).content == first.content


def test_mixed_draft_mapping_requires_explicit_order():
    initial = scene([pose("a"), pose("b", 9)], ["a", "b"])
    prop = proposal(initial)
    corrected = scene([pose("a", 13), pose("manual", 15)], ["manual", "a"])
    reviewed = ReviewedCardSceneRecord.create(
        proposal_id=prop.proposal_id, scene=corrected.to_mapping(), decision="adjusted"
    )
    states = [
        CardReviewState.create(
            card_id="a", source="proposal", proposal_id=prop.proposal_id, state="adjusted"
        ),
        CardReviewState.create(
            card_id="b", source="proposal", proposal_id=prop.proposal_id, state="pending"
        ),
        CardReviewState.create(
            card_id="manual", source="manual", proposal_id=None, state="accepted"
        ),
    ]
    draft = CardSceneDraft.create(
        proposal=prop,
        reviewed=reviewed,
        card_states=states,
        completion=FrameReviewCompletion.create(state="pending", unresolved_card_ids=["b"]),
    )
    with pytest.raises(ValueError, match="explicit complete scene"):
        from_draft(draft, FRAME)
    combined = scene([pose("a", 13), pose("b", 9), pose("manual", 15)], ["b", "manual", "a"])
    mapped = from_draft(draft, FRAME, scene=combined.to_mapping())
    assert mapped["content"]["frames"][0]["scene"] == combined.to_mapping()
    assert mapped["legacy_review"]["reviewer"] is None
    assert mapped["legacy_review"]["completion"]["state"] == "pending"
    bad = scene([pose("a", 14), pose("b", 9), pose("manual", 15)], ["b", "manual", "a"])
    with pytest.raises(ValueError, match="changes retained poses"):
        from_draft(draft, FRAME, scene=bad.to_mapping())


def test_calibration_and_frame_dependencies_are_validated(tmp_path: Path):
    geometry = scene([pose("a")], ["a"])
    content = {
        "schema_version": "virtual-scene-data/v1",
        "frames": [
            {
                "frame_id": "frame-1",
                "frame_identity": FRAME,
                "calibration": {"revision_id": "calibration-1", "digest": "c" * 64},
                "scene": geometry.to_mapping(),
                "pile_regions": [],
                "ignore_regions": [],
            }
        ],
    }
    store = PipelineNodeStore(tmp_path)
    first = store.create("node", "scene", "virtual_scenes", SOURCE, content, {})
    changed = deepcopy(content)
    changed["frames"][0]["calibration"] = {"revision_id": "calibration-2", "digest": "e" * 64}
    with pytest.raises(ValueError, match="frame or calibration"):
        validate_virtual_scenes(changed)
    changed["frames"][0]["scene"] = scene(
        [pose("a")], ["a"], "calibration-2", "e" * 64
    ).to_mapping()
    second = store.save("node", first.revision_id, changed, {})
    assert second.content["frames"][0]["calibration"]["revision_id"] == "calibration-2"
    bad_source = deepcopy(content)
    bad_source["frames"][0]["frame_identity"]["source_video_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="source video"):
        store.create("bad", "bad", "virtual_scenes", SOURCE, bad_source, {})
