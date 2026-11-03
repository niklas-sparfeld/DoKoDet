from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from doko_operations.pipeline_reference import (
    PipelineReferenceDraft,
    PipelineReferenceState,
)

from dokodetector_backend.pipeline_reference_store import (
    PipelineReferenceStore,
    StoredPipelineReference,
)
from dokodetector_backend.visible_card_review_store import (
    VisibleCardReviewConflict,
    VisibleCardReviewStore,
)

TIMESTAMP = "2026-11-03T10:00:00.000000Z"


def _reference(*, revision: int = 0, decision: str = "pending") -> StoredPipelineReference:
    draft = PipelineReferenceDraft.from_mapping(
        {
            "schema_version": "pipeline-reference-draft/v2",
            "recording_id": "recording-01",
            "content_type": "visible_cards",
            "revision": revision,
            "source_revision_id": "detector-revision-01",
            "items": [
                {
                    "item_id": "frame-01-card-01",
                    "base_item_id": None,
                    "review_state": decision,
                    "item": {"card_id": "card-01", "frame_id": "frame-01"},
                }
            ],
            "coverage": None,
            "impact": [],
            "updated_at": TIMESTAMP,
        }
    )
    state = PipelineReferenceState.from_mapping(
        {
            "schema_version": "pipeline-reference-state/v1",
            "recording_id": "recording-01",
            "content_type": "visible_cards",
            "draft_revision": revision,
            "draft_state": "draft",
            "source_revision_id": "detector-revision-01",
            "selected_completed_revision_id": "completed-visible-cards-01",
            "updated_at": TIMESTAMP,
        }
    )
    return StoredPipelineReference(state=state, draft=draft)


def _create(
    store: VisibleCardReviewStore,
    review_id: str,
    *,
    decision: str = "pending",
    commands: dict[str, str] | None = None,
    updated_at: str = TIMESTAMP,
) -> object:
    ref = _reference(decision=decision)
    if updated_at != TIMESTAMP:
        ref = StoredPipelineReference(
            state=PipelineReferenceState.from_mapping(
                {**ref.state.to_mapping(), "updated_at": updated_at}
            ),
            draft=PipelineReferenceDraft.from_mapping(
                {**ref.draft.to_mapping(), "updated_at": updated_at}
            ),
        )
    return store.create(
        recording_id="recording-01",
        review_id=review_id,
        source="visible_regions",
        lineage={"detector_revision_id": "detector-revision-01"},
        reference=ref,
        commands=commands,
    )


def test_reviews_are_isolated_durable_and_selected_by_review_id(tmp_path: Path) -> None:
    store = VisibleCardReviewStore(tmp_path / "pipeline-reviews")
    first = _create(store, "review-01", decision="accepted", commands={"edit-01": "a" * 64})
    second = _create(store, "review-02", decision="pending")
    _create(store, "review-03", updated_at="2026-11-03T09:00:00.000000Z")

    assert first.reference.draft.items[0].review_state == "accepted"
    assert second.reference.draft.items[0].review_state == "pending"
    assert first.commands == {"edit-01": "a" * 64}
    assert second.commands == {}
    assert [review.review_id for review in store.list_reviews("recording-01")] == [
        "review-01",
        "review-02",
        "review-03",
    ]

    restarted = VisibleCardReviewStore(tmp_path / "pipeline-reviews")
    first_restored = restarted.get("recording-01", "review-01")
    second_restored = restarted.get("recording-01", "review-02")
    assert first_restored.reference.draft.items[0].review_state == "accepted"
    assert second_restored.reference.draft.items[0].review_state == "pending"


def test_legacy_review_is_read_only_and_preserves_selected_completion(tmp_path: Path) -> None:
    legacy = PipelineReferenceStore(tmp_path / "pipeline-references")
    with legacy.locked("recording-01", "visible_cards"):
        legacy.write_locked(_reference(decision="accepted"))
        legacy.write_commands_locked("recording-01", "visible_cards", {"legacy-edit": "b" * 64})
    state_before = legacy.state_path("recording-01", "visible_cards").read_bytes()
    draft_before = legacy.draft_path("recording-01", "visible_cards").read_bytes()
    commands_before = legacy.command_path("recording-01", "visible_cards").read_bytes()

    store = VisibleCardReviewStore(
        tmp_path / "pipeline-reviews", legacy_reference_store=legacy
    )
    review = store.get("recording-01", "legacy-visible-cards")
    assert review.legacy
    assert review.reference.state.selected_completed_revision_id == "completed-visible-cards-01"
    assert review.reference.draft.items[0].review_state == "accepted"
    assert review.commands == {"legacy-edit": "b" * 64}
    assert legacy.state_path("recording-01", "visible_cards").read_bytes() == state_before
    assert legacy.draft_path("recording-01", "visible_cards").read_bytes() == draft_before
    assert legacy.command_path("recording-01", "visible_cards").read_bytes() == commands_before
    assert [item.review_id for item in store.list_reviews("recording-01")] == [
        "legacy-visible-cards"
    ]


def test_concurrent_creates_publish_complete_reviews_and_reject_duplicate_ids(
    tmp_path: Path,
) -> None:
    store = VisibleCardReviewStore(tmp_path / "pipeline-reviews")
    with ThreadPoolExecutor(max_workers=6) as pool:
        created = list(pool.map(lambda index: _create(store, f"review-{index:02d}"), range(6)))
    assert len({review.review_id for review in created}) == 6
    assert len(store.list_reviews("recording-01")) == 6
    with pytest.raises(VisibleCardReviewConflict):
        _create(store, "review-00")


def test_interrupted_creation_does_not_replace_existing_review(tmp_path: Path, monkeypatch) -> None:
    import dokodetector_backend.visible_card_review_store as review_store_module

    store = VisibleCardReviewStore(tmp_path / "pipeline-reviews")
    original = _create(store, "review-01", decision="accepted")

    def fail_publish(*_args, **_kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(review_store_module, "commit_staged_directory", fail_publish)
    with pytest.raises(OSError, match="simulated disk failure"):
        _create(store, "review-02")

    restored = VisibleCardReviewStore(tmp_path / "pipeline-reviews")
    assert restored.get("recording-01", "review-01").to_mapping() == original.to_mapping()
    assert [review.review_id for review in restored.list_reviews("recording-01")] == [
        "review-01"
    ]
