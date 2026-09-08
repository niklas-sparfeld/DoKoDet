"""Immutable contracts for deterministic recording-pipeline comparisons."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .pipeline_data import canonical_json_bytes

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


__all__ = [
    "ComparisonMode",
    "ComparisonOutcome",
    "ComparisonPolicyKind",
    "ComparisonSideName",
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
    "build_frame_comparison_scope",
    "normalize_event_coverage",
    "parse_pipeline_comparison_bytes",
    "parse_pipeline_comparison_request_bytes",
]
