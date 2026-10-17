import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from dokodetector_backend.frame_review_queue import (
    QueueContractError,
    ReviewState,
    parse_frozen_queue,
    parse_review_receipt,
    review_state,
)

QUEUE_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "reports" / "0096-M4_Human_Review_Queue.json"
).resolve()


def _queue() -> dict:
    return json.loads(QUEUE_PATH.read_text())


def _digest(queue: dict) -> None:
    queue.pop("selection_sha256", None)
    canonical = json.dumps(queue, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    queue["selection_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()


def _receipt(item) -> dict:
    return {
        "schema_version": "frame-review-receipt/v1",
        "queue_id": item.queue_id,
        "queue_digest": item.queue_digest,
        "recording_id": item.recording_id,
        "stage": item.stage,
        "item_id": item.item_id,
        "source_revision_id": item.source_revision_id,
        "source_revision_sha256": item.source_revision_sha256,
        "scene_run_id": item.scene_run_id,
        "scene_revision_id": item.scene_revision_id,
        "draft_revision": 2,
        "decision_item_ids": ["card-1"],
        "saved_at": "2026-10-17T12:00:00Z",
    }


def test_frozen_queue_projects_165_exact_items_and_allows_partial_scene_output() -> None:
    items = parse_frozen_queue(_queue())
    assert len(items) == 165
    assert len({(item.recording_id, item.item_id) for item in items}) == 165
    calibration_item = next(item for item in items if item.scene_revision_id is None)
    assert calibration_item.source_revision_id
    assert calibration_item.result_available
    assert calibration_item.comparison_reference_revision_id is None


def test_queue_digest_duplicate_item_and_protected_source_are_rejected() -> None:
    queue = _queue()
    queue["recordings"][1]["review_frames"][0]["reasons"].append("changed")
    with pytest.raises(QueueContractError, match="digest"):
        parse_frozen_queue(queue)

    queue = _queue()
    duplicate = dict(queue["recordings"][1]["review_frames"][0])
    queue["recordings"][1]["review_frames"].append(duplicate)
    _digest(queue)
    with pytest.raises(QueueContractError, match="duplicate item_id"):
        parse_frozen_queue(queue)

    queue = _queue()
    protected_frame = next(
        frame
        for row in queue["recordings"]
        for frame in row["review_frames"]
        if frame["m4_training_overlap"]
    )
    _digest(queue)
    protected = next(
        item
        for item in parse_frozen_queue(queue)
        if item.item_id == protected_frame["item_id"]
        and item.recording_id == protected_frame["recording_id"]
    )
    assert protected.eligible
    assert not protected.comparison_eligible


def test_progress_distinguishes_comparison_reference_from_saved_proposal_review() -> None:
    item = parse_frozen_queue(_queue())[0]
    assert item.comparison_reference_revision_id is None
    assert review_state(item) is ReviewState.PENDING

    # Even a comparison reference does not count without a queue receipt for this result.
    item_with_comparison = replace(item, comparison_reference_revision_id="old-completed-reference")
    assert review_state(item_with_comparison) is ReviewState.PENDING


def test_matching_receipt_requires_current_draft_and_exact_result_lineage() -> None:
    item = parse_frozen_queue(_queue())[0]
    receipt = parse_review_receipt(_receipt(item))
    assert (
        review_state(
            item,
            receipt=receipt,
            current_draft_revision=2,
            current_decision_item_ids={"card-1"},
        )
        is ReviewState.SAVED
    )
    assert (
        review_state(
            item,
            receipt=receipt,
            current_draft_revision=3,
            current_decision_item_ids={"card-1"},
        )
        is ReviewState.UNAVAILABLE
    )

    stale = _receipt(item)
    stale["source_revision_id"] = "newer-result"
    assert (
        review_state(
            item,
            receipt=parse_review_receipt(stale),
            current_draft_revision=2,
            current_decision_item_ids={"card-1"},
        )
        is ReviewState.UNAVAILABLE
    )

    unrelated = _receipt(item)
    unrelated["recording_id"] = "another-recording"
    assert (
        review_state(
            item,
            receipt=parse_review_receipt(unrelated),
            current_draft_revision=2,
            current_decision_item_ids={"card-1"},
        )
        is ReviewState.UNAVAILABLE
    )


def test_missing_result_is_unavailable_and_does_not_become_deferred() -> None:
    queue = _queue()
    frame = queue["recordings"][1]["review_frames"][0]
    frame["m1_revision_id"] = None
    frame["m1_revision_sha256"] = None
    _digest(queue)
    item = parse_frozen_queue(queue)[0]
    assert review_state(item, deferred=True) is ReviewState.UNAVAILABLE


def test_receipt_needs_explicit_persisted_decision_links() -> None:
    item = parse_frozen_queue(_queue())[0]
    receipt = _receipt(item)
    receipt["decision_item_ids"] = []
    with pytest.raises(QueueContractError, match="decision_item_ids"):
        parse_review_receipt(receipt)
