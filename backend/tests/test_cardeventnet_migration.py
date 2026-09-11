import json
from pathlib import Path

import pytest

from dokodetector_backend.cardeventnet_migration import (
    CardEventNetMigrationError,
    _default_repository_root,
    _load_events,
    filter_selected_videos,
    read_dataset_metadata,
    read_split,
)


def test_read_split_normalizes_validation_alias(tmp_path):
    split = tmp_path / "default.yaml"
    split.write_text(
        "train:\n- IMG_0001\nval:\n- IMG_0002\ntest:\n- IMG_0003\n",
        encoding="utf-8",
    )

    assert read_split(split, ("validation",)) == [("IMG_0002", "validation")]


def test_filter_selected_videos_keeps_one_requested_split_item():
    selected = [("IMG_0001", "train"), ("IMG_0002", "validation")]

    assert filter_selected_videos(selected, ("IMG_0002",)) == [("IMG_0002", "validation")]


def test_filter_selected_videos_rejects_item_outside_selected_partitions():
    with pytest.raises(CardEventNetMigrationError, match="not in the selected split partitions"):
        filter_selected_videos([("IMG_0001", "train")], ("IMG_0002",))


def test_read_dataset_metadata_reads_scalar_overrides(tmp_path):
    manifest = tmp_path / "dataset-manifest.v1.yaml"
    manifest.write_text(
        """
videos:
  - &base
    video_id: IMG_0001
    file_name: IMG_0001.mov
    session_id: capture-img-0001
    duration_s: 12.5
    recording_date: "2020-01-01T00:00:00Z"
  - <<: *base
    video_id: IMG_0002
    file_name: IMG_0002.m4v
    session_id: capture-img-0002
    duration_s: 8.25
""",
        encoding="utf-8",
    )

    metadata = read_dataset_metadata(manifest)

    assert metadata["IMG_0002"].file_name == "IMG_0002.m4v"
    assert metadata["IMG_0002"].duration_s == 8.25
    assert metadata["IMG_0002"].session_id == "capture-img-0002"


def test_load_events_accepts_legacy_annotation_envelope_with_canonical_events(tmp_path):
    annotation = tmp_path / "IMG_2780.json"
    annotation.write_text(
        json.dumps(
            {
                "video": "IMG_2780.m4v",
                "roi": {"x": 0, "y": 0, "width": 1, "height": 1},
                "events": [{"time_s": 1.25, "type": "card_state_changed"}],
            }
        ),
        encoding="utf-8",
    )

    events, schema = _load_events(
        annotation,
        video_name="IMG_2780.m4v",
        duration_us=2_000_000,
    )

    assert schema == "cardevent-annotation/legacy-v1"
    assert len(events) == 1
    assert events[0].start_us == 1_250_000


def test_migration_defaults_to_repository_storage_root():
    assert _default_repository_root() == Path(__file__).resolve().parents[2]
