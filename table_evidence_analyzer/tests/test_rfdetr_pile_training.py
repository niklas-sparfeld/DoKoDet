from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import table_evidence_analyzer.rfdetr_segmentation_training as segmentation_training
from table_evidence_analyzer.rfdetr_segmentation_training import (
    RFDETR_PILE_CLASS_MAP,
    RFDETR_PILE_MASK_POLICY,
    RfdetrSegmentationCampaignTrainingConfig,
    RfdetrSegmentationTrainingConfig,
    load_rfdetr_segmentation_bundle,
    run_rfdetr_segmentation_campaign_training,
    run_rfdetr_segmentation_training,
)
from table_evidence_analyzer.visible_cards import (
    LocalVisibleCardSegmentationProvider,
    VisibleCardRequest,
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _build_pile_view(root: Path) -> tuple[Path, Path]:
    image_root = root / "train" / "images"
    image_root.mkdir(parents=True)
    valid_root = root / "valid" / "images"
    valid_root.mkdir(parents=True)
    generated: list[dict[str, str]] = []
    categories = [
        {"id": 1, "name": "visible_card", "supercategory": "card"},
        {"id": 2, "name": "card_pile", "supercategory": "card"},
    ]
    for partition, image_id in (("train", 1), ("valid", 2)):
        path = root / partition / "images" / f"{image_id}.png"
        Image.new("RGB", (8, 6), (120, 80, 40)).save(path)
        image_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        generated.append({"path": f"{partition}/images/{image_id}.png", "sha256": image_digest})
        image = {
            "id": image_id,
            "file_name": f"images/{image_id}.png",
            "width": 8,
            "height": 6,
            "sha256": image_digest,
            "recording_id": f"recording-{partition}",
            "event_id": f"event-{image_id}",
        }
        annotations = [
            {
                "id": image_id * 10,
                "image_id": image_id,
                "category_id": 1,
                "bbox": [0, 0, 2, 2],
                "area": 4,
                "segmentation": [[0, 0, 2, 0, 2, 2, 0, 2]],
                "iscrowd": 0,
                "card_id": f"card-{image_id}",
                "card_side": "face_up",
            },
            {
                "id": image_id * 10 + 1,
                "image_id": image_id,
                "category_id": 2,
                "bbox": [3, 1, 4, 4],
                "area": 12,
                "segmentation": {"size": [6, 8], "counts": [11, 2, 4, 2, 4, 2, 4, 2, 17]},
                "iscrowd": 0,
                "grouped_candidate_ids": [f"candidate-{image_id}"],
            },
        ]
        coco = {
            "info": {"campaign_id": "0091-m2-reviewed-two-class-pile-export"},
            "licenses": [],
            "images": [image],
            "annotations": annotations,
            "categories": categories,
        }
        coco_path = root / partition / "_annotations.coco.json"
        coco_path.write_bytes(_canonical(coco) + b"\n")
        generated.append(
            {
                "path": f"{partition}/_annotations.coco.json",
                "sha256": hashlib.sha256(coco_path.read_bytes()).hexdigest(),
            }
        )
    m2_core = {
        "schema_version": "rfdetr-pile-segmentation-manifest/v1",
        "campaign_id": "0091-m2-reviewed-two-class-pile-export",
        "milestone": "M2",
        "read_only": True,
        "freeze_state": "frozen",
        "recipe": {"package": {"name": "rfdetr", "version": "1.9.4"}},
        "recipe_sha256": _digest({"package": {"name": "rfdetr", "version": "1.9.4"}}),
    }
    m2_manifest = {**m2_core, "manifest_digest": _digest(m2_core)}
    manifest_path = root / "m2-manifest.json"
    manifest_path.write_bytes(_canonical(m2_manifest) + b"\n")
    materialization_core = {
        "schema_version": "rfdetr-segmentation-materialization/v1",
        "campaign_id": "0091-m2-reviewed-two-class-pile-export",
        "campaign_manifest": {"manifest_digest": m2_manifest["manifest_digest"]},
        "target_conversion": {
            **RFDETR_PILE_MASK_POLICY,
            "categories": [
                {"id": 1, "name": "visible_card", "supercategory": "card"},
                {"id": 2, "name": "card_pile", "supercategory": "card"},
            ],
        },
        "review_readiness": {"two_class_ready": True},
        "generated_files": generated,
    }
    (root / "materialization.json").write_bytes(
        _canonical(
            {
                **materialization_core,
                "materialization_digest": _digest(materialization_core),
            }
        )
        + b"\n"
    )
    return root, manifest_path


def test_two_class_smoke_stages_piles_and_bundles_explicit_class_map(tmp_path: Path) -> None:
    view, manifest = _build_pile_view(tmp_path / "view")
    pretrained = tmp_path / "pretrained.pt"
    pretrained.write_bytes(b"pinned fixture checkpoint")
    output = tmp_path / "smoke"

    record = run_rfdetr_segmentation_training(
        RfdetrSegmentationTrainingConfig(
            dataset_dir=view,
            campaign_manifest=manifest,
            pretrained_checkpoint=pretrained,
            output_dir=output,
            runner="fixture",
            device="cpu",
            train_image_count=1,
            validation_image_count=1,
        )
    )

    assert record["status"] == "completed"
    assert record["model"]["num_classes"] == 2
    assert record["class_map"] == RFDETR_PILE_CLASS_MAP
    assert record["training_arguments"]["class_names"] == ["visible_card", "card_pile"]
    assert record["loss_confirmation"]["finite"] is True
    bundle = load_rfdetr_segmentation_bundle(output / "bundle")
    assert bundle.manifest["class_map"] == RFDETR_PILE_CLASS_MAP
    assert bundle.manifest["num_classes"] == 2
    assert bundle.manifest["mask_policy"] == RFDETR_PILE_MASK_POLICY
    assert bundle.manifest["campaign_id"] == "0091-m2-reviewed-two-class-pile-export"


def test_two_class_campaign_fixture_preserves_category_contract(tmp_path: Path) -> None:
    view, manifest = _build_pile_view(tmp_path / "view")
    pretrained = tmp_path / "pretrained.pt"
    pretrained.write_bytes(b"pinned fixture checkpoint")

    record = run_rfdetr_segmentation_campaign_training(
        RfdetrSegmentationCampaignTrainingConfig(
            dataset_dir=view,
            campaign_manifest=manifest,
            pretrained_checkpoint=pretrained,
            output_dir=tmp_path / "campaign",
            runner="fixture",
            device="cpu",
        )
    )

    assert record["schema_version"] == "rfdetr-pile-segmentation-training-run/v1"
    assert record["class_map"] == RFDETR_PILE_CLASS_MAP
    assert record["model"]["num_classes"] == 2
    assert record["training_arguments"]["class_names"] == ["visible_card", "card_pile"]
    bundle = load_rfdetr_segmentation_bundle(record["bundle"]["path"])
    assert bundle.manifest["class_map"] == RFDETR_PILE_CLASS_MAP
    assert bundle.manifest["mask_policy"] == RFDETR_PILE_MASK_POLICY


def test_segmentation_provider_keeps_pile_predictions_separate(tmp_path: Path, monkeypatch) -> None:
    bundle = SimpleNamespace(
        manifest={
            "schema_version": "rfdetr-segmentation-bundle/v1",
            "bundle_digest": "a" * 64,
            "checkpoint_sha256": "b" * 64,
            "run_id": "fixture-run",
        }
    )
    monkeypatch.setattr(
        segmentation_training, "load_rfdetr_segmentation_bundle", lambda _path: bundle
    )

    class Detector:
        def predict(self, *_args, **_kwargs):
            return SimpleNamespace(
                xyxy=[[10, 10, 30, 30], [5, 5, 50, 50], [6, 6, 49, 49]],
                confidence=[0.91, 0.87, 0.75],
                class_id=[0, 1, 1],
                mask=None,
            )

    image_path = tmp_path / "frame.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(image_path)
    request = VisibleCardRequest(
        package_id="fixture",
        frame_part_name="frame-1",
        target_offset_ms=0,
        image_bytes=image_path.read_bytes(),
        width=64,
        height=64,
        provider="local-rfdetr-segmentation",
    )
    provider = LocalVisibleCardSegmentationProvider("fixture-bundle", detector=Detector())
    result = provider.propose(request)

    assert result.status == "ok"
    assert len(result.proposals) == 1
    assert len(result.pile_proposals) == 1
    assert result.pile_proposals[0].confidence == 0.87
    assert result.raw_response["pile_detection_supported"] is True
    assert any(
        item["geometry_source"] == "duplicate_pile_prediction"
        for item in result.raw_response["skipped_detections"]
    )
    round_trip = type(result).from_mapping(result.to_mapping())
    assert round_trip.pile_proposals == result.pile_proposals
