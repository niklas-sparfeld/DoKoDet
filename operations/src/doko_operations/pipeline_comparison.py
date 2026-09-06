"""Deterministic recording-pipeline comparison contracts.

The comparison is a pure domain result.  The backend resolves retained revisions and passes their
validated event content to this module.  No comparison result is stored.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from table_evidence_analyzer.pipeline_data import (
    DetectorBoxGeometry,
    PipelineGeometry,
    ReviewedVisibleRegionGeometry,
    VisibleCardData,
    VisibleCardOutcome,
    VisualIdentityData,
    VisualIdentityOutcome,
)

from .pipeline_data import EventData, EventRecord, canonical_json_bytes

PIPELINE_COMPARISON_REQUEST_SCHEMA_VERSION = "pipeline-comparison-request/v1"
PIPELINE_COMPARISON_SCHEMA_VERSION = "pipeline-comparison/v1"
PIPELINE_COMPARISON_ALGORITHM_VERSION = "event-matching/v1"

ComparisonMode = Literal["paired_processor", "upstream_experiment"]
ComparisonOutcome = Literal[
    "match",
    "miss",
    "extra",
    "disagreement",
    "failure",
    "empty",
    "not_reviewed",
    "unpaired_input",
]
ComparisonSideName = Literal["left", "right"]
ComparisonPolicyKind = Literal[
    "event_timing",
    "visible_card_geometry",
    "visual_identity_geometry",
]
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_QUALIFIED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


class PipelineComparisonContractError(ValueError):
    """Raised when a comparison contract is invalid."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise PipelineComparisonContractError(f"{field} must be an object")
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
        raise PipelineComparisonContractError(f"{field} has invalid fields ({'; '.join(details)})")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PipelineComparisonContractError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or _IDENTIFIER.fullmatch(result) is None:
        raise PipelineComparisonContractError(f"{field} must be a safe identifier")
    return result


def _qualified(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or _QUALIFIED.fullmatch(result) is None:
        raise PipelineComparisonContractError(f"{field} must be a qualified identifier")
    return result


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PipelineComparisonContractError(f"{field} must be a non-negative integer")
    return value


def _positive_int(value: Any, field: str) -> int:
    result = _non_negative_int(value, field)
    if result == 0:
        raise PipelineComparisonContractError(f"{field} must be positive")
    return result


def _finite_number(value: Any, field: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PipelineComparisonContractError(f"{field} must be a finite number or null")
    if not math.isfinite(float(value)):
        raise PipelineComparisonContractError(f"{field} must be a finite number or null")
    return value


def _json_value(value: Any, field: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PipelineComparisonContractError(f"{field} must contain finite JSON values")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise PipelineComparisonContractError(f"{field} object keys must be strings")
        return {key: _json_value(child, f"{field}.{key}") for key, child in value.items()}
    if isinstance(value, list):
        return [_json_value(child, f"{field}[{index}]") for index, child in enumerate(value)]
    raise PipelineComparisonContractError(f"{field} must contain JSON-compatible values")


def _identifier_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PipelineComparisonContractError(f"{field} must be a list")
    result = tuple(_identifier(item, f"{field}[{index}]") for index, item in enumerate(value))
    if len(result) != len(set(result)):
        raise PipelineComparisonContractError(f"{field} must contain unique identifiers")
    return result


@dataclass(frozen=True, slots=True)
class EventMatchingPolicy:
    """The explicit timing or geometry policy used to compare revisions."""

    policy_id: str
    anchor: Literal["start_us", "end_us", "midpoint_us"] | None = None
    tolerance_us: int | None = None
    event_type: str | None = None
    iou_threshold: float | None = None
    derived_box_policy: Literal["bounding_box"] | None = None
    kind: ComparisonPolicyKind | None = None

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
        *,
        geometry_kind: ComparisonPolicyKind | None = None,
    ) -> EventMatchingPolicy:
        data = _mapping(raw, "matching_policy")
        allowed = {
            "policy_id",
            "anchor",
            "tolerance_us",
            "event_type",
            "iou_threshold",
            "derived_box_policy",
            "kind",
        }
        unknown = set(data) - allowed
        if unknown:
            raise PipelineComparisonContractError(
                "matching_policy has unknown fields: " + ", ".join(sorted(unknown))
            )
        if "policy_id" not in data:
            raise PipelineComparisonContractError("matching_policy has missing fields: policy_id")
        policy_id = _qualified(data["policy_id"], "matching_policy.policy_id")
        kind = data.get("kind")
        if kind is not None and kind not in {
            "event_timing",
            "visible_card_geometry",
            "visual_identity_geometry",
        }:
            raise PipelineComparisonContractError("matching_policy.kind is unsupported")
        has_event_fields = any(
            data.get(field) is not None for field in ("anchor", "tolerance_us", "event_type")
        )
        has_geometry_fields = any(
            data.get(field) is not None for field in ("iou_threshold", "derived_box_policy")
        )
        if has_event_fields and has_geometry_fields:
            raise PipelineComparisonContractError(
                "matching_policy cannot combine timing and geometry fields"
            )
        if has_event_fields or kind == "event_timing":
            if kind not in {None, "event_timing"}:
                raise PipelineComparisonContractError(
                    "matching_policy.kind does not match timing fields"
                )
            if "anchor" not in data or "tolerance_us" not in data:
                raise PipelineComparisonContractError(
                    "matching_policy timing fields are incomplete"
                )
            anchor = _text(data["anchor"], "matching_policy.anchor")
            if anchor not in {"start_us", "end_us", "midpoint_us"}:
                raise PipelineComparisonContractError("matching_policy.anchor is unsupported")
            return cls(
                policy_id=policy_id,
                anchor=anchor,  # type: ignore[arg-type]
                tolerance_us=_non_negative_int(
                    data["tolerance_us"], "matching_policy.tolerance_us"
                ),
                event_type=(
                    None
                    if data.get("event_type") is None
                    else _qualified(data["event_type"], "matching_policy.event_type")
                ),
                kind="event_timing",
            )
        if not has_geometry_fields:
            raise PipelineComparisonContractError("matching_policy needs timing or geometry fields")
        if kind == "event_timing":
            raise PipelineComparisonContractError("event timing policy fields are incomplete")
        if "iou_threshold" not in data or "derived_box_policy" not in data:
            raise PipelineComparisonContractError("matching_policy geometry fields are incomplete")
        threshold = _finite_number(data["iou_threshold"], "matching_policy.iou_threshold")
        if threshold is None or not 0.0 < float(threshold) <= 1.0:
            raise PipelineComparisonContractError(
                "matching_policy.iou_threshold must be greater than 0 and at most 1"
            )
        if data["derived_box_policy"] != "bounding_box":
            raise PipelineComparisonContractError(
                "matching_policy.derived_box_policy is unsupported"
            )
        if kind is None:
            kind = geometry_kind or "visible_card_geometry"
        if kind not in {"visible_card_geometry", "visual_identity_geometry"}:
            raise PipelineComparisonContractError(
                "matching_policy.kind does not match geometry fields"
            )
        return cls(
            policy_id=policy_id,
            iou_threshold=float(threshold),
            derived_box_policy="bounding_box",
            kind=kind,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "anchor": self.anchor,
            "tolerance_us": self.tolerance_us,
            "event_type": self.event_type,
            "iou_threshold": self.iou_threshold,
            "derived_box_policy": self.derived_box_policy,
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class PipelineComparisonRequest:
    """The immutable selection of two runs, one reference, and one policy."""

    recording_id: str
    content_type: Literal["events", "visible_cards", "visual_identities"]
    left_run_id: str
    right_run_id: str
    reference_revision_id: str
    matching_policy: EventMatchingPolicy

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> PipelineComparisonRequest:
        data = _mapping(raw, "pipeline comparison request")
        _strict(
            data,
            {
                "schema_version",
                "recording_id",
                "content_type",
                "left_run_id",
                "right_run_id",
                "reference_revision_id",
                "matching_policy",
            },
            "pipeline comparison request",
        )
        if data["schema_version"] != PIPELINE_COMPARISON_REQUEST_SCHEMA_VERSION:
            raise PipelineComparisonContractError(
                "pipeline comparison request has an unsupported schema"
            )
        if data["content_type"] not in {"events", "visible_cards", "visual_identities"}:
            raise PipelineComparisonContractError("pipeline comparison content_type is unsupported")
        content_type = data["content_type"]
        expected_kind = {
            "events": "event_timing",
            "visible_cards": "visible_card_geometry",
            "visual_identities": "visual_identity_geometry",
        }[content_type]
        matching_policy = EventMatchingPolicy.from_mapping(
            _mapping(data["matching_policy"], "matching_policy"),
            geometry_kind=expected_kind,
        )
        if matching_policy.kind != expected_kind:
            raise PipelineComparisonContractError(
                f"matching_policy.kind must be {expected_kind} for {content_type}"
            )
        return cls(
            recording_id=_identifier(data["recording_id"], "recording_id"),
            content_type=content_type,  # type: ignore[arg-type]
            left_run_id=_identifier(data["left_run_id"], "left_run_id"),
            right_run_id=_identifier(data["right_run_id"], "right_run_id"),
            reference_revision_id=_identifier(
                data["reference_revision_id"], "reference_revision_id"
            ),
            matching_policy=matching_policy,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": PIPELINE_COMPARISON_REQUEST_SCHEMA_VERSION,
            "recording_id": self.recording_id,
            "content_type": self.content_type,
            "left_run_id": self.left_run_id,
            "right_run_id": self.right_run_id,
            "reference_revision_id": self.reference_revision_id,
            "matching_policy": self.matching_policy.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class PipelineComparisonScope:
    """Normalized temporal and exact-frame coverage used by a comparison."""

    reviewed: tuple[tuple[int, int], ...]
    common_covered: tuple[tuple[int, int], ...]
    left_only: tuple[tuple[int, int], ...]
    right_only: tuple[tuple[int, int], ...]
    reviewed_frame_identities: tuple[dict[str, Any], ...] = ()
    common_frame_identities: tuple[dict[str, Any], ...] = ()
    left_only_frame_identities: tuple[dict[str, Any], ...] = ()
    right_only_frame_identities: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> PipelineComparisonScope:
        data = _mapping(raw, "scope")
        _strict(
            data,
            {
                "reviewed",
                "common_covered",
                "left_only",
                "right_only",
                "reviewed_frame_identities",
                "common_frame_identities",
                "left_only_frame_identities",
                "right_only_frame_identities",
            },
            "scope",
        )
        return cls(
            reviewed=_parse_intervals(data["reviewed"], "scope.reviewed"),
            common_covered=_parse_intervals(data["common_covered"], "scope.common_covered"),
            left_only=_parse_intervals(data["left_only"], "scope.left_only"),
            right_only=_parse_intervals(data["right_only"], "scope.right_only"),
            reviewed_frame_identities=_parse_frame_identities(
                data["reviewed_frame_identities"], "scope.reviewed_frame_identities"
            ),
            common_frame_identities=_parse_frame_identities(
                data["common_frame_identities"], "scope.common_frame_identities"
            ),
            left_only_frame_identities=_parse_frame_identities(
                data["left_only_frame_identities"], "scope.left_only_frame_identities"
            ),
            right_only_frame_identities=_parse_frame_identities(
                data["right_only_frame_identities"], "scope.right_only_frame_identities"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "reviewed": _interval_mappings(self.reviewed),
            "common_covered": _interval_mappings(self.common_covered),
            "left_only": _interval_mappings(self.left_only),
            "right_only": _interval_mappings(self.right_only),
            "reviewed_frame_identities": list(self.reviewed_frame_identities),
            "common_frame_identities": list(self.common_frame_identities),
            "left_only_frame_identities": list(self.left_only_frame_identities),
            "right_only_frame_identities": list(self.right_only_frame_identities),
        }


def _parse_frame_identities(value: Any, field: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise PipelineComparisonContractError(f"{field} must be a list")
    result = tuple(_object(item, f"{field}[{index}]") for index, item in enumerate(value))
    keys = [canonical_json_bytes(item) for item in result]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise PipelineComparisonContractError(
            f"{field} must contain unique identities in canonical order"
        )
    return result


def _parse_intervals(value: Any, field: str) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, list):
        raise PipelineComparisonContractError(f"{field} must be a list")
    intervals: list[tuple[int, int]] = []
    for index, raw in enumerate(value):
        data = _mapping(raw, f"{field}[{index}]")
        _strict(data, {"start_us", "end_us"}, f"{field}[{index}]")
        start = _non_negative_int(data["start_us"], f"{field}[{index}].start_us")
        end = _non_negative_int(data["end_us"], f"{field}[{index}].end_us")
        if end <= start:
            raise PipelineComparisonContractError(f"{field}[{index}] must have positive length")
        intervals.append((start, end))
    return _merge_intervals(intervals)


def _interval_mappings(intervals: Sequence[tuple[int, int]]) -> list[dict[str, int]]:
    return [{"start_us": start, "end_us": end} for start, end in intervals]


def _merge_intervals(intervals: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    result: list[list[int]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return tuple((start, end) for start, end in result)


def _intersection(
    first: Sequence[tuple[int, int]], second: Sequence[tuple[int, int]]
) -> tuple[tuple[int, int], ...]:
    result: list[tuple[int, int]] = []
    for first_start, first_end in first:
        for second_start, second_end in second:
            start = max(first_start, second_start)
            end = min(first_end, second_end)
            if start < end:
                result.append((start, end))
    return _merge_intervals(result)


def _difference(
    first: Sequence[tuple[int, int]], second: Sequence[tuple[int, int]]
) -> tuple[tuple[int, int], ...]:
    remaining = list(first)
    for cut_start, cut_end in second:
        next_remaining: list[tuple[int, int]] = []
        for start, end in remaining:
            if cut_end <= start or cut_start >= end:
                next_remaining.append((start, end))
                continue
            if start < cut_start:
                next_remaining.append((start, cut_start))
            if cut_end < end:
                next_remaining.append((cut_end, end))
        remaining = next_remaining
    return _merge_intervals(remaining)


def normalize_event_coverage(
    coverage: Mapping[str, Any], *, duration_us: int
) -> tuple[tuple[int, int], ...]:
    """Normalize one event revision or reference coverage declaration."""

    data = _mapping(coverage, "coverage")
    kind = data.get("kind")
    if kind in {"full-recording", "full_recording"}:
        return ((0, duration_us),)
    if kind not in {"processed", "event_intervals", "intervals"}:
        raise PipelineComparisonContractError("coverage.kind does not describe event coverage")
    raw_intervals = data.get("intervals")
    if not isinstance(raw_intervals, list):
        raise PipelineComparisonContractError("coverage.intervals must be a list")
    intervals = _parse_intervals(raw_intervals, "coverage.intervals")
    if any(end > duration_us for _, end in intervals):
        raise PipelineComparisonContractError("coverage interval is outside the source video")
    return intervals


def build_comparison_scope(
    *,
    reviewed: tuple[tuple[int, int], ...],
    left_coverage: tuple[tuple[int, int], ...],
    right_coverage: tuple[tuple[int, int], ...],
) -> PipelineComparisonScope:
    """Build normalized reviewed and side evidence scope."""

    common = _intersection(left_coverage, right_coverage)
    return PipelineComparisonScope(
        reviewed=_merge_intervals(reviewed),
        common_covered=common,
        left_only=_difference(left_coverage, right_coverage),
        right_only=_difference(right_coverage, left_coverage),
    )


def build_frame_comparison_scope(
    *,
    reviewed: Sequence[Mapping[str, Any]],
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
) -> PipelineComparisonScope:
    """Build normalized scope for exact resolved frames."""

    normalized = {
        name: _sorted_unique_frame_identities(value, name)
        for name, value in (("reviewed", reviewed), ("left", left), ("right", right))
    }
    left_keys = {_frame_identity_key(frame) for frame in normalized["left"]}
    right_keys = {_frame_identity_key(frame) for frame in normalized["right"]}
    return PipelineComparisonScope(
        reviewed=(),
        common_covered=(),
        left_only=(),
        right_only=(),
        reviewed_frame_identities=normalized["reviewed"],
        common_frame_identities=tuple(
            frame for frame in normalized["left"] if _frame_identity_key(frame) in right_keys
        ),
        left_only_frame_identities=tuple(
            frame for frame in normalized["left"] if _frame_identity_key(frame) not in right_keys
        ),
        right_only_frame_identities=tuple(
            frame for frame in normalized["right"] if _frame_identity_key(frame) not in left_keys
        ),
    )


def _sorted_unique_frame_identities(
    frames: Sequence[Mapping[str, Any]], field: str
) -> tuple[dict[str, Any], ...]:
    normalized = tuple(_object(frame, f"{field}[{index}]") for index, frame in enumerate(frames))
    unique = {_frame_identity_key(frame): frame for frame in normalized}
    return tuple(unique[key] for key in sorted(unique))


def _frame_identity_key(frame: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(frame)


@dataclass(frozen=True, slots=True)
class PipelineComparisonCounts:
    """Counts for one compared run inside the reviewed scope."""

    reference_events: int
    run_events: int
    matches: int
    misses: int
    extras: int
    not_reviewed: int
    unpaired_input: int
    failures: int = 0

    def to_mapping(self) -> dict[str, int]:
        return {
            "reference_events": self.reference_events,
            "run_events": self.run_events,
            "matches": self.matches,
            "misses": self.misses,
            "extras": self.extras,
            "not_reviewed": self.not_reviewed,
            "unpaired_input": self.unpaired_input,
            "failures": self.failures,
        }


@dataclass(frozen=True, slots=True)
class PipelineComparisonMetrics:
    """Quality metrics calculated only from reviewed and covered events."""

    precision: float | None
    recall: float | None
    f1: float | None
    mean_error_us: float | None
    max_error_us: int | None

    def to_mapping(self) -> dict[str, float | int | None]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "mean_error_us": self.mean_error_us,
            "max_error_us": self.max_error_us,
        }


@dataclass(frozen=True, slots=True)
class PipelineComparisonDelta:
    """Right-minus-left quality metrics for a paired comparison."""

    precision: float | None
    recall: float | None
    f1: float | None
    mean_error_us: float | None
    max_error_us: int | None

    def to_mapping(self) -> dict[str, float | int | None]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "mean_error_us": self.mean_error_us,
            "max_error_us": self.max_error_us,
        }


@dataclass(frozen=True, slots=True)
class PipelineComparisonItem:
    """One stable source-ordered event outcome for one run side."""

    item_id: str
    side: ComparisonSideName
    outcome: ComparisonOutcome
    source_time_us: int | None
    event_type: str
    reference_event_id: str | None
    run_event_id: str | None
    reference_event: dict[str, Any] | None
    run_event: dict[str, Any] | None
    delta_us: int | None
    source_links: dict[str, str]
    frame_identity: dict[str, Any] | None = None
    reference_card_id: str | None = None
    run_card_id: str | None = None
    reference_card: dict[str, Any] | None = None
    run_card: dict[str, Any] | None = None
    iou: float | None = None
    reference_identity: str | None = None
    run_identity: str | None = None
    reference_candidates: tuple[dict[str, Any], ...] | None = None
    run_candidates: tuple[dict[str, Any], ...] | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "side": self.side,
            "outcome": self.outcome,
            "source_time_us": self.source_time_us,
            "event_type": self.event_type,
            "reference_event_id": self.reference_event_id,
            "run_event_id": self.run_event_id,
            "reference_event": self.reference_event,
            "run_event": self.run_event,
            "delta_us": self.delta_us,
            "source_links": self.source_links,
            "frame_identity": self.frame_identity,
            "reference_card_id": self.reference_card_id,
            "run_card_id": self.run_card_id,
            "reference_card": self.reference_card,
            "run_card": self.run_card,
            "iou": self.iou,
            "reference_identity": self.reference_identity,
            "run_identity": self.run_identity,
            "reference_candidates": (
                None if self.reference_candidates is None else list(self.reference_candidates)
            ),
            "run_candidates": None if self.run_candidates is None else list(self.run_candidates),
        }


@dataclass(frozen=True, slots=True)
class PipelineComparisonSide:
    """Exact retained run and output revision identity."""

    run_id: str
    revision_id: str
    status: Literal["complete", "partial"]
    input_revision_ids: tuple[str, ...]
    content_sha256: str
    implementation: dict[str, Any]
    model: dict[str, Any] | None
    configuration: dict[str, Any]
    extraction_policy: dict[str, Any]
    failure: dict[str, Any] | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "revision_id": self.revision_id,
            "status": self.status,
            "input_revision_ids": list(self.input_revision_ids),
            "content_sha256": self.content_sha256,
            "implementation": self.implementation,
            "model": self.model,
            "configuration": self.configuration,
            "extraction_policy": self.extraction_policy,
            "failure": self.failure,
        }


@dataclass(frozen=True, slots=True)
class PipelineComparisonReference:
    """Exact completed maintained reference identity."""

    revision_id: str
    input_revision_ids: tuple[str, ...]
    content_sha256: str
    origin: Literal["manual", "corrected"]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "input_revision_ids": list(self.input_revision_ids),
            "content_sha256": self.content_sha256,
            "origin": self.origin,
        }


@dataclass(frozen=True, slots=True)
class PipelineComparison:
    """The complete deterministic event comparison response."""

    comparison_id: str
    recording_id: str
    content_type: Literal["events", "visible_cards", "visual_identities"]
    mode: ComparisonMode
    algorithm_version: str
    left: PipelineComparisonSide
    right: PipelineComparisonSide
    reference: PipelineComparisonReference
    scope: PipelineComparisonScope
    matching_policy: EventMatchingPolicy
    counts: dict[str, PipelineComparisonCounts]
    metrics: dict[str, PipelineComparisonMetrics]
    paired_delta: PipelineComparisonDelta | None
    items: tuple[PipelineComparisonItem, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": PIPELINE_COMPARISON_SCHEMA_VERSION,
            "comparison_id": self.comparison_id,
            "recording_id": self.recording_id,
            "content_type": self.content_type,
            "mode": self.mode,
            "algorithm_version": self.algorithm_version,
            "left": self.left.to_mapping(),
            "right": self.right.to_mapping(),
            "reference": self.reference.to_mapping(),
            "scope": self.scope.to_mapping(),
            "matching_policy": self.matching_policy.to_mapping(),
            "counts": {side: value.to_mapping() for side, value in sorted(self.counts.items())},
            "metrics": {side: value.to_mapping() for side, value in sorted(self.metrics.items())},
            "paired_delta": None if self.paired_delta is None else self.paired_delta.to_mapping(),
            "items": [item.to_mapping() for item in self.items],
        }


def canonical_pipeline_comparison_request_bytes(
    value: PipelineComparisonRequest | Mapping[str, Any],
) -> bytes:
    request = (
        value
        if isinstance(value, PipelineComparisonRequest)
        else PipelineComparisonRequest.from_mapping(value)
    )
    return canonical_json_bytes(request.to_mapping())


def canonical_pipeline_comparison_bytes(value: PipelineComparison | Mapping[str, Any]) -> bytes:
    comparison = value if isinstance(value, PipelineComparison) else _comparison_from_mapping(value)
    return canonical_json_bytes(comparison.to_mapping())


def parse_pipeline_comparison_request_bytes(raw: bytes) -> PipelineComparisonRequest:
    return PipelineComparisonRequest.from_mapping(_parse_json(raw, "pipeline comparison request"))


def parse_pipeline_comparison_bytes(raw: bytes) -> PipelineComparison:
    return _comparison_from_mapping(_parse_json(raw, "pipeline comparison"))


def _parse_json(raw: bytes, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, bytes):
        raise TypeError(f"{field} must be bytes")

    def reject_constant(value: str) -> None:
        raise PipelineComparisonContractError(f"{field} contains a non-finite JSON number: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PipelineComparisonContractError(f"{field} contains a duplicate field: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except PipelineComparisonContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineComparisonContractError(f"{field} must be valid UTF-8 JSON") from error
    return _mapping(value, field)


def _comparison_from_mapping(raw: Mapping[str, Any]) -> PipelineComparison:
    """Validate a generated comparison response without changing its bytes."""

    data = _mapping(raw, "pipeline comparison")
    _strict(
        data,
        {
            "schema_version",
            "comparison_id",
            "recording_id",
            "content_type",
            "mode",
            "algorithm_version",
            "left",
            "right",
            "reference",
            "scope",
            "matching_policy",
            "counts",
            "metrics",
            "paired_delta",
            "items",
        },
        "pipeline comparison",
    )
    if data["schema_version"] != PIPELINE_COMPARISON_SCHEMA_VERSION:
        raise PipelineComparisonContractError("pipeline comparison has an unsupported schema")
    if data["content_type"] not in {"events", "visible_cards", "visual_identities"}:
        raise PipelineComparisonContractError("pipeline comparison content_type is unsupported")
    expected_policy_kind = {
        "events": "event_timing",
        "visible_cards": "visible_card_geometry",
        "visual_identities": "visual_identity_geometry",
    }[data["content_type"]]
    parsed_policy = EventMatchingPolicy.from_mapping(
        data["matching_policy"], geometry_kind=expected_policy_kind
    )
    if parsed_policy.kind != expected_policy_kind:
        raise PipelineComparisonContractError(
            f"matching_policy.kind must be {expected_policy_kind} for {data['content_type']}"
        )
    mode = data["mode"]
    if mode not in {"paired_processor", "upstream_experiment"}:
        raise PipelineComparisonContractError("pipeline comparison mode is unsupported")
    counts_raw = _mapping(data["counts"], "counts")
    metrics_raw = _mapping(data["metrics"], "metrics")
    if set(counts_raw) != {"left", "right"} or set(metrics_raw) != {"left", "right"}:
        raise PipelineComparisonContractError("counts and metrics must contain left and right")
    counts = {side: _counts_from_mapping(counts_raw[side], f"counts.{side}") for side in counts_raw}
    metrics = {
        side: _metrics_from_mapping(metrics_raw[side], f"metrics.{side}") for side in metrics_raw
    }
    paired_delta = data["paired_delta"]
    parsed_delta = None if paired_delta is None else _delta_from_mapping(paired_delta)
    if mode == "upstream_experiment" and parsed_delta is not None:
        raise PipelineComparisonContractError("upstream experiments cannot have a paired delta")
    raw_items = data["items"]
    if not isinstance(raw_items, list):
        raise PipelineComparisonContractError("items must be a list")
    items = tuple(
        _item_from_mapping(item, f"items[{index}]") for index, item in enumerate(raw_items)
    )
    if len({item.item_id for item in items}) != len(items):
        raise PipelineComparisonContractError("comparison item IDs must be unique")
    return PipelineComparison(
        comparison_id=_identifier(data["comparison_id"], "comparison_id"),
        recording_id=_identifier(data["recording_id"], "recording_id"),
        content_type=data["content_type"],  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        algorithm_version=_qualified(data["algorithm_version"], "algorithm_version"),
        left=_side_from_mapping(data["left"], "left"),
        right=_side_from_mapping(data["right"], "right"),
        reference=_reference_from_mapping(data["reference"]),
        scope=PipelineComparisonScope.from_mapping(data["scope"]),
        matching_policy=parsed_policy,
        counts=counts,
        metrics=metrics,
        paired_delta=parsed_delta,
        items=items,
    )


def _counts_from_mapping(raw: Any, field: str) -> PipelineComparisonCounts:
    data = _mapping(raw, field)
    _strict(
        data,
        {
            "reference_events",
            "run_events",
            "matches",
            "misses",
            "extras",
            "not_reviewed",
            "unpaired_input",
            "failures",
        },
        field,
    )
    values = {key: _non_negative_int(value, f"{field}.{key}") for key, value in data.items()}
    return PipelineComparisonCounts(**values)


def _metrics_from_mapping(raw: Any, field: str) -> PipelineComparisonMetrics:
    data = _mapping(raw, field)
    _strict(data, {"precision", "recall", "f1", "mean_error_us", "max_error_us"}, field)
    max_error = data["max_error_us"]
    return PipelineComparisonMetrics(
        precision=_finite_number(data["precision"], f"{field}.precision"),
        recall=_finite_number(data["recall"], f"{field}.recall"),
        f1=_finite_number(data["f1"], f"{field}.f1"),
        mean_error_us=_finite_number(data["mean_error_us"], f"{field}.mean_error_us"),
        max_error_us=None
        if max_error is None
        else _non_negative_int(max_error, f"{field}.max_error_us"),
    )


def _delta_from_mapping(raw: Any) -> PipelineComparisonDelta:
    data = _mapping(raw, "paired_delta")
    _strict(data, {"precision", "recall", "f1", "mean_error_us", "max_error_us"}, "paired_delta")
    return PipelineComparisonDelta(
        precision=_finite_number(data["precision"], "paired_delta.precision"),
        recall=_finite_number(data["recall"], "paired_delta.recall"),
        f1=_finite_number(data["f1"], "paired_delta.f1"),
        mean_error_us=_finite_number(data["mean_error_us"], "paired_delta.mean_error_us"),
        max_error_us=(
            None
            if data["max_error_us"] is None
            else _non_negative_int(data["max_error_us"], "paired_delta.max_error_us")
        ),
    )


def _side_from_mapping(raw: Any, field: str) -> PipelineComparisonSide:
    data = _mapping(raw, field)
    _strict(
        data,
        {
            "run_id",
            "revision_id",
            "status",
            "input_revision_ids",
            "content_sha256",
            "implementation",
            "model",
            "configuration",
            "extraction_policy",
            "failure",
        },
        field,
    )
    status = data["status"]
    if status not in {"complete", "partial"}:
        raise PipelineComparisonContractError(f"{field}.status is unsupported")
    return PipelineComparisonSide(
        run_id=_identifier(data["run_id"], f"{field}.run_id"),
        revision_id=_identifier(data["revision_id"], f"{field}.revision_id"),
        status=status,  # type: ignore[arg-type]
        input_revision_ids=_identifier_list(
            data["input_revision_ids"], f"{field}.input_revision_ids"
        ),
        content_sha256=_digest(data["content_sha256"], f"{field}.content_sha256"),
        implementation=_object(data["implementation"], f"{field}.implementation"),
        model=None if data["model"] is None else _object(data["model"], f"{field}.model"),
        configuration=_object(data["configuration"], f"{field}.configuration"),
        extraction_policy=_object(data["extraction_policy"], f"{field}.extraction_policy"),
        failure=None if data["failure"] is None else _object(data["failure"], f"{field}.failure"),
    )


def _reference_from_mapping(raw: Any) -> PipelineComparisonReference:
    data = _mapping(raw, "reference")
    _strict(data, {"revision_id", "input_revision_ids", "content_sha256", "origin"}, "reference")
    if data["origin"] not in {"manual", "corrected"}:
        raise PipelineComparisonContractError("reference.origin is unsupported")
    return PipelineComparisonReference(
        revision_id=_identifier(data["revision_id"], "reference.revision_id"),
        input_revision_ids=_identifier_list(
            data["input_revision_ids"], "reference.input_revision_ids"
        ),
        content_sha256=_digest(data["content_sha256"], "reference.content_sha256"),
        origin=data["origin"],  # type: ignore[arg-type]
    )


def _item_from_mapping(raw: Any, field: str) -> PipelineComparisonItem:
    data = _mapping(raw, field)
    _strict(
        data,
        {
            "item_id",
            "side",
            "outcome",
            "source_time_us",
            "event_type",
            "reference_event_id",
            "run_event_id",
            "reference_event",
            "run_event",
            "delta_us",
            "source_links",
            "frame_identity",
            "reference_card_id",
            "run_card_id",
            "reference_card",
            "run_card",
            "iou",
            "reference_identity",
            "run_identity",
            "reference_candidates",
            "run_candidates",
        },
        field,
    )
    if data["side"] not in {"left", "right"}:
        raise PipelineComparisonContractError(f"{field}.side is unsupported")
    if data["outcome"] not in {
        "match",
        "miss",
        "extra",
        "disagreement",
        "failure",
        "empty",
        "not_reviewed",
        "unpaired_input",
    }:
        raise PipelineComparisonContractError(f"{field}.outcome is unsupported")
    source_time = data["source_time_us"]
    delta = data["delta_us"]
    if source_time is not None:
        source_time = _non_negative_int(source_time, f"{field}.source_time_us")
    if delta is not None and (isinstance(delta, bool) or not isinstance(delta, int)):
        raise PipelineComparisonContractError(f"{field}.delta_us must be an integer or null")
    frame_identity = data["frame_identity"]
    if frame_identity is not None:
        frame_identity = _object(frame_identity, f"{field}.frame_identity")
    iou = data["iou"]
    if iou is not None:
        iou = _finite_number(iou, f"{field}.iou")
        if iou is None or not 0.0 <= float(iou) <= 1.0:
            raise PipelineComparisonContractError(f"{field}.iou must be in [0, 1] or null")
    reference_candidates = _optional_object_list(
        data["reference_candidates"], f"{field}.reference_candidates"
    )
    run_candidates = _optional_object_list(data["run_candidates"], f"{field}.run_candidates")
    return PipelineComparisonItem(
        item_id=_identifier(data["item_id"], f"{field}.item_id"),
        side=data["side"],  # type: ignore[arg-type]
        outcome=data["outcome"],  # type: ignore[arg-type]
        source_time_us=source_time,
        event_type=_qualified(data["event_type"], f"{field}.event_type"),
        reference_event_id=(
            None
            if data["reference_event_id"] is None
            else _identifier(data["reference_event_id"], f"{field}.reference_event_id")
        ),
        run_event_id=(
            None
            if data["run_event_id"] is None
            else _identifier(data["run_event_id"], f"{field}.run_event_id")
        ),
        reference_event=None
        if data["reference_event"] is None
        else _object(data["reference_event"], f"{field}.reference_event"),
        run_event=None
        if data["run_event"] is None
        else _object(data["run_event"], f"{field}.run_event"),
        delta_us=delta,
        source_links=_string_map(data["source_links"], f"{field}.source_links"),
        frame_identity=frame_identity,
        reference_card_id=(
            None
            if data["reference_card_id"] is None
            else _identifier(data["reference_card_id"], f"{field}.reference_card_id")
        ),
        run_card_id=(
            None
            if data["run_card_id"] is None
            else _identifier(data["run_card_id"], f"{field}.run_card_id")
        ),
        reference_card=(
            None
            if data["reference_card"] is None
            else _object(data["reference_card"], f"{field}.reference_card")
        ),
        run_card=(
            None if data["run_card"] is None else _object(data["run_card"], f"{field}.run_card")
        ),
        iou=None if iou is None else float(iou),
        reference_identity=(
            None
            if data["reference_identity"] is None
            else _qualified(data["reference_identity"], f"{field}.reference_identity")
        ),
        run_identity=(
            None
            if data["run_identity"] is None
            else _qualified(data["run_identity"], f"{field}.run_identity")
        ),
        reference_candidates=reference_candidates,
        run_candidates=run_candidates,
    )


def _object(value: Any, field: str) -> dict[str, Any]:
    data = _mapping(value, field)
    copied = _json_value(data, field)
    if not isinstance(copied, dict):  # pragma: no cover - guarded by _mapping
        raise PipelineComparisonContractError(f"{field} must be an object")
    return copied


def _string_map(value: Any, field: str) -> dict[str, str]:
    data = _mapping(value, field)
    if any(not isinstance(child, str) or not child for child in data.values()):
        raise PipelineComparisonContractError(f"{field} must map strings to non-empty strings")
    return dict(data)


def _optional_object_list(value: Any, field: str) -> tuple[dict[str, Any], ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise PipelineComparisonContractError(f"{field} must be a list or null")
    return tuple(_object(item, f"{field}[{index}]") for index, item in enumerate(value))


def _digest(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PipelineComparisonContractError(f"{field} must be a lower-case SHA-256 digest")
    return result


def event_anchor(event: EventRecord, policy: EventMatchingPolicy) -> int:
    """Return the declared source anchor for one event."""

    if policy.anchor == "start_us":
        return event.start_us
    if policy.anchor == "end_us":
        return event.end_us
    return (event.start_us + event.end_us) // 2


def match_event_records(
    predicted: Sequence[EventRecord],
    reference: Sequence[EventRecord],
    *,
    policy: EventMatchingPolicy,
) -> tuple[tuple[int, int], ...]:
    """Match events one-to-one by type and anchor with stable tie breaks.

    This is the same maximum-cardinality, minimum-total-error dynamic-programming primitive used
    by CardEventNet, adapted to validated microsecond event records.
    """

    def better(
        first: tuple[int, int, tuple[tuple[int, int], ...]],
        second: tuple[int, int, tuple[tuple[int, int], ...]],
    ) -> tuple[int, int, tuple[tuple[int, int], ...]]:
        if first[0] != second[0]:
            return first if first[0] > second[0] else second
        if first[1] != second[1]:
            return first if first[1] < second[1] else second
        return first if first[2] <= second[2] else second

    pairs: list[tuple[int, int]] = []
    event_types = sorted(
        {event.event_type for event in predicted} | {event.event_type for event in reference}
    )
    for event_type in event_types:
        predicted_order = tuple(
            sorted(
                (index for index, event in enumerate(predicted) if event.event_type == event_type),
                key=lambda index: (
                    event_anchor(predicted[index], policy),
                    predicted[index].event_id,
                ),
            )
        )
        reference_order = tuple(
            sorted(
                (index for index, event in enumerate(reference) if event.event_type == event_type),
                key=lambda index: (
                    event_anchor(reference[index], policy),
                    reference[index].event_id,
                ),
            )
        )
        states: list[list[tuple[int, int, tuple[tuple[int, int], ...]]]] = [
            [(0, 0, ()) for _ in range(len(reference_order) + 1)]
            for _ in range(len(predicted_order) + 1)
        ]
        for predicted_index in range(1, len(predicted_order) + 1):
            for reference_index in range(1, len(reference_order) + 1):
                state = better(
                    states[predicted_index - 1][reference_index],
                    states[predicted_index][reference_index - 1],
                )
                error = abs(
                    event_anchor(predicted[predicted_order[predicted_index - 1]], policy)
                    - event_anchor(reference[reference_order[reference_index - 1]], policy)
                )
                if error <= policy.tolerance_us:
                    prior = states[predicted_index - 1][reference_index - 1]
                    state = better(
                        state,
                        (
                            prior[0] + 1,
                            prior[1] + error,
                            (*prior[2], (predicted_index - 1, reference_index - 1)),
                        ),
                    )
                states[predicted_index][reference_index] = state
        pairs.extend(
            (predicted_order[predicted_index], reference_order[reference_index])
            for predicted_index, reference_index in states[-1][-1][2]
        )
    return tuple(sorted(pairs))


def compare_event_data(
    *,
    recording_id: str,
    left_run_id: str,
    right_run_id: str,
    reference: EventData,
    left: EventData,
    right: EventData,
    policy: EventMatchingPolicy,
    scope: PipelineComparisonScope,
    left_coverage: tuple[tuple[int, int], ...],
    right_coverage: tuple[tuple[int, int], ...],
) -> tuple[
    dict[str, PipelineComparisonCounts],
    dict[str, PipelineComparisonMetrics],
    tuple[PipelineComparisonItem, ...],
]:
    """Compare both event outputs against one reviewed reference."""

    result_items: list[PipelineComparisonItem] = []
    counts: dict[str, PipelineComparisonCounts] = {}
    metrics: dict[str, PipelineComparisonMetrics] = {}
    for side, _run_id, content, coverage in (
        ("left", left_run_id, left, left_coverage),
        ("right", right_run_id, right, right_coverage),
    ):
        reviewed_coverage = _intersection(scope.reviewed, coverage)
        reviewed_reference_events = [
            event
            for event in reference.events
            if _eligible_type(event, policy)
            and _contains(scope.reviewed, event_anchor(event, policy))
        ]
        reference_events = [
            event
            for event in reviewed_reference_events
            if _contains(coverage, event_anchor(event, policy))
        ]
        candidate_events = [
            event
            for event in content.events
            if _eligible_type(event, policy)
            and _contains(reviewed_coverage, event_anchor(event, policy))
        ]
        pairs = match_event_records(candidate_events, reference_events, policy=policy)
        matched_predicted = {predicted_index for predicted_index, _ in pairs}
        matched_reference = {reference_index for _, reference_index in pairs}
        errors: list[int] = []
        for predicted_index, reference_index in pairs:
            predicted_event = candidate_events[predicted_index]
            reference_event = reference_events[reference_index]
            error = event_anchor(predicted_event, policy) - event_anchor(reference_event, policy)
            errors.append(abs(error))
            result_items.append(
                _item(
                    recording_id=recording_id,
                    side=side,
                    outcome="match",
                    source_time_us=event_anchor(reference_event, policy),
                    reference_event=reference_event,
                    run_event=predicted_event,
                    delta_us=error,
                )
            )
        for reference_index, reference_event in enumerate(reference_events):
            if reference_index not in matched_reference:
                result_items.append(
                    _item(
                        recording_id=recording_id,
                        side=side,
                        outcome=(
                            "unpaired_input"
                            if not _contains(coverage, event_anchor(reference_event, policy))
                            else "miss"
                        ),
                        source_time_us=event_anchor(reference_event, policy),
                        reference_event=reference_event,
                        run_event=None,
                        delta_us=None,
                    )
                )
        for reference_event in reviewed_reference_events:
            if not _contains(coverage, event_anchor(reference_event, policy)):
                result_items.append(
                    _item(
                        recording_id=recording_id,
                        side=side,
                        outcome="unpaired_input",
                        source_time_us=event_anchor(reference_event, policy),
                        reference_event=reference_event,
                        run_event=None,
                        delta_us=None,
                    )
                )
        for predicted_index, predicted_event in enumerate(candidate_events):
            if predicted_index not in matched_predicted:
                result_items.append(
                    _item(
                        recording_id=recording_id,
                        side=side,
                        outcome="extra",
                        source_time_us=event_anchor(predicted_event, policy),
                        reference_event=None,
                        run_event=predicted_event,
                        delta_us=None,
                    )
                )
        not_reviewed_events = [
            event
            for event in content.events
            if _eligible_type(event, policy)
            and not _contains(scope.reviewed, event_anchor(event, policy))
        ]
        for event in not_reviewed_events:
            result_items.append(
                _item(
                    recording_id=recording_id,
                    side=side,
                    outcome="not_reviewed",
                    source_time_us=event_anchor(event, policy),
                    reference_event=None,
                    run_event=event,
                    delta_us=None,
                )
            )
        unpaired = sum(
            1
            for index, event in enumerate(reference_events)
            if index not in matched_reference
            and not _contains(coverage, event_anchor(event, policy))
        )
        misses = sum(
            1
            for index in range(len(reference_events))
            if index not in matched_reference
            and _contains(coverage, event_anchor(reference_events[index], policy))
        )
        extras = len(candidate_events) - len(matched_predicted)
        counts[side] = PipelineComparisonCounts(
            reference_events=len(reviewed_reference_events),
            run_events=len(candidate_events),
            matches=len(pairs),
            misses=misses,
            extras=extras,
            not_reviewed=len(not_reviewed_events),
            unpaired_input=unpaired,
        )
        denominator = len(pairs) + extras
        precision = None if denominator == 0 else len(pairs) / denominator
        recall = (
            None if not reviewed_reference_events else len(pairs) / len(reviewed_reference_events)
        )
        f1 = (
            None
            if precision is None or recall is None or precision + recall == 0
            else 2 * precision * recall / (precision + recall)
        )
        metrics[side] = PipelineComparisonMetrics(
            precision=precision,
            recall=recall,
            f1=f1,
            mean_error_us=None if not errors else sum(errors) / len(errors),
            max_error_us=None if not errors else max(errors),
        )
    result_items.sort(
        key=lambda item: (
            item.source_time_us is None,
            item.source_time_us if item.source_time_us is not None else 0,
            item.event_type,
            0 if item.side == "left" else 1,
            item.outcome,
            item.item_id,
        )
    )
    return counts, metrics, tuple(result_items)


def geometry_box(geometry: PipelineGeometry) -> tuple[int, int, int, int]:
    """Return the declared derived box for detector or reviewed geometry."""

    if isinstance(geometry, DetectorBoxGeometry):
        return geometry.x_min, geometry.y_min, geometry.x_max, geometry.y_max
    if isinstance(geometry, ReviewedVisibleRegionGeometry):
        points = [point for polygon in geometry.polygons for point in polygon]
        return (
            min(point[0] for point in points),
            min(point[1] for point in points),
            max(point[0] for point in points),
            max(point[1] for point in points),
        )
    raise PipelineComparisonContractError("geometry is not a supported pipeline geometry")


def geometry_iou(left: PipelineGeometry, right: PipelineGeometry) -> float:
    """Calculate IoU for the declared boxes of two pipeline geometries."""

    left_box = geometry_box(left)
    right_box = geometry_box(right)
    x_min = max(left_box[0], right_box[0])
    y_min = max(left_box[1], right_box[1])
    x_max = min(left_box[2], right_box[2])
    y_max = min(left_box[3], right_box[3])
    intersection = max(0, x_max - x_min) * max(0, y_max - y_min)
    left_area = (left_box[2] - left_box[0]) * (left_box[3] - left_box[1])
    right_area = (right_box[2] - right_box[0]) * (right_box[3] - right_box[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def match_geometry_records(
    predicted: Sequence[tuple[str, PipelineGeometry]],
    reference: Sequence[tuple[str, PipelineGeometry]],
    *,
    threshold: float,
) -> tuple[tuple[int, int, float], ...]:
    """Match geometry records with deterministic highest-IoU tie breaks."""

    if not 0.0 < threshold <= 1.0 or not math.isfinite(threshold):
        raise PipelineComparisonContractError("geometry IoU threshold must be in (0, 1]")
    predicted_order = tuple(
        sorted(
            range(len(predicted)),
            key=lambda index: (geometry_box(predicted[index][1]), predicted[index][0]),
        )
    )
    reference_order = tuple(
        sorted(
            range(len(reference)),
            key=lambda index: (geometry_box(reference[index][1]), reference[index][0]),
        )
    )
    candidates = sorted(
        (
            geometry_iou(predicted[predicted_index][1], reference[reference_index][1]),
            predicted_index,
            reference_index,
        )
        for predicted_index in predicted_order
        for reference_index in reference_order
        if geometry_iou(predicted[predicted_index][1], reference[reference_index][1]) >= threshold
    )
    used_predicted: set[int] = set()
    used_reference: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for iou, predicted_index, reference_index in sorted(
        candidates,
        key=lambda item: (
            -item[0],
            geometry_box(predicted[item[1]][1]),
            predicted[item[1]][0],
            geometry_box(reference[item[2]][1]),
            reference[item[2]][0],
        ),
    ):
        if predicted_index in used_predicted or reference_index in used_reference:
            continue
        used_predicted.add(predicted_index)
        used_reference.add(reference_index)
        matches.append((predicted_index, reference_index, iou))
    return tuple(sorted(matches))


def compare_visible_card_data(
    *,
    recording_id: str,
    reference: VisibleCardData,
    left: VisibleCardData,
    right: VisibleCardData,
    policy: EventMatchingPolicy,
    scope: PipelineComparisonScope,
) -> tuple[
    dict[str, PipelineComparisonCounts],
    dict[str, PipelineComparisonMetrics],
    tuple[PipelineComparisonItem, ...],
]:
    """Compare visible-card outcomes only on equal reviewed frame identities."""

    threshold = _geometry_threshold(policy, "visible_card_geometry")
    reviewed_keys = {_frame_identity_key(frame) for frame in scope.reviewed_frame_identities}
    results: dict[
        str,
        tuple[PipelineComparisonCounts, PipelineComparisonMetrics, list[PipelineComparisonItem]],
    ] = {}
    for side, content in (("left", left), ("right", right)):
        counts, metrics, items = _compare_visible_card_side(
            recording_id=recording_id,
            side=side,  # type: ignore[arg-type]
            reference=reference,
            content=content,
            reviewed_keys=reviewed_keys,
            threshold=threshold,
        )
        results[side] = counts, metrics, items
    return (
        {side: result[0] for side, result in results.items()},
        {side: result[1] for side, result in results.items()},
        tuple(
            sorted(
                [item for result in results.values() for item in result[2]],
                key=_item_sort_key,
            )
        ),
    )


def _compare_visible_card_side(
    *,
    recording_id: str,
    side: ComparisonSideName,
    reference: VisibleCardData,
    content: VisibleCardData,
    reviewed_keys: set[bytes],
    threshold: float,
) -> tuple[PipelineComparisonCounts, PipelineComparisonMetrics, list[PipelineComparisonItem]]:
    reference_groups = _visible_frame_groups(reference.outcomes)
    content_groups = _visible_frame_groups(content.outcomes)
    reference_count = 0
    run_count = 0
    matches = 0
    misses = 0
    extras = 0
    not_reviewed = 0
    unpaired_input = 0
    failures = 0
    items: list[PipelineComparisonItem] = []
    for frame_key in sorted(set(reference_groups) | set(content_groups)):
        reference_outcomes = reference_groups.get(frame_key, [])
        content_outcomes = content_groups.get(frame_key, [])
        is_reviewed = frame_key in reviewed_keys
        if not is_reviewed:
            for outcome in content_outcomes:
                if outcome.status == "failed":
                    failures += 1
                    items.append(
                        _vision_item(
                            recording_id=recording_id,
                            side=side,
                            outcome="failure",
                            frame=outcome.frame_identity,
                            run_event_id=outcome.event_id,
                            run_context=outcome.to_mapping(),
                        )
                    )
                else:
                    not_reviewed += max(1, len(outcome.candidates))
                    if outcome.candidates:
                        for candidate in outcome.candidates:
                            items.append(
                                _vision_item(
                                    recording_id=recording_id,
                                    side=side,
                                    outcome="not_reviewed",
                                    frame=outcome.frame_identity,
                                    run_event_id=outcome.event_id,
                                    run_card=candidate,
                                )
                            )
                    else:
                        items.append(
                            _vision_item(
                                recording_id=recording_id,
                                side=side,
                                outcome="not_reviewed",
                                frame=outcome.frame_identity,
                                run_event_id=outcome.event_id,
                                run_context=outcome.to_mapping(),
                            )
                        )
            continue
        for reference_outcome, content_outcome in _pair_outcomes(
            reference_outcomes, content_outcomes
        ):
            if reference_outcome is None:
                assert content_outcome is not None
                if content_outcome.status == "failed":
                    failures += 1
                    items.append(
                        _vision_item(
                            recording_id=recording_id,
                            side=side,
                            outcome="failure",
                            frame=content_outcome.frame_identity,
                            run_event_id=content_outcome.event_id,
                            run_context=content_outcome.to_mapping(),
                        )
                    )
                else:
                    unpaired_input += max(1, len(content_outcome.candidates))
                    if content_outcome.candidates:
                        for candidate in content_outcome.candidates:
                            items.append(
                                _vision_item(
                                    recording_id=recording_id,
                                    side=side,
                                    outcome="unpaired_input",
                                    frame=content_outcome.frame_identity,
                                    run_event_id=content_outcome.event_id,
                                    run_card=candidate,
                                )
                            )
                    else:
                        items.append(
                            _vision_item(
                                recording_id=recording_id,
                                side=side,
                                outcome="unpaired_input",
                                frame=content_outcome.frame_identity,
                                run_event_id=content_outcome.event_id,
                                run_context=content_outcome.to_mapping(),
                            )
                        )
                continue
            if content_outcome is None:
                if reference_outcome.status == "failed":
                    failures += 1
                    items.append(
                        _vision_item(
                            recording_id=recording_id,
                            side=side,
                            outcome="failure",
                            frame=reference_outcome.frame_identity,
                            reference_event_id=reference_outcome.event_id,
                            reference_context=reference_outcome.to_mapping(),
                        )
                    )
                else:
                    unpaired_input += max(1, len(reference_outcome.candidates))
                    if reference_outcome.candidates:
                        for candidate in reference_outcome.candidates:
                            items.append(
                                _vision_item(
                                    recording_id=recording_id,
                                    side=side,
                                    outcome="unpaired_input",
                                    frame=reference_outcome.frame_identity,
                                    reference_event_id=reference_outcome.event_id,
                                    reference_card=candidate,
                                )
                            )
                    else:
                        items.append(
                            _vision_item(
                                recording_id=recording_id,
                                side=side,
                                outcome="unpaired_input",
                                frame=reference_outcome.frame_identity,
                                reference_event_id=reference_outcome.event_id,
                                reference_context=reference_outcome.to_mapping(),
                            )
                        )
                continue
            reference_count += len(reference_outcome.candidates)
            run_count += len(content_outcome.candidates)
            if reference_outcome.status == "failed" or content_outcome.status == "failed":
                failures += 1
                items.append(
                    _vision_item(
                        recording_id=recording_id,
                        side=side,
                        outcome="failure",
                        frame=content_outcome.frame_identity or reference_outcome.frame_identity,
                        reference_event_id=reference_outcome.event_id,
                        run_event_id=content_outcome.event_id,
                        reference_context=reference_outcome.to_mapping(),
                        run_context=content_outcome.to_mapping(),
                    )
                )
                continue
            if not reference_outcome.candidates and not content_outcome.candidates:
                items.append(
                    _vision_item(
                        recording_id=recording_id,
                        side=side,
                        outcome="empty",
                        frame=content_outcome.frame_identity,
                        reference_event_id=reference_outcome.event_id,
                        run_event_id=content_outcome.event_id,
                        reference_context=reference_outcome.to_mapping(),
                        run_context=content_outcome.to_mapping(),
                    )
                )
                continue
            candidate_matches = match_geometry_records(
                [
                    (candidate.card_id, candidate.geometry)
                    for candidate in content_outcome.candidates
                ],
                [
                    (candidate.card_id, candidate.geometry)
                    for candidate in reference_outcome.candidates
                ],
                threshold=threshold,
            )
            matched_content = {pair[0] for pair in candidate_matches}
            matched_reference = {pair[1] for pair in candidate_matches}
            matches += len(candidate_matches)
            misses += len(reference_outcome.candidates) - len(matched_reference)
            extras += len(content_outcome.candidates) - len(matched_content)
            for content_index, reference_index, iou in candidate_matches:
                items.append(
                    _vision_item(
                        recording_id=recording_id,
                        side=side,
                        outcome="match",
                        frame=content_outcome.frame_identity,
                        reference_event_id=reference_outcome.event_id,
                        run_event_id=content_outcome.event_id,
                        reference_card=reference_outcome.candidates[reference_index],
                        run_card=content_outcome.candidates[content_index],
                        iou=iou,
                    )
                )
            for index, candidate in enumerate(reference_outcome.candidates):
                if index not in matched_reference:
                    items.append(
                        _vision_item(
                            recording_id=recording_id,
                            side=side,
                            outcome="miss",
                            frame=content_outcome.frame_identity,
                            reference_event_id=reference_outcome.event_id,
                            run_event_id=content_outcome.event_id,
                            reference_card=candidate,
                        )
                    )
            for index, candidate in enumerate(content_outcome.candidates):
                if index not in matched_content:
                    items.append(
                        _vision_item(
                            recording_id=recording_id,
                            side=side,
                            outcome="extra",
                            frame=content_outcome.frame_identity,
                            reference_event_id=reference_outcome.event_id,
                            run_event_id=content_outcome.event_id,
                            run_card=candidate,
                        )
                    )
    precision = None if matches + extras == 0 else matches / (matches + extras)
    recall = None if matches + misses == 0 else matches / (matches + misses)
    f1 = (
        None
        if precision is None or recall is None or precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    return (
        PipelineComparisonCounts(
            reference_events=reference_count,
            run_events=run_count,
            matches=matches,
            misses=misses,
            extras=extras,
            not_reviewed=not_reviewed,
            unpaired_input=unpaired_input,
            failures=failures,
        ),
        PipelineComparisonMetrics(
            precision=precision,
            recall=recall,
            f1=f1,
            mean_error_us=None,
            max_error_us=None,
        ),
        items,
    )


def compare_visual_identity_data(
    *,
    recording_id: str,
    reference: VisualIdentityData,
    left: VisualIdentityData,
    right: VisualIdentityData,
    policy: EventMatchingPolicy,
    scope: PipelineComparisonScope,
    left_exact_upstream: bool,
    right_exact_upstream: bool,
) -> tuple[
    dict[str, PipelineComparisonCounts],
    dict[str, PipelineComparisonMetrics],
    tuple[PipelineComparisonItem, ...],
]:
    """Compare identity candidates by exact cards or equal-frame geometry."""

    threshold = _geometry_threshold(policy, "visual_identity_geometry")
    reviewed_keys = {_frame_identity_key(frame) for frame in scope.reviewed_frame_identities}
    results: dict[
        str,
        tuple[PipelineComparisonCounts, PipelineComparisonMetrics, list[PipelineComparisonItem]],
    ] = {}
    for side, content, exact_upstream in (
        ("left", left, left_exact_upstream),
        ("right", right, right_exact_upstream),
    ):
        results[side] = _compare_identity_side(
            recording_id=recording_id,
            side=side,  # type: ignore[arg-type]
            reference=reference,
            content=content,
            reviewed_keys=reviewed_keys,
            threshold=threshold,
            exact_upstream=exact_upstream,
        )
    return (
        {side: result[0] for side, result in results.items()},
        {side: result[1] for side, result in results.items()},
        tuple(
            sorted(
                [item for result in results.values() for item in result[2]],
                key=_item_sort_key,
            )
        ),
    )


def _compare_identity_side(
    *,
    recording_id: str,
    side: ComparisonSideName,
    reference: VisualIdentityData,
    content: VisualIdentityData,
    reviewed_keys: set[bytes],
    threshold: float,
    exact_upstream: bool,
) -> tuple[PipelineComparisonCounts, PipelineComparisonMetrics, list[PipelineComparisonItem]]:
    reference_by_card = {outcome.card_id: outcome for outcome in reference.outcomes}
    reference_by_frame = _identity_frame_groups(reference.outcomes)
    content_by_frame = _identity_frame_groups(content.outcomes)
    pairs: list[
        tuple[VisualIdentityOutcome | None, VisualIdentityOutcome | None, float | None, bool]
    ] = []
    if exact_upstream:
        content_by_id = {outcome.card_id: outcome for outcome in content.outcomes}
        for card_id in sorted(set(reference_by_card) | set(content_by_id)):
            pairs.append((reference_by_card.get(card_id), content_by_id.get(card_id), None, False))
    else:
        for frame_key in sorted(set(reference_by_frame) | set(content_by_frame)):
            references = reference_by_frame.get(frame_key, [])
            candidates = content_by_frame.get(frame_key, [])
            geometry_matches = match_geometry_records(
                [(outcome.card_id, outcome.geometry) for outcome in candidates],
                [(outcome.card_id, outcome.geometry) for outcome in references],
                threshold=threshold,
            )
            matched_candidates = {pair[0] for pair in geometry_matches}
            matched_references = {pair[1] for pair in geometry_matches}
            pairs.extend(
                (references[reference_index], candidates[candidate_index], iou, False)
                for candidate_index, reference_index, iou in geometry_matches
            )
            pairs.extend(
                (None, candidates[index], None, True)
                for index in range(len(candidates))
                if index not in matched_candidates
            )
            pairs.extend(
                (references[index], None, None, True)
                for index in range(len(references))
                if index not in matched_references
            )
    reference_count = 0
    run_count = 0
    matches = 0
    misses = 0
    extras = 0
    not_reviewed = 0
    unpaired_input = 0
    failures = 0
    items: list[PipelineComparisonItem] = []
    for reference_outcome, content_outcome, iou, geometry_unpaired in pairs:
        frame = (None if content_outcome is None else content_outcome.frame_identity) or (
            None if reference_outcome is None else reference_outcome.frame_identity
        )
        frame_key = None if frame is None else _frame_identity_key(frame.to_mapping())
        if frame_key not in reviewed_keys:
            if content_outcome is not None:
                if content_outcome.status == "failed":
                    failures += 1
                    outcome = "failure"
                else:
                    not_reviewed += 1
                    outcome = "not_reviewed"
                items.append(
                    _vision_item(
                        recording_id=recording_id,
                        side=side,
                        outcome=outcome,
                        frame=frame,
                        run_card=content_outcome,
                        run_identity=_top_identity(content_outcome),
                        run_candidates=content_outcome.candidates,
                    )
                )
            continue
        if reference_outcome is None:
            if content_outcome is not None:
                if content_outcome.status == "failed":
                    failures += 1
                    outcome: ComparisonOutcome = "failure"
                elif geometry_unpaired:
                    unpaired_input += 1
                    outcome = "unpaired_input"
                else:
                    extras += 1
                    outcome = "extra"
                run_count += 1
                items.append(
                    _vision_item(
                        recording_id=recording_id,
                        side=side,
                        outcome=outcome,
                        frame=frame,
                        run_card=content_outcome,
                        run_identity=_top_identity(content_outcome),
                        run_candidates=content_outcome.candidates,
                    )
                )
            continue
        if content_outcome is None:
            reference_count += 1
            if reference_outcome.status == "failed":
                failures += 1
                outcome = "failure"
            elif geometry_unpaired:
                unpaired_input += 1
                outcome = "unpaired_input"
            else:
                misses += 1
                outcome = "miss"
            items.append(
                _vision_item(
                    recording_id=recording_id,
                    side=side,
                    outcome=outcome,
                    frame=frame,
                    reference_card=reference_outcome,
                    reference_identity=_top_identity(reference_outcome),
                    reference_candidates=reference_outcome.candidates,
                )
            )
            continue
        reference_count += 1
        run_count += 1
        if reference_outcome.status == "failed" or content_outcome.status == "failed":
            failures += 1
            outcome = "failure"
        elif not reference_outcome.candidates and not content_outcome.candidates:
            outcome = "empty"
        elif geometry_unpaired:
            unpaired_input += 1
            outcome = "unpaired_input"
        elif not reference_outcome.candidates or not content_outcome.candidates:
            misses += 1
            outcome = "disagreement"
        elif _top_identity(reference_outcome) == _top_identity(content_outcome):
            matches += 1
            outcome = "match"
        else:
            misses += 1
            outcome = "disagreement"
        items.append(
            _vision_item(
                recording_id=recording_id,
                side=side,
                outcome=outcome,
                frame=frame,
                reference_card=reference_outcome,
                run_card=content_outcome,
                iou=iou,
                reference_identity=_top_identity(reference_outcome),
                run_identity=_top_identity(content_outcome),
                reference_candidates=reference_outcome.candidates,
                run_candidates=content_outcome.candidates,
            )
        )
    precision = None if matches + extras + misses == 0 else matches / (matches + extras + misses)
    recall = None if reference_count == 0 else matches / reference_count
    f1 = (
        None
        if precision is None or recall is None or precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    return (
        PipelineComparisonCounts(
            reference_events=reference_count,
            run_events=run_count,
            matches=matches,
            misses=misses,
            extras=extras,
            not_reviewed=not_reviewed,
            unpaired_input=unpaired_input,
            failures=failures,
        ),
        PipelineComparisonMetrics(
            precision=precision,
            recall=recall,
            f1=f1,
            mean_error_us=None,
            max_error_us=None,
        ),
        items,
    )


def _geometry_threshold(policy: EventMatchingPolicy, expected_kind: ComparisonPolicyKind) -> float:
    if policy.kind != expected_kind or policy.iou_threshold is None:
        raise PipelineComparisonContractError(
            f"matching policy must be {expected_kind} with an IoU threshold"
        )
    return policy.iou_threshold


def _visible_frame_groups(
    outcomes: Sequence[VisibleCardOutcome],
) -> dict[bytes, list[VisibleCardOutcome]]:
    groups: dict[bytes, list[VisibleCardOutcome]] = {}
    for outcome in outcomes:
        key = (
            _frame_identity_key(outcome.frame_identity.to_mapping())
            if outcome.frame_identity
            else b"missing:" + outcome.event_id.encode()
        )
        groups.setdefault(key, []).append(outcome)
    for values in groups.values():
        values.sort(key=lambda outcome: outcome.event_id)
    return groups


def _identity_frame_groups(
    outcomes: Sequence[VisualIdentityOutcome],
) -> dict[bytes, list[VisualIdentityOutcome]]:
    groups: dict[bytes, list[VisualIdentityOutcome]] = {}
    for outcome in outcomes:
        key = _frame_identity_key(outcome.frame_identity.to_mapping())
        groups.setdefault(key, []).append(outcome)
    for values in groups.values():
        values.sort(key=lambda outcome: (geometry_box(outcome.geometry), outcome.card_id))
    return groups


def _pair_outcomes(
    references: Sequence[VisibleCardOutcome],
    contents: Sequence[VisibleCardOutcome],
) -> tuple[tuple[VisibleCardOutcome | None, VisibleCardOutcome | None], ...]:
    size = max(len(references), len(contents))
    return tuple(
        (
            references[index] if index < len(references) else None,
            contents[index] if index < len(contents) else None,
        )
        for index in range(size)
    )


def _top_identity(outcome: VisualIdentityOutcome | None) -> str | None:
    if outcome is None or not outcome.candidates:
        return None
    return outcome.candidates[0].identity


def _vision_item(
    *,
    recording_id: str,
    side: ComparisonSideName,
    outcome: ComparisonOutcome,
    frame: Any | None,
    reference_event_id: str | None = None,
    run_event_id: str | None = None,
    reference_card: Any | None = None,
    run_card: Any | None = None,
    iou: float | None = None,
    reference_identity: str | None = None,
    run_identity: str | None = None,
    reference_candidates: Sequence[Any] | None = None,
    run_candidates: Sequence[Any] | None = None,
    reference_context: dict[str, Any] | None = None,
    run_context: dict[str, Any] | None = None,
) -> PipelineComparisonItem:
    frame_mapping = None if frame is None else frame.to_mapping()
    reference_card_mapping = _vision_mapping(reference_card)
    run_card_mapping = _vision_mapping(run_card)
    reference_card_id = _vision_id(reference_card)
    run_card_id = _vision_id(run_card)
    reference_candidates_mapping = _vision_mappings(reference_candidates)
    run_candidates_mapping = _vision_mappings(run_candidates)
    source_time = None if frame is None else frame.requested_time_us
    seed = {
        "side": side,
        "outcome": outcome,
        "frame_identity": frame_mapping,
        "reference_event_id": reference_event_id,
        "run_event_id": run_event_id,
        "reference_card_id": reference_card_id,
        "run_card_id": run_card_id,
        "reference_identity": reference_identity,
        "run_identity": run_identity,
        "iou": iou,
    }
    item_id = f"comparison-item-{hashlib.sha256(canonical_json_bytes(seed)).hexdigest()[:24]}"
    if source_time is None:
        source_links = {"pipeline": f"/api/recordings/{recording_id}/pipeline"}
    else:
        source_links = {
            "derived_view": (
                f"/api/recordings/{recording_id}/pipeline/derived-views/exact-event/{source_time}"
            )
        }
    return PipelineComparisonItem(
        item_id=item_id,
        side=side,
        outcome=outcome,
        source_time_us=source_time,
        event_type=(
            "visual_identity"
            if reference_identity is not None
            or run_identity is not None
            or reference_candidates is not None
            or run_candidates is not None
            or (reference_context is not None and "classifier" in reference_context)
            or (run_context is not None and "classifier" in run_context)
            else "visible_card"
        ),
        reference_event_id=reference_event_id,
        run_event_id=run_event_id,
        reference_event=reference_context,
        run_event=run_context,
        delta_us=None,
        source_links=source_links,
        frame_identity=frame_mapping,
        reference_card_id=reference_card_id,
        run_card_id=run_card_id,
        reference_card=reference_card_mapping,
        run_card=run_card_mapping,
        iou=iou,
        reference_identity=reference_identity,
        run_identity=run_identity,
        reference_candidates=reference_candidates_mapping,
        run_candidates=run_candidates_mapping,
    )


def _vision_mapping(value: Any | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "to_mapping"):
        return value.to_mapping()
    if isinstance(value, Mapping):
        return dict(value)
    raise PipelineComparisonContractError("vision comparison item is not mappable")


def _vision_mappings(values: Sequence[Any] | None) -> tuple[dict[str, Any], ...] | None:
    if values is None:
        return None
    return tuple(mapping for value in values if (mapping := _vision_mapping(value)) is not None)


def _vision_id(value: Any | None) -> str | None:
    if value is None:
        return None
    if hasattr(value, "card_id"):
        return value.card_id
    if hasattr(value, "event_id"):
        return value.event_id
    if isinstance(value, Mapping):
        return value.get("card_id") or value.get("event_id")
    return None


def _item_sort_key(item: PipelineComparisonItem) -> tuple[Any, ...]:
    return (
        item.source_time_us is None,
        item.source_time_us if item.source_time_us is not None else 0,
        item.event_type,
        0 if item.side == "left" else 1,
        item.outcome,
        item.item_id,
    )


def _eligible_type(event: EventRecord, policy: EventMatchingPolicy) -> bool:
    return policy.event_type is None or event.event_type == policy.event_type


def _contains(intervals: Sequence[tuple[int, int]], value: int) -> bool:
    return any(start <= value <= end for start, end in intervals)


def _item(
    *,
    recording_id: str,
    side: ComparisonSideName,
    outcome: ComparisonOutcome,
    source_time_us: int | None,
    reference_event: EventRecord | None,
    run_event: EventRecord | None,
    delta_us: int | None,
) -> PipelineComparisonItem:
    event = reference_event or run_event
    if event is None:  # pragma: no cover - all event outcomes carry an event
        raise PipelineComparisonContractError("comparison item needs an event")
    reference_id = None if reference_event is None else reference_event.event_id
    run_id = None if run_event is None else run_event.event_id
    seed = {
        "side": side,
        "outcome": outcome,
        "reference_event_id": reference_id,
        "run_event_id": run_id,
        "source_time_us": source_time_us,
    }
    item_id = f"comparison-item-{hashlib.sha256(canonical_json_bytes(seed)).hexdigest()[:24]}"
    requested_time = source_time_us if source_time_us is not None else event.start_us
    source_links = {
        "derived_view": (
            f"/api/recordings/{recording_id}/pipeline/derived-views/exact-event/{requested_time}"
        )
    }
    return PipelineComparisonItem(
        item_id=item_id,
        side=side,
        outcome=outcome,
        source_time_us=source_time_us,
        event_type=event.event_type,
        reference_event_id=reference_id,
        run_event_id=run_id,
        reference_event=None if reference_event is None else reference_event.to_mapping(),
        run_event=None if run_event is None else run_event.to_mapping(),
        delta_us=delta_us,
        source_links=source_links,
    )


__all__ = [
    "ComparisonMode",
    "ComparisonOutcome",
    "ComparisonPolicyKind",
    "EventMatchingPolicy",
    "PIPELINE_COMPARISON_ALGORITHM_VERSION",
    "PIPELINE_COMPARISON_REQUEST_SCHEMA_VERSION",
    "PIPELINE_COMPARISON_SCHEMA_VERSION",
    "PipelineComparison",
    "PipelineComparisonContractError",
    "PipelineComparisonCounts",
    "PipelineComparisonDelta",
    "PipelineComparisonItem",
    "PipelineComparisonMetrics",
    "PipelineComparisonReference",
    "PipelineComparisonRequest",
    "PipelineComparisonScope",
    "PipelineComparisonSide",
    "canonical_pipeline_comparison_bytes",
    "canonical_pipeline_comparison_request_bytes",
    "build_comparison_scope",
    "compare_event_data",
    "event_anchor",
    "match_event_records",
    "normalize_event_coverage",
    "parse_pipeline_comparison_bytes",
    "parse_pipeline_comparison_request_bytes",
]
