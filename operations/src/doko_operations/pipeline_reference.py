"""Contracts for maintained recording-pipeline reference drafts."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

PIPELINE_REFERENCE_STATE_SCHEMA_VERSION = "pipeline-reference-state/v1"
PIPELINE_REFERENCE_DRAFT_SCHEMA_VERSION = "pipeline-reference-draft/v1"
PIPELINE_REFERENCE_COVERAGE_SCHEMA_VERSION = "pipeline-reference-coverage/v1"
PIPELINE_REFERENCE_IMPACT_SCHEMA_VERSION = "pipeline-reference-impact/v1"
PIPELINE_REFERENCE_CONTENT_TYPES = frozenset({"events", "visible_cards", "visual_identities"})
PIPELINE_REFERENCE_DRAFT_STATES = frozenset({"draft", "completed"})
PIPELINE_REFERENCE_ITEM_STATES = frozenset(
    {
        "pending",
        "accepted",
        "rejected",
        "added",
        "corrected",
        "empty",
        "unusable",
        "identity_unusable",
        "source_problem",
        "affected",
    }
)
PIPELINE_REFERENCE_OPERATIONS = frozenset(
    {
        "accept",
        "reject",
        "add",
        "correct",
        "decide",
        "rebase",
        "set_frame_review",
        "accept_frame_suggestions",
        "set_frame_empty",
        "set_frame_unusable",
    }
)
PIPELINE_REFERENCE_DECISIONS = frozenset(
    {
        "accepted",
        "rejected",
        "empty",
        "unusable",
        "identity_unusable",
        "source_problem",
    }
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class PipelineReferenceContractError(ValueError):
    """Raised when a maintained-reference contract is invalid."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise PipelineReferenceContractError(f"{field} must be an object")
    return value


def _strict(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    fields = set(value)
    missing = expected - fields
    unknown = fields - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise PipelineReferenceContractError(f"{field} has invalid fields ({'; '.join(details)})")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PipelineReferenceContractError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or _IDENTIFIER.fullmatch(result) is None:
        raise PipelineReferenceContractError(f"{field} must be a safe identifier")
    return result


def _optional_identifier(value: Any, field: str) -> str | None:
    return None if value is None else _identifier(value, field)


def _identifier_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PipelineReferenceContractError(f"{field} must be a list")
    values = tuple(_identifier(item, f"{field}[{index}]") for index, item in enumerate(value))
    if len(values) != len(set(values)):
        raise PipelineReferenceContractError(f"{field} must contain unique identifiers")
    return values


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PipelineReferenceContractError(f"{field} must be a non-negative integer")
    return value


def _utc_timestamp(value: Any, field: str) -> str:
    result = _text(value, field)
    try:
        parsed = datetime.fromisoformat(result[:-1] + "+00:00" if result.endswith("Z") else result)
    except ValueError as error:
        raise PipelineReferenceContractError(f"{field} must be an ISO-8601 timestamp") from error
    if "T" not in result or parsed.utcoffset() is None or parsed.utcoffset() != timedelta(0):
        raise PipelineReferenceContractError(f"{field} must use UTC")
    return result


def _validate_json(value: Any, field: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PipelineReferenceContractError(f"{field} must contain finite JSON values")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise PipelineReferenceContractError(f"{field} object keys must be strings")
            _validate_json(child, f"{field}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json(child, f"{field}[{index}]")
        return
    raise PipelineReferenceContractError(f"{field} must contain JSON-compatible values")


def canonical_json_bytes(value: Any) -> bytes:
    _validate_json(value, "value")
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _parse_json(raw: bytes, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, bytes):
        raise TypeError(f"{field} must be bytes")

    def reject_constant(value: str) -> None:
        raise PipelineReferenceContractError(f"{field} contains a non-finite JSON number: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PipelineReferenceContractError(f"{field} contains a duplicate field: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except PipelineReferenceContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineReferenceContractError(f"{field} must be valid UTF-8 JSON") from error
    return _mapping(value, field)


def _content_type(value: Any) -> str:
    result = _identifier(value, "content_type")
    if result not in PIPELINE_REFERENCE_CONTENT_TYPES:
        raise PipelineReferenceContractError("content_type is not referenceable")
    return result


@dataclass(frozen=True, slots=True)
class ReferenceDraftItem:
    """One content item plus explicit human review state."""

    item_id: str
    base_item_id: str | None
    review_state: str
    item: dict[str, Any]

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "reference item"
    ) -> ReferenceDraftItem:
        data = _mapping(raw, context)
        _strict(data, {"item_id", "base_item_id", "review_state", "item"}, context)
        item = _mapping(data["item"], f"{context}.item")
        _validate_json(item, f"{context}.item")
        state = _text(data["review_state"], f"{context}.review_state")
        if state not in PIPELINE_REFERENCE_ITEM_STATES:
            raise PipelineReferenceContractError(f"{context}.review_state is unsupported")
        base_item_id = _optional_identifier(data["base_item_id"], f"{context}.base_item_id")
        if state == "corrected" and base_item_id is None:
            raise PipelineReferenceContractError(f"{context}.corrected items need a base_item_id")
        if (
            state
            not in {
                "accepted",
                "corrected",
                "rejected",
                "empty",
                "unusable",
                "identity_unusable",
                "source_problem",
            }
            and base_item_id is not None
        ):
            raise PipelineReferenceContractError(
                f"{context}.non-corrected items cannot have a base_item_id"
            )
        return cls(
            item_id=_identifier(data["item_id"], f"{context}.item_id"),
            base_item_id=base_item_id,
            review_state=state,
            item=json.loads(canonical_json_bytes(item).decode("utf-8")),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "base_item_id": self.base_item_id,
            "review_state": self.review_state,
            "item": self.item,
        }


@dataclass(frozen=True, slots=True)
class PipelineReferenceDraft:
    """The mutable command-derived draft for one maintained reference."""

    recording_id: str
    content_type: str
    revision: int
    source_revision_id: str | None
    items: tuple[ReferenceDraftItem, ...]
    coverage: dict[str, Any] | None
    impact: tuple[dict[str, Any], ...]
    updated_at: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> PipelineReferenceDraft:
        data = _mapping(raw, "pipeline reference draft")
        _strict(
            data,
            {
                "schema_version",
                "recording_id",
                "content_type",
                "revision",
                "source_revision_id",
                "items",
                "coverage",
                "impact",
                "updated_at",
            },
            "pipeline reference draft",
        )
        if data["schema_version"] != PIPELINE_REFERENCE_DRAFT_SCHEMA_VERSION:
            raise PipelineReferenceContractError(
                "pipeline reference draft has an unsupported schema"
            )
        raw_items = data["items"]
        if not isinstance(raw_items, list):
            raise PipelineReferenceContractError("pipeline reference draft.items must be a list")
        items = tuple(
            ReferenceDraftItem.from_mapping(item, f"items[{index}]")
            for index, item in enumerate(raw_items)
        )
        identifiers = [item.item_id for item in items]
        if len(identifiers) != len(set(identifiers)):
            raise PipelineReferenceContractError("pipeline reference draft item IDs must be unique")
        coverage = data["coverage"]
        if coverage is not None:
            coverage = _mapping(coverage, "pipeline reference draft.coverage")
            _validate_json(coverage, "pipeline reference draft.coverage")
            coverage = json.loads(canonical_json_bytes(coverage).decode("utf-8"))
        raw_impact = data["impact"]
        if not isinstance(raw_impact, list):
            raise PipelineReferenceContractError("pipeline reference draft.impact must be a list")
        impact: list[dict[str, Any]] = []
        for index, raw_entry in enumerate(raw_impact):
            entry = _mapping(raw_entry, f"pipeline reference draft.impact[{index}]")
            _strict(
                entry,
                {
                    "schema_version",
                    "source_content_type",
                    "source_item_id",
                    "downstream_content_type",
                    "affected_item_ids",
                    "reason",
                    "re_review_required",
                },
                f"pipeline reference draft.impact[{index}]",
            )
            if entry["schema_version"] != PIPELINE_REFERENCE_IMPACT_SCHEMA_VERSION:
                raise PipelineReferenceContractError(
                    "pipeline reference draft.impact has an unsupported schema"
                )
            if not isinstance(entry["re_review_required"], bool):
                raise PipelineReferenceContractError(
                    f"pipeline reference draft.impact[{index}].re_review_required must be boolean"
                )
            affected_item_ids = _identifier_list(
                entry["affected_item_ids"],
                f"pipeline reference draft.impact[{index}].affected_item_ids",
            )
            impact.append(
                {
                    "schema_version": PIPELINE_REFERENCE_IMPACT_SCHEMA_VERSION,
                    "source_content_type": _content_type(entry["source_content_type"]),
                    "source_item_id": _identifier(
                        entry["source_item_id"],
                        f"pipeline reference draft.impact[{index}].source_item_id",
                    ),
                    "downstream_content_type": _content_type(entry["downstream_content_type"]),
                    "affected_item_ids": list(affected_item_ids),
                    "reason": _text(
                        entry["reason"], f"pipeline reference draft.impact[{index}].reason"
                    ),
                    "re_review_required": entry["re_review_required"],
                }
            )
        return cls(
            recording_id=_identifier(data["recording_id"], "recording_id"),
            content_type=_content_type(data["content_type"]),
            revision=_non_negative_int(data["revision"], "revision"),
            source_revision_id=_optional_identifier(
                data["source_revision_id"], "source_revision_id"
            ),
            items=items,
            coverage=coverage,
            impact=tuple(impact),
            updated_at=_utc_timestamp(data["updated_at"], "updated_at"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": PIPELINE_REFERENCE_DRAFT_SCHEMA_VERSION,
            "recording_id": self.recording_id,
            "content_type": self.content_type,
            "revision": self.revision,
            "source_revision_id": self.source_revision_id,
            "items": [item.to_mapping() for item in self.items],
            "coverage": self.coverage,
            "impact": list(self.impact),
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class PipelineReferenceState:
    """The mutable pointer for one maintained reference."""

    recording_id: str
    content_type: str
    draft_revision: int
    draft_state: str
    source_revision_id: str | None
    selected_completed_revision_id: str | None
    updated_at: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> PipelineReferenceState:
        data = _mapping(raw, "pipeline reference state")
        _strict(
            data,
            {
                "schema_version",
                "recording_id",
                "content_type",
                "draft_revision",
                "draft_state",
                "source_revision_id",
                "selected_completed_revision_id",
                "updated_at",
            },
            "pipeline reference state",
        )
        if data["schema_version"] != PIPELINE_REFERENCE_STATE_SCHEMA_VERSION:
            raise PipelineReferenceContractError(
                "pipeline reference state has an unsupported schema"
            )
        draft_state = _text(data["draft_state"], "draft_state")
        if draft_state not in PIPELINE_REFERENCE_DRAFT_STATES:
            raise PipelineReferenceContractError("draft_state is unsupported")
        return cls(
            recording_id=_identifier(data["recording_id"], "recording_id"),
            content_type=_content_type(data["content_type"]),
            draft_revision=_non_negative_int(data["draft_revision"], "draft_revision"),
            draft_state=draft_state,
            source_revision_id=_optional_identifier(
                data["source_revision_id"], "source_revision_id"
            ),
            selected_completed_revision_id=_optional_identifier(
                data["selected_completed_revision_id"], "selected_completed_revision_id"
            ),
            updated_at=_utc_timestamp(data["updated_at"], "updated_at"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": PIPELINE_REFERENCE_STATE_SCHEMA_VERSION,
            "recording_id": self.recording_id,
            "content_type": self.content_type,
            "draft_revision": self.draft_revision,
            "draft_state": self.draft_state,
            "source_revision_id": self.source_revision_id,
            "selected_completed_revision_id": self.selected_completed_revision_id,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class PipelineReferenceOperation:
    """One optimistic draft operation."""

    operation: str
    item_id: str | None = None
    item: dict[str, Any] | None = None
    decision: str | None = None
    source_revision_id: str | None = None

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "operation"
    ) -> PipelineReferenceOperation:
        data = _mapping(raw, context)
        operation = _text(data.get("operation"), f"{context}.operation")
        if operation not in PIPELINE_REFERENCE_OPERATIONS:
            raise PipelineReferenceContractError(f"{context}.operation is unsupported")
        if operation in {"accept", "reject", "correct"}:
            expected = (
                {"operation", "item_id", "item"}
                if operation == "correct"
                else {"operation", "item_id"}
            )
            _strict(data, expected, context)
            item_id = _identifier(data["item_id"], f"{context}.item_id")
            item = None
            if operation == "correct":
                item_value = _mapping(data["item"], f"{context}.item")
                _validate_json(item_value, f"{context}.item")
                item = json.loads(canonical_json_bytes(item_value).decode("utf-8"))
            return cls(operation=operation, item_id=item_id, item=item)
        if operation in {
            "accept_frame_suggestions",
            "set_frame_empty",
            "set_frame_unusable",
        }:
            _strict(data, {"operation", "item_id"}, context)
            return cls(
                operation=operation,
                item_id=_identifier(data["item_id"], f"{context}.item_id"),
            )
        if operation == "set_frame_review":
            _strict(data, {"operation", "item_id", "item"}, context)
            item_value = _mapping(data["item"], f"{context}.item")
            _validate_json(item_value, f"{context}.item")
            return cls(
                operation=operation,
                item_id=_identifier(data["item_id"], f"{context}.item_id"),
                item=json.loads(canonical_json_bytes(item_value).decode("utf-8")),
            )
        if operation == "decide":
            _strict(data, {"operation", "item_id", "decision"}, context)
            item_id = _identifier(data["item_id"], f"{context}.item_id")
            decision = _text(data["decision"], f"{context}.decision")
            if decision not in PIPELINE_REFERENCE_DECISIONS:
                raise PipelineReferenceContractError(f"{context}.decision is unsupported")
            return cls(operation=operation, item_id=item_id, decision=decision)
        if operation == "rebase":
            _strict(data, {"operation", "source_revision_id"}, context)
            return cls(
                operation=operation,
                source_revision_id=_identifier(
                    data["source_revision_id"], f"{context}.source_revision_id"
                ),
            )
        _strict(data, {"operation", "item"}, context)
        item_value = _mapping(data["item"], f"{context}.item")
        _validate_json(item_value, f"{context}.item")
        return cls(
            operation=operation,
            item=json.loads(canonical_json_bytes(item_value).decode("utf-8")),
        )

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {"operation": self.operation}
        if self.item_id is not None:
            value["item_id"] = self.item_id
        if self.item is not None:
            value["item"] = self.item
        if self.decision is not None:
            value["decision"] = self.decision
        if self.source_revision_id is not None:
            value["source_revision_id"] = self.source_revision_id
        return value


def canonical_reference_state_bytes(value: PipelineReferenceState | Mapping[str, Any]) -> bytes:
    state = (
        value
        if isinstance(value, PipelineReferenceState)
        else PipelineReferenceState.from_mapping(value)
    )
    return canonical_json_bytes(state.to_mapping())


def parse_reference_state_bytes(raw: bytes) -> PipelineReferenceState:
    return PipelineReferenceState.from_mapping(_parse_json(raw, "pipeline reference state"))


def canonical_reference_draft_bytes(value: PipelineReferenceDraft | Mapping[str, Any]) -> bytes:
    draft = (
        value
        if isinstance(value, PipelineReferenceDraft)
        else PipelineReferenceDraft.from_mapping(value)
    )
    return canonical_json_bytes(draft.to_mapping())


def parse_reference_draft_bytes(raw: bytes) -> PipelineReferenceDraft:
    return PipelineReferenceDraft.from_mapping(_parse_json(raw, "pipeline reference draft"))


__all__ = [
    "PIPELINE_REFERENCE_CONTENT_TYPES",
    "PIPELINE_REFERENCE_COVERAGE_SCHEMA_VERSION",
    "PIPELINE_REFERENCE_DRAFT_SCHEMA_VERSION",
    "PIPELINE_REFERENCE_DRAFT_STATES",
    "PIPELINE_REFERENCE_IMPACT_SCHEMA_VERSION",
    "PIPELINE_REFERENCE_ITEM_STATES",
    "PIPELINE_REFERENCE_OPERATIONS",
    "PIPELINE_REFERENCE_DECISIONS",
    "PIPELINE_REFERENCE_STATE_SCHEMA_VERSION",
    "PipelineReferenceContractError",
    "PipelineReferenceDraft",
    "PipelineReferenceOperation",
    "PipelineReferenceState",
    "ReferenceDraftItem",
    "canonical_json_bytes",
    "canonical_reference_draft_bytes",
    "canonical_reference_state_bytes",
    "parse_reference_draft_bytes",
    "parse_reference_state_bytes",
]
