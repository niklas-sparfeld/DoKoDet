from __future__ import annotations

import pytest

from table_evidence_analyzer.model_parity import (
    match_detections,
    ranked_indices,
    threshold_decision,
    within_tolerance,
)


def test_float_comparison_handles_equality_tolerance_and_drift() -> None:
    assert within_tolerance(1.0, 1.0, atol=1e-4, rtol=1e-4)
    assert within_tolerance(1.00005, 1.0, atol=1e-4, rtol=1e-4)
    assert not within_tolerance(1.001, 1.0, atol=1e-4, rtol=1e-4)


def test_rank_and_threshold_comparisons_report_decision_changes() -> None:
    assert ranked_indices([0.2, 0.8, 0.4]) == (1, 2, 0)
    assert ranked_indices([0.2, 0.5, 0.4]) != ranked_indices([0.2, 0.39, 0.4])
    assert threshold_decision(0.5, 0.5)
    assert threshold_decision(0.499, 0.5) != threshold_decision(0.501, 0.5)


def test_mask_matching_reports_unmatched_detection_and_mask() -> None:
    polygon = [
        {"x": 100, "y": 100},
        {"x": 900, "y": 100},
        {"x": 900, "y": 900},
        {"x": 100, "y": 900},
    ]
    shifted = [
        {"x": 150, "y": 100},
        {"x": 950, "y": 100},
        {"x": 950, "y": 900},
        {"x": 150, "y": 900},
    ]
    reference = [{"class_id": 0, "visible_polygon": polygon}]
    candidate = [
        {"class_id": 0, "visible_polygon": shifted},
        {"class_id": 1, "visible_polygon": polygon},
    ]

    comparison = match_detections(reference, candidate, min_mask_iou=0.5)

    assert len(comparison["matches"]) == 1
    assert comparison["matches"][0]["reference_index"] == 0
    assert comparison["matches"][0]["candidate_index"] == 0
    assert comparison["matches"][0]["mask_iou"] == pytest.approx(15 / 17)
    assert comparison["unmatched_reference"] == []
    assert comparison["unmatched_candidate"] == [1]


def test_invalid_comparison_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        within_tolerance(1.0, 1.0, atol=-1.0, rtol=0.0)
    with pytest.raises(ValueError, match="finite"):
        ranked_indices([float("nan")])
