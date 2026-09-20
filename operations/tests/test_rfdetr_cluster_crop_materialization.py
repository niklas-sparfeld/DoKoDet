from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

import doko_operations.reviewed_rfdetr_detector_campaign as reviewed_campaign
from doko_operations.card_plane_geometry import (
    CardPose,
    CardStackingOrder,
    ReviewedCardScene,
    derive_pose_scene_visible_regions,
)
from doko_operations.rfdetr_cluster_crop_materialization import (
    RfdetrClusterCropMaterializationError,
    load_rfdetr_cluster_crop_materialization,
    materialize_rfdetr_cluster_crop_dataset,
)
from doko_operations.rfdetr_segmentation_campaign import sha256_json


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _frame_bytes(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (1000, 1000), color).save(output, format="PNG", optimize=False)
    return output.getvalue()


def _scene_targets(event_id: str, *, count: int) -> tuple[dict[str, Any], dict[str, Any]]:
    poses = tuple(
        CardPose(
            card_id=f"{event_id}:card-{index}",
            center=(180.0 + index * 300.0, 450.0),
            rotation_degrees=0.0,
            source_suggestion_id=None,
            fit_diagnostics_digest=None,
        )
        for index in range(count)
    )
    scene = ReviewedCardScene.create(
        source_frame_id=f"{event_id}:frame",
        source_frame_width=1000,
        source_frame_height=1000,
        calibration_revision_id=f"calibration-{event_id}",
        calibration_digest="a" * 64,
        poses=poses,
        stacking_order=CardStackingOrder(
            card_ids=tuple(pose.card_id for pose in poses),
            uncertain_edges=(),
            contradictions=(),
        ),
    )
    projection = {
        "table_to_image_homography": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "card_short_size": 100.0,
        "card_long_size": 150.0,
    }
    derivation = derive_pose_scene_visible_regions(scene, projection)
    targets = [
        {
            "card_id": region["card_id"],
            "side": "face_up",
            "geometry": region["geometry"],
            "normalization": region["normalization"],
        }
        for region in derivation.regions
    ]
    envelope = {
        "schema_version": "reviewed-card-scene-editor/v1",
        "scene": scene.to_mapping(),
        "initialized_scene": scene.to_mapping(),
        "projection": projection,
        "derived_region_receipt": derivation.receipt.to_mapping(),
    }
    return {"targets": targets, "card_scene": envelope}, envelope


def _scene_manifest(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, bytes]]:
    from test_rfdetr_card_cluster_materialization import _manifest_fixture

    monkeypatch.setattr(reviewed_campaign, "REQUIRED_SEALED_TEST_GROUPS", 1)
    manifest_path, _ = _manifest_fixture(root, monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frame_bytes_by_split = {
        "train": _frame_bytes((80, 120, 160)),
        "validation": _frame_bytes((120, 160, 80)),
    }
    frame_lookup: dict[str, bytes] = {}
    for sample in manifest["samples"]:
        if sample["split"] not in frame_bytes_by_split:
            continue
        scene_data, _ = _scene_targets(sample["event_id"], count=len(sample["targets"]))
        sample.update(scene_data)
        frame_bytes = frame_bytes_by_split[sample["split"]]
        old_digest = sample["frame_identity"]["image_sha256"]
        new_digest = _digest_bytes(frame_bytes)
        sample["frame_identity"]["image_sha256"] = new_digest
        frame_lookup[new_digest] = frame_bytes
        for reference in manifest["references"]:
            for reference_sample in reference["samples"]:
                if reference_sample["event_id"] == sample["event_id"]:
                    reference_sample.update(scene_data)
                    reference_sample["frame_identity"]["image_sha256"] = new_digest
        assert old_digest != new_digest
    core = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    manifest["manifest_digest"] = sha256_json(core)
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    return manifest_path, frame_lookup


def test_materializer_uses_scene_derived_targets_and_rebuilds_identically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, frame_lookup = _scene_manifest(tmp_path, monkeypatch)

    def extract(_source: Path, frame: dict[str, Any]) -> bytes:
        return frame_lookup[frame["image_sha256"]]

    first = materialize_rfdetr_cluster_crop_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=tmp_path / "view-one",
        frame_extractor=extract,
        include_synthetic=False,
    )
    second = materialize_rfdetr_cluster_crop_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=tmp_path / "view-two",
        frame_extractor=extract,
        include_synthetic=False,
    )

    assert first.to_mapping() | {"view_root": "same"} == second.to_mapping() | {"view_root": "same"}
    assert first.real_crop_count == 4
    assert first.synthetic_crop_count == 0
    assert first.annotation_count == 4
    assert load_rfdetr_cluster_crop_materialization(first.view_root)["counts"]["real_crops"] == 4
    assert (first.view_root / "contact-sheet.png").is_file()

    train = json.loads((first.view_root / "train" / "_annotations.coco.json").read_text())
    assert train["categories"] == [{"id": 1, "name": "visible_card", "supercategory": "card"}]
    assert len(train["images"]) == 3
    assert len(train["annotations"]) == 3
    assert train["images"][0]["perturbation"]["translation"] == [25, -25]
    assert all(annotation["dataset_origin"] == "real_0072" for annotation in train["annotations"])
    assert all(annotation["crop_box"]["x_min"] >= 0 for annotation in train["annotations"])

    lineage = json.loads((first.view_root / "lineage.json").read_text())
    assert lineage["records"][0]["scene_lineage"]["authority"] == (
        "0072_reviewed_card_scene_derived_visible_regions"
    )
    files_one = sorted(
        (path.relative_to(first.view_root).as_posix(), _digest_bytes(path.read_bytes()))
        for path in first.view_root.rglob("*")
        if path.is_file()
    )
    files_two = sorted(
        (path.relative_to(second.view_root).as_posix(), _digest_bytes(path.read_bytes()))
        for path in second.view_root.rglob("*")
        if path.is_file()
    )
    assert files_one == files_two


def test_materializer_rejects_missing_or_stale_scene_derivation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, frame_lookup = _scene_manifest(tmp_path, monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["samples"][0].pop("card_scene")
    core = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    manifest["manifest_digest"] = sha256_json(core)
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    def extract(_source: Path, frame: dict[str, Any]) -> bytes:
        return frame_lookup[frame["image_sha256"]]

    with pytest.raises(RfdetrClusterCropMaterializationError, match="no completed 0072"):
        materialize_rfdetr_cluster_crop_dataset(
            manifest_path,
            repository_root=tmp_path,
            output_root=tmp_path / "missing-scene",
            frame_extractor=extract,
            include_synthetic=False,
        )


def test_materializer_adds_receipt_checked_synthetic_train_crops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, frame_lookup = _scene_manifest(tmp_path, monkeypatch)
    synthetic_root = tmp_path / "synthetic-view"
    image_root = synthetic_root / "train" / "images"
    image_root.mkdir(parents=True)
    synthetic_bytes = _frame_bytes((180, 60, 90))
    (image_root / "scene-0001.jpg").write_bytes(synthetic_bytes)
    source_digest = "b" * 64
    image_digest = _digest_bytes(synthetic_bytes)
    scene_id = "scene-0001"
    image = {
        "id": 1,
        "file_name": "images/scene-0001.jpg",
        "width": 1000,
        "height": 1000,
        "sha256": image_digest,
        "recording_id": "synthetic-visible-region-0070",
        "event_id": scene_id,
        "item_id": "background-1",
        "reference_revision_id": "synthetic-visible-region-recipe-v1",
        "source_video_sha256": source_digest,
        "source_frame_sha256": image_digest,
        "split": "train",
        "trainer_partition": "train",
        "session_id": "synthetic-visible-region-0070",
        "source_asset_id": "background-1",
        "video_id": "synthetic-visible-region-0070",
        "table_setup": "setup-synthetic",
        "source_group_key": "c" * 64,
        "dataset_origin": "synthetic",
        "synthetic_scene_id": scene_id,
    }
    annotation = {
        "id": 1,
        "image_id": 1,
        "category_id": 1,
        "bbox": [300, 300, 200, 200],
        "area": 20000.0,
        "segmentation": [[300, 300, 500, 300, 500, 500, 300, 500]],
        "iscrowd": 0,
        "recording_id": image["recording_id"],
        "event_id": scene_id,
        "item_id": "card-1",
        "reference_revision_id": image["reference_revision_id"],
        "card_id": "card-1",
        "source_video_sha256": source_digest,
        "source_frame_sha256": image_digest,
        "split": "train",
        "card_side": "face_up",
        "session_id": image["session_id"],
        "source_asset_id": image["source_asset_id"],
        "video_id": image["video_id"],
        "table_setup": image["table_setup"],
        "source_group_key": image["source_group_key"],
        "dataset_origin": "synthetic",
    }
    coco = {
        "info": {
            "description": "fixture",
            "version": "fixture",
            "coco_version": "coco-2017",
            "campaign_id": "0070-fixture",
            "trainer_partition": "train",
        },
        "licenses": [],
        "images": [image],
        "annotations": [annotation],
        "categories": [{"id": 1, "name": "visible_card", "supercategory": "card"}],
    }
    (synthetic_root / "train" / "_annotations.coco.json").write_text(
        json.dumps(coco), encoding="utf-8"
    )
    receipt_core = {
        "schema_version": "synthetic-visible-region-scenes/v1",
        "scene_id": scene_id,
        "source_lineage": {"source_group_keys": [image["source_group_key"]]},
    }
    receipt = {
        **receipt_core,
        "receipt_digest": _digest_bytes(
            json.dumps(
                receipt_core, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode()
        ),
    }
    receipt_root = synthetic_root / "receipts"
    receipt_root.mkdir()
    (receipt_root / f"{scene_id}.json").write_text(json.dumps(receipt), encoding="utf-8")

    def extract(_source: Path, frame: dict[str, Any]) -> bytes:
        return frame_lookup[frame["image_sha256"]]

    result = materialize_rfdetr_cluster_crop_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=tmp_path / "view-with-synthetic",
        frame_extractor=extract,
        synthetic_view_root=synthetic_root,
        synthetic_manifest_path=None,
    )

    assert result.synthetic_crop_count == 1
    train = json.loads(
        (result.view_root / "train" / "_annotations.coco.json").read_text(encoding="utf-8")
    )
    assert any(
        annotation["dataset_origin"] == "synthetic_0070" for annotation in train["annotations"]
    )
