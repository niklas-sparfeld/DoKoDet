"""Resumable review workflow for corrected visible-card geometry.

The v2 queue keeps source and teacher evidence immutable. Review state is the only part that can
change. A GOOD frame can be saved while its card actions are still incomplete, then finalized only
when every teacher proposal has an accept, reshape, or remove action and every added card has a
complete reviewed geometry.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from .visible_card_review import (
    VISIBLE_CARD_FAILURE_TAGS,
    ReviewedVisibleCard,
    VisibleCardReviewContractError,
)
from .visible_cards import (
    IMPROVED_REQUEST_SCHEMA_VERSION,
    ProviderResult,
    VisibleCardError,
    normalize_prediction,
)

VISIBLE_CARD_REVIEW_QUEUE_SCHEMA = "visible-card-review-queue/v2"
VISIBLE_CARD_REVIEW_LINEAGE_SCHEMA = "visible-card-review-lineage/v1"
REVIEW_FRAME_STATES = frozenset({"unreviewed", "in_progress", "reviewed"})
REVIEW_FRAME_DECISIONS = frozenset({"GOOD", "BAD"})
REVIEW_CARD_ACTIONS = frozenset({"accepted", "reshaped", "added", "removed"})


class VisibleCardReviewWorkflowError(VisibleCardError, ValueError):
    """Raised when a visible-card review queue cannot be safely changed or applied."""


class VisibleCardReviewConflict(VisibleCardReviewWorkflowError):
    """Raised when a revision-guarded review write is based on stale state."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise VisibleCardReviewWorkflowError(f"could not read teacher artifact: {path}") from error


def _identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-/"
            for character in value
        )
    ):
        raise VisibleCardReviewWorkflowError(f"{field} must be a simple non-empty identifier")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisibleCardReviewWorkflowError(f"{field} must be a non-empty string")
    return value


def _digest_value(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise VisibleCardReviewWorkflowError(f"{field} must be a lower-case SHA-256 digest")
    return result


def _timestamp(value: Any, field: str) -> str:
    result = _text(value, field)
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as error:
        raise VisibleCardReviewWorkflowError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise VisibleCardReviewWorkflowError(f"{field} must use UTC")
    return result


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VisibleCardReviewWorkflowError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VisibleCardReviewWorkflowError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class VisibleCardSourceLineage:
    """Immutable source-frame identity needed by a reviewed visible-card artifact."""

    package_id: str
    frame_part_name: str
    target_offset_ms: int
    image: str
    frame_sha256: str
    source_asset_id: str
    source_lineage_group: str
    width: int
    height: int
    source_asset_sha256: str | None = None

    @property
    def item_id(self) -> str:
        return f"{self.package_id}:{self.frame_part_name}"

    def __post_init__(self) -> None:
        _identifier(self.package_id, "source.package_id")
        _identifier(self.frame_part_name, "source.frame_part_name")
        if isinstance(self.target_offset_ms, bool) or not isinstance(self.target_offset_ms, int):
            raise VisibleCardReviewWorkflowError("source.target_offset_ms must be an integer")
        _text(self.image, "source.image")
        _digest_value(self.frame_sha256, "source.frame_sha256")
        _identifier(self.source_asset_id, "source.source_asset_id")
        _identifier(self.source_lineage_group, "source.source_lineage_group")
        _positive_int(self.width, "source.width")
        _positive_int(self.height, "source.height")
        if self.source_asset_sha256 is not None:
            _digest_value(self.source_asset_sha256, "source.source_asset_sha256")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "frame_part_name": self.frame_part_name,
            "target_offset_ms": self.target_offset_ms,
            "image": self.image,
            "frame_sha256": self.frame_sha256,
            "source_asset_id": self.source_asset_id,
            "source_lineage_group": self.source_lineage_group,
            "source_asset_sha256": self.source_asset_sha256,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "VisibleCardSourceLineage":
        fields = {
            "package_id",
            "frame_part_name",
            "target_offset_ms",
            "image",
            "frame_sha256",
            "source_asset_id",
            "source_lineage_group",
            "source_asset_sha256",
            "width",
            "height",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise VisibleCardReviewWorkflowError("source lineage has unexpected fields")
        try:
            return cls(**value)
        except (TypeError, VisibleCardReviewWorkflowError) as error:
            raise VisibleCardReviewWorkflowError("source lineage is invalid") from error


@dataclass(frozen=True, slots=True)
class VisibleCardTeacherLineage:
    """Immutable request and provider result lineage for the teacher proposal."""

    result_path: str
    result_digest: str
    request_digest: str
    request: dict[str, Any]
    provider: dict[str, str]
    result: dict[str, Any]
    prediction_sha256: str

    def __post_init__(self) -> None:
        _text(self.result_path, "teacher.result_path")
        _digest_value(self.result_digest, "teacher.result_digest")
        _digest_value(self.request_digest, "teacher.request_digest")
        if not isinstance(self.request, dict) or _digest(self.request) != self.request_digest:
            raise VisibleCardReviewWorkflowError("teacher request does not match request_digest")
        if not isinstance(self.provider, dict) or set(self.provider) != {"name", "model"}:
            raise VisibleCardReviewWorkflowError("teacher provider has unexpected fields")
        _text(self.provider["name"], "teacher.provider.name")
        _text(self.provider["model"], "teacher.provider.model")
        if not isinstance(self.result, dict):
            raise VisibleCardReviewWorkflowError("teacher result must be an object")
        expected_result_fields = {
            "status",
            "prediction",
            "usage",
            "latency_ms",
            "retry_count",
            "estimated_cost_usd",
            "error",
            "raw_response",
        }
        if set(self.result) != expected_result_fields:
            raise VisibleCardReviewWorkflowError("teacher result has unexpected fields")
        try:
            normalized = ProviderResult.from_mapping(self.result).prediction.to_mapping()
        except (TypeError, ValueError, VisibleCardError) as error:
            raise VisibleCardReviewWorkflowError("teacher result is invalid") from error
        if self.request.get("schema_version") == IMPROVED_REQUEST_SCHEMA_VERSION:
            normalize_prediction(normalized, require_tight_boxes=True)
        if _digest(normalized) != self.prediction_sha256:
            raise VisibleCardReviewWorkflowError("teacher prediction digest does not match")
        if self.result["prediction"] != normalized:
            raise VisibleCardReviewWorkflowError("teacher prediction is not canonical")

    @property
    def prediction(self) -> dict[str, Any]:
        return self.result["prediction"]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "result_path": self.result_path,
            "result_digest": self.result_digest,
            "request_digest": self.request_digest,
            "request": self.request,
            "provider": self.provider,
            "result": self.result,
            "prediction_sha256": self.prediction_sha256,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "VisibleCardTeacherLineage":
        fields = {
            "result_path",
            "result_digest",
            "request_digest",
            "request",
            "provider",
            "result",
            "prediction_sha256",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise VisibleCardReviewWorkflowError("teacher lineage has unexpected fields")
        try:
            return cls(**value)
        except (TypeError, VisibleCardReviewWorkflowError) as error:
            raise VisibleCardReviewWorkflowError("teacher lineage is invalid") from error


@dataclass(frozen=True, slots=True)
class VisibleCardReviewAction:
    """One accept, reshape, add, or remove operation for one card proposal."""

    card_id: str
    action: Literal["accepted", "reshaped", "added", "removed"]
    proposal_index: int | None
    reviewed_card: ReviewedVisibleCard | None

    def __post_init__(self) -> None:
        _identifier(self.card_id, "card action.card_id")
        if self.action not in REVIEW_CARD_ACTIONS:
            raise VisibleCardReviewWorkflowError(f"unknown card action: {self.action}")
        if self.action == "added" and self.proposal_index is not None:
            raise VisibleCardReviewWorkflowError("added card actions cannot name a proposal")
        if self.action != "added":
            _non_negative_int(self.proposal_index, "card action.proposal_index")
        if self.action == "removed" and self.reviewed_card is not None:
            raise VisibleCardReviewWorkflowError("removed card actions cannot contain geometry")
        if self.action != "removed" and self.reviewed_card is None:
            raise VisibleCardReviewWorkflowError(
                "accepted, reshaped, and added actions need reviewed geometry"
            )
        if self.reviewed_card is not None and self.reviewed_card.card_id != self.card_id:
            raise VisibleCardReviewWorkflowError(
                "reviewed card ID does not match its action card ID"
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "action": self.action,
            "proposal_index": self.proposal_index,
            "reviewed_card": self.reviewed_card.to_mapping() if self.reviewed_card else None,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "VisibleCardReviewAction":
        fields = {"card_id", "action", "proposal_index", "reviewed_card"}
        if not isinstance(value, dict) or set(value) != fields:
            raise VisibleCardReviewWorkflowError("review action has unexpected fields")
        reviewed_card = value["reviewed_card"]
        try:
            return cls(
                card_id=value["card_id"],
                action=value["action"],
                proposal_index=value["proposal_index"],
                reviewed_card=(
                    None
                    if reviewed_card is None
                    else ReviewedVisibleCard.from_mapping(reviewed_card)
                ),
            )
        except (TypeError, ValueError, VisibleCardReviewContractError) as error:
            raise VisibleCardReviewWorkflowError("review action is invalid") from error


@dataclass(frozen=True, slots=True)
class VisibleCardFrameReview:
    """Mutable review state stored immutably as a queue snapshot after each write."""

    status: Literal["unreviewed", "in_progress", "reviewed"] = "unreviewed"
    decision: Literal["GOOD", "BAD"] | None = None
    empty_frame: bool | None = None
    failure_tags: tuple[str, ...] = ()
    actions: tuple[VisibleCardReviewAction, ...] = ()
    reviewer: str | None = None
    review_id: str | None = None
    started_at_utc: str | None = None
    updated_at_utc: str | None = None
    completed_at_utc: str | None = None

    def __post_init__(self) -> None:
        if self.status not in REVIEW_FRAME_STATES:
            raise VisibleCardReviewWorkflowError(f"unknown review status: {self.status}")
        if self.status == "unreviewed":
            if (
                any(
                    value is not None
                    for value in (
                        self.decision,
                        self.empty_frame,
                        self.reviewer,
                        self.review_id,
                        self.started_at_utc,
                        self.updated_at_utc,
                        self.completed_at_utc,
                    )
                )
                or self.failure_tags
                or self.actions
            ):
                raise VisibleCardReviewWorkflowError(
                    "an unreviewed frame cannot contain review state"
                )
            return
        if self.decision not in REVIEW_FRAME_DECISIONS:
            raise VisibleCardReviewWorkflowError("reviewed frame needs GOOD or BAD")
        if not isinstance(self.empty_frame, bool):
            raise VisibleCardReviewWorkflowError(
                "empty_frame must be a boolean after review starts"
            )
        if self.decision == "GOOD" and self.empty_frame:
            raise VisibleCardReviewWorkflowError("GOOD frame cannot be marked empty")
        if not isinstance(self.actions, tuple) or any(
            not isinstance(action, VisibleCardReviewAction) for action in self.actions
        ):
            raise VisibleCardReviewWorkflowError("review actions must use the review contract")
        if len(set(self.failure_tags)) != len(self.failure_tags) or any(
            tag not in VISIBLE_CARD_FAILURE_TAGS for tag in self.failure_tags
        ):
            raise VisibleCardReviewWorkflowError("review failure_tags are invalid")
        _text(self.reviewer, "review.reviewer")
        _identifier(self.review_id, "review.review_id")
        _timestamp(self.started_at_utc, "review.started_at_utc")
        _timestamp(self.updated_at_utc, "review.updated_at_utc")
        if self.status == "reviewed":
            _timestamp(self.completed_at_utc, "review.completed_at_utc")
        elif self.completed_at_utc is not None:
            raise VisibleCardReviewWorkflowError("in-progress review cannot have completed_at_utc")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "decision": self.decision,
            "empty_frame": self.empty_frame,
            "failure_tags": list(self.failure_tags),
            "actions": [action.to_mapping() for action in self.actions],
            "reviewer": self.reviewer,
            "review_id": self.review_id,
            "started_at_utc": self.started_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "completed_at_utc": self.completed_at_utc,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "VisibleCardFrameReview":
        fields = {
            "status",
            "decision",
            "empty_frame",
            "failure_tags",
            "actions",
            "reviewer",
            "review_id",
            "started_at_utc",
            "updated_at_utc",
            "completed_at_utc",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise VisibleCardReviewWorkflowError("frame review has unexpected fields")
        if not isinstance(value["failure_tags"], list) or not isinstance(value["actions"], list):
            raise VisibleCardReviewWorkflowError("frame review lists are invalid")
        try:
            return cls(
                status=value["status"],
                decision=value["decision"],
                empty_frame=value["empty_frame"],
                failure_tags=tuple(value["failure_tags"]),
                actions=tuple(
                    VisibleCardReviewAction.from_mapping(item) for item in value["actions"]
                ),
                reviewer=value["reviewer"],
                review_id=value["review_id"],
                started_at_utc=value["started_at_utc"],
                updated_at_utc=value["updated_at_utc"],
                completed_at_utc=value["completed_at_utc"],
            )
        except (TypeError, ValueError, VisibleCardReviewWorkflowError) as error:
            raise VisibleCardReviewWorkflowError("frame review is invalid") from error


@dataclass(frozen=True, slots=True)
class VisibleCardReviewItem:
    item_id: str
    source: VisibleCardSourceLineage
    teacher: VisibleCardTeacherLineage
    review: VisibleCardFrameReview = field(default_factory=VisibleCardFrameReview)

    def __post_init__(self) -> None:
        _identifier(self.item_id, "item_id")
        if self.item_id != self.source.item_id:
            raise VisibleCardReviewWorkflowError("item_id does not match source lineage")
        request = self.teacher.request
        if (
            request.get("package_id") != self.source.package_id
            or request.get("frame_part_name") != self.source.frame_part_name
            or request.get("target_offset_ms") != self.source.target_offset_ms
            or request.get("image_sha256") != self.source.frame_sha256
            or request.get("width") != self.source.width
            or request.get("height") != self.source.height
        ):
            raise VisibleCardReviewWorkflowError("teacher request does not match source lineage")
        _validate_actions(
            self.review.actions,
            len(self.teacher.prediction["cards"]),
            teacher_prediction=self.teacher.prediction,
        )
        if self.review.status == "reviewed":
            _validate_complete_review(self.review, len(self.teacher.prediction["cards"]))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "source": self.source.to_mapping(),
            "teacher": self.teacher.to_mapping(),
            "review": self.review.to_mapping(),
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "VisibleCardReviewItem":
        fields = {"item_id", "source", "teacher", "review"}
        if not isinstance(value, dict) or set(value) != fields:
            raise VisibleCardReviewWorkflowError("review item has unexpected fields")
        try:
            return cls(
                item_id=value["item_id"],
                source=VisibleCardSourceLineage.from_mapping(value["source"]),
                teacher=VisibleCardTeacherLineage.from_mapping(value["teacher"]),
                review=VisibleCardFrameReview.from_mapping(value["review"]),
            )
        except (TypeError, ValueError, VisibleCardReviewWorkflowError) as error:
            raise VisibleCardReviewWorkflowError("review item is invalid") from error


@dataclass(frozen=True, slots=True)
class VisibleCardReviewQueue:
    run_id: str
    items: tuple[VisibleCardReviewItem, ...]
    created_at_utc: str
    revision: int = 0
    schema_version: str = VISIBLE_CARD_REVIEW_QUEUE_SCHEMA

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        if self.schema_version != VISIBLE_CARD_REVIEW_QUEUE_SCHEMA:
            raise VisibleCardReviewWorkflowError("unsupported visible-card review queue schema")
        _timestamp(self.created_at_utc, "created_at_utc")
        _non_negative_int(self.revision, "revision")
        if len({item.item_id for item in self.items}) != len(self.items):
            raise VisibleCardReviewWorkflowError("review queue item IDs must be unique")

    @property
    def pending_items(self) -> tuple[VisibleCardReviewItem, ...]:
        return tuple(item for item in self.items if item.review.status != "reviewed")

    @property
    def reviewed_items(self) -> tuple[VisibleCardReviewItem, ...]:
        return tuple(item for item in self.items if item.review.status == "reviewed")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at_utc": self.created_at_utc,
            "revision": self.revision,
            "items": [item.to_mapping() for item in self.items],
        }


def _validate_actions(
    actions: Sequence[VisibleCardReviewAction],
    proposal_count: int,
    *,
    teacher_prediction: Mapping[str, Any] | None = None,
) -> None:
    proposal_indices = [
        action.proposal_index for action in actions if action.proposal_index is not None
    ]
    if len(set(proposal_indices)) != len(proposal_indices):
        raise VisibleCardReviewWorkflowError("each teacher proposal can have only one action")
    if any(index >= proposal_count for index in proposal_indices):
        raise VisibleCardReviewWorkflowError("review action refers to a missing teacher proposal")
    card_ids = [action.card_id for action in actions]
    if len(set(card_ids)) != len(card_ids):
        raise VisibleCardReviewWorkflowError("review action card IDs must be unique")
    if teacher_prediction is not None:
        teacher_cards = teacher_prediction["cards"]
        for action in actions:
            if action.action != "accepted":
                continue
            assert action.proposal_index is not None
            teacher_card = teacher_cards[action.proposal_index]
            reviewed = action.reviewed_card
            assert reviewed is not None
            if (
                reviewed.visible_region.to_mapping()["polygons"] != [teacher_card["polygon"]]
                or reviewed.derived_box.to_mapping() != teacher_card["box_2d"]
                or reviewed.side != teacher_card["side"]
            ):
                raise VisibleCardReviewWorkflowError(
                    "accepted action must preserve the teacher visible geometry and side"
                )


def _validate_complete_review(review: VisibleCardFrameReview, proposal_count: int) -> None:
    if review.status != "reviewed":
        raise VisibleCardReviewWorkflowError("review is not complete")
    if review.decision == "BAD":
        if review.actions:
            raise VisibleCardReviewWorkflowError("BAD frames cannot contain card actions")
        return
    proposal_indices = {
        action.proposal_index for action in review.actions if action.proposal_index is not None
    }
    expected_indices = set(range(proposal_count))
    if proposal_indices != expected_indices:
        raise VisibleCardReviewWorkflowError(
            "GOOD review must action every teacher proposal, including removed proposals"
        )
    if not any(action.reviewed_card is not None for action in review.actions):
        raise VisibleCardReviewWorkflowError("GOOD review must contain one visible card")


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        fd, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_path)


def _teacher_from_artifact(
    artifact: Mapping[str, Any], artifact_path: str | None
) -> VisibleCardTeacherLineage:
    try:
        request = artifact["request"]
        request_digest = artifact["request_key"]
        provider = artifact["provider"]
        result = {
            field: artifact[field]
            for field in (
                "status",
                "prediction",
                "usage",
                "latency_ms",
                "retry_count",
                "estimated_cost_usd",
                "error",
                "raw_response",
            )
        }
    except KeyError as error:
        raise VisibleCardReviewWorkflowError(
            "teacher input must be a complete visible-card run artifact"
        ) from error
    if not isinstance(request, dict) or not isinstance(provider, dict):
        raise VisibleCardReviewWorkflowError("teacher request and provider must be objects")
    if request_digest != _digest(request):
        raise VisibleCardReviewWorkflowError("teacher request key does not match request")
    try:
        normalized_result = ProviderResult.from_mapping(result)
    except (TypeError, ValueError, VisibleCardError) as error:
        raise VisibleCardReviewWorkflowError("teacher result is invalid") from error
    if normalized_result.status != "ok":
        raise VisibleCardReviewWorkflowError("an unavailable teacher result cannot enter review")
    result["prediction"] = normalized_result.prediction.to_mapping()
    if request.get("schema_version") == IMPROVED_REQUEST_SCHEMA_VERSION:
        normalize_prediction(result["prediction"], require_tight_boxes=True)
    if artifact_path is not None:
        result_path = _text(artifact_path, "teacher result path")
        path = Path(result_path)
        result_digest = _file_digest(path) if path.is_file() else artifact.get("result_digest")
        if result_digest is None:
            raise VisibleCardReviewWorkflowError(
                f"teacher result does not exist and has no digest: {result_path}"
            )
    else:
        result_path = "<inline-run-artifact>"
        result_digest = artifact.get("result_digest") or _digest(artifact)
    return VisibleCardTeacherLineage(
        result_path=result_path,
        result_digest=_digest_value(result_digest, "teacher.result_digest"),
        request_digest=request_digest,
        request=request,
        provider=provider,
        result=result,
        prediction_sha256=_digest(result["prediction"]),
    )


def _source_from_artifact(
    artifact: Mapping[str, Any],
    lineage: Mapping[str, Any] | None,
) -> VisibleCardSourceLineage:
    request = artifact.get("request")
    if not isinstance(request, dict):
        raise VisibleCardReviewWorkflowError("teacher artifact request is required")
    package_id = request.get("package_id")
    frame_part_name = request.get("frame_part_name")
    item_id = f"{package_id}:{frame_part_name}"
    values = dict(lineage or artifact.get("source_lineage") or {})
    values.pop("item_id", None)
    values.setdefault("package_id", package_id)
    values.setdefault("frame_part_name", frame_part_name)
    values.setdefault("target_offset_ms", request.get("target_offset_ms"))
    values.setdefault("image", artifact.get("image"))
    values.setdefault("frame_sha256", request.get("image_sha256"))
    values.setdefault("width", request.get("width"))
    values.setdefault("height", request.get("height"))
    try:
        source = VisibleCardSourceLineage.from_mapping(values)
    except VisibleCardReviewWorkflowError as error:
        raise VisibleCardReviewWorkflowError(
            f"source lineage is incomplete for {item_id}; provide source_asset_id and "
            "source_lineage_group"
        ) from error
    return source


def build_visible_card_review_queue(
    artifacts: Sequence[Mapping[str, Any]],
    destination: str | Path,
    *,
    run_id: str,
    lineage_by_item: Mapping[str, Mapping[str, Any]] | None = None,
) -> VisibleCardReviewQueue:
    """Build a v2 queue from immutable run artifacts and explicit source lineage."""

    _identifier(run_id, "run_id")
    destination_path = Path(destination)
    if destination_path.exists():
        raise VisibleCardReviewWorkflowError(f"review queue already exists: {destination_path}")
    items: list[VisibleCardReviewItem] = []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise VisibleCardReviewWorkflowError("each teacher artifact must be an object")
        source = _source_from_artifact(
            artifact,
            (lineage_by_item or {}).get(
                _artifact_item_id(artifact),
            ),
        )
        teacher = _teacher_from_artifact(
            artifact,
            artifact.get("artifact_path")
            if isinstance(artifact.get("artifact_path"), str)
            else None,
        )
        item = VisibleCardReviewItem(
            item_id=source.item_id,
            source=source,
            teacher=teacher,
        )
        if any(existing.item_id == item.item_id for existing in items):
            raise VisibleCardReviewWorkflowError(f"duplicate review item: {item.item_id}")
        items.append(item)
    items.sort(key=lambda item: item.item_id)
    queue = VisibleCardReviewQueue(
        run_id=run_id,
        items=tuple(items),
        created_at_utc=_now(),
    )
    _atomic_write(destination_path, queue.to_mapping())
    return queue


def _artifact_item_id(artifact: Mapping[str, Any]) -> str:
    request = artifact.get("request")
    if not isinstance(request, Mapping):
        raise VisibleCardReviewWorkflowError("teacher artifact request is required")
    return f"{request.get('package_id')}:{request.get('frame_part_name')}"


def load_visible_card_review_queue(path: str | Path) -> VisibleCardReviewQueue:
    queue_path = Path(path)
    try:
        value = json.loads(queue_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardReviewWorkflowError(
            f"could not read review queue: {queue_path}"
        ) from error
    fields = {"schema_version", "run_id", "created_at_utc", "revision", "items"}
    if not isinstance(value, dict) or set(value) != fields:
        raise VisibleCardReviewWorkflowError("review queue has unexpected fields")
    if value["schema_version"] != VISIBLE_CARD_REVIEW_QUEUE_SCHEMA:
        raise VisibleCardReviewWorkflowError("unsupported visible-card review queue schema")
    if not isinstance(value["items"], list):
        raise VisibleCardReviewWorkflowError("review queue items must be a list")
    try:
        items = tuple(VisibleCardReviewItem.from_mapping(item) for item in value["items"])
        return VisibleCardReviewQueue(
            run_id=value["run_id"],
            items=items,
            created_at_utc=value["created_at_utc"],
            revision=value["revision"],
        )
    except (TypeError, ValueError, VisibleCardReviewWorkflowError) as error:
        raise VisibleCardReviewWorkflowError("review queue is invalid") from error


def _find_item(queue: VisibleCardReviewQueue, item_id: str) -> VisibleCardReviewItem:
    _identifier(item_id, "item_id")
    for item in queue.items:
        if item.item_id == item_id:
            return item
    raise VisibleCardReviewWorkflowError(f"review queue item does not exist: {item_id}")


def _review_id(run_id: str, item_id: str) -> str:
    return f"review-{_digest({'run_id': run_id, 'item_id': item_id})[:24]}"


def _actions(
    value: Sequence[VisibleCardReviewAction | Mapping[str, Any]],
) -> tuple[VisibleCardReviewAction, ...]:
    result: list[VisibleCardReviewAction] = []
    for action in value:
        result.append(
            action
            if isinstance(action, VisibleCardReviewAction)
            else VisibleCardReviewAction.from_mapping(action)
        )
    return tuple(result)


def record_frame_review(
    path: str | Path,
    item_id: str,
    decision: Literal["GOOD", "BAD"],
    *,
    reviewer: str,
    empty_frame: bool | None = None,
    failure_tags: Sequence[str] = (),
    actions: Sequence[VisibleCardReviewAction | Mapping[str, Any]] = (),
) -> VisibleCardReviewQueue:
    """Save the frame decision and any supplied card actions in one atomic update."""

    if decision not in REVIEW_FRAME_DECISIONS:
        raise VisibleCardReviewWorkflowError("decision must be GOOD or BAD")
    reviewer = _text(reviewer, "reviewer")
    if empty_frame is None:
        raise VisibleCardReviewWorkflowError(
            "empty_frame must be explicit; use true for a reviewed empty negative"
        )
    if not isinstance(empty_frame, bool):
        raise VisibleCardReviewWorkflowError("empty_frame must be a boolean")
    if decision == "GOOD" and empty_frame:
        raise VisibleCardReviewWorkflowError("GOOD frame cannot be empty")
    queue = load_visible_card_review_queue(path)
    item = _find_item(queue, item_id)
    if item.review.status != "unreviewed":
        raise VisibleCardReviewWorkflowError(f"review already started for {item_id}")
    parsed_actions = _actions(actions)
    if decision == "BAD" and parsed_actions:
        raise VisibleCardReviewWorkflowError("BAD frames cannot contain card actions")
    _validate_actions(
        parsed_actions,
        len(item.teacher.prediction["cards"]),
        teacher_prediction=item.teacher.prediction,
    )
    now = _now()
    state = VisibleCardFrameReview(
        status="in_progress",
        decision=decision,
        empty_frame=empty_frame,
        failure_tags=tuple(failure_tags),
        actions=parsed_actions,
        reviewer=reviewer,
        review_id=_review_id(queue.run_id, item_id),
        started_at_utc=now,
        updated_at_utc=now,
    )
    if decision == "BAD" or _complete_if_possible(state, len(item.teacher.prediction["cards"])):
        state = replace(state, status="reviewed", completed_at_utc=now)
    updated = replace(item, review=state)
    return _write_updated_item(path, queue, updated)


def _complete_if_possible(state: VisibleCardFrameReview, proposal_count: int) -> bool:
    if state.decision == "BAD":
        return True
    try:
        _validate_complete_review(
            replace(state, status="reviewed", completed_at_utc=_now()), proposal_count
        )
    except VisibleCardReviewWorkflowError:
        return False
    return True


def record_card_action(
    path: str | Path,
    item_id: str,
    action: Literal["accepted", "reshaped", "added", "removed"] | Mapping[str, Any],
    *,
    reviewer: str,
) -> VisibleCardReviewQueue:
    """Save one card correction and keep the frame resumable until completion."""

    reviewer = _text(reviewer, "reviewer")
    parsed = (
        action
        if isinstance(action, VisibleCardReviewAction)
        else VisibleCardReviewAction.from_mapping(action)
    )
    queue = load_visible_card_review_queue(path)
    item = _find_item(queue, item_id)
    state = item.review
    if state.status != "in_progress" or state.decision != "GOOD":
        raise VisibleCardReviewWorkflowError(
            "start a GOOD frame review before recording card actions"
        )
    if state.reviewer != reviewer:
        raise VisibleCardReviewWorkflowError("reviewer does not match the active review")
    if parsed.proposal_index is not None:
        proposal_count = len(item.teacher.prediction["cards"])
        if parsed.proposal_index >= proposal_count:
            raise VisibleCardReviewWorkflowError("card action refers to a missing proposal")
    actions = [existing for existing in state.actions if existing.card_id != parsed.card_id]
    actions.append(parsed)
    _validate_actions(
        actions,
        len(item.teacher.prediction["cards"]),
        teacher_prediction=item.teacher.prediction,
    )
    updated_state = replace(state, actions=tuple(actions), updated_at_utc=_now())
    return _write_updated_item(path, queue, replace(item, review=updated_state))


def finalize_visible_card_review(
    path: str | Path,
    item_id: str,
    *,
    reviewer: str,
) -> VisibleCardReviewQueue:
    """Finalize a GOOD review only after all teacher proposals have an action."""

    reviewer = _text(reviewer, "reviewer")
    queue = load_visible_card_review_queue(path)
    item = _find_item(queue, item_id)
    state = item.review
    if state.status != "in_progress":
        raise VisibleCardReviewWorkflowError(f"review is not in progress for {item_id}")
    if state.reviewer != reviewer:
        raise VisibleCardReviewWorkflowError("reviewer does not match the active review")
    completed_at = _now()
    _validate_complete_review(
        replace(state, status="reviewed", completed_at_utc=completed_at),
        len(item.teacher.prediction["cards"]),
    )
    updated_state = replace(
        state,
        status="reviewed",
        updated_at_utc=completed_at,
        completed_at_utc=completed_at,
    )
    return _write_updated_item(path, queue, replace(item, review=updated_state))


def validate_completed_visible_card_review_queue(
    queue: VisibleCardReviewQueue,
) -> VisibleCardReviewQueue:
    """Reject a resumable queue until every item is a complete reviewed artifact."""

    for item in queue.items:
        if item.review.status != "reviewed":
            raise VisibleCardReviewWorkflowError(f"review is incomplete: {item.item_id}")
        _validate_complete_review(item.review, len(item.teacher.prediction["cards"]))
    return queue


def _write_updated_item(
    path: str | Path,
    queue: VisibleCardReviewQueue,
    updated_item: VisibleCardReviewItem,
) -> VisibleCardReviewQueue:
    items = tuple(
        updated_item if item.item_id == updated_item.item_id else item for item in queue.items
    )
    result = replace(queue, items=items, revision=queue.revision + 1)
    _atomic_write(Path(path), result.to_mapping())
    return result


@contextlib.contextmanager
def _queue_lock(path: Path):
    """Serialize queue read-check-write operations without locking replaceable inodes."""

    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _check_expected_revision(queue: VisibleCardReviewQueue, expected_revision: int) -> None:
    _non_negative_int(expected_revision, "expected_revision")
    if queue.revision != expected_revision:
        raise VisibleCardReviewConflict(
            f"review queue revision changed: expected {expected_revision}, current {queue.revision}"
        )


def _review_from_update(
    value: Mapping[str, Any],
    existing: VisibleCardFrameReview,
    *,
    run_id: str,
    item_id: str,
    proposal_count: int,
    teacher_prediction: Mapping[str, Any],
) -> VisibleCardFrameReview:
    fields = {"status", "decision", "empty_frame", "failure_tags", "actions", "reviewer"}
    if set(value) != fields:
        raise VisibleCardReviewWorkflowError("frame review update has unexpected fields")
    status = value["status"]
    if status not in {"in_progress", "reviewed"}:
        raise VisibleCardReviewWorkflowError("frame review update status is invalid")
    if not isinstance(value["failure_tags"], list) or not isinstance(value["actions"], list):
        raise VisibleCardReviewWorkflowError("frame review update lists are invalid")
    reviewer = _text(value["reviewer"], "reviewer")
    if existing.reviewer is not None and existing.reviewer != reviewer:
        raise VisibleCardReviewWorkflowError("reviewer does not match the active review")
    parsed_actions = _actions(value["actions"])
    decision = value["decision"]
    if decision not in REVIEW_FRAME_DECISIONS:
        raise VisibleCardReviewWorkflowError("decision must be GOOD or BAD")
    empty_frame = value["empty_frame"]
    if not isinstance(empty_frame, bool):
        raise VisibleCardReviewWorkflowError("empty_frame must be a boolean")
    if decision == "GOOD" and empty_frame:
        raise VisibleCardReviewWorkflowError("GOOD frame cannot be empty")
    if decision == "BAD" and parsed_actions:
        raise VisibleCardReviewWorkflowError("BAD frames cannot contain card actions")
    _validate_actions(
        parsed_actions,
        proposal_count,
        teacher_prediction=teacher_prediction,
    )
    now = _now()
    started_at = existing.started_at_utc or now
    review_id = existing.review_id or _review_id(run_id, item_id)
    completed_at = now if status == "reviewed" else None
    return VisibleCardFrameReview(
        status=status,
        decision=decision,
        empty_frame=empty_frame,
        failure_tags=tuple(value["failure_tags"]),
        actions=parsed_actions,
        reviewer=reviewer,
        review_id=review_id,
        started_at_utc=started_at,
        updated_at_utc=now,
        completed_at_utc=completed_at,
    )


def update_frame_review(
    path: str | Path,
    item_id: str,
    review: Mapping[str, Any],
    *,
    expected_revision: int,
) -> VisibleCardReviewQueue:
    """Replace one complete frame review only when the queue revision still matches."""

    queue_path = Path(path)
    if not isinstance(review, Mapping):
        raise VisibleCardReviewWorkflowError("frame review update must be an object")
    with _queue_lock(queue_path):
        queue = load_visible_card_review_queue(queue_path)
        _check_expected_revision(queue, expected_revision)
        item = _find_item(queue, item_id)
        updated_review = _review_from_update(
            review,
            item.review,
            run_id=queue.run_id,
            item_id=item_id,
            proposal_count=len(item.teacher.prediction["cards"]),
            teacher_prediction=item.teacher.prediction,
        )
        updated_item = replace(item, review=updated_review)
        return _write_updated_item(queue_path, queue, updated_item)


def load_source_lineage_manifest(path: str | Path) -> dict[str, dict[str, Any]]:
    """Load explicit source lineage for queue construction."""

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardReviewWorkflowError(f"could not read source lineage: {path}") from error
    if not isinstance(value, dict) or set(value) != {"schema_version", "items"}:
        raise VisibleCardReviewWorkflowError("source lineage manifest has unexpected fields")
    if value["schema_version"] != VISIBLE_CARD_REVIEW_LINEAGE_SCHEMA:
        raise VisibleCardReviewWorkflowError("unsupported source lineage manifest schema")
    if not isinstance(value["items"], list):
        raise VisibleCardReviewWorkflowError("source lineage manifest items must be a list")
    result: dict[str, dict[str, Any]] = {}
    for entry in value["items"]:
        if not isinstance(entry, dict) or "item_id" not in entry:
            raise VisibleCardReviewWorkflowError("source lineage entries need item_id")
        item_id = _identifier(entry["item_id"], "source lineage item_id")
        if item_id in result:
            raise VisibleCardReviewWorkflowError(f"duplicate source lineage item: {item_id}")
        source = dict(entry)
        source.pop("item_id")
        parsed = VisibleCardSourceLineage.from_mapping(source)
        if parsed.item_id != item_id:
            raise VisibleCardReviewWorkflowError(
                f"source lineage item_id does not match its source: {item_id}"
            )
        result[item_id] = source
    return result


def record_review(
    path: str | Path,
    item_id: str,
    decision: Literal["GOOD", "BAD"],
    *,
    reviewer: str,
    empty_frame: bool | None = None,
    failure_tags: Sequence[str] = (),
    actions: Sequence[VisibleCardReviewAction | Mapping[str, Any]] = (),
) -> VisibleCardReviewQueue:
    """Short alias for callers migrating from the binary review command."""

    return record_frame_review(
        path,
        item_id,
        decision,
        reviewer=reviewer,
        empty_frame=empty_frame,
        failure_tags=failure_tags,
        actions=actions,
    )


__all__ = [
    "REVIEW_CARD_ACTIONS",
    "REVIEW_FRAME_DECISIONS",
    "REVIEW_FRAME_STATES",
    "VISIBLE_CARD_REVIEW_LINEAGE_SCHEMA",
    "VISIBLE_CARD_REVIEW_QUEUE_SCHEMA",
    "VisibleCardFrameReview",
    "VisibleCardReviewConflict",
    "VisibleCardReviewAction",
    "VisibleCardReviewItem",
    "VisibleCardReviewQueue",
    "VisibleCardReviewWorkflowError",
    "VisibleCardSourceLineage",
    "VisibleCardTeacherLineage",
    "build_visible_card_review_queue",
    "finalize_visible_card_review",
    "load_source_lineage_manifest",
    "load_visible_card_review_queue",
    "record_card_action",
    "record_frame_review",
    "record_review",
    "update_frame_review",
    "validate_completed_visible_card_review_queue",
]
