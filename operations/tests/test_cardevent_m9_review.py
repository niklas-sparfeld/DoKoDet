from __future__ import annotations

from doko_operations.cardevent_m9 import _clean_negative_reason


def test_m9_hard_negative_filter_excludes_interval_interiors_first() -> None:
    intervals = ((10.0, 12.0), (20.0, 20.0))

    assert _clean_negative_reason(10.5, intervals) == "interval_interior"
    assert _clean_negative_reason(11.9, intervals) == "interval_interior"
    assert _clean_negative_reason(19.9, intervals) == "positive_window"
    assert _clean_negative_reason(20.3, intervals) == "point_event_exclusion_buffer"
    assert _clean_negative_reason(25.0, intervals) is None


def test_m9_hard_negative_filter_rejects_interval_end_positive_window() -> None:
    intervals = ((30.0, 31.0),)

    assert _clean_negative_reason(31.0, intervals) == "positive_window"
    assert _clean_negative_reason(31.2, intervals) == "point_event_exclusion_buffer"
