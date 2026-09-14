"""Materialize the frozen epic 0067 manifest into a disposable COCO view.

The M0 manifest is the only annotation authority for this view.  This module extracts the
recorded exact frames from accepted source videos, converts reviewed visible regions to COCO
instance-segmentation annotations, and keeps excluded or ineligible outcomes in a receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .derived_view import ExactEventRequest, FFmpegFrameResolver
from .pipeline_data import RecordingVideoSource
from .rfdetr_segmentation_campaign import (
    RfdetrSegmentationCampaignError,
    canonical_json_bytes,
    sha256_json,
    validate_rfdetr_segmentation_manifest,
)

RFDETR_SEGMENTATION_MATERIALIZATION_SCHEMA_VERSION = (
    "rfdetr-segmentation-materialization/v1"
)
RFDETR_SEGMENTATION_MATERIALIZER_VERSION = "rfdetr-segmentation-materializer/v1"
RFDETR_SEGMENTATION_SPLIT_SCHEMA_VERSION = "rfdetr-segmentation-split/v1"
RFDETR_SEGMENTATION_EXCLUSIONS_SCHEMA_VERSION = "rfdetr-segmentation-exclusions/v1"
COCO_VERSION = "coco-2017"
TARGET_CATEGORY = {"id": 1, "name": "visible_card", "supercategory": "card"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FRAME_IDENTITY_FIELDS = (
    "schema_version",
    "source_video_sha256",
    "requested_time_us",
    "frame_index",
    "presentation_timestamp_us",
    "width",
    "height",
    "decoder_version",
    "transform_version",
    "output_encoding",
    "content_type",
    "policy",
)
FrameExtractor = Callable[[Path, Mapping[str, Any]], bytes]


class RfdetrSegmentationMaterializationError(ValueError):
    """The frozen RF-DETR segmentation manifest cannot be materialized safely."""


@dataclass(frozen=True, slots=True)
class RfdetrSegmentationMaterializationResult:
    """The disposable trainer view and its immutable input identity."""

    view_root: Path
    campaign_manifest_digest: str
    split_digest: str
    materialization_digest: str
    image_count: int
    annotation_count: int
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
            "excluded_frame_count": self.excluded_frame_count,
            "ineligible_outcome_count": self.ineligible_outcome_count,
        }


def materialize_rfdetr_segmentation_dataset(
    manifest_path: str | Path,
    *,
    repository_root: str | Path,
    output_root: str | Path | None = None,
    frame_extractor: FrameExtractor | None = None,
) -> RfdetrSegmentationMaterializationResult:
    """Build one deterministic COCO trainer view from a frozen M0 manifest."""

    repository = Path(repository_root).expanduser().resolve()
    source_manifest_path = _resolve_input_path(manifest_path, repository, "M0 manifest")
    manifest = _read_json(source_manifest_path, "M0 manifest")
    try:
        validate_rfdetr_segmentation_manifest(manifest)
    except (RfdetrSegmentationCampaignError, TypeError, ValueError) as error:
        raise RfdetrSegmentationMaterializationError(
            f"M0 manifest is invalid: {error}"
        ) from error
    if manifest["freeze_state"] != "frozen":
        raise RfdetrSegmentationMaterializationError(
            "M1 requires a frozen M0 manifest; blocked manifests are not trainer inputs"
        )

    samples = _validated_samples(manifest)
    recordings = _recordings_by_id(manifest)
    source_inputs = _verify_source_videos(repository, recordings)
    extractor = frame_extractor or _default_frame_extractor()
    destination = _output_directory(repository, output_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix=".rfdetr-segmentation-", dir=destination.parent))
    staging = staging_parent / destination.name
    try:
        (staging / "train" / "images").mkdir(parents=True)
        (staging / "valid" / "images").mkdir(parents=True)

        partition_samples: dict[str, list[dict[str, Any]]] = {"train": [], "validation": []}
        images_by_split: dict[str, list[dict[str, Any]]] = {"train": [], "validation": []}
        annotations_by_split: dict[str, list[dict[str, Any]]] = {
            "train": [],
            "validation": [],
        }
        generated_files: list[dict[str, Any]] = []
        image_id = 0
        annotation_id = 0
        for sample in samples:
            split = str(sample["split"])
            recording = recordings[str(sample["recording_id"])]
            frame = sample["frame_identity"]
            source_path = repository / _relative_path(
                recording["source_video_path"], "recording.source_video_path"
            )
            try:
                image_bytes = extractor(source_path, frame)
            except RfdetrSegmentationMaterializationError:
                raise
            except (OSError, RuntimeError, ValueError, TypeError) as error:
                raise RfdetrSegmentationMaterializationError(
                    f"could not extract {sample['recording_id']}:{sample['event_id']}: {error}"
                ) from error
            if not isinstance(image_bytes, bytes) or not image_bytes:
                raise RfdetrSegmentationMaterializationError(
                    f"frame extractor returned no bytes for {sample['event_id']}"
                )
            expected_frame_digest = _digest(frame.get("image_sha256"), "frame.image_sha256")
            actual_frame_digest = _sha256_bytes(image_bytes)
            if actual_frame_digest != expected_frame_digest:
                raise RfdetrSegmentationMaterializationError(
                    f"recorded frame digest differs for {sample['event_id']}"
                )

            image_id += 1
            image_name = f"image-{image_id:06d}.jpg"
            partition_name = "valid" if split == "validation" else "train"
            image_path = staging / partition_name / "images" / image_name
            image_path.write_bytes(image_bytes)
            image_record = _coco_image(
                image_id,
                image_name,
                sample,
                expected_frame_digest,
                partition_name,
            )
            images_by_split[split].append(image_record)
            partition_samples[split].append(sample)
            generated_files.append(
                {
                    "kind": "extracted_frame",
                    "path": f"{partition_name}/images/{image_name}",
                    "recording_id": sample["recording_id"],
                    "event_id": sample["event_id"],
                    "sha256": actual_frame_digest,
                }
            )
            for target in sample["targets"]:
                annotation_id += 1
                annotations_by_split[split].append(
                    _coco_annotation(annotation_id, image_id, sample, target)
                )

        split_payload = _split_payload(manifest, partition_samples)
        split_path = staging / "split.json"
        _write_json(split_path, split_payload)
        generated_files.append(
            {"kind": "trainer_split", "path": "split.json", "sha256": _sha256_file(split_path)}
        )

        for split, partition_name in (("train", "train"), ("validation", "valid")):
            coco = _coco_payload(
                manifest,
                images_by_split[split],
                annotations_by_split[split],
                partition_name,
            )
            validate_rfdetr_coco_annotations(coco)
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

        exclusions = _exclusions_payload(manifest)
        exclusions_path = staging / "exclusions.json"
        _write_json(exclusions_path, exclusions)
        generated_files.append(
            {
                "kind": "exclusion_receipt",
                "path": "exclusions.json",
                "sha256": _sha256_file(exclusions_path),
            }
        )

        generated_files.sort(key=lambda item: str(item["path"]))
        input_manifest = {
            "path": _relative_to_repository(source_manifest_path, repository),
            "manifest_digest": str(manifest["manifest_digest"]),
            "file_sha256": _sha256_file(source_manifest_path),
        }
        materialization_core: dict[str, Any] = {
            "schema_version": RFDETR_SEGMENTATION_MATERIALIZATION_SCHEMA_VERSION,
            "materializer_version": RFDETR_SEGMENTATION_MATERIALIZER_VERSION,
            "campaign_id": manifest["campaign_id"],
            "campaign_manifest": input_manifest,
            "frame_extraction": {
                "policy": "recorded-exact-event-frame-v1",
                "output_encoding": "jpeg",
                "verification": "frame_identity_and_image_sha256",
            },
            "target_conversion": {
                "source": "reviewed_visible_region",
                "normalization": "full-frame-0-1000/v1",
                "pixel_point_rounding": "six_decimal_places",
                "derived_box": "tight_floor_min_ceil_max_v1",
                "category": TARGET_CATEGORY,
            },
            "ignore_policy": "exclude_frame_on_any_reviewed_ignore_region",
            "split": {
                "path": "split.json",
                "sha256": _sha256_file(split_path),
                "digest": split_payload["split_digest"],
            },
            "inputs": source_inputs,
            "exclusions": {
                "path": "exclusions.json",
                "sha256": _sha256_file(exclusions_path),
                "excluded_frame_count": len(manifest["excluded_frames"]),
                "ineligible_outcome_count": len(manifest["ineligible_outcomes"]),
            },
            "counts": {
                "images": image_id,
                "annotations": annotation_id,
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
        return RfdetrSegmentationMaterializationResult(
            view_root=destination,
            campaign_manifest_digest=str(manifest["manifest_digest"]),
            split_digest=str(split_payload["split_digest"]),
            materialization_digest=str(materialization["materialization_digest"]),
            image_count=image_id,
            annotation_count=annotation_id,
            excluded_frame_count=len(manifest["excluded_frames"]),
            ineligible_outcome_count=len(manifest["ineligible_outcomes"]),
        )
    except RfdetrSegmentationMaterializationError:
        raise
    except (OSError, TypeError, ValueError, KeyError) as error:
        raise RfdetrSegmentationMaterializationError(
            f"could not materialize RF-DETR segmentation view: {error}"
        ) from error
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def load_rfdetr_segmentation_materialization(path: str | Path) -> dict[str, Any]:
    """Load and verify a generated RF-DETR segmentation trainer view."""

    root = Path(path).expanduser().resolve()
    manifest_path = root / "materialization.json"
    manifest = _read_json(manifest_path, "materialization manifest")
    expected = {
        "schema_version",
        "materializer_version",
        "campaign_id",
        "campaign_manifest",
        "frame_extraction",
        "target_conversion",
        "ignore_policy",
        "split",
        "inputs",
        "exclusions",
        "counts",
        "generated_files",
        "materialization_digest",
    }
    if set(manifest) != expected:
        raise RfdetrSegmentationMaterializationError(
            "materialization manifest has invalid fields"
        )
    if manifest["schema_version"] != RFDETR_SEGMENTATION_MATERIALIZATION_SCHEMA_VERSION:
        raise RfdetrSegmentationMaterializationError(
            "materialization manifest schema is unsupported"
        )
    core = {key: value for key, value in manifest.items() if key != "materialization_digest"}
    if manifest["materialization_digest"] != sha256_json(core):
        raise RfdetrSegmentationMaterializationError(
            "materialization_digest does not match manifest contents"
        )
    generated_files = manifest["generated_files"]
    if not isinstance(generated_files, list):
        raise RfdetrSegmentationMaterializationError("generated_files must be a list")
    for item in generated_files:
        if not isinstance(item, Mapping):
            raise RfdetrSegmentationMaterializationError("generated file is not an object")
        relative_path = _relative_path(item.get("path"), "generated file path")
        generated_path = root / relative_path
        if not generated_path.is_file() or _sha256_file(generated_path) != _digest(
            item.get("sha256"), f"{relative_path}.sha256"
        ):
            raise RfdetrSegmentationMaterializationError(
                f"generated file is missing or has a different digest: {relative_path}"
            )
    for partition in ("train", "valid"):
        annotations_path = root / partition / "_annotations.coco.json"
        validate_rfdetr_coco_annotations(
            _read_json(annotations_path, f"{partition} COCO annotations")
        )
        if not (root / partition / "images").is_dir():
            raise RfdetrSegmentationMaterializationError(
                f"materialization is missing {partition}/images"
            )
    _read_json(root / "split.json", "materialization split")
    _read_json(root / "exclusions.json", "materialization exclusion receipt")
    return manifest


def validate_rfdetr_coco_annotations(raw: Mapping[str, Any]) -> None:
    """Validate the COCO subset emitted by the M1 materializer."""

    data = _mapping(raw, "COCO annotations")
    expected = {"info", "licenses", "images", "annotations", "categories"}
    if set(data) != expected:
        raise RfdetrSegmentationMaterializationError("COCO annotations have invalid fields")
    if data["categories"] != [TARGET_CATEGORY]:
        raise RfdetrSegmentationMaterializationError("COCO category map is not visible_card")
    images = data["images"]
    annotations = data["annotations"]
    if not isinstance(images, list) or not isinstance(annotations, list):
        raise RfdetrSegmentationMaterializationError("COCO images and annotations must be lists")
    image_by_id: dict[int, Mapping[str, Any]] = {}
    for image in images:
        image_data = _mapping(image, "COCO image")
        image_id = _positive_int(image_data.get("id"), "COCO image id")
        if image_id in image_by_id:
            raise RfdetrSegmentationMaterializationError("COCO image IDs are not unique")
        width = _positive_int(image_data.get("width"), f"COCO image {image_id}.width")
        height = _positive_int(image_data.get("height"), f"COCO image {image_id}.height")
        _relative_path(image_data.get("file_name"), f"COCO image {image_id}.file_name")
        _digest(image_data.get("sha256"), f"COCO image {image_id}.sha256")
        image_by_id[image_id] = {**image_data, "width": width, "height": height}
    annotation_ids: set[int] = set()
    for annotation in annotations:
        item = _mapping(annotation, "COCO annotation")
        annotation_id = _positive_int(item.get("id"), "COCO annotation id")
        if annotation_id in annotation_ids:
            raise RfdetrSegmentationMaterializationError("COCO annotation IDs are not unique")
        annotation_ids.add(annotation_id)
        image_id = _positive_int(item.get("image_id"), "COCO annotation image_id")
        image = image_by_id.get(image_id)
        if image is None:
            raise RfdetrSegmentationMaterializationError(
                f"COCO annotation {annotation_id} references an unknown image"
            )
        if item.get("category_id") != 1 or item.get("iscrowd") != 0:
            raise RfdetrSegmentationMaterializationError(
                f"COCO annotation {annotation_id} has an invalid category or crowd flag"
            )
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4 or any(
            not _finite_number(value) for value in bbox
        ):
            raise RfdetrSegmentationMaterializationError(
                f"COCO annotation {annotation_id} has an invalid bbox"
            )
        x_min, y_min, box_width, box_height = bbox
        if (
            x_min < 0
            or y_min < 0
            or box_width <= 0
            or box_height <= 0
            or x_min + box_width > image["width"]
            or y_min + box_height > image["height"]
        ):
            raise RfdetrSegmentationMaterializationError(
                f"COCO annotation {annotation_id} bbox is outside its image"
            )
        segmentation = item.get("segmentation")
        if not isinstance(segmentation, list) or not segmentation:
            raise RfdetrSegmentationMaterializationError(
                f"COCO annotation {annotation_id} has no polygon segmentation"
            )
        all_points: list[tuple[float, float]] = []
        polygon_area = 0.0
        for polygon in segmentation:
            if not isinstance(polygon, list) or len(polygon) < 6 or len(polygon) % 2:
                raise RfdetrSegmentationMaterializationError(
                    f"COCO annotation {annotation_id} has an invalid polygon"
                )
            points = [
                (float(polygon[index]), float(polygon[index + 1]))
                for index in range(0, len(polygon), 2)
            ]
            if any(
                not math.isfinite(x)
                or not math.isfinite(y)
                or x < 0
                or y < 0
                or x > image["width"]
                or y > image["height"]
                for x, y in points
            ):
                raise RfdetrSegmentationMaterializationError(
                    f"COCO annotation {annotation_id} polygon is outside its image"
                )
            all_points.extend(points)
            polygon_area += abs(_shoelace(points)) / 2.0
        if polygon_area <= 0 or not _finite_number(item.get("area")):
            raise RfdetrSegmentationMaterializationError(
                f"COCO annotation {annotation_id} has a non-positive area"
            )
        if not math.isclose(float(item["area"]), polygon_area, rel_tol=0, abs_tol=0.00001):
            raise RfdetrSegmentationMaterializationError(
                f"COCO annotation {annotation_id} area does not match its polygon"
            )
        expected_bbox = _tight_bbox(all_points, image["width"], image["height"])
        if bbox != expected_bbox:
            raise RfdetrSegmentationMaterializationError(
                f"COCO annotation {annotation_id} bbox is not derived from its polygon"
            )
        for field in (
            "recording_id",
            "event_id",
            "item_id",
            "reference_revision_id",
            "card_id",
            "source_video_sha256",
            "source_frame_sha256",
        ):
            if not isinstance(item.get(field), str) or not item[field]:
                raise RfdetrSegmentationMaterializationError(
                    f"COCO annotation {annotation_id} is missing {field} lineage"
                )


def _validated_samples(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    recordings = _recordings_by_id(manifest)
    split_recordings = {
        split: set(_mapping(manifest["split"][split], f"split.{split}").get("recording_ids", []))
        for split in ("train", "validation")
    }
    result: list[dict[str, Any]] = []
    sample_keys: set[tuple[str, str]] = set()
    frame_keys: set[tuple[str, int]] = set()
    for index, raw_sample in enumerate(manifest["samples"]):
        sample = _mapping(raw_sample, f"samples[{index}]")
        recording_id = _identifier(sample.get("recording_id"), f"samples[{index}].recording_id")
        split = sample.get("split")
        if split not in {"train", "validation"} or recording_id not in split_recordings[split]:
            raise RfdetrSegmentationMaterializationError(
                f"sample {index} is not in its frozen recording split"
            )
        if recording_id not in recordings:
            raise RfdetrSegmentationMaterializationError(
                f"sample {index} references an unknown recording"
            )
        event_id = _identifier(sample.get("event_id"), f"samples[{index}].event_id")
        item_id = _identifier(sample.get("item_id"), f"samples[{index}].item_id")
        key = (recording_id, event_id)
        if key in sample_keys:
            raise RfdetrSegmentationMaterializationError("M0 samples contain duplicate events")
        sample_keys.add(key)
        frame = _mapping(sample.get("frame_identity"), f"samples[{index}].frame_identity")
        frame_index = _non_negative_int(frame.get("frame_index"), f"samples[{index}].frame_index")
        _digest(frame.get("image_sha256"), f"samples[{index}].image_sha256")
        source_digest = _digest(
            frame.get("source_video_sha256"), f"samples[{index}].source_video_sha256"
        )
        recording = recordings[recording_id]
        if source_digest != recording.get("source_sha256") or sample.get(
            "source_sha256"
        ) != source_digest:
            raise RfdetrSegmentationMaterializationError(
                f"sample {event_id} source digest differs from its recording"
            )
        frame_key = (source_digest, frame_index)
        if frame_key in frame_keys:
            raise RfdetrSegmentationMaterializationError(
                f"sample {event_id} reuses a source frame"
            )
        frame_keys.add(frame_key)
        width = _positive_int(frame.get("width"), f"samples[{index}].width")
        height = _positive_int(frame.get("height"), f"samples[{index}].height")
        targets = sample.get("targets")
        if not isinstance(targets, list) or not targets:
            raise RfdetrSegmentationMaterializationError(
                f"sample {event_id} has no retained target; empty outcomes stay ineligible"
            )
        normalized_targets: list[dict[str, Any]] = []
        card_ids: set[str] = set()
        for target_index, raw_target in enumerate(targets):
            target = _mapping(raw_target, f"sample {event_id}.targets[{target_index}]")
            card_id = _identifier(target.get("card_id"), f"sample {event_id}.card_id")
            if card_id in card_ids:
                raise RfdetrSegmentationMaterializationError(
                    f"sample {event_id} has duplicate card IDs"
                )
            card_ids.add(card_id)
            normalization = _mapping(
                target.get("normalization"), f"sample {event_id}.target.normalization"
            )
            if (
                normalization.get("policy_id") != "full-frame-0-1000/v1"
                or normalization.get("width") != width
                or normalization.get("height") != height
            ):
                raise RfdetrSegmentationMaterializationError(
                    f"sample {event_id} target normalization does not match its frame"
                )
            normalized_targets.append(dict(target))
        result.append(
            {
                **dict(sample),
                "recording_id": recording_id,
                "split": split,
                "event_id": event_id,
                "item_id": item_id,
                "frame_identity": dict(frame),
                "targets": normalized_targets,
            }
        )
    return sorted(
        result,
        key=lambda sample: (
            0 if sample["split"] == "train" else 1,
            str(sample["recording_id"]),
            str(sample["event_id"]),
            int(sample["frame_identity"]["frame_index"]),
        ),
    )


def _recordings_by_id(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    recordings: dict[str, Mapping[str, Any]] = {}
    for raw_recording in manifest["recordings"]:
        recording = _mapping(raw_recording, "recording")
        recording_id = _identifier(recording.get("recording_id"), "recording.recording_id")
        if recording_id in recordings:
            raise RfdetrSegmentationMaterializationError("M0 recordings are not unique")
        recordings[recording_id] = recording
    return recordings


def _verify_source_videos(
    repository: Path, recordings: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for recording_id in sorted(recordings):
        recording = recordings[recording_id]
        relative_path = _relative_path(
            recording.get("source_video_path"), f"{recording_id}.source_video_path"
        )
        path = repository / relative_path
        if not path.is_file():
            raise RfdetrSegmentationMaterializationError(
                f"source video is missing for {recording_id}"
            )
        expected_size = _positive_int(
            recording.get("source_byte_length"), f"{recording_id}.source_byte_length"
        )
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise RfdetrSegmentationMaterializationError(
                f"source video byte length differs for {recording_id}"
            )
        expected_digest = _digest(recording.get("source_sha256"), f"{recording_id}.source_sha256")
        actual_digest = _sha256_file(path)
        if actual_digest != expected_digest:
            raise RfdetrSegmentationMaterializationError(
                f"source video digest differs for {recording_id}"
            )
        result.append(
            {
                "recording_id": recording_id,
                "path": relative_path,
                "sha256": actual_digest,
                "byte_length": actual_size,
                "split": recording.get("split"),
                "session_id": recording.get("session_id"),
                "table_setup": recording.get("table_setup"),
                "source_asset_id": recording.get("source_asset_id"),
            }
        )
    return result


def _default_frame_extractor() -> FrameExtractor:
    resolver = FFmpegFrameResolver()

    def extract(video_path: Path, frame: Mapping[str, Any]) -> bytes:
        requested = frame.get("requested_time_us")
        presentation = frame.get("presentation_timestamp_us")
        if isinstance(requested, int) and not isinstance(requested, bool) and isinstance(
            presentation, int
        ) and not isinstance(presentation, bool):
            digest = _digest(frame.get("source_video_sha256"), "frame.source_video_sha256")
            source = RecordingVideoSource(
                recording_id="rfdetr-segmentation-source",
                relative_path=video_path.name,
                video_sha256=digest,
                byte_length=video_path.stat().st_size,
                duration_us=max(requested, presentation) + 1,
            )
            request = ExactEventRequest(
                source=source,
                requested_time_us=requested,
                output_encoding="jpeg",
            )
            resolved = resolver.resolve(request, video_path)
            identity = resolved.identity_mapping()
            for field in _FRAME_IDENTITY_FIELDS:
                if field in frame and identity.get(field) != frame[field]:
                    raise RfdetrSegmentationMaterializationError(
                        f"extracted frame identity differs in {field}"
                    )
            return resolved.image_bytes
        return _decode_frame_by_index(
            video_path, _non_negative_int(frame.get("frame_index"), "frame_index")
        )

    return extract


def _decode_frame_by_index(video_path: Path, frame_index: int) -> bytes:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(video_path),
        "-vf",
        f"select=eq(n\\,{frame_index})",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-c:v",
        "mjpeg",
        "-q:v",
        "2",
        "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise RfdetrSegmentationMaterializationError(
            f"ffmpeg could not extract frame {frame_index}: {error}"
        ) from error
    if result.returncode != 0 or not result.stdout:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RfdetrSegmentationMaterializationError(
            f"ffmpeg could not extract frame {frame_index}: {detail or result.returncode}"
        )
    return result.stdout


def _coco_image(
    image_id: int,
    image_name: str,
    sample: Mapping[str, Any],
    frame_digest: str,
    partition_name: str,
) -> dict[str, Any]:
    frame = sample["frame_identity"]
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
    }


def _coco_annotation(
    annotation_id: int,
    image_id: int,
    sample: Mapping[str, Any],
    target: Mapping[str, Any],
) -> dict[str, Any]:
    frame = sample["frame_identity"]
    width, height = frame["width"], frame["height"]
    geometry = _mapping(target.get("geometry"), f"{sample['event_id']}.target.geometry")
    if geometry.get("kind") not in {"visible-region/v1", "reviewed-visible-region/v1"}:
        raise RfdetrSegmentationMaterializationError(
            f"target {target.get('card_id')} is not a visible-region geometry"
        )
    visible_region = _mapping(
        geometry.get("visible_region"), f"{sample['event_id']}.target.visible_region"
    )
    raw_polygons = visible_region.get("polygons")
    if not isinstance(raw_polygons, list) or not raw_polygons:
        raise RfdetrSegmentationMaterializationError(
            f"target {target.get('card_id')} has no visible-region polygons"
        )
    segmentation: list[list[float]] = []
    points: list[tuple[float, float]] = []
    area = 0.0
    for polygon_index, raw_polygon in enumerate(raw_polygons):
        if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
            raise RfdetrSegmentationMaterializationError(
                f"target {target.get('card_id')} polygon {polygon_index} has too few points"
            )
        converted: list[float] = []
        polygon_points: list[tuple[float, float]] = []
        for point in raw_polygon:
            point_data = _mapping(point, "visible-region point")
            x = _normalized_coordinate(point_data.get("x"), "visible-region x")
            y = _normalized_coordinate(point_data.get("y"), "visible-region y")
            pixel_point = (round(x * width / 1000.0, 6), round(y * height / 1000.0, 6))
            polygon_points.append(pixel_point)
            converted.extend(pixel_point)
        polygon_area = abs(_shoelace(polygon_points)) / 2.0
        if polygon_area <= 0:
            raise RfdetrSegmentationMaterializationError(
                f"target {target.get('card_id')} polygon {polygon_index} has zero area"
            )
        segmentation.append(converted)
        points.extend(polygon_points)
        area += polygon_area
    bbox = _tight_bbox(points, width, height)
    frame_digest = _digest(frame.get("image_sha256"), "frame.image_sha256")
    return {
        "id": annotation_id,
        "image_id": image_id,
        "category_id": 1,
        "bbox": bbox,
        "area": round(area, 6),
        "segmentation": segmentation,
        "iscrowd": 0,
        "target_state": "reviewed_visible_region",
        "recording_id": sample["recording_id"],
        "event_id": sample["event_id"],
        "item_id": sample["item_id"],
        "reference_revision_id": sample["reference_revision_id"],
        "card_id": target["card_id"],
        "source_video_sha256": sample["source_sha256"],
        "source_frame_sha256": frame_digest,
        "target_geometry_sha256": sha256_json(geometry),
    }


def _coco_payload(
    manifest: Mapping[str, Any],
    images: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    partition_name: str,
) -> dict[str, Any]:
    return {
        "info": {
            "description": "DokoDetector RF-DETR visible-region instance-segmentation view",
            "version": "visible-region-segmentation-poc-v1",
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
    manifest: Mapping[str, Any], partition_samples: Mapping[str, list[Mapping[str, Any]]]
) -> dict[str, Any]:
    core = {
        "schema_version": RFDETR_SEGMENTATION_SPLIT_SCHEMA_VERSION,
        "campaign_manifest_digest": manifest["manifest_digest"],
        "train": list(manifest["split"]["train"]["recording_ids"]),
        "validation": list(manifest["split"]["validation"]["recording_ids"]),
        "test": [],
        "sample_counts": {
            "train": len(partition_samples["train"]),
            "validation": len(partition_samples["validation"]),
        },
    }
    return {**core, "split_digest": sha256_json(core)}


def _exclusions_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    core = {
        "schema_version": RFDETR_SEGMENTATION_EXCLUSIONS_SCHEMA_VERSION,
        "campaign_manifest_digest": manifest["manifest_digest"],
        "policy": "exclude_frame_and_preserve_ineligible_outcome_receipt",
        "excluded_frames": manifest["excluded_frames"],
        "ineligible_outcomes": manifest["ineligible_outcomes"],
    }
    return {**core, "exclusions_digest": sha256_json(core)}


def _resolve_input_path(value: str | Path, repository: Path, field: str) -> Path:
    path = Path(value).expanduser()
    resolved = path if path.is_absolute() else repository / path
    resolved = resolved.resolve()
    if not resolved.is_file():
        raise RfdetrSegmentationMaterializationError(f"{field} does not exist: {resolved}")
    return resolved


def _output_directory(repository: Path, output_root: str | Path | None) -> Path:
    if output_root is None:
        return repository / ".runtime" / "rfdetr-segmentation-0067"
    path = Path(output_root).expanduser()
    return (repository / path if not path.is_absolute() else path).resolve()


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RfdetrSegmentationMaterializationError(f"could not read {field}: {error}") from error
    return dict(_mapping(value, field))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RfdetrSegmentationMaterializationError(f"{field} must be a relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise RfdetrSegmentationMaterializationError(f"{field} must be a safe relative path")
    return path.as_posix()


def _relative_to_repository(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError as error:
        raise RfdetrSegmentationMaterializationError(
            f"path is outside repository root: {path}"
        ) from error


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value:
        raise RfdetrSegmentationMaterializationError(f"{field} must be an identifier")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RfdetrSegmentationMaterializationError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RfdetrSegmentationMaterializationError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RfdetrSegmentationMaterializationError(f"{field} must be a non-negative integer")
    return value


def _normalized_coordinate(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise RfdetrSegmentationMaterializationError(
            f"{field} must be an integer from 0 through 1000"
        )
    return value


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise RfdetrSegmentationMaterializationError(f"{field} must be an object")
    return value


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _shoelace(points: list[tuple[float, float]]) -> float:
    return sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    ) / 2.0


def _tight_bbox(
    points: list[tuple[float, float]], width: int, height: int
) -> list[int | float]:
    if not points:
        raise RfdetrSegmentationMaterializationError("polygon has no points")
    x_min = max(0, min(width - 1, math.floor(min(point[0] for point in points))))
    y_min = max(0, min(height - 1, math.floor(min(point[1] for point in points))))
    x_max = min(width, max(x_min + 1, math.ceil(max(point[0] for point in points))))
    y_max = min(height, max(y_min + 1, math.ceil(max(point[1] for point in points))))
    if x_max <= x_min or y_max <= y_min:
        raise RfdetrSegmentationMaterializationError("polygon has an empty derived box")
    return [x_min, y_min, x_max - x_min, y_max - y_min]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RfdetrSegmentationMaterializationError(
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
    "RFDETR_SEGMENTATION_EXCLUSIONS_SCHEMA_VERSION",
    "RFDETR_SEGMENTATION_MATERIALIZATION_SCHEMA_VERSION",
    "RFDETR_SEGMENTATION_MATERIALIZER_VERSION",
    "RFDETR_SEGMENTATION_SPLIT_SCHEMA_VERSION",
    "RfdetrSegmentationMaterializationError",
    "RfdetrSegmentationMaterializationResult",
    "FrameExtractor",
    "load_rfdetr_segmentation_materialization",
    "materialize_rfdetr_segmentation_dataset",
    "validate_rfdetr_coco_annotations",
]
