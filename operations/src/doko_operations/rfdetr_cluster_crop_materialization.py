"""Materialize the epic 0071 M4 cluster-crop segmentation view.

Real rows use only the reviewed card-scene derivation from epic 0072.  The frozen epic 0070
synthetic train view is added after the same deterministic cluster and crop transform.  The
result is a disposable COCO instance-segmentation view with source-linked crop and scene lineage.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, UnidentifiedImageError
from table_evidence_analyzer.visible_card_cascade import (
    CASCADE_FINE_INPUT_SIZE,
    CASCADE_FINE_MODEL_CLASS,
    CASCADE_RFDETR_VERSION,
    CardCluster,
    ClusterCrop,
    CoarseProposal,
    CoordinateTransform,
    Padding,
    PixelBox,
    PixelPoint,
    build_cascade_layout,
    frozen_cascade_recipe,
)
from table_evidence_analyzer.visible_card_cascade_provider import crop_source_image

from .card_plane_geometry import CardPlaneGeometryError, validate_pose_scene_candidate_view
from .reviewed_rfdetr_detector_campaign import (
    RFDETR_DETECTOR_CAMPAIGN_ID,
    RFDETR_DETECTOR_MANIFEST_SCHEMA_VERSION,
    ReviewedRfdetrDetectorCampaignError,
    validate_reviewed_rfdetr_detector_manifest,
)
from .rfdetr_segmentation_campaign import canonical_json_bytes, sha256_json
from .rfdetr_segmentation_materialization import (
    _default_frame_extractor,
    _recordings_by_id,
    _validated_samples,
    _verify_source_videos,
    validate_rfdetr_coco_annotations,
)

RFDETR_CLUSTER_CROP_MATERIALIZATION_SCHEMA = "rfdetr-cluster-crop-materialization/v1"
RFDETR_CLUSTER_CROP_MATERIALIZER_VERSION = "rfdetr-cluster-crop-materializer/v1"
RFDETR_CLUSTER_CROP_SPLIT_SCHEMA = "rfdetr-cluster-crop-split/v1"
RFDETR_CLUSTER_CROP_LINEAGE_SCHEMA = "rfdetr-cluster-crop-lineage/v1"
RFDETR_CLUSTER_CROP_EXCLUSIONS_SCHEMA = "rfdetr-cluster-crop-exclusions/v1"
RFDETR_CLUSTER_CROP_COVERAGE_SCHEMA = "rfdetr-cluster-crop-coverage/v1"
RFDETR_CLUSTER_CROP_SCALE_SCHEMA = "rfdetr-cluster-crop-scale/v1"
RFDETR_CLUSTER_CROP_CONTACT_SHEET_SCHEMA = "rfdetr-cluster-crop-contact-sheet/v1"
RFDETR_CLUSTER_CROP_CAMPAIGN_ID = "0071-m4-rfdetr-cluster-crop-segmentation"
RFDETR_CLUSTER_CROP_PERTURBATION_POLICY = "quarter-span-diagonal-shift-v1"
RFDETR_CLUSTER_CROP_SYNTHETIC_VIEW_DEFAULT = (
    ".runtime/synthetic-visible-region-0070-m4-50-50/synthetic-candidate-view"
)
RFDETR_CLUSTER_CROP_SYNTHETIC_MANIFEST_DEFAULT = (
    "data/operations/synthetic-visible-region-0070-m5-50-50-training-view.json"
)
TRAINING_PARTITIONS = ("train", "validation")
TARGET_CATEGORY = {"id": 1, "name": "visible_card", "supercategory": "card"}
_SHA256 = set("0123456789abcdef")
FrameExtractor = Callable[[Path, Mapping[str, Any]], bytes]


class RfdetrClusterCropMaterializationError(ValueError):
    """The frozen M4 inputs cannot be converted into a safe crop view."""


@dataclass(frozen=True, slots=True)
class RfdetrClusterCropMaterializationResult:
    """The disposable M4 trainer view and its immutable input identity."""

    view_root: Path
    real_crop_count: int
    synthetic_crop_count: int
    annotation_count: int
    materialization_digest: str
    lineage_digest: str
    contact_sheet_digest: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "view_root": str(self.view_root),
            "real_crop_count": self.real_crop_count,
            "synthetic_crop_count": self.synthetic_crop_count,
            "annotation_count": self.annotation_count,
            "materialization_digest": self.materialization_digest,
            "lineage_digest": self.lineage_digest,
            "contact_sheet_digest": self.contact_sheet_digest,
        }


def materialize_rfdetr_cluster_crop_dataset(
    manifest_path: str | Path,
    *,
    repository_root: str | Path,
    output_root: str | Path | None = None,
    frame_extractor: FrameExtractor | None = None,
    synthetic_view_root: str | Path | None = RFDETR_CLUSTER_CROP_SYNTHETIC_VIEW_DEFAULT,
    synthetic_manifest_path: str | Path | None = RFDETR_CLUSTER_CROP_SYNTHETIC_MANIFEST_DEFAULT,
    include_synthetic: bool = True,
) -> RfdetrClusterCropMaterializationResult:
    """Build the deterministic real-plus-synthetic train and real validation crop view."""

    repository = Path(repository_root).expanduser().resolve()
    source_manifest_path = _resolve_file(manifest_path, repository, "0068 M0 manifest")
    manifest = _read_json(source_manifest_path, "0068 M0 manifest")
    _validate_input_manifest(manifest)
    try:
        samples = _validated_samples(manifest)
        recordings = _recordings_by_id(manifest)
    except (KeyError, TypeError, ValueError) as error:
        raise RfdetrClusterCropMaterializationError(
            f"0068 M0 samples are invalid: {error}"
        ) from error
    real_samples = [sample for sample in samples if sample["split"] in TRAINING_PARTITIONS]
    if not real_samples:
        raise RfdetrClusterCropMaterializationError("M4 has no train or validation samples")
    real_recording_ids = {str(sample["recording_id"]) for sample in real_samples}
    real_recordings = {
        recording_id: recording
        for recording_id, recording in recordings.items()
        if recording_id in real_recording_ids
    }
    try:
        source_inputs = _verify_source_videos(repository, real_recordings)
    except (OSError, TypeError, ValueError) as error:
        raise RfdetrClusterCropMaterializationError(
            f"M4 source videos are invalid: {error}"
        ) from error
    synthetic_input = _load_synthetic_input(
        repository,
        synthetic_view_root=synthetic_view_root,
        synthetic_manifest_path=synthetic_manifest_path,
        include_synthetic=include_synthetic,
    )
    extractor = frame_extractor or _default_frame_extractor()
    destination = _output_directory(repository, output_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix=".rfdetr-cluster-crop-", dir=destination.parent))
    staging = staging_parent / destination.name
    try:
        (staging / "train" / "images").mkdir(parents=True)
        (staging / "valid" / "images").mkdir(parents=True)
        images_by_split: dict[str, list[dict[str, Any]]] = {
            split: [] for split in TRAINING_PARTITIONS
        }
        annotations_by_split: dict[str, list[dict[str, Any]]] = {
            split: [] for split in TRAINING_PARTITIONS
        }
        lineage_records: list[dict[str, Any]] = []
        crop_records: list[dict[str, Any]] = []
        generated_files: list[dict[str, Any]] = []
        image_id = 0
        annotation_id = 0
        real_crop_count = 0
        synthetic_crop_count = 0

        for sample in real_samples:
            scene_data = _validated_scene_targets(sample)
            recording = real_recordings[str(sample["recording_id"])]
            frame = sample["frame_identity"]
            source_path = repository / _safe_relative_path(
                recording["source_video_path"], "recording.source_video_path"
            )
            try:
                image_bytes = extractor(source_path, frame)
            except RfdetrClusterCropMaterializationError:
                raise
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                raise RfdetrClusterCropMaterializationError(
                    f"could not extract {sample['recording_id']}:{sample['event_id']}: {error}"
                ) from error
            frame_digest = _digest(frame.get("image_sha256"), "frame.image_sha256")
            if not isinstance(image_bytes, bytes) or not image_bytes:
                raise RfdetrClusterCropMaterializationError(
                    f"frame extractor returned no bytes for {sample['event_id']}"
                )
            if _sha256_bytes(image_bytes) != frame_digest:
                raise RfdetrClusterCropMaterializationError(
                    f"recorded frame digest differs for {sample['event_id']}"
                )
            source_image = _decode_image(
                image_bytes, frame["width"], frame["height"], sample["event_id"]
            )
            layout = _layout_for_targets(scene_data["targets"], frame["width"], frame["height"])
            metadata = _real_metadata(sample, recording, frame_digest)
            image_id, annotation_id = _append_source_crops(
                staging=staging,
                images_by_split=images_by_split,
                annotations_by_split=annotations_by_split,
                lineage_records=lineage_records,
                crop_records=crop_records,
                generated_files=generated_files,
                image_id=image_id,
                annotation_id=annotation_id,
                layout=layout,
                source_image=source_image,
                metadata=metadata,
                target_records=scene_data["targets"],
                scene_lineage=scene_data["scene_lineage"],
                dataset_origin="real_0072",
            )
            real_crop_count += len(layout.clusters)

        if include_synthetic:
            for synthetic_row in synthetic_input["rows"]:
                image = synthetic_row["image"]
                source_image_bytes = synthetic_row["image_bytes"]
                source_image = _decode_image(
                    source_image_bytes,
                    int(image["width"]),
                    int(image["height"]),
                    str(image.get("event_id", image.get("id"))),
                )
                targets = _synthetic_targets(synthetic_row["annotations"], image)
                layout = _layout_for_targets(targets, int(image["width"]), int(image["height"]))
                metadata = _synthetic_metadata(image, synthetic_row["receipt"])
                image_id, annotation_id = _append_source_crops(
                    staging=staging,
                    images_by_split=images_by_split,
                    annotations_by_split=annotations_by_split,
                    lineage_records=lineage_records,
                    crop_records=crop_records,
                    generated_files=generated_files,
                    image_id=image_id,
                    annotation_id=annotation_id,
                    layout=layout,
                    source_image=source_image,
                    metadata=metadata,
                    target_records=targets,
                    scene_lineage={
                        "authority": "0070_frozen_scene_receipt",
                        "receipt": synthetic_row["receipt"],
                    },
                    dataset_origin="synthetic_0070",
                )
                synthetic_crop_count += len(layout.clusters)

        if not crop_records:
            raise RfdetrClusterCropMaterializationError("M4 did not produce any cluster crops")
        split_payload = _split_payload(manifest, images_by_split, synthetic_input)
        split_path = staging / "split.json"
        _write_json(split_path, split_payload)
        generated_files.append(
            {"kind": "trainer_split", "path": "split.json", "sha256": _sha256_file(split_path)}
        )
        for split in TRAINING_PARTITIONS:
            partition_name = "train" if split == "train" else "valid"
            coco = _coco_payload(
                images_by_split[split], annotations_by_split[split], partition_name
            )
            validate_rfdetr_cluster_crop_coco_annotations(coco)
            annotations_path = staging / partition_name / "_annotations.coco.json"
            _write_json(annotations_path, coco)
            generated_files.append(
                {
                    "kind": "coco_annotations",
                    "path": f"{partition_name}/_annotations.coco.json",
                    "split": split,
                    "sha256": _sha256_file(annotations_path),
                }
            )
        lineage_payload = _lineage_payload(manifest, lineage_records, synthetic_input)
        lineage_path = staging / "lineage.json"
        _write_json(lineage_path, lineage_payload)
        generated_files.append(
            {
                "kind": "lineage",
                "path": "lineage.json",
                "sha256": _sha256_file(lineage_path),
            }
        )
        exclusions_payload = _exclusions_payload(manifest, real_samples, synthetic_input)
        exclusions_path = staging / "exclusions.json"
        _write_json(exclusions_path, exclusions_payload)
        generated_files.append(
            {
                "kind": "exclusions",
                "path": "exclusions.json",
                "sha256": _sha256_file(exclusions_path),
            }
        )
        coverage_payload = _coverage_payload(manifest, crop_records, synthetic_input)
        coverage_path = staging / "coverage-report.json"
        _write_json(coverage_path, coverage_payload)
        generated_files.append(
            {
                "kind": "coverage",
                "path": "coverage-report.json",
                "sha256": _sha256_file(coverage_path),
            }
        )
        scale_payload = _scale_payload(manifest, crop_records)
        scale_path = staging / "scale-report.json"
        _write_json(scale_path, scale_payload)
        generated_files.append(
            {"kind": "scale", "path": "scale-report.json", "sha256": _sha256_file(scale_path)}
        )
        contact_sheet = _write_contact_sheet(staging, crop_records)
        generated_files.append(
            {
                "kind": "contact_sheet",
                "path": "contact-sheet.png",
                "sha256": _sha256_file(contact_sheet),
            }
        )
        generated_files.sort(key=lambda item: str(item["path"]))
        manifest_ref = {
            "path": _relative_to_repository(source_manifest_path, repository),
            "manifest_digest": str(manifest["manifest_digest"]),
            "file_sha256": _sha256_file(source_manifest_path),
        }
        materialization_core: dict[str, Any] = {
            "schema_version": RFDETR_CLUSTER_CROP_MATERIALIZATION_SCHEMA,
            "materializer_version": RFDETR_CLUSTER_CROP_MATERIALIZER_VERSION,
            "campaign_id": RFDETR_CLUSTER_CROP_CAMPAIGN_ID,
            "source_campaign_id": RFDETR_DETECTOR_CAMPAIGN_ID,
            "campaign_manifest": manifest_ref,
            "crop_recipe": {
                "cascade": frozen_cascade_recipe(),
                "fine_model_class": CASCADE_FINE_MODEL_CLASS,
                "fine_model_input_size": [CASCADE_FINE_INPUT_SIZE, CASCADE_FINE_INPUT_SIZE],
                "package": {"name": "rfdetr", "version": CASCADE_RFDETR_VERSION},
                "perturbation_policy": RFDETR_CLUSTER_CROP_PERTURBATION_POLICY,
                "perturbation": {
                    "translation": ["reference_span/4", "-reference_span/4"],
                    "scale": 1.0,
                },
            },
            "frame_extraction": {
                "policy": "recorded-exact-event-frame-v1",
                "output_encoding": "source-image-decoded-to-rgb-and-crop-png",
                "verification": "frame_identity_and_image_sha256",
            },
            "target_authority": {
                "real": "0072_reviewed_card_scene_derived_visible_regions",
                "synthetic": "0070_frozen_scene_receipts_and_exact_masks",
                "processor_polygons": "rejected",
            },
            "split": {
                "path": "split.json",
                "sha256": _sha256_file(split_path),
                "digest": split_payload["split_digest"],
            },
            "inputs": {
                "source_videos": source_inputs,
                "synthetic_training_view": synthetic_input["identity"],
            },
            "lineage": {
                "path": "lineage.json",
                "sha256": _sha256_file(lineage_path),
                "schema_version": RFDETR_CLUSTER_CROP_LINEAGE_SCHEMA,
                "digest": lineage_payload["lineage_digest"],
            },
            "exclusions": {
                "path": "exclusions.json",
                "sha256": _sha256_file(exclusions_path),
                "schema_version": RFDETR_CLUSTER_CROP_EXCLUSIONS_SCHEMA,
            },
            "coverage": {
                "path": "coverage-report.json",
                "sha256": _sha256_file(coverage_path),
                "schema_version": RFDETR_CLUSTER_CROP_COVERAGE_SCHEMA,
            },
            "scale": {
                "path": "scale-report.json",
                "sha256": _sha256_file(scale_path),
                "schema_version": RFDETR_CLUSTER_CROP_SCALE_SCHEMA,
            },
            "contact_sheet": {
                "path": "contact-sheet.png",
                "sha256": _sha256_file(contact_sheet),
                "schema_version": RFDETR_CLUSTER_CROP_CONTACT_SHEET_SCHEMA,
                "crop_count": len(crop_records),
            },
            "counts": {
                "images": len(crop_records),
                "annotations": annotation_id,
                "real_crops": real_crop_count,
                "synthetic_crops": synthetic_crop_count,
                "train_images": len(images_by_split["train"]),
                "validation_images": len(images_by_split["validation"]),
                "train_annotations": len(annotations_by_split["train"]),
                "validation_annotations": len(annotations_by_split["validation"]),
            },
            "generated_files": generated_files,
        }
        materialization = {
            **materialization_core,
            "materialization_digest": sha256_json(materialization_core),
        }
        materialization_path = staging / "materialization.json"
        _write_json(materialization_path, materialization)
        if destination.exists() or destination.is_symlink():
            _remove_destination(destination)
        os.replace(staging, destination)
        return RfdetrClusterCropMaterializationResult(
            view_root=destination,
            real_crop_count=real_crop_count,
            synthetic_crop_count=synthetic_crop_count,
            annotation_count=annotation_id,
            materialization_digest=str(materialization["materialization_digest"]),
            lineage_digest=str(lineage_payload["lineage_digest"]),
            contact_sheet_digest=_sha256_file(destination / "contact-sheet.png"),
        )
    except RfdetrClusterCropMaterializationError:
        raise
    except (
        CardPlaneGeometryError,
        KeyError,
        OSError,
        TypeError,
        UnidentifiedImageError,
        ValueError,
    ) as error:
        raise RfdetrClusterCropMaterializationError(
            f"could not materialize RF-DETR cluster-crop view: {error}"
        ) from error
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def load_rfdetr_cluster_crop_materialization(path: str | Path) -> dict[str, Any]:
    """Load and verify a generated M4 crop view."""

    root = Path(path).expanduser().resolve()
    materialization = _read_json(root / "materialization.json", "materialization manifest")
    if materialization.get("schema_version") != RFDETR_CLUSTER_CROP_MATERIALIZATION_SCHEMA:
        raise RfdetrClusterCropMaterializationError("materialization schema is unsupported")
    digest = materialization.get("materialization_digest")
    core = {key: value for key, value in materialization.items() if key != "materialization_digest"}
    if digest != sha256_json(core):
        raise RfdetrClusterCropMaterializationError("materialization digest is stale")
    for item in materialization.get("generated_files", []):
        if not isinstance(item, Mapping):
            raise RfdetrClusterCropMaterializationError("generated file is not an object")
        relative = _safe_relative_path(item.get("path"), "generated file.path")
        generated = root / relative
        if not generated.is_file() or _sha256_file(generated) != _digest(
            item.get("sha256"), f"generated file {relative}.sha256"
        ):
            raise RfdetrClusterCropMaterializationError(
                f"generated file is missing or stale: {relative}"
            )
    for partition in ("train", "valid"):
        annotations = _read_json(
            root / partition / "_annotations.coco.json", f"{partition} COCO annotations"
        )
        validate_rfdetr_cluster_crop_coco_annotations(annotations)
        if not (root / partition / "images").is_dir():
            raise RfdetrClusterCropMaterializationError(f"missing {partition}/images")
    lineage = _read_json(root / "lineage.json", "lineage")
    lineage_core = {key: value for key, value in lineage.items() if key != "lineage_digest"}
    if lineage.get("lineage_digest") != sha256_json(lineage_core):
        raise RfdetrClusterCropMaterializationError("lineage digest is stale")
    split = _read_json(root / "split.json", "split")
    split_core = {key: value for key, value in split.items() if key != "split_digest"}
    if split.get("split_digest") != sha256_json(split_core):
        raise RfdetrClusterCropMaterializationError("split digest is stale")
    return materialization


def validate_rfdetr_cluster_crop_coco_annotations(raw: Mapping[str, Any]) -> None:
    """Validate the M4 COCO subset and its crop lineage."""

    validate_rfdetr_coco_annotations(raw)
    images = {int(image["id"]): image for image in raw["images"]}
    for image in raw["images"]:
        for field in (
            "crop_id",
            "source_frame_sha256",
            "cluster_id",
            "cluster",
            "transform",
            "perturbation",
            "dataset_origin",
        ):
            if field not in image:
                raise RfdetrClusterCropMaterializationError(
                    f"COCO image {image['id']} is missing crop lineage {field}"
                )
    for annotation in raw["annotations"]:
        image = images[int(annotation["image_id"])]
        for field in ("crop_id", "cluster_id", "source_box", "crop_box", "source_geometry"):
            if field not in annotation:
                raise RfdetrClusterCropMaterializationError(
                    f"COCO annotation {annotation['id']} is missing crop lineage {field}"
                )
        if (
            annotation["crop_id"] != image["crop_id"]
            or annotation["cluster_id"] != image["cluster_id"]
        ):
            raise RfdetrClusterCropMaterializationError(
                f"COCO annotation {annotation['id']} has inconsistent crop lineage"
            )


def _append_source_crops(
    *,
    staging: Path,
    images_by_split: dict[str, list[dict[str, Any]]],
    annotations_by_split: dict[str, list[dict[str, Any]]],
    lineage_records: list[dict[str, Any]],
    crop_records: list[dict[str, Any]],
    generated_files: list[dict[str, Any]],
    image_id: int,
    annotation_id: int,
    layout: Any,
    source_image: Image.Image,
    metadata: Mapping[str, Any],
    target_records: Sequence[Mapping[str, Any]],
    scene_lineage: Mapping[str, Any],
    dataset_origin: str,
) -> tuple[int, int]:
    targets_by_proposal = {str(target["proposal_id"]): target for target in target_records}
    split = str(metadata["split"])
    partition_name = "train" if split == "train" else "valid"
    for base_cluster in layout.clusters:
        cluster, perturbation = _perturb_cluster_crop(base_cluster)
        members = [targets_by_proposal[proposal_id] for proposal_id in cluster.proposal_ids]
        image_id += 1
        crop_image = crop_source_image(source_image, cluster)
        crop_bytes = _png_bytes(crop_image)
        crop_id = (
            f"{dataset_origin}:{metadata['recording_id']}:{metadata['event_id']}"
            f":{cluster.cluster_id}"
        )
        image_name = f"crop-{image_id:06d}.png"
        relative_path = f"{partition_name}/images/{image_name}"
        image_path = staging / relative_path
        image_path.write_bytes(crop_bytes)
        crop_digest = _sha256_bytes(crop_bytes)
        transform = cluster.transform
        image_record = {
            "id": image_id,
            "file_name": f"images/{image_name}",
            "width": cluster.crop_width,
            "height": cluster.crop_height,
            "sha256": crop_digest,
            "recording_id": metadata["recording_id"],
            "event_id": metadata["event_id"],
            "item_id": metadata["item_id"],
            "reference_revision_id": metadata["reference_revision_id"],
            "source_video_sha256": metadata["source_video_sha256"],
            "source_frame_sha256": metadata["source_frame_sha256"],
            "source_frame": dict(metadata["source_frame"]),
            "split": split,
            "trainer_partition": partition_name,
            "session_id": metadata["session_id"],
            "source_asset_id": metadata["source_asset_id"],
            "video_id": metadata["video_id"],
            "table_setup": metadata["table_setup"],
            "source_group_key": metadata["source_group_key"],
            "dataset_origin": dataset_origin,
            "crop_id": crop_id,
            "cluster_id": cluster.cluster_id,
            "cluster": cluster.to_mapping(),
            "transform": transform.to_mapping(),
            "perturbation": perturbation,
        }
        images_by_split[split].append(image_record)
        crop_lineage_cards: list[dict[str, Any]] = []
        for target in members:
            annotation_id += 1
            source_polygons = target["source_polygons"]
            crop_polygons = tuple(
                tuple(transform.source_to_crop(point) for point in polygon)
                for polygon in source_polygons
            )
            crop_box = _box_from_polygons(crop_polygons)
            source_box = target["source_box"]
            segmentation = [
                [number for point in polygon for number in (round(point.x, 6), round(point.y, 6))]
                for polygon in crop_polygons
            ]
            area = round(
                sum(
                    abs(_shoelace([(point.x, point.y) for point in polygon])) / 2
                    for polygon in crop_polygons
                ),
                6,
            )
            annotation = {
                "id": annotation_id,
                "image_id": image_id,
                "category_id": 1,
                "bbox": _box_to_bbox(crop_box),
                "area": area,
                "segmentation": segmentation,
                "iscrowd": 0,
                "target_state": "reviewed_visible_region"
                if dataset_origin == "real_0072"
                else "synthetic_visible_region",
                "recording_id": metadata["recording_id"],
                "event_id": metadata["event_id"],
                "item_id": metadata["item_id"],
                "reference_revision_id": metadata["reference_revision_id"],
                "card_id": target["card_id"],
                "source_video_sha256": metadata["source_video_sha256"],
                "source_frame_sha256": metadata["source_frame_sha256"],
                "target_geometry_sha256": sha256_json(target["geometry"]),
                "split": split,
                "card_side": target.get("side", "unknown"),
                "session_id": metadata["session_id"],
                "source_asset_id": metadata["source_asset_id"],
                "video_id": metadata["video_id"],
                "table_setup": metadata["table_setup"],
                "source_group_key": metadata["source_group_key"],
                "dataset_origin": dataset_origin,
                "crop_id": crop_id,
                "cluster_id": cluster.cluster_id,
                "source_box": source_box.to_mapping(),
                "crop_box": crop_box.to_mapping(),
                "source_geometry": target["geometry"],
            }
            annotations_by_split[split].append(annotation)
            crop_lineage_cards.append(
                {
                    "card_id": target["card_id"],
                    "side": target.get("side", "unknown"),
                    "source_box": source_box.to_mapping(),
                    "crop_box": crop_box.to_mapping(),
                    "source_polygons": _polygons_mapping(source_polygons),
                    "crop_polygons": _polygons_mapping(crop_polygons),
                    "source_geometry": target["geometry"],
                    "derived_region_digest": target.get("derived_region_digest"),
                }
            )
        lineage_records.append(
            {
                "crop_id": crop_id,
                "image_id": image_id,
                "dataset_origin": dataset_origin,
                "split": split,
                "recording_id": metadata["recording_id"],
                "event_id": metadata["event_id"],
                "item_id": metadata["item_id"],
                "reference_revision_id": metadata["reference_revision_id"],
                "source_frame": dict(metadata["source_frame"]),
                "source_frame_sha256": metadata["source_frame_sha256"],
                "source_group_key": metadata["source_group_key"],
                "cluster": cluster.to_mapping(),
                "transform": transform.to_mapping(),
                "perturbation": perturbation,
                "scene_lineage": dict(scene_lineage),
                "cards": crop_lineage_cards,
            }
        )
        crop_records.append(
            {
                "crop_id": crop_id,
                "image_id": image_id,
                "path": relative_path,
                "split": split,
                "dataset_origin": dataset_origin,
                "cluster_id": cluster.cluster_id,
                "source_group_key": metadata["source_group_key"],
                "width": cluster.crop_width,
                "height": cluster.crop_height,
                "transform": transform.to_mapping(),
                "annotations": crop_lineage_cards,
            }
        )
        generated_files.append(
            {
                "kind": "cluster_crop",
                "path": relative_path,
                "sha256": crop_digest,
                "crop_id": crop_id,
                "dataset_origin": dataset_origin,
            }
        )
    return image_id, annotation_id


def _validated_scene_targets(sample: Mapping[str, Any]) -> dict[str, Any]:
    envelope = sample.get("card_scene")
    if not isinstance(envelope, Mapping):
        raise RfdetrClusterCropMaterializationError(
            f"sample {sample.get('event_id')} has no completed 0072 card_scene envelope"
        )
    scene = envelope.get("scene")
    projection = envelope.get("projection")
    if not isinstance(scene, Mapping) or not isinstance(projection, Mapping):
        raise RfdetrClusterCropMaterializationError(
            f"sample {sample.get('event_id')} card_scene is missing scene or projection"
        )
    frame = sample.get("frame_identity")
    width = _positive_int(frame.get("width"), "frame.width") if isinstance(frame, Mapping) else 0
    height = _positive_int(frame.get("height"), "frame.height") if isinstance(frame, Mapping) else 0
    if scene.get("source_frame_width") != width or scene.get("source_frame_height") != height:
        raise RfdetrClusterCropMaterializationError(
            f"sample {sample.get('event_id')} card scene dimensions differ from source frame"
        )
    try:
        derivation = validate_pose_scene_candidate_view(
            scene,
            projection,
            sample.get("targets", []),
            receipt=envelope.get("derived_region_receipt"),
        )
    except (CardPlaneGeometryError, TypeError, ValueError) as error:
        raise RfdetrClusterCropMaterializationError(
            f"sample {sample.get('event_id')} has invalid 0072 scene-derived regions: {error}"
        ) from error
    target_by_id = {str(target["card_id"]): target for target in sample["targets"]}
    receipt = envelope.get("derived_region_receipt")
    if not isinstance(receipt, Mapping):
        raise RfdetrClusterCropMaterializationError("validated scene is missing its region receipt")
    receipt_digests = receipt.get("region_digests")
    if not isinstance(receipt_digests, list) or len(receipt_digests) != len(derivation.regions):
        raise RfdetrClusterCropMaterializationError("derived region receipt has stale region count")
    targets: list[dict[str, Any]] = []
    for index, region in enumerate(derivation.regions):
        card_id = str(region["card_id"])
        target = target_by_id[card_id]
        polygons = _normalized_region_polygons(region, width, height)
        source_box = _box_from_polygons(polygons)
        targets.append(
            {
                "card_id": card_id,
                "proposal_id": f"card-{index + 1:04d}",
                "side": target.get("side", "unknown"),
                "geometry": region["geometry"],
                "source_polygons": polygons,
                "source_box": source_box,
                "derived_region_digest": str(receipt_digests[index]),
            }
        )
    return {
        "targets": targets,
        "scene_lineage": {
            "authority": "0072_reviewed_card_scene_derived_visible_regions",
            "scene": dict(scene),
            "calibration_revision_id": scene["calibration_revision_id"],
            "calibration_digest": scene["calibration_digest"],
            "projection": dict(projection),
            "derived_region_receipt": dict(receipt),
        },
    }


def _synthetic_targets(
    annotations: Sequence[Mapping[str, Any]], image: Mapping[str, Any]
) -> list[dict[str, Any]]:
    width = _positive_int(image.get("width"), "synthetic image.width")
    height = _positive_int(image.get("height"), "synthetic image.height")
    targets: list[dict[str, Any]] = []
    for index, annotation in enumerate(sorted(annotations, key=lambda item: int(item["id"]))):
        raw_segmentation = annotation.get("segmentation")
        if not isinstance(raw_segmentation, list) or not raw_segmentation:
            raise RfdetrClusterCropMaterializationError("synthetic annotation has no polygons")
        polygons: list[tuple[PixelPoint, ...]] = []
        for polygon in raw_segmentation:
            if not isinstance(polygon, list) or len(polygon) < 6 or len(polygon) % 2:
                raise RfdetrClusterCropMaterializationError("synthetic polygon is invalid")
            points = tuple(
                PixelPoint(float(polygon[offset]), float(polygon[offset + 1]))
                for offset in range(0, len(polygon), 2)
            )
            if any(
                point.x < 0 or point.x > width or point.y < 0 or point.y > height
                for point in points
            ):
                raise RfdetrClusterCropMaterializationError(
                    "synthetic polygon is outside its image"
                )
            polygons.append(points)
        geometry = {
            "kind": "synthetic-visible-region/v1",
            "visible_region": {
                "polygons": [
                    [{"x": round(point.x, 6), "y": round(point.y, 6)} for point in polygon]
                    for polygon in polygons
                ]
            },
        }
        targets.append(
            {
                "card_id": str(annotation["card_id"]),
                "proposal_id": f"synthetic-card-{index + 1:04d}",
                "side": annotation.get("card_side", "unknown"),
                "geometry": geometry,
                "source_polygons": tuple(polygons),
                "source_box": _box_from_polygons(polygons),
                "derived_region_digest": None,
            }
        )
    if not targets:
        raise RfdetrClusterCropMaterializationError(
            f"synthetic image {image.get('id')} has no visible-card annotations"
        )
    return targets


def _perturb_cluster_crop(base: ClusterCrop) -> tuple[ClusterCrop, dict[str, Any]]:
    """Apply the frozen tolerance shift while proving the source box stays complete."""

    shift = max(1, round(base.cluster.reference_span / 4.0))
    base_box = base.padded_square_box
    side = int(base_box.width)
    shifted_box = PixelBox(
        int(base_box.x_min) + shift,
        int(base_box.y_min) - shift,
        int(base_box.x_min) + shift + side,
        int(base_box.y_min) - shift + side,
    )
    applied_box = shifted_box if shifted_box.contains(base.source_box) else base_box
    translation = [
        int(applied_box.x_min - base_box.x_min),
        int(applied_box.y_min - base_box.y_min),
    ]
    cluster = CardCluster(
        cluster_id=base.cluster.cluster_id,
        proposal_ids=base.cluster.proposal_ids,
        source_box=base.source_box,
        padded_square_box=applied_box,
        reference_span=base.cluster.reference_span,
    )
    transform = CoordinateTransform(
        source_width=base.source_width,
        source_height=base.source_height,
        crop_x_min=int(applied_box.x_min),
        crop_y_min=int(applied_box.y_min),
        crop_width=side,
        crop_height=side,
        model_width=CASCADE_FINE_INPUT_SIZE,
        model_height=CASCADE_FINE_INPUT_SIZE,
    )
    perturbed = ClusterCrop(
        cluster=cluster,
        source_width=base.source_width,
        source_height=base.source_height,
        crop_width=side,
        crop_height=side,
        scale=CASCADE_FINE_INPUT_SIZE / side,
        padding=Padding(
            left=max(0, int(-applied_box.x_min)),
            top=max(0, int(-applied_box.y_min)),
            right=max(0, int(applied_box.x_max - base.source_width)),
            bottom=max(0, int(applied_box.y_max - base.source_height)),
        ),
        transform=transform,
    )
    return perturbed, {
        "policy_id": RFDETR_CLUSTER_CROP_PERTURBATION_POLICY,
        "translation": translation,
        "scale": 1.0,
        "complete_source_regions": True,
        "fallback_to_base": translation == [0, 0],
    }


def _layout_for_targets(targets: Sequence[Mapping[str, Any]], width: int, height: int) -> Any:
    proposals = tuple(
        CoarseProposal(proposal_id=str(target["proposal_id"]), box=target["source_box"], score=1.0)
        for target in targets
    )
    try:
        return build_cascade_layout(
            proposals,
            frame_width=width,
            frame_height=height,
            coarse_threshold=0.5,
            model_input_size=CASCADE_FINE_INPUT_SIZE,
        )
    except (TypeError, ValueError) as error:
        raise RfdetrClusterCropMaterializationError(
            f"cluster layout is invalid: {error}"
        ) from error


def _real_metadata(
    sample: Mapping[str, Any], recording: Mapping[str, Any], frame_digest: str
) -> dict[str, Any]:
    group = sample.get("source_group")
    if not isinstance(group, Mapping):
        raise RfdetrClusterCropMaterializationError(
            f"sample {sample.get('event_id')} has no source group"
        )
    return {
        "recording_id": sample["recording_id"],
        "event_id": sample["event_id"],
        "item_id": sample["item_id"],
        "reference_revision_id": sample["reference_revision_id"],
        "source_video_sha256": sample["source_sha256"],
        "source_frame_sha256": frame_digest,
        "source_frame": dict(sample["frame_identity"]),
        "split": sample["split"],
        "session_id": recording["session_id"],
        "source_asset_id": recording["source_asset_id"],
        "video_id": recording["video_id"],
        "table_setup": recording["table_setup"],
        "source_group_key": sample.get("source_group_key", group.get("group_key")),
    }


def _synthetic_metadata(image: Mapping[str, Any], receipt: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "recording_id",
        "event_id",
        "item_id",
        "reference_revision_id",
        "source_video_sha256",
        "source_frame_sha256",
        "session_id",
        "source_asset_id",
        "video_id",
        "table_setup",
        "source_group_key",
    )
    if any(not isinstance(image.get(field), str) or not image[field] for field in required):
        raise RfdetrClusterCropMaterializationError("synthetic image is missing source lineage")
    return {
        **{field: image[field] for field in required},
        "source_frame": {
            "frame_id": image["event_id"],
            "width": image["width"],
            "height": image["height"],
            "image_sha256": image["source_frame_sha256"],
            "source_video_sha256": image["source_video_sha256"],
        },
        "split": "train",
        "receipt_digest": receipt.get("receipt_digest"),
    }


def _load_synthetic_input(
    repository: Path,
    *,
    synthetic_view_root: str | Path | None,
    synthetic_manifest_path: str | Path | None,
    include_synthetic: bool,
) -> dict[str, Any]:
    if not include_synthetic:
        return {"rows": [], "identity": {"enabled": False}}
    if synthetic_view_root is None:
        raise RfdetrClusterCropMaterializationError("M4 synthetic input path is required")
    root = _resolve_directory(synthetic_view_root, repository, "0070 synthetic training view")
    coco_path = root / "train" / "_annotations.coco.json"
    if not coco_path.is_file():
        raise RfdetrClusterCropMaterializationError(
            f"0070 synthetic training view is missing train COCO annotations: {coco_path}"
        )
    coco = _read_json(coco_path, "0070 synthetic train COCO annotations")
    try:
        validate_rfdetr_coco_annotations(coco)
    except (TypeError, ValueError) as error:
        raise RfdetrClusterCropMaterializationError(
            f"0070 synthetic train COCO annotations are invalid: {error}"
        ) from error
    view_manifest: dict[str, Any] | None = None
    manifest_ref: dict[str, Any] | None = None
    if synthetic_manifest_path is not None:
        candidate = Path(synthetic_manifest_path).expanduser()
        candidate = candidate if candidate.is_absolute() else repository / candidate
        if candidate.is_file():
            view_manifest = _read_json(candidate, "0070 synthetic training-view manifest")
            try:
                from .synthetic_visible_region_training_view import (
                    validate_synthetic_visible_region_training_view,
                )

                validate_synthetic_visible_region_training_view(view_manifest)
            except (TypeError, ValueError) as error:
                raise RfdetrClusterCropMaterializationError(
                    f"0070 synthetic training-view manifest is invalid: {error}"
                ) from error
            manifest_ref = {
                "path": _relative_to_repository(candidate, repository),
                "manifest_digest": view_manifest["manifest_digest"],
                "file_sha256": _sha256_file(candidate),
            }
    annotations_by_image: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for annotation in coco.get("annotations", []):
        if isinstance(annotation, Mapping) and annotation.get("dataset_origin") == "synthetic":
            annotations_by_image[int(annotation["image_id"])].append(annotation)
    rows: list[dict[str, Any]] = []
    for image in sorted(coco.get("images", []), key=lambda item: int(item["id"])):
        if not isinstance(image, Mapping) or image.get("dataset_origin") != "synthetic":
            continue
        image_id = int(image["id"])
        relative = _safe_relative_path(image.get("file_name"), "synthetic image.file_name")
        image_path = root / "train" / relative
        if not image_path.is_file() or _sha256_file(image_path) != _digest(
            image.get("sha256"), f"synthetic image {image_id}.sha256"
        ):
            raise RfdetrClusterCropMaterializationError(
                f"synthetic image is missing or stale: {relative}"
            )
        scene_id = str(image.get("synthetic_scene_id", image.get("event_id")))
        receipt = _load_synthetic_receipt(repository, root, scene_id, view_manifest)
        annotations = annotations_by_image.get(image_id, [])
        if not annotations:
            raise RfdetrClusterCropMaterializationError(
                f"synthetic image {scene_id} has no synthetic annotations"
            )
        rows.append(
            {
                "image": dict(image),
                "image_bytes": image_path.read_bytes(),
                "annotations": [dict(annotation) for annotation in annotations],
                "receipt": receipt,
            }
        )
    materialization_ref = None
    materialization_path = root / "materialization.json"
    if materialization_path.is_file():
        materialization = _read_json(materialization_path, "0070 synthetic materialization")
        materialization_ref = {
            "path": _relative_to_repository(materialization_path, repository),
            "materialization_digest": materialization.get("materialization_digest"),
            "file_sha256": _sha256_file(materialization_path),
        }
    return {
        "rows": rows,
        "identity": {
            "enabled": True,
            "root": _relative_to_repository(root, repository),
            "train_coco_sha256": _sha256_file(coco_path),
            "manifest": manifest_ref,
            "materialization": materialization_ref,
            "row_count": len(rows),
        },
    }


def _load_synthetic_receipt(
    repository: Path, root: Path, scene_id: str, view_manifest: Mapping[str, Any] | None
) -> dict[str, Any]:
    candidates = [root / "receipts" / f"{scene_id}.json"]
    if view_manifest is not None:
        inputs = view_manifest.get("inputs")
        m2 = inputs.get("m2") if isinstance(inputs, Mapping) else None
        if isinstance(m2, Mapping) and isinstance(m2.get("path"), str):
            scene_manifest_path = _resolve_file(m2["path"], repository, "0070 scene manifest")
            scene_manifest = _read_json(scene_manifest_path, "0070 scene manifest")
            for summary in scene_manifest.get("scenes", []):
                if isinstance(summary, Mapping) and str(summary.get("scene_id")) == scene_id:
                    receipt_path = summary.get("receipt_path")
                    if isinstance(receipt_path, str):
                        candidates.append(_resolve_file(receipt_path, repository, "0070 receipt"))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        receipt = _read_json(candidate, f"0070 receipt {scene_id}")
        if receipt.get("scene_id") != scene_id or not isinstance(
            receipt.get("receipt_digest"), str
        ):
            raise RfdetrClusterCropMaterializationError(f"0070 receipt is invalid: {candidate}")
        core = {key: value for key, value in receipt.items() if key != "receipt_digest"}
        if receipt["receipt_digest"] != _sha256_bytes(canonical_json_bytes(core)):
            raise RfdetrClusterCropMaterializationError(
                f"0070 receipt digest is stale: {candidate}"
            )
        return receipt
    raise RfdetrClusterCropMaterializationError(
        f"0070 synthetic scene receipt is missing for {scene_id}"
    )


def _decode_image(image_bytes: bytes, width: int, height: int, item_id: str) -> Image.Image:
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.size != (width, height):
                raise RfdetrClusterCropMaterializationError(
                    f"decoded image dimensions differ for {item_id}"
                )
            return image.convert("RGB").copy()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise RfdetrClusterCropMaterializationError(
            f"image could not be decoded for {item_id}: {error}"
        ) from error


def _normalized_region_polygons(
    region: Mapping[str, Any], width: int, height: int
) -> tuple[tuple[PixelPoint, ...], ...]:
    geometry = region.get("geometry")
    visible_region = geometry.get("visible_region") if isinstance(geometry, Mapping) else None
    raw_polygons = visible_region.get("polygons") if isinstance(visible_region, Mapping) else None
    normalization = region.get("normalization")
    if not isinstance(raw_polygons, list) or not raw_polygons:
        raise RfdetrClusterCropMaterializationError("derived region has no polygons")
    if (
        not isinstance(normalization, Mapping)
        or normalization.get("width") != width
        or normalization.get("height") != height
    ):
        raise RfdetrClusterCropMaterializationError(
            "derived region normalization differs from source frame"
        )
    result: list[tuple[PixelPoint, ...]] = []
    for polygon in raw_polygons:
        if not isinstance(polygon, list) or len(polygon) < 3:
            raise RfdetrClusterCropMaterializationError("derived region polygon is invalid")
        points = tuple(
            PixelPoint(
                float(point["x"]) * width / 1000.0,
                float(point["y"]) * height / 1000.0,
            )
            for point in polygon
            if isinstance(point, Mapping)
        )
        if len(points) != len(polygon) or any(
            point.x < 0 or point.x > width or point.y < 0 or point.y > height for point in points
        ):
            raise RfdetrClusterCropMaterializationError("derived region point is outside the frame")
        result.append(points)
    return tuple(result)


def _box_from_polygons(polygons: Sequence[Sequence[PixelPoint]]) -> PixelBox:
    points = tuple(point for polygon in polygons for point in polygon)
    if not points:
        raise RfdetrClusterCropMaterializationError("polygon set is empty")
    return PixelBox(
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


def _box_to_bbox(box: PixelBox) -> list[int]:
    x_min = math.floor(box.x_min)
    y_min = math.floor(box.y_min)
    x_max = math.ceil(box.x_max)
    y_max = math.ceil(box.y_max)
    return [x_min, y_min, x_max - x_min, y_max - y_min]


def _shoelace(points: Sequence[tuple[float, float]]) -> float:
    return 0.5 * sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, points[1:] + points[:1], strict=True)
    )


def _polygons_mapping(polygons: Sequence[Sequence[PixelPoint]]) -> list[list[dict[str, float]]]:
    return [
        [{"x": round(point.x, 6), "y": round(point.y, 6)} for point in polygon]
        for polygon in polygons
    ]


def _png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def _lineage_payload(
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    synthetic_input: Mapping[str, Any],
) -> dict[str, Any]:
    core = {
        "schema_version": RFDETR_CLUSTER_CROP_LINEAGE_SCHEMA,
        "campaign_id": RFDETR_CLUSTER_CROP_CAMPAIGN_ID,
        "source_manifest_digest": manifest["manifest_digest"],
        "real_authority": "0072_reviewed_card_scene_derived_visible_regions",
        "synthetic_input": synthetic_input["identity"],
        "records": list(records),
    }
    return {**core, "lineage_digest": sha256_json(core)}


def _split_payload(
    manifest: Mapping[str, Any],
    images_by_split: Mapping[str, Sequence[Mapping[str, Any]]],
    synthetic_input: Mapping[str, Any],
) -> dict[str, Any]:
    core = {
        "schema_version": RFDETR_CLUSTER_CROP_SPLIT_SCHEMA,
        "source_manifest_digest": manifest["manifest_digest"],
        "train_source_groups": list(manifest["split"]["train"]["recording_ids"]),
        "validation_source_groups": list(manifest["split"]["validation"]["recording_ids"]),
        "synthetic_train_only": bool(synthetic_input["identity"].get("enabled")),
        "crop_counts": {split: len(images_by_split[split]) for split in TRAINING_PARTITIONS},
    }
    return {**core, "split_digest": sha256_json(core)}


def _exclusions_payload(
    manifest: Mapping[str, Any],
    samples: Sequence[Mapping[str, Any]],
    synthetic_input: Mapping[str, Any],
) -> dict[str, Any]:
    sealed = [
        {
            "recording_id": sample["recording_id"],
            "event_id": sample["event_id"],
            "split": sample["split"],
            "frame_identity": sample["frame_identity"],
            "reason": "0068 sealed_test remains outside M4 train and validation view",
        }
        for sample in manifest["samples"]
        if isinstance(sample, Mapping) and sample.get("split") == "sealed_test"
    ]
    core = {
        "schema_version": RFDETR_CLUSTER_CROP_EXCLUSIONS_SCHEMA,
        "policy": {
            "real_partitions": list(TRAINING_PARTITIONS),
            "sealed_test": "excluded and unchanged",
            "missing_scene_derivation": "reject before target conversion",
            "synthetic": "train_only",
        },
        "source_manifest_digest": manifest["manifest_digest"],
        "0068_excluded_frames": manifest["excluded_frames"],
        "0068_ineligible_outcomes": manifest["ineligible_outcomes"],
        "sealed_test_samples": sealed,
        "synthetic_input": synthetic_input["identity"],
        "materialized_real_sample_count": len(samples),
    }
    return {**core, "exclusions_digest": sha256_json(core)}


def _coverage_payload(
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    synthetic_input: Mapping[str, Any],
) -> dict[str, Any]:
    partitions: dict[str, dict[str, Any]] = {}
    for split in TRAINING_PARTITIONS:
        selected = [record for record in records if record["split"] == split]
        partitions[split] = {
            "crop_count": len(selected),
            "annotation_count": sum(len(record["annotations"]) for record in selected),
            "real_crop_count": sum(record["dataset_origin"] == "real_0072" for record in selected),
            "synthetic_crop_count": sum(
                record["dataset_origin"] == "synthetic_0070" for record in selected
            ),
            "source_group_keys": sorted({str(record["source_group_key"]) for record in selected}),
            "complete_visible_region_coverage": True,
        }
    core = {
        "schema_version": RFDETR_CLUSTER_CROP_COVERAGE_SCHEMA,
        "source_manifest_digest": manifest["manifest_digest"],
        "authority": "0072_scene_derived_real_and_0070_frozen_synthetic",
        "partitions": partitions,
        "synthetic_input": synthetic_input["identity"],
    }
    return {**core, "coverage_digest": sha256_json(core)}


def _scale_payload(
    manifest: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    values = [
        {
            "crop_id": record["crop_id"],
            "dataset_origin": record["dataset_origin"],
            "source_size": record["transform"]["source_size"],
            "crop_size": record["transform"]["crop_size"],
            "fine_model_input_size": CASCADE_FINE_INPUT_SIZE,
            "source_pixels_per_fine_input_pixel": {
                "x": round(float(record["width"]) / CASCADE_FINE_INPUT_SIZE, 6),
                "y": round(float(record["height"]) / CASCADE_FINE_INPUT_SIZE, 6),
            },
        }
        for record in records
    ]
    core = {
        "schema_version": RFDETR_CLUSTER_CROP_SCALE_SCHEMA,
        "source_manifest_digest": manifest["manifest_digest"],
        "fine_model": {
            "class": CASCADE_FINE_MODEL_CLASS,
            "input_size": CASCADE_FINE_INPUT_SIZE,
            "class_name": "visible_card",
        },
        "crops": values,
    }
    return {**core, "scale_digest": sha256_json(core)}


def _write_contact_sheet(root: Path, records: Sequence[Mapping[str, Any]]) -> Path:
    tile_width, tile_height, columns = 560, 460, 2
    rows = math.ceil(len(records) / columns)
    sheet = Image.new("RGB", (tile_width * columns, tile_height * rows), (35, 35, 35))
    draw = ImageDraw.Draw(sheet)
    for index, record in enumerate(sorted(records, key=lambda item: str(item["crop_id"]))):
        path = root / str(record["path"])
        with Image.open(path) as source:
            image = source.convert("RGB")
        scale = min((tile_width - 24) / image.width, (tile_height - 74) / image.height)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        preview = image.resize(size, Image.Resampling.NEAREST)
        left = (index % columns) * tile_width + (tile_width - size[0]) // 2
        top = (index // columns) * tile_height + 42
        sheet.paste(preview, (left, top))
        overlay = ImageDraw.Draw(sheet)
        for annotation in record["annotations"]:
            for polygon in annotation["crop_polygons"]:
                points = [
                    (
                        left + round(float(point["x"]) * scale),
                        top + round(float(point["y"]) * scale),
                    )
                    for point in polygon
                ]
                overlay.line(points + [points[0]], fill=(255, 214, 64), width=3, joint="curve")
        draw.text(
            ((index % columns) * tile_width + 10, (index // columns) * tile_height + 10),
            f"{record['dataset_origin']}  {record['crop_id']}",
            fill=(240, 240, 240),
        )
    path = root / "contact-sheet.png"
    sheet.save(path, format="PNG", optimize=False)
    return path


def _coco_payload(
    images: Sequence[Mapping[str, Any]],
    annotations: Sequence[Mapping[str, Any]],
    partition_name: str,
) -> dict[str, Any]:
    return {
        "info": {
            "description": "DokoDetector RF-DETR cluster-crop visible-card segmentation view",
            "version": "cluster-crop-visible-region-v1",
            "coco_version": "coco-2017",
            "campaign_id": RFDETR_CLUSTER_CROP_CAMPAIGN_ID,
            "trainer_partition": partition_name,
        },
        "licenses": [],
        "images": [dict(image) for image in images],
        "annotations": [dict(annotation) for annotation in annotations],
        "categories": [TARGET_CATEGORY],
    }


def _validate_input_manifest(manifest: Mapping[str, Any]) -> None:
    try:
        validate_reviewed_rfdetr_detector_manifest(manifest)
    except (ReviewedRfdetrDetectorCampaignError, TypeError, ValueError) as error:
        raise RfdetrClusterCropMaterializationError(
            f"0068 M0 manifest is invalid: {error}"
        ) from error
    if manifest.get("freeze_state") != "frozen":
        raise RfdetrClusterCropMaterializationError(
            "M4 requires a frozen 0068 M0 manifest; blocked manifests are not trainer inputs"
        )
    if manifest.get("campaign_id") != RFDETR_DETECTOR_CAMPAIGN_ID:
        raise RfdetrClusterCropMaterializationError(
            "input manifest is not the reviewed 0068 campaign"
        )
    if manifest.get("schema_version") != RFDETR_DETECTOR_MANIFEST_SCHEMA_VERSION:
        raise RfdetrClusterCropMaterializationError(
            "input manifest schema is not the reviewed 0068 schema"
        )


def _output_directory(repository: Path, output_root: str | Path | None) -> Path:
    if output_root is None:
        return repository / ".runtime" / "rfdetr-cluster-crop-0071-m4"
    path = Path(output_root).expanduser()
    return (repository / path if not path.is_absolute() else path).resolve()


def _resolve_file(value: str | Path, repository: Path, field: str) -> Path:
    path = Path(value).expanduser()
    resolved = path if path.is_absolute() else repository / path
    resolved = resolved.resolve()
    if not resolved.is_file():
        raise RfdetrClusterCropMaterializationError(f"{field} does not exist: {resolved}")
    return resolved


def _resolve_directory(value: str | Path, repository: Path, field: str) -> Path:
    path = Path(value).expanduser()
    resolved = path if path.is_absolute() else repository / path
    resolved = resolved.resolve()
    if not resolved.is_dir():
        raise RfdetrClusterCropMaterializationError(f"{field} does not exist: {resolved}")
    return resolved


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RfdetrClusterCropMaterializationError(f"could not read {field}: {path}") from error
    if not isinstance(value, Mapping):
        raise RfdetrClusterCropMaterializationError(f"{field} must be an object")
    return dict(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _safe_relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise RfdetrClusterCropMaterializationError(f"{field} must be a relative path")
    path = Path(value)
    if ".." in path.parts:
        raise RfdetrClusterCropMaterializationError(f"{field} escapes its root")
    return path.as_posix()


def _relative_to_repository(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - _SHA256:
        raise RfdetrClusterCropMaterializationError(f"{field} must be a SHA-256 digest")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RfdetrClusterCropMaterializationError(f"{field} must be a positive integer")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_destination(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


__all__ = [
    "RFDETR_CLUSTER_CROP_CAMPAIGN_ID",
    "RFDETR_CLUSTER_CROP_MATERIALIZATION_SCHEMA",
    "RFDETR_CLUSTER_CROP_MATERIALIZER_VERSION",
    "RFDETR_CLUSTER_CROP_PERTURBATION_POLICY",
    "RfdetrClusterCropMaterializationError",
    "RfdetrClusterCropMaterializationResult",
    "load_rfdetr_cluster_crop_materialization",
    "materialize_rfdetr_cluster_crop_dataset",
    "validate_rfdetr_cluster_crop_coco_annotations",
]
