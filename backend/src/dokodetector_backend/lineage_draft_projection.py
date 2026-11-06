"""Project retained draft content without treating pending items as reviewed."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from doko_operations.pipeline_reference import PipelineReferenceDraft

from table_evidence_analyzer.pipeline_data import VisibleCardData


def project_visible_card_items(
    items: tuple[Any, ...],
    *,
    coverage: dict[str, Any] | None,
    impact: tuple[dict[str, Any], ...],
    proposal_revision_id: str | None,
) -> dict[str, Any]:
    """Project node-owned visible-card items without legacy reference handlers."""
    if proposal_revision_id is None and any(
        item.item.get("card_scene") is not None for item in items
    ):
        raise ValueError("retained scenes have no exact proposal revision")
    retained = [item for item in items if item.review_state != "rejected"]
    content_items = []
    content_retained = []
    scene_only_items = []
    for item in retained:
        value = dict(item.item)
        scene = value.pop("card_scene", None)
        if (
            scene is not None
            and value.get("status") == "detected"
            and not value.get("candidates")
            and not value.get("ignored_regions")
            and not value.get("pile_regions")
        ):
            scene_only_items.append(item.item_id)
            continue
        content_items.append(value)
        content_retained.append(item)
    content = VisibleCardData.from_mapping(
        {"schema_version": "visible-card-data/v2", "outcomes": content_items}
    ).to_mapping()
    return {
        "content": content,
        "pointers": {
            item.item_id: f"/outcomes/{index}" for index, item in enumerate(content_retained)
        },
        "scene_only_items": scene_only_items,
        "coverage": coverage,
        "impact": list(impact),
    }


def _project_items(
    content_type: str,
    items: tuple[Any, ...],
    *,
    coverage: dict[str, Any] | None,
    impact: tuple[dict[str, Any], ...],
    proposal_revision_id: str | None,
) -> dict[str, Any]:
    from dokodetector_backend.pipeline_reference_handlers import build_reference_handlers

    handlers = build_reference_handlers(
        source_for=lambda *_: None, selected_revision=lambda *_: None
    )
    handler = handlers[content_type]
    ordered = handler.order_items(items)
    if (
        content_type == "visible_cards"
        and proposal_revision_id is None
        and any(item.item.get("card_scene") is not None for item in ordered)
    ):
        raise ValueError("retained scenes have no exact proposal revision")
    retained = [item for item in ordered if item.review_state != "rejected"]
    content_items = []
    content_retained = []
    scene_only_items = []
    for item in retained:
        value = dict(item.item)
        if content_type == "visible_cards":
            scene = value.pop("card_scene", None)
            if (
                scene is not None
                and value.get("status") == "detected"
                and not value.get("candidates")
                and not value.get("ignored_regions")
                and not value.get("pile_regions")
            ):
                scene_only_items.append(item.item_id)
                continue
        content_items.append(value)
        content_retained.append(item)
    content = {
        "schema_version": handler.content_schema,
        handler.content_key: content_items,
    }
    # Validate the projected content without changing classifier or provenance fields.
    content = json.loads(handler.canonical_content_bytes(content))
    return {
        "content": content,
        "pointers": {
            item.item_id: f"/{handler.content_key}/{index}"
            for index, item in enumerate(content_retained)
        },
        "scene_only_items": scene_only_items,
        "coverage": coverage,
        "impact": list(impact),
    }


def project_draft(draft: PipelineReferenceDraft) -> dict[str, Any]:
    """Project one migration draft into node content."""
    return _project_items(
        draft.content_type,
        draft.items,
        coverage=draft.coverage,
        impact=draft.impact,
        proposal_revision_id=draft.proposal_revision_id,
    )


def project_scene_frame(frame: dict[str, Any]) -> dict[str, Any]:
    """Keep exact scene geometry and the original review facts for one frame."""
    from table_evidence_analyzer.card_scene_contract import CardSceneDraft

    from dokodetector_backend.virtual_scene_data import from_draft, validate_virtual_scenes

    raw = frame["card_scene"]
    if raw.get("schema_version") == "card-scene-draft/v1":
        draft = CardSceneDraft.from_mapping(raw, "card_scene")
        if draft.proposal.status == "supported":
            try:
                return from_draft(
                    draft,
                    frame["frame_identity"],
                    pile_regions=frame.get("pile_regions", []),
                    ignore_regions=frame.get("ignored_regions", []),
                )
            except ValueError as error:
                if (
                    str(error) != "partial proposal requires an explicit complete scene"
                    or draft.completion.state != "unusable"
                ):
                    raise
        calibration_id = draft.proposal.calibration_revision_id
        calibration_digest = draft.proposal.calibration_digest
        geometry = None
        frame_id = draft.proposal.source_frame_id
        if frame["frame_identity"]["image_sha256"] != draft.proposal.source_frame_digest:
            raise ValueError("draft frame identity does not match proposal")
    elif raw.get("schema_version") == "reviewed-card-scene-editor/v1":
        geometry = raw.get("scene")
        calibration_source = geometry or raw.get("initialized_scene")
        if calibration_source is None:
            raise ValueError("legacy scene has no recorded calibration")
        calibration_id = calibration_source["calibration_revision_id"]
        calibration_digest = calibration_source["calibration_digest"]
        frame_id = calibration_source["source_frame_id"]
    else:
        raise ValueError("unsupported retained scene format")
    content = validate_virtual_scenes(
        {
            "schema_version": "virtual-scene-data/v1",
            "frames": [
                {
                    "frame_id": frame_id,
                    "frame_identity": frame["frame_identity"],
                    "calibration": {"revision_id": calibration_id, "digest": calibration_digest},
                    "scene": geometry,
                    "pile_regions": frame.get("pile_regions", []),
                    "ignore_regions": frame.get("ignored_regions", []),
                }
            ],
        }
    )
    return {
        "content": content,
        "geometry_unavailable": (
            geometry is None and raw.get("schema_version") == "card-scene-draft/v1"
        ),
    }
