"""Materialize the frozen epic 0084 poses as a disposable COCO training view."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .card_plane_geometry import (
    CardPlaneGeometryError,
    ReviewedCardScene,
    derive_visible_masks,
    mask_bbox,
    project_rounded_card,
    rasterize_polygon,
    virtual_card_long_size,
)
from .derived_view import ExactEventRequest, FFmpegFrameResolver
from .pipeline_data import RecordingVideoSource
from .rfdetr_segmentation_campaign import sha256_json

POSE_DERIVED_MATERIALIZATION_SCHEMA_VERSION = "rfdetr-pose-derived-materialization/v1"
POSE_DERIVED_MATERIALIZER_VERSION = "rfdetr-pose-derived-materializer/v1"
POSE_DERIVED_COCO_INFO = {
    "description": "Epic 0084 pose-derived visible-card training view",
    "version": "1",
    "year": 2026,
    "contributor": "DokoDetector",
    "date_created": "2026-09-25",
    "campaign_id": "0084-m0-rfdetr-pose-derived-visible-cards",
}
POSE_DERIVED_CATEGORY = {"id": 1, "name": "visible_card", "supercategory": "card"}
DEFAULT_POSE_DERIVED_OUTPUT = Path("data/operations/rfdetr-pose-derived-0084-m1")


class RfdetrPoseDerivedMaterializationError(ValueError):
    """The frozen pose-derived campaign cannot be materialized safely."""


class _InvalidPoseMaskError(RfdetrPoseDerivedMaterializationError):
    def __init__(self, pose_id: str, detail: str) -> None:
        self.pose_id = pose_id
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class RfdetrPoseDerivedMaterializationResult:
    """Identity and counts for one frozen pose-derived view."""

    view_root: Path
    m0_manifest_digest: str
    materialization_digest: str
    image_count: int
    annotation_count: int
    excluded_scene_count: int
    hidden_card_count: int
    excluded_card_count: int

    def to_mapping(self) -> dict[str, Any]:
        return {
            "view_root": str(self.view_root),
            "m0_manifest_digest": self.m0_manifest_digest,
            "materialization_digest": self.materialization_digest,
            "image_count": self.image_count,
            "annotation_count": self.annotation_count,
            "excluded_scene_count": self.excluded_scene_count,
            "hidden_card_count": self.hidden_card_count,
            "excluded_card_count": self.excluded_card_count,
        }


FrameExtractor = Callable[[Path, Mapping[str, Any]], bytes]


def materialize_rfdetr_pose_derived_dataset(
    manifest_path: str | Path,
    *,
    repository_root: str | Path,
    output_root: str | Path | None = None,
    frame_extractor: FrameExtractor | None = None,
) -> RfdetrPoseDerivedMaterializationResult:
    """Extract exact source frames and write deterministic visible-card COCO RLE masks."""

    repository = Path(repository_root).expanduser().resolve()
    source_manifest_path = _resolve_path(manifest_path, repository, "M0 manifest")
    manifest = _read_json(source_manifest_path, "M0 manifest")
    _validate_m0_manifest(manifest)
    if manifest["freeze_state"] != "frozen":
        raise RfdetrPoseDerivedMaterializationError("M1 requires a frozen M0 manifest")

    destination = _resolve_path(output_root or DEFAULT_POSE_DERIVED_OUTPUT, repository, "output")
    source_videos = _verified_source_videos(repository, manifest)
    proposal_cache, detector_cache = _load_revision_inputs(repository, manifest)
    extractor = frame_extractor or _frame_extractor()

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix=".pose-derived-0084-", dir=destination.parent))
    staging = staging_parent / destination.name
    try:
        image_dir = staging / "train" / "images"
        image_dir.mkdir(parents=True)
        images: list[dict[str, Any]] = []
        annotations: list[dict[str, Any]] = []
        generated_files: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = [
            {
                "kind": "m0_excluded_scene",
                "recording_id": row.get("recording_id"),
                "frame_id": row.get("frame_id"),
                "run_id": row.get("run_id"),
                "reasons": row.get("reasons", []),
            }
            for row in manifest.get("excluded_scenes", [])
            if isinstance(row, Mapping)
        ]
        hidden_count = 0
        excluded_card_count = 0

        for image_id, raw_entry in enumerate(manifest["eligible_scenes"], start=1):
            entry = {**raw_entry, "m0_manifest_digest": manifest["manifest_digest"]}
            scene = _scene_input(entry, proposal_cache, detector_cache)
            frame_identity = scene["frame_identity"]
            recording_id = str(entry["recording_id"])
            source = source_videos.get(recording_id)
            if source is None:
                raise RfdetrPoseDerivedMaterializationError(
                    f"M0 has no verified source video for {recording_id}"
                )
            video_path = repository / _relative_path(source["relative_path"], "source video path")
            try:
                image_bytes = extractor(video_path, frame_identity)
            except RfdetrPoseDerivedMaterializationError:
                raise
            except (OSError, RuntimeError, ValueError, TypeError) as error:
                raise RfdetrPoseDerivedMaterializationError(
                    f"could not extract {recording_id}:{entry['frame_id']}: {error}"
                ) from error
            if not isinstance(image_bytes, bytes) or not image_bytes:
                raise RfdetrPoseDerivedMaterializationError(
                    f"frame extractor returned no bytes for {entry['frame_id']}"
                )
            frame_digest = _checked_frame_digest(image_bytes, entry)
            decoded_image = cv2.imdecode(
                np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if (
                decoded_image is None
                or decoded_image.shape[1] != frame_identity["width"]
                or decoded_image.shape[0] != frame_identity["height"]
            ):
                raise RfdetrPoseDerivedMaterializationError(
                    f"source frame dimensions differ for {entry['frame_id']}"
                )

            try:
                full_masks, visible_masks = _derive_masks(scene["scene"], scene["calibration"])
            except _InvalidPoseMaskError as error:
                receipts.append(
                    {
                        "kind": "m1_excluded_scene",
                        "recording_id": recording_id,
                        "frame_id": entry["frame_id"],
                        "proposal_revision_id": entry["proposal_revision_id"],
                            "reason": "invalid_pose_mask_scene",
                            "cards": [
                                {
                                    **_card_receipt(entry, error.pose_id, "invalid_mask_geometry"),
                                    "kind": "m1_invalid_mask",
                                    "detail": str(error),
                                }
                        ],
                    }
                )
                continue
            frame_annotations: list[dict[str, Any]] = []
            frame_receipts: list[dict[str, Any]] = []
            for pose_index, (pose, full_mask, mask) in enumerate(
                zip(scene["scene"].poses, full_masks, visible_masks, strict=True)
            ):
                card_id = pose.card_id
                full_pixels = int(np.count_nonzero(full_mask))
                visible_pixels = int(np.count_nonzero(mask))
                if full_pixels == 0:
                    frame_receipts.append(
                        _card_receipt(entry, card_id, "fully_clipped_outside_source_frame")
                    )
                    continue
                if visible_pixels == 0:
                    hidden_count += 1
                    frame_receipts.append(
                        _card_receipt(
                            entry,
                            card_id,
                            "fully_hidden_by_front_cards",
                            full_pixel_count=full_pixels,
                        )
                    )
                    continue
                occluded_pixels = full_pixels - visible_pixels
                if occluded_pixels > 0:
                    frame_receipts.append(
                        _card_receipt(
                            entry,
                            card_id,
                            "partially_occluded_by_front_cards",
                            full_pixel_count=full_pixels,
                            occluded_pixel_count=occluded_pixels,
                            visible_pixel_count=visible_pixels,
                        )
                    )
                box = mask_bbox(mask)
                if (
                    visible_pixels < manifest["mask_policy"]["minimum_visible_pixels"]
                    or box[2] < manifest["mask_policy"]["minimum_tight_box_width_pixels"]
                    or box[3] < manifest["mask_policy"]["minimum_tight_box_height_pixels"]
                ):
                    excluded_card_count += 1
                    frame_receipts.append(
                        _card_receipt(
                            entry,
                            card_id,
                            "below_frozen_visible_mask_minimum",
                            visible_pixels=visible_pixels,
                            tight_box=box,
                        )
                    )
                    continue
                annotation_id = len(annotations) + len(frame_annotations) + 1
                frame_annotations.append(
                    _coco_rle_annotation(
                        annotation_id=annotation_id,
                        image_id=image_id,
                        entry=entry,
                        pose_id=card_id,
                        pose_index=pose_index,
                        mask=mask,
                        box=box,
                        scene=scene["scene"],
                    )
                )
            if not frame_annotations:
                receipts.append(
                    {
                        "kind": "m1_excluded_scene",
                        "recording_id": recording_id,
                        "frame_id": entry["frame_id"],
                        "proposal_revision_id": entry["proposal_revision_id"],
                        "reason": "no_cards_passed_visible_mask_minimum",
                        "cards": frame_receipts,
                    }
                )
                continue
            image_name = f"image-{image_id:06d}.jpg"
            image_path = image_dir / image_name
            image_path.write_bytes(image_bytes)
            images.append(
                {
                    "id": image_id,
                    "file_name": f"images/{image_name}",
                    "width": frame_identity["width"],
                    "height": frame_identity["height"],
                    "sha256": frame_digest,
                    "recording_id": recording_id,
                    "frame_id": entry["frame_id"],
                    "frame_index": frame_identity["frame_index"],
                    "requested_time_us": frame_identity["requested_time_us"],
                    "presentation_timestamp_us": frame_identity["presentation_timestamp_us"],
                    "source_video_sha256": frame_identity["source_video_sha256"],
                    "source_group": dict(entry["source_group"]),
                    "source_group_key": entry["source_group"]["group_key"],
                    "split": "train",
                    "m0_manifest_digest": manifest["manifest_digest"],
                    "proposal_revision_id": entry["proposal_revision_id"],
                    "calibration_digest": entry["calibration_digest"],
                    "scene_digest": entry["scene_digest"],
                }
            )
            annotations.extend(frame_annotations)
            if frame_receipts:
                receipts.append(
                    {
                        "kind": "m1_card_receipts",
                        "recording_id": recording_id,
                        "frame_id": entry["frame_id"],
                        "proposal_revision_id": entry["proposal_revision_id"],
                        "cards": frame_receipts,
                    }
                )
            generated_files.append(
                {
                    "kind": "source_frame",
                    "path": f"train/images/{image_name}",
                    "recording_id": recording_id,
                    "frame_id": entry["frame_id"],
                    "sha256": frame_digest,
                }
            )

        minimums = manifest["mask_policy"]["mask_minimum_gate"]
        groups = {image["source_group_key"] for image in images}
        if (
            len(images) < minimums["minimum_frames"]
            or len(annotations) < minimums["minimum_masks"]
            or len(groups) < minimums["minimum_source_groups"]
        ):
            raise RfdetrPoseDerivedMaterializationError(
                "materialized masks fail the M0 minimum gate: "
                f"{len(images)} frames, {len(annotations)} masks, {len(groups)} source groups"
            )

        coco = {
            "info": {
                **POSE_DERIVED_COCO_INFO,
                "m0_manifest_digest": manifest["manifest_digest"],
                "materialization_schema_version": POSE_DERIVED_MATERIALIZATION_SCHEMA_VERSION,
                "split": "train",
            },
            "licenses": [],
            "images": images,
            "annotations": annotations,
            "categories": [POSE_DERIVED_CATEGORY],
        }
        _validate_coco_rle(coco)
        annotation_path = staging / "train" / "_annotations.coco.json"
        _write_json(annotation_path, coco)
        generated_files.append(
            {
                "kind": "coco_rle_annotations",
                "path": "train/_annotations.coco.json",
                "sha256": _sha256_file(annotation_path),
            }
        )
        split_payload = {
            "schema_version": "rfdetr-pose-derived-split/v1",
            "campaign_id": manifest["campaign_id"],
            "m0_manifest_digest": manifest["manifest_digest"],
            "train": {
                "source_group_keys": sorted(groups),
                "image_ids": [image["id"] for image in images],
                "annotation_ids": [annotation["id"] for annotation in annotations],
            },
        }
        split_payload["split_digest"] = sha256_json(split_payload)
        split_path = staging / "split.json"
        _write_json(split_path, split_payload)
        generated_files.append(
            {"kind": "trainer_split", "path": "split.json", "sha256": _sha256_file(split_path)}
        )
        exclusion_payload = {
            "schema_version": "rfdetr-pose-derived-exclusions/v1",
            "campaign_id": manifest["campaign_id"],
            "m0_manifest_digest": manifest["manifest_digest"],
            "receipts": receipts,
            "counts": {
                "m0_excluded_scenes": sum(
                    row.get("kind") == "m0_excluded_scene" for row in receipts
                ),
                "m1_excluded_scenes": sum(
                    row.get("kind") == "m1_excluded_scene" for row in receipts
                ),
                "fully_hidden_cards": hidden_count,
                "below_minimum_cards": excluded_card_count,
            },
        }
        exclusion_payload["exclusions_digest"] = sha256_json(exclusion_payload)
        exclusion_path = staging / "exclusions.json"
        _write_json(exclusion_path, exclusion_payload)
        generated_files.append(
            {
                "kind": "exclusion_receipt",
                "path": "exclusions.json",
                "sha256": _sha256_file(exclusion_path),
            }
        )
        generated_files.sort(key=lambda item: item["path"])
        core = {
            "schema_version": POSE_DERIVED_MATERIALIZATION_SCHEMA_VERSION,
            "materializer_version": POSE_DERIVED_MATERIALIZER_VERSION,
            "campaign_id": manifest["campaign_id"],
            "m0_manifest": {
                "path": _relative_path_in_repo(source_manifest_path, repository),
                "manifest_digest": manifest["manifest_digest"],
                "file_sha256": _sha256_file(source_manifest_path),
            },
            "mask_policy": dict(manifest["mask_policy"]),
            "encoding": {
                "format": "COCO_RLE/uncompressed/v1",
                "order": "column-major",
                "decoded_mask_sha256": "sha256-C-contiguous-uint8-0-or-1",
            },
            "source_videos": [
                {
                    "recording_id": row["recording_id"],
                    "path": row["relative_path"],
                    "sha256": row["sha256"],
                    "byte_length": row["byte_length"],
                }
                for row in sorted(source_videos.values(), key=lambda value: value["recording_id"])
            ],
            "counts": {
                "images": len(images),
                "annotations": len(annotations),
                "source_groups": len(groups),
                "hidden_cards": hidden_count,
                "excluded_cards": excluded_card_count,
                "excluded_scenes": exclusion_payload["counts"]["m1_excluded_scenes"],
            },
            "generated_files": generated_files,
        }
        materialization = {
            **core,
            "materialization_digest": sha256_json(core),
        }
        materialization_path = staging / "materialization.json"
        _write_json(materialization_path, materialization)
        load_rfdetr_pose_derived_materialization(staging)

        if destination.exists() or destination.is_symlink():
            existing = load_rfdetr_pose_derived_materialization(destination)
            if existing["materialization_digest"] != materialization["materialization_digest"]:
                raise RfdetrPoseDerivedMaterializationError(
                    "output exists with a different materialization digest; "
                    "choose a new output path"
                )
            return _result_from_manifest(destination, existing)
        os.replace(staging, destination)
        return _result_from_manifest(destination, materialization)
    except RfdetrPoseDerivedMaterializationError:
        raise
    except (OSError, TypeError, ValueError, KeyError, CardPlaneGeometryError) as error:
        raise RfdetrPoseDerivedMaterializationError(
            f"could not materialize pose-derived RF-DETR view: {error}"
        ) from error
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def load_rfdetr_pose_derived_materialization(path: str | Path) -> dict[str, Any]:
    """Load and verify generated files, COCO RLE counts, boxes, and mask digests."""

    root = Path(path).expanduser().resolve()
    materialization = _read_json(root / "materialization.json", "materialization manifest")
    expected = {
        "schema_version",
        "materializer_version",
        "campaign_id",
        "m0_manifest",
        "mask_policy",
        "encoding",
        "source_videos",
        "counts",
        "generated_files",
        "materialization_digest",
    }
    if set(materialization) != expected:
        raise RfdetrPoseDerivedMaterializationError("materialization manifest has invalid fields")
    core = {key: value for key, value in materialization.items() if key != "materialization_digest"}
    if materialization["materialization_digest"] != sha256_json(core):
        raise RfdetrPoseDerivedMaterializationError("materialization digest does not match content")
    for item in materialization["generated_files"]:
        path_value = _relative_path(item.get("path"), "generated file path")
        file_path = root / path_value
        if not file_path.is_file() or _sha256_file(file_path) != item.get("sha256"):
            raise RfdetrPoseDerivedMaterializationError(
                f"generated file is missing or has a different digest: {path_value}"
            )
    coco = _read_json(root / "train" / "_annotations.coco.json", "COCO RLE annotations")
    _validate_coco_rle(coco)
    split = _read_json(root / "split.json", "trainer split")
    split_core = {key: value for key, value in split.items() if key != "split_digest"}
    if split.get("split_digest") != sha256_json(split_core):
        raise RfdetrPoseDerivedMaterializationError("trainer split digest does not match content")
    exclusions = _read_json(root / "exclusions.json", "exclusion receipts")
    exclusion_core = {key: value for key, value in exclusions.items() if key != "exclusions_digest"}
    if exclusions.get("exclusions_digest") != sha256_json(exclusion_core):
        raise RfdetrPoseDerivedMaterializationError("exclusion digest does not match content")
    if (
        materialization["counts"].get("images") != len(coco["images"])
        or materialization["counts"].get("annotations") != len(coco["annotations"])
    ):
        raise RfdetrPoseDerivedMaterializationError("materialization counts differ from COCO data")
    return materialization


def _scene_input(
    entry: Mapping[str, Any],
    proposal_cache: Mapping[str, tuple[Mapping[str, Any], Mapping[str, Any]]],
    detector_cache: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    revision_id = str(entry["proposal_revision_id"])
    proposal_content, proposal_manifest = proposal_cache[revision_id]
    if _sha256_json_bytes(proposal_content) != entry["proposal_content_sha256"]:
        raise RfdetrPoseDerivedMaterializationError(f"proposal content changed: {revision_id}")
    if _sha256_file(Path(proposal_manifest["_manifest_path"])) != entry["proposal_revision_sha256"]:
        raise RfdetrPoseDerivedMaterializationError(f"proposal revision changed: {revision_id}")
    frame = _mapping_by_key(proposal_content["frames"], "frame_id", str(entry["frame_id"]))
    proposal = frame.get("proposal")
    if not isinstance(proposal, Mapping):
        raise RfdetrPoseDerivedMaterializationError(f"proposal is missing: {entry['frame_id']}")
    if frame.get("source_frame_digest") != entry["source_frame_digest"]:
        raise RfdetrPoseDerivedMaterializationError(f"frame digest changed: {entry['frame_id']}")
    raw_scene = proposal.get("initialized_scene")
    if not isinstance(raw_scene, Mapping):
        raise RfdetrPoseDerivedMaterializationError(f"pose scene is missing: {entry['frame_id']}")
    scene = ReviewedCardScene.from_mapping(raw_scene)
    if scene.scene_digest != entry["scene_digest"]:
        raise RfdetrPoseDerivedMaterializationError(
            f"pose scene digest changed: {entry['frame_id']}"
        )
    if sorted(pose.card_id for pose in scene.poses) != sorted(entry["pose_ids"]):
        raise RfdetrPoseDerivedMaterializationError(f"pose membership changed: {entry['frame_id']}")
    calibration = proposal_content.get("calibration")
    if not isinstance(calibration, Mapping):
        raise RfdetrPoseDerivedMaterializationError(f"calibration is missing: {revision_id}")
    if (
        calibration.get("calibration_digest") != entry["calibration_digest"]
        or calibration.get("calibration_revision_id") != entry["calibration_revision_id"]
        or calibration.get("recording_id") != entry["recording_id"]
    ):
        raise RfdetrPoseDerivedMaterializationError(f"calibration lineage changed: {revision_id}")
    if (
        proposal.get("calibration_digest") != entry["calibration_digest"]
        or proposal.get("calibration_revision_id") != entry["calibration_revision_id"]
        or proposal.get("source_frame_id") != entry["frame_id"]
        or proposal.get("source_frame_digest") != entry["source_frame_digest"]
    ):
        raise RfdetrPoseDerivedMaterializationError(
            f"proposal lineage changed: {entry['frame_id']}"
        )
    if (
        scene.calibration_digest != entry["calibration_digest"]
        or scene.calibration_revision_id != entry["calibration_revision_id"]
    ):
        raise RfdetrPoseDerivedMaterializationError(
            f"scene calibration changed: {entry['frame_id']}"
        )
    detector_revision_id = str(entry["visible_card_revision_id"])
    detector_content = detector_cache[detector_revision_id]
    detector_content_value = detector_content["content"]
    if _sha256_json_bytes(detector_content_value) != entry["visible_card_revision_digest"]:
        raise RfdetrPoseDerivedMaterializationError(
            f"visible-card revision changed: {detector_revision_id}"
        )
    if (
        proposal.get("detector_revision_id") != detector_revision_id
        or proposal.get("detector_revision_digest") != entry["visible_card_revision_digest"]
    ):
        raise RfdetrPoseDerivedMaterializationError(
            f"proposal detector lineage changed: {entry['frame_id']}"
        )
    outcome = _mapping_by_key(
        detector_content_value["outcomes"], "event_id", str(entry["frame_id"])
    )
    identity = outcome.get("frame_identity")
    if not isinstance(identity, Mapping):
        raise RfdetrPoseDerivedMaterializationError(
            f"frame identity is missing: {entry['frame_id']}"
        )
    if (
        identity.get("image_sha256") != entry["source_frame_digest"]
        or identity.get("source_video_sha256") != entry["source_group"]["source_sha256"]
        or identity.get("width") != scene.source_frame_width
        or identity.get("height") != scene.source_frame_height
    ):
        raise RfdetrPoseDerivedMaterializationError(f"source identity changed: {entry['frame_id']}")
    return {"scene": scene, "calibration": calibration, "frame_identity": dict(identity)}


def _load_revision_inputs(
    repository: Path, manifest: Mapping[str, Any]
) -> tuple[dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]], dict[str, Mapping[str, Any]]]:
    operations = repository / "data" / "operations" / "pipeline" / "revisions"
    proposal_cache: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    detector_cache: dict[str, Mapping[str, Any]] = {}
    for entry in manifest["eligible_scenes"]:
        proposal_id = str(entry["proposal_revision_id"])
        if proposal_id not in proposal_cache:
            directory = operations / proposal_id
            revision_manifest = _read_json(directory / "manifest.json", f"revision {proposal_id}")
            if (
                revision_manifest.get("revision_id") != proposal_id
                or revision_manifest.get("recording_id") != entry["recording_id"]
                or revision_manifest.get("content_sha256") != entry["proposal_content_sha256"]
            ):
                raise RfdetrPoseDerivedMaterializationError(
                    f"proposal revision lineage differs: {proposal_id}"
                )
            proposal_content = _read_json(directory / "content.json", f"content {proposal_id}")
            if _sha256_json_bytes(proposal_content) != revision_manifest["content_sha256"]:
                raise RfdetrPoseDerivedMaterializationError(
                    f"proposal content digest differs: {proposal_id}"
                )
            proposal_cache[proposal_id] = (
                proposal_content,
                {**revision_manifest, "_manifest_path": str(directory / "manifest.json")},
            )
        detector_id = str(entry["visible_card_revision_id"])
        if detector_id not in detector_cache:
            directory = operations / detector_id
            revision_manifest = _read_json(directory / "manifest.json", f"revision {detector_id}")
            detector_content = _read_json(directory / "content.json", f"content {detector_id}")
            if (
                revision_manifest.get("revision_id") != detector_id
                or revision_manifest.get("recording_id") != entry["recording_id"]
                or revision_manifest.get("content_sha256") != entry["visible_card_revision_digest"]
                or _sha256_json_bytes(detector_content) != revision_manifest["content_sha256"]
            ):
                raise RfdetrPoseDerivedMaterializationError(
                    f"visible-card revision lineage differs: {detector_id}"
                )
            detector_cache[detector_id] = {
                "content": detector_content,
                "manifest": revision_manifest,
                "_manifest_path": str(directory / "manifest.json"),
            }
    return proposal_cache, detector_cache


def _verified_source_videos(
    repository: Path, manifest: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for raw in manifest["verified_source_videos"]:
        if not isinstance(raw, Mapping):
            raise RfdetrPoseDerivedMaterializationError("M0 source video entry is invalid")
        recording_id = str(raw["recording_id"])
        path = repository / _relative_path(raw["relative_path"], "source video path")
        if not path.is_file() or path.stat().st_size != raw["byte_length"]:
            raise RfdetrPoseDerivedMaterializationError(
                f"source video is missing or has a different length: {recording_id}"
            )
        if _sha256_file(path) != raw["sha256"] or raw.get("bytes_verified") is not True:
            raise RfdetrPoseDerivedMaterializationError(
                f"source video digest differs from M0: {recording_id}"
            )
        result[recording_id] = raw
    return result


def _validate_m0_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != "rfdetr-pose-derived-campaign-manifest/v1":
        raise RfdetrPoseDerivedMaterializationError("M0 manifest schema is unsupported")
    digest = manifest.get("manifest_digest")
    core = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    if not isinstance(digest, str) or sha256_json(core) != digest:
        raise RfdetrPoseDerivedMaterializationError("M0 manifest digest does not match content")
    if manifest.get("campaign_id") != "0084-m0-rfdetr-pose-derived-visible-cards":
        raise RfdetrPoseDerivedMaterializationError("M0 campaign ID is invalid")
    policy = manifest.get("mask_policy")
    if not isinstance(policy, Mapping) or policy.get("encoding") != "COCO_RLE":
        raise RfdetrPoseDerivedMaterializationError("M0 mask policy must specify COCO_RLE")
    if not all(
        isinstance(manifest.get(key), list)
        for key in ("eligible_scenes", "excluded_scenes", "verified_source_videos")
    ):
        raise RfdetrPoseDerivedMaterializationError("M0 manifest scene or source lists are invalid")
    if not manifest["eligible_scenes"]:
        raise RfdetrPoseDerivedMaterializationError("M0 has no eligible scenes")
    groups = {
        row.get("source_group", {}).get("group_key")
        for row in manifest["eligible_scenes"]
        if isinstance(row, Mapping) and isinstance(row.get("source_group"), Mapping)
    }
    if any(
        not isinstance(row, Mapping)
        or not isinstance(row.get("source_group"), Mapping)
        or row["source_group"].get("partition") != "train"
        for row in manifest["eligible_scenes"]
    ):
        raise RfdetrPoseDerivedMaterializationError("M0 includes a non-training source group")
    if len(groups) < policy["mask_minimum_gate"]["minimum_source_groups"]:
        raise RfdetrPoseDerivedMaterializationError("M0 fails the minimum source-group gate")


def _derive_masks(
    scene: ReviewedCardScene, calibration: Mapping[str, Any]
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    table_to_image = np.asarray(calibration["table_to_image"], dtype=np.float64)
    short_size = float(calibration["card_short_size"])
    long_size = virtual_card_long_size(short_size)
    width = scene.source_frame_width
    height = scene.source_frame_height
    full_masks = []
    for pose in scene.poses:
        try:
            projected = project_rounded_card(
                table_to_image,
                pose.center,
                pose.rotation_degrees,
                short_size,
                long_size,
            )
            full_masks.append(rasterize_polygon(projected, width, height))
        except CardPlaneGeometryError as error:
            raise _InvalidPoseMaskError(pose.card_id, str(error)) from error
    pose_indices = {pose.card_id: index for index, pose in enumerate(scene.poses)}
    order = [pose_indices[card_id] for card_id in scene.stacking_order.card_ids]
    return full_masks, derive_visible_masks(full_masks, order)


def _coco_rle_annotation(
    *,
    annotation_id: int,
    image_id: int,
    entry: Mapping[str, Any],
    pose_id: str,
    pose_index: int,
    mask: np.ndarray,
    box: Sequence[int],
    scene: ReviewedCardScene,
) -> dict[str, Any]:
    binary = np.asarray(mask > 0, dtype=np.uint8)
    height, width = binary.shape
    counts: list[int] = []
    previous = 0
    run_length = 0
    for value in binary.ravel(order="F"):
        bit = int(value)
        if bit == previous:
            run_length += 1
        else:
            counts.append(run_length)
            previous = bit
            run_length = 1
    counts.append(run_length)
    group = entry["source_group"]
    mask_bytes = np.ascontiguousarray(binary).tobytes()
    return {
        "id": annotation_id,
        "image_id": image_id,
        "category_id": POSE_DERIVED_CATEGORY["id"],
        "bbox": [int(value) for value in box],
        "area": int(binary.sum()),
        "segmentation": {"size": [height, width], "counts": counts},
        "iscrowd": 0,
        "mask_sha256": hashlib.sha256(mask_bytes).hexdigest(),
        "m0_manifest_digest": entry["m0_manifest_digest"],
        "recording_id": entry["recording_id"],
        "frame_id": entry["frame_id"],
        "card_pose_id": pose_id,
        "card_pose_index": pose_index,
        "scene_digest": scene.scene_digest,
        "run_id": entry["run_id"],
        "proposal_revision_id": entry["proposal_revision_id"],
        "proposal_revision_sha256": entry["proposal_revision_sha256"],
        "proposal_content_sha256": entry["proposal_content_sha256"],
        "calibration_revision_id": entry["calibration_revision_id"],
        "calibration_digest": entry["calibration_digest"],
        "source_frame_sha256": entry["source_frame_digest"],
        "source_video_sha256": group["source_sha256"],
        "source_group_key": group["group_key"],
        "source_group": dict(group),
        "split": "train",
        "target_state": "pose_derived_visible_card",
    }


def _validate_coco_rle(coco: Mapping[str, Any]) -> None:
    if not isinstance(coco, Mapping) or set(coco) != {
        "info",
        "licenses",
        "images",
        "annotations",
        "categories",
    }:
        raise RfdetrPoseDerivedMaterializationError("COCO RLE document has invalid fields")
    if coco["categories"] != [POSE_DERIVED_CATEGORY]:
        raise RfdetrPoseDerivedMaterializationError("COCO category must be visible_card")
    if not isinstance(coco["images"], list) or not isinstance(coco["annotations"], list):
        raise RfdetrPoseDerivedMaterializationError("COCO images and annotations must be lists")
    images: dict[int, Mapping[str, Any]] = {}
    for item in coco["images"]:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), int):
            raise RfdetrPoseDerivedMaterializationError("COCO image record is invalid")
        if item["id"] in images:
            raise RfdetrPoseDerivedMaterializationError("COCO image IDs are not unique")
        images[item["id"]] = item
    annotation_ids: set[int] = set()
    for item in coco["annotations"]:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), int):
            raise RfdetrPoseDerivedMaterializationError("COCO annotation record is invalid")
        if item["id"] in annotation_ids:
            raise RfdetrPoseDerivedMaterializationError("COCO annotation IDs are not unique")
        annotation_ids.add(item["id"])
        image = images.get(item.get("image_id"))
        if image is None or item.get("category_id") != 1 or item.get("iscrowd") != 0:
            raise RfdetrPoseDerivedMaterializationError("COCO annotation lineage is invalid")
        rle = item.get("segmentation")
        if not isinstance(rle, Mapping) or set(rle) != {"size", "counts"}:
            raise RfdetrPoseDerivedMaterializationError("COCO segmentation is not uncompressed RLE")
        height, width = rle["size"]
        if height != image.get("height") or width != image.get("width"):
            raise RfdetrPoseDerivedMaterializationError("COCO RLE dimensions differ from its image")
        counts = rle["counts"]
        if not isinstance(counts, list) or not counts or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts
        ):
            raise RfdetrPoseDerivedMaterializationError("COCO RLE counts are invalid")
        flat = np.zeros(height * width, dtype=np.uint8)
        offset = 0
        bit = 0
        for count in counts:
            end = offset + count
            if end > len(flat):
                raise RfdetrPoseDerivedMaterializationError("COCO RLE exceeds image dimensions")
            if bit:
                flat[offset:end] = 1
            offset = end
            bit = 1 - bit
        if offset != len(flat):
            raise RfdetrPoseDerivedMaterializationError("COCO RLE does not cover the full image")
        mask = flat.reshape((height, width), order="F")
        if int(mask.sum()) != item.get("area"):
            raise RfdetrPoseDerivedMaterializationError("COCO annotation area differs from RLE")
        ys, xs = np.where(mask > 0)
        if not len(xs):
            raise RfdetrPoseDerivedMaterializationError("COCO annotation RLE is empty")
        expected_box = [
            int(xs.min()),
            int(ys.min()),
            int(xs.max() - xs.min() + 1),
            int(ys.max() - ys.min() + 1),
        ]
        if item.get("bbox") != expected_box:
            raise RfdetrPoseDerivedMaterializationError("COCO box is not tight around decoded RLE")
        if hashlib.sha256(np.ascontiguousarray(mask).tobytes()).hexdigest() != item.get(
            "mask_sha256"
        ):
            raise RfdetrPoseDerivedMaterializationError("decoded COCO RLE mask digest differs")
        for field in (
            "m0_manifest_digest",
            "recording_id",
            "frame_id",
            "card_pose_id",
            "scene_digest",
            "proposal_revision_id",
            "calibration_digest",
            "source_frame_sha256",
            "source_video_sha256",
            "source_group_key",
        ):
            if not isinstance(item.get(field), str) or not item[field]:
                raise RfdetrPoseDerivedMaterializationError(
                    f"COCO annotation is missing {field} lineage"
                )
        if item.get("split") != "train" or item.get("source_group", {}).get("partition") != "train":
            raise RfdetrPoseDerivedMaterializationError("non-training group appears in COCO labels")


def _frame_extractor() -> FrameExtractor:
    resolver = FFmpegFrameResolver()

    def extract(video_path: Path, frame: Mapping[str, Any]) -> bytes:
        request_time = _positive_or_zero_int(frame.get("requested_time_us"), "requested_time_us")
        presentation = _positive_or_zero_int(
            frame.get("presentation_timestamp_us"), "presentation_timestamp_us"
        )
        digest = str(frame.get("source_video_sha256", ""))
        source = RecordingVideoSource(
            recording_id="rfdetr-pose-derived-source",
            relative_path=video_path.name,
            video_sha256=digest,
            byte_length=video_path.stat().st_size,
            duration_us=max(request_time, presentation) + 1,
        )
        resolved = resolver.resolve(
            ExactEventRequest(source=source, requested_time_us=request_time), video_path
        )
        identity = resolved.identity_mapping()
        for key in (
            "source_video_sha256",
            "requested_time_us",
            "frame_index",
            "presentation_timestamp_us",
            "width",
            "height",
            "image_sha256",
        ):
            expected = frame.get("image_sha256") if key == "image_sha256" else frame.get(key)
            if identity.get(key) != expected:
                raise RfdetrPoseDerivedMaterializationError(
                    f"extracted frame identity differs in {key}"
                )
        return resolved.image_bytes

    return extract


def _result_from_manifest(
    view_root: Path, materialization: Mapping[str, Any]
) -> RfdetrPoseDerivedMaterializationResult:
    counts = materialization["counts"]
    exclusions = _read_json(view_root / "exclusions.json", "exclusion receipts")
    exclusion_counts = exclusions["counts"]
    return RfdetrPoseDerivedMaterializationResult(
        view_root=view_root,
        m0_manifest_digest=materialization["m0_manifest"]["manifest_digest"],
        materialization_digest=materialization["materialization_digest"],
        image_count=counts["images"],
        annotation_count=counts["annotations"],
        excluded_scene_count=exclusion_counts["m1_excluded_scenes"],
        hidden_card_count=counts["hidden_cards"],
        excluded_card_count=counts["excluded_cards"],
    )


def _card_receipt(
    entry: Mapping[str, Any], card_id: str, reason: str, **details: Any
) -> dict[str, Any]:
    return {
        "kind": "card_exclusion",
        "recording_id": entry["recording_id"],
        "frame_id": entry["frame_id"],
        "card_pose_id": card_id,
        "proposal_revision_id": entry["proposal_revision_id"],
        "calibration_digest": entry["calibration_digest"],
        "reason": reason,
        **details,
    }


def _mapping_by_key(rows: Sequence[Any], key: str, value: str) -> Mapping[str, Any]:
    matches = [row for row in rows if isinstance(row, Mapping) and row.get(key) == value]
    if len(matches) != 1:
        raise RfdetrPoseDerivedMaterializationError(f"expected one revision row for {value}")
    return matches[0]


def _resolve_path(value: str | Path, repository: Path, field: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repository / path
    resolved = path.resolve()
    try:
        resolved.relative_to(repository)
    except ValueError as error:
        raise RfdetrPoseDerivedMaterializationError(f"{field} path escapes repository") from error
    return resolved


def _relative_path(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise RfdetrPoseDerivedMaterializationError(f"{field} must be a non-empty path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise RfdetrPoseDerivedMaterializationError(f"{field} must stay inside repository")
    return path


def _relative_path_in_repo(path: Path, repository: Path) -> str:
    return path.relative_to(repository).as_posix()


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RfdetrPoseDerivedMaterializationError(f"could not read {field}: {error}") from error
    if not isinstance(value, dict):
        raise RfdetrPoseDerivedMaterializationError(f"{field} must be a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _sha256_json_bytes(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError as error:
        raise RfdetrPoseDerivedMaterializationError(f"could not hash {path}: {error}") from error


def _positive_or_zero_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RfdetrPoseDerivedMaterializationError(f"{field} must be a non-negative integer")
    return value


def _checked_frame_digest(image_bytes: bytes, entry: Mapping[str, Any]) -> str:
    digest = _sha256_bytes(image_bytes)
    if digest != entry.get("source_frame_digest"):
        raise RfdetrPoseDerivedMaterializationError(
            f"source frame digest differs for {entry.get('frame_id', 'unknown frame')}"
        )
    return digest


__all__ = [
    "DEFAULT_POSE_DERIVED_OUTPUT",
    "POSE_DERIVED_MATERIALIZATION_SCHEMA_VERSION",
    "RfdetrPoseDerivedMaterializationError",
    "RfdetrPoseDerivedMaterializationResult",
    "load_rfdetr_pose_derived_materialization",
    "materialize_rfdetr_pose_derived_dataset",
]
