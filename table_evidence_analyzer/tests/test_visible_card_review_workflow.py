from __future__ import annotations

import json
from pathlib import Path

import pytest

from table_evidence_analyzer.visible_card_review import ReviewedVisibleCard
from table_evidence_analyzer.visible_card_review_workflow import (
    VisibleCardReviewWorkflowError,
    build_visible_card_review_queue,
    finalize_visible_card_review,
    load_visible_card_review_queue,
    record_card_action,
    record_frame_review,
    update_frame_review,
    validate_completed_visible_card_review_queue,
)
from table_evidence_analyzer.visible_cards import (
    FakeVisibleCardProvider,
    VisibleCardRequest,
    load_run_artifact,
    write_run_artifact,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "visible_card_review_cases.json"


def _fixture(name: str) -> dict:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return payload["cases"][name]


def _artifact(
    tmp_path: Path,
    prediction: dict,
    *,
    package_id: str = "package-001",
    frame_part_name: str = "frame_00",
) -> tuple[dict, dict[str, dict[str, object]]]:
    request = VisibleCardRequest(
        package_id=package_id,
        frame_part_name=frame_part_name,
        target_offset_ms=0,
        image_bytes=b"frame-contents",
        width=1000,
        height=1000,
        provider="fake",
    )
    result = FakeVisibleCardProvider({request.image_sha256: prediction}).propose(request)
    artifact_path = tmp_path / f"{package_id}.json"
    write_run_artifact(
        request,
        result,
        artifact_path,
        image="frames/frame_00.jpg",
        overlay="overlays/frame_00.svg",
    )
    artifact = load_run_artifact(artifact_path)
    artifact["artifact_path"] = str(artifact_path)
    item_id = f"{package_id}:{frame_part_name}"
    lineage = {
        item_id: {
            "package_id": package_id,
            "frame_part_name": frame_part_name,
            "target_offset_ms": 0,
            "image": "frames/frame_00.jpg",
            "frame_sha256": request.image_sha256,
            "source_asset_id": "asset-001",
            "source_lineage_group": "session-001",
            "source_asset_sha256": None,
            "width": 1000,
            "height": 1000,
        }
    }
    return artifact, lineage


def _queue(
    tmp_path: Path,
    prediction: dict,
    *,
    package_id: str = "package-001",
) -> Path:
    artifact, lineage = _artifact(tmp_path, prediction, package_id=package_id)
    queue_path = tmp_path / f"{package_id}-queue.json"
    build_visible_card_review_queue(
        [artifact],
        queue_path,
        run_id="review-run-001",
        lineage_by_item=lineage,
    )
    return queue_path


def test_good_review_resumes_and_preserves_source_and_teacher_lineage(tmp_path: Path) -> None:
    case = _fixture("overlapping_cards")
    queue_path = _queue(tmp_path, case["teacher_prediction"])

    partial = record_frame_review(
        queue_path,
        "package-001:frame_00",
        "GOOD",
        reviewer="operator",
        empty_frame=False,
    )
    assert partial.pending_items[0].review.status == "in_progress"

    for action in case["actions"]:
        partial = record_card_action(
            queue_path,
            "package-001:frame_00",
            action,
            reviewer="operator",
        )
    completed = finalize_visible_card_review(
        queue_path,
        "package-001:frame_00",
        reviewer="operator",
    )
    validate_completed_visible_card_review_queue(completed)

    item = completed.items[0]
    assert completed.revision == 4
    assert item.review.status == "reviewed"
    assert item.source.source_lineage_group == "session-001"
    assert item.source.frame_sha256 == item.teacher.request["image_sha256"]
    assert item.teacher.result_path.endswith("package-001.json")
    assert item.teacher.result["raw_response"]["provider"] == "fake"
    assert item.review.actions[0].action == "reshaped"
    reshaped = item.review.actions[0].reviewed_card
    assert reshaped is not None
    assert all(
        not (point["x"] > 300 and point["y"] > 250)
        for point in [
            point
            for polygon in reshaped.to_mapping()["visible_region"]["polygons"]
            for point in polygon
        ]
    )


def test_disconnected_visible_region_is_a_single_card_and_box_is_derived(tmp_path: Path) -> None:
    case = _fixture("disconnected_visible_region")
    teacher = {
        "cards": [
            {
                "box_2d": {"y_min": 100, "x_min": 100, "y_max": 500, "x_max": 800},
                "polygon": [
                    {"x": 100, "y": 100},
                    {"x": 800, "y": 100},
                    {"x": 800, "y": 500},
                    {"x": 100, "y": 500},
                ],
                "side": "unknown",
                "label": "occluded card",
            }
        ]
    }
    queue_path = _queue(tmp_path, teacher)
    record_frame_review(
        queue_path,
        "package-001:frame_00",
        "GOOD",
        reviewer="operator",
        empty_frame=False,
        actions=[
            {
                "card_id": "card-001",
                "action": "reshaped",
                "proposal_index": 0,
                "reviewed_card": case["reviewed_card"],
            }
        ],
    )
    completed = load_visible_card_review_queue(queue_path)
    assert completed.items[0].review.status == "reviewed"
    reviewed_card = completed.items[0].review.actions[0].reviewed_card
    assert reviewed_card is not None
    assert len(reviewed_card.visible_region.polygons) == 2
    assert reviewed_card.derived_box.box_2d.x_max == 800


@pytest.mark.parametrize("fixture_name", ["empty_frame", "bad_frame"])
def test_bad_and_reviewed_empty_frames_are_distinct(tmp_path: Path, fixture_name: str) -> None:
    case = _fixture(fixture_name)
    queue_path = _queue(tmp_path, {"cards": []}, package_id=fixture_name)
    completed = record_frame_review(
        queue_path,
        f"{fixture_name}:frame_00",
        case["decision"],
        reviewer="operator",
        empty_frame=case["empty_frame"],
        failure_tags=case.get("failure_tags", []),
    )

    review = completed.items[0].review
    assert review.status == "reviewed"
    assert review.decision == "BAD"
    assert review.empty_frame is case["empty_frame"]
    assert (review.empty_frame is True) != (fixture_name == "bad_frame")
    validate_completed_visible_card_review_queue(completed)


def test_remove_and_add_actions_cover_all_teacher_proposals(tmp_path: Path) -> None:
    teacher = _fixture("overlapping_cards")["teacher_prediction"]
    teacher["cards"] = teacher["cards"][:1]
    queue_path = _queue(tmp_path, teacher)
    record_frame_review(
        queue_path,
        "package-001:frame_00",
        "GOOD",
        reviewer="operator",
        empty_frame=False,
    )
    added_card = _fixture("occluded_card")["reviewed_card"]
    record_card_action(
        queue_path,
        "package-001:frame_00",
        {
            "card_id": "card-001",
            "action": "removed",
            "proposal_index": 0,
            "reviewed_card": None,
        },
        reviewer="operator",
    )
    record_card_action(
        queue_path,
        "package-001:frame_00",
        {
            "card_id": "card-added-001",
            "action": "added",
            "proposal_index": None,
            "reviewed_card": {**added_card, "card_id": "card-added-001"},
        },
        reviewer="operator",
    )
    completed = finalize_visible_card_review(
        queue_path,
        "package-001:frame_00",
        reviewer="operator",
    )
    assert [action.action for action in completed.items[0].review.actions] == [
        "removed",
        "added",
    ]


def test_incomplete_review_cannot_be_validated_as_dataset_input(tmp_path: Path) -> None:
    case = _fixture("overlapping_cards")
    queue_path = _queue(tmp_path, case["teacher_prediction"])
    partial = record_frame_review(
        queue_path,
        "package-001:frame_00",
        "GOOD",
        reviewer="operator",
        empty_frame=False,
    )

    with pytest.raises(VisibleCardReviewWorkflowError, match="incomplete"):
        validate_completed_visible_card_review_queue(partial)

    malformed = json.loads(queue_path.read_text(encoding="utf-8"))
    malformed["items"][0]["review"]["status"] = "reviewed"
    queue_path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(VisibleCardReviewWorkflowError):
        load_visible_card_review_queue(queue_path)


def test_queue_requires_explicit_source_lineage(tmp_path: Path) -> None:
    artifact, _ = _artifact(tmp_path, {"cards": []})

    with pytest.raises(VisibleCardReviewWorkflowError, match="source lineage is incomplete"):
        build_visible_card_review_queue(
            [artifact],
            tmp_path / "queue.json",
            run_id="review-run-001",
        )


def test_accepted_action_must_keep_teacher_geometry(tmp_path: Path) -> None:
    teacher = _fixture("overlapping_cards")["teacher_prediction"]
    queue_path = _queue(tmp_path, {"cards": teacher["cards"][:1]})
    bad_card = _fixture("occluded_card")["reviewed_card"]

    with pytest.raises(VisibleCardReviewWorkflowError, match="accepted action"):
        record_frame_review(
            queue_path,
            "package-001:frame_00",
            "GOOD",
            reviewer="operator",
            empty_frame=False,
            actions=[
                {
                    "card_id": "card-001",
                    "action": "accepted",
                    "proposal_index": 0,
                    "reviewed_card": bad_card,
                }
            ],
        )


def test_reviewed_card_fixture_round_trips_as_contract() -> None:
    card = ReviewedVisibleCard.from_mapping(_fixture("occluded_card")["reviewed_card"])
    assert card.identity_usability.usable is False
    assert card.failure_tags == ("occlusion", "human_hand")


def test_full_frame_update_increments_revision_and_rejects_stale_writes(
    tmp_path: Path,
) -> None:
    queue_path = _queue(tmp_path, {"cards": []}, package_id="revision-001")
    review = {
        "status": "reviewed",
        "decision": "BAD",
        "empty_frame": True,
        "failure_tags": [],
        "actions": [],
        "reviewer": "operator",
    }

    updated = update_frame_review(
        queue_path,
        "revision-001:frame_00",
        review,
        expected_revision=0,
    )

    assert updated.revision == 1
    assert updated.items[0].review.status == "reviewed"
    before_stale_write = queue_path.read_bytes()
    with pytest.raises(VisibleCardReviewWorkflowError, match="revision"):
        update_frame_review(
            queue_path,
            "revision-001:frame_00",
            review,
            expected_revision=0,
        )
    assert queue_path.read_bytes() == before_stale_write
