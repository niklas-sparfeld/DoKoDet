from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from table_evidence_analyzer.rfdetr_cluster_crop_evaluation import (
    RfdetrClusterCropEvaluationConfig,
    run_rfdetr_cluster_crop_validation,
)
from table_evidence_analyzer.rfdetr_cluster_crop_training import (
    RFDETR_CLUSTER_CROP_DATASET_SCHEMA,
    RfdetrClusterCropTrainingConfig,
    load_rfdetr_cluster_crop_view,
    run_rfdetr_cluster_crop_training,
)
from table_evidence_analyzer.rfdetr_segmentation_training import (
    RFDETR_SEGMENTATION_BUNDLE_SCHEMA,
    RFDETR_SEGMENTATION_FINAL_CHECKPOINT,
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")


def _bundle(
    root: Path, *, campaign_id: str = "0068-m0-reviewed-rfdetr-local-visible-card-detector"
) -> Path:
    root.mkdir(parents=True)
    checkpoint = root / RFDETR_SEGMENTATION_FINAL_CHECKPOINT
    checkpoint.write_bytes(b"selected-0068-checkpoint")
    checkpoint_digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    recipe_core = {"schema_version": "fixture-recipe/v1", "initializer": checkpoint_digest}
    recipe = {**recipe_core, "recipe_digest": _digest(recipe_core)}
    manifest_core = {
        "schema_version": RFDETR_SEGMENTATION_BUNDLE_SCHEMA,
        "component": "visible-card-segmentation",
        "quality_state": "unreviewed",
        "campaign_id": campaign_id,
        "model": {"class": "RFDETRSegMedium"},
        "model_variant": "rfdetr-seg-medium",
        "package": {"name": "rfdetr", "version": "1.9.4"},
        "class_map": {"1": "visible_card"},
        "input_size": [432, 432],
        "confidence_threshold": 0.5,
        "recipe": recipe,
        "checkpoint_file": checkpoint.name,
        "checkpoint_sha256": checkpoint_digest,
        "files": {checkpoint.name: checkpoint_digest},
    }
    _write_json(root / "manifest.json", {**manifest_core, "bundle_digest": _digest(manifest_core)})
    return root


def _crop_image(path: Path, color: tuple[int, int, int]) -> str:
    image = Image.new("RGB", (32, 32), color)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _m4_view(root: Path) -> Path:
    records: list[dict[str, object]] = []
    images_by_partition: dict[str, list[dict[str, object]]] = {"train": [], "valid": []}
    annotations_by_partition: dict[str, list[dict[str, object]]] = {"train": [], "valid": []}
    image_id = 0
    annotation_id = 0

    def add_crop(
        partition: str,
        origin: str,
        group: str,
        crop_id: str,
        polygons: list[list[float]],
        color: tuple[int, int, int],
    ) -> None:
        nonlocal image_id, annotation_id
        image_id += 1
        image_name = f"crop-{image_id:06d}.png"
        image_path = root / partition / "images" / image_name
        image_digest = _crop_image(image_path, color)
        source_frame_digest = hashlib.sha256(f"source-{crop_id}".encode()).hexdigest()
        transform = {
            "schema_version": "visible-card-cascade-transform/v1",
            "source_size": {"width": 100, "height": 100},
            "crop_origin": {"x": 10, "y": 20},
            "crop_size": {"width": 32, "height": 32},
            "model_size": {"width": 432, "height": 432},
            "scale": {"x": 13.5, "y": 13.5},
        }
        image = {
            "id": image_id,
            "file_name": f"images/{image_name}",
            "width": 32,
            "height": 32,
            "sha256": image_digest,
            "recording_id": f"recording-{origin}",
            "event_id": f"event-{origin}",
            "item_id": f"item-{origin}",
            "reference_revision_id": f"revision-{origin}",
            "source_video_sha256": "a" * 64,
            "source_frame_sha256": source_frame_digest,
            "source_frame": {"frame_index": image_id, "image_sha256": source_frame_digest},
            "split": "train" if partition == "train" else "validation",
            "trainer_partition": partition,
            "source_group_key": group,
            "dataset_origin": origin,
            "crop_id": crop_id,
            "cluster_id": f"cluster-{crop_id}",
            "cluster": {"cluster_id": f"cluster-{crop_id}"},
            "transform": transform,
            "perturbation": {"policy_id": "quarter-span-diagonal-shift-v1"},
        }
        images_by_partition[partition].append(image)
        cards = []
        for card_index, polygon in enumerate(polygons):
            annotation_id += 1
            x_values = polygon[0::2]
            y_values = polygon[1::2]
            bbox = [
                min(x_values),
                min(y_values),
                max(x_values) - min(x_values),
                max(y_values) - min(y_values),
            ]
            annotation = {
                "id": annotation_id,
                "image_id": image_id,
                "category_id": 1,
                "bbox": bbox,
                "area": bbox[2] * bbox[3],
                "segmentation": [polygon],
                "iscrowd": 0,
                "card_id": f"{crop_id}-card-{card_index}",
                "card_side": "face_up",
                "source_box": {
                    "x_min": bbox[0] + 10,
                    "y_min": bbox[1] + 20,
                    "x_max": bbox[0] + bbox[2] + 10,
                    "y_max": bbox[1] + bbox[3] + 20,
                },
                "crop_box": {
                    "x_min": bbox[0],
                    "y_min": bbox[1],
                    "x_max": bbox[0] + bbox[2],
                    "y_max": bbox[1] + bbox[3],
                },
                "crop_id": crop_id,
                "cluster_id": f"cluster-{crop_id}",
                "source_geometry": {"kind": "fixture"},
                "source_frame_sha256": source_frame_digest,
            }
            annotations_by_partition[partition].append(annotation)
            cards.append({"card_id": annotation["card_id"]})
        records.append(
            {
                "crop_id": crop_id,
                "image_id": image_id,
                "dataset_origin": origin,
                "scene_lineage": (
                    {
                        "authority": "0072_reviewed_card_scene_derived_visible_regions",
                        "calibration_revision_id": "calibration-1",
                        "calibration_digest": "b" * 64,
                        "derived_region_receipt": {"receipt_digest": "c" * 64},
                    }
                    if origin == "real_0072"
                    else {
                        "authority": "0070_frozen_scene_receipt",
                        "receipt": {"scene_id": crop_id},
                    }
                ),
                "cards": cards,
            }
        )

    add_crop(
        "train",
        "real_0072",
        "real-train",
        "real-train",
        [[2, 2, 14, 2, 14, 14, 2, 14]],
        (30, 40, 50),
    )
    add_crop(
        "train",
        "synthetic_0070",
        "synthetic-train",
        "synthetic-train",
        [[16, 2, 28, 2, 28, 14, 16, 14]],
        (50, 60, 70),
    )
    add_crop(
        "valid",
        "real_0072",
        "real-validation",
        "real-validation",
        [[2, 2, 16, 2, 16, 16, 2, 16], [12, 12, 26, 12, 26, 26, 12, 26]],
        (70, 80, 90),
    )
    for partition in ("train", "valid"):
        _write_json(
            root / partition / "_annotations.coco.json",
            {
                "info": {"campaign_id": "0071-m4-rfdetr-cluster-crop-segmentation"},
                "licenses": [],
                "images": images_by_partition[partition],
                "annotations": annotations_by_partition[partition],
                "categories": [{"id": 1, "name": "visible_card", "supercategory": "card"}],
            },
        )
    lineage_core = {
        "schema_version": "rfdetr-cluster-crop-lineage/v1",
        "campaign_id": "0071-m4-rfdetr-cluster-crop-segmentation",
        "records": records,
    }
    lineage = {**lineage_core, "lineage_digest": _digest(lineage_core)}
    _write_json(root / "lineage.json", lineage)
    generated = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {"materialization.json"}:
            generated.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    materialization_core = {
        "schema_version": "rfdetr-cluster-crop-materialization/v1",
        "materializer_version": "fixture",
        "campaign_id": "0071-m4-rfdetr-cluster-crop-segmentation",
        "generated_files": generated,
    }
    _write_json(
        root / "materialization.json",
        {**materialization_core, "materialization_digest": _digest(materialization_core)},
    )
    return root


def test_m5_fixture_consumes_m4_crops_and_pins_selected_0068_initializer(tmp_path: Path) -> None:
    view = _m4_view(tmp_path / "view")
    initializer = _bundle(tmp_path / "initializer")
    output = tmp_path / "campaign"

    report = run_rfdetr_cluster_crop_training(
        RfdetrClusterCropTrainingConfig(
            dataset_dir=view,
            initializer_bundle=initializer,
            output_dir=output,
            runner="fixture",
            device="cpu",
        )
    )

    assert report["status"] == "completed"
    assert report["dataset"]["schema_version"] == RFDETR_CLUSTER_CROP_DATASET_SCHEMA
    assert report["dataset"]["real_train_image_count"] == 1
    assert report["dataset"]["synthetic_train_image_count"] == 1
    assert report["dataset"]["validation_real_only"] is True
    assert report["initializer_bundle"]["campaign_id"] == (
        "0068-m0-reviewed-rfdetr-local-visible-card-detector"
    )
    assert report["checkpoint"]["weights_differ"] is True
    staged_image = output / "campaign-dataset" / "train" / "images" / "crop-000001.png"
    assert staged_image.is_symlink()
    assert staged_image.resolve() == (view / "train" / "images" / "crop-000001.png").resolve()


def test_m5_validation_reports_crop_source_and_overlap_metrics(tmp_path: Path) -> None:
    view = _m4_view(tmp_path / "view")
    initializer = _bundle(tmp_path / "initializer")
    campaign = tmp_path / "campaign"
    run_rfdetr_cluster_crop_training(
        RfdetrClusterCropTrainingConfig(
            dataset_dir=view,
            initializer_bundle=initializer,
            output_dir=campaign,
            runner="fixture",
            device="cpu",
        )
    )

    report = run_rfdetr_cluster_crop_validation(
        RfdetrClusterCropEvaluationConfig(
            dataset_dir=view,
            candidate_bundle=campaign / "bundle",
            output_dir=tmp_path / "evaluation",
            runner="fixture",
            device="cpu",
        )
    )

    crop = report["metrics"]["crop_coordinates"]
    source = report["metrics"]["source_coordinates"]
    assert crop["recall"] == 1.0
    assert crop["exact_card_count"]["exact_count_frames"] == 1
    assert source["overlapping_target_separation"]["overlapping_target_pairs"] == 1
    assert source["overlapping_target_separation"]["separation_rate"] == 1.0
    assert source["source_pixels_per_model_input_pixel"]["mean"] == {"x": 0.074074, "y": 0.074074}


def test_m5_rejects_real_crop_without_0072_scene_authority(tmp_path: Path) -> None:
    view = _m4_view(tmp_path / "view")
    lineage_path = view / "lineage.json"
    lineage = json.loads(lineage_path.read_text())
    lineage["records"][0]["scene_lineage"] = {"authority": "processor"}
    core = {key: value for key, value in lineage.items() if key != "lineage_digest"}
    lineage["lineage_digest"] = _digest(core)
    _write_json(lineage_path, lineage)
    materialization_path = view / "materialization.json"
    materialization = json.loads(materialization_path.read_text())
    for item in materialization["generated_files"]:
        if item["path"] == "lineage.json":
            item["sha256"] = hashlib.sha256(lineage_path.read_bytes()).hexdigest()
    materialization_core = {
        key: value for key, value in materialization.items() if key != "materialization_digest"
    }
    materialization["materialization_digest"] = _digest(materialization_core)
    _write_json(materialization_path, materialization)
    with pytest.raises(Exception, match="0072 scene authority"):
        load_rfdetr_cluster_crop_view(view)
