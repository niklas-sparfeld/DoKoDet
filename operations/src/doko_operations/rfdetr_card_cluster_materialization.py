"""Materialize the epic 0071 full-frame card-cluster detection view.

The frozen 0068 reviewed-detector manifest is the only annotation authority.  This module derives
one ``card_cluster`` box from each connected component of reviewed visible-card boxes.  It keeps
the 0068 sealed-test partition out of the training view and writes an explicit exclusion receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from table_evidence_analyzer.visible_card_cascade import (
    CASCADE_COARSE_CONFIDENCE_THRESHOLD,
    CASCADE_COARSE_INPUT_SIZE,
    CASCADE_FINE_INPUT_SIZE,
    CoarseProposal,
    PixelBox,
    build_cascade_layout,
)

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
)

RFDETR_CARD_CLUSTER_MATERIALIZATION_SCHEMA = "rfdetr-card-cluster-materialization/v1"
RFDETR_CARD_CLUSTER_MATERIALIZER_VERSION = "rfdetr-card-cluster-materializer/v1"
RFDETR_CARD_CLUSTER_SPLIT_SCHEMA = "rfdetr-card-cluster-split/v1"
RFDETR_CARD_CLUSTER_EXCLUSIONS_SCHEMA = "rfdetr-card-cluster-exclusions/v1"
RFDETR_CARD_CLUSTER_LINEAGE_SCHEMA = "rfdetr-card-cluster-lineage/v1"
RFDETR_CARD_CLUSTER_COVERAGE_SCHEMA = "rfdetr-card-cluster-coverage/v1"
RFDETR_CARD_CLUSTER_SCALE_SCHEMA = "rfdetr-card-cluster-scale/v1"
COCO_VERSION = "coco-2017"
TARGET_CATEGORY = {"id": 1, "name": "card_cluster", "supercategory": "card"}
TRAINING_PARTITIONS = ("train", "validation")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
FrameExtractor = Callable[[Path, Mapping[str, Any]], bytes]


class RfdetrCardClusterMaterializationError(ValueError):
    """The frozen reviewed input cannot be converted into a card-cluster view."""


@dataclass(frozen=True, slots=True)
class RfdetrCardClusterMaterializationResult:
    """The disposable card-cluster trainer view and its input identity."""

    view_root: Path
    campaign_manifest_digest: str
    split_digest: str
    materialization_digest: str
    image_count: int
    annotation_count: int
    cluster_count: int
    reviewed_card_count: int
    excluded_frame_count: int
    ineligible_outcome_count: int

    def to_mapping(self) -> dict[str, Any]:
        return {
            "view_root": str(self.view_root),
            "campaign_manifest_digest": self.campaign_manifest_digest,
            "split_digest": self.split_digest,
            "materialization_digest": self.materialization_digest,
            "image_count": self.image_count,
            "annotation_count": self.annotation_count,
            "cluster_count": self.cluster_count,
            "reviewed_card_count": self.reviewed_card_count,
            "excluded_frame_count": self.excluded_frame_count,
            "ineligible_outcome_count": self.ineligible_outcome_count,
        }


def materialize_rfdetr_card_cluster_dataset(
    manifest_path: str | Path,
    *,
    repository_root: str | Path,
    output_root: str | Path | None = None,
    frame_extractor: FrameExtractor | None = None,
) -> RfdetrCardClusterMaterializationResult:
    """Build a deterministic train/validation COCO detection view from the frozen 0068 input."""

    repository = Path(repository_root).expanduser().resolve()
    source_manifest_path = _resolve_input_path(manifest_path, repository, "0068 M0 manifest")
    manifest = _read_json(source_manifest_path, "0068 M0 manifest")
    _validate_input_manifest(manifest)

    try:
        recordings = _recordings_by_id(manifest)
        samples = _validated_samples(manifest)
    except (KeyError, TypeError, ValueError) as error:
        raise RfdetrCardClusterMaterializationError(
            f"0068 M0 samples are invalid: {error}"
        ) from error
    eligible_samples = [sample for sample in samples if sample["split"] in TRAINING_PARTITIONS]
    if not eligible_samples:
        raise RfdetrCardClusterMaterializationError(
            "0068 M0 has no train or validation samples for card-cluster training"
        )
    eligible_recording_ids = {str(sample["recording_id"]) for sample in eligible_samples}
    eligible_recordings = {
        recording_id: recording
        for recording_id, recording in recordings.items()
        if recording_id in eligible_recording_ids
    }
    source_inputs = _verify_source_videos(repository, eligible_recordings)
    extractor = frame_extractor or _default_frame_extractor()
    destination = _output_directory(repository, output_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(
        tempfile.mkdtemp(prefix=".rfdetr-card-cluster-", dir=destination.parent)
    )
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
        lineage_frames: list[dict[str, Any]] = []
        coverage_frames: list[dict[str, Any]] = []
        scale_frames: list[dict[str, Any]] = []
        generated_files: list[dict[str, Any]] = []
        image_id = 0
        annotation_id = 0
        cluster_count = 0
        reviewed_card_count = 0

        for sample in eligible_samples:
            split = str(sample["split"])
            recording = eligible_recordings[str(sample["recording_id"])]
            frame = sample["frame_identity"]
            source_path = repository / _safe_relative_path(
                recording["source_video_path"], "recording.source_video_path"
            )
            try:
                image_bytes = extractor(source_path, frame)
            except RfdetrCardClusterMaterializationError:
                raise
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                raise RfdetrCardClusterMaterializationError(
                    f"could not extract {sample['recording_id']}:{sample['event_id']}: {error}"
                ) from error
            if not isinstance(image_bytes, bytes) or not image_bytes:
                raise RfdetrCardClusterMaterializationError(
                    f"frame extractor returned no bytes for {sample['event_id']}"
                )
            frame_digest = _digest(frame.get("image_sha256"), "frame.image_sha256")
            if _sha256_bytes(image_bytes) != frame_digest:
                raise RfdetrCardClusterMaterializationError(
                    f"recorded frame digest differs for {sample['event_id']}"
                )

            target_records, proposals = _reviewed_card_proposals(sample)
            layout = build_cascade_layout(
                proposals,
                frame_width=_positive_int(frame.get("width"), "frame.width"),
                frame_height=_positive_int(frame.get("height"), "frame.height"),
                coarse_threshold=CASCADE_COARSE_CONFIDENCE_THRESHOLD,
                model_input_size=CASCADE_FINE_INPUT_SIZE,
            )
            proposal_to_target = {
                record["proposal_id"]: record for record in target_records
            }
            cluster_records: list[dict[str, Any]] = []
            cluster_annotations: list[dict[str, Any]] = []
            assigned_card_records: list[dict[str, Any]] = []
            for cluster_crop in layout.clusters:
                member_records = [
                    {
                        **proposal_to_target[proposal_id],
                        "cluster_id": cluster_crop.cluster_id,
                    }
                    for proposal_id in cluster_crop.proposal_ids
                ]
                assigned_card_records.extend(member_records)
                cluster_record = {
                    **cluster_crop.to_mapping(),
                    "member_card_ids": [record["card_id"] for record in member_records],
                    "member_proposal_ids": list(cluster_crop.proposal_ids),
                    "target_box": _box_mapping(cluster_crop.source_box),
                }
                cluster_records.append(cluster_record)
                cluster_annotations.append(
                    {
                        "cluster": cluster_record,
                        "members": member_records,
                    }
                )
            if len(cluster_records) == 0 or sum(
                len(cluster["members"]) for cluster in cluster_annotations
            ) != len(target_records):
                raise RfdetrCardClusterMaterializationError(
                    f"reviewed cards do not map one-to-one to clusters for {sample['event_id']}"
                )

            image_id += 1
            image_name = f"image-{image_id:06d}.jpg"
            partition_name = "train" if split == "train" else "valid"
            image_path = staging / partition_name / "images" / image_name
            image_path.write_bytes(image_bytes)
            image_record = _coco_image(
                image_id,
                image_name,
                sample,
                frame_digest,
                partition_name,
                recording,
            )
            images_by_split[split].append(image_record)
            generated_files.append(
                {
                    "kind": "extracted_frame",
                    "path": f"{partition_name}/images/{image_name}",
                    "recording_id": sample["recording_id"],
                    "event_id": sample["event_id"],
                    "sha256": frame_digest,
                }
            )
            for cluster in cluster_annotations:
                annotation_id += 1
                annotations_by_split[split].append(
                    _coco_annotation(
                        annotation_id,
                        image_id,
                        sample,
                        recording,
                        cluster["cluster"],
                    )
                )

            lineage_frames.append(
                {
                    "frame_id": _frame_id(sample),
                    "recording_id": sample["recording_id"],
                    "event_id": sample["event_id"],
                    "item_id": sample["item_id"],
                    "reference_revision_id": sample["reference_revision_id"],
                    "split": split,
                    "partition": partition_name,
                    "image_path": f"{partition_name}/images/{image_name}",
                    "image_sha256": frame_digest,
                    "frame_identity": frame,
                    "source_group": sample.get("source_group"),
                    "source_group_key": sample.get("source_group_key"),
                    "source_cards": assigned_card_records,
                    "clusters": cluster_records,
                }
            )
            coverage_frames.append(
                {
                    "frame_id": _frame_id(sample),
                    "recording_id": sample["recording_id"],
                    "event_id": sample["event_id"],
                    "split": split,
                    "reviewed_card_count": len(target_records),
                    "cluster_count": len(cluster_records),
                    "cards_per_cluster": [
                        len(cluster["members"]) for cluster in cluster_annotations
                    ],
                }
            )
            scale_frames.append(
                _scale_record(sample, layout, target_records, cluster_records)
            )
            cluster_count += len(cluster_records)
            reviewed_card_count += len(target_records)

        split_payload = _split_payload(manifest, images_by_split, annotations_by_split)
        split_path = staging / "split.json"
        _write_json(split_path, split_payload)
        generated_files.append(
            {"kind": "trainer_split", "path": "split.json", "sha256": _sha256_file(split_path)}
        )

        for split in TRAINING_PARTITIONS:
            partition_name = "train" if split == "train" else "valid"
            coco = _coco_payload(
                manifest,
                images_by_split[split],
                annotations_by_split[split],
                partition_name,
            )
            validate_rfdetr_card_cluster_coco_annotations(coco)
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

        lineage = _lineage_payload(manifest, lineage_frames)
        lineage_path = staging / "lineage.json"
        _write_json(lineage_path, lineage)
        generated_files.append(
            {"kind": "lineage", "path": "lineage.json", "sha256": _sha256_file(lineage_path)}
        )
        exclusions = _exclusions_payload(manifest, samples)
        exclusions_path = staging / "exclusions.json"
        _write_json(exclusions_path, exclusions)
        generated_files.append(
            {
                "kind": "exclusion_receipt",
                "path": "exclusions.json",
                "sha256": _sha256_file(exclusions_path),
            }
        )
        coverage = _coverage_payload(manifest, coverage_frames, exclusions, images_by_split)
        coverage_path = staging / "coverage-report.json"
        _write_json(coverage_path, coverage)
        generated_files.append(
            {
                "kind": "coverage_report",
                "path": "coverage-report.json",
                "sha256": _sha256_file(coverage_path),
            }
        )
        scale = _scale_payload(manifest, scale_frames)
        scale_path = staging / "scale-report.json"
        _write_json(scale_path, scale)
        generated_files.append(
            {
                "kind": "scale_report",
                "path": "scale-report.json",
                "sha256": _sha256_file(scale_path),
            }
        )

        generated_files.sort(key=lambda item: str(item["path"]))
        materialization_core = {
            "schema_version": RFDETR_CARD_CLUSTER_MATERIALIZATION_SCHEMA,
            "materializer_version": RFDETR_CARD_CLUSTER_MATERIALIZER_VERSION,
            "campaign_id": RFDETR_DETECTOR_CAMPAIGN_ID,
            "campaign_manifest": {
                "path": _relative_to_repository(source_manifest_path, repository),
                "manifest_digest": manifest["manifest_digest"],
                "file_sha256": _sha256_file(source_manifest_path),
            },
            "cluster_recipe": {
                "source": "reviewed_visible_card_tight_boxes",
                "threshold": CASCADE_COARSE_CONFIDENCE_THRESHOLD,
                "reference_span": "median_retained_box_shorter_side",
                "expanded_intersection": "one_half_reference_span_each_side",
                "component_rule": "transitive_connected_components",
                "target_box": "tight_union_of_unexpanded_member_boxes",
                "crop_context": "one_half_reference_span_each_side",
                "crop_recipe_version": "visible-card-cluster-crop/v1",
                "fine_model_input_size": CASCADE_FINE_INPUT_SIZE,
            },
            "coarse_model_recipe": {
                "model_class": "RFDETRSmall",
                "class_name": "card_cluster",
                "input_size": CASCADE_COARSE_INPUT_SIZE,
            },
            "frame_extraction": {
                "policy": "recorded-exact-event-frame-v1",
                "output_encoding": "jpeg",
                "verification": "frame_identity_and_image_sha256",
            },
            "target_conversion": {
                "source": "reviewed_visible_region_tight_box",
                "normalization": "full-frame-0-1000/v1",
                "box_rounding": "floor_min_ceil_max_v1",
                "category": TARGET_CATEGORY,
            },
            "split": {
                "path": "split.json",
                "sha256": _sha256_file(split_path),
                "digest": split_payload["split_digest"],
            },
            "inputs": source_inputs,
            "lineage": {
                "path": "lineage.json",
                "sha256": _sha256_file(lineage_path),
                "schema_version": RFDETR_CARD_CLUSTER_LINEAGE_SCHEMA,
            },
            "exclusions": {
                "path": "exclusions.json",
                "sha256": _sha256_file(exclusions_path),
                "schema_version": RFDETR_CARD_CLUSTER_EXCLUSIONS_SCHEMA,
            },
            "coverage": {
                "path": "coverage-report.json",
                "sha256": _sha256_file(coverage_path),
                "schema_version": RFDETR_CARD_CLUSTER_COVERAGE_SCHEMA,
            },
            "scale": {
                "path": "scale-report.json",
                "sha256": _sha256_file(scale_path),
                "schema_version": RFDETR_CARD_CLUSTER_SCALE_SCHEMA,
            },
            "counts": {
                "images": image_id,
                "annotations": annotation_id,
                "clusters": cluster_count,
                "reviewed_cards": reviewed_card_count,
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
        return RfdetrCardClusterMaterializationResult(
            view_root=destination,
            campaign_manifest_digest=str(manifest["manifest_digest"]),
            split_digest=str(split_payload["split_digest"]),
            materialization_digest=str(materialization["materialization_digest"]),
            image_count=image_id,
            annotation_count=annotation_id,
            cluster_count=cluster_count,
            reviewed_card_count=reviewed_card_count,
            excluded_frame_count=len(manifest["excluded_frames"]),
            ineligible_outcome_count=len(manifest["ineligible_outcomes"]),
        )
    except RfdetrCardClusterMaterializationError:
        raise
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise RfdetrCardClusterMaterializationError(
            f"could not materialize RF-DETR card-cluster view: {error}"
        ) from error
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def load_rfdetr_card_cluster_materialization(path: str | Path) -> dict[str, Any]:
    """Load and verify a generated card-cluster trainer view."""

    root = Path(path).expanduser().resolve()
    materialization = _read_json(root / "materialization.json", "materialization manifest")
    expected = {
        "schema_version",
        "materializer_version",
        "campaign_id",
        "campaign_manifest",
        "cluster_recipe",
        "coarse_model_recipe",
        "frame_extraction",
        "target_conversion",
        "split",
        "inputs",
        "lineage",
        "exclusions",
        "coverage",
        "scale",
        "counts",
        "generated_files",
        "materialization_digest",
    }
    if set(materialization) != expected:
        raise RfdetrCardClusterMaterializationError("materialization manifest has invalid fields")
    if materialization["schema_version"] != RFDETR_CARD_CLUSTER_MATERIALIZATION_SCHEMA:
        raise RfdetrCardClusterMaterializationError("materialization schema is unsupported")
    if materialization["campaign_id"] != RFDETR_DETECTOR_CAMPAIGN_ID:
        raise RfdetrCardClusterMaterializationError("materialization campaign is not 0068")
    core = {
        key: value for key, value in materialization.items() if key != "materialization_digest"
    }
    if materialization["materialization_digest"] != sha256_json(core):
        raise RfdetrCardClusterMaterializationError(
            "materialization digest does not match contents"
        )
    generated_files = materialization["generated_files"]
    if not isinstance(generated_files, list):
        raise RfdetrCardClusterMaterializationError("generated_files must be a list")
    for item in generated_files:
        if not isinstance(item, Mapping):
            raise RfdetrCardClusterMaterializationError("generated file is not an object")
        relative = _safe_relative_path(item.get("path"), "generated file path")
        generated = root / relative
        if not generated.is_file() or _sha256_file(generated) != _digest(
            item.get("sha256"), f"{relative}.sha256"
        ):
            raise RfdetrCardClusterMaterializationError(
                f"generated file is missing or has a different digest: {relative}"
            )
    for partition in ("train", "valid"):
        annotations = _read_json(root / partition / "_annotations.coco.json", f"{partition} COCO")
        validate_rfdetr_card_cluster_coco_annotations(annotations)
        if not (root / partition / "images").is_dir():
            raise RfdetrCardClusterMaterializationError(
                f"materialization is missing {partition}/images"
            )
    split = _read_json(root / "split.json", "split")
    split_core = {key: value for key, value in split.items() if key != "split_digest"}
    if split.get("split_digest") != sha256_json(split_core):
        raise RfdetrCardClusterMaterializationError("split digest does not match contents")
    if materialization["split"].get("digest") != split["split_digest"]:
        raise RfdetrCardClusterMaterializationError("materialization split digest differs")
    for name, descriptor in (
        ("lineage", materialization["lineage"]),
        ("exclusions", materialization["exclusions"]),
        ("coverage", materialization["coverage"]),
        ("scale", materialization["scale"]),
    ):
        value = _read_json(root / descriptor["path"], name)
        schema = value.get("schema_version")
        if schema != descriptor["schema_version"]:
            raise RfdetrCardClusterMaterializationError(
                f"{name} schema does not match materialization"
            )
        if _sha256_file(root / descriptor["path"]) != descriptor["sha256"]:
            raise RfdetrCardClusterMaterializationError(
                f"{name} digest does not match materialization"
            )
        digest_field = {
            "lineage": "lineage_digest",
            "exclusions": "exclusions_digest",
            "coverage": "coverage_digest",
            "scale": "scale_digest",
        }[name]
        embedded_core = {key: item for key, item in value.items() if key != digest_field}
        if value.get(digest_field) != sha256_json(embedded_core):
            raise RfdetrCardClusterMaterializationError(f"{name} digest does not match contents")
        if value.get("campaign_manifest_digest") != materialization["campaign_manifest"][
            "manifest_digest"
        ]:
            raise RfdetrCardClusterMaterializationError(
                f"{name} points to another campaign manifest"
            )
    return materialization


def validate_rfdetr_card_cluster_coco_annotations(raw: Mapping[str, Any]) -> None:
    """Validate one COCO detection partition and its source-linked cluster boxes."""

    if not isinstance(raw, Mapping) or set(raw) != {
        "info",
        "licenses",
        "images",
        "annotations",
        "categories",
    }:
        raise RfdetrCardClusterMaterializationError("COCO annotations have invalid fields")
    if raw["categories"] != [TARGET_CATEGORY]:
        raise RfdetrCardClusterMaterializationError("COCO category map is not card_cluster")
    info = raw["info"]
    if not isinstance(info, Mapping) or info.get("trainer_partition") not in {"train", "valid"}:
        raise RfdetrCardClusterMaterializationError("COCO trainer partition is invalid")
    images = raw["images"]
    annotations = raw["annotations"]
    if not isinstance(images, list) or not isinstance(annotations, list):
        raise RfdetrCardClusterMaterializationError("COCO images and annotations must be lists")
    image_by_id: dict[int, Mapping[str, Any]] = {}
    for image in images:
        if not isinstance(image, Mapping):
            raise RfdetrCardClusterMaterializationError("COCO image is not an object")
        image_id = _positive_int(image.get("id"), "COCO image id")
        if image_id in image_by_id:
            raise RfdetrCardClusterMaterializationError("COCO image IDs are not unique")
        width = _positive_int(image.get("width"), f"COCO image {image_id}.width")
        height = _positive_int(image.get("height"), f"COCO image {image_id}.height")
        _safe_relative_path(image.get("file_name"), f"COCO image {image_id}.file_name")
        _digest(image.get("sha256"), f"COCO image {image_id}.sha256")
        if image.get("trainer_partition") != info["trainer_partition"]:
            raise RfdetrCardClusterMaterializationError(
                "COCO image has the wrong trainer partition"
            )
        if image.get("split") not in TRAINING_PARTITIONS:
            raise RfdetrCardClusterMaterializationError("COCO image has an invalid split")
        image_by_id[image_id] = {**image, "width": width, "height": height}

    annotation_ids: set[int] = set()
    for annotation in annotations:
        if not isinstance(annotation, Mapping):
            raise RfdetrCardClusterMaterializationError("COCO annotation is not an object")
        annotation_id = _positive_int(annotation.get("id"), "COCO annotation id")
        if annotation_id in annotation_ids:
            raise RfdetrCardClusterMaterializationError("COCO annotation IDs are not unique")
        annotation_ids.add(annotation_id)
        image = image_by_id.get(annotation.get("image_id"))
        if image is None:
            raise RfdetrCardClusterMaterializationError(
                "COCO annotation references an unknown image"
            )
        if annotation.get("category_id") != 1 or annotation.get("iscrowd") != 0:
            raise RfdetrCardClusterMaterializationError(
                "COCO annotation category or crowd flag is invalid"
            )
        bbox = annotation.get("bbox")
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or any(isinstance(value, bool) or not isinstance(value, int) for value in bbox)
            or bbox[2] <= 0
            or bbox[3] <= 0
            or bbox[0] < 0
            or bbox[1] < 0
            or bbox[0] + bbox[2] > image["width"]
            or bbox[1] + bbox[3] > image["height"]
        ):
            raise RfdetrCardClusterMaterializationError("COCO card-cluster bbox is invalid")
        if annotation.get("area") != bbox[2] * bbox[3]:
            raise RfdetrCardClusterMaterializationError("COCO card-cluster area is invalid")
        members = annotation.get("member_card_ids")
        if not isinstance(members, list) or not members or len(members) != len(set(members)):
            raise RfdetrCardClusterMaterializationError("COCO cluster members are invalid")
        source_box = annotation.get("source_box")
        if not isinstance(source_box, Mapping):
            raise RfdetrCardClusterMaterializationError("COCO annotation has no source box")
        if _box_to_bbox(_pixel_box(source_box, "annotation.source_box")) != bbox:
            raise RfdetrCardClusterMaterializationError(
                "COCO bbox does not round-trip to source box"
            )
        if annotation.get("split") != image["split"]:
            raise RfdetrCardClusterMaterializationError(
                "COCO annotation split differs from image"
            )
        for field in (
            "recording_id",
            "event_id",
            "item_id",
            "reference_revision_id",
            "source_video_sha256",
            "source_frame_sha256",
            "cluster_id",
        ):
            if not isinstance(annotation.get(field), str) or not annotation[field]:
                raise RfdetrCardClusterMaterializationError(
                    f"COCO annotation is missing {field} lineage"
                )


def _validate_input_manifest(manifest: Mapping[str, Any]) -> None:
    try:
        validate_reviewed_rfdetr_detector_manifest(manifest)
    except (ReviewedRfdetrDetectorCampaignError, TypeError, ValueError) as error:
        raise RfdetrCardClusterMaterializationError(
            f"0068 M0 manifest is invalid: {error}"
        ) from error
    if manifest.get("freeze_state") != "frozen":
        raise RfdetrCardClusterMaterializationError(
            "M2 requires a frozen 0068 M0 manifest; blocked manifests are not trainer inputs"
        )
    if manifest.get("campaign_id") != RFDETR_DETECTOR_CAMPAIGN_ID:
        raise RfdetrCardClusterMaterializationError(
            "input manifest is not the reviewed 0068 campaign"
        )
    if manifest.get("schema_version") != RFDETR_DETECTOR_MANIFEST_SCHEMA_VERSION:
        raise RfdetrCardClusterMaterializationError(
            "input manifest schema is not the reviewed 0068 schema"
        )


def _reviewed_card_proposals(
    sample: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], tuple[CoarseProposal, ...]]:
    frame = sample["frame_identity"]
    width = _positive_int(frame.get("width"), "frame.width")
    height = _positive_int(frame.get("height"), "frame.height")
    targets = sample.get("targets")
    if not isinstance(targets, list) or not targets:
        raise RfdetrCardClusterMaterializationError(
            f"sample {sample.get('event_id')} has no reviewed visible-card targets"
        )
    records: list[dict[str, Any]] = []
    proposals: list[CoarseProposal] = []
    for index, target in enumerate(targets):
        if not isinstance(target, Mapping):
            raise RfdetrCardClusterMaterializationError("reviewed target is not an object")
        card_id = _identifier(target.get("card_id"), "target.card_id")
        geometry = target.get("geometry")
        if not isinstance(geometry, Mapping) or geometry.get("kind") not in {
            "visible-region/v1",
            "reviewed-visible-region/v1",
        }:
            raise RfdetrCardClusterMaterializationError(
                f"target {card_id} is not reviewed geometry"
            )
        visible_region = geometry.get("visible_region")
        polygons = visible_region.get("polygons") if isinstance(visible_region, Mapping) else None
        if not isinstance(polygons, list) or not polygons:
            raise RfdetrCardClusterMaterializationError(f"target {card_id} has no polygons")
        pixel_polygons: list[list[dict[str, float]]] = []
        points: list[tuple[float, float]] = []
        for polygon in polygons:
            if not isinstance(polygon, list) or len(polygon) < 3:
                raise RfdetrCardClusterMaterializationError(f"target {card_id} polygon is invalid")
            converted: list[dict[str, float]] = []
            for point in polygon:
                if not isinstance(point, Mapping):
                    raise RfdetrCardClusterMaterializationError(
                        f"target {card_id} point is invalid"
                    )
                x = _normalized_coordinate(point.get("x"), "target.x") * width / 1000.0
                y = _normalized_coordinate(point.get("y"), "target.y") * height / 1000.0
                converted.append({"x": round(x, 6), "y": round(y, 6)})
                points.append((x, y))
            pixel_polygons.append(converted)
        tight_box = _tight_box(points, width, height)
        proposal_id = f"card-{index + 1:04d}"
        record = {
            "card_id": card_id,
            "proposal_id": proposal_id,
            "side": target.get("side", "unknown"),
            "geometry": dict(geometry),
            "pixel_polygons": pixel_polygons,
            "tight_box": _box_mapping(tight_box),
            "source_frame_sha256": frame["image_sha256"],
            "reference_revision_id": sample["reference_revision_id"],
            "partition": sample["split"],
        }
        records.append(record)
        proposals.append(CoarseProposal(proposal_id=proposal_id, box=tight_box, score=1.0))
    return records, tuple(proposals)


def _tight_box(points: Sequence[tuple[float, float]], width: int, height: int) -> PixelBox:
    if not points:
        raise RfdetrCardClusterMaterializationError("reviewed polygon has no points")
    x_min = max(0, math.floor(min(point[0] for point in points)))
    y_min = max(0, math.floor(min(point[1] for point in points)))
    x_max = min(width, max(x_min + 1, math.ceil(max(point[0] for point in points))))
    y_max = min(height, max(y_min + 1, math.ceil(max(point[1] for point in points))))
    if x_max <= x_min or y_max <= y_min:
        raise RfdetrCardClusterMaterializationError("reviewed polygon has an empty tight box")
    return PixelBox(x_min, y_min, x_max, y_max)


def _pixel_box(value: Mapping[str, Any], field: str) -> PixelBox:
    try:
        return PixelBox(
            float(value["x_min"]),
            float(value["y_min"]),
            float(value["x_max"]),
            float(value["y_max"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RfdetrCardClusterMaterializationError(f"{field} is not a valid box") from error


def _box_mapping(box: PixelBox) -> dict[str, float | int]:
    return {
        "x_min": _number(box.x_min),
        "y_min": _number(box.y_min),
        "x_max": _number(box.x_max),
        "y_max": _number(box.y_max),
    }


def _box_to_bbox(box: PixelBox) -> list[int]:
    x_min = math.floor(box.x_min)
    y_min = math.floor(box.y_min)
    x_max = math.ceil(box.x_max)
    y_max = math.ceil(box.y_max)
    return [x_min, y_min, x_max - x_min, y_max - y_min]


def _number(value: float) -> float | int:
    return int(value) if value.is_integer() else round(value, 6)


def _coco_image(
    image_id: int,
    image_name: str,
    sample: Mapping[str, Any],
    frame_digest: str,
    partition_name: str,
    recording: Mapping[str, Any],
) -> dict[str, Any]:
    frame = sample["frame_identity"]
    group = sample.get("source_group", {})
    return {
        "id": image_id,
        "file_name": f"images/{image_name}",
        "width": frame["width"],
        "height": frame["height"],
        "sha256": frame_digest,
        "recording_id": sample["recording_id"],
        "event_id": sample["event_id"],
        "item_id": sample["item_id"],
        "reference_revision_id": sample["reference_revision_id"],
        "source_video_sha256": sample["source_sha256"],
        "source_frame_sha256": frame_digest,
        "split": sample["split"],
        "trainer_partition": partition_name,
        "session_id": recording["session_id"],
        "source_asset_id": recording["source_asset_id"],
        "video_id": recording["video_id"],
        "table_setup": recording["table_setup"],
        "source_group_key": sample.get("source_group_key", group.get("group_key")),
    }


def _coco_annotation(
    annotation_id: int,
    image_id: int,
    sample: Mapping[str, Any],
    recording: Mapping[str, Any],
    cluster: Mapping[str, Any],
) -> dict[str, Any]:
    source_box = _pixel_box(cluster["source_box"], "cluster.source_box")
    bbox = _box_to_bbox(source_box)
    return {
        "id": annotation_id,
        "image_id": image_id,
        "category_id": 1,
        "bbox": bbox,
        "area": bbox[2] * bbox[3],
        "iscrowd": 0,
        "target_state": "reviewed_card_cluster",
        "recording_id": sample["recording_id"],
        "event_id": sample["event_id"],
        "item_id": sample["item_id"],
        "reference_revision_id": sample["reference_revision_id"],
        "cluster_id": cluster["cluster_id"],
        "member_card_ids": list(cluster["member_card_ids"]),
        "member_proposal_ids": list(cluster["member_proposal_ids"]),
        "source_box": dict(cluster["source_box"]),
        "source_video_sha256": sample["source_sha256"],
        "source_frame_sha256": sample["frame_identity"]["image_sha256"],
        "split": sample["split"],
        "card_side": "card_cluster",
        "session_id": recording["session_id"],
        "source_asset_id": recording["source_asset_id"],
        "video_id": recording["video_id"],
        "table_setup": recording["table_setup"],
        "source_group_key": sample.get("source_group_key"),
    }


def _coco_payload(
    manifest: Mapping[str, Any],
    images: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    partition_name: str,
) -> dict[str, Any]:
    return {
        "info": {
            "description": "DokoDetector RF-DETR full-frame card-cluster detection view",
            "version": "card-cluster-detection-v1",
            "coco_version": COCO_VERSION,
            "campaign_id": manifest["campaign_id"],
            "campaign_manifest_digest": manifest["manifest_digest"],
            "trainer_partition": partition_name,
        },
        "licenses": [],
        "images": images,
        "annotations": annotations,
        "categories": [TARGET_CATEGORY],
    }


def _split_payload(
    manifest: Mapping[str, Any],
    images: Mapping[str, Sequence[Mapping[str, Any]]],
    annotations: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    core = {
        "schema_version": RFDETR_CARD_CLUSTER_SPLIT_SCHEMA,
        "campaign_manifest_digest": manifest["manifest_digest"],
        "train": list(manifest["split"]["train"]["recording_ids"]),
        "validation": list(manifest["split"]["validation"]["recording_ids"]),
        "sample_counts": {split: len(images[split]) for split in TRAINING_PARTITIONS},
        "cluster_counts": {split: len(annotations[split]) for split in TRAINING_PARTITIONS},
    }
    return {**core, "split_digest": sha256_json(core)}


def _lineage_payload(
    manifest: Mapping[str, Any], frames: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    core = {
        "schema_version": RFDETR_CARD_CLUSTER_LINEAGE_SCHEMA,
        "campaign_manifest_digest": manifest["manifest_digest"],
        "authority": "0068_completed_corrected_visible_card_references",
        "frames": list(frames),
    }
    return {**core, "lineage_digest": sha256_json(core)}


def _exclusions_payload(
    manifest: Mapping[str, Any], samples: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    sealed = [
        {
            "recording_id": sample["recording_id"],
            "event_id": sample["event_id"],
            "item_id": sample["item_id"],
            "split": sample["split"],
            "frame_identity": sample["frame_identity"],
            "target_count": len(sample["targets"]),
            "reason": "0068 sealed_test is not a training input",
        }
        for sample in samples
        if sample["split"] == "sealed_test"
    ]
    core = {
        "schema_version": RFDETR_CARD_CLUSTER_EXCLUSIONS_SCHEMA,
        "campaign_manifest_digest": manifest["manifest_digest"],
        "policy": {
            "training_partitions": list(TRAINING_PARTITIONS),
            "sealed_test": "explicitly excluded from materialization",
            "ignore_regions": "exclude frame and preserve receipt",
            "ineligible_outcomes": "exclude outcome and preserve receipt",
            "incomplete_coverage": "reject or preserve the 0068 exclusion receipt",
        },
        "excluded_frames": manifest["excluded_frames"],
        "ineligible_outcomes": manifest["ineligible_outcomes"],
        "sealed_test_samples": sealed,
    }
    return {**core, "exclusions_digest": sha256_json(core)}


def _coverage_payload(
    manifest: Mapping[str, Any],
    frames: Sequence[Mapping[str, Any]],
    exclusions: Mapping[str, Any],
    images: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    partition_payload: dict[str, Any] = {}
    for split in TRAINING_PARTITIONS:
        selected = [frame for frame in frames if frame["split"] == split]
        card_count = sum(int(frame["reviewed_card_count"]) for frame in selected)
        cluster_count = sum(int(frame["cluster_count"]) for frame in selected)
        partition_payload[split] = {
            "source_group_count": len(manifest["split"][split]["recording_ids"]),
            "frame_count": len(selected),
            "image_count": len(images[split]),
            "reviewed_card_count": card_count,
            "cluster_count": cluster_count,
            "cards_per_cluster": [
                count for frame in selected for count in frame["cards_per_cluster"]
            ],
            "complete_review_coverage": True,
        }
    core = {
        "schema_version": RFDETR_CARD_CLUSTER_COVERAGE_SCHEMA,
        "campaign_manifest_digest": manifest["manifest_digest"],
        "authority": "0068_completed_corrected_visible_card_references",
        "partitions": partition_payload,
        "excluded_frame_count": len(exclusions["excluded_frames"]),
        "ineligible_outcome_count": len(exclusions["ineligible_outcomes"]),
        "sealed_test_sample_count": len(exclusions["sealed_test_samples"]),
    }
    return {**core, "coverage_digest": sha256_json(core)}


def _scale_record(
    sample: Mapping[str, Any],
    layout: Any,
    cards: Sequence[Mapping[str, Any]],
    clusters: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    frame = sample["frame_identity"]
    boxes = [_pixel_box(card["tight_box"], "card.tight_box") for card in cards]
    return {
        "frame_id": _frame_id(sample),
        "recording_id": sample["recording_id"],
        "event_id": sample["event_id"],
        "split": sample["split"],
        "source_size": {"width": frame["width"], "height": frame["height"]},
        "coarse_model_input_size": CASCADE_COARSE_INPUT_SIZE,
        "source_pixels_per_coarse_input_pixel": {
            "x": round(frame["width"] / CASCADE_COARSE_INPUT_SIZE, 6),
            "y": round(frame["height"] / CASCADE_COARSE_INPUT_SIZE, 6),
        },
        "reviewed_card_pixel_sizes": [
            {"width": round(box.width, 6), "height": round(box.height, 6)} for box in boxes
        ],
        "cluster_crop_side_pixels": [
            round(float(cluster["crop_dimensions"]["width"]), 6) for cluster in clusters
        ],
        "cluster_crop_area_relative_to_source": [
            round(
                float(cluster["crop_dimensions"]["width"]) ** 2
                / (frame["width"] * frame["height"]),
                6,
            )
            for cluster in clusters
        ],
        "reference_span": layout.reference_span,
    }


def _scale_payload(
    manifest: Mapping[str, Any], frames: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    core = {
        "schema_version": RFDETR_CARD_CLUSTER_SCALE_SCHEMA,
        "campaign_manifest_digest": manifest["manifest_digest"],
        "coarse_model": {
            "class": "RFDETRSmall",
            "input_size": CASCADE_COARSE_INPUT_SIZE,
            "class_name": "card_cluster",
        },
        "frames": list(frames),
    }
    return {**core, "scale_digest": sha256_json(core)}


def _frame_id(sample: Mapping[str, Any]) -> str:
    return f"{sample['recording_id']}:{sample['event_id']}"


def _output_directory(repository: Path, output_root: str | Path | None) -> Path:
    if output_root is None:
        return repository / ".runtime" / "rfdetr-card-cluster-0071"
    path = Path(output_root).expanduser()
    return (repository / path if not path.is_absolute() else path).resolve()


def _resolve_input_path(value: str | Path, repository: Path, field: str) -> Path:
    path = Path(value).expanduser()
    resolved = path if path.is_absolute() else repository / path
    resolved = resolved.resolve()
    if not resolved.is_file():
        raise RfdetrCardClusterMaterializationError(f"{field} does not exist: {resolved}")
    return resolved


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RfdetrCardClusterMaterializationError(f"could not read {field}: {error}") from error
    if not isinstance(value, dict):
        raise RfdetrCardClusterMaterializationError(f"{field} must be an object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _relative_to_repository(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError as error:
        raise RfdetrCardClusterMaterializationError(
            f"path is outside repository root: {path}"
        ) from error


def _safe_relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RfdetrCardClusterMaterializationError(f"{field} must be a safe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise RfdetrCardClusterMaterializationError(f"{field} must be a safe relative path")
    return path.as_posix()


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value:
        raise RfdetrCardClusterMaterializationError(f"{field} must be an identifier")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RfdetrCardClusterMaterializationError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RfdetrCardClusterMaterializationError(f"{field} must be a positive integer")
    return value


def _normalized_coordinate(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise RfdetrCardClusterMaterializationError(
            f"{field} must be an integer from 0 through 1000"
        )
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RfdetrCardClusterMaterializationError(
            f"could not hash file {path}: {error}"
        ) from error
    return digest.hexdigest()


def _remove_destination(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


__all__ = [
    "COCO_VERSION",
    "RFDETR_CARD_CLUSTER_COVERAGE_SCHEMA",
    "RFDETR_CARD_CLUSTER_EXCLUSIONS_SCHEMA",
    "RFDETR_CARD_CLUSTER_LINEAGE_SCHEMA",
    "RFDETR_CARD_CLUSTER_MATERIALIZATION_SCHEMA",
    "RFDETR_CARD_CLUSTER_MATERIALIZER_VERSION",
    "RFDETR_CARD_CLUSTER_SCALE_SCHEMA",
    "RFDETR_CARD_CLUSTER_SPLIT_SCHEMA",
    "RfdetrCardClusterMaterializationError",
    "RfdetrCardClusterMaterializationResult",
    "load_rfdetr_card_cluster_materialization",
    "materialize_rfdetr_card_cluster_dataset",
    "validate_rfdetr_card_cluster_coco_annotations",
]
