"""Persist non-decision calibration lineage needed to reflow visible-card nodes."""

from __future__ import annotations

from doko_operations.pipeline_reference import PipelineReferenceDraft


def build_calibration_reflow_context(draft: PipelineReferenceDraft) -> dict[str, object]:
    """Keep source links, rejected items, and derived re-review status outside review records."""
    if draft.content_type != "visible_cards":
        raise ValueError("calibration reflow context requires visible-card content")
    return {
        "schema_version": "calibration-reflow-context/v1",
        "source_revision_id": draft.source_revision_id,
        "proposal_revision_id": draft.proposal_revision_id,
        "draft_revision": draft.revision,
        "updated_at": draft.updated_at,
        "impact": [dict(item) for item in draft.impact],
        "base_item_ids": {
            item.item_id: item.base_item_id for item in draft.items if item.base_item_id is not None
        },
        "excluded_items": [
            item.to_mapping() for item in draft.items if item.review_state == "rejected"
        ],
        "affected_item_ids": [
            item.item_id for item in draft.items if item.review_state == "affected"
        ],
    }


__all__ = ["build_calibration_reflow_context"]
