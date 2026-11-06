"""Create and edit isolated visible-card reviews."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping
from uuid import uuid4

from dokodetector_backend.pipeline_reference_errors import (
    PipelineReferenceConflict,
    PipelineReferenceInputError,
)
from dokodetector_backend.pipeline_reference_store import StoredPipelineReference
from dokodetector_backend.pipeline_store import PipelineNotFound, PipelineSelectionConflict
from dokodetector_backend.visible_card_review_store import (
    StoredVisibleCardReview,
    VisibleCardReviewConflict,
    VisibleCardReviewStore,
)


class _ReviewReferenceStore:
    """Present one review as a reference store to the existing operation validator."""

    def __init__(self, store: VisibleCardReviewStore, recording_id: str, review_id: str):
        self.store = store
        self.recording_id = recording_id
        self.review_id = review_id
        self._commands: dict[str, str] = {}

    def locked(self, recording_id: str, content_type: str):
        if recording_id != self.recording_id or content_type != "visible_cards":
            raise PipelineReferenceInputError("review identity does not match the command")
        return self.store.locked_review(recording_id, self.review_id)

    def read_locked(self, recording_id: str, content_type: str) -> StoredPipelineReference:
        review = self.store.get(recording_id, self.review_id)
        self._commands = dict(review.commands)
        return review.reference

    def read_commands_locked(self, recording_id: str, content_type: str) -> dict[str, str]:
        return dict(self._commands)

    def get(self, recording_id: str, content_type: str) -> StoredPipelineReference | None:
        if recording_id != self.recording_id or content_type != "visible_cards":
            return None
        return self.store.get(recording_id, self.review_id).reference

    def write_locked(self, reference: StoredPipelineReference) -> StoredPipelineReference:
        review = self.store.update_review(
            self.recording_id, self.review_id, reference, self._commands
        )
        return review.reference

    def write_commands_locked(
        self, recording_id: str, content_type: str, commands: Mapping[str, str]
    ) -> None:
        self._commands = dict(commands)
        current = self.store.get(recording_id, self.review_id)
        self.store.update_review(recording_id, self.review_id, current.reference, self._commands)


class VisibleCardReviewService:
    """Own review-scoped creation, retrieval, and draft commands."""

    def __init__(self, *, store: VisibleCardReviewStore, reference_service: Any):
        self.store = store
        self.reference_service = reference_service

    def create(self, recording_id: str, payload: Mapping[str, Any]) -> StoredVisibleCardReview:
        if not isinstance(payload, Mapping):
            raise PipelineReferenceInputError("the visible-card review request must be an object")
        allowed = {
            "operator_id",
            "seed",
            "source_revision_id",
            "proposal_revision_id",
            "idempotency_key",
        }
        if set(payload) - allowed:
            raise PipelineReferenceInputError("the visible-card review request has unknown fields")
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or not key:
            raise PipelineReferenceInputError("idempotency_key is required")
        request_bytes = json.dumps(
            dict(payload), ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        request_digest = hashlib.sha256(request_bytes).hexdigest()
        prior = self.store.find_idempotent(recording_id, key, request_digest)
        if prior is not None:
            return prior
        reference = self.reference_service.create_reference(
            recording_id,
            "visible_cards",
            {k: v for k, v in payload.items() if k != "idempotency_key"},
            review_creation=True,
        )
        lineage = self._lineage(recording_id, reference)
        source = "card_scenes" if reference.draft.proposal_revision_id else "visible_regions"
        return self.store.create(
            recording_id=recording_id,
            review_id=f"visible-cards-{uuid4().hex}",
            source=source,
            lineage=lineage,
            reference=reference,
            idempotency_key=key,
            request_digest=request_digest,
        )

    def list(self, recording_id: str) -> tuple[StoredVisibleCardReview, ...]:
        return self.store.list_reviews(recording_id)

    def get(self, recording_id: str, review_id: str) -> StoredVisibleCardReview:
        return self.store.get(recording_id, review_id)

    def update(
        self, recording_id: str, review_id: str, payload: Mapping[str, Any]
    ) -> StoredVisibleCardReview:
        if review_id == "legacy-visible-cards":
            raise PipelineReferenceInputError("the legacy visible-card review is read-only")
        if not isinstance(payload, Mapping) or not isinstance(payload.get("command_id"), str):
            raise PipelineReferenceInputError("command_id is required for a review edit")
        if "expected_revision" not in payload:
            raise PipelineReferenceInputError("expected_revision is required for a review edit")
        adapter = _ReviewReferenceStore(self.store, recording_id, review_id)
        try:
            self.reference_service.update_draft(
                recording_id, "visible_cards", payload, store_override=adapter
            )
        except VisibleCardReviewConflict as error:
            raise PipelineReferenceConflict(
                str(error), adapter.get(recording_id, "visible_cards")
            ) from error
        return self.store.get(recording_id, review_id)

    def complete(
        self, recording_id: str, review_id: str, payload: Mapping[str, Any]
    ) -> StoredVisibleCardReview:
        if review_id == "legacy-visible-cards":
            raise PipelineReferenceInputError("the legacy visible-card review is read-only")
        if not isinstance(payload, Mapping):
            raise PipelineReferenceInputError("the review completion request must be an object")
        review = self.store.get(recording_id, review_id)
        if review.status == "completed":
            raise PipelineReferenceInputError("the visible-card review is already complete")
        adapter = _ReviewReferenceStore(self.store, recording_id, review_id)
        self.reference_service.complete_reference(
            recording_id,
            "visible_cards",
            payload,
            store_override=adapter,
            select_completed=False,
            producer_review_id=review_id,
            review_lineage=review.lineage,
        )
        return self.store.get(recording_id, review_id)

    def select_completed(
        self, recording_id: str, review_id: str, expected_selection_revision: Any
    ) -> dict[str, Any]:
        if (
            isinstance(expected_selection_revision, bool)
            or not isinstance(expected_selection_revision, int)
            or expected_selection_revision < 0
        ):
            raise PipelineReferenceInputError(
                "expected_selection_revision must be a non-negative integer"
            )
        review = self.store.get(recording_id, review_id)
        revision_id = review.reference.state.selected_completed_revision_id
        if review.status != "completed" or revision_id is None:
            raise PipelineReferenceInputError("the review has no completed revision to select")
        try:
            revision = self.reference_service.revision_store.require(revision_id)
        except PipelineNotFound as error:
            raise PipelineReferenceInputError(
                "the completed review revision is unavailable"
            ) from error
        if (
            revision.manifest.recording_id != recording_id
            or revision.manifest.content_type != "visible_cards"
            or revision.manifest.producer.review_id != review_id
        ):
            raise PipelineReferenceInputError(
                "the completed revision does not belong to this review"
            )
        selection_store = self.reference_service.selection_store
        current = selection_store.get(recording_id, "visible_cards")
        current_revision = 0 if current is None else current.revision
        if current_revision != expected_selection_revision:
            raise PipelineReferenceConflict(
                "the downstream visible-card selection changed; reload it", review.reference
            )
        try:
            selected = selection_store.update_pointers(
                recording_id,
                "visible_cards",
                expected_revision=expected_selection_revision,
                selected_generated_revision_id=(
                    None if current is None else current.selected_generated_revision_id
                ),
                selected_completed_reference_revision_id=revision_id,
            )
        except PipelineSelectionConflict as error:
            raise PipelineReferenceConflict(
                "the downstream visible-card selection changed; reload it", review.reference
            ) from error
        return selected.to_mapping()

    def _lineage(self, recording_id: str, reference: StoredPipelineReference) -> dict[str, Any]:
        lineage: dict[str, Any] = {
            "source_revision_id": reference.draft.source_revision_id,
            "proposal_revision_id": reference.draft.proposal_revision_id,
        }
        source_id = reference.draft.source_revision_id
        if source_id is not None:
            source = self.reference_service.revision_store.require(source_id)
            if source.manifest.recording_id != recording_id:
                raise PipelineReferenceInputError("source revision belongs to another recording")
            lineage["detector_revision_digest"] = source.manifest.content_sha256
            content = source.content
            outcomes = getattr(content, "outcomes", ())
            lineage["frames"] = [
                {
                    "frame_id": outcome.event_id,
                    "frame_identity": (
                        None
                        if outcome.frame_identity is None
                        else outcome.frame_identity.to_mapping()
                    ),
                    "image_digest": (
                        None
                        if outcome.frame_identity is None
                        else outcome.frame_identity.image_sha256
                    ),
                    "outcome": outcome.status,
                }
                for outcome in outcomes
            ]
        proposal_id = reference.draft.proposal_revision_id
        if proposal_id is not None:
            try:
                proposal = self.reference_service.revision_store.require(proposal_id)
            except PipelineNotFound as error:
                raise PipelineReferenceInputError("proposal revision was not found") from error
            data = proposal.content
            lineage.update(
                proposal_revision_digest=proposal.manifest.content_sha256,
                detector_revision_id=data.detector_revision_id,
                detector_revision_digest=data.detector_revision_digest,
                calibration_revision_id=data.calibration_revision_id,
                calibration_digest=data.calibration_digest,
                frames=[
                    {
                        "frame_id": frame.frame_id,
                        "frame_identity": (
                            None
                            if frame.source_identity is None
                            else frame.source_identity.to_mapping()
                        ),
                        "image_digest": frame.source_frame_digest,
                        "outcome": frame.status,
                    }
                    for frame in data.frames
                ],
            )
        return lineage


__all__ = ["VisibleCardReviewService"]
