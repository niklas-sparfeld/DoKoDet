from __future__ import annotations

import pytest

from doko_operations.pipeline_comparison_contract import (
    EventMatchingPolicy,
    PipelineComparisonScope,
    canonical_pipeline_comparison_request_bytes,
    parse_pipeline_comparison_request_bytes,
)
from doko_operations.pipeline_comparison_execution import compare_event_data, match_event_records
from doko_operations.pipeline_data import EventData, EventRecord


def _event(event_id: str, event_type: str, start_us: int, end_us: int | None = None) -> EventRecord:
    return EventRecord(
        event_id=event_id,
        event_type=event_type,
        start_us=start_us,
        end_us=start_us + 10 if end_us is None else end_us,
    )


def _policy(*, tolerance_us: int = 50) -> EventMatchingPolicy:
    return EventMatchingPolicy(
        policy_id="event-timing/v1",
        anchor="start_us",
        tolerance_us=tolerance_us,
    )


def test_event_matching_groups_types_and_uses_stable_minimum_error_ties() -> None:
    policy = _policy(tolerance_us=100)
    predicted = (
        _event("pred-b", "other", 100),
        _event("pred-a", "card_played", 90),
        _event("pred-c", "card_played", 110),
    )
    reference = (
        _event("ref-b", "card_played", 100),
        _event("ref-a", "card_played", 100),
        _event("ref-other", "other", 100),
    )

    pairs = match_event_records(predicted, reference, policy=policy)

    assert {(predicted[pred].event_id, reference[ref].event_id) for pred, ref in pairs} == {
        ("pred-a", "ref-a"),
        ("pred-c", "ref-b"),
        ("pred-b", "ref-other"),
    }


def test_event_comparison_excludes_unreviewed_events_from_metrics() -> None:
    policy = _policy(tolerance_us=25)
    reference = EventData(
        events=(_event("ref-1", "card_played", 100), _event("ref-2", "card_played", 700))
    )
    left = EventData(
        events=(
            _event("left-match", "card_played", 110),
            _event("left-extra", "card_played", 300),
            _event("left-unreviewed", "card_played", 900),
        )
    )
    right = EventData(events=(_event("right-match", "card_played", 100),))
    scope = PipelineComparisonScope(
        reviewed=((0, 800),),
        common_covered=((0, 800),),
        left_only=(),
        right_only=(),
    )

    counts, metrics, items = compare_event_data(
        recording_id="recording-1",
        left_run_id="left-run",
        right_run_id="right-run",
        reference=reference,
        left=left,
        right=right,
        policy=policy,
        scope=scope,
        left_coverage=((0, 1_000),),
        right_coverage=((0, 1_000),),
    )

    assert counts["left"].matches == 1
    assert counts["left"].misses == 1
    assert counts["left"].extras == 1
    assert counts["left"].not_reviewed == 1
    assert metrics["left"].precision == 0.5
    assert metrics["left"].recall == 0.5
    assert [item.outcome for item in items].count("not_reviewed") == 1


def test_comparison_request_canonicalization_normalizes_optional_event_type() -> None:
    request_without_type = {
        "schema_version": "pipeline-comparison-request/v1",
        "recording_id": "recording-1",
        "content_type": "events",
        "left_run_id": "left-run",
        "right_run_id": "right-run",
        "reference_revision_id": "reference-1",
        "matching_policy": {
            "policy_id": "event-timing/v1",
            "anchor": "start_us",
            "tolerance_us": 25,
        },
    }
    request_with_null = {
        **request_without_type,
        "matching_policy": {**request_without_type["matching_policy"], "event_type": None},
    }

    assert canonical_pipeline_comparison_request_bytes(request_without_type) == (
        canonical_pipeline_comparison_request_bytes(request_with_null)
    )


def test_comparison_request_parser_rejects_duplicate_fields() -> None:
    raw = (
        b'{"schema_version":"pipeline-comparison-request/v1",'
        b'"schema_version":"pipeline-comparison-request/v1"}'
    )

    with pytest.raises(ValueError, match="duplicate field"):
        parse_pipeline_comparison_request_bytes(raw)
