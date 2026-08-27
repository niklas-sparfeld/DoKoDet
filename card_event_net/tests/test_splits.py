from __future__ import annotations

from pathlib import Path

import pytest

from cardevent.splits import SplitError, VideoSplit, load_split, make_video_split, save_split


def test_video_split_is_deterministic_and_has_no_overlap() -> None:
    videos = [Path(f"game{index}.mov") for index in range(6)]

    first = make_video_split(videos, seed=42)
    second = make_video_split(videos, seed=42)

    assert first == second
    assert set(first.train).isdisjoint(first.val)
    assert set(first.train).isdisjoint(first.test)
    assert set(first.val).isdisjoint(first.test)
    assert len(first.train) + len(first.val) + len(first.test) == 6


def test_small_split_warns() -> None:
    with pytest.warns(UserWarning, match="Fewer than three"):
        split = make_video_split(["one.mov", "two.mov"])

    assert len(split.train) == 1
    assert len(split.val) == 1
    assert not split.test


def test_split_round_trips_and_rejects_overlap(tmp_path: Path) -> None:
    path = tmp_path / "default.yaml"
    expected = VideoSplit(train=("a",), val=("b",), test=("c",), unassigned=("d",))

    save_split(expected, path)

    assert load_split(path) == expected
    with pytest.raises(SplitError, match="more than one partition"):
        VideoSplit.from_mapping({"train": ["a"], "val": ["a"], "test": []})


def test_split_rejects_unknown_fields() -> None:
    with pytest.raises(SplitError, match="Unknown split fields"):
        VideoSplit.from_mapping({"train": [], "val": [], "test": [], "pending": []})
