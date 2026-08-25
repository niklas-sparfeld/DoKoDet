from cardevent.review_ui import _queue_candidate_time


def test_queue_candidate_marker_keeps_original_time_after_correction() -> None:
    item = {"timestamp_s": 3.8, "original_timestamp_s": 4.0}

    assert _queue_candidate_time(item) == 4.0


def test_queue_candidate_marker_supports_unreviewed_items() -> None:
    assert _queue_candidate_time({"timestamp_s": 4.0}) == 4.0
