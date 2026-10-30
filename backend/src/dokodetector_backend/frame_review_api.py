"""Paged API for the frozen 0096 M4 frame review queue."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field

from dokodetector_backend.contract import ContractModel
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
    draft_revision: int | None = Field(default=None, ge=1)


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


def _editor_target(item: FrameReviewItem) -> FrameReviewTarget | None:
    if item.source_revision_id is None:
        return None
    return FrameReviewTarget(
        path=(
            f"/recordings/{quote(item.recording_id, safe='')}/pipeline/visible_cards"
            f"?view=generated&revision={quote(item.source_revision_id, safe='')}"
            f"&item={quote(item.item_id, safe='')}"
        ),
        revision_id=item.source_revision_id,
        item_id=item.item_id,
        scene_run_id=item.scene_run_id,
        scene_revision_id=item.scene_revision_id,
    )


def _revision_problem(item: FrameReviewItem, result: Any) -> str | None:
    if not item.eligible:
        return "The frozen selection has no detector revision. Check the recording's M1 dependency."
    if result is None:
        return (
            "The pinned detector result is missing or invalid. "
            "Restore that exact revision before review."
        )
    if (
        result.manifest.recording_id != item.recording_id
        or result.manifest.content_type != "visible_cards"
    ):
        return "The pinned detector revision belongs to a different recording or stage."
    if (
        item.source_revision_sha256 is not None
        and result.manifest.content_sha256 != item.source_revision_sha256
    ):
        return "The pinned detector result digest changed. Restore the frozen result before review."
    if not any(outcome.event_id == item.item_id for outcome in result.content.outcomes):
        return "The pinned detector result does not contain this frame."
    return None


def _project(
    request: Request,
    item: FrameReviewItem,
    deferred_keys: set[str],
    by_id: dict[str, Any],
    reference_cache: dict[str, Any],
) -> FrameReviewItemResponse:
    result = by_id.get(item.source_revision_id or "")
    unavailable_reason = _revision_problem(item, result)

    item_key = _item_key(item.recording_id, item.item_id)
    receipt_raw = request.app.state.frame_review_workflow_store.read_receipt(QUEUE_ID, item_key)
    receipt = None
    if receipt_raw is not None:
        try:
            receipt = parse_review_receipt(receipt_raw)
        except QueueContractError:
            unavailable_reason = (
                "The saved-review receipt is invalid. Keep the maintained draft and "
                "re-save this exact frame after checking its lineage."
            )
    if receipt is not None and item.recording_id not in reference_cache:
        reference_cache[item.recording_id] = request.app.state.pipeline_reference_store.get(
            item.recording_id, "visible_cards"
        )
    reference = reference_cache.get(item.recording_id)
    current_decisions = (
        {decision.item_id for decision in reference.draft.items} if reference is not None else None
    )
    if unavailable_reason:
        state = ReviewState.UNAVAILABLE
    else:
        state = review_state(
            item,
            deferred=item_key in deferred_keys,
            receipt=receipt,
            current_draft_revision=(reference.draft.revision if reference is not None else None),
            current_decision_item_ids=current_decisions,
        )
        if state is ReviewState.UNAVAILABLE:
            unavailable_reason = (
                "The saved-review receipt no longer matches the current result or "
                "maintained draft. Inspect the draft before continuing."
            )
    return FrameReviewItemResponse(
        recording_id=item.recording_id,
        item_id=item.item_id,
        state=state.value,
        reasons=list(item.reasons),
        eligible=item.eligible,
        comparison_eligible=item.comparison_eligible,
        unavailable_reason=unavailable_reason,
        editor_target=_editor_target(item),
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
    store = request.app.state.pipeline_revision_store
    by_id = {}
    revision_cache = {}
    for revision_id in {item.source_revision_id for item in items if item.source_revision_id}:
        revision = store.get(revision_id, revision_cache=revision_cache)
        if revision is not None:
            by_id[revision_id] = revision
    reference_cache: dict[str, Any] = {}
    projected = [_project(request, item, deferred_keys, by_id, reference_cache) for item in items]
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
        if payload.draft_revision is None or queue_item.source_revision_id is None:
            raise HTTPException(
                status_code=422, detail="A saved review needs an exact draft revision."
            )
        revision = request.app.state.pipeline_revision_store.get(queue_item.source_revision_id)
        problem = _revision_problem(queue_item, revision)
        if problem is not None:
            raise HTTPException(status_code=409, detail=problem)
        reference = request.app.state.pipeline_reference_store.get(recording_id, "visible_cards")
        decided = next(
            (draft_item for draft_item in reference.draft.items if draft_item.item_id == item_id),
            None,
        )
        if (
            reference.draft.revision != payload.draft_revision
            or reference.draft.source_revision_id != queue_item.source_revision_id
            or decided is None
            or decided.review_state
            not in {"accepted", "corrected", "rejected", "empty", "unusable"}
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "The maintained draft does not contain a saved decision for "
                    "this exact queue result."
                ),
            )
        store.write_receipt(
            QUEUE_ID,
            item_key,
            {
                "schema_version": "frame-review-receipt/v1",
                "queue_id": QUEUE_ID,
                "queue_digest": digest,
                "recording_id": recording_id,
                "stage": queue_item.stage,
                "item_id": item_id,
                "source_revision_id": queue_item.source_revision_id,
                "source_revision_sha256": queue_item.source_revision_sha256,
                "scene_run_id": queue_item.scene_run_id,
                "scene_revision_id": queue_item.scene_revision_id,
                "draft_revision": reference.draft.revision,
                "decision_item_ids": [item_id],
                "saved_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        # Keep earlier saved decisions current as other frames in the same draft are saved.
        current_decisions = {draft_item.item_id for draft_item in reference.draft.items}
        for previous in items:
            if previous.recording_id != recording_id or previous.item_id == item_id:
                continue
            previous_key = _item_key(recording_id, previous.item_id)
            prior = store.read_receipt(QUEUE_ID, previous_key)
            if prior is None or prior.get("source_revision_id") != previous.source_revision_id:
                continue
            decisions = prior.get("decision_item_ids")
            if not isinstance(decisions, list) or not set(decisions) <= current_decisions:
                continue
            prior["draft_revision"] = reference.draft.revision
            store.write_receipt(QUEUE_ID, previous_key, prior)
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
