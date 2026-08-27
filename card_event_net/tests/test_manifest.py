from __future__ import annotations

from pathlib import Path

import pytest

from cardevent.manifest import (
    MANIFEST_SCHEMA_VERSION,
    DatasetRecord,
    ManifestError,
    load_dataset_manifest,
    make_group_split,
    validate_session_isolation,
)
from cardevent.splits import SplitError, VideoSplit, load_split
from cardevent.video import SUPPORTED_VIDEO_EXTENSIONS


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


def test_game_validation_rejects_leakage() -> None:
    records = (
        DatasetRecord(video_id="one", session_id="session-one", game_id="game-one"),
        DatasetRecord(video_id="two", session_id="session-two", game_id="game-one"),
    )
    with pytest.raises(SplitError, match="Game game-one"):
        validate_session_isolation(VideoSplit(("one",), ("two",), ()), records)


def test_table_setup_validation_rejects_leakage() -> None:
    records = (
        DatasetRecord(video_id="one", session_id="session-one", table_setup="table-one"),
        DatasetRecord(video_id="two", session_id="session-two", table_setup="table-one"),
    )
    with pytest.raises(SplitError, match="Table setup table-one"):
        validate_session_isolation(VideoSplit(("one",), ("two",), ()), records)


def test_group_split_keeps_linked_game_sessions_together() -> None:
    records = (
        DatasetRecord(video_id="one", session_id="session-one", game_id="game-one"),
        DatasetRecord(video_id="two", session_id="session-two", game_id="game-one"),
        DatasetRecord(video_id="three", session_id="session-three", game_id="game-two"),
    )

    split = make_group_split(records, seed=4)

    assert set(split.train).isdisjoint(split.val)
    assert set(split.train).isdisjoint(split.test)
    assert set(split.val).isdisjoint(split.test)
    assert ("one" in split.train) == ("two" in split.train)
    assert ("one" in split.val) == ("two" in split.val)
    assert ("one" in split.test) == ("two" in split.test)


def test_load_versioned_example_manifest() -> None:
    path = Path(__file__).parents[1] / "data" / "dataset-manifest.example.yaml"

    records = load_dataset_manifest(path)

    assert records[0].content_type == "staged_trick_sequence"
    assert records[0].game_id is None
    assert records[0].scenario_tags == (
        "normal_card_play",
        "trick_collected_during_play",
        "collected_tricks_visible",
    )


def test_current_manifest_covers_local_annotations_and_development_split() -> None:
    data_dir = Path(__file__).parents[1] / "data"
    records = load_dataset_manifest(data_dir / "dataset-manifest.v1.yaml")
    split = load_split(data_dir / "splits" / "full-frame-development.yaml")
    by_video = {record.video_id: record for record in records}

    expected_video_ids = {path.stem for path in (data_dir / "annotations").glob("*.json")}
    manifest_video_ids = {record.video_id for record in records}
    assert expected_video_ids <= manifest_video_ids
    raw_video_ids = {
        path.stem
        for path in (data_dir / "raw").iterdir()
        if path.is_file() and path.suffix.casefold() in SUPPORTED_VIDEO_EXTENSIONS
    }
    assert raw_video_ids == manifest_video_ids
    assigned_video_ids = set(split.train + split.val + split.test)
    assert assigned_video_ids.isdisjoint(split.unassigned)
    assert assigned_video_ids | set(split.unassigned) == expected_video_ids
    assert set(split.unassigned) == {"IMG_0669", "IMG_0670", "IMG_0671", "IMG_0673", "IMG_0674"}
    assert split.test == ()
    assert "IMG_2781" in split.train
    intake_records = [by_video[video_id] for video_id in split.unassigned]
    assert {record.content_type for record in intake_records} == {"staged_scenario"}
    assert {record.session_id for record in intake_records} == {
        "capture-20260825-weird-staged-a"
    }
    assert all(record.game_id is None for record in intake_records)
    assert {record.source for record in intake_records} == {"self_recorded"}
    assert {record.source_permission for record in intake_records} == {
        "training_and_evaluation"
    }
    assert {by_video[video_id].content_type for video_id in split.train} == {
        "real_game",
        "staged_trick_sequence",
    }
    assert {by_video[video_id].content_type for video_id in split.val} == {
        "real_game",
        "staged_trick_sequence",
    }
    assert {by_video[video_id].device for video_id in split.val} == {
        "Apple iPhone SE (2nd generation)",
        "Apple iPhone 14",
        "Apple iPhone X",
    }
    validate_session_isolation(split, records)


def test_current_manifest_describes_recording_groups() -> None:
    path = Path(__file__).parents[1] / "data" / "dataset-manifest.v1.yaml"
    records = load_dataset_manifest(path)

    old_staged = tuple(record for record in records if record.file_name.endswith(".mov"))
    target_videos = tuple(record for record in records if record.file_name.endswith(".MOV"))
    real_games = tuple(record for record in records if record.file_name.endswith(".m4v"))

    assert len(old_staged) == 6
    assert len(target_videos) == 32
    assert len(real_games) == 5
    assert {record.content_type for record in old_staged + target_videos} == {
        "staged_scenario",
        "staged_trick_sequence",
    }
    assert all(record.game_id is None for record in old_staged + target_videos)
    assert len({record.session_id for record in old_staged + target_videos}) == 34
    assert len({record.table_setup for record in old_staged + target_videos}) == 34
    assert {record.device for record in target_videos} == {"Apple iPhone 14"}
    assert {record.content_type for record in real_games} == {"real_game"}
    assert {record.device for record in real_games} == {"Apple iPhone X"}
    assert len({record.game_id for record in real_games}) == 2
    january_28_game_ids = {
        record.game_id for record in real_games if "2018-01-28" in record.recording_date
    }
    assert january_28_game_ids == {"game-20180128-a"}
    assert all(record.known_limitations == () for record in real_games)
    assert all(
        record.notes == "One complete 40-card round with 10 tricks from a real game."
        for record in real_games
    )


def test_versioned_manifest_requires_complete_records(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(
        f"schema_version: {MANIFEST_SCHEMA_VERSION}\nvideos:\n  - video_id: one\n"
        "    session_id: session-one\n",
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="missing fields"):
        load_dataset_manifest(path)


def test_versioned_manifest_rejects_unknown_controlled_value(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "data" / "dataset-manifest.example.yaml"
    path = tmp_path / "manifest.yaml"
    path.write_text(
        source.read_text(encoding="utf-8").replace(
            "content_type: staged_trick_sequence", "content_type: artificial"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="content_type"):
        load_dataset_manifest(path)


def test_versioned_manifest_rejects_null_controlled_value(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "data" / "dataset-manifest.example.yaml"
    path = tmp_path / "manifest.yaml"
    path.write_text(
        source.read_text(encoding="utf-8").replace(
            "camera_view: high_oblique", "camera_view: null"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="null required fields"):
        load_dataset_manifest(path)


def test_real_game_requires_game_id(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "data" / "dataset-manifest.example.yaml"
    path = tmp_path / "manifest.yaml"
    path.write_text(
        source.read_text(encoding="utf-8").replace(
            "content_type: staged_trick_sequence", "content_type: real_game"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="game_id"):
        load_dataset_manifest(path)
