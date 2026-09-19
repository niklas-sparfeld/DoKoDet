"""Render a small synthetic visible-card sample set on reviewed empty tables only.

Card-bearing reviewed frames are used as geometry and lighting references.  They never become
background pixels.  The rendering order is fixed:

1. white-balance every eligible training cutout;
2. estimate one lighting profile from known cards in the reference frame;
3. apply that shared profile to every card in the scene;
4. composite cards onto an explicitly reviewed empty table; and
5. apply one scene-level lighting condition to the complete image.

The command is deliberately bounded by default.  The operator must inspect the sample output
before using a larger scene limit.
"""

from __future__ import annotations

import hashlib
import json
import platform
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .reviewed_rfdetr_detector_campaign import canonical_json_bytes
from .rfdetr_segmentation_materialization import validate_rfdetr_coco_annotations
from .synthetic_visible_region_materialization import (
    validate_synthetic_visible_region_inputs,
)
from .synthetic_visible_region_recording_synthesis import (
    MAX_CARD_COUNT_DEFAULT,
    SOURCE_MANIFEST_DEFAULT,
    _estimate_table_geometry,
    _materialization_frame_paths,
    _quad_array,
    _regularize_quadrilaterals,
    _select_table_geometry_references,
    _selected_assets,
    _usable_cutouts,
    build_synthetic_visible_region_recording_discovery,
)
from .synthetic_visible_region_rendering import (
    CANONICAL_HEIGHT,
    CANONICAL_WIDTH,
    MIN_VISIBLE_PIXELS,
    _alpha_composite,
    _apply_shadow,
    _mask_bbox,
    _mask_polygons,
    _occlusion_ratio,
    _polygon_area,
    _quad_to_records,
    _read_cutout,
    _remove_small_components,
    _warp_cutout,
)

SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_SCHEMA_VERSION = (
    "synthetic-visible-region-empty-table-samples/v1"
)
SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_CAMPAIGN_ID = (
    "0070-m5-synthetic-visible-region-empty-table-samples"
)
M1_MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-m1-inputs.json"
MATERIALIZATION_DEFAULT = ".runtime/rfdetr-segmentation-0068"
OUTPUT_DIRECTORY_DEFAULT = ".runtime/synthetic-visible-region-0070-empty-table-samples"
MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-empty-table-samples.json"
SCENE_LIMIT_DEFAULT = 6
LIGHTING_PROFILE_METHOD = "known-card-highlight-transfer-v1"
BACKGROUND_STRATEGY = "explicit-reviewed-empty-table-only-v1"
WHITE_BALANCE_METHOD = "neutral-highlight-gray-world-v1"
_SHA256_LENGTH = 64


class SyntheticVisibleRegionEmptyTableError(ValueError):
    """The empty-table synthesis contract is invalid."""


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyntheticVisibleRegionEmptyTableError(
            f"could not read {field} {path}: {error}"
        ) from error
    if not isinstance(value, Mapping):
        raise SyntheticVisibleRegionEmptyTableError(f"{field} must be a JSON object")
    return dict(value)


def _resolve(repository: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else repository / path


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _write_bytes(path: Path, value: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return _sha256_bytes(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> str:
    return _write_bytes(path, canonical_json_bytes(value) + b"\n")


def _round(value: float) -> float:
    return round(float(value), 6)


def _valid_pixels(image: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] != 3 or alpha.shape != image.shape[:2]:
        raise SyntheticVisibleRegionEmptyTableError("image and alpha dimensions are invalid")
    interior = cv2.erode(
        np.where(alpha > 0, 255, 0).astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)),
    )
    if int(np.count_nonzero(interior)) < 100:
        interior = np.where(alpha > 0, 255, 0).astype(np.uint8)
    return image[interior > 0].astype(np.float32)


def _estimate_white_point(image: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, int]:
    """Estimate the card-paper white point from bright, low-saturation pixels."""

    pixels = _valid_pixels(image, alpha)
    if len(pixels) == 0:
        raise SyntheticVisibleRegionEmptyTableError("card cutout has no opaque pixels")
    hsv = cv2.cvtColor(pixels.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2HSV)
    luminance = np.max(pixels, axis=1)
    saturation = hsv[:, 0:1, 1].reshape(-1).astype(np.float32)
    threshold = float(np.percentile(luminance, 65.0))
    selected = (luminance >= threshold) & (saturation <= 72.0)
    if int(np.count_nonzero(selected)) < max(40, len(pixels) // 100):
        selected = luminance >= float(np.percentile(luminance, 80.0))
    if int(np.count_nonzero(selected)) == 0:
        selected = np.ones(len(pixels), dtype=bool)
    return np.median(pixels[selected], axis=0) / 255.0, int(np.count_nonzero(selected))


def _white_balance_cutout(
    rgba: np.ndarray, alpha: np.ndarray
) -> tuple[np.ndarray, dict[str, Any]]:
    """Neutralize one card before any scene lighting is applied."""

    source_white, sample_count = _estimate_white_point(rgba[:, :, :3], alpha)
    mean_white = float(np.mean(source_white))
    channel_gains = np.clip(mean_white / np.maximum(source_white, 1e-4), 0.65, 1.55)
    balanced = rgba.astype(np.float32).copy()
    balanced[:, :, :3] *= channel_gains.reshape(1, 1, 3)
    balanced_white = source_white * channel_gains
    exposure = float(np.clip(0.88 / max(float(np.mean(balanced_white)), 1e-4), 0.75, 1.25))
    balanced[:, :, :3] *= exposure
    result = np.clip(balanced, 0, 255).astype(np.uint8)
    return result, {
        "method": WHITE_BALANCE_METHOD,
        "source_white_point_bgr": [_round(value) for value in source_white],
        "channel_gains_bgr": [_round(value) for value in channel_gains],
        "exposure": _round(exposure),
        "sample_count": sample_count,
    }


def _reference_white_point(
    image: np.ndarray, normalized_quads: Sequence[Sequence[Mapping[str, float]]]
) -> tuple[np.ndarray, int]:
    height, width = image.shape[:2]
    destination = np.asarray(
        [
            [0, 0],
            [CANONICAL_WIDTH - 1, 0],
            [CANONICAL_WIDTH - 1, CANONICAL_HEIGHT - 1],
            [0, CANONICAL_HEIGHT - 1],
        ],
        dtype=np.float32,
    )
    estimates: list[np.ndarray] = []
    sample_count = 0
    dimensions = np.asarray([width, height], dtype=np.float32)
    for normalized_quad in normalized_quads:
        source = _quad_array(normalized_quad) * dimensions
        transform = cv2.getPerspectiveTransform(source.astype(np.float32), destination)
        patch = cv2.warpPerspective(image, transform, (CANONICAL_WIDTH, CANONICAL_HEIGHT))
        patch_white, count = _estimate_white_point(
            patch, np.full(patch.shape[:2], 255, dtype=np.uint8)
        )
        estimates.append(patch_white)
        sample_count += count
    if not estimates:
        raise SyntheticVisibleRegionEmptyTableError("lighting reference has no card quadrilateral")
    return np.median(np.stack(estimates), axis=0), sample_count


def _lighting_profile(
    image: np.ndarray,
    candidate: Mapping[str, Any],
    frame_path: Path,
    frame_digest: str,
) -> dict[str, Any]:
    reference_white, sample_count = _reference_white_point(
        image, candidate["normalized_quadrilaterals"]
    )
    target_white = 0.88
    gains = np.clip(reference_white / target_white, 0.65, 1.45)
    return {
        "method": LIGHTING_PROFILE_METHOD,
        "scope": "all_cards_in_scene",
        "reference_recording_id": str(candidate["recording_id"]),
        "reference_event_id": str(candidate["event_id"]),
        "reference_candidate_id": str(candidate["candidate_id"]),
        "reference_frame_path": str(frame_path),
        "reference_frame_sha256": frame_digest,
        "reference_card_count": int(candidate["card_count"]),
        "reference_white_point_bgr": [_round(value) for value in reference_white],
        "shared_card_gains_bgr": [_round(value) for value in gains],
        "white_point_sample_count": sample_count,
    }


def _apply_card_lighting(
    rgba: np.ndarray, alpha: np.ndarray, profile: Mapping[str, Any]
) -> np.ndarray:
    result = rgba.astype(np.float32).copy()
    gains = np.asarray(profile["shared_card_gains_bgr"], dtype=np.float32)
    result[:, :, :3] *= gains.reshape(1, 1, 3)
    result[:, :, 3] = alpha
    return np.clip(result, 0, 255).astype(np.uint8)


def _scene_lighting_parameters(seed: int) -> dict[str, Any]:
    """Create one lighting condition for the complete scene, never per card."""

    rng = np.random.default_rng(seed)
    temperature = float(rng.uniform(-0.045, 0.045))
    return {
        "scope": "complete_scene",
        "seed": seed,
        "exposure": _round(float(rng.uniform(0.88, 1.12))),
        "contrast": _round(float(rng.uniform(0.92, 1.08))),
        "color_gains_bgr": [
            _round(1.0 - temperature),
            1.0,
            _round(1.0 + temperature),
        ],
        "vignette": _round(float(rng.uniform(0.0, 0.08))),
        "shadow_opacity": _round(float(rng.uniform(0.10, 0.22))),
        "jpeg_quality": int(rng.integers(88, 97)),
    }


def _apply_scene_lighting(scene: np.ndarray, parameters: Mapping[str, Any]) -> np.ndarray:
    height, width = scene.shape[:2]
    result = scene.astype(np.float32)
    result = (result - 128.0) * float(parameters["contrast"]) + 128.0
    result *= float(parameters["exposure"])
    result *= np.asarray(parameters["color_gains_bgr"], dtype=np.float32).reshape(1, 1, 3)
    vignette = float(parameters["vignette"])
    if vignette > 0.0:
        y, x = np.ogrid[:height, :width]
        distance = np.sqrt(
            ((x - width / 2.0) / max(width / 2.0, 1.0)) ** 2
            + ((y - height / 2.0) / max(height / 2.0, 1.0)) ** 2
        )
        result *= np.clip(1.0 - vignette * np.minimum(distance, 1.0), 0.0, 1.0)[
            :, :, None
        ]
    return np.clip(result, 0, 255).astype(np.uint8)


def _empty_backgrounds(m1: Mapping[str, Any]) -> list[dict[str, Any]]:
    backgrounds: list[dict[str, Any]] = []
    for background in m1.get("backgrounds", []):
        if not isinstance(background, Mapping):
            continue
        decision = background.get("reviewed_decision")
        source_group = background.get("source_group")
        files = background.get("files")
        image = files.get("image") if isinstance(files, Mapping) else None
        if (
            not isinstance(decision, Mapping)
            or decision.get("status") != "accepted"
            or decision.get("contains_visible_card") is not False
            or decision.get("full_frame_review_coverage") is not True
            or not isinstance(source_group, Mapping)
            or source_group.get("split") != "train"
            or not isinstance(image, Mapping)
        ):
            continue
        backgrounds.append({"record": dict(background), "image": dict(image)})
    return sorted(backgrounds, key=lambda item: str(item["record"]["background_id"]))


def _prepare_white_balanced_cutouts(
    repository: Path,
    output_root: Path,
    usable: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    prepared: dict[str, dict[str, Any]] = {}
    for item in usable:
        record = item["record"]
        rgba, alpha = _read_cutout(item)
        balanced, profile = _white_balance_cutout(rgba, alpha)
        cutout_id = str(record["cutout_id"])
        path = output_root / "cutouts" / f"{cutout_id}.png"
        ok, encoded = cv2.imencode(".png", balanced)
        if not ok:
            raise SyntheticVisibleRegionEmptyTableError(
                f"could not encode white-balanced cutout {cutout_id}"
            )
        digest = _write_bytes(path, encoded.tobytes())
        prepared[cutout_id] = {
            **dict(item),
            "rgba_path": path,
            "white_balance": profile,
            "white_balance_sha256": digest,
        }
    return prepared


def _candidate_plan(
    discovery: Mapping[str, Any],
    background: Mapping[str, Any],
    *,
    max_card_count: int,
    variants_per_candidate: int,
    scene_limit: int,
) -> list[tuple[Mapping[str, Any], int]]:
    source_group = background["source_group"]
    recording_id = str(source_group["id"])
    candidates = [
        candidate
        for candidate in discovery["candidates"]
        if isinstance(candidate, Mapping)
        and candidate.get("source_split") == "train"
        and candidate.get("recording_id") == recording_id
        and 1 <= int(candidate.get("card_count", 0)) <= max_card_count
    ]
    by_count: dict[int, list[Mapping[str, Any]]] = {}
    for candidate in candidates:
        by_count.setdefault(int(candidate["card_count"]), []).append(candidate)
    for items in by_count.values():
        items.sort(
            key=lambda item: (
                -float(item["selection_score"]),
                -int(item["reviewed_target_count"]),
                str(item["event_id"]),
            )
        )
    plan: list[tuple[Mapping[str, Any], int]] = []
    for variant_index in range(variants_per_candidate):
        for card_count in range(1, max_card_count + 1):
            for candidate in by_count.get(card_count, []):
                plan.append((candidate, variant_index))
    if scene_limit > 0:
        return plan[:scene_limit]
    return plan


def _render_sample_scene(
    repository: Path,
    output_root: Path,
    *,
    scene_id: str,
    image_id: int,
    seed: int,
    background: Mapping[str, Any],
    background_path: Path,
    background_digest: str,
    candidate: Mapping[str, Any],
    geometry_estimate: Mapping[str, Any],
    assets: Sequence[Mapping[str, Any]],
    lighting_profile: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    scene = cv2.imread(str(background_path), cv2.IMREAD_COLOR)
    if scene is None:
        raise SyntheticVisibleRegionEmptyTableError(
            f"could not decode reviewed empty background {background_path}"
        )
    height, width = scene.shape[:2]
    normalized_quads = _regularize_quadrilaterals(
        candidate["normalized_quadrilaterals"], geometry_estimate
    )
    placements: list[dict[str, Any]] = []
    dimensions = np.asarray([width, height], dtype=np.float32)
    for index, (quad, asset) in enumerate(zip(normalized_quads, assets, strict=True), start=1):
        record = asset["record"]
        rgba, alpha = _read_cutout(asset)
        rgba = _apply_card_lighting(rgba, alpha, lighting_profile)
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
                "white_balance": asset["white_balance"],
            }
        )
    full_masks = [placement["full_mask"] for placement in placements]
    visible_masks = [np.zeros((height, width), dtype=np.uint8) for _ in placements]
    higher = np.zeros((height, width), dtype=np.uint8)
    for index in range(len(placements) - 1, -1, -1):
        visible_masks[index] = np.where(
            (full_masks[index] > 0) & (higher == 0), 255, 0
        ).astype(np.uint8)
        visible_masks[index] = _remove_small_components(visible_masks[index], MIN_VISIBLE_PIXELS)
        higher = np.maximum(higher, full_masks[index])

    scene_lighting = _scene_lighting_parameters(seed)
    for full_mask in full_masks:
        _apply_shadow(scene, full_mask, float(scene_lighting["shadow_opacity"]))
    for placement in placements:
        _alpha_composite(scene, placement["warped_rgba"], placement["full_mask"])
    scene = _apply_scene_lighting(scene, scene_lighting)
    ok, encoded = cv2.imencode(
        ".jpg", scene, [cv2.IMWRITE_JPEG_QUALITY, int(scene_lighting["jpeg_quality"])]
    )
    if not ok:
        raise SyntheticVisibleRegionEmptyTableError(f"could not encode scene {scene_id}")
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
            output_root / "masks" / f"{scene_id}-instance-{placement['instance_index']:02d}.png"
        )
        ok, mask_bytes = cv2.imencode(".png", visible_mask)
        if not ok:
            raise SyntheticVisibleRegionEmptyTableError(f"could not encode mask {scene_id}")
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
            "white_balance": placement["white_balance"],
            "mask": {
                "path": _relative(mask_path, repository),
                "sha256": mask_digest,
                "bbox": bbox,
                "polygons": polygons,
            },
        }
        instances.append(instance)
        annotation_id = int(
            hashlib.sha256(f"{scene_id}:{placement['instance_index']}".encode()).hexdigest()[:12],
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
                "reference_revision_id": "synthetic-visible-region-empty-table-v1",
                "card_id": placement["cutout_id"],
                "source_video_sha256": str(background["source_group"]["source_sha256"]),
                "source_frame_sha256": image_digest,
                "target_geometry_sha256": _sha256_bytes(
                    canonical_json_bytes(placement["target_quad"].tolist())
                ),
                "split": "train",
                "card_side": placement["side"],
                "session_id": f"synthetic-empty-table-{background['background_id']}",
                "source_asset_id": placement["source_asset_id"],
                "video_id": scene_id,
                "table_setup": str(background["source_group"]["table_setup"]),
                "source_group_key": str(background["source_group"]["key"]),
            }
        )
    background_record = background
    receipt_core = {
        "schema_version": SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_CAMPAIGN_ID,
        "milestone": "M5-revision",
        "scene_id": scene_id,
        "seed": seed,
        "background": {
            "strategy": BACKGROUND_STRATEGY,
            "background_id": background_record["background_id"],
            "reviewed_decision": background_record["reviewed_decision"],
            "source_group": background_record["source_group"],
            "frame_identity": background_record["frame_identity"],
            "path": _relative(background_path, repository),
            "sha256": background_digest,
        },
        "geometry_reference": {
            "candidate_id": candidate["candidate_id"],
            "event_id": candidate["event_id"],
            "recording_id": candidate["recording_id"],
            "card_count": candidate["card_count"],
            "normalized_quadrilaterals": normalized_quads,
            "selection_score": candidate["selection_score"],
            "table_geometry_estimate": geometry_estimate,
        },
        "lighting_reference": dict(lighting_profile),
        "scene_lighting": scene_lighting,
        "placements": instances,
        "omitted_instances": omitted,
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
                {str(background_record["source_group"]["key"])}
                | {str(item["source_group"]["key"]) for item in instances}
                | {str(candidate["source_group_key"])}
            ),
        },
        "renderer": {
            "opencv_version": cv2.__version__,
            "numpy_version": np.__version__,
            "python_version": platform.python_version(),
            "mask_policy": "opaque-card-z-order-and-frame-clipping-v1",
            "card_lighting_scope": "shared-profile-per-scene-v1",
        },
    }
    receipt = {
        **receipt_core,
        "receipt_digest": _sha256_bytes(canonical_json_bytes(receipt_core)),
    }
    receipt_path = output_root / "receipts" / f"{scene_id}.json"
    _write_json(receipt_path, receipt)
    summary = {
        "scene_id": scene_id,
        "card_count": int(candidate["card_count"]),
        "recording_id": str(candidate["recording_id"]),
        "table_setup": str(background_record["source_group"]["table_setup"]),
        "background": {
            "background_id": background_record["background_id"],
            "strategy": BACKGROUND_STRATEGY,
            "reviewed_decision": background_record["reviewed_decision"],
            "path": _relative(background_path, repository),
            "sha256": background_digest,
        },
        "lighting_reference": {
            "candidate_id": lighting_profile["reference_candidate_id"],
            "event_id": lighting_profile["reference_event_id"],
            "scope": lighting_profile["scope"],
        },
        "scene_lighting": scene_lighting,
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
        "item_id": background_record["background_id"],
        "reference_revision_id": "synthetic-visible-region-empty-table-v1",
        "source_video_sha256": str(background_record["source_group"]["source_sha256"]),
        "source_frame_sha256": image_digest,
        "split": "train",
        "trainer_partition": "train",
        "session_id": f"synthetic-empty-table-{background_record['background_id']}",
        "source_asset_id": background_record["background_id"],
        "video_id": scene_id,
        "table_setup": str(background_record["source_group"]["table_setup"]),
        "source_group_key": str(background_record["source_group"]["key"]),
        "dataset_origin": "synthetic",
        "background_strategy": BACKGROUND_STRATEGY,
    }
    return summary, image, annotations


def build_synthetic_visible_region_empty_table_samples(
    repository_root: str | Path,
    *,
    source_manifest_path: str | Path = SOURCE_MANIFEST_DEFAULT,
    m1_manifest_path: str | Path = M1_MANIFEST_DEFAULT,
    materialization_directory: str | Path = MATERIALIZATION_DEFAULT,
    output_directory: str | Path = OUTPUT_DIRECTORY_DEFAULT,
    scene_limit: int = SCENE_LIMIT_DEFAULT,
    variants_per_candidate: int = 1,
    max_card_count: int = MAX_CARD_COUNT_DEFAULT,
    seed_start: int = 7001,
) -> dict[str, Any]:
    """Render bounded samples on explicit empty tables; zero scene limit means all samples."""

    if scene_limit < 0:
        raise SyntheticVisibleRegionEmptyTableError("scene_limit must be zero or positive")
    if variants_per_candidate < 1:
        raise SyntheticVisibleRegionEmptyTableError("variants_per_candidate must be positive")
    if not 1 <= max_card_count <= 4:
        raise SyntheticVisibleRegionEmptyTableError("max_card_count must be between 1 and 4")
    repository = Path(repository_root).expanduser().resolve()
    discovery = build_synthetic_visible_region_recording_discovery(
        repository,
        source_manifest_path=source_manifest_path,
        max_card_count=max_card_count,
    )
    m1_path = _resolve(repository, m1_manifest_path)
    m1 = _read_json(m1_path, "M1 input manifest")
    try:
        validate_synthetic_visible_region_inputs(m1)
    except ValueError as error:
        raise SyntheticVisibleRegionEmptyTableError(
            f"M1 input manifest is invalid: {error}"
        ) from error
    backgrounds = _empty_backgrounds(m1)
    if not backgrounds:
        raise SyntheticVisibleRegionEmptyTableError(
            "no accepted full-frame-reviewed training empty table is available"
        )
    materialization_root = _resolve(repository, materialization_directory)
    frame_paths = _materialization_frame_paths(repository, materialization_root)
    usable = _usable_cutouts(repository, m1)
    output_root = _resolve(repository, output_directory)
    output_root.mkdir(parents=True, exist_ok=True)
    prepared = _prepare_white_balanced_cutouts(repository, output_root, usable)
    table_references = _select_table_geometry_references(discovery, 3)
    table_geometry = {
        table_setup: _estimate_table_geometry(table_setup, references)
        for table_setup, references in table_references.items()
    }

    plans: list[tuple[dict[str, Any], Mapping[str, Any], int]] = []
    for background_item in backgrounds:
        background = background_item["record"]
        for candidate, variant_index in _candidate_plan(
            discovery,
            background,
            max_card_count=max_card_count,
            variants_per_candidate=variants_per_candidate,
            scene_limit=0,
        ):
            plans.append((background, candidate, variant_index))
    if scene_limit > 0:
        # Keep the sample balanced across the available 1/2/3/4-card buckets.
        grouped: dict[int, list[tuple[dict[str, Any], Mapping[str, Any], int]]] = {}
        for plan in plans:
            grouped.setdefault(int(plan[1]["card_count"]), []).append(plan)
        balanced: list[tuple[dict[str, Any], Mapping[str, Any], int]] = []
        while len(balanced) < scene_limit and any(grouped.values()):
            for card_count in sorted(grouped):
                if grouped[card_count] and len(balanced) < scene_limit:
                    balanced.append(grouped[card_count].pop(0))
        plans = balanced
    if not plans:
        raise SyntheticVisibleRegionEmptyTableError(
            "reviewed empty tables have no matching train geometry candidates"
        )

    scene_summaries: list[dict[str, Any]] = []
    coco_images: list[dict[str, Any]] = []
    coco_annotations: list[dict[str, Any]] = []
    for index, (background, candidate, variant_index) in enumerate(plans):
        background_path = _resolve(repository, background["files"]["image"]["path"])
        background_digest = str(background["files"]["image"]["sha256"])
        if not background_path.is_file() or _sha256_file(background_path) != background_digest:
            raise SyntheticVisibleRegionEmptyTableError(
                f"reviewed empty background is missing or changed: {background['background_id']}"
            )
        frame_data = frame_paths.get(str(candidate["event_id"]))
        if frame_data is None:
            raise SyntheticVisibleRegionEmptyTableError(
                f"lighting reference frame is missing: {candidate['event_id']}"
            )
        frame_path, frame_digest = frame_data
        reference_image = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        if reference_image is None:
            raise SyntheticVisibleRegionEmptyTableError(
                f"lighting reference frame is unreadable: {frame_path}"
            )
        lighting = _lighting_profile(reference_image, candidate, frame_path, frame_digest)
        geometry_estimate = table_geometry[str(background["source_group"]["table_setup"])]
        asset_items = _selected_assets(
            list(prepared.values()),
            str(candidate["recording_id"]),
            int(candidate["card_count"]),
            variant_index,
        )
        scene_id = (
            f"scene-{index:03d}-{background['background_id']}-"
            f"{candidate['card_count']}cards-v{variant_index:02d}"
        )
        summary, image, annotations = _render_sample_scene(
            repository,
            output_root,
            scene_id=scene_id,
            image_id=index + 1,
            seed=seed_start + index,
            background=background,
            background_path=background_path,
            background_digest=background_digest,
            candidate=candidate,
            geometry_estimate=geometry_estimate,
            assets=asset_items,
            lighting_profile=lighting,
        )
        scene_summaries.append(summary)
        coco_images.append(image)
        coco_annotations.extend(annotations)

    coco = {
        "info": {
            "description": "Bounded synthetic visible-card samples on reviewed empty tables",
            "version": SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_SCHEMA_VERSION,
            "coco_version": "coco-2017",
            "campaign_id": SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_CAMPAIGN_ID,
            "trainer_partition": "train",
        },
        "licenses": [],
        "images": coco_images,
        "annotations": coco_annotations,
        "categories": [{"id": 1, "name": "visible_card", "supercategory": "card"}],
    }
    validate_rfdetr_coco_annotations(coco)
    coco_path = output_root / "_annotations.coco.json"
    coco_digest = _write_json(coco_path, coco)
    core = {
        "schema_version": SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_EMPTY_TABLE_CAMPAIGN_ID,
        "milestone": "M5-revision",
        "freeze_state": "sample_ready_for_operator_review",
        "source_manifest": {
            "path": _relative(_resolve(repository, source_manifest_path), repository),
            "sha256": _sha256_file(_resolve(repository, source_manifest_path)),
            "manifest_digest": discovery["source_manifest"]["manifest_digest"],
        },
        "m1_manifest": {
            "path": _relative(m1_path, repository),
            "sha256": _sha256_file(m1_path),
            "manifest_digest": m1["manifest_digest"],
        },
        "policy": {
            "background_strategy": BACKGROUND_STRATEGY,
            "empty_backgrounds_only": True,
            "white_balance_method": WHITE_BALANCE_METHOD,
            "lighting_profile_method": LIGHTING_PROFILE_METHOD,
            "lighting_profile_scope": "all_cards_in_scene",
            "scene_lighting_scope": "complete_scene",
            "max_card_count": max_card_count,
            "variants_per_candidate": variants_per_candidate,
            "scene_limit": scene_limit,
            "seed_start": seed_start,
            "table_geometry_reference_frame_count": 3,
            "table_geometry_estimates": table_geometry,
        },
        "inventory": {
            "empty_background_count": len(backgrounds),
            "white_balanced_cutout_count": len(prepared),
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
            "only explicitly reviewed empty training tables can render scenes",
            "card-bearing frames are lighting and geometry references only",
            "no full training pool was generated by this bounded sample command",
        ],
    }
    return {**core, "manifest_digest": _sha256_bytes(canonical_json_bytes(core))}


def write_synthetic_visible_region_empty_table_manifest(
    path: str | Path, manifest: Mapping[str, Any]
) -> Path:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(manifest) + b"\n")
    return destination


def render_synthetic_visible_region_empty_table_human(manifest: Mapping[str, Any]) -> str:
    inventory = manifest["inventory"]
    lines = [
        "Epic 0070 empty-table synthetic sample set",
        f"state: {manifest['freeze_state']}",
        f"reviewed empty backgrounds: {inventory['empty_background_count']}",
        f"white-balanced cutouts: {inventory['white_balanced_cutout_count']}",
        f"sample scenes: {inventory['synthesized_scene_count']}",
        f"card-count distribution: {inventory['synthesized_scene_counts_by_card_count']}",
        f"COCO: {manifest['outputs']['coco']['path']}",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "M1_MANIFEST_DEFAULT",
    "MANIFEST_DEFAULT",
    "MATERIALIZATION_DEFAULT",
    "OUTPUT_DIRECTORY_DEFAULT",
    "SCENE_LIMIT_DEFAULT",
    "SyntheticVisibleRegionEmptyTableError",
    "_apply_scene_lighting",
    "_scene_lighting_parameters",
    "_white_balance_cutout",
    "build_synthetic_visible_region_empty_table_samples",
    "render_synthetic_visible_region_empty_table_human",
    "write_synthetic_visible_region_empty_table_manifest",
]
