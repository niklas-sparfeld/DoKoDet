"""Deterministic matching and comparison execution for pipeline data."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

from table_evidence_analyzer.pipeline_data import (
    DetectorBoxGeometry,
    PipelineGeometry,
    PredictedVisibleRegionGeometry,
    ReviewedIgnoreRegionGeometry,
    ReviewedVisibleRegionGeometry,
    VisibleCardData,
    VisibleCardIgnoreRegion,
    VisibleCardOutcome,
    VisualIdentityData,
    VisualIdentityOutcome,
)

from .pipeline_comparison_contract import (
    ComparisonOutcome,
    ComparisonPolicyKind,
    ComparisonSideName,
    EventMatchingPolicy,
    PipelineComparisonContractError,
    PipelineComparisonCounts,
    PipelineComparisonItem,
    PipelineComparisonMetrics,
    PipelineComparisonScope,
    _frame_identity_key,
    _intersection,
)
from .pipeline_data import EventData, EventRecord, canonical_json_bytes
from .visible_card_ignore import (
    mask_count,
    rasterize_geometry,
    subtract_mask,
    union_masks,
)


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


def geometry_box(
    geometry: PipelineGeometry | ReviewedIgnoreRegionGeometry,
) -> tuple[int, int, int, int]:
    """Return the declared derived box for detector or reviewed geometry."""

    if isinstance(geometry, DetectorBoxGeometry):
        return geometry.x_min, geometry.y_min, geometry.x_max, geometry.y_max
    if isinstance(
        geometry,
        (
            PredictedVisibleRegionGeometry,
            ReviewedVisibleRegionGeometry,
            ReviewedIgnoreRegionGeometry,
        ),
    ):
        points = [point for polygon in geometry.polygons for point in polygon]
        return (
            min(point[0] for point in points),
            min(point[1] for point in points),
            max(point[0] for point in points),
            max(point[1] for point in points),
        )
    raise PipelineComparisonContractError("geometry is not a supported pipeline geometry")


def geometry_iou(
    left: PipelineGeometry | ReviewedIgnoreRegionGeometry,
    right: PipelineGeometry | ReviewedIgnoreRegionGeometry,
) -> float:
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
    ignored_frames = 0
    ignored_regions = 0
    ignored_pixels = 0
    neutralized_predictions = 0
    items: list[PipelineComparisonItem] = []
    for frame_key in sorted(set(reference_groups) | set(content_groups)):
        reference_outcomes = reference_groups.get(frame_key, [])
        content_outcomes = content_groups.get(frame_key, [])
        is_reviewed = frame_key in reviewed_keys
        frame_ignore_regions = _visible_ignore_regions(reference_outcomes)
        if is_reviewed and frame_ignore_regions:
            ignored_frames += 1
            ignored_regions += len(frame_ignore_regions)
            ignored_pixels += _visible_ignore_pixel_count(reference_outcomes)
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
            neutralized_indices = {
                index
                for index, candidate in enumerate(content_outcome.candidates)
                if _overlaps_ignore_region(candidate.geometry, frame_ignore_regions, threshold)
            }
            neutralized_predictions += len(neutralized_indices)
            ordinary_content = [
                candidate
                for index, candidate in enumerate(content_outcome.candidates)
                if index not in neutralized_indices
            ]
            for index in sorted(neutralized_indices):
                items.append(
                    _vision_item(
                        recording_id=recording_id,
                        side=side,
                        outcome="ignored",
                        frame=content_outcome.frame_identity,
                        reference_event_id=reference_outcome.event_id,
                        run_event_id=content_outcome.event_id,
                        run_card=content_outcome.candidates[index],
                    )
                )
            if not reference_outcome.candidates and not ordinary_content:
                if not neutralized_indices:
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
                [(candidate.card_id, candidate.geometry) for candidate in ordinary_content],
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
            extras += len(ordinary_content) - len(matched_content)
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
            for index, candidate in enumerate(ordinary_content):
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
            ignored_frames=ignored_frames,
            ignored_regions=ignored_regions,
            ignored_pixels=ignored_pixels,
            neutralized_predictions=neutralized_predictions,
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


def _visible_ignore_regions(
    outcomes: Sequence[VisibleCardOutcome],
) -> tuple[VisibleCardIgnoreRegion, ...]:
    return tuple(region for outcome in outcomes for region in outcome.ignored_regions)


def _visible_ignore_pixel_count(outcomes: Sequence[VisibleCardOutcome]) -> int:
    """Count the effective ignored pixels in one reviewed frame group."""

    with_frames = [outcome for outcome in outcomes if outcome.frame_identity is not None]
    if not with_frames:
        return 0
    frame = with_frames[0].frame_identity
    assert frame is not None
    width = frame.width
    height = frame.height
    size = width * height
    normal = union_masks(
        [
            rasterize_geometry(candidate.geometry, width=width, height=height)
            for outcome in with_frames
            for candidate in outcome.candidates
        ],
        size=size,
    )
    effective = [
        subtract_mask(
            rasterize_geometry(region.geometry, width=width, height=height),
            normal,
        )
        for outcome in with_frames
        for region in outcome.ignored_regions
    ]
    return mask_count(union_masks(effective, size=size))


def _overlaps_ignore_region(
    geometry: PipelineGeometry,
    regions: Sequence[VisibleCardIgnoreRegion],
    threshold: float,
) -> bool:
    return any(geometry_iou(geometry, region.geometry) >= threshold for region in regions)


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
    "compare_event_data",
    "compare_visible_card_data",
    "compare_visual_identity_data",
    "event_anchor",
    "geometry_box",
    "geometry_iou",
    "match_event_records",
    "match_geometry_records",
]
