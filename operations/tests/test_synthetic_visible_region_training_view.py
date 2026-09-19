from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from test_synthetic_visible_region_rendering import _write_fixture_inputs

from doko_operations.reviewed_rfdetr_detector_campaign import canonical_json_bytes
from doko_operations.synthetic_visible_region_rendering import (
    validate_synthetic_visible_region_scenes,
)
from doko_operations.synthetic_visible_region_training_view import (
    build_synthetic_visible_region_training_view,
    validate_synthetic_visible_region_training_view,
)


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _coco(partition: str, image_name: str) -> dict[str, object]:
    image = {
        "id": 1,
        "file_name": f"images/{image_name}",
        "width": 80,
        "height": 60,
        "sha256": "1" * 64,
        "recording_id": f"fixture-{partition}",
        "event_id": f"event-{partition}",
        "item_id": f"item-{partition}",
        "reference_revision_id": "fixture-v1",
        "source_video_sha256": "2" * 64,
        "source_frame_sha256": "1" * 64,
        "split": "validation" if partition == "valid" else partition,
        "trainer_partition": partition,
        "session_id": f"session-{partition}",
        "source_asset_id": f"asset-{partition}",
        "video_id": f"video-{partition}",
        "table_setup": "fixture-table",
        "source_group_key": "3" * 64,
    }
    annotation = {
        "id": 1,
        "image_id": 1,
        "category_id": 1,
        "bbox": [10, 10, 20, 20],
        "area": 200.0,
        "segmentation": [[10, 10, 30, 10, 30, 30, 10, 30]],
        "iscrowd": 0,
        "target_state": "reviewed_visible_region",
        "recording_id": image["recording_id"],
        "event_id": image["event_id"],
        "item_id": image["item_id"],
        "reference_revision_id": "fixture-v1",
        "card_id": "card-fixture",
        "source_video_sha256": "2" * 64,
        "source_frame_sha256": "1" * 64,
        "target_geometry_sha256": "4" * 64,
        "split": image["split"],
        "card_side": "face_up",
        "session_id": image["session_id"],
        "source_asset_id": image["source_asset_id"],
        "video_id": image["video_id"],
        "table_setup": image["table_setup"],
        "source_group_key": image["source_group_key"],
    }
    return {
        "info": {
            "description": "fixture",
            "version": "fixture-v1",
            "coco_version": "coco-2017",
            "campaign_id": "fixture-campaign",
            "trainer_partition": partition,
        },
        "licenses": [],
        "images": [image],
        "annotations": [annotation],
        "categories": [{"id": 1, "name": "visible_card", "supercategory": "card"}],
    }


def _base_view(tmp_path: Path) -> tuple[Path, dict[str, object], dict[str, bytes]]:
    root = tmp_path / "base"
    coco_by_partition: dict[str, dict[str, object]] = {}
    before: dict[str, bytes] = {}
    for partition, directory in (
        ("train", "train"),
        ("valid", "valid"),
        ("sealed_test", "sealed_test"),
    ):
        partition_root = root / directory
        (partition_root / "images").mkdir(parents=True)
        image_path = partition_root / "images" / f"{partition}.jpg"
        assert cv2.imwrite(str(image_path), np.full((60, 80, 3), 70, dtype=np.uint8))
        coco = _coco(partition, f"{partition}.jpg")
        coco_path = partition_root / "_annotations.coco.json"
        coco_path.write_bytes(canonical_json_bytes(coco) + b"\n")
        coco_by_partition[partition] = coco
        if partition != "train":
            before[partition] = coco_path.read_bytes()
            before[f"{partition}/image"] = image_path.read_bytes()
    return root, {"coco": coco_by_partition, "root": root}, before


def test_m3_merges_synthetic_train_only_and_preserves_held_out_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    m1_path, m0_path = _write_fixture_inputs(tmp_path)
    base_root, base_data, before = _base_view(tmp_path)

    def fake_load_base_view(repository: Path, materialization_root: Path) -> dict[str, object]:
        partitions = {
            "train": base_root / "train",
            "validation": base_root / "valid",
            "sealed_test": base_root / "sealed_test",
        }
        return {
            "materialization": {"materialization_digest": "5" * 64},
            "partitions": partitions,
            "coco": base_data["coco"],
            "coco_paths": {
                name: path / "_annotations.coco.json" for name, path in partitions.items()
            },
            "heldout_inventory": {
                "validation": [],
                "sealed_test": [],
            },
            "train_coco_sha256": hashlib.sha256(
                (base_root / "train" / "_annotations.coco.json").read_bytes()
            ).hexdigest(),
            "materialization_path": materialization_root / "materialization.json",
            "repository": repository,
        }

    # The helper returns the production inventory.  Keep this test focused on M3's merge logic.
    from doko_operations import synthetic_visible_region_training_view as training_view

    real_load = training_view._load_base_view

    def patched_load(repository: Path, materialization_root: Path) -> dict[str, object]:
        result = fake_load_base_view(repository, materialization_root)
        result["heldout_inventory"] = {
            "validation": training_view._file_inventory(base_root / "valid"),
            "sealed_test": training_view._file_inventory(base_root / "sealed_test"),
        }
        return result

    monkeypatch.setattr(training_view, "_load_base_view", patched_load)
    try:
        manifest = build_synthetic_visible_region_training_view(
            tmp_path,
            m0_manifest_path=m0_path,
            m1_manifest_path=m1_path,
            scene_manifest_path=tmp_path / "m3-scenes.json",
            materialization_root=tmp_path / "base",
            output_directory=tmp_path / "m3",
        )
    finally:
        monkeypatch.setattr(training_view, "_load_base_view", real_load)

    validate_synthetic_visible_region_training_view(manifest)
    assert manifest["dataset"]["synthetic"]["images"] == 2
    assert manifest["dataset"]["merged_train"]["images"] == 3
    assert manifest["operator_approval"]["status"] == "approved"
    assert manifest["inspection"]["samples"]
    assert (tmp_path / "m3" / "inspection" / "contact-sheet.jpg").is_file()
    assert (tmp_path / "m3" / "train" / "images" / "synthetic" / "scene-0000.jpg").is_file()
    assert (tmp_path / "m3" / "valid" / "_annotations.coco.json").read_bytes() == before["valid"]
    assert (tmp_path / "m3" / "valid" / "images" / "valid.jpg").read_bytes() == before[
        "valid/image"
    ]
    assert (tmp_path / "m3" / "sealed_test" / "_annotations.coco.json").read_bytes() == before[
        "sealed_test"
    ]
    assert (tmp_path / "m3" / "sealed_test" / "images" / "sealed_test.jpg").read_bytes() == before[
        "sealed_test/image"
    ]

    scene_manifest = json.loads((tmp_path / "m3-scenes.json").read_text())
    validate_synthetic_visible_region_scenes(scene_manifest)
