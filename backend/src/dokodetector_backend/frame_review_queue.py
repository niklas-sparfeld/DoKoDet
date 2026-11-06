"""Read-only contract and progress rules for frozen frame review queues."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

QUEUE_SCHEMA = "frame-review-queue/v1"
RECEIPT_SCHEMA = "frame-review-receipt/v2"


class QueueContractError(ValueError):
    """A frozen queue or review receipt is invalid."""


class ReviewState(StrEnum):
    PENDING = "pending"
    DEFERRED = "deferred"
    SAVED = "saved_review"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class FrameReviewItem:
    queue_id: str
    queue_digest: str
    recording_id: str
    stage: str
    item_id: str
    source_revision_id: str | None
    source_revision_sha256: str | None
    scene_run_id: str | None
    scene_revision_id: str | None
    comparison_reference_revision_id: str | None
    reasons: tuple[str, ...]
    eligible: bool
    comparison_eligible: bool

    @property
    def result_available(self) -> bool:
        # A detector result is enough for calibration diagnostics. Scene output is optional.
        return self.source_revision_id is not None


@dataclass(frozen=True, slots=True)
class FrameReviewReceipt:
    """An explicit queue save marker that points to one exact node review."""

    queue_id: str
    queue_digest: str
    recording_id: str
    stage: str
    item_id: str
    source_revision_id: str
    source_revision_sha256: str | None
    scene_run_id: str | None
    scene_revision_id: str | None
    node_id: str
    revision_id: str
    review_id: str
    saved_at: str


def _text(data: Mapping[str, Any], key: str, *, optional: bool = False) -> str | None:
    value = data.get(key)
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise QueueContractError(f"{key} must be a non-empty string")
    return value


def parse_frozen_queue(raw: Mapping[str, Any]) -> tuple[FrameReviewItem, ...]:
    """Validate the 0096 frozen manifest and project stable editor targets."""
    if raw.get("schema_version") != "0096-m4-human-review-queue/v1":
        raise QueueContractError("unsupported frozen queue schema")
    digest = _text(raw, "selection_sha256")
    unsigned = dict(raw)
    unsigned.pop("selection_sha256", None)
    actual_digest = hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != actual_digest:
        raise QueueContractError("frozen queue digest does not match its contents")

    items: list[FrameReviewItem] = []
    seen: set[tuple[str, str]] = set()
    recordings = raw.get("recordings")
    if not isinstance(recordings, list):
        raise QueueContractError("recordings must be a list")
    for recording in recordings:
        if not isinstance(recording, Mapping):
            raise QueueContractError("recording entries must be objects")
        recording_id = _text(recording, "recording_id")
        frames = recording.get("review_frames", [])
        if not isinstance(frames, list):
            raise QueueContractError("review_frames must be a list")
        for frame in frames:
            if not isinstance(frame, Mapping):
                raise QueueContractError("review frame entries must be objects")
            item_id = _text(frame, "item_id")
            frame_recording = _text(frame, "recording_id")
            key = (frame_recording, item_id)
            if key in seen:
                raise QueueContractError(f"duplicate item_id: {item_id}")
            seen.add(key)
            if frame_recording != recording_id:
                raise QueueContractError("frame recording_id does not match its queue group")
            reasons = frame.get("reasons")
            if (
                not isinstance(reasons, list)
                or not reasons
                or not all(isinstance(reason, str) and reason for reason in reasons)
            ):
                raise QueueContractError("reasons must contain non-empty strings")
            training_overlap = frame.get("m4_training_overlap")
            evaluation_eligible = frame.get("evaluation_eligibility")
            if not isinstance(training_overlap, bool) or not isinstance(evaluation_eligible, bool):
                raise QueueContractError("source eligibility flags must be boolean")
            revision_id = frame.get("m1_revision_id")
            if revision_id is not None and (not isinstance(revision_id, str) or not revision_id):
                raise QueueContractError("m1_revision_id must be a non-empty string or null")
            revision_digest = frame.get("m1_revision_sha256")
            if revision_digest is not None and (
                not isinstance(revision_digest, str) or len(revision_digest) != 64
            ):
                raise QueueContractError("m1_revision_sha256 must be a SHA-256 digest or null")
            items.append(
                FrameReviewItem(
                    queue_id="0096-M4",
                    queue_digest=digest,
                    recording_id=recording_id,
                    stage="visible_cards",
                    item_id=item_id,
                    source_revision_id=revision_id,
                    source_revision_sha256=revision_digest,
                    scene_run_id=frame.get("m2_run_id"),
                    scene_revision_id=frame.get("scene_revision_id"),
                    comparison_reference_revision_id=frame.get("reference_revision_id"),
                    reasons=tuple(reasons),
                    eligible=revision_id is not None,
                    comparison_eligible=(
                        evaluation_eligible
                        and not training_overlap
                        and frame.get("reference_revision_id") is not None
                    ),
                )
            )
    return tuple(items)


def parse_review_receipt(raw: Mapping[str, Any]) -> FrameReviewReceipt:
    """Parse the minimal workflow receipt; it stores no review geometry or decisions."""
    if raw.get("schema_version") != RECEIPT_SCHEMA:
        raise QueueContractError("unsupported review receipt schema")
    return FrameReviewReceipt(
        queue_id=_text(raw, "queue_id"),
        queue_digest=_text(raw, "queue_digest"),
        recording_id=_text(raw, "recording_id"),
        stage=_text(raw, "stage"),
        item_id=_text(raw, "item_id"),
        source_revision_id=_text(raw, "source_revision_id"),
        source_revision_sha256=_text(raw, "source_revision_sha256", optional=True),
        scene_run_id=_text(raw, "scene_run_id", optional=True),
        scene_revision_id=_text(raw, "scene_revision_id", optional=True),
        node_id=_text(raw, "node_id"),
        revision_id=_text(raw, "revision_id"),
        review_id=_text(raw, "review_id"),
        saved_at=_text(raw, "saved_at"),
    )


def review_state(
    item: FrameReviewItem,
    *,
    deferred: bool = False,
    receipt: FrameReviewReceipt | None = None,
    review_applicable: bool = False,
) -> ReviewState:
    """Return workflow state without changing canonical review data."""
    if not item.eligible or not item.result_available:
        return ReviewState.UNAVAILABLE
    if receipt is not None:
        matches = (
            receipt.queue_id == item.queue_id
            and receipt.queue_digest == item.queue_digest
            and receipt.recording_id == item.recording_id
            and receipt.stage == item.stage
            and receipt.item_id == item.item_id
            and receipt.source_revision_id == item.source_revision_id
            and receipt.source_revision_sha256 == item.source_revision_sha256
            and receipt.scene_run_id == item.scene_run_id
            and receipt.scene_revision_id == item.scene_revision_id
        )
        if matches and review_applicable:
            return ReviewState.SAVED
        return ReviewState.UNAVAILABLE
    return ReviewState.DEFERRED if deferred else ReviewState.PENDING
