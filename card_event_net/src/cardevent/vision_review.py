"""Parse table-observation review artifacts for the legacy dataset assembler."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .vision_annotation import (
    TableObservationAnnotation,
    VisionAnnotationError,
)


class VisionReviewError(RuntimeError):
    """Raised when a table-observation review cannot be validated."""


TABLE_OBSERVATION_REVIEW_SCHEMA_VERSION = "table-observation-review/v1"
VISION_REVIEW_DECISIONS = frozenset({"confirm_card_play", "reject_event"})


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisionReviewError(f"{field} must be a non-empty string.")
    return value


def _sha256_value(value: Any, field: str) -> str:
    result = _required_string(value, field)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise VisionReviewError(f"{field} must be a lower-case SHA-256 digest.")
    return result


def _utc_timestamp(value: Any, field: str) -> str:
    result = _required_string(value, field)
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VisionReviewError(f"{field} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise VisionReviewError(f"{field} must use UTC.")
    return result


def _strict_fields(data: dict[str, Any], expected: set[str], context: str) -> None:
    missing = expected - set(data)
    unknown = set(data) - expected
    if missing or unknown:
        parts: list[str] = []
        if missing:
            parts.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            parts.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise VisionReviewError(f"{context} has invalid fields ({'; '.join(parts)}).")


@dataclass(frozen=True, slots=True)
class TableObservationReview:
    """One immutable event decision and complete reviewed annotation snapshot."""

    review_id: str
    annotation_set_id: str
    source_annotation_sha256: str
    event_decision: str
    reviewer: str
    reviewed_at: str
    reviewed_annotation: TableObservationAnnotation
    notes: str | None = None

    def __post_init__(self) -> None:
        _required_string(self.review_id, "review_id")
        _required_string(self.annotation_set_id, "annotation_set_id")
        _sha256_value(self.source_annotation_sha256, "source_annotation_sha256")
        if self.event_decision not in VISION_REVIEW_DECISIONS:
            raise VisionReviewError(f"Unknown event_decision: {self.event_decision}.")
        _required_string(self.reviewer, "reviewer")
        _utc_timestamp(self.reviewed_at, "reviewed_at")
        if self.reviewed_annotation.annotation_set_id != self.annotation_set_id:
            raise VisionReviewError("reviewed annotation set ID does not match review.")
        if self.reviewed_annotation.review_state != "reviewed":
            raise VisionReviewError("reviewed_annotation must have review_state reviewed.")
        expected_event_review = {
            "confirm_card_play": "confirmed_card_play",
            "reject_event": "false_event_proposal",
        }[self.event_decision]
        if self.reviewed_annotation.event_review != expected_event_review:
            raise VisionReviewError("reviewed annotation event_review does not match review.")
        if self.notes is not None and not isinstance(self.notes, str):
            raise VisionReviewError("notes must be a string or null.")

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "TableObservationReview":
        if not isinstance(data, dict):
            raise VisionReviewError("table-observation review must be an object.")
        _strict_fields(
            data,
            {
                "schema_version",
                "review_id",
                "annotation_set_id",
                "source_annotation_sha256",
                "event_decision",
                "reviewer",
                "reviewed_at",
                "reviewed_annotation",
                "notes",
            },
            "table-observation review",
        )
        if data["schema_version"] != TABLE_OBSERVATION_REVIEW_SCHEMA_VERSION:
            raise VisionReviewError(
                f"schema_version must be {TABLE_OBSERVATION_REVIEW_SCHEMA_VERSION}."
            )
        try:
            annotation = TableObservationAnnotation.from_mapping(data["reviewed_annotation"])
        except VisionAnnotationError as exc:
            raise VisionReviewError(f"Invalid reviewed annotation: {exc}") from exc
        return cls(
            review_id=_required_string(data["review_id"], "review_id"),
            annotation_set_id=_required_string(data["annotation_set_id"], "annotation_set_id"),
            source_annotation_sha256=_sha256_value(
                data["source_annotation_sha256"], "source_annotation_sha256"
            ),
            event_decision=_required_string(data["event_decision"], "event_decision"),
            reviewer=_required_string(data["reviewer"], "reviewer"),
            reviewed_at=_utc_timestamp(data["reviewed_at"], "reviewed_at"),
            reviewed_annotation=annotation,
            notes=data["notes"],
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": TABLE_OBSERVATION_REVIEW_SCHEMA_VERSION,
            "review_id": self.review_id,
            "annotation_set_id": self.annotation_set_id,
            "source_annotation_sha256": self.source_annotation_sha256,
            "event_decision": self.event_decision,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "reviewed_annotation": self.reviewed_annotation.to_mapping(),
            "notes": self.notes,
        }


def load_table_observation_review(path: str | Path) -> TableObservationReview:
    review_path = Path(path)
    try:
        payload = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisionReviewError(
            f"Could not read table-observation review {review_path}: {exc}"
        ) from exc
    return TableObservationReview.from_mapping(payload)


__all__ = [
    "TABLE_OBSERVATION_REVIEW_SCHEMA_VERSION",
    "TableObservationReview",
    "VisionReviewError",
    "load_table_observation_review",
]
