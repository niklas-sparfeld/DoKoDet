"""Render deterministic synthetic visible-card scenes for epic 0070 M2.

The renderer uses only training-only assets from the M1 manifest.  It keeps the missing
face-down input explicit: face-down and mixed-side buckets are omitted, never simulated.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .reviewed_rfdetr_detector_campaign import canonical_json_bytes
from .rfdetr_segmentation_materialization import validate_rfdetr_coco_annotations
from .synthetic_visible_region_campaign import validate_synthetic_visible_region_manifest
from .synthetic_visible_region_materialization import (
    M0_MANIFEST_DEFAULT,
    validate_synthetic_visible_region_inputs,
)
from .synthetic_visible_region_materialization import (
    MANIFEST_DEFAULT as M1_MANIFEST_DEFAULT,
)

SYNTHETIC_VISIBLE_REGION_SCENES_SCHEMA_VERSION = "synthetic-visible-region-scenes/v1"
SYNTHETIC_VISIBLE_REGION_SCENES_CAMPAIGN_ID = "0070-m2-synthetic-visible-region-scenes"
OUTPUT_DIRECTORY_DEFAULT = ".runtime/synthetic-visible-region-0070-m2"
SCENE_COUNT_DEFAULT = 8
TARGET_CATEGORY = {"id": 1, "name": "visible_card", "supercategory": "card"}
CANONICAL_WIDTH = 640
CANONICAL_HEIGHT = 960
MIN_VISIBLE_PIXELS = 64
AVAILABLE_BUCKETS = (
    "fully_visible_card",
    "separated_cards",
    "overlapping_cards_shallow",
    "overlapping_cards_medium",
    "overlapping_cards_heavy",
    "frame_boundary_clipping",
    "blur_glare_dark_compressed",
    "reviewed_empty_background",
)
OMITTED_BUCKETS = ("face_down_cards", "mixed_card_sides")
_SHA256_LENGTH = 64


class SyntheticVisibleRegionRenderingError(ValueError):
    """Raised when deterministic synthetic rendering cannot produce a safe receipt."""


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


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyntheticVisibleRegionRenderingError(
            f"could not read {field} {path}: {error}"
        ) from error
    if not isinstance(value, Mapping):
        raise SyntheticVisibleRegionRenderingError(f"{field} must be a JSON object")
    return dict(value)


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        raise SyntheticVisibleRegionRenderingError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise SyntheticVisibleRegionRenderingError(f"{field} must be a SHA-256 digest") from error
    return value


def _round(value: float) -> float:
    return round(float(value), 6)


def _write_bytes(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return _sha256_bytes(payload)


def _write_json(path: Path, value: Mapping[str, Any]) -> str:
    return _write_bytes(path, canonical_json_bytes(value) + b"\n")


def _resolve(repository: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else repository / path


def _load_image(path: Path, *, flags: int = cv2.IMREAD_COLOR) -> np.ndarray:
    image = cv2.imread(str(path), flags)
    if image is None:
        raise SyntheticVisibleRegionRenderingError(f"could not decode image {path}")
    return image


def _quad_points(value: Sequence[Mapping[str, Any]] | Sequence[Sequence[float]]) -> np.ndarray:
    points: list[list[float]] = []
    for point in value:
        if isinstance(point, Mapping):
            points.append([float(point["x"]), float(point["y"])])
        else:
            points.append([float(point[0]), float(point[1])])
    if len(points) != 4:
        raise SyntheticVisibleRegionRenderingError("a card placement must have four corners")
    return np.asarray(points, dtype=np.float32)


def _quad_to_records(quad: np.ndarray) -> list[dict[str, float]]:
    return [{"x": _round(point[0]), "y": _round(point[1])} for point in quad]


def _center(quad: np.ndarray) -> np.ndarray:
    return np.mean(quad, axis=0)


def _transform_quad(
    quad: np.ndarray,
    *,
    output_width: int,
    output_height: int,
    scale: float = 1.0,
    rotation_degrees: float = 0.0,
    center_normalized: tuple[float, float] | None = None,
    offset_normalized: tuple[float, float] = (0.0, 0.0),
) -> np.ndarray:
    source_center = _center(quad)
    target_center = (
        np.asarray(center_normalized, dtype=np.float32)
        * np.asarray([output_width, output_height], dtype=np.float32)
        if center_normalized is not None
        else source_center
    )
    target_center = target_center + np.asarray(
        [offset_normalized[0] * output_width, offset_normalized[1] * output_height],
        dtype=np.float32,
    )
    radians = math.radians(rotation_degrees)
    rotation = np.asarray(
        [[math.cos(radians), -math.sin(radians)], [math.sin(radians), math.cos(radians)]],
        dtype=np.float32,
    )
    return (quad - source_center) @ rotation.T * scale + target_center


def _polygon_area(points: Sequence[tuple[float, float]]) -> float:
    return abs(
        sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )
        / 2.0
    )


def _mask_polygons(mask: np.ndarray) -> list[list[float]]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    polygons: list[list[float]] = []
    for contour in contours:
        approximation = cv2.approxPolyDP(contour, 0.0, True).reshape(-1, 2)
        if len(approximation) < 3:
            approximation = contour.reshape(-1, 2)
        if len(approximation) < 3:
            continue
        # Contour coordinates refer to pixel centers.  Shift to pixel boundaries so the
        # COCO box is exactly the integer mask extent, including the last pixel.
        polygon: list[float] = []
        for x, y in approximation:
            polygon.extend([_round(float(x) + 0.5), _round(float(y) + 0.5)])
        if _polygon_area(list(zip(polygon[::2], polygon[1::2], strict=True))) > 0:
            polygons.append(polygon)
    polygons.sort(key=lambda item: (-len(item), item))
    return polygons


def _mask_bbox(mask: np.ndarray) -> list[int]:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        raise SyntheticVisibleRegionRenderingError("visible mask is empty")
    x_min, x_max = int(xs.min()), int(xs.max())
    y_min, y_max = int(ys.min()), int(ys.max())
    return [x_min, y_min, x_max - x_min + 1, y_max - y_min + 1]


def _source_paths(
    repository: Path, manifest: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    cutouts = [dict(item) for item in manifest.get("cutouts", []) if isinstance(item, Mapping)]
    usable: list[dict[str, Any]] = []
    for cutout in cutouts:
        decision = cutout.get("reviewed_decision", {})
        source_group = cutout.get("source_group", {})
        if not isinstance(decision, Mapping) or not isinstance(source_group, Mapping):
            continue
        if source_group.get("split") != "train":
            continue
        if decision.get("card_side") not in {"face_up", "unknown"}:
            continue
        path_data = cutout.get("files", {}).get("rgba")
        alpha_data = cutout.get("files", {}).get("alpha")
        if not isinstance(path_data, Mapping) or not isinstance(alpha_data, Mapping):
            continue
        rgba_path = _resolve(repository, str(path_data["path"]))
        alpha_path = _resolve(repository, str(alpha_data["path"]))
        if not rgba_path.is_file() or not alpha_path.is_file():
            raise SyntheticVisibleRegionRenderingError(
                f"M1 cutout files are missing for {cutout.get('cutout_id')}"
            )
        if _sha256_file(rgba_path) != path_data.get("sha256"):
            raise SyntheticVisibleRegionRenderingError(
                f"M1 cutout RGBA digest differs for {cutout.get('cutout_id')}"
            )
        if _sha256_file(alpha_path) != alpha_data.get("sha256"):
            raise SyntheticVisibleRegionRenderingError(
                f"M1 cutout alpha digest differs for {cutout.get('cutout_id')}"
            )
        usable.append({"record": cutout, "rgba_path": rgba_path, "alpha_path": alpha_path})
    if not usable:
        raise SyntheticVisibleRegionRenderingError("M1 has no usable face-up or unknown cutouts")
    backgrounds: list[dict[str, Any]] = []
    for background in manifest.get("backgrounds", []):
        if not isinstance(background, Mapping):
            continue
        image_data = background.get("files", {}).get("image")
        if not isinstance(image_data, Mapping):
            continue
        path = _resolve(repository, str(image_data["path"]))
        if not path.is_file():
            raise SyntheticVisibleRegionRenderingError(
                f"M1 background file is missing for {background.get('background_id')}"
            )
        if _sha256_file(path) != image_data.get("sha256"):
            raise SyntheticVisibleRegionRenderingError(
                f"M1 background digest differs for {background.get('background_id')}"
            )
        backgrounds.append({"record": dict(background), "path": path})
    if not backgrounds:
        raise SyntheticVisibleRegionRenderingError("M1 has no reviewed empty background")
    by_id = {item["record"]["cutout_id"]: item for item in usable}
    return usable, by_id, backgrounds


def _geometry_examples(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    examples = manifest.get("perspective_library", {}).get("examples", [])
    result: list[dict[str, Any]] = []
    for example in examples:
        if not isinstance(example, Mapping):
            continue
        width = float(example.get("source_width", 0))
        height = float(example.get("source_height", 0))
        raw_quad = example.get("source_quadrilateral")
        if width <= 0 or height <= 0 or not isinstance(raw_quad, list):
            continue
        quad = _quad_points(raw_quad)
        result.append(
            {
                "cutout_id": str(example["cutout_id"]),
                "table_setup": str(example.get("table_setup", "unknown")),
                "normalized_quad": quad / np.asarray([width, height], dtype=np.float32),
            }
        )
    if not result:
        raise SyntheticVisibleRegionRenderingError("M1 has no perspective examples")
    return result


def _calibration_geometry_examples(
    manifest: Mapping[str, Any], background: Mapping[str, Any]
) -> list[dict[str, Any]]:
    library = manifest.get("perspective_library", {})
    raw_examples = library.get("calibration_examples", [])
    if not isinstance(raw_examples, list):
        return []
    background_group = background.get("source_group", {})
    background_recording = str(background_group.get("id", ""))
    background_setup = str(background_group.get("table_setup", ""))
    matching = [
        item
        for item in raw_examples
        if isinstance(item, Mapping)
        and item.get("recording_id") == background_recording
        and item.get("table_setup") == background_setup
    ]
    if not matching:
        matching = [
            item
            for item in raw_examples
            if isinstance(item, Mapping) and item.get("table_setup") == background_setup
        ]
    result: list[dict[str, Any]] = []
    for item in matching:
        quads = item.get("normalized_quadrilaterals")
        if not isinstance(quads, list) or not quads or len(quads) > 2:
            continue
        try:
            parsed = [_quad_points(quad) for quad in quads]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        result.append(
            {
                "example_id": str(item.get("example_id", "unknown")),
                "recording_id": str(item.get("recording_id", "")),
                "event_id": str(item.get("event_id", "")),
                "table_setup": str(item.get("table_setup", "")),
                "normalized_quads": parsed,
                "card_count": len(parsed),
                "selection": str(item.get("selection", "unknown")),
            }
        )
    if result:
        return result
    return []


def _read_cutout(asset: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    rgba = _load_image(asset["rgba_path"], flags=cv2.IMREAD_UNCHANGED)
    alpha = _load_image(asset["alpha_path"], flags=cv2.IMREAD_GRAYSCALE)
    if rgba.ndim != 3 or rgba.shape[2] != 4 or alpha.shape != rgba.shape[:2]:
        raise SyntheticVisibleRegionRenderingError("M1 cutout dimensions or channels are invalid")
    return rgba, np.where(alpha > 0, 255, 0).astype(np.uint8)


def _warp_cutout(
    rgba: np.ndarray,
    alpha: np.ndarray,
    destination_quad: np.ndarray,
    output_width: int,
    output_height: int,
) -> tuple[np.ndarray, np.ndarray]:
    source_quad = np.asarray(
        [
            [0, 0],
            [CANONICAL_WIDTH - 1, 0],
            [CANONICAL_WIDTH - 1, CANONICAL_HEIGHT - 1],
            [0, CANONICAL_HEIGHT - 1],
        ],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(source_quad, destination_quad.astype(np.float32))
    warped = cv2.warpPerspective(
        rgba, transform, (output_width, output_height), flags=cv2.INTER_CUBIC
    )
    warped_alpha = cv2.warpPerspective(
        alpha, transform, (output_width, output_height), flags=cv2.INTER_NEAREST
    )
    return warped, np.where(warped_alpha > 0, 255, 0).astype(np.uint8)


def _remove_small_components(mask: np.ndarray, minimum_pixels: int) -> np.ndarray:
    components, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    cleaned = np.zeros_like(mask)
    for component in range(1, components):
        if int(stats[component, cv2.CC_STAT_AREA]) >= minimum_pixels:
            cleaned[labels == component] = 255
    return cleaned


def _alpha_composite(background: np.ndarray, foreground: np.ndarray, alpha: np.ndarray) -> None:
    weight = alpha.astype(np.float32) / 255.0
    for channel in range(3):
        background[:, :, channel] = np.clip(
            background[:, :, channel].astype(np.float32) * (1.0 - weight)
            + foreground[:, :, channel].astype(np.float32) * weight,
            0,
            255,
        ).astype(np.uint8)


def _apply_shadow(scene: np.ndarray, mask: np.ndarray, opacity: float) -> None:
    shadow = cv2.GaussianBlur(mask, (0, 0), 4.0)
    translation = np.float32([[1, 0, 4], [0, 1, 5]])
    shadow = cv2.warpAffine(shadow, translation, (scene.shape[1], scene.shape[0]))
    weight = shadow.astype(np.float32) / 255.0 * opacity
    scene[:] = np.clip(
        scene.astype(np.float32) * (1.0 - weight[:, :, None]), 0, 255
    ).astype(np.uint8)


def _photometric(
    scene: np.ndarray, rng: np.random.Generator, enabled: bool
) -> dict[str, float | int]:
    if not enabled:
        return {
            "brightness_delta": 0.0,
            "contrast": 1.0,
            "saturation": 1.0,
            "blur_sigma": 0.0,
            "glare_opacity": 0.0,
            "jpeg_quality": 95,
        }
    brightness = float(rng.uniform(-0.12, 0.12))
    contrast = float(rng.uniform(0.85, 1.15))
    saturation = float(rng.uniform(0.85, 1.15))
    blur_sigma = float(rng.uniform(0.0, 1.2))
    glare_opacity = float(rng.uniform(0.0, 0.12))
    jpeg_quality = int(rng.integers(70, 96))
    adjusted = scene.astype(np.float32) * contrast + brightness * 255.0
    adjusted = np.clip(adjusted, 0, 255).astype(np.uint8)
    hsv = cv2.cvtColor(adjusted, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation, 0, 255)
    scene[:] = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    if glare_opacity > 0:
        overlay = np.zeros_like(scene)
        center = (int(scene.shape[1] * 0.72), int(scene.shape[0] * 0.28))
        axes = (max(1, int(scene.shape[1] * 0.22)), max(1, int(scene.shape[0] * 0.10)))
        cv2.ellipse(overlay, center, axes, -12, 0, 360, (255, 255, 255), -1)
        overlay = cv2.GaussianBlur(overlay, (0, 0), max(1.0, scene.shape[0] * 0.025))
        scene[:] = np.clip(
            scene.astype(np.float32) * (1.0 - glare_opacity)
            + overlay.astype(np.float32) * glare_opacity,
            0,
            255,
        ).astype(np.uint8)
    if blur_sigma > 0.01:
        scene[:] = cv2.GaussianBlur(scene, (0, 0), blur_sigma)
    return {
        "brightness_delta": _round(brightness),
        "contrast": _round(contrast),
        "saturation": _round(saturation),
        "blur_sigma": _round(blur_sigma),
        "glare_opacity": _round(glare_opacity),
        "jpeg_quality": jpeg_quality,
    }


def _scene_placements(
    bucket: str,
    *,
    base_quad: np.ndarray | None,
    template_quads: Sequence[np.ndarray] = (),
    output_width: int,
    output_height: int,
    rng: np.random.Generator,
    card_count: int,
) -> list[dict[str, Any]]:
    if bucket == "reviewed_empty_background":
        return []
    calibrated = [quad.copy() for quad in template_quads]
    if calibrated:
        if bucket in {
            "fully_visible_card",
            "blur_glare_dark_compressed",
            "frame_boundary_clipping",
        }:
            targets = calibrated[:1]
        elif bucket == "separated_cards" or bucket.startswith("overlapping_cards_"):
            targets = calibrated[:2]
            if len(targets) == 1:
                targets.append(
                    _transform_quad(
                        targets[0],
                        output_width=output_width,
                        output_height=output_height,
                        center_normalized=(
                            min(0.86, float(np.mean(targets[0][:, 0])) / output_width + 0.20),
                            float(np.mean(targets[0][:, 1])) / output_height,
                        ),
                    )
                )
        else:
            raise SyntheticVisibleRegionRenderingError(f"unsupported scene bucket: {bucket}")
        if bucket.startswith("overlapping_cards_") and len(targets) >= 2:
            depth = {
                "overlapping_cards_shallow": 0.20,
                "overlapping_cards_medium": 0.42,
                "overlapping_cards_heavy": 0.68,
            }[bucket]
            first_center = _center(targets[0])
            first_edge = targets[0][1] - targets[0][0]
            edge_length = float(np.linalg.norm(first_edge))
            if edge_length <= 0.0:
                raise SyntheticVisibleRegionRenderingError("calibration card edge is empty")
            target_center = first_center + first_edge / edge_length * edge_length * (1.0 - depth)
            targets[1] = _transform_quad(
                targets[1],
                output_width=output_width,
                output_height=output_height,
                center_normalized=(
                    float(target_center[0]) / output_width,
                    float(target_center[1]) / output_height,
                ),
            )
        common_offset = (
            float(rng.uniform(-0.008, 0.008)),
            float(rng.uniform(-0.008, 0.008)),
        )
        placements: list[dict[str, Any]] = []
        for index, target in enumerate(targets[:card_count], start=1):
            rotation = float(rng.uniform(-2.0, 2.0))
            scale = float(rng.uniform(0.995, 1.005))
            if bucket == "frame_boundary_clipping":
                quad = _transform_quad(
                    target,
                    output_width=output_width,
                    output_height=output_height,
                    scale=scale,
                    rotation_degrees=rotation,
                    center_normalized=(0.03, 0.04),
                )
            else:
                quad = _transform_quad(
                    target,
                    output_width=output_width,
                    output_height=output_height,
                    scale=scale,
                    rotation_degrees=rotation,
                    offset_normalized=common_offset,
                )
            center = _center(quad) / np.asarray([output_width, output_height], dtype=np.float32)
            placements.append(
                {
                    "z_order": index,
                    "target_quad": quad,
                    "placement": {
                        "center_normalized": [_round(center[0]), _round(center[1])],
                        "scale": _round(scale),
                        "rotation_degrees": _round(rotation),
                    },
                }
            )
        return placements

    if base_quad is None:
        raise SyntheticVisibleRegionRenderingError("scene has no measured geometry")
    if bucket == "fully_visible_card":
        centers = [(0.50, 0.52)]
        scales = [1.0]
    elif bucket == "separated_cards":
        centers = [(0.29, 0.50), (0.71, 0.50)]
        scales = [0.95, 0.95]
    elif bucket == "frame_boundary_clipping":
        centers = [(0.03, 0.04)]
        scales = [1.0]
    elif bucket.startswith("overlapping_cards_"):
        depth = {
            "overlapping_cards_shallow": 0.20,
            "overlapping_cards_medium": 0.42,
            "overlapping_cards_heavy": 0.68,
        }[bucket]
        edge = float(np.linalg.norm(base_quad[1] - base_quad[0])) / output_width
        centers = [(0.42, 0.52), (0.42 + edge * (1.0 - depth), 0.52)]
        scales = [1.0, 1.0]
    elif bucket == "blur_glare_dark_compressed":
        centers = [(0.50, 0.52)]
        scales = [1.0]
    else:
        raise SyntheticVisibleRegionRenderingError(f"unsupported scene bucket: {bucket}")
    placements: list[dict[str, Any]] = []
    for index, center in enumerate(centers[:card_count], start=1):
        jitter_x = float(rng.uniform(-0.015, 0.015))
        jitter_y = float(rng.uniform(-0.015, 0.015))
        rotation = float(rng.uniform(-4.0, 4.0))
        scale = scales[index - 1] * float(rng.uniform(0.99, 1.01))
        quad = _transform_quad(
            base_quad,
            output_width=output_width,
            output_height=output_height,
            scale=scale,
            rotation_degrees=rotation,
            center_normalized=center,
            offset_normalized=(jitter_x, jitter_y),
        )
        placements.append(
            {
                "z_order": index,
                "target_quad": quad,
                "placement": {
                    "center_normalized": [
                        _round(center[0] + jitter_x),
                        _round(center[1] + jitter_y),
                    ],
                    "scale": _round(scale),
                    "rotation_degrees": _round(rotation),
                },
            }
        )
    return placements


def _occlusion_ratio(full_mask: np.ndarray, visible_mask: np.ndarray) -> float:
    total = int(np.count_nonzero(full_mask))
    return _round(0.0 if total == 0 else 1.0 - int(np.count_nonzero(visible_mask)) / total)


def _coco_annotation(
    annotation_id: int,
    image_id: int,
    scene_id: str,
    scene_digest: str,
    placement: Mapping[str, Any],
    polygons: list[list[float]],
    bbox: list[int],
    area: float,
    side: str,
    background: Mapping[str, Any],
) -> dict[str, Any]:
    source_group = background["source_group"]
    source_group_key = str(source_group["key"])
    return {
        "id": annotation_id,
        "image_id": image_id,
        "category_id": 1,
        "bbox": bbox,
        "area": _round(area),
        "segmentation": polygons,
        "iscrowd": 0,
        "target_state": "synthetic_visible_region",
        "recording_id": "synthetic-visible-region-0070",
        "event_id": scene_id,
        "item_id": str(placement["cutout_id"]),
        "reference_revision_id": "synthetic-visible-region-recipe-v1",
        "card_id": str(placement["cutout_id"]),
        "source_video_sha256": str(source_group["source_sha256"]),
        "source_frame_sha256": scene_digest,
        "target_geometry_sha256": _sha256_bytes(
            canonical_json_bytes(placement["target_quadrilateral"])
        ),
        "split": "train",
        "card_side": side,
        "session_id": "synthetic-visible-region-0070",
        "source_asset_id": str(placement["source_asset_id"]),
        "video_id": "synthetic-visible-region-0070",
        "table_setup": str(source_group["table_setup"]),
        "source_group_key": source_group_key,
    }


def _coco_image(
    image_id: int,
    scene_id: str,
    image_path: str,
    width: int,
    height: int,
    image_digest: str,
    background: Mapping[str, Any],
) -> dict[str, Any]:
    source_group = background["source_group"]
    return {
        "id": image_id,
        "file_name": image_path,
        "width": width,
        "height": height,
        "sha256": image_digest,
        "recording_id": "synthetic-visible-region-0070",
        "event_id": scene_id,
        "item_id": str(background["background_id"]),
        "reference_revision_id": "synthetic-visible-region-recipe-v1",
        "source_video_sha256": str(source_group["source_sha256"]),
        "source_frame_sha256": image_digest,
        "split": "train",
        "trainer_partition": "train",
        "session_id": "synthetic-visible-region-0070",
        "source_asset_id": str(background["background_id"]),
        "video_id": "synthetic-visible-region-0070",
        "table_setup": str(source_group["table_setup"]),
        "source_group_key": str(source_group["key"]),
    }


def _validate_visible_masks(visible_masks: Sequence[np.ndarray]) -> None:
    occupied = np.zeros_like(visible_masks[0]) if visible_masks else None
    if occupied is None:
        return
    for mask in visible_masks:
        if np.any((occupied > 0) & (mask > 0)):
            raise SyntheticVisibleRegionRenderingError("visible instance masks overlap")
        occupied = np.maximum(occupied, mask)


def _load_recipe(repository: Path, m0_manifest_path: Path) -> tuple[dict[str, Any], str]:
    m0 = _read_json(m0_manifest_path, "M0 manifest")
    validate_synthetic_visible_region_manifest(m0)
    recipe = m0.get("recipe")
    if not isinstance(recipe, Mapping):
        raise SyntheticVisibleRegionRenderingError("M0 recipe is missing")
    recipe_copy = json.loads(canonical_json_bytes(recipe).decode("utf-8"))
    return recipe_copy, _sha256_bytes(canonical_json_bytes(recipe_copy))


def _scene_bucket_list(recipe: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    requested = recipe.get("scene_buckets", [])
    if not isinstance(requested, list):
        raise SyntheticVisibleRegionRenderingError("M0 recipe scene_buckets must be a list")
    available = [bucket for bucket in AVAILABLE_BUCKETS if bucket in requested]
    omitted = [bucket for bucket in OMITTED_BUCKETS if bucket in requested]
    if not available:
        raise SyntheticVisibleRegionRenderingError("M0 recipe has no renderable scene bucket")
    return available, omitted


def _render_scene(
    repository: Path,
    output_root: Path,
    *,
    scene_id: str,
    bucket: str,
    seed: int,
    background: Mapping[str, Any],
    background_path: Path,
    card_assets: Sequence[Mapping[str, Any]],
    geometry: Mapping[str, Any],
    recipe_digest: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    rng = np.random.default_rng(seed)
    scene = _load_image(background_path, flags=cv2.IMREAD_COLOR)
    output_height, output_width = scene.shape[:2]
    dimensions = np.asarray([output_width, output_height], dtype=np.float32)
    base_quad = None
    if "normalized_quad" in geometry:
        base_quad = np.asarray(geometry["normalized_quad"], dtype=np.float32) * dimensions
    template_quads = [
        np.asarray(item, dtype=np.float32) * dimensions
        for item in geometry.get("normalized_quads", [])
    ]
    count = (
        0
        if bucket == "reviewed_empty_background"
        else (2 if bucket != "fully_visible_card" else 1)
    )
    if bucket == "frame_boundary_clipping":
        count = 1
    if bucket == "blur_glare_dark_compressed":
        count = 1
    placements = _scene_placements(
        bucket,
        base_quad=base_quad,
        template_quads=template_quads,
        output_width=output_width,
        output_height=output_height,
        rng=rng,
        card_count=count,
    )
    selected = list(card_assets[: len(placements)])
    for index, placement in enumerate(placements):
        asset = selected[index]
        record = asset["record"]
        rgba, alpha = _read_cutout(asset)
        warped, warped_alpha = _warp_cutout(
            rgba, alpha, placement["target_quad"], output_width, output_height
        )
        warped_alpha = _remove_small_components(warped_alpha, MIN_VISIBLE_PIXELS)
        placement.update(
            {
                "cutout_id": str(record["cutout_id"]),
                "source_asset_id": str(record["source_asset_id"]),
                "side": str(record["reviewed_decision"]["card_side"]),
                "source_group": dict(record["source_group"]),
                "full_mask": warped_alpha,
                "warped_rgba": warped,
                "source_quad": record["source_quadrilateral"],
            }
        )
    full_masks = [placement["full_mask"] for placement in placements]
    visible_masks: list[np.ndarray] = [np.zeros_like(scene[:, :, 0]) for _ in placements]
    higher = np.zeros_like(scene[:, :, 0])
    for index in range(len(placements) - 1, -1, -1):
        visible_masks[index] = np.where((full_masks[index] > 0) & (higher == 0), 255, 0).astype(
            np.uint8
        )
        visible_masks[index] = _remove_small_components(visible_masks[index], MIN_VISIBLE_PIXELS)
        higher = np.maximum(higher, full_masks[index])
    _validate_visible_masks(visible_masks)
    shadow_opacity = float(rng.uniform(0.08, 0.22)) if placements else 0.0
    for full_mask in full_masks:
        _apply_shadow(scene, full_mask, shadow_opacity)
    for placement in placements:
        _alpha_composite(scene, placement["warped_rgba"], placement["full_mask"])
    photometric = _photometric(scene, rng, bucket == "blur_glare_dark_compressed")
    ok, encoded_scene = cv2.imencode(
        ".jpg", scene, [cv2.IMWRITE_JPEG_QUALITY, int(photometric["jpeg_quality"])]
    )
    if not ok:
        raise SyntheticVisibleRegionRenderingError(f"could not encode scene {scene_id}")
    image_path = output_root / "images" / f"{scene_id}.jpg"
    image_digest = _write_bytes(image_path, encoded_scene.tobytes())
    omitted_instances: list[dict[str, Any]] = []
    coco_annotations: list[dict[str, Any]] = []
    instance_records: list[dict[str, Any]] = []
    for index, (placement, visible_mask) in enumerate(
        zip(placements, visible_masks, strict=True), start=1
    ):
        visible_pixels = int(np.count_nonzero(visible_mask))
        full_pixels = int(np.count_nonzero(placement["full_mask"]))
        if visible_pixels < MIN_VISIBLE_PIXELS:
            omitted_instances.append(
                {
                    "cutout_id": placement["cutout_id"],
                    "reason": "below_visible_pixel_threshold",
                    "full_mask_pixels": full_pixels,
                    "visible_mask_pixels": visible_pixels,
                }
            )
            continue
        mask_path = output_root / "masks" / f"{scene_id}-instance-{index:02d}.png"
        ok, encoded_mask = cv2.imencode(".png", visible_mask)
        if not ok:
            raise SyntheticVisibleRegionRenderingError(f"could not encode mask {scene_id}/{index}")
        mask_digest = _write_bytes(mask_path, encoded_mask.tobytes())
        polygons = _mask_polygons(visible_mask)
        if not polygons:
            omitted_instances.append(
                {
                    "cutout_id": placement["cutout_id"],
                    "reason": "visible_mask_has_no_polygon",
                    "full_mask_pixels": full_pixels,
                    "visible_mask_pixels": visible_pixels,
                }
            )
            continue
        bbox = _mask_bbox(visible_mask)
        # Match the repository COCO validator's frozen area convention.  Its shared
        # shoelace helper already divides by two before the validator divides again.
        area = sum(
            _polygon_area(list(zip(polygon[::2], polygon[1::2], strict=True)))
            for polygon in polygons
        ) / 2.0
        instance = {
            "instance_index": index,
            "cutout_id": placement["cutout_id"],
            "source_asset_id": placement["source_asset_id"],
            "side": placement["side"],
            "z_order": placement["z_order"],
            "source_group": placement["source_group"],
            "source_quadrilateral": placement["source_quad"],
            "target_quadrilateral": _quad_to_records(placement["target_quad"]),
            "placement": placement["placement"],
            "full_mask_pixels": full_pixels,
            "visible_mask_pixels": visible_pixels,
            "occlusion_ratio": _occlusion_ratio(placement["full_mask"], visible_mask),
            "clipped": bool(
                np.any(placement["target_quad"][:, 0] < 0)
                or np.any(placement["target_quad"][:, 0] > output_width)
                or np.any(placement["target_quad"][:, 1] < 0)
                or np.any(placement["target_quad"][:, 1] > output_height)
            ),
            "mask": {
                "path": _relative(mask_path, repository),
                "sha256": mask_digest,
                "bbox": bbox,
                "polygons": polygons,
            },
        }
        instance_records.append(instance)
        coco_annotations.append(
            _coco_annotation(
                int(scene_id.rsplit("-", 1)[-1]) * 100 + index,
                int(scene_id.rsplit("-", 1)[-1]) + 1,
                scene_id,
                image_digest,
                instance,
                polygons,
                bbox,
                area,
                placement["side"],
                background,
            )
        )
    receipt_core = {
        "schema_version": SYNTHETIC_VISIBLE_REGION_SCENES_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_SCENES_CAMPAIGN_ID,
        "milestone": "M2",
        "scene_id": scene_id,
        "bucket": bucket,
        "seed": seed,
        "recipe_digest": recipe_digest,
        "geometry_reference": {
            "example_id": geometry.get("example_id"),
            "recording_id": geometry.get("recording_id"),
            "event_id": geometry.get("event_id"),
            "table_setup": geometry.get("table_setup"),
            "selection": geometry.get("selection", "legacy-perspective-example-v1"),
        },
        "background": {
            "background_id": background["background_id"],
            "source_group": background["source_group"],
            "source_frame": background["frame_identity"],
            "path": _relative(background_path, repository),
            "sha256": _sha256_file(background_path),
        },
        "placements": instance_records,
        "omitted_instances": omitted_instances,
        "effects": {"shadow_opacity": _round(shadow_opacity), **photometric},
        "output": {
            "image": {
                "path": _relative(image_path, repository),
                "sha256": image_digest,
                "width": output_width,
                "height": output_height,
            }
        },
        "source_lineage": {
            "permission": "training_only",
            "split": "train",
            "source_group_keys": sorted(
                {str(background["source_group"]["key"])}
                | {str(item["source_group"]["key"]) for item in instance_records}
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
    receipt_summary = {
        "scene_id": scene_id,
        "bucket": bucket,
        "seed": seed,
        "receipt_path": _relative(receipt_path, repository),
        "receipt_digest": receipt["receipt_digest"],
        "image_path": _relative(image_path, repository),
        "image_sha256": image_digest,
        "instance_count": len(instance_records),
        "omitted_instance_count": len(omitted_instances),
        "card_sides": sorted({str(item["side"]) for item in instance_records}),
    }
    coco_image = _coco_image(
        int(scene_id.rsplit("-", 1)[-1]) + 1,
        scene_id,
        _relative(image_path, output_root),
        output_width,
        output_height,
        image_digest,
        background,
    )
    return receipt, receipt_summary, {"image": coco_image, "annotations": coco_annotations}


def build_synthetic_visible_region_scenes(
    repository_root: str | Path,
    *,
    m1_manifest_path: str | Path = M1_MANIFEST_DEFAULT,
    m0_manifest_path: str | Path = M0_MANIFEST_DEFAULT,
    output_directory: str | Path = OUTPUT_DIRECTORY_DEFAULT,
    scene_count: int = SCENE_COUNT_DEFAULT,
) -> dict[str, Any]:
    """Render one deterministic M2 smoke set from the M1 training-only assets."""

    if isinstance(scene_count, bool) or not isinstance(scene_count, int) or scene_count <= 0:
        raise SyntheticVisibleRegionRenderingError("scene_count must be a positive integer")
    repository = Path(repository_root).expanduser().resolve()
    m1_path = _resolve(repository, m1_manifest_path)
    m0_path = _resolve(repository, m0_manifest_path)
    output_root = _resolve(repository, output_directory)
    m1 = _read_json(m1_path, "M1 input manifest")
    validate_synthetic_visible_region_inputs(m1)
    recipe, recipe_digest = _load_recipe(repository, m0_path)
    available_buckets, omitted_buckets = _scene_bucket_list(recipe)
    usable, _, backgrounds = _source_paths(repository, m1)
    background = backgrounds[0]["record"]
    background_path = backgrounds[0]["path"]
    geometry = _calibration_geometry_examples(m1, background)
    uses_calibrated_geometry = bool(geometry)
    if not geometry:
        geometry = [
            {
                **item,
                "selection": "legacy-perspective-example-v1",
            }
            for item in _geometry_examples(m1)
        ]
    base_seed = int(recipe.get("seed", 7001))
    selected_assets = [
        usable[index % len(usable)] for index in range(max(1, min(scene_count, len(usable))))
    ]
    count = min(scene_count, len(available_buckets))
    receipts: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    coco_images: list[dict[str, Any]] = []
    coco_annotations: list[dict[str, Any]] = []
    for index in range(count):
        bucket = available_buckets[index]
        rotation = index % len(selected_assets)
        selected = selected_assets[rotation:] + selected_assets[:rotation]
        receipt, summary, coco = _render_scene(
            repository,
            output_root,
            scene_id=f"scene-{index:04d}",
            bucket=bucket,
            seed=base_seed + index,
            background=background,
            background_path=background_path,
            card_assets=selected,
            geometry=geometry[index % len(geometry)],
            recipe_digest=recipe_digest,
        )
        receipts.append(receipt)
        summaries.append(summary)
        coco_images.append(coco["image"])
        coco_annotations.extend(coco["annotations"])
    coco = {
        "info": {
            "description": "DokoDetector deterministic synthetic visible-region scenes",
            "version": "synthetic-visible-region-scenes-v1",
            "coco_version": "coco-2017",
            "campaign_id": SYNTHETIC_VISIBLE_REGION_SCENES_CAMPAIGN_ID,
            "campaign_manifest_digest": recipe_digest,
            "trainer_partition": "train",
        },
        "licenses": [],
        "images": coco_images,
        "annotations": coco_annotations,
        "categories": [TARGET_CATEGORY],
    }
    validate_rfdetr_coco_annotations(coco)
    coco_path = output_root / "_annotations.coco.json"
    coco_digest = _write_json(coco_path, coco)
    core = {
        "schema_version": SYNTHETIC_VISIBLE_REGION_SCENES_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_SCENES_CAMPAIGN_ID,
        "milestone": "M2",
        "freeze_state": "complete_with_gap" if omitted_buckets else "complete",
        "input_manifest": {
            "path": _relative(m1_path, repository),
            "manifest_digest": _digest(m1["manifest_digest"], "M1 manifest digest"),
            "file_sha256": _sha256_file(m1_path),
        },
        "m0_recipe": {
            "path": _relative(m0_path, repository),
            "recipe_digest": recipe_digest,
        },
        "recipe": {
            "seed": base_seed,
            "scene_count": count,
            "available_buckets": available_buckets,
            "omitted_buckets": omitted_buckets,
            "card_sides": ["face_up", "unknown"],
            "card_card_occlusion": True,
            "human_occluders": False,
            "geometry_source": (
                "setup-matched-human-single-two-card-templates-v1"
                if uses_calibrated_geometry
                else "legacy-perspective-library-v1"
            ),
            "source_permission": "training_only",
        },
        "scenes": summaries,
        "outputs": {
            "coco": {"path": _relative(coco_path, repository), "sha256": coco_digest},
            "scene_count": count,
            "image_count": len(coco_images),
            "annotation_count": len(coco_annotations),
        },
        "coverage_gaps": [
            "face_down_cards and mixed_card_sides buckets omitted because M1 has no "
            "face_down cutout"
        ]
        if omitted_buckets
        else [],
    }
    manifest = {**core, "manifest_digest": _sha256_bytes(canonical_json_bytes(core))}
    _write_json(output_root / "manifest.json", manifest)
    return manifest


def validate_synthetic_visible_region_scenes(raw: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "campaign_id",
        "milestone",
        "freeze_state",
        "input_manifest",
        "m0_recipe",
        "recipe",
        "scenes",
        "outputs",
        "coverage_gaps",
        "manifest_digest",
    }
    if set(raw) != expected:
        raise SyntheticVisibleRegionRenderingError("M2 scene manifest has invalid fields")
    if raw["schema_version"] != SYNTHETIC_VISIBLE_REGION_SCENES_SCHEMA_VERSION:
        raise SyntheticVisibleRegionRenderingError("M2 scene manifest schema is unsupported")
    if raw["campaign_id"] != SYNTHETIC_VISIBLE_REGION_SCENES_CAMPAIGN_ID:
        raise SyntheticVisibleRegionRenderingError("M2 scene manifest identity is invalid")
    if raw["milestone"] != "M2" or raw["freeze_state"] not in {"complete", "complete_with_gap"}:
        raise SyntheticVisibleRegionRenderingError("M2 scene manifest state is invalid")
    if not isinstance(raw["scenes"], list) or not raw["scenes"]:
        raise SyntheticVisibleRegionRenderingError("M2 scene manifest has no scenes")
    if not isinstance(raw["coverage_gaps"], list):
        raise SyntheticVisibleRegionRenderingError("M2 coverage_gaps must be a list")
    if raw["freeze_state"] == "complete_with_gap" and not raw["coverage_gaps"]:
        raise SyntheticVisibleRegionRenderingError("M2 gap state has no coverage gap")
    core = {key: raw[key] for key in expected if key != "manifest_digest"}
    if raw["manifest_digest"] != _sha256_bytes(canonical_json_bytes(core)):
        raise SyntheticVisibleRegionRenderingError("M2 manifest digest is stale")


def write_synthetic_visible_region_scenes(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    validate_synthetic_visible_region_scenes(manifest)
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(manifest) + b"\n"
    if destination.exists() and destination.read_bytes() != payload:
        raise SyntheticVisibleRegionRenderingError(
            f"M2 scene manifest already exists and differs: {destination}"
        )
    if not destination.exists():
        destination.write_bytes(payload)
    return destination


def render_synthetic_visible_region_scenes_human(manifest: Mapping[str, Any]) -> str:
    outputs = manifest["outputs"]
    lines = [
        "Synthetic visible-region training data M2",
        f"status: {manifest['freeze_state']}",
        f"scenes: {outputs['scene_count']}",
        f"images: {outputs['image_count']}",
        f"annotations: {outputs['annotation_count']}",
        f"manifest digest: {manifest['manifest_digest']}",
    ]
    if manifest["coverage_gaps"]:
        lines.append("coverage gaps:")
        lines.extend(f"- {gap}" for gap in manifest["coverage_gaps"])
    return "\n".join(lines) + "\n"


__all__ = [
    "M1_MANIFEST_DEFAULT",
    "M0_MANIFEST_DEFAULT",
    "OUTPUT_DIRECTORY_DEFAULT",
    "SCENE_COUNT_DEFAULT",
    "SYNTHETIC_VISIBLE_REGION_SCENES_CAMPAIGN_ID",
    "SYNTHETIC_VISIBLE_REGION_SCENES_SCHEMA_VERSION",
    "SyntheticVisibleRegionRenderingError",
    "build_synthetic_visible_region_scenes",
    "render_synthetic_visible_region_scenes_human",
    "validate_synthetic_visible_region_scenes",
    "write_synthetic_visible_region_scenes",
]
