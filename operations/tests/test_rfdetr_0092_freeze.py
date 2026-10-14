from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "freeze_0092_m0.py"
SPEC = importlib.util.spec_from_file_location("freeze_0092_m0", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
freeze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(freeze)


def test_frozen_split_has_twenty_distinct_recordings_and_fresh_holdouts() -> None:
    split_ids = freeze.SPLIT_IDS
    all_ids = [
        recording_id for recording_ids in split_ids.values() for recording_id in recording_ids
    ]

    assert len(all_ids) == 20
    assert len(set(all_ids)) == 20
    assert len(split_ids["train"]) == 16
    assert split_ids["validation"] == ["cardeventnet-IMG_0651", "cardeventnet-IMG_0658"]
    assert split_ids["sealed_test"] == ["cardeventnet-IMG_0656", "cardeventnet-IMG_0660"]
    assert {"cardeventnet-IMG_0097", "cardeventnet-IMG_0654"}.issubset(split_ids["train"])


def test_source_lineage_cannot_cross_frozen_partitions() -> None:
    recordings = []
    for _split, recording_ids in freeze.SPLIT_IDS.items():
        for recording_id in recording_ids:
            recordings.append(
                {
                    "recording_id": recording_id,
                    "source_group": {
                        field: f"{field}-{recording_id}"
                        for field in (
                            "source_group_id",
                            "session_id",
                            "table_setup",
                            "source_asset_id",
                            "source_video_sha256",
                        )
                    },
                }
            )

    freeze._partition_lineage(recordings)
    train_id = freeze.SPLIT_IDS["train"][0]
    test_id = freeze.SPLIT_IDS["sealed_test"][0]
    by_id = {record["recording_id"]: record for record in recordings}
    by_id[test_id]["source_group"]["source_video_sha256"] = by_id[train_id]["source_group"][
        "source_video_sha256"
    ]

    with pytest.raises(ValueError, match="source_video_sha256 lineage overlaps"):
        freeze._partition_lineage(recordings)
