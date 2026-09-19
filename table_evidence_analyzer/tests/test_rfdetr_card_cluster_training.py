from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

import table_evidence_analyzer.rfdetr_card_cluster_training as campaign
from table_evidence_analyzer.rfdetr_card_cluster_training import (
    RfdetrCardClusterEvaluationConfig,
    RfdetrCardClusterTrainingConfig,
    RfdetrCardClusterTrainingError,
    load_rfdetr_card_cluster_bundle,
    run_rfdetr_card_cluster_training,
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _image_bytes(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (100, 80), color).save(output, format="JPEG")
    return output.getvalue()


def _write_view(root: Path) -> Path:
    images: list[dict[str, object]] = []
    annotations: list[dict[str, object]] = []
    lineage_frames: list[dict[str, object]] = []
    generated: list[dict[str, str]] = []
    for partition, color, image_id in (("train", (30, 50, 70), 1), ("valid", (60, 80, 100), 2)):
        image_name = f"image-{image_id:06d}.jpg"
        image_path = root / partition / "images" / image_name
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_bytes = _image_bytes(color)
        image_path.write_bytes(image_bytes)
        digest = hashlib.sha256(image_bytes).hexdigest()
        image = {
            "id": image_id,
            "file_name": f"images/{image_name}",
            "width": 100,
            "height": 80,
            "sha256": digest,
            "recording_id": f"recording-{partition}",
            "event_id": f"event-{image_id}",
            "trainer_partition": partition,
        }
        annotation = {
            "id": image_id,
            "image_id": image_id,
            "category_id": 1,
            "bbox": [10, 10, 20, 20],
            "area": 400,
            "iscrowd": 0,
            "cluster_id": "cluster-0001",
            "member_card_ids": [f"card-{image_id}"],
            "source_box": {"x_min": 10, "y_min": 10, "x_max": 30, "y_max": 30},
        }
        images.append(image)
        annotations.append(annotation)
        lineage_frames.append(
            {
                "frame_id": f"frame-{image_id}",
                "image_path": f"{partition}/images/{image_name}",
                "recording_id": f"recording-{partition}",
                "event_id": f"event-{image_id}",
                "source_cards": [
                    {
                        "card_id": f"card-{image_id}",
                        "proposal_id": "card-0001",
                        "tight_box": {"x_min": 10, "y_min": 10, "x_max": 30, "y_max": 30},
                        "source_frame_sha256": digest,
                    }
                ],
            }
        )
        generated.append(
            {
                "kind": "extracted_frame",
                "path": f"{partition}/images/{image_name}",
                "sha256": digest,
            }
        )

    for partition, _partition_name in (("train", "train"), ("valid", "validation")):
        partition_images = [image for image in images if image["trainer_partition"] == partition]
        partition_annotations = [
            annotation
            for annotation in annotations
            if annotation["image_id"] == partition_images[0]["id"]
        ]
        coco = {
            "info": {"campaign_id": "0068-m0-reviewed-rfdetr-local-visible-card-detector"},
            "licenses": [],
            "images": partition_images,
            "annotations": partition_annotations,
            "categories": [{"id": 1, "name": "card_cluster", "supercategory": "card"}],
        }
        path = root / partition / "_annotations.coco.json"
        path.write_bytes(_canonical(coco) + b"\n")
        generated.append(
            {
                "kind": "coco_annotations",
                "path": f"{partition}/_annotations.coco.json",
                "sha256": _digest_file(path),
            }
        )

    lineage = {
        "schema_version": "rfdetr-card-cluster-lineage/v1",
        "frames": lineage_frames,
    }
    lineage["lineage_digest"] = _digest(
        {key: value for key, value in lineage.items() if key != "lineage_digest"}
    )
    lineage_path = root / "lineage.json"
    lineage_path.write_bytes(_canonical(lineage) + b"\n")
    generated.append(
        {"kind": "lineage", "path": "lineage.json", "sha256": _digest_file(lineage_path)}
    )

    split_core = {
        "schema_version": "rfdetr-card-cluster-split/v1",
        "train": ["recording-train"],
        "validation": ["recording-valid"],
    }
    split = {**split_core, "digest": _digest(split_core)}
    split_path = root / "split.json"
    split_path.write_bytes(_canonical(split) + b"\n")
    generated.append(
        {"kind": "trainer_split", "path": "split.json", "sha256": _digest_file(split_path)}
    )
    generated.sort(key=lambda item: item["path"])

    materialization_core = {
        "schema_version": "rfdetr-card-cluster-materialization/v1",
        "materializer_version": "rfdetr-card-cluster-materializer/v1",
        "campaign_id": "0068-m0-reviewed-rfdetr-local-visible-card-detector",
        "campaign_manifest": {"manifest_digest": "a" * 64, "file_sha256": "b" * 64},
        "split": {
            "path": "split.json",
            "sha256": _digest_file(split_path),
            "digest": split["digest"],
        },
        "lineage": {"path": "lineage.json", "sha256": _digest_file(lineage_path)},
        "generated_files": generated,
        "counts": {"images": 2, "annotations": 2, "clusters": 2},
    }
    materialization = {
        **materialization_core,
        "materialization_digest": _digest(materialization_core),
    }
    (root / "materialization.json").write_bytes(_canonical(materialization) + b"\n")
    return root


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fixture_campaign_writes_small_bundle_and_calibrates_containment(tmp_path: Path) -> None:
    view = _write_view(tmp_path / "view")
    pretrained = tmp_path / "rf-detr-small.pt"
    pretrained.write_bytes(b"official pretrained RF-DETR Small checkpoint")
    output = tmp_path / "campaign"

    report = run_rfdetr_card_cluster_training(
        RfdetrCardClusterTrainingConfig(
            dataset_dir=view,
            pretrained_checkpoint=pretrained,
            output_dir=output,
            runner="fixture",
            device="cpu",
        )
    )

    assert report["status"] == "completed"
    assert report["model"]["class"] == "RFDETRSmall"
    assert report["model"]["resolution"] == [512, 512]
    assert report["checkpoint"]["weights_differ"] is True
    assert report["reload"] == {"status": "fixture_verified", "model_class": "RFDETRSmall"}
    assert report["validation"]["selected_threshold"] == 0.9
    assert report["validation"]["containment_floor_met"] is True

    bundle = load_rfdetr_card_cluster_bundle(output / "bundle")
    assert bundle.manifest["class_map"] == {"1": "card_cluster"}
    assert bundle.manifest["input_size"] == [512, 512]
    assert bundle.manifest["confidence_threshold"] == 0.9
    assert bundle.manifest["materialization_digest"] == report["materialization_digest"]
    assert bundle.checkpoint_path.read_bytes() != pretrained.read_bytes()

    second = run_rfdetr_card_cluster_training(
        RfdetrCardClusterTrainingConfig(
            dataset_dir=view,
            pretrained_checkpoint=pretrained,
            output_dir=output,
            runner="fixture",
            device="cpu",
        )
    )
    assert second == report


def test_validation_retains_missed_cards_and_extra_clusters(tmp_path: Path) -> None:
    view = _write_view(tmp_path / "view")
    checkpoint = tmp_path / "checkpoint.pth"
    checkpoint.write_bytes(b"trained")

    def predictions(_path: Path, _width: int, _height: int) -> list[dict[str, object]]:
        return [
            {
                "prediction_id": "cluster-extra",
                "score": 0.8,
                "box": {"x_min": 60, "y_min": 10, "x_max": 80, "y_max": 30},
            }
        ]

    with pytest.raises(RfdetrCardClusterTrainingError, match="containment recall floor"):
        campaign.evaluate_rfdetr_card_cluster_validation(
            RfdetrCardClusterEvaluationConfig(
                dataset_dir=view,
                checkpoint=checkpoint,
                output_dir=tmp_path / "validation",
                device="cpu",
                runner="fixture",
            ),
            prediction_provider=predictions,
        )


def test_real_runner_rejects_unavailable_device_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = _write_view(tmp_path / "view")
    pretrained = tmp_path / "rf-detr-small.pt"
    pretrained.write_bytes(b"official pretrained RF-DETR Small checkpoint")
    monkeypatch.setattr(campaign, "_requested_device_available", lambda _device: False)

    with pytest.raises(RfdetrCardClusterTrainingError, match="no fallback"):
        campaign.run_rfdetr_card_cluster_training(
            RfdetrCardClusterTrainingConfig(
                dataset_dir=view,
                pretrained_checkpoint=pretrained,
                output_dir=tmp_path / "campaign",
                runner="rfdetr",
                device="mps",
            )
        )

    record = json.loads((tmp_path / "campaign" / "run.json").read_text())
    assert record["status"] == "failed"
    assert record["failure"]["message"].endswith("no fallback is permitted")


def test_bundle_rejects_checkpoint_tampering(tmp_path: Path) -> None:
    view = _write_view(tmp_path / "view")
    pretrained = tmp_path / "rf-detr-small.pt"
    pretrained.write_bytes(b"official pretrained RF-DETR Small checkpoint")
    output = tmp_path / "campaign"
    run_rfdetr_card_cluster_training(
        RfdetrCardClusterTrainingConfig(
            dataset_dir=view,
            pretrained_checkpoint=pretrained,
            output_dir=output,
            runner="fixture",
            device="cpu",
        )
    )
    checkpoint = output / "bundle" / "checkpoint_best_total.pth"
    checkpoint.write_bytes(b"tampered")
    with pytest.raises(RfdetrCardClusterTrainingError, match="missing or changed"):
        load_rfdetr_card_cluster_bundle(output / "bundle")
