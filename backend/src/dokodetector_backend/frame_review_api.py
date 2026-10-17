"""Paged API for the frozen 0096 M4 frame review queue."""

from __future__ import annotations

import json
from collections import Counter
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
    action: Literal["defer", "resume", "set_resume"]


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


def _project(
    request: Request,
    item: FrameReviewItem,
    deferred_keys: set[str],
    by_id: dict[str, Any],
    reference_cache: dict[str, Any],
) -> FrameReviewItemResponse:
    result = by_id.get(item.source_revision_id or "")
    unavailable_reason: str | None = None
    if not item.eligible:
        unavailable_reason = (
            "The frozen selection has no detector revision. Check the recording's M1 dependency."
        )
    elif result is None:
        unavailable_reason = (
            "The pinned detector result is missing or invalid. "
            "Restore that exact revision before review."
        )
    elif result.recording_id != item.recording_id or result.content_type != "visible_cards":
        unavailable_reason = (
            "The pinned detector revision belongs to a different recording or stage."
        )
    elif (
        item.source_revision_sha256 is not None
        and result.content_sha256 != item.source_revision_sha256
    ):
        unavailable_reason = (
            "The pinned detector result digest changed. Restore the frozen result before review."
        )

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
    """Return a deterministic page and whole-queue counts without decoding result content."""
    raw, items = _load_queue(request)
    digest = raw["selection_sha256"]
    workflow: FrameReviewWorkflowStore = request.app.state.frame_review_workflow_store
    progress = workflow.read(QUEUE_ID, digest)
    deferred_keys = set(progress["deferred_item_keys"])
    # Build one manifest index for the whole page request. It reads only revision manifests.
    revision_manifests = request.app.state.pipeline_revision_store.list_manifests()
    by_id = {value.revision_id: value for value in revision_manifests}
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
    progress = store.update(
        QUEUE_ID,
        digest,
        action=payload.action,
        item_key=_item_key(recording_id, item_id),
    )
    resume_recording_id = resume_item_id = None
    if progress["resume_item_key"] is not None:
        resume_recording_id, resume_item_id = json.loads(progress["resume_item_key"])
    return FrameReviewWorkflowResponse(
        queue_id=QUEUE_ID,
        queue_digest=digest,
        deferred=_item_key(recording_id, item_id) in set(progress["deferred_item_keys"]),
        resume_recording_id=resume_recording_id,
        resume_item_id=resume_item_id,
    )
