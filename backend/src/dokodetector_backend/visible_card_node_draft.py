"""Node-owned working state for visible-card scene reflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class VisibleCardNodeDraftItem:
    """One editable visible-card node item with its current review status."""

    item_id: str
    base_item_id: str | None
    review_state: str
    item: dict[str, Any]

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> VisibleCardNodeDraftItem:
        if set(raw) != {"item_id", "base_item_id", "review_state", "item"}:
            raise ValueError("visible-card node draft item has invalid fields")
        item_id = raw["item_id"]
        base_item_id = raw["base_item_id"]
        review_state = raw["review_state"]
        item = raw["item"]
        if (
            not isinstance(item_id, str)
            or not item_id
            or (
                base_item_id is not None and (not isinstance(base_item_id, str) or not base_item_id)
            )
            or not isinstance(review_state, str)
            or not isinstance(item, dict)
        ):
            raise ValueError("visible-card node draft item is invalid")
        return cls(item_id, base_item_id, review_state, item)


@dataclass(frozen=True, slots=True)
class VisibleCardNodeDraft:
    """The node content and review facts needed for calibration reflow."""

    revision: int
    source_revision_id: str
    proposal_revision_id: str
    items: tuple[VisibleCardNodeDraftItem, ...]
    coverage: dict[str, Any] | None
    impact: tuple[dict[str, Any], ...]
    updated_at: str

    content_type = "visible_cards"

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": "visible-card-node-draft/v1",
            "content_type": self.content_type,
            "revision": self.revision,
            "source_revision_id": self.source_revision_id,
            "proposal_revision_id": self.proposal_revision_id,
            "items": [
                {
                    "item_id": item.item_id,
                    "base_item_id": item.base_item_id,
                    "review_state": item.review_state,
                    "item": item.item,
                }
                for item in self.items
            ],
            "coverage": self.coverage,
            "impact": list(self.impact),
            "updated_at": self.updated_at,
        }


def build_calibration_reflow_context(draft: VisibleCardNodeDraft) -> dict[str, Any]:
    """Keep non-decision lineage needed to reflow a visible-card node."""
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
            {
                "item_id": item.item_id,
                "base_item_id": item.base_item_id,
                "review_state": item.review_state,
                "item": item.item,
            }
            for item in draft.items
            if item.review_state == "rejected"
        ],
        "affected_item_ids": [
            item.item_id for item in draft.items if item.review_state == "affected"
        ],
    }


__all__ = [
    "VisibleCardNodeDraft",
    "VisibleCardNodeDraftItem",
    "build_calibration_reflow_context",
]
