"""Build reviewed visible-card drafts from exact detector and proposal revisions."""

from __future__ import annotations

from collections.abc import Mapping

from doko_operations.card_plane_geometry import virtual_card_long_size
from doko_operations.pipeline_reference import ReferenceDraftItem
from table_evidence_analyzer.card_scene_contract import (
    CardReviewState,
    CardSceneDraft,
    FrameReviewCompletion,
)
from table_evidence_analyzer.pipeline_data import ProposedCardSceneData, VisibleCardData

from dokodetector_backend.pipeline_reference_errors import PipelineReferenceInputError
from dokodetector_backend.pipeline_reference_handlers import build_reference_handlers
from dokodetector_backend.pipeline_store import StoredPipelineRevision


def seed_proposal_items(
    recording_id: str,
    source_revision: StoredPipelineRevision,
    proposal_data: ProposedCardSceneData,
    proposal_revision_id: str,
    previous_items: tuple[ReferenceDraftItem, ...] = (),
) -> tuple[ReferenceDraftItem, ...]:
    """Seed a draft while preserving reviewed pile and ignore regions by exact frame."""
    if not isinstance(source_revision.content, VisibleCardData):
        raise PipelineReferenceInputError("the proposal source must be visible-card data")
    outcomes = source_revision.content.outcomes
    frames = {frame.frame_id: frame for frame in proposal_data.frames}
    if set(frames) != {outcome.event_id for outcome in outcomes}:
        raise PipelineReferenceInputError(
            "proposal frames do not match the detector source coverage"
        )
    projection = proposal_projection(proposal_data)
    previous_by_item_id = {item.item_id: item for item in previous_items}
    items: list[ReferenceDraftItem] = []
    for outcome in outcomes:
        frame = frames[outcome.event_id]
        item = outcome.to_mapping()
        previous = previous_by_item_id.get(outcome.event_id)
        if previous is not None:
            previous_regions = previous.item.get("ignored_regions", [])
            if previous_regions:
                if previous.item.get("frame_identity") != item.get("frame_identity"):
                    raise PipelineReferenceInputError(
                        "cannot rebase reviewed ignore regions for a changed source frame: "
                        f"{outcome.event_id}"
                    )
                item["ignored_regions"] = list(previous_regions)
            previous_piles = previous.item.get("pile_regions", [])
            if previous_piles:
                if previous.item.get("frame_identity") != item.get("frame_identity"):
                    raise PipelineReferenceInputError(
                        "cannot rebase reviewed pile regions for a changed source frame: "
                        f"{outcome.event_id}"
                    )
                item["pile_regions"] = list(previous_piles)
        if frame.status == "supported":
            if frame.proposal is None or outcome.frame_identity is None:
                raise PipelineReferenceInputError(
                    f"supported proposal has incomplete frame lineage: {outcome.event_id}"
                )
            if frame.source_frame_digest != outcome.frame_identity.image_sha256:
                raise PipelineReferenceInputError(
                    f"proposal source frame digest does not match: {outcome.event_id}"
                )
            if outcome.status != "detected":
                raise PipelineReferenceInputError(
                    f"supported proposal requires a detected source frame: {outcome.event_id}"
                )
            draft = CardSceneDraft.create(
                proposal=frame.proposal,
                reviewed=None,
                card_states=tuple(
                    CardReviewState.create(
                        card_id=card_id,
                        source="proposal",
                        proposal_id=frame.proposal.proposal_id,
                        state="pending",
                    )
                    for card_id in frame.proposal.card_ids
                ),
                completion=FrameReviewCompletion.create(
                    state="pending",
                    unresolved_card_ids=frame.proposal.card_ids,
                ),
                proposal_revision_id=proposal_revision_id,
                proposal_data_digest=proposal_data.data_digest,
                projection=projection,
            )
            item["candidates"] = []
            item["card_scene"] = draft.to_mapping()
            review_state = "pending"
            if previous is not None:
                grouped_ids = {
                    candidate.get("card_id")
                    for pile in previous.item.get("pile_regions", [])
                    if isinstance(pile, Mapping)
                    for candidate in pile.get("grouped_candidates", [])
                    if isinstance(candidate, Mapping)
                }
                duplicated = grouped_ids.intersection(frame.proposal.card_ids)
                if duplicated:
                    raise PipelineReferenceInputError(
                        "proposal refresh found cards already grouped into reviewed piles; "
                        "review pile membership before refreshing this frame"
                    )
        else:
            reason = frame.unsupported_reason or "proposal frame is unsupported"
            has_reviewed_piles = bool(item.get("pile_regions"))
            item["status"] = "detected" if has_reviewed_piles else "failed"
            item["candidates"] = []
            item["ignored_regions"] = []
            item["error"] = None if has_reviewed_piles else reason
            if frame.proposal is not None:
                draft = CardSceneDraft.create(
                    proposal=frame.proposal,
                    reviewed=None,
                    card_states=(),
                    completion=FrameReviewCompletion.create(
                        state="unusable",
                        unresolved_card_ids=(),
                        reason=reason,
                    ),
                    proposal_revision_id=proposal_revision_id,
                    proposal_data_digest=proposal_data.data_digest,
                    projection=projection,
                )
                item["card_scene"] = draft.to_mapping()
            review_state = "accepted" if has_reviewed_piles else "unusable"
        items.append(
            ReferenceDraftItem(
                item_id=outcome.event_id,
                base_item_id=None,
                review_state=review_state,
                item=item,
            )
        )
    handlers = build_reference_handlers(
        source_for=lambda *_: None,
        selected_revision=lambda *_: None,
    )
    handlers["visible_cards"].validate_draft_items(
        recording_id, source_revision.manifest.revision_id, items
    )
    return tuple(items)


def proposal_projection(proposal_data: ProposedCardSceneData) -> dict[str, object]:
    """Return the geometry projection required by scene review contracts."""
    calibration = proposal_data.calibration
    try:
        short_size = calibration["card_short_size"]
        return {
            "table_to_image_homography": calibration["table_to_image"],
            "card_short_size": short_size,
            "card_long_size": virtual_card_long_size(short_size),
        }
    except KeyError as error:
        raise PipelineReferenceInputError("proposal calibration has no card projection") from error


__all__ = ["proposal_projection", "seed_proposal_items"]
