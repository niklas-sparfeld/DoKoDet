"""Paged API for the frozen 0096 M4 frame review queue."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field

from dokodetector_backend.contract import ContractModel
from dokodetector_backend.frame_review_bindings import load_frame_review_bindings
from dokodetector_backend.frame_review_queue import (
    FrameReviewItem,
    QueueContractError,
    ReviewState,
    parse_frozen_queue,
    parse_review_receipt,
    review_state,
)
from dokodetector_backend.frame_review_workflow_store import FrameReviewWorkflowStore

router = APIRouter()
QUEUE_ID = "0096-M4"
MANIFEST_RELATIVE_PATH = Path("docs/reports/0096-M4_Human_Review_Queue.json")


class FrameReviewTarget(ContractModel):
    path: str
    revision_id: str
    item_id: str
    scene_run_id: str | None
    scene_revision_id: str | None


class FrameReviewItemResponse(ContractModel):
    recording_id: str
    item_id: str
    state: Literal["pending", "deferred", "saved_review", "unavailable"]
    reasons: list[str]
    eligible: bool
    comparison_eligible: bool
    unavailable_reason: str | None
    editor_target: FrameReviewTarget | None


class FrameReviewCounts(ContractModel):
    total: int = Field(ge=0)
    by_state: dict[str, int]
    by_reason: dict[str, int]


class FrameReviewPageResponse(ContractModel):
    schema_version: Literal["frame-review-page/v1"]
    queue_id: str
    queue_digest: str
    items: list[FrameReviewItemResponse]
    counts: FrameReviewCounts
    next_cursor: int | None
    resume_recording_id: str | None
    resume_item_id: str | None


class FrameReviewWorkflowRequest(ContractModel):
    queue_digest: str = Field(min_length=64, max_length=64)
    action: Literal["defer", "resume", "set_resume", "save_review"]
    node_id: str | None = None
    revision_id: str | None = None
    review_id: str | None = None


class FrameReviewWorkflowResponse(ContractModel):
    queue_id: str
    queue_digest: str
    deferred: bool
    resume_recording_id: str | None
    resume_item_id: str | None


def _item_key(recording_id: str, item_id: str) -> str:
    return json.dumps([recording_id, item_id], ensure_ascii=False, separators=(",", ":"))


def _load_queue(request: Request) -> tuple[dict[str, Any], tuple[FrameReviewItem, ...]]:
    path = request.app.state.settings.repository_root / MANIFEST_RELATIVE_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw, parse_frozen_queue(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, QueueContractError) as error:
        raise HTTPException(
            status_code=503,
            detail="The frozen frame review queue is unavailable.",
        ) from error


def _queue_bindings(request: Request, digest: str) -> dict[tuple[str, str], dict[str, str] | None]:
    try:
        return load_frame_review_bindings(
            request.app.state.pipeline_node_reviews.store.root, digest
        )
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, ValueError) as error:
        raise HTTPException(
            status_code=503, detail="The frame review node bindings are invalid."
        ) from error


def _source_node(
    request: Request, item: FrameReviewItem, bindings: dict, cache: dict
) -> tuple[dict[str, str] | None, str | None]:
    if not item.eligible:
        return (
            None,
            "The frozen selection has no detector revision. Check the recording's M1 dependency.",
        )
    target = bindings.get((item.recording_id, item.item_id))
    if target is None:
        return (
            None,
            "The pinned detector result is missing or invalid. "
            "Restore that exact revision before review.",
        )
    pair = (target["node_id"], target["revision_id"])
    try:
        if pair not in cache:
            store = request.app.state.pipeline_node_reviews.store
            cache[pair] = (store.get(pair[0]), store.read_revision(pair[0], pair[1]))
        node, revision = cache[pair]
        if (
            node.content_type != "visible_cards"
            or node.source.get("recording_id") != item.recording_id
            or revision.metadata.get("legacy_revision_id") != item.source_revision_id
        ):
            return None, "The pinned detector revision belongs to a different recording or stage."
        if (
            item.source_revision_sha256 is not None
            and revision.metadata.get("legacy_content_sha256") != item.source_revision_sha256
        ):
            return (
                None,
                "The pinned detector result digest changed. "
                "Restore the frozen result before review.",
            )
        if not any(
            outcome.get("event_id") == item.item_id
            for outcome in revision.content.get("outcomes", [])
        ):
            return None, "The pinned detector result does not contain this frame."
    except (OSError, KeyError, TypeError, ValueError):
        return (
            None,
            "The pinned detector result is missing or invalid. "
            "Restore that exact revision before review.",
        )
    return target, None


def _editor_target(
    item: FrameReviewItem, target: dict[str, str] | None
) -> FrameReviewTarget | None:
    if target is None:
        return None
    selection = {
        "schema_version": "pipeline-lineage-selection/v1",
        "selected": {"visible_cards": target},
    }
    query = urlencode(
        {"lineage": json.dumps(selection, separators=(",", ":")), "item": item.item_id}
    )
    return FrameReviewTarget(
        path=f"/recordings/{quote(item.recording_id, safe='')}/pipeline/visible_cards?{query}",
        revision_id=item.source_revision_id,
        item_id=item.item_id,
        scene_run_id=item.scene_run_id,
        scene_revision_id=item.scene_revision_id,
    )


def _review_is_applicable(
    request: Request, item: FrameReviewItem, receipt: Any, source: dict[str, str] | None
) -> bool:
    """Check the saved review, its exact source lineage, and the current node head."""
    if source is None:
        return False
    reviews = request.app.state.pipeline_node_reviews
    store = reviews.store
    try:
        review = reviews.get(receipt.review_id)
        node = store.get(receipt.node_id)
        if (
            node.content_type != "visible_cards"
            or node.source.get("recording_id") != item.recording_id
            or review.get("kind") != "item"
            or review.get("node_id") != receipt.node_id
            or review.get("revision_id") != receipt.revision_id
            or review.get("item_id") != item.item_id
            or review.get("decision") not in {"accepted", "rejected"}
        ):
            return False
        current = store.read_revision(receipt.node_id, receipt.revision_id)
        seen = set()
        while (current.node_id, current.revision_id) not in seen:
            pair = (current.node_id, current.revision_id)
            if pair == (source["node_id"], source["revision_id"]):
                return (
                    reviews.applicability(
                        receipt.review_id,
                        receipt.node_id,
                        node.head_revision_id,
                        review["evidence"],
                    )["status"]
                    == "applicable"
                )
            seen.add(pair)
            if current.parent_revision_id is not None:
                current = store.read_revision(current.node_id, current.parent_revision_id)
                continue
            copied = current.metadata.get("copied_from")
            if not isinstance(copied, dict):
                return False
            current = store.read_revision(copied["node_id"], copied["revision_id"])
    except (OSError, KeyError, TypeError, ValueError):
        return False
    return False


def _project(
    request: Request,
    item: FrameReviewItem,
    deferred_keys: set[str],
    bindings: dict,
    cache: dict,
) -> FrameReviewItemResponse:
    source, unavailable_reason = _source_node(request, item, bindings, cache)
    editor_target = _editor_target(item, source)

    item_key = _item_key(item.recording_id, item.item_id)
    receipt_raw = request.app.state.frame_review_workflow_store.read_receipt(QUEUE_ID, item_key)
    receipt = None
    if receipt_raw is not None:
        try:
            receipt = parse_review_receipt(receipt_raw)
        except QueueContractError:
            unavailable_reason = (
                "The saved-review receipt is invalid. Re-save this exact frame after "
                "checking its lineage."
            )
    if unavailable_reason:
        state = ReviewState.UNAVAILABLE
    else:
        state = review_state(
            item,
            deferred=item_key in deferred_keys,
            receipt=receipt,
            review_applicable=receipt is not None
            and _review_is_applicable(request, item, receipt, source),
        )
        if state is ReviewState.UNAVAILABLE:
            unavailable_reason = (
                "The saved review no longer applies to the current result. "
                "Inspect its lineage before continuing."
            )
    return FrameReviewItemResponse(
        recording_id=item.recording_id,
        item_id=item.item_id,
        state=state.value,
        reasons=list(item.reasons),
        eligible=item.eligible,
        comparison_eligible=item.comparison_eligible,
        unavailable_reason=unavailable_reason,
        editor_target=editor_target,
    )


@router.get("/api/frame-reviews/0096-M4", response_model=FrameReviewPageResponse)
def get_frame_review_queue(
    request: Request,
    limit: int = Query(default=40, ge=1, le=100),
    cursor: int = Query(default=0, ge=0),
    state: Literal["pending", "deferred", "saved_review", "unavailable"] | None = None,
) -> FrameReviewPageResponse:
    """Return deterministic counts after validating the pinned revision content."""
    raw, items = _load_queue(request)
    digest = raw["selection_sha256"]
    workflow: FrameReviewWorkflowStore = request.app.state.frame_review_workflow_store
    progress = workflow.read(QUEUE_ID, digest)
    deferred_keys = set(progress["deferred_item_keys"])
    bindings = _queue_bindings(request, digest)
    cache: dict = {}
    projected = [_project(request, item, deferred_keys, bindings, cache) for item in items]
    counts_by_state = Counter(item.state for item in projected)
    counts_by_reason = Counter(reason for item in projected for reason in item.reasons)
    filtered = [item for item in projected if state is None or item.state == state]
    page = filtered[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < len(filtered) else None
    resume_key = progress["resume_item_key"]
    resume_recording_id = resume_item_id = None
    if resume_key is not None:
        try:
            resume_recording_id, resume_item_id = json.loads(resume_key)
        except (TypeError, ValueError):
            resume_recording_id = resume_item_id = None
    return FrameReviewPageResponse(
        schema_version="frame-review-page/v1",
        queue_id=QUEUE_ID,
        queue_digest=digest,
        items=page,
        counts=FrameReviewCounts(
            total=len(projected),
            by_state={value.value: counts_by_state[value.value] for value in ReviewState},
            by_reason=dict(sorted(counts_by_reason.items())),
        ),
        next_cursor=next_cursor,
        resume_recording_id=resume_recording_id,
        resume_item_id=resume_item_id,
    )


@router.put(
    "/api/frame-reviews/0096-M4/items/{recording_id}/{item_id}/workflow",
    response_model=FrameReviewWorkflowResponse,
)
def update_frame_review_workflow(
    recording_id: str,
    item_id: str,
    payload: FrameReviewWorkflowRequest,
    request: Request,
) -> FrameReviewWorkflowResponse:
    """Change queue deferral or resume position without touching a maintained reference."""
    raw, items = _load_queue(request)
    digest = raw["selection_sha256"]
    if payload.queue_digest != digest:
        raise HTTPException(
            status_code=409,
            detail="The frozen review queue changed. Reload it before updating progress.",
        )
    if not any(item.recording_id == recording_id and item.item_id == item_id for item in items):
        raise HTTPException(status_code=404, detail="The frame is not in this frozen review queue.")
    store: FrameReviewWorkflowStore = request.app.state.frame_review_workflow_store
    item_key = _item_key(recording_id, item_id)
    if payload.action == "save_review":
        queue_item = next(
            item for item in items if item.recording_id == recording_id and item.item_id == item_id
        )
        if not all(
            (payload.node_id, payload.revision_id, payload.review_id, queue_item.source_revision_id)
        ):
            raise HTTPException(
                status_code=422,
                detail="A saved review needs an exact node, revision, and review ID.",
            )
        bindings = _queue_bindings(request, digest)
        source, problem = _source_node(request, queue_item, bindings, {})
        if problem is not None:
            raise HTTPException(status_code=409, detail=problem)
        raw_receipt = {
            "schema_version": "frame-review-receipt/v2",
            "queue_id": QUEUE_ID,
            "queue_digest": digest,
            "recording_id": recording_id,
            "stage": queue_item.stage,
            "item_id": item_id,
            "source_revision_id": queue_item.source_revision_id,
            "source_revision_sha256": queue_item.source_revision_sha256,
            "scene_run_id": queue_item.scene_run_id,
            "scene_revision_id": queue_item.scene_revision_id,
            "node_id": payload.node_id,
            "revision_id": payload.revision_id,
            "review_id": payload.review_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        receipt = parse_review_receipt(raw_receipt)
        if not _review_is_applicable(request, queue_item, receipt, source):
            raise HTTPException(
                status_code=409,
                detail="The saved review does not apply to this exact queue result.",
            )
        store.write_receipt(QUEUE_ID, item_key, raw_receipt)
        progress = store.read(QUEUE_ID, digest)
    else:
        progress = store.update(
            QUEUE_ID,
            digest,
            action=payload.action,
            item_key=item_key,
        )
    resume_recording_id = resume_item_id = None
    if progress["resume_item_key"] is not None:
        resume_recording_id, resume_item_id = json.loads(progress["resume_item_key"])
    return FrameReviewWorkflowResponse(
        queue_id=QUEUE_ID,
        queue_digest=digest,
        deferred=item_key in set(progress["deferred_item_keys"]),
        resume_recording_id=resume_recording_id,
        resume_item_id=resume_item_id,
    )
