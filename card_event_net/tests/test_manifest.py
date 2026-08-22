from __future__ import annotations

import pytest

from cardevent.manifest import DatasetRecord, make_group_split, validate_session_isolation
from cardevent.splits import SplitError, VideoSplit


def test_group_split_keeps_sessions_together() -> None:
    records = tuple(
        DatasetRecord(video_id=f"v{index}", session_id=f"s{index // 2}") for index in range(6)
    )

    split = make_group_split(records, seed=4)

    validate_session_isolation(split, records)


def test_session_validation_rejects_leakage() -> None:
    records = (DatasetRecord(video_id="one", session_id="same"), DatasetRecord("two", "same"))
    with pytest.raises(SplitError, match="Session same"):
        validate_session_isolation(VideoSplit(("one",), ("two",), ()), records)
