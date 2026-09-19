"""Find table geometry in all recordings and synthesize train-only scenes.

The discovery pass uses the frozen 0068 corrected references.  It keeps exact four-corner
one-, two-, and three-card examples from every recording in the audit.  The synthesis pass
uses only train recordings.  It removes the selected cards from each source frame with a
deterministic OpenCV inpaint operation, then renders reviewed deck cutouts back onto that
recording's measured card geometry.
"""

from __future__ import annotations

import hashlib
import json
import platform
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .reviewed_rfdetr_detector_campaign import (
    canonical_json_bytes,
    validate_reviewed_rfdetr_detector_manifest,
)
from .synthetic_visible_region_materialization import (
    validate_synthetic_visible_region_inputs,
)
from .synthetic_visible_region_rendering import (
    MIN_VISIBLE_PIXELS,
    _alpha_composite,
    _apply_shadow,
    _mask_bbox,
    _mask_polygons,
    _occlusion_ratio,
    _photometric,
    _polygon_area,
    _quad_to_records,
    _read_cutout,
    _remove_small_components,
    _warp_cutout,
)

SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_SCHEMA_VERSION = (
    "synthetic-visible-region-all-recordings/v1"
)
SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_CAMPAIGN_ID = (
    "0070-m5-synthetic-visible-region-all-recordings"
)
SOURCE_MANIFEST_DEFAULT = "data/operations/rfdetr-visible-card-detector-0068-m0-manifest.json"
M1_MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-m1-inputs.json"
MATERIALIZATION_DEFAULT = ".runtime/rfdetr-segmentation-0068"
OUTPUT_DIRECTORY_DEFAULT = ".runtime/synthetic-visible-region-0070-all-recordings"
MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-all-recordings.json"
CARD_COUNTS = (1, 2, 3)
TRAIN_PARTITION = "train"
HELD_OUT_PARTITIONS = frozenset({"validation", "sealed_test"})
_SHA256_LENGTH = 64


class SyntheticVisibleRegionAllRecordingsError(ValueError):
    """The all-recordings geometry or synthesis contract is invalid."""


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyntheticVisibleRegionAllRecordingsError(
            f"could not read {field} {path}: {error}"
        ) from error
    if not isinstance(value, Mapping):
        raise SyntheticVisibleRegionAllRecordingsError(f"{field} must be a JSON object")
    return dict(value)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise SyntheticVisibleRegionAllRecordingsError(f"could not hash {path}: {error}") from error
    return digest.hexdigest()


def _write_bytes(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return _sha256_bytes(payload)


def _write_json(path: Path, value: Mapping[str, Any]) -> str:
    return _write_bytes(path, canonical_json_bytes(value) + b"\n")


def _resolve(repository: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else repository / path


def _relative(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _round(value: float) -> float:
    return round(float(value), 6)


def _quad(target: Mapping[str, Any]) -> list[dict[str, float]] | None:
    geometry = target.get("geometry")
    if not isinstance(geometry, Mapping):
        return None
    visible_region = geometry.get("visible_region")
    if not isinstance(visible_region, Mapping):
        return None
    polygons = visible_region.get("polygons")
    if not isinstance(polygons, list) or len(polygons) != 1:
        return None
    points = polygons[0]
    if not isinstance(points, list) or len(points) != 4:
        return None
    result: list[dict[str, float]] = []
    for point in points:
        if not isinstance(point, Mapping):
            return None
        x = point.get("x")
        y = point.get("y")
        if isinstance(x, bool) or not isinstance(x, int) or not 0 < x < 1000:
            return None
        if isinstance(y, bool) or not isinstance(y, int) or not 0 < y < 1000:
            return None
        result.append({"x": _round(x / 1000), "y": _round(y / 1000)})
    crosses = [
        (result[(index + 1) % 4]["x"] - result[index]["x"])
        * (result[(index + 2) % 4]["y"] - result[(index + 1) % 4]["y"])
        - (result[(index + 1) % 4]["y"] - result[index]["y"])
        * (result[(index + 2) % 4]["x"] - result[(index + 1) % 4]["x"])
        for index in range(4)
    ]
    if not (all(value > 0 for value in crosses) or all(value < 0 for value in crosses)):
        return None
    return result


def _quad_array(quad: Sequence[Mapping[str, float]]) -> np.ndarray:
    return np.asarray([[float(point["x"]), float(point["y"])] for point in quad], dtype=np.float32)


def _quad_metrics(quads: Sequence[Sequence[Mapping[str, float]]]) -> dict[str, Any]:
    arrays = [_quad_array(quad) for quad in quads]
    areas = [float(cv2.contourArea(array.astype(np.float32))) for array in arrays]
    centers = [np.mean(array, axis=0) for array in arrays]
    edge_ratios: list[float] = []
    for array in arrays:
        lengths = [
            float(np.linalg.norm(array[(index + 1) % 4] - array[index]))
            for index in range(4)
        ]
        edge_ratios.append(max(lengths) / min(lengths))
    overlap_ratios: list[float] = []
    if len(arrays) > 1:
        masks = []
        for array in arrays:
            mask = np.zeros((1000, 1000), dtype=np.uint8)
            cv2.fillConvexPoly(mask, np.round(array * 1000).astype(np.int32), 255)
            masks.append(mask)
        for index, mask in enumerate(masks):
            for other in masks[index + 1 :]:
                intersection = int(np.count_nonzero(cv2.bitwise_and(mask, other)))
                denominator = min(int(np.count_nonzero(mask)), int(np.count_nonzero(other)))
                overlap_ratios.append(0.0 if denominator == 0 else intersection / denominator)
    points = np.concatenate(arrays)
    interior_margin = float(min(np.min(points), np.min(1.0 - points)))
    return {
        "card_area_ratios": [_round(area) for area in areas],
        "card_area_ratio_mean": _round(sum(areas) / len(areas)),
        "card_area_ratio_min": _round(min(areas)),
        "edge_length_ratio_max": _round(max(edge_ratios)),
        "interior_margin": _round(interior_margin),
        "maximum_pairwise_overlap_ratio": _round(max(overlap_ratios, default=0.0)),
        "centers": [
            {"x": _round(float(center[0])), "y": _round(float(center[1]))}
            for center in centers
        ],
    }


def _candidate_score(metrics: Mapping[str, Any], reviewed_count: int, card_count: int) -> float:
    # Prefer human-corrected geometry, interior cards, regular card shapes, and non-overlap.
    score = reviewed_count * 100.0
    score += float(metrics["interior_margin"]) * 20.0
    score += min(0.10, float(metrics["card_area_ratio_mean"])) * 10.0
    score -= max(0.0, float(metrics["edge_length_ratio_max"]) - 1.8) * 4.0
    score -= float(metrics["maximum_pairwise_overlap_ratio"]) * 40.0
    score += card_count * 0.001
    return _round(score)


def _source_group_by_recording(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result = {}
    for group in manifest.get("source_groups", []):
        if isinstance(group, Mapping):
            result[str(group["recording_id"])] = group
    return result


def _candidate_from_sample(
    sample: Mapping[str, Any], group: Mapping[str, Any]
) -> dict[str, Any] | None:
    targets = sample.get("targets")
    if not isinstance(targets, list) or len(targets) not in CARD_COUNTS:
        return None
    if sample.get("ignored_regions"):
        return None
    quads: list[list[dict[str, float]]] = []
    kinds: list[str] = []
    sides: list[str] = []
    for target in targets:
        if not isinstance(target, Mapping):
            return None
        parsed = _quad(target)
        if parsed is None:
            return None
        geometry = target.get("geometry", {})
        kinds.append(str(geometry.get("kind", "unknown")))
        sides.append(str(target.get("side", "unknown")))
        quads.append(parsed)
    metrics = _quad_metrics(quads)
    reviewed_count = sum(kind == "reviewed-visible-region/v1" for kind in kinds)
    return {
        "candidate_id": f"{sample['event_id']}-table-geometry",
        "event_id": str(sample["event_id"]),
        "item_id": str(sample.get("item_id", sample["event_id"])),
        "recording_id": str(sample["recording_id"]),
        "source_group_key": str(group["group_key"]),
        "source_split": str(sample["split"]),
        "table_setup": str(group["table_setup"]),
        "frame_identity": dict(sample["frame_identity"]),
        "card_count": len(quads),
        "card_sides": sides,
        "annotation_kinds": kinds,
        "reviewed_target_count": reviewed_count,
        "normalized_quadrilaterals": quads,
        "metrics": metrics,
        "selection_score": _candidate_score(metrics, reviewed_count, len(quads)),
        "selection": "exact-four-corner-one-two-three-card-corrected-frame-v2",
    }


def build_synthetic_visible_region_recording_discovery(
    repository_root: str | Path,
    *,
    source_manifest_path: str | Path = SOURCE_MANIFEST_DEFAULT,
) -> dict[str, Any]:
    """Audit exact 1/2/3-card geometry across every frozen 0068 recording."""

    repository = Path(repository_root).expanduser().resolve()
    source_path = _resolve(repository, source_manifest_path)
    source_manifest = _read_json(source_path, "0068 source manifest")
    try:
        validate_reviewed_rfdetr_detector_manifest(source_manifest)
    except ValueError as error:
        raise SyntheticVisibleRegionAllRecordingsError(
            f"0068 source manifest is invalid: {error}"
        ) from error
    groups = _source_group_by_recording(source_manifest)
    candidates: list[dict[str, Any]] = []
    for sample in source_manifest.get("samples", []):
        if not isinstance(sample, Mapping) or str(sample.get("split")) not in {
            "train",
            "validation",
            "sealed_test",
        }:
            continue
        recording_id = str(sample.get("recording_id"))
        group = groups.get(recording_id)
        if group is None:
            continue
        candidate = _candidate_from_sample(sample, group)
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(key=lambda item: (item["recording_id"], item["card_count"], item["event_id"]))
    by_recording: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_recording[candidate["recording_id"]].append(candidate)
    recordings: list[dict[str, Any]] = []
    for recording_id in sorted(groups):
        group = groups[recording_id]
        recording_candidates = by_recording.get(recording_id, [])
        selected = {}
        for card_count in CARD_COUNTS:
            options = [item for item in recording_candidates if item["card_count"] == card_count]
            if options:
                selected[str(card_count)] = max(
                    options,
                    key=lambda item: (
                        float(item["selection_score"]),
                        int(item["reviewed_target_count"]),
                        str(item["event_id"]),
                    ),
                )
            else:
                selected[str(card_count)] = None
        recordings.append(
            {
                "recording_id": recording_id,
                "source_group_key": str(group["group_key"]),
                "source_sha256": str(group["source_sha256"]),
                "source_split": str(group["partition"]),
                "table_setup": str(group["table_setup"]),
                "candidate_count": len(recording_candidates),
                "candidate_counts": {
                    str(card_count): sum(
                        item["card_count"] == card_count for item in recording_candidates
                    )
                    for card_count in CARD_COUNTS
                },
                "selected_candidates": selected,
                "synthesis_policy": (
                    "train_recording_only"
                    if group["partition"] == TRAIN_PARTITION
                    else "discovery_only"
                ),
            }
        )
    partition_counts = Counter(str(item["source_split"]) for item in candidates)
    selected_train = sum(
        sum(value is not None for value in item["selected_candidates"].values())
        for item in recordings
        if item["source_split"] == TRAIN_PARTITION
    )
    core = {
        "schema_version": SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_CAMPAIGN_ID,
        "milestone": "M5",
        "freeze_state": "discovery_ready",
        "source_manifest": {
            "path": _relative(source_path, repository),
            "sha256": _sha256_file(source_path),
            "manifest_digest": str(source_manifest["manifest_digest"]),
        },
        "policy": {
            "card_counts": list(CARD_COUNTS),
            "discovery_partitions": ["train", "validation", "sealed_test"],
            "synthesis_partitions": [TRAIN_PARTITION],
            "held_out_synthesis": False,
            "geometry_selection": "highest-scoring-candidate-per-recording-and-card-count-v2",
            "background_strategy": "reviewed-source-frame-card-region-inpaint-v1",
        },
        "inventory": {
            "recording_count": len(recordings),
            "candidate_count": len(candidates),
            "candidate_counts_by_partition": dict(sorted(partition_counts.items())),
            "recordings_with_train_scene_candidates": sum(
                item["source_split"] == TRAIN_PARTITION and item["candidate_count"] > 0
                for item in recordings
            ),
            "selected_train_scene_count": selected_train,
        },
        "recordings": recordings,
        "candidates": candidates,
        "outputs": None,
        "coverage_gaps": [
            "validation and sealed_test geometry is audited for table discovery only",
            "synthetic scene materialization is train-only to preserve held-out partitions",
        ],
    }
    return {**core, "manifest_digest": _sha256_bytes(canonical_json_bytes(core))}


def _materialization_frame_paths(
    repository: Path, materialization_root: Path
) -> dict[str, tuple[Path, str]]:
    manifest = _read_json(materialization_root / "materialization.json", "0068 materialization")
    result: dict[str, tuple[Path, str]] = {}
    for item in manifest.get("generated_files", []):
        if not isinstance(item, Mapping) or item.get("kind") != "extracted_frame":
            continue
        event_id = item.get("event_id")
        relative_path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(event_id, str) or not isinstance(relative_path, str):
            continue
        path = materialization_root / relative_path
        if not path.is_file() or not isinstance(digest, str) or _sha256_file(path) != digest:
            raise SyntheticVisibleRegionAllRecordingsError(
                f"0068 materialized frame is missing or changed: {event_id}"
            )
        result[event_id] = (path, digest)
    return result


def _inpaint_background(
    image: np.ndarray, quads: Sequence[Sequence[Mapping[str, float]]]
) -> np.ndarray:
    height, width = image.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    for quad in quads:
        points = np.round(_quad_array(quad) * np.asarray([width, height])).astype(np.int32)
        cv2.fillConvexPoly(mask, points, 255)
    mask = cv2.dilate(mask, np.ones((5, 5), dtype=np.uint8), iterations=1)
    return cv2.inpaint(image, mask, 7.0, cv2.INPAINT_TELEA)


def _usable_cutouts(repository: Path, m1: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for record in m1.get("cutouts", []):
        if not isinstance(record, Mapping):
            continue
        group = record.get("source_group")
        decision = record.get("reviewed_decision")
        files = record.get("files")
        if not isinstance(group, Mapping) or group.get("split") != TRAIN_PARTITION:
            continue
        if not isinstance(decision, Mapping) or decision.get("card_side") not in {
            "face_up",
            "unknown",
        }:
            continue
        if not isinstance(files, Mapping) or not isinstance(files.get("rgba"), Mapping):
            continue
        if not isinstance(files.get("alpha"), Mapping):
            continue
        rgba_path = _resolve(repository, str(files["rgba"]["path"]))
        alpha_path = _resolve(repository, str(files["alpha"]["path"]))
        if not rgba_path.is_file() or not alpha_path.is_file():
            raise SyntheticVisibleRegionAllRecordingsError(
                f"M1 cutout files are missing: {record.get('cutout_id')}"
            )
        for path, field in ((rgba_path, "rgba"), (alpha_path, "alpha")):
            if _sha256_file(path) != files[field].get("sha256"):
                raise SyntheticVisibleRegionAllRecordingsError(
                    f"M1 cutout {field} digest differs: {record.get('cutout_id')}"
                )
        result.append({"record": dict(record), "rgba_path": rgba_path, "alpha_path": alpha_path})
    if not result:
        raise SyntheticVisibleRegionAllRecordingsError("M1 has no usable train cutouts")
    return sorted(result, key=lambda item: str(item["record"]["cutout_id"]))


def _selected_assets(
    usable: Sequence[Mapping[str, Any]], recording_id: str, card_count: int
) -> list[Mapping[str, Any]]:
    digest = hashlib.sha256(f"{recording_id}:{card_count}".encode("utf-8")).hexdigest()
    offset = int(digest[:8], 16) % len(usable)
    return [usable[(offset + index) % len(usable)] for index in range(card_count)]


def _render_recording_scene(
    repository: Path,
    output_root: Path,
    *,
    scene_id: str,
    recording: Mapping[str, Any],
    candidate: Mapping[str, Any],
    background_path: Path,
    background_digest: str,
    assets: Sequence[Mapping[str, Any]],
    seed: int,
    image_id: int,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    scene = cv2.imread(str(background_path), cv2.IMREAD_COLOR)
    if scene is None:
        raise SyntheticVisibleRegionAllRecordingsError(
            f"could not decode background {background_path}"
        )
    height, width = scene.shape[:2]
    dimensions = np.asarray([width, height], dtype=np.float32)
    rng = np.random.default_rng(seed)
    placements: list[dict[str, Any]] = []
    for index, (quad, asset) in enumerate(
        zip(candidate["normalized_quadrilaterals"], assets, strict=True), start=1
    ):
        record = asset["record"]
        rgba, alpha = _read_cutout(asset)
        destination_quad = _quad_array(quad) * dimensions
        warped, warped_alpha = _warp_cutout(rgba, alpha, destination_quad, width, height)
        warped_alpha = _remove_small_components(warped_alpha, MIN_VISIBLE_PIXELS)
        placements.append(
            {
                "instance_index": index,
                "z_order": index,
                "target_quad": destination_quad,
                "cutout_id": str(record["cutout_id"]),
                "source_asset_id": str(record["source_asset_id"]),
                "side": str(record["reviewed_decision"]["card_side"]),
                "source_group": dict(record["source_group"]),
                "full_mask": warped_alpha,
                "warped_rgba": warped,
                "source_quadrilateral": record["source_quadrilateral"],
            }
        )
    full_masks = [item["full_mask"] for item in placements]
    visible_masks = [np.zeros((height, width), dtype=np.uint8) for _ in placements]
    higher = np.zeros((height, width), dtype=np.uint8)
    for index in range(len(placements) - 1, -1, -1):
        visible_masks[index] = np.where(
            (full_masks[index] > 0) & (higher == 0), 255, 0
        ).astype(np.uint8)
        visible_masks[index] = _remove_small_components(visible_masks[index], MIN_VISIBLE_PIXELS)
        higher = np.maximum(higher, full_masks[index])
    shadow_opacity = float(rng.uniform(0.08, 0.22))
    for full_mask in full_masks:
        _apply_shadow(scene, full_mask, shadow_opacity)
    for placement in placements:
        _alpha_composite(scene, placement["warped_rgba"], placement["full_mask"])
    effects = {"shadow_opacity": _round(shadow_opacity), **_photometric(scene, rng, True)}
    ok, encoded = cv2.imencode(
        ".jpg", scene, [cv2.IMWRITE_JPEG_QUALITY, int(effects["jpeg_quality"])]
    )
    if not ok:
        raise SyntheticVisibleRegionAllRecordingsError(f"could not encode scene {scene_id}")
    image_path = output_root / "images" / f"{scene_id}.jpg"
    image_digest = _write_bytes(image_path, encoded.tobytes())
    instances: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    for placement, visible_mask in zip(placements, visible_masks, strict=True):
        visible_pixels = int(np.count_nonzero(visible_mask))
        full_pixels = int(np.count_nonzero(placement["full_mask"]))
        if visible_pixels < MIN_VISIBLE_PIXELS:
            omitted.append(
                {
                    "cutout_id": placement["cutout_id"],
                    "reason": "below_visible_pixel_threshold",
                    "visible_mask_pixels": visible_pixels,
                }
            )
            continue
        polygons = _mask_polygons(visible_mask)
        if not polygons:
            omitted.append(
                {
                    "cutout_id": placement["cutout_id"],
                    "reason": "visible_mask_has_no_polygon",
                    "visible_mask_pixels": visible_pixels,
                }
            )
            continue
        mask_path = (
            output_root
            / "masks"
            / f"{scene_id}-instance-{placement['instance_index']:02d}.png"
        )
        ok, mask_bytes = cv2.imencode(".png", visible_mask)
        if not ok:
            raise SyntheticVisibleRegionAllRecordingsError(f"could not encode mask {scene_id}")
        mask_digest = _write_bytes(mask_path, mask_bytes.tobytes())
        bbox = _mask_bbox(visible_mask)
        area = sum(
            _polygon_area(list(zip(polygon[::2], polygon[1::2], strict=True)))
            for polygon in polygons
        ) / 2.0
        instance = {
            "instance_index": placement["instance_index"],
            "cutout_id": placement["cutout_id"],
            "source_asset_id": placement["source_asset_id"],
            "side": placement["side"],
            "z_order": placement["z_order"],
            "source_group": placement["source_group"],
            "source_quadrilateral": placement["source_quadrilateral"],
            "target_quadrilateral": _quad_to_records(placement["target_quad"]),
            "full_mask_pixels": full_pixels,
            "visible_mask_pixels": visible_pixels,
            "occlusion_ratio": _occlusion_ratio(placement["full_mask"], visible_mask),
            "mask": {
                "path": _relative(mask_path, repository),
                "sha256": mask_digest,
                "bbox": bbox,
                "polygons": polygons,
            },
        }
        instances.append(instance)
        annotation_id = int(
            hashlib.sha256(
                f"{scene_id}:{placement['instance_index']}".encode()
            ).hexdigest()[:12],
            16,
        )
        annotations.append(
            {
                "id": annotation_id,
                "image_id": image_id,
                "category_id": 1,
                "bbox": bbox,
                "area": _round(area),
                "segmentation": polygons,
                "iscrowd": 0,
                "target_state": "synthetic_visible_region",
                "recording_id": scene_id,
                "event_id": scene_id,
                "item_id": placement["cutout_id"],
                "reference_revision_id": "synthetic-visible-region-all-recordings-v1",
                "card_id": placement["cutout_id"],
                "source_video_sha256": str(recording["source_sha256"]),
                "source_frame_sha256": image_digest,
                "target_geometry_sha256": _sha256_bytes(
                    canonical_json_bytes(placement["target_quad"].tolist())
                ),
                "split": "train",
                "card_side": placement["side"],
                "session_id": f"synthetic-{recording['recording_id']}",
                "source_asset_id": placement["source_asset_id"],
                "video_id": scene_id,
                "table_setup": str(recording["table_setup"]),
                "source_group_key": str(recording["source_group_key"]),
                "synthetic_source_recording_id": str(recording["recording_id"]),
            }
        )
    receipt_core = {
        "schema_version": SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_CAMPAIGN_ID,
        "milestone": "M5",
        "scene_id": scene_id,
        "seed": seed,
        "recording_id": recording["recording_id"],
        "table_setup": recording["table_setup"],
        "card_count": candidate["card_count"],
        "geometry_reference": {
            "candidate_id": candidate["candidate_id"],
            "event_id": candidate["event_id"],
            "frame_identity": candidate["frame_identity"],
            "selection_score": candidate["selection_score"],
            "normalized_quadrilaterals": candidate["normalized_quadrilaterals"],
            "metrics": candidate["metrics"],
        },
        "background": {
            "strategy": "reviewed-source-frame-card-region-inpaint-v1",
            "source_event_id": candidate["event_id"],
            "source_frame_sha256": background_digest,
            "path": _relative(background_path, repository),
            "output_sha256": _sha256_file(background_path),
        },
        "placements": instances,
        "omitted_instances": omitted,
        "effects": effects,
        "output": {
            "image": {
                "path": _relative(image_path, repository),
                "sha256": image_digest,
                "width": width,
                "height": height,
            }
        },
        "source_lineage": {
            "permission": "training_only",
            "split": "train",
            "source_group_keys": sorted(
                {str(recording["source_group_key"])}
                | {str(item["source_group"]["key"]) for item in instances}
            ),
        },
        "renderer": {
            "opencv_version": cv2.__version__,
            "numpy_version": np.__version__,
            "python_version": platform.python_version(),
            "mask_policy": "opaque-card-z-order-and-frame-clipping-v1",
        },
    }
    receipt = {**receipt_core, "receipt_digest": _sha256_bytes(canonical_json_bytes(receipt_core))}
    receipt_path = output_root / "receipts" / f"{scene_id}.json"
    _write_json(receipt_path, receipt)
    summary = {
        "scene_id": scene_id,
        "recording_id": recording["recording_id"],
        "table_setup": recording["table_setup"],
        "card_count": candidate["card_count"],
        "candidate_id": candidate["candidate_id"],
        "image_path": _relative(image_path, repository),
        "image_sha256": image_digest,
        "receipt_path": _relative(receipt_path, repository),
        "receipt_digest": receipt["receipt_digest"],
        "instance_count": len(instances),
        "omitted_instance_count": len(omitted),
    }
    image = {
        "id": image_id,
        "file_name": _relative(image_path, output_root),
        "width": width,
        "height": height,
        "sha256": image_digest,
        "recording_id": scene_id,
        "event_id": scene_id,
        "item_id": candidate["event_id"],
        "reference_revision_id": "synthetic-visible-region-all-recordings-v1",
        "source_video_sha256": str(recording["source_sha256"]),
        "source_frame_sha256": image_digest,
        "split": "train",
        "trainer_partition": "train",
        "session_id": f"synthetic-{recording['recording_id']}",
        "source_asset_id": scene_id,
        "video_id": scene_id,
        "table_setup": str(recording["table_setup"]),
        "source_group_key": str(recording["source_group_key"]),
        "dataset_origin": "synthetic",
        "synthetic_source_recording_id": str(recording["recording_id"]),
        "scene_bucket": f"recording_{candidate['card_count']}_cards",
    }
    return summary, image, annotations


def build_synthetic_visible_region_all_recordings(
    repository_root: str | Path,
    *,
    source_manifest_path: str | Path = SOURCE_MANIFEST_DEFAULT,
    m1_manifest_path: str | Path = M1_MANIFEST_DEFAULT,
    materialization_directory: str | Path = MATERIALIZATION_DEFAULT,
    output_directory: str | Path = OUTPUT_DIRECTORY_DEFAULT,
    discover_only: bool = False,
) -> dict[str, Any]:
    """Discover all recording geometries and optionally render train-only scenes."""

    repository = Path(repository_root).expanduser().resolve()
    discovery = build_synthetic_visible_region_recording_discovery(
        repository, source_manifest_path=source_manifest_path
    )
    if discover_only:
        return discovery
    m1_path = _resolve(repository, m1_manifest_path)
    m1 = _read_json(m1_path, "M1 input manifest")
    try:
        validate_synthetic_visible_region_inputs(m1)
    except ValueError as error:
        raise SyntheticVisibleRegionAllRecordingsError(
            f"M1 input manifest is invalid: {error}"
        ) from error
    materialization_root = _resolve(repository, materialization_directory)
    frame_paths = _materialization_frame_paths(repository, materialization_root)
    output_root = _resolve(repository, output_directory)
    output_root.mkdir(parents=True, exist_ok=True)
    usable = _usable_cutouts(repository, m1)
    scene_summaries: list[dict[str, Any]] = []
    coco_images: list[dict[str, Any]] = []
    coco_annotations: list[dict[str, Any]] = []
    errors: list[str] = []
    scene_index = 0
    for recording in discovery["recordings"]:
        if recording["source_split"] != TRAIN_PARTITION:
            continue
        for card_count in CARD_COUNTS:
            candidate = recording["selected_candidates"].get(str(card_count))
            if candidate is None:
                continue
            event_id = str(candidate["event_id"])
            frame_data = frame_paths.get(event_id)
            if frame_data is None:
                errors.append(
                    f"{recording['recording_id']}/{card_count}: materialized frame is missing"
                )
                continue
            frame_path, frame_digest = frame_data
            source = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
            if source is None:
                errors.append(
                    f"{recording['recording_id']}/{card_count}: source frame is unreadable"
                )
                continue
            background = _inpaint_background(source, candidate["normalized_quadrilaterals"])
            background_path = (
                output_root
                / "backgrounds"
                / f"{recording['recording_id']}-{event_id}.jpg"
            )
            ok, encoded_background = cv2.imencode(
                ".jpg", background, [cv2.IMWRITE_JPEG_QUALITY, 95]
            )
            if not ok:
                raise SyntheticVisibleRegionAllRecordingsError(
                    f"could not encode background {recording['recording_id']}"
                )
            background_digest = _write_bytes(background_path, encoded_background.tobytes())
            scene_id = f"scene-{scene_index:04d}-{recording['recording_id']}-{card_count}cards"
            summary, image, annotations = _render_recording_scene(
                repository,
                output_root,
                scene_id=scene_id,
                recording=recording,
                candidate=candidate,
                background_path=background_path,
                background_digest=frame_digest,
                assets=_selected_assets(usable, str(recording["recording_id"]), card_count),
                seed=7001 + scene_index,
                image_id=scene_index + 1,
            )
            summary["background_path"] = _relative(background_path, repository)
            summary["background_sha256"] = background_digest
            summary["source_frame_sha256"] = frame_digest
            scene_summaries.append(summary)
            coco_images.append(image)
            coco_annotations.extend(annotations)
            scene_index += 1
    if errors:
        raise SyntheticVisibleRegionAllRecordingsError("; ".join(errors))
    coco = {
        "info": {
            "description": (
                "DokoDetector train-only synthetic visible-region scenes for all train recordings"
            ),
            "version": SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_SCHEMA_VERSION,
            "coco_version": "coco-2017",
            "campaign_id": SYNTHETIC_VISIBLE_REGION_ALL_RECORDINGS_CAMPAIGN_ID,
            "trainer_partition": "train",
        },
        "licenses": [],
        "images": coco_images,
        "annotations": coco_annotations,
        "categories": [{"id": 1, "name": "visible_card", "supercategory": "card"}],
    }
    from .rfdetr_segmentation_materialization import validate_rfdetr_coco_annotations

    validate_rfdetr_coco_annotations(coco)
    coco_path = output_root / "_annotations.coco.json"
    coco_digest = _write_json(coco_path, coco)
    core = {
        **{key: value for key, value in discovery.items() if key != "manifest_digest"},
        "freeze_state": "complete_with_gaps",
        "m1_manifest": {
            "path": _relative(m1_path, repository),
            "sha256": _sha256_file(m1_path),
            "manifest_digest": str(m1["manifest_digest"]),
        },
        "materialization": {
            "path": _relative(materialization_root, repository),
            "materialization_manifest_sha256": _sha256_file(
                materialization_root / "materialization.json"
            ),
        },
        "inventory": {
            **discovery["inventory"],
            "synthesized_recording_count": len({item["recording_id"] for item in scene_summaries}),
            "synthesized_scene_count": len(scene_summaries),
            "synthesized_annotation_count": len(coco_annotations),
            "synthesized_scene_counts_by_card_count": dict(
                sorted(Counter(str(item["card_count"]) for item in scene_summaries).items())
            ),
        },
        "outputs": {
            "directory": _relative(output_root, repository),
            "coco": {"path": _relative(coco_path, repository), "sha256": coco_digest},
            "scene_count": len(scene_summaries),
            "image_count": len(coco_images),
            "annotation_count": len(coco_annotations),
        },
        "scenes": scene_summaries,
        "coverage_gaps": [
            "validation and sealed_test geometry is audited for table discovery only",
            "synthetic scenes are materialized only for train recordings",
            "background pixels under source cards use deterministic OpenCV inpainting",
        ],
    }
    return {**core, "manifest_digest": _sha256_bytes(canonical_json_bytes(core))}


def write_synthetic_visible_region_all_recordings_manifest(
    path: str | Path, manifest: Mapping[str, Any]
) -> Path:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(manifest) + b"\n")
    return destination


def render_synthetic_visible_region_all_recordings_human(manifest: Mapping[str, Any]) -> str:
    inventory = manifest["inventory"]
    lines = [
        "Epic 0070 all-recordings table geometry and synthesis",
        f"state: {manifest['freeze_state']}",
        f"recordings audited: {inventory['recording_count']}",
        f"1/2/3-card candidates: {inventory['candidate_count']}",
    ]
    if manifest.get("outputs"):
        lines.extend(
            [
                f"train recordings synthesized: {inventory['synthesized_recording_count']}",
                f"synthetic scenes: {inventory['synthesized_scene_count']}",
                f"COCO: {manifest['outputs']['coco']['path']}",
            ]
        )
    else:
        lines.append("mode: discovery only")
    lines.append("held-out synthesis: forbidden")
    for gap in manifest.get("coverage_gaps", []):
        lines.append(f"gap: {gap}")
    return "\n".join(lines) + "\n"


__all__ = [
    "MANIFEST_DEFAULT",
    "M1_MANIFEST_DEFAULT",
    "MATERIALIZATION_DEFAULT",
    "OUTPUT_DIRECTORY_DEFAULT",
    "SOURCE_MANIFEST_DEFAULT",
    "SyntheticVisibleRegionAllRecordingsError",
    "build_synthetic_visible_region_all_recordings",
    "build_synthetic_visible_region_recording_discovery",
    "render_synthetic_visible_region_all_recordings_human",
    "write_synthetic_visible_region_all_recordings_manifest",
]
