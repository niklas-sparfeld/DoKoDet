"""Immutable review and apply artifacts for table-observation annotations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from .lifecycle import build_annotation_application_receipt
from .vision_annotation import (
    TABLE_OBSERVATION_SCHEMA_VERSION,
    TableObservationAnnotation,
    VisionAnnotationError,
    load_vision_annotation,
)


class VisionReviewError(RuntimeError):
    """Raised when a table-observation review cannot be safely applied."""


TABLE_OBSERVATION_REVIEW_SCHEMA_VERSION = "table-observation-review/v1"
TABLE_OBSERVATION_APPLY_SCHEMA_VERSION = "table-observation-apply/v1"
VISION_REVIEW_SCHEMA_VERSION = TABLE_OBSERVATION_REVIEW_SCHEMA_VERSION
VISION_APPLY_SCHEMA_VERSION = TABLE_OBSERVATION_APPLY_SCHEMA_VERSION
VISION_REVIEW_DECISIONS = frozenset({"confirm_card_play", "reject_event"})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256(path.read_bytes())
    except OSError as exc:
        raise VisionReviewError(f"Could not read {path}: {exc}") from exc


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


TableObservationReviewArtifact = TableObservationReview


def build_table_observation_review(
    annotation: TableObservationAnnotation,
    *,
    reviewer: str,
    event_decision: str,
    observed_cards: Sequence[Any] | None = None,
    notes: str | None = None,
    review_id: str | None = None,
    reviewed_at: str | None = None,
    source_annotation_sha256: str | None = None,
) -> TableObservationReview:
    """Create an event review without changing the draft annotation."""

    if annotation.review_state != "draft":
        raise VisionReviewError("Only draft annotations can receive a new review.")
    if event_decision not in VISION_REVIEW_DECISIONS:
        raise VisionReviewError(f"Unknown event_decision: {event_decision}.")
    if observed_cards is None:
        cards = annotation.observed_cards
    else:
        from .vision_annotation import ObservedCard

        cards = tuple(
            item if isinstance(item, ObservedCard) else ObservedCard.from_mapping(item)
            for item in observed_cards
        )
    event_review = {
        "confirm_card_play": "confirmed_card_play",
        "reject_event": "false_event_proposal",
    }[event_decision]
    reviewed = replace(
        annotation,
        observed_cards=tuple(cards),
        event_review=event_review,
        review_state="reviewed",
    )
    return TableObservationReview(
        review_id=review_id or f"review-{uuid4().hex}",
        annotation_set_id=annotation.annotation_set_id,
        source_annotation_sha256=source_annotation_sha256 or _sha256(_annotation_bytes(annotation)),
        event_decision=event_decision,
        reviewer=reviewer,
        reviewed_at=reviewed_at or _now(),
        reviewed_annotation=reviewed,
        notes=notes,
    )


def _annotation_bytes(annotation: TableObservationAnnotation) -> bytes:
    from .vision_annotation import annotation_bytes

    return annotation_bytes(annotation)


def load_table_observation_review(path: str | Path) -> TableObservationReview:
    review_path = Path(path)
    try:
        payload = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisionReviewError(
            f"Could not read table-observation review {review_path}: {exc}"
        ) from exc
    return TableObservationReview.from_mapping(payload)


def save_table_observation_review(
    review: TableObservationReview, path: str | Path, *, overwrite: bool = False
) -> None:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise VisionReviewError(f"Refusing to overwrite review: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(review.to_mapping(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def _same_source_annotation(
    source: TableObservationAnnotation, reviewed: TableObservationAnnotation
) -> bool:
    source_mapping = source.to_mapping()
    reviewed_mapping = reviewed.to_mapping()
    for field in ("observed_cards", "event_review", "review_state"):
        source_mapping.pop(field)
        reviewed_mapping.pop(field)
    return source_mapping == reviewed_mapping


def apply_table_observation_review(
    annotation_path: str | Path,
    review_path: str | Path,
    *,
    out_dir: str | Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply one immutable review to a new directory and write a receipt."""

    source_path = Path(annotation_path)
    review_file = Path(review_path)
    try:
        source = load_vision_annotation(source_path)
        review = load_table_observation_review(review_file)
    except (VisionAnnotationError, VisionReviewError) as exc:
        raise VisionReviewError(str(exc)) from exc
    source_hash = _sha256_file(source_path)
    canonical_source_hash = _sha256(_annotation_bytes(source))
    if review.source_annotation_sha256 not in {source_hash, canonical_source_hash}:
        raise VisionReviewError("The source annotation checksum does not match the review.")
    if review.annotation_set_id != source.annotation_set_id:
        raise VisionReviewError("The review annotation_set_id does not match the source.")
    if not _same_source_annotation(source, review.reviewed_annotation):
        raise VisionReviewError("The review changes immutable annotation fields.")

    destination = Path(out_dir).resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise VisionReviewError(f"Output directory is not empty: {destination}")
    output_annotation = destination / f"{source.annotation_set_id}.json"
    applied_at = _now()
    review_sha256 = _sha256_file(review_file)
    output_annotation_sha256 = _sha256(_annotation_bytes(review.reviewed_annotation))
    lifecycle_receipt = build_annotation_application_receipt(
        annotation_set_id=source.annotation_set_id,
        review_id=review.review_id,
        source_annotation_digest=canonical_source_hash,
        output_annotation_digest=output_annotation_sha256,
        review_digest=review_sha256,
        event_decision=review.event_decision,
        operator=review.reviewer,
        receipt_id=f"receipt-{review.review_id}",
        occurred_at=applied_at,
    )
    receipt = {
        "schema_version": TABLE_OBSERVATION_APPLY_SCHEMA_VERSION,
        "apply_id": f"apply-{uuid4().hex}",
        "source_annotation": str(source_path),
        "source_annotation_sha256": source_hash,
        "review": str(review_file),
        "review_sha256": review_sha256,
        "review_id": review.review_id,
        "annotation_set_id": source.annotation_set_id,
        "event_decision": review.event_decision,
        "output_annotation": str(output_annotation),
        "output_schema_version": TABLE_OBSERVATION_SCHEMA_VERSION,
        "source_unchanged": True,
        "applied_at": applied_at,
        "lifecycle_receipt": lifecycle_receipt.to_mapping(),
    }
    if dry_run:
        return receipt

    destination.mkdir(parents=True, exist_ok=True)
    output_annotation.write_text(
        json.dumps(review.reviewed_annotation.to_mapping(), indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (destination / "table-observation-review.json").write_text(
        json.dumps(review.to_mapping(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    receipt["output_annotation_sha256"] = _sha256_file(output_annotation)
    (destination / "table-observation-apply-receipt.json").write_text(
        json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return receipt


# Short aliases for callers that use the old review verb without the superseded schema.
VisionReview = TableObservationReview
build_vision_review = build_table_observation_review
load_vision_review = load_table_observation_review
save_vision_review = save_table_observation_review
apply_vision_review = apply_table_observation_review


__all__ = [
    "TABLE_OBSERVATION_APPLY_SCHEMA_VERSION",
    "TABLE_OBSERVATION_REVIEW_SCHEMA_VERSION",
    "TableObservationReview",
    "TableObservationReviewArtifact",
    "VisionReview",
    "VisionReviewError",
    "apply_table_observation_review",
    "apply_vision_review",
    "build_table_observation_review",
    "build_vision_review",
    "load_table_observation_review",
    "load_vision_review",
    "save_table_observation_review",
    "save_vision_review",
]
