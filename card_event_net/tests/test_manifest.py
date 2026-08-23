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
