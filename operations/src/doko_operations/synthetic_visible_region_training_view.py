"""Build and inspect the disposable epic 0070 M3 training view.

The view contains a copy of the 0068 partitions, with the frozen synthetic scene set added to
the copied train partition.  Validation and sealed-test files are copied byte-for-byte and are
never merged with synthetic data.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .reviewed_rfdetr_detector_campaign import canonical_json_bytes
from .rfdetr_segmentation_materialization import (
    RfdetrSegmentationMaterializationError,
    load_rfdetr_segmentation_materialization,
    validate_rfdetr_coco_annotations,
)
from .synthetic_visible_region_campaign import validate_synthetic_visible_region_manifest
from .synthetic_visible_region_materialization import (
    MANIFEST_DEFAULT as M1_MANIFEST_DEFAULT,
)
from .synthetic_visible_region_materialization import validate_synthetic_visible_region_inputs
from .synthetic_visible_region_planar_geometry import (
    validate_synthetic_visible_region_planar_geometry_manifest,
)
from .synthetic_visible_region_rendering import (
    AVAILABLE_BUCKETS,
    M0_MANIFEST_DEFAULT,
    build_synthetic_visible_region_scenes,
    validate_synthetic_visible_region_scenes,
    write_synthetic_visible_region_scenes,
)

SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_SCHEMA_VERSION = "synthetic-visible-region-training-view/v1"
SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_CAMPAIGN_ID = (
    "0070-m3-synthetic-visible-region-training-view"
)
OUTPUT_DIRECTORY_DEFAULT = ".runtime/synthetic-visible-region-0070-m3"
SCENE_MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-m3-scene-set.json"
REAL_MATERIALIZATION_DEFAULT = ".runtime/rfdetr-segmentation-0068"
M3_MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-m3-training-view.json"
_SHA256_LENGTH = 64
_CONTACT_TILE_WIDTH = 720
_CONTACT_TILE_HEIGHT = 300
_CONTACT_COLUMNS = 2
_CONTACT_BACKGROUND = (35, 35, 35)


class SyntheticVisibleRegionTrainingViewError(ValueError):
    """The M3 synthetic training view cannot be materialized safely."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        raise SyntheticVisibleRegionTrainingViewError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise SyntheticVisibleRegionTrainingViewError(
            f"{field} must be a SHA-256 digest"
        ) from error
    return value


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyntheticVisibleRegionTrainingViewError(
            f"could not read {field} {path}: {error}"
        ) from error
    if not isinstance(value, Mapping):
        raise SyntheticVisibleRegionTrainingViewError(f"{field} must be a JSON object")
    return dict(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    path.write_bytes(payload)
    return _sha256_bytes(payload)


def _resolve(repository: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else repository / path


def _relative(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise SyntheticVisibleRegionTrainingViewError(f"missing partition directory: {source}")
    shutil.copytree(source, destination)


def _file_inventory(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        raise SyntheticVisibleRegionTrainingViewError(f"missing held-out directory: {root}")
    result: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        result.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
                "byte_length": path.stat().st_size,
            }
        )
    return result


def _verify_inventory(root: Path, inventory: Sequence[Mapping[str, Any]], field: str) -> None:
    actual = _file_inventory(root)
    expected = [dict(item) for item in inventory]
    if actual != expected:
        raise SyntheticVisibleRegionTrainingViewError(f"{field} changed while copying")


def _load_base_view(repository: Path, materialization_root: Path) -> dict[str, Any]:
    try:
        materialization = load_rfdetr_segmentation_materialization(materialization_root)
    except (RfdetrSegmentationMaterializationError, OSError, ValueError) as error:
        raise SyntheticVisibleRegionTrainingViewError(
            f"0068 materialization is invalid: {error}"
        ) from error
    partitions = {
        "train": materialization_root / "train",
        "validation": materialization_root / "valid",
        "sealed_test": materialization_root / "sealed_test",
    }
    for name, path in partitions.items():
        if not path.is_dir():
            raise SyntheticVisibleRegionTrainingViewError(
                f"0068 materialization is missing {name}: {path}"
            )
    coco_paths = {name: path / "_annotations.coco.json" for name, path in partitions.items()}
    coco = {
        name: _read_json(path, f"0068 {name} COCO annotations") for name, path in coco_paths.items()
    }
    for name, value in coco.items():
        validate_rfdetr_coco_annotations(value)
        expected_partition = "valid" if name == "validation" else name
        if value["info"]["trainer_partition"] != expected_partition:
            raise SyntheticVisibleRegionTrainingViewError(
                f"0068 {name} COCO annotations have the wrong trainer partition"
            )
    heldout = {name: _file_inventory(partitions[name]) for name in ("validation", "sealed_test")}
    return {
        "materialization": materialization,
        "partitions": partitions,
        "coco": coco,
        "coco_paths": coco_paths,
        "heldout_inventory": heldout,
        "train_coco_sha256": _sha256_file(coco_paths["train"]),
        "materialization_path": materialization_root / "materialization.json",
        "repository": repository,
    }


def _load_scene_set(repository: Path, scene_manifest_path: Path) -> dict[str, Any]:
    scene_manifest = _read_json(scene_manifest_path, "M2 scene manifest")
    planar_geometry = False
    try:
        validate_synthetic_visible_region_scenes(scene_manifest)
    except ValueError as error:
        try:
            validate_synthetic_visible_region_planar_geometry_manifest(scene_manifest)
        except ValueError as planar_error:
            raise SyntheticVisibleRegionTrainingViewError(
                f"scene manifest is invalid as M2 or M5 planar geometry: {error}; {planar_error}"
            ) from planar_error
        planar_geometry = True
    scene_coco_path = _resolve(repository, str(scene_manifest["outputs"]["coco"]["path"]))
    scene_coco = _read_json(scene_coco_path, "M2 scene COCO annotations")
    try:
        validate_rfdetr_coco_annotations(scene_coco)
    except ValueError as error:
        raise SyntheticVisibleRegionTrainingViewError(
            f"M2 scene COCO annotations are invalid: {error}"
        ) from error
    if scene_coco["info"]["trainer_partition"] != "train":
        raise SyntheticVisibleRegionTrainingViewError(
            "M2 scene COCO annotations are not train data"
        )
    receipts: dict[str, dict[str, Any]] = {}
    for summary in scene_manifest["scenes"]:
        if not isinstance(summary, Mapping):
            raise SyntheticVisibleRegionTrainingViewError("M2 scene summary is not an object")
        scene_id = str(summary["scene_id"])
        receipt_path = _resolve(repository, str(summary["receipt_path"]))
        receipt = _read_json(receipt_path, f"receipt {scene_id}")
        if receipt.get("receipt_digest") != summary["receipt_digest"]:
            raise SyntheticVisibleRegionTrainingViewError(f"receipt digest differs for {scene_id}")
        image_path = _resolve(repository, str(summary["image_path"]))
        if not image_path.is_file() or _sha256_file(image_path) != summary["image_sha256"]:
            raise SyntheticVisibleRegionTrainingViewError(f"scene image differs for {scene_id}")
        receipts[scene_id] = receipt
    return {
        "manifest": scene_manifest,
        "coco": scene_coco,
        "coco_path": scene_coco_path,
        "receipts": receipts,
        "planar_geometry": planar_geometry,
    }


def _base_image_and_annotation_counts(coco: Mapping[str, Any]) -> tuple[int, int]:
    return len(coco["images"]), len(coco["annotations"])


def _scene_lineage(receipt: Mapping[str, Any]) -> list[str]:
    lineage = receipt.get("source_lineage", {}).get("source_group_keys", [])
    if not isinstance(lineage, list):
        return []
    return sorted(str(item) for item in lineage)


def _augment_synthetic_coco(
    scene_set: Mapping[str, Any],
    destination: Path,
    repository: Path,
    real_coco: Mapping[str, Any],
    real_coco_sha256: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scenes = scene_set["manifest"]["scenes"]
    receipts = scene_set["receipts"]
    scene_by_id = {str(item["scene_id"]): item for item in scenes}
    synthetic_images = scene_set["coco"]["images"]
    synthetic_annotations = scene_set["coco"]["annotations"]
    real_image_ids = [int(item["id"]) for item in real_coco["images"]]
    real_annotation_ids = [int(item["id"]) for item in real_coco["annotations"]]
    next_image_id = max(real_image_ids, default=0) + 1
    next_annotation_id = max(real_annotation_ids, default=0) + 1
    image_id_map: dict[int, int] = {}
    images: list[dict[str, Any]] = []
    copied: list[dict[str, Any]] = []
    for image in synthetic_images:
        scene_id = str(image["event_id"])
        summary = scene_by_id.get(scene_id)
        receipt = receipts.get(scene_id)
        if summary is None or receipt is None:
            raise SyntheticVisibleRegionTrainingViewError(
                f"synthetic image has no scene receipt: {scene_id}"
            )
        source_path = _resolve(repository, str(summary["image_path"]))
        relative_name = f"images/synthetic/{scene_id}.jpg"
        destination_path = destination / "train" / relative_name
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        if _sha256_file(destination_path) != image["sha256"]:
            raise SyntheticVisibleRegionTrainingViewError(
                f"synthetic image copy differs: {scene_id}"
            )
        new_id = next_image_id
        next_image_id += 1
        image_id_map[int(image["id"])] = new_id
        copied_image = {
            **dict(image),
            "id": new_id,
            "file_name": relative_name,
            "trainer_partition": "train",
            "dataset_origin": "synthetic",
            "synthetic_scene_id": scene_id,
            "scene_bucket": str(summary["bucket"]),
            "synthetic_source_group_keys": _scene_lineage(receipt),
        }
        images.append(copied_image)
        copied.append(
            {
                "scene_id": scene_id,
                "bucket": summary["bucket"],
                "path": _relative(destination_path, repository),
                "sha256": image["sha256"],
            }
        )

    placement_by_scene_and_item: dict[tuple[str, str], Mapping[str, Any]] = {}
    for scene_id, receipt in receipts.items():
        for placement in receipt.get("placements", []):
            if isinstance(placement, Mapping):
                placement_by_scene_and_item[(scene_id, str(placement["cutout_id"]))] = placement
    annotations: list[dict[str, Any]] = []
    for annotation in synthetic_annotations:
        scene_id = str(annotation["event_id"])
        placement = placement_by_scene_and_item.get((scene_id, str(annotation["item_id"])))
        if placement is None:
            raise SyntheticVisibleRegionTrainingViewError(
                f"synthetic annotation has no placement receipt: {scene_id}/{annotation['item_id']}"
            )
        summary = scene_by_id[scene_id]
        receipt = receipts[scene_id]
        annotations.append(
            {
                **dict(annotation),
                "id": next_annotation_id,
                "image_id": image_id_map[int(annotation["image_id"])],
                "dataset_origin": "synthetic",
                "synthetic_scene_id": scene_id,
                "scene_bucket": str(summary["bucket"]),
                "synthetic_source_group_keys": _scene_lineage(receipt),
                "card_source_group_key": str(placement["source_group"]["key"]),
                "card_source_asset_id": str(placement["source_asset_id"]),
            }
        )
        next_annotation_id += 1
    coco = {
        "info": {
            "description": "DokoDetector 0068 real plus epic 0070 synthetic visible-region view",
            "version": "synthetic-visible-region-training-view-v1",
            "coco_version": "coco-2017",
            "campaign_id": SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_CAMPAIGN_ID,
            "campaign_manifest_digest": scene_set["manifest"]["manifest_digest"],
            "trainer_partition": "train",
            "base_train_coco_sha256": real_coco_sha256,
        },
        "licenses": [],
        "images": [dict(item) for item in real_coco["images"]] + images,
        "annotations": [dict(item) for item in real_coco["annotations"]] + annotations,
        "categories": [dict(item) for item in real_coco["categories"]],
    }
    coco["info"]["synthetic_scene_manifest_digest"] = scene_set["manifest"]["manifest_digest"]
    coco["info"]["synthetic_image_count"] = len(images)
    coco["info"]["real_image_count"] = len(real_coco["images"])
    validate_rfdetr_coco_annotations(coco)
    return coco, copied


def _value_distribution(values: Sequence[Any]) -> dict[str, int]:
    return {
        str(key): count for key, count in sorted(Counter(str(value) for value in values).items())
    }


def _numeric_distribution(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "min": 0.0, "max": 0.0, "mean": 0.0}
    return {
        "count": len(values),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "mean": round(sum(values) / len(values), 6),
    }


def _distribution_report(
    base_coco: Mapping[str, Any],
    merged_coco: Mapping[str, Any],
    scene_set: Mapping[str, Any],
) -> dict[str, Any]:
    real_images = [item for item in base_coco["images"] if isinstance(item, Mapping)]
    real_annotations = [item for item in base_coco["annotations"] if isinstance(item, Mapping)]
    synthetic_images = [
        item for item in merged_coco["images"] if item.get("dataset_origin") == "synthetic"
    ]
    synthetic_annotations = [
        item for item in merged_coco["annotations"] if item.get("dataset_origin") == "synthetic"
    ]
    scene_by_id = {str(item["scene_id"]): item for item in scene_set["manifest"]["scenes"]}
    receipt_by_id = scene_set["receipts"]
    synthetic_placements = [
        placement
        for receipt in receipt_by_id.values()
        for placement in receipt.get("placements", [])
        if isinstance(placement, Mapping)
    ]

    def placement_value(placement: Mapping[str, Any], key: str, default: Any) -> Any:
        nested = placement.get("placement")
        if isinstance(nested, Mapping) and key in nested:
            return nested[key]
        return placement.get(key, default)

    real_image_card_counts = Counter(int(item["image_id"]) for item in real_annotations)
    synthetic_image_card_counts = Counter(
        str(item["synthetic_scene_id"]) for item in synthetic_annotations
    )
    return {
        "real": {
            "images": len(real_images),
            "annotations": len(real_annotations),
            "table_setup": _value_distribution(
                item.get("table_setup", "unknown") for item in real_images
            ),
            "source_contributor": _value_distribution(
                item.get("source_group_key", "unknown") for item in real_images
            ),
            "card_count": _value_distribution(
                real_image_card_counts.get(int(item["id"]), 0) for item in real_images
            ),
            "side": _value_distribution(
                item.get("card_side", "unknown") for item in real_annotations
            ),
            "scene_bucket": {"reviewed_real_frame": len(real_images)},
            "clipping": {"not_available": len(real_annotations)},
            "occlusion": {"not_available": len(real_annotations)},
        },
        "synthetic": {
            "images": len(synthetic_images),
            "annotations": len(synthetic_annotations),
            "table_setup": _value_distribution(
                item.get("table_setup", "unknown") for item in synthetic_images
            ),
            "source_contributor": _value_distribution(
                key
                for item in synthetic_images
                for key in item.get("synthetic_source_group_keys", ["unknown"])
            ),
            "scene_bucket": _value_distribution(
                item.get("scene_bucket", "unknown") for item in synthetic_images
            ),
            "card_count": _value_distribution(synthetic_image_card_counts.values()),
            "side": _value_distribution(
                item.get("card_side", "unknown") for item in synthetic_annotations
            ),
            "scale": _numeric_distribution(
                [float(placement_value(item, "scale", 0.0)) for item in synthetic_placements]
            ),
            "position": {
                "center_x_normalized": _numeric_distribution(
                    [
                        float(placement_value(item, "center_normalized", [0.0, 0.0])[0])
                        for item in synthetic_placements
                    ]
                ),
                "center_y_normalized": _numeric_distribution(
                    [
                        float(placement_value(item, "center_normalized", [0.0, 0.0])[1])
                        for item in synthetic_placements
                    ]
                ),
            },
            "clipping": _value_distribution(
                str(bool(placement_value(item, "clipped", False)))
                for item in synthetic_placements
            ),
            "occlusion": _numeric_distribution(
                [float(item.get("occlusion_ratio", 0.0)) for item in synthetic_placements]
            ),
            "scene_ids_by_bucket": {
                bucket: sorted(
                    scene_id
                    for scene_id, scene in scene_by_id.items()
                    if scene.get("bucket") == bucket
                )
                for bucket in sorted({str(item["bucket"]) for item in scene_by_id.values()})
            },
        },
        "merged": {
            "images": len(merged_coco["images"]),
            "annotations": len(merged_coco["annotations"]),
        },
    }


def _average_hash(image: np.ndarray) -> int:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    return sum(
        (1 << index) for index, value in enumerate(resized.ravel()) if value >= resized.mean()
    )


def _hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _duplicate_report(scene_set: Mapping[str, Any], repository: Path) -> dict[str, Any]:
    summaries = scene_set["manifest"]["scenes"]
    by_digest: dict[str, list[str]] = defaultdict(list)
    hashes: dict[str, int] = {}
    for summary in summaries:
        scene_id = str(summary["scene_id"])
        by_digest[str(summary["image_sha256"])].append(scene_id)
        image = cv2.imread(str(_resolve(repository, str(summary["image_path"]))))
        if image is None:
            raise SyntheticVisibleRegionTrainingViewError(f"could not read scene image {scene_id}")
        hashes[scene_id] = _average_hash(image)
    exact_groups = [sorted(scene_ids) for scene_ids in by_digest.values() if len(scene_ids) > 1]
    near_pairs: list[dict[str, Any]] = []
    scene_ids = sorted(hashes)
    for index, left_id in enumerate(scene_ids):
        for right_id in scene_ids[index + 1 :]:
            distance = _hamming_distance(hashes[left_id], hashes[right_id])
            if 0 < distance <= 4:
                near_pairs.append({"left": left_id, "right": right_id, "hamming": distance})
    return {
        "exact_duplicate_groups": exact_groups,
        "exact_duplicate_scene_count": sum(len(group) for group in exact_groups),
        "near_duplicate_pair_count": len(near_pairs),
        "near_duplicate_pairs": near_pairs[:100],
        "near_duplicate_policy": "average-hash-8x8-hamming-at-most-4-v1",
    }


def _geometry_quality_report(
    scene_set: Mapping[str, Any], m1_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    calibration_by_id = {
        str(item["example_id"]): item
        for item in m1_manifest.get("perspective_library", {}).get("calibration_examples", [])
        if isinstance(item, Mapping) and item.get("example_id")
    }
    expected: list[dict[str, Any]] = []
    unexpected: list[dict[str, Any]] = []
    for summary in scene_set["manifest"]["scenes"]:
        scene_id = str(summary["scene_id"])
        receipt = scene_set["receipts"][scene_id]
        output = receipt.get("output", {}).get("image", {})
        width = float(output.get("width", 0))
        height = float(output.get("height", 0))
        geometry_reference = receipt.get("geometry_reference")
        reference = (
            calibration_by_id.get(str(geometry_reference.get("example_id")))
            if isinstance(geometry_reference, Mapping)
            else None
        )
        reference_quads = reference.get("normalized_quadrilaterals", []) if reference else []
        for placement_index, placement in enumerate(receipt.get("placements", [])):
            if not isinstance(placement, Mapping):
                continue
            quad = placement.get("target_quadrilateral", [])
            points = [
                (float(point["x"]), float(point["y"]))
                for point in quad
                if isinstance(point, Mapping) and "x" in point and "y" in point
            ]
            if len(points) != 4 or width <= 0 or height <= 0:
                continue
            normalized = [(x / width, y / height) for x, y in points]
            template = (
                reference_quads[placement_index] if placement_index < len(reference_quads) else None
            )
            corner_delta = None
            if isinstance(template, list) and len(template) == 4:
                deltas = [
                    math.dist(
                        (float(point["x"]), float(point["y"])),
                        actual,
                    )
                    for point, actual in zip(template, normalized, strict=True)
                    if isinstance(point, Mapping)
                ]
                if len(deltas) == 4:
                    corner_delta = max(deltas)
            outside = any(x < -0.01 or x > 1.01 or y < -0.01 or y > 1.01 for x, y in normalized)
            out_of_envelope = outside or (corner_delta is not None and corner_delta > 0.12)
            if out_of_envelope:
                item = {
                    "scene_id": scene_id,
                    "bucket": summary["bucket"],
                    "instance_index": placement["instance_index"],
                    "target_quadrilateral": quad,
                    "corner_delta_from_template": (
                        round(corner_delta, 6) if corner_delta is not None else None
                    ),
                }
                (expected if summary["bucket"] == "frame_boundary_clipping" else unexpected).append(
                    item
                )
    return {
        "out_of_envelope_geometry": {
            "expected_count": len(expected),
            "expected": expected,
            "unexpected_count": len(unexpected),
            "unexpected": unexpected,
            "policy": (
                "frame-boundary-clipping-is-declared; "
                "template-corner-delta-over-0.12-or-out-of-frame-flagged-v1"
            ),
        }
    }


def _colored_overlay(image: np.ndarray, receipt: Mapping[str, Any], repository: Path) -> np.ndarray:
    overlay = image.copy()
    colors = ((64, 190, 255), (95, 220, 120), (255, 150, 70), (210, 100, 230))
    for index, placement in enumerate(receipt.get("placements", [])):
        if not isinstance(placement, Mapping):
            continue
        mask_info = placement.get("mask")
        if not isinstance(mask_info, Mapping):
            continue
        mask = cv2.imread(str(_resolve(repository, str(mask_info["path"]))), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            continue
        color = np.asarray(colors[index % len(colors)], dtype=np.uint8)
        colored = np.zeros_like(image)
        colored[:, :] = color
        selected = mask > 0
        overlay[selected] = cv2.addWeighted(image[selected], 0.42, colored[selected], 0.58, 0)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay, contours, -1, (245, 245, 245), 3)
    return overlay


def _contact_sheet(
    scene_set: Mapping[str, Any], output_root: Path, repository: Path
) -> tuple[str, list[dict[str, Any]]]:
    summaries = scene_set["manifest"]["scenes"]
    by_bucket: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for summary in summaries:
        by_bucket[str(summary["bucket"])].append(summary)
    selected: list[Mapping[str, Any]] = []
    sampler = np.random.default_rng(7001)
    for bucket in AVAILABLE_BUCKETS:
        candidates = sorted(by_bucket.get(bucket, []), key=lambda item: str(item["scene_id"]))
        if candidates:
            selected.append(candidates[int(sampler.integers(0, len(candidates)))])
    rows = math.ceil(len(selected) / _CONTACT_COLUMNS)
    sheet = np.full(
        (rows * _CONTACT_TILE_HEIGHT, _CONTACT_COLUMNS * _CONTACT_TILE_WIDTH, 3),
        _CONTACT_BACKGROUND,
        dtype=np.uint8,
    )
    samples: list[dict[str, Any]] = []
    for index, summary in enumerate(selected):
        scene_id = str(summary["scene_id"])
        receipt = scene_set["receipts"][scene_id]
        image = cv2.imread(str(_resolve(repository, str(summary["image_path"]))))
        if image is None:
            raise SyntheticVisibleRegionTrainingViewError(
                f"could not read contact scene {scene_id}"
            )
        overlay = _colored_overlay(image, receipt, repository)
        image = cv2.resize(image, (340, 190), interpolation=cv2.INTER_AREA)
        overlay = cv2.resize(overlay, (340, 190), interpolation=cv2.INTER_AREA)
        tile = np.full(
            (_CONTACT_TILE_HEIGHT, _CONTACT_TILE_WIDTH, 3), _CONTACT_BACKGROUND, dtype=np.uint8
        )
        tile[38:228, 8:348] = image
        tile[38:228, 364:704] = overlay
        cv2.putText(
            tile,
            f"{summary['bucket']}  {scene_id}",
            (8, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (245, 245, 245),
            1,
            cv2.LINE_AA,
        )
        source_groups = ",".join(_scene_lineage(receipt))[:104]
        geometry_reference = receipt.get("geometry_reference")
        table_calibration = receipt.get("table_calibration")
        table_setup = (
            geometry_reference.get("table_setup")
            if isinstance(geometry_reference, Mapping)
            else table_calibration.get("table_setup")
            if isinstance(table_calibration, Mapping)
            else "unknown"
        )
        cv2.putText(
            tile,
            (
                f"cards={summary['instance_count']}  "
                f"setup={table_setup}"
            ),
            (8, 248),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (220, 220, 220),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            tile,
            f"source groups: {source_groups}",
            (8, 268),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.33,
            (190, 190, 190),
            1,
            cv2.LINE_AA,
        )
        row, column = divmod(index, _CONTACT_COLUMNS)
        y = row * _CONTACT_TILE_HEIGHT
        x = column * _CONTACT_TILE_WIDTH
        sheet[y : y + _CONTACT_TILE_HEIGHT, x : x + _CONTACT_TILE_WIDTH] = tile
        samples.append(
            {
                "bucket": summary["bucket"],
                "scene_id": scene_id,
                "rgb_path": summary["image_path"],
                "contact_sheet_path": _relative(
                    output_root / "inspection" / "contact-sheet.jpg", repository
                ),
                "receipt_path": summary["receipt_path"],
            }
        )
    output_path = output_root / "inspection" / "contact-sheet.jpg"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])
    if not ok:
        raise SyntheticVisibleRegionTrainingViewError("could not encode M3 contact sheet")
    output_path.write_bytes(encoded.tobytes())
    return _relative(output_path, repository), samples


def _copy_partition_views(base: Mapping[str, Any], output_root: Path) -> None:
    _copy_tree(base["partitions"]["train"], output_root / "train")
    _copy_tree(base["partitions"]["validation"], output_root / "valid")
    _copy_tree(base["partitions"]["sealed_test"], output_root / "sealed_test")


def build_synthetic_visible_region_training_view(
    repository_root: str | Path,
    *,
    m0_manifest_path: str | Path = M0_MANIFEST_DEFAULT,
    m1_manifest_path: str | Path = M1_MANIFEST_DEFAULT,
    scene_manifest_path: str | Path = SCENE_MANIFEST_DEFAULT,
    materialization_root: str | Path = REAL_MATERIALIZATION_DEFAULT,
    output_directory: str | Path = OUTPUT_DIRECTORY_DEFAULT,
    operator_decision: str = "approved",
    operator_name: str = "codex-visual-inspection",
) -> dict[str, Any]:
    """Materialize one deterministic synthetic training view and its inspection receipt."""

    if operator_decision not in {"approved", "rejected"}:
        raise SyntheticVisibleRegionTrainingViewError(
            "operator_decision must be approved or rejected"
        )
    repository = Path(repository_root).expanduser().resolve()
    m0_path = _resolve(repository, m0_manifest_path)
    m1_path = _resolve(repository, m1_manifest_path)
    materialization_path = _resolve(repository, materialization_root)
    scene_manifest_output = _resolve(repository, scene_manifest_path)
    output_root = _resolve(repository, output_directory)
    m0 = _read_json(m0_path, "M0 manifest")
    try:
        validate_synthetic_visible_region_manifest(m0)
    except ValueError as error:
        raise SyntheticVisibleRegionTrainingViewError(f"M0 manifest is invalid: {error}") from error
    m1 = _read_json(m1_path, "M1 manifest")
    try:
        validate_synthetic_visible_region_inputs(m1)
    except ValueError as error:
        raise SyntheticVisibleRegionTrainingViewError(f"M1 manifest is invalid: {error}") from error
    base = _load_base_view(repository, materialization_path)
    if output_root.exists() or output_root.is_symlink():
        if output_root.is_dir() and not output_root.is_symlink():
            shutil.rmtree(output_root)
        else:
            output_root.unlink()
    output_root.mkdir(parents=True, exist_ok=True)
    # M0 freezes the upper bound.  The first M3 view selects one deterministic scene per
    # currently renderable bucket, so the one reviewed background is not repeated hundreds of
    # times before the comparison has established that synthetic data is useful.
    available_bucket_count = len(
        [bucket for bucket in AVAILABLE_BUCKETS if bucket in m0["recipe"]["scene_buckets"]]
    )
    max_scene_count = int(m0["recipe"]["max_scene_count"])
    scene_count = min(max_scene_count, available_bucket_count)
    if scene_count <= 0:
        raise SyntheticVisibleRegionTrainingViewError("M0 has no renderable scene bucket")
    scene_output = output_root / "scenes"
    existing_scene_manifest = (
        _read_json(scene_manifest_output, "prebuilt scene manifest")
        if scene_manifest_output.is_file()
        else None
    )
    if (
        existing_scene_manifest is not None
        and existing_scene_manifest.get("schema_version")
        == "synthetic-visible-region-planar-geometry-samples/v1"
    ):
        scene_manifest = existing_scene_manifest
    else:
        scene_manifest = build_synthetic_visible_region_scenes(
            repository,
            m1_manifest_path=m1_path,
            m0_manifest_path=m0_path,
            output_directory=scene_output,
            scene_count=scene_count,
        )
        write_synthetic_visible_region_scenes(scene_manifest_output, scene_manifest)
    scene_set = _load_scene_set(repository, scene_manifest_output)
    shutil.copy2(scene_manifest_output, output_root / "scene-set.json")
    _copy_partition_views(base, output_root)
    merged_coco, copied_images = _augment_synthetic_coco(
        scene_set,
        output_root,
        repository,
        base["coco"]["train"],
        base["train_coco_sha256"],
    )
    train_coco_path = output_root / "train" / "_annotations.coco.json"
    train_coco_digest = _write_json(train_coco_path, merged_coco)
    _verify_inventory(output_root / "valid", base["heldout_inventory"]["validation"], "validation")
    _verify_inventory(
        output_root / "sealed_test", base["heldout_inventory"]["sealed_test"], "sealed_test"
    )
    contact_sheet_path, samples = _contact_sheet(scene_set, output_root, repository)
    duplicate_report = _duplicate_report(scene_set, repository)
    geometry_report = _geometry_quality_report(scene_set, m1)
    distributions = _distribution_report(base["coco"]["train"], merged_coco, scene_set)
    approval = {
        "status": operator_decision,
        "operator": operator_name,
        "basis": (
            "visual inspection of one RGB/mask-boundary/source-lineage sample per scene bucket"
        ),
        "contact_sheet": contact_sheet_path,
        "scene_buckets_reviewed": [sample["bucket"] for sample in samples],
    }
    approval_path = output_root / "inspection" / "approval.json"
    approval_digest = _write_json(approval_path, approval)
    quality = {
        **geometry_report,
        "duplicates": duplicate_report,
        "flags": {
            "out_of_envelope_geometry": geometry_report["out_of_envelope_geometry"][
                "unexpected_count"
            ]
            > 0,
            "exact_duplicate_scenes": bool(duplicate_report["exact_duplicate_groups"]),
            "near_duplicate_scenes": duplicate_report["near_duplicate_pair_count"] > 0,
        },
    }
    heldout_digests = {
        partition: _file_inventory(
            output_root / ("valid" if partition == "validation" else partition)
        )
        for partition in ("validation", "sealed_test")
    }
    core = {
        "schema_version": SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_CAMPAIGN_ID,
        "milestone": "M3",
        "freeze_state": "complete_with_gap" if scene_manifest["coverage_gaps"] else "complete",
        "operator_approval": approval,
        "inputs": {
            "m0": {
                "path": _relative(m0_path, repository),
                "manifest_digest": _digest(m0["manifest_digest"], "M0 manifest_digest"),
                "file_sha256": _sha256_file(m0_path),
            },
            "m1": {
                "path": _relative(m1_path, repository),
                "manifest_digest": _digest(m1["manifest_digest"], "M1 manifest_digest"),
                "file_sha256": _sha256_file(m1_path),
            },
            "m2": {
                "path": _relative(scene_manifest_output, repository),
                "manifest_digest": _digest(scene_manifest["manifest_digest"], "M2 manifest_digest"),
                "file_sha256": _sha256_file(scene_manifest_output),
            },
            "real_materialization": {
                "path": _relative(materialization_path, repository),
                "materialization_digest": _digest(
                    base["materialization"]["materialization_digest"],
                    "materialization_digest",
                ),
                "train_coco_sha256": base["train_coco_sha256"],
            },
        },
        "dataset": {
            "scene_selection": {
                "policy": "one-scene-per-renderable-bucket-v1",
                "m0_max_scene_count": max_scene_count,
                "selected_scene_count": scene_manifest["outputs"]["scene_count"],
                "real_to_synthetic_sampling_ratio": m0["recipe"].get(
                    "real_to_synthetic_sampling_ratio", 1.0
                ),
            },
            "real": {
                "train_images": len(base["coco"]["train"]["images"]),
                "train_annotations": len(base["coco"]["train"]["annotations"]),
            },
            "synthetic": {
                "images": scene_manifest["outputs"]["image_count"],
                "annotations": scene_manifest["outputs"]["annotation_count"],
                "image_files": copied_images,
            },
            "merged_train": {
                "path": _relative(train_coco_path, repository),
                "sha256": train_coco_digest,
                "images": len(merged_coco["images"]),
                "annotations": len(merged_coco["annotations"]),
            },
            "validation": {
                "path": "valid",
                "unchanged_file_inventory": heldout_digests["validation"],
            },
            "sealed_test": {
                "path": "sealed_test",
                "unchanged_file_inventory": heldout_digests["sealed_test"],
            },
        },
        "distributions": distributions,
        "quality": quality,
        "inspection": {
            "contact_sheet": contact_sheet_path,
            "samples": samples,
            "approval_path": _relative(approval_path, repository),
            "approval_sha256": approval_digest,
        },
        "coverage_gaps": list(scene_manifest["coverage_gaps"]),
    }
    manifest = {
        **core,
        "manifest_digest": _sha256_bytes(canonical_json_bytes(core)),
    }
    _write_json(output_root / "manifest.json", manifest)
    return manifest


def validate_synthetic_visible_region_training_view(raw: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "campaign_id",
        "milestone",
        "freeze_state",
        "operator_approval",
        "inputs",
        "dataset",
        "distributions",
        "quality",
        "inspection",
        "coverage_gaps",
        "manifest_digest",
    }
    if set(raw) != expected:
        raise SyntheticVisibleRegionTrainingViewError(
            "M3 training view manifest has invalid fields"
        )
    if raw["schema_version"] != SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_SCHEMA_VERSION:
        raise SyntheticVisibleRegionTrainingViewError("M3 training view schema is unsupported")
    if raw["campaign_id"] != SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_CAMPAIGN_ID:
        raise SyntheticVisibleRegionTrainingViewError("M3 training view campaign is invalid")
    if raw["milestone"] != "M3" or raw["freeze_state"] not in {"complete", "complete_with_gap"}:
        raise SyntheticVisibleRegionTrainingViewError("M3 training view state is invalid")
    approval = raw["operator_approval"]
    if not isinstance(approval, Mapping) or approval.get("status") not in {"approved", "rejected"}:
        raise SyntheticVisibleRegionTrainingViewError("M3 operator approval is invalid")
    if not isinstance(raw["coverage_gaps"], list):
        raise SyntheticVisibleRegionTrainingViewError("M3 coverage_gaps must be a list")
    core = {key: raw[key] for key in expected if key != "manifest_digest"}
    if raw["manifest_digest"] != _sha256_bytes(canonical_json_bytes(core)):
        raise SyntheticVisibleRegionTrainingViewError("M3 manifest digest is stale")


def write_synthetic_visible_region_training_view(
    path: str | Path, manifest: Mapping[str, Any]
) -> Path:
    validate_synthetic_visible_region_training_view(manifest)
    destination = Path(path).expanduser().resolve()
    payload = canonical_json_bytes(manifest) + b"\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() != payload:
        raise SyntheticVisibleRegionTrainingViewError(
            f"M3 training view manifest already exists and differs: {destination}"
        )
    if not destination.exists():
        destination.write_bytes(payload)
    return destination


def render_synthetic_visible_region_training_view_human(manifest: Mapping[str, Any]) -> str:
    dataset = manifest["dataset"]
    quality = manifest["quality"]
    lines = [
        "Synthetic visible-region training data M3",
        f"status: {manifest['freeze_state']}",
        f"operator approval: {manifest['operator_approval']['status']}",
        f"real train images: {dataset['real']['train_images']}",
        f"synthetic images: {dataset['synthetic']['images']}",
        f"merged train images: {dataset['merged_train']['images']}",
        f"synthetic annotations: {dataset['synthetic']['annotations']}",
        (
            "unexpected out-of-envelope geometry: "
            f"{quality['out_of_envelope_geometry']['unexpected_count']}"
        ),
        f"exact duplicate groups: {len(quality['duplicates']['exact_duplicate_groups'])}",
        f"near duplicate pairs: {quality['duplicates']['near_duplicate_pair_count']}",
        f"manifest digest: {manifest['manifest_digest']}",
    ]
    if manifest["coverage_gaps"]:
        lines.append("coverage gaps:")
        lines.extend(f"- {gap}" for gap in manifest["coverage_gaps"])
    return "\n".join(lines) + "\n"


__all__ = [
    "M1_MANIFEST_DEFAULT",
    "M0_MANIFEST_DEFAULT",
    "M3_MANIFEST_DEFAULT",
    "OUTPUT_DIRECTORY_DEFAULT",
    "REAL_MATERIALIZATION_DEFAULT",
    "SCENE_MANIFEST_DEFAULT",
    "SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_CAMPAIGN_ID",
    "SYNTHETIC_VISIBLE_REGION_TRAINING_VIEW_SCHEMA_VERSION",
    "SyntheticVisibleRegionTrainingViewError",
    "build_synthetic_visible_region_training_view",
    "render_synthetic_visible_region_training_view_human",
    "validate_synthetic_visible_region_training_view",
    "write_synthetic_visible_region_training_view",
]
