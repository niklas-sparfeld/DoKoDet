from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import table_evidence_analyzer.visible_cards as visible_cards
from table_evidence_analyzer.rfdetr_segmentation_evaluation import calculate_metrics
from table_evidence_analyzer.rfdetr_segmentation_training import (
    RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID,
    RFDETR_REVIEWED_DETECTOR_CAMPAIGN_RUN_SCHEMA,
    RFDETR_REVIEWED_DETECTOR_DATASET_SCHEMA,
    RFDETR_REVIEWED_DETECTOR_SMOKE_RUN_SCHEMA,
    RFDETR_SEGMENTATION_BUNDLE_SCHEMA,
    RFDETR_SEGMENTATION_CAMPAIGN_DATASET_SCHEMA,
    RFDETR_SEGMENTATION_CAMPAIGN_RUN_SCHEMA,
    RFDETR_SEGMENTATION_TRAINING_RUN_SCHEMA,
    RfdetrSegmentationCampaignTrainingConfig,
    RfdetrSegmentationTrainingConfig,
    RfdetrSegmentationTrainingError,
    load_rfdetr_segmentation_bundle,
    run_rfdetr_segmentation_campaign_training,
    run_rfdetr_segmentation_training,
)
from table_evidence_analyzer.visible_cards import (
    LOCAL_SEGMENTATION_PROVIDER_NAME,
    LocalVisibleCardSegmentationProvider,
    VisibleCardRequest,
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _image_bytes(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (24, 16), color).save(output, format="JPEG")
    return output.getvalue()


def _write_view(root: Path, *, reviewed: bool = False) -> Path:
    generated: list[dict[str, str]] = []
    coco_by_partition: dict[str, dict[str, object]] = {}
    samples = (
        ("train", 1, "recording-train", (20, 40, 60)),
        ("train", 2, "recording-train-2", (40, 60, 80)),
        ("valid", 3, "recording-valid", (60, 80, 100)),
    )
    if reviewed:
        samples += (("sealed_test", 4, "recording-sealed", (80, 100, 120)),)
    campaign_id = (
        RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID if reviewed else "0067-m0-rfdetr-segmentation"
    )
    for partition, image_id, recording_id, color in samples:
        image_name = f"image-{image_id:06d}.jpg"
        image_path = root / partition / "images" / image_name
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_bytes = _image_bytes(color)
        image_path.write_bytes(image_bytes)
        generated.append(
            {
                "kind": "extracted_frame",
                "path": f"{partition}/images/{image_name}",
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
            }
        )
        coco = {
            "info": {"campaign_id": campaign_id},
            "licenses": [],
            "images": [
                {
                    "id": image_id,
                    "file_name": f"images/{image_name}",
                    "width": 24,
                    "height": 16,
                    "sha256": hashlib.sha256(image_bytes).hexdigest(),
                    "recording_id": recording_id,
                    "event_id": f"event-{image_id}",
                    "reference_revision_id": f"revision-{image_id}",
                }
            ],
            "annotations": [
                {
                    "id": image_id,
                    "image_id": image_id,
                    "category_id": 1,
                    "bbox": [2, 2, 8, 8],
                    "area": 64.0,
                    "segmentation": [[2, 2, 10, 2, 10, 10, 2, 10]],
                    "iscrowd": 0,
                    "recording_id": recording_id,
                    "event_id": f"event-{image_id}",
                    "card_id": f"card-{image_id}",
                }
            ],
            "categories": [{"id": 1, "name": "visible_card", "supercategory": "card"}],
        }
        aggregate = coco_by_partition.setdefault(
            partition,
            {
                "info": coco["info"],
                "licenses": [],
                "images": [],
                "annotations": [],
                "categories": coco["categories"],
            },
        )
        aggregate["images"].extend(coco["images"])
        aggregate["annotations"].extend(coco["annotations"])

    for partition, coco in coco_by_partition.items():
        annotation_path = root / partition / "_annotations.coco.json"
        annotation_path.write_bytes(_canonical(coco) + b"\n")
        generated.append(
            {
                "kind": "coco_annotations",
                "path": f"{partition}/_annotations.coco.json",
                "sha256": hashlib.sha256(annotation_path.read_bytes()).hexdigest(),
            }
        )

    split = {
        "schema_version": "rfdetr-segmentation-split/v1",
        "campaign_manifest_digest": "a" * 64,
        "train": ["recording-train", "recording-train-2"],
        "validation": ["recording-valid"],
        "test": [],
    }
    split["split_digest"] = _digest(
        {key: value for key, value in split.items() if key != "split_digest"}
    )
    split_path = root / "split.json"
    split_path.write_bytes(_canonical(split) + b"\n")
    generated.append(
        {
            "kind": "trainer_split",
            "path": "split.json",
            "sha256": hashlib.sha256(split_path.read_bytes()).hexdigest(),
        }
    )
    exclusions = {"excluded_frames": [], "ineligible_outcomes": []}
    exclusions_path = root / "exclusions.json"
    exclusions_path.write_bytes(_canonical(exclusions) + b"\n")
    generated.append(
        {
            "kind": "exclusion_receipt",
            "path": "exclusions.json",
            "sha256": hashlib.sha256(exclusions_path.read_bytes()).hexdigest(),
        }
    )
    generated.sort(key=lambda item: item["path"])
    core = {
        "schema_version": "rfdetr-segmentation-materialization/v1",
        "materializer_version": "rfdetr-segmentation-materializer/v1",
        "campaign_manifest": {"manifest_digest": "a" * 64},
        "frame_extraction": {},
        "target_conversion": {},
        "ignore_policy": "exclude_frame_on_any_reviewed_ignore_region",
        "split": {"path": "split.json", "sha256": generated[-2]["sha256"]},
        "inputs": [],
        "exclusions": {},
        "counts": {
            "images": len(samples),
            "annotations": len(samples),
            **({"sealed_test_images": 1, "sealed_test_annotations": 1} if reviewed else {}),
        },
        "campaign_id": campaign_id,
        "generated_files": generated,
    }
    materialization = {**core, "materialization_digest": _digest(core)}
    (root / "materialization.json").write_bytes(_canonical(materialization) + b"\n")
    return root


def _config(tmp_path: Path, *, runner: str = "fixture") -> tuple[Path, Path, Path]:
    view = _write_view(tmp_path / "view")
    pretrained = tmp_path / "rf-detr-seg-medium.pt"
    pretrained.write_bytes(b"fixture pretrained weights")
    output = tmp_path / "run"
    run_rfdetr_segmentation_training(
        RfdetrSegmentationTrainingConfig(
            dataset_dir=view,
            pretrained_checkpoint=pretrained,
            output_dir=output,
            runner=runner,
            device="cpu",
            train_image_count=2,
            validation_image_count=1,
        )
    )
    return view, pretrained, output


def _campaign_manifest(view: Path, pretrained: Path) -> Path:
    recipe = {
        "schema_version": "rfdetr-segmentation-recipe/v1",
        "model": {
            "class": "RFDETRSegMedium",
            "variant": "rfdetr-seg-medium",
            "class_names": ["visible_card"],
            "num_classes": 1,
            "resolution": [432, 432],
        },
        "package": {"name": "rfdetr", "version": "1.9.4"},
        "pretrained_checkpoint": {
            "name": "rf-detr-seg-medium.pt",
            "path": str(pretrained),
            "sha256": hashlib.sha256(pretrained.read_bytes()).hexdigest(),
        },
        "augmentation": {
            "policy_id": "rfdetr-default-v1",
            "multi_scale": True,
            "expanded_scales": True,
            "do_random_resize_via_padding": False,
            "use_ema": True,
        },
        "training": {
            "batch_size": 1,
            "grad_accum_steps": 4,
            "effective_batch_size": 4,
            "epochs": 40,
            "seed": 6701,
            "num_workers": 0,
            "device": "mps",
            "mixed_precision": False,
            "output_dir_name": "rfdetr-segmentation-0067",
        },
        "early_stopping": {
            "enabled": True,
            "monitor": "val/mask_ap_50_95",
            "patience": 8,
            "min_delta": 0.001,
        },
    }
    manifest_core = {
        "schema_version": "rfdetr-segmentation-campaign-manifest/v1",
        "campaign_id": "0067-m0-rfdetr-segmentation",
        "milestone": "M0",
        "read_only": True,
        "freeze_state": "frozen",
        "recipe": recipe,
        "recipe_sha256": _digest(recipe),
    }
    manifest = {
        **manifest_core,
        "manifest_digest": _digest(manifest_core),
    }
    manifest_path = view.parent / "m0-manifest.json"
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    materialization_path = view / "materialization.json"
    materialization = json.loads(materialization_path.read_text())
    materialization_core = {
        key: value for key, value in materialization.items() if key != "materialization_digest"
    }
    materialization_core["campaign_manifest"] = {
        "manifest_digest": manifest["manifest_digest"],
        "file_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    materialization = {
        **materialization_core,
        "materialization_digest": _digest(materialization_core),
    }
    materialization_path.write_bytes(_canonical(materialization) + b"\n")
    return manifest_path


def _reviewed_campaign_manifest(view: Path, pretrained: Path) -> Path:
    checkpoint_digest = hashlib.sha256(pretrained.read_bytes()).hexdigest()
    recipe = {
        "schema_version": "rfdetr-segmentation-recipe/v1",
        "model": {
            "class": "RFDETRSegMedium",
            "variant": "rfdetr-seg-medium",
            "class_names": ["visible_card"],
            "num_classes": 1,
            "resolution": [432, 432],
        },
        "package": {"name": "rfdetr", "version": "1.9.4"},
        "pretrained_checkpoint": {"name": "rf-detr-seg-medium.pt", "sha256": checkpoint_digest},
        "augmentation": {
            "policy_id": "rfdetr-default-v1",
            "multi_scale": True,
            "expanded_scales": True,
            "do_random_resize_via_padding": False,
            "use_ema": True,
        },
        "training": {
            "batch_size": 1,
            "grad_accum_steps": 4,
            "effective_batch_size": 4,
            "epochs": 40,
            "seed": 6701,
            "num_workers": 0,
            "device": "mps",
            "mixed_precision": False,
            "output_dir_name": "rfdetr-segmentation-0068",
        },
        "early_stopping": {"enabled": True, "patience": 8, "min_delta": 0.001},
        "data_contract": {"test_partition": "sealed_test"},
        "validation": {"checkpoint_selection": "highest_validation_mask_ap_50_95_then_recall"},
    }
    manifest_core = {
        "schema_version": "rfdetr-visible-card-detector-manifest/v1",
        "campaign_id": RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID,
        "milestone": "M0",
        "read_only": True,
        "freeze_state": "frozen",
        "recipe": recipe,
        "recipe_sha256": _digest(recipe),
    }
    manifest = {**manifest_core, "manifest_digest": _digest(manifest_core)}
    manifest_path = view.parent / "reviewed-m0-manifest.json"
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    split_path = view / "split.json"
    split = json.loads(split_path.read_text())
    split_core = {key: value for key, value in split.items() if key != "split_digest"}
    split_core["campaign_manifest_digest"] = manifest["manifest_digest"]
    split = {**split_core, "split_digest": _digest(split_core)}
    split_path.write_bytes(_canonical(split) + b"\n")
    materialization_path = view / "materialization.json"
    materialization = json.loads(materialization_path.read_text())
    materialization_core = {
        key: value for key, value in materialization.items() if key != "materialization_digest"
    }
    materialization_core["campaign_manifest"] = {
        "manifest_digest": manifest["manifest_digest"],
        "file_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    for item in materialization_core["generated_files"]:
        if item["path"] == "split.json":
            item["sha256"] = hashlib.sha256(split_path.read_bytes()).hexdigest()
    materialization = {
        **materialization_core,
        "materialization_digest": _digest(materialization_core),
    }
    materialization_path.write_bytes(_canonical(materialization) + b"\n")
    return manifest_path


def test_fixture_training_freezes_segmentation_identity_and_arguments(tmp_path: Path) -> None:
    view, pretrained, output = _config(tmp_path)

    record = json.loads((output / "run.json").read_text())
    assert record["schema_version"] == RFDETR_SEGMENTATION_TRAINING_RUN_SCHEMA
    assert record["status"] == "completed"
    assert record["model"]["class"] == "RFDETRSegMedium"
    assert record["training_arguments"] == {
        "dataset_dir": str((output / "smoke-dataset").resolve()),
        "dataset_file": "roboflow",
        "output_dir": str((output / "rfdetr").resolve()),
        "epochs": 1,
        "batch_size": 1,
        "grad_accum_steps": 4,
        "num_workers": 0,
        "seed": 6701,
        "resolution": 432,
        "device": "cpu",
        "class_names": ["visible_card"],
        "run_test": False,
        "use_ema": True,
        "multi_scale": True,
        "expanded_scales": True,
        "do_random_resize_via_padding": False,
        "tensorboard": False,
        "wandb": False,
        "progress_bar": None,
    }
    assert record["model_arguments"] == {
        "num_classes": 1,
        "pretrain_weights": str(pretrained.resolve()),
        "resolution": 432,
    }
    assert record["checkpoint"]["weights_differ"] is True
    assert record["subset"]["train_image_count"] == 2
    assert record["subset"]["validation_image_count"] == 1
    assert record["bundle"]["schema_version"] == RFDETR_SEGMENTATION_BUNDLE_SCHEMA

    bundle = load_rfdetr_segmentation_bundle(output / "bundle")
    assert bundle.manifest["component"] == "visible-card-segmentation"
    assert bundle.manifest["model"]["class"] == "RFDETRSegMedium"
    assert bundle.checkpoint_path.name == "checkpoint_best_total.pth"
    assert view.joinpath("train/images").is_dir()


def test_campaign_fixture_uses_all_m1_images_and_frozen_training_recipe(tmp_path: Path) -> None:
    view = _write_view(tmp_path / "view")
    pretrained = tmp_path / "rf-detr-seg-medium.pt"
    pretrained.write_bytes(b"fixture pretrained weights")
    manifest = _campaign_manifest(view, pretrained)
    output = tmp_path / "campaign"
    config = RfdetrSegmentationCampaignTrainingConfig(
        dataset_dir=view,
        campaign_manifest=manifest,
        pretrained_checkpoint=pretrained,
        output_dir=output,
        runner="fixture",
        device="cpu",
    )

    report = run_rfdetr_segmentation_campaign_training(config)
    record = json.loads((output / "run.json").read_text())

    assert report["run_id"] == record["run_id"]
    assert record["schema_version"] == RFDETR_SEGMENTATION_CAMPAIGN_RUN_SCHEMA
    assert record["status"] == "completed"
    manifest_data = json.loads(manifest.read_text())
    assert record["campaign_manifest"]["manifest_digest"] == manifest_data["manifest_digest"]
    assert record["dataset"]["schema_version"] == RFDETR_SEGMENTATION_CAMPAIGN_DATASET_SCHEMA
    assert record["dataset"]["train_image_count"] == 2
    assert record["dataset"]["validation_image_count"] == 1
    assert record["training_arguments"] == {
        "dataset_dir": str((output / "campaign-dataset").resolve()),
        "dataset_file": "roboflow",
        "output_dir": str((output / "rfdetr").resolve()),
        "epochs": 40,
        "batch_size": 1,
        "grad_accum_steps": 4,
        "num_workers": 0,
        "seed": 6701,
        "resolution": 432,
        "device": "cpu",
        "class_names": ["visible_card"],
        "run_test": False,
        "use_ema": True,
        "multi_scale": True,
        "expanded_scales": True,
        "do_random_resize_via_padding": False,
        "early_stopping": True,
        "early_stopping_patience": 8,
        "early_stopping_min_delta": 0.001,
        "tensorboard": False,
        "wandb": False,
        "progress_bar": None,
        "eval_interval": 1,
        "save_dataset_grids": False,
    }
    assert record["model_arguments"] == {
        "num_classes": 1,
        "pretrain_weights": str(pretrained.resolve()),
        "resolution": 432,
        "amp": False,
    }
    assert len(list((output / "campaign-dataset" / "train" / "images").iterdir())) == 2
    assert len(list((output / "campaign-dataset" / "valid" / "images").iterdir())) == 1
    assert record["bundle"]["schema_version"] == RFDETR_SEGMENTATION_BUNDLE_SCHEMA

    rerun = run_rfdetr_segmentation_campaign_training(config)
    assert rerun["run_id"] == record["run_id"]


def test_campaign_resume_reuses_staged_dataset_and_records_checkpoint(tmp_path: Path) -> None:
    view = _write_view(tmp_path / "view")
    pretrained = tmp_path / "rf-detr-seg-medium.pt"
    pretrained.write_bytes(b"fixture pretrained weights")
    manifest = _campaign_manifest(view, pretrained)
    output = tmp_path / "campaign"
    initial_config = RfdetrSegmentationCampaignTrainingConfig(
        dataset_dir=view,
        campaign_manifest=manifest,
        pretrained_checkpoint=pretrained,
        output_dir=output,
        runner="fixture",
        device="cpu",
    )

    run_rfdetr_segmentation_campaign_training(initial_config)
    staged_snapshot = {
        path.relative_to(output / "campaign-dataset").as_posix(): path.read_bytes()
        for path in (output / "campaign-dataset").rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    resume_checkpoint = output / "rfdetr" / "last.ckpt"
    resume_checkpoint.write_bytes(b"fixture full resume checkpoint")
    shutil.rmtree(output / "bundle")
    (output / "run.json").unlink()

    resumed = run_rfdetr_segmentation_campaign_training(
        replace(initial_config, resume=resume_checkpoint)
    )
    record = json.loads((output / "run.json").read_text())
    resumed_snapshot = {
        path.relative_to(output / "campaign-dataset").as_posix(): path.read_bytes()
        for path in (output / "campaign-dataset").rglob("*")
        if path.is_file() and not path.is_symlink()
    }

    assert resumed["status"] == "completed"
    assert record["resumed_from"] == str(resume_checkpoint.resolve())
    assert record["training_arguments"]["resume"] == str(resume_checkpoint.resolve())
    assert staged_snapshot == resumed_snapshot


def test_reviewed_detector_smoke_records_matching_m0_m1_and_device_facts(tmp_path: Path) -> None:
    view = _write_view(tmp_path / "view", reviewed=True)
    pretrained = tmp_path / "rf-detr-seg-medium.pt"
    pretrained.write_bytes(b"fixture reviewed pretrained weights")
    manifest = _reviewed_campaign_manifest(view, pretrained)
    output = tmp_path / "smoke"

    report = run_rfdetr_segmentation_training(
        RfdetrSegmentationTrainingConfig(
            dataset_dir=view,
            campaign_manifest=manifest,
            pretrained_checkpoint=pretrained,
            output_dir=output,
            runner="fixture",
            device="cpu",
            train_image_count=2,
            validation_image_count=1,
        )
    )

    assert report["schema_version"] == RFDETR_REVIEWED_DETECTOR_SMOKE_RUN_SCHEMA
    assert report["campaign_id"] == RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID
    assert (
        report["campaign_manifest"]["manifest_digest"]
        == json.loads(manifest.read_text())["manifest_digest"]
    )
    assert (
        report["materialization_digest"]
        == json.loads((view / "materialization.json").read_text())["materialization_digest"]
    )
    assert report["resource_facts"]["requested_device"] == "cpu"
    assert report["checkpoint"]["weights_differ"] is True
    assert report["bundle"]["schema_version"] == RFDETR_SEGMENTATION_BUNDLE_SCHEMA
    assert report["stages"]["reload"] == "skipped"
    assert report["stages"]["inference"] == "skipped"
    assert load_rfdetr_segmentation_bundle(output / "bundle").manifest["campaign_id"] == (
        RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID
    )


def test_reviewed_detector_campaign_uses_all_m1_images_and_reuses_verified_run(
    tmp_path: Path,
) -> None:
    view = _write_view(tmp_path / "view", reviewed=True)
    pretrained = tmp_path / "rf-detr-seg-medium.pt"
    pretrained.write_bytes(b"fixture reviewed pretrained weights")
    manifest = _reviewed_campaign_manifest(view, pretrained)
    output = tmp_path / "campaign"
    config = RfdetrSegmentationCampaignTrainingConfig(
        dataset_dir=view,
        campaign_manifest=manifest,
        pretrained_checkpoint=pretrained,
        output_dir=output,
        runner="fixture",
        device="cpu",
    )

    report = run_rfdetr_segmentation_campaign_training(config)
    record = json.loads((output / "run.json").read_text())
    rerun = run_rfdetr_segmentation_campaign_training(config)

    assert report["schema_version"] == RFDETR_REVIEWED_DETECTOR_CAMPAIGN_RUN_SCHEMA
    assert record["campaign_id"] == RFDETR_REVIEWED_DETECTOR_CAMPAIGN_ID
    assert record["dataset"]["schema_version"] == RFDETR_REVIEWED_DETECTOR_DATASET_SCHEMA
    assert record["dataset"]["train_image_count"] == 2
    assert record["dataset"]["validation_image_count"] == 1
    assert record["checkpoint_selection"] == "highest_validation_mask_ap_50_95_then_recall"
    assert rerun == record


def test_failure_writes_resumable_segmentation_run_record(tmp_path: Path) -> None:
    view = _write_view(tmp_path / "view")
    output = tmp_path / "run"
    missing = tmp_path / "missing.pt"

    with pytest.raises(RfdetrSegmentationTrainingError, match="pretrained checkpoint"):
        run_rfdetr_segmentation_training(
            RfdetrSegmentationTrainingConfig(
                dataset_dir=view,
                pretrained_checkpoint=missing,
                output_dir=output,
                runner="fixture",
                device="cpu",
            )
        )

    record = json.loads((output / "run.json").read_text())
    assert record["schema_version"] == RFDETR_SEGMENTATION_TRAINING_RUN_SCHEMA
    assert record["status"] == "failed"
    assert record["resumable"]["supported"] is True
    assert record["resumable"]["next_stage"] == "inputs"
    assert record["failure"]["type"] == "RfdetrSegmentationTrainingError"
    assert record["finished_at"]


def test_segmentation_provider_uses_mask_and_distinct_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _view, _pretrained, output = _config(tmp_path)
    monkeypatch.setattr(
        visible_cards,
        "_mask_to_polygons",
        lambda _mask: [[[2, 2], [10, 2], [10, 10], [2, 10]]],
    )

    class Detector:
        def predict(self, _image: object, **_kwargs: object) -> object:
            return SimpleNamespace(
                xyxy=[[1, 1, 12, 12]],
                confidence=[0.9],
                class_id=[0],
                mask=[[[True]]],
            )

    provider = LocalVisibleCardSegmentationProvider(
        output / "bundle", device="cpu", detector=Detector()
    )
    image = _image_bytes((120, 80, 40))
    result = provider.propose(
        VisibleCardRequest(
            package_id="smoke",
            frame_part_name="image-000001",
            target_offset_ms=0,
            image_bytes=image,
            width=24,
            height=16,
            provider=LOCAL_SEGMENTATION_PROVIDER_NAME,
            model="rfdetr-seg-medium",
        )
    )

    assert result.status == "ok"
    assert provider.bundle_identity["schema_version"] == RFDETR_SEGMENTATION_BUNDLE_SCHEMA
    assert result.proposals[0].box_2d.to_mapping() == {
        "x_min": 83,
        "y_min": 125,
        "x_max": 417,
        "y_max": 625,
    }
    assert result.raw_response["detections"][0]["geometry_source"] == "segmentation_mask"


def test_locked_metrics_count_mask_matches_false_duplicates_and_empty_frames() -> None:
    target = {
        "annotation_id": 1,
        "card_id": "card-1",
        "polygons": [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]],
        "box_xywh": [0.0, 0.0, 10.0, 10.0],
        "width": 40,
        "height": 40,
    }
    prediction = {
        "score": 0.9,
        "polygons": target["polygons"],
        "box_xywh": target["box_xywh"],
        "width": 40,
        "height": 40,
    }
    metrics = calculate_metrics(
        [
            {
                "image_id": 1,
                "targets": [target],
                "predictions": [prediction, {**prediction, "score": 0.8}],
            },
            {
                "image_id": 2,
                "targets": [{**target, "annotation_id": 2, "card_id": "card-2"}],
                "predictions": [],
            },
        ]
    )

    assert metrics["recall"] == 0.5
    assert metrics["false_predictions"] == 1
    assert metrics["duplicate_predictions"] == 1
    assert metrics["empty_prediction_rate"] == 0.5
    assert metrics["mask_ap50"] == pytest.approx(0.50495)
