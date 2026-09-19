"""Calibrate one stable table plane from reviewed card quadrilaterals.

This module deliberately contains no white balance, color transfer, blur, shadow, glare, or JPEG
variation.  It uses only the geometry needed to place cards plausibly on an explicit reviewed empty
table frame.

The calibration treats each complete reviewed card as a 1 by 1.5 rectangle on one flat table
plane.  One rectangle gives an initial projective rectification.  All available rectangles then
fit a common metric upgrade, reject outliers, and provide the median card size in table coordinates.
The inverse homography projects synthetic card layouts, including overlap, back into the empty
source frame.
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
    _quad_array,
    _selected_assets,
    _usable_cutouts,
    build_synthetic_visible_region_recording_discovery,
)
from .synthetic_visible_region_rendering import (
    MIN_VISIBLE_PIXELS,
    _alpha_composite,
    _mask_bbox,
    _mask_polygons,
    _occlusion_ratio,
    _polygon_area,
    _quad_to_records,
    _read_cutout,
    _remove_small_components,
    _warp_cutout,
)

SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_SCHEMA_VERSION = (
    "synthetic-visible-region-planar-geometry-samples/v1"
)
SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_CAMPAIGN_ID = (
    "0070-m5-synthetic-visible-region-planar-geometry-samples"
)
M1_MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-m1-inputs.json"
OUTPUT_DIRECTORY_DEFAULT = ".runtime/synthetic-visible-region-0070-planar-geometry-samples"
MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-planar-geometry-samples.json"
SAMPLE_COUNT_DEFAULT = 3
CARD_ASPECT_RATIO = 1.5
BACKGROUND_STRATEGY = "explicit-reviewed-empty-table-only-v1"
_SHA256_LENGTH = 64


class SyntheticVisibleRegionPlanarGeometryError(ValueError):
    """The reviewed table-plane geometry cannot safely produce a sample."""


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"could not read {field} {path}: {error}"
        ) from error
    if not isinstance(value, Mapping):
        raise SyntheticVisibleRegionPlanarGeometryError(f"{field} must be a JSON object")
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


def _apply_homography(homography: np.ndarray, points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    homogeneous = np.column_stack((points, np.ones(len(points), dtype=np.float64)))
    transformed = homogeneous @ np.asarray(homography, dtype=np.float64).T
    denominator = transformed[:, 2:3]
    if np.any(np.abs(denominator) < 1e-9):
        raise SyntheticVisibleRegionPlanarGeometryError("homography projects a point to infinity")
    return transformed[:, :2] / denominator


def _cyclic_quad(points: np.ndarray) -> np.ndarray:
    """Return a cyclic quadrilateral order with the first edge considered short for now."""

    points = np.asarray(points, dtype=np.float64).reshape(4, 2)
    center = np.mean(points, axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]
    if abs(float(cv2.contourArea(ordered.astype(np.float32)))) < 1e-6:
        raise SyntheticVisibleRegionPlanarGeometryError("card quadrilateral has zero area")
    return ordered


def _orientations(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the two physical assignments of adjacent edges to short and long card sides."""

    cyclic = _cyclic_quad(points)
    return cyclic, np.roll(cyclic, -1, axis=0)


def _card_vectors(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return average short and long edge vectors for a short-first cyclic quadrilateral."""

    short = ((points[1] - points[0]) + (points[2] - points[3])) / 2.0
    long = ((points[3] - points[0]) + (points[2] - points[1])) / 2.0
    return short, long


def _cross2(left: np.ndarray, right: np.ndarray) -> float:
    return float(left[0] * right[1] - left[1] * right[0])


def _card_residual(points: np.ndarray) -> tuple[float, float, float]:
    short, long = _card_vectors(points)
    short_length = float(np.linalg.norm(short))
    long_length = float(np.linalg.norm(long))
    if short_length < 1e-9 or long_length < 1e-9:
        return float("inf"), float("inf"), float("inf")
    cosine = float(abs(np.dot(short, long) / (short_length * long_length)))
    angle_error = float(np.degrees(np.arcsin(min(1.0, cosine))))
    aspect_error = abs(float(np.log((long_length / short_length) / CARD_ASPECT_RATIO)))
    opposite_short = points[2] - points[3]
    opposite_long = points[2] - points[1]
    opposite_short_length = max(float(np.linalg.norm(opposite_short)), 1e-9)
    opposite_long_length = max(float(np.linalg.norm(opposite_long)), 1e-9)
    parallel_error = (
        abs(_cross2(short, opposite_short)) / (short_length * opposite_short_length)
        + abs(_cross2(long, opposite_long)) / (long_length * opposite_long_length)
    )
    return angle_error, aspect_error, parallel_error


def _best_orientation(points: np.ndarray, image_to_table: np.ndarray) -> np.ndarray:
    candidates = []
    for orientation in _orientations(points):
        transformed = _apply_homography(image_to_table, orientation)
        angle_error, aspect_error, parallel_error = _card_residual(transformed)
        score = angle_error / 10.0 + aspect_error + parallel_error
        candidates.append((score, orientation))
    return min(candidates, key=lambda item: item[0])[1]


def _initial_image_to_table(card_quads: Sequence[np.ndarray]) -> np.ndarray:
    """Choose the card assignment that best rectifies the full reviewed-card set."""

    destination = np.asarray(
        [[0.0, 0.0], [1.0, 0.0], [1.0, CARD_ASPECT_RATIO], [0.0, CARD_ASPECT_RATIO]],
        dtype=np.float32,
    )
    choices: list[tuple[float, np.ndarray]] = []
    for raw_quad in card_quads:
        for orientation in _orientations(raw_quad):
            homography = cv2.getPerspectiveTransform(orientation.astype(np.float32), destination)
            residuals: list[float] = []
            for candidate in card_quads:
                best = _best_orientation(candidate, homography)
                transformed = _apply_homography(homography, best)
                angle_error, aspect_error, parallel_error = _card_residual(transformed)
                residuals.append(angle_error / 10.0 + aspect_error + parallel_error)
            choices.append((float(np.median(residuals)), homography.astype(np.float64)))
    if not choices:
        raise SyntheticVisibleRegionPlanarGeometryError(
            "table calibration has no card quadrilateral"
        )
    return min(choices, key=lambda item: item[0])[1]


def _metric_upgrade(points: Sequence[np.ndarray]) -> np.ndarray:
    equations: list[list[float]] = []
    for quad in points:
        short, long = _card_vectors(quad)
        sx, sy = short
        lx, ly = long
        equations.append([sx * lx, sx * ly + sy * lx, sy * ly])
        equations.append(
            [
                lx * lx - CARD_ASPECT_RATIO**2 * sx * sx,
                2.0 * (lx * ly - CARD_ASPECT_RATIO**2 * sx * sy),
                ly * ly - CARD_ASPECT_RATIO**2 * sy * sy,
            ]
        )
    if len(equations) < 6:
        raise SyntheticVisibleRegionPlanarGeometryError(
            "at least three complete reviewed cards are required for table calibration"
        )
    _, _, right = np.linalg.svd(np.asarray(equations, dtype=np.float64))
    values = right[-1]
    metric = np.asarray(
        [[values[0], values[1]], [values[1], values[2]]], dtype=np.float64
    )
    eigenvalues, eigenvectors = np.linalg.eigh(metric)
    if np.all(eigenvalues < 0.0):
        metric *= -1.0
        eigenvalues *= -1.0
    if np.any(eigenvalues <= 1e-8):
        # The fitting equations are homogeneous.  Project the weak numerical solution to the
        # nearest positive-definite metric instead of silently accepting a mirrored table plane.
        eigenvalues = np.maximum(np.abs(eigenvalues), 1e-6)
        metric = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
    metric /= np.sqrt(np.linalg.det(metric))
    return np.linalg.cholesky(metric).T


def _robust_inliers(points: Sequence[np.ndarray]) -> list[int]:
    residuals = []
    for quad in points:
        angle_error, aspect_error, parallel_error = _card_residual(quad)
        residuals.append(angle_error / 10.0 + aspect_error + parallel_error)
    median = float(np.median(residuals))
    mad = float(np.median(np.abs(np.asarray(residuals) - median)))
    threshold = median + max(0.025, 3.0 * mad)
    return [index for index, residual in enumerate(residuals) if residual <= threshold]


def fit_table_plane(card_quads: Sequence[np.ndarray]) -> dict[str, Any]:
    """Fit a metric table coordinate system from multiple complete card rectangles."""

    raw_quads = [np.asarray(quad, dtype=np.float64).reshape(4, 2) for quad in card_quads]
    if len(raw_quads) < 3:
        raise SyntheticVisibleRegionPlanarGeometryError(
            "at least three complete reviewed cards are required for table calibration"
        )
    initial = _initial_image_to_table(raw_quads)
    oriented = [_best_orientation(quad, initial) for quad in raw_quads]
    affine_quads = [_apply_homography(initial, quad) for quad in oriented]
    upgrade = _metric_upgrade(affine_quads)
    affine_transform = np.eye(3, dtype=np.float64)
    affine_transform[:2, :2] = upgrade
    image_to_table = affine_transform @ initial
    table_quads = [_apply_homography(image_to_table, quad) for quad in oriented]
    inlier_indices = _robust_inliers(table_quads)
    if len(inlier_indices) < 3:
        raise SyntheticVisibleRegionPlanarGeometryError(
            "table calibration rejected too many reviewed card quadrilaterals"
        )
    if len(inlier_indices) != len(raw_quads):
        affine_quads = [affine_quads[index] for index in inlier_indices]
        upgrade = _metric_upgrade(affine_quads)
        affine_transform[:2, :2] = upgrade
        image_to_table = affine_transform @ initial
        table_quads = [_apply_homography(image_to_table, quad) for quad in oriented]
        inlier_indices = _robust_inliers(table_quads)
    short_lengths = []
    long_lengths = []
    angle_errors = []
    aspect_errors = []
    parallel_errors = []
    for index in inlier_indices:
        short, long = _card_vectors(table_quads[index])
        short_lengths.append(float(np.linalg.norm(short)))
        long_lengths.append(float(np.linalg.norm(long)))
        angle_error, aspect_error, parallel_error = _card_residual(table_quads[index])
        angle_errors.append(angle_error)
        aspect_errors.append(aspect_error)
        parallel_errors.append(parallel_error)
    short_size = float(np.median(short_lengths))
    if short_size < 1e-9:
        raise SyntheticVisibleRegionPlanarGeometryError("calibrated card short side is zero")
    scale = 1.0 / short_size
    scaling = np.diag([scale, scale, 1.0])
    image_to_table = scaling @ image_to_table
    table_quads = [_apply_homography(image_to_table, quad) for quad in oriented]
    long_lengths = [
        np.linalg.norm(_card_vectors(table_quads[index])[1]) for index in inlier_indices
    ]
    long_size = float(np.median(long_lengths))
    calibration_core = {
        "method": "multi-card-planar-metric-rectification-v1",
        "card_aspect_ratio": CARD_ASPECT_RATIO,
        "input_card_count": len(raw_quads),
        "accepted_card_count": len(inlier_indices),
        "rejected_card_indices": [
            index for index in range(len(raw_quads)) if index not in inlier_indices
        ],
        "image_to_table_homography": [
            [_round(value) for value in row] for row in image_to_table
        ],
        "table_to_image_homography": [
            [_round(value) for value in row] for row in np.linalg.inv(image_to_table)
        ],
        "card_short_size": _round(1.0),
        "card_long_size": _round(long_size),
        "median_angle_error_degrees": _round(float(np.median(angle_errors))),
        "median_aspect_error": _round(float(np.median(aspect_errors))),
        "median_parallel_error": _round(float(np.median(parallel_errors))),
    }
    return {
        **calibration_core,
        "image_to_table": image_to_table,
        "table_to_image": np.linalg.inv(image_to_table),
        "oriented_image_quads": oriented,
        "table_quads": table_quads,
        "inlier_indices": inlier_indices,
        "calibration_digest": _sha256_bytes(canonical_json_bytes(calibration_core)),
    }


def _empty_backgrounds(
    repository: Path, m1: Mapping[str, Any], recording_ids: set[str] | None
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in m1.get("backgrounds", []):
        if not isinstance(item, Mapping):
            continue
        source_group = item.get("source_group")
        decision = item.get("reviewed_decision")
        files = item.get("files")
        image = files.get("image") if isinstance(files, Mapping) else None
        if (
            not isinstance(source_group, Mapping)
            or not isinstance(decision, Mapping)
            or not isinstance(image, Mapping)
            or source_group.get("split") != "train"
            or decision.get("status") != "accepted"
            or decision.get("contains_visible_card") is not False
            or decision.get("full_frame_review_coverage") is not True
        ):
            continue
        recording_id = str(source_group.get("id", ""))
        if recording_ids is not None and recording_id not in recording_ids:
            continue
        path = _resolve(repository, str(image.get("path", "")))
        if not path.is_file() or _sha256_file(path) != image.get("sha256"):
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"reviewed empty background is missing or changed: {item.get('background_id')}"
            )
        result.append({"record": dict(item), "path": path, "sha256": str(image["sha256"])})
    return sorted(result, key=lambda item: str(item["record"]["background_id"]))


def _recording_geometry(
    discovery: Mapping[str, Any], background: Mapping[str, Any]
) -> tuple[list[np.ndarray], list[dict[str, Any]]]:
    source_group = background["source_group"]
    recording_id = str(source_group["id"])
    width = int(background["frame_identity"]["width"])
    height = int(background["frame_identity"]["height"])
    dimensions = np.asarray([width, height], dtype=np.float64)
    quads: list[np.ndarray] = []
    provenance: list[dict[str, Any]] = []
    for candidate in discovery["candidates"]:
        if (
            not isinstance(candidate, Mapping)
            or candidate.get("source_split") != "train"
            or candidate.get("recording_id") != recording_id
            or candidate.get("table_setup") != source_group.get("table_setup")
        ):
            continue
        frame = candidate.get("frame_identity", {})
        if frame.get("width") != width or frame.get("height") != height:
            continue
        for card_index, normalized_quad in enumerate(candidate["normalized_quadrilaterals"]):
            quads.append(_quad_array(normalized_quad) * dimensions)
            provenance.append(
                {
                    "candidate_id": str(candidate["candidate_id"]),
                    "event_id": str(candidate["event_id"]),
                    "card_index": card_index,
                    "selection_score": _round(float(candidate["selection_score"])),
                }
            )
    if len(quads) < 3:
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"recording {recording_id} has fewer than three complete reviewed card quadrilaterals"
        )
    return quads, provenance


def _pose_from_quad(quad: np.ndarray) -> dict[str, np.ndarray | float]:
    short, long = _card_vectors(quad)
    short_length = float(np.linalg.norm(short))
    long_length = float(np.linalg.norm(long))
    if short_length < 1e-8 or long_length < 1e-8:
        raise SyntheticVisibleRegionPlanarGeometryError("card pose has a zero-length edge")
    return {
        "center": np.mean(quad, axis=0),
        "short_axis": short / short_length,
        "long_axis": long / long_length,
        "short_size": short_length,
        "long_size": long_length,
    }


def _rotate(vector: np.ndarray, degrees: float) -> np.ndarray:
    radians = np.deg2rad(degrees)
    matrix = np.asarray(
        [[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]],
        dtype=np.float64,
    )
    return matrix @ vector


def _quad_from_pose(
    center: np.ndarray,
    short_axis: np.ndarray,
    long_axis: np.ndarray,
    short_size: float,
    long_size: float,
) -> np.ndarray:
    short = short_axis * short_size / 2.0
    long = long_axis * long_size / 2.0
    return np.asarray(
        [
            center - short - long,
            center + short - long,
            center + short + long,
            center - short + long,
        ],
        dtype=np.float64,
    )


def _anchor_pose(
    calibration: Mapping[str, Any], width: int, height: int
) -> dict[str, np.ndarray | float]:
    target = np.asarray([width * 0.56, height * 0.55], dtype=np.float64)
    inverse = np.asarray(calibration["table_to_image"], dtype=np.float64)
    candidates = []
    for index in calibration["inlier_indices"]:
        table_quad = calibration["table_quads"][index]
        image_center = np.mean(_apply_homography(inverse, table_quad), axis=0)
        candidates.append((float(np.linalg.norm(image_center - target)), table_quad))
    if not candidates:
        raise SyntheticVisibleRegionPlanarGeometryError("table calibration has no anchor card")
    return _pose_from_quad(min(candidates, key=lambda item: item[0])[1])


def _sample_layouts(anchor: Mapping[str, np.ndarray | float]) -> list[tuple[str, list[np.ndarray]]]:
    center = np.asarray(anchor["center"], dtype=np.float64)
    short_axis = np.asarray(anchor["short_axis"], dtype=np.float64)
    long_axis = np.asarray(anchor["long_axis"], dtype=np.float64)
    short_size = float(anchor["short_size"])
    long_size = float(anchor["long_size"])

    def pose(offset_short: float, offset_long: float, rotation: float) -> np.ndarray:
        return _quad_from_pose(
            center + short_axis * offset_short + long_axis * offset_long,
            _rotate(short_axis, rotation),
            _rotate(long_axis, rotation),
            short_size,
            long_size,
        )

    return [
        ("observed_single_card_pose", [pose(0.0, 0.0, 0.0)]),
        (
            "two_card_overlap",
            [
                pose(-0.14 * short_size, -0.18 * long_size, -7.0),
                pose(0.24 * short_size, 0.17 * long_size, 10.0),
            ],
        ),
        (
            "three_card_overlap",
            [
                pose(-0.28 * short_size, -0.20 * long_size, -12.0),
                pose(0.02 * short_size, 0.08 * long_size, 1.0),
                pose(0.30 * short_size, 0.36 * long_size, 14.0),
            ],
        ),
    ]


def _render_scene(
    repository: Path,
    output_root: Path,
    *,
    scene_id: str,
    image_id: int,
    background: Mapping[str, Any],
    background_path: Path,
    background_sha256: str,
    layout_name: str,
    table_quads: Sequence[np.ndarray],
    table_to_image: np.ndarray,
    assets: Sequence[Mapping[str, Any]],
    calibration: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    scene = cv2.imread(str(background_path), cv2.IMREAD_COLOR)
    if scene is None:
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"could not decode empty background {background_path}"
        )
    height, width = scene.shape[:2]
    placements: list[dict[str, Any]] = []
    for index, (table_quad, asset) in enumerate(zip(table_quads, assets, strict=True), start=1):
        record = asset["record"]
        rgba, alpha = _read_cutout(asset)
        image_quad = _apply_homography(table_to_image, table_quad)
        warped, warped_alpha = _warp_cutout(rgba, alpha, image_quad, width, height)
        warped_alpha = _remove_small_components(warped_alpha, MIN_VISIBLE_PIXELS)
        placements.append(
            {
                "instance_index": index,
                "z_order": index,
                "table_quad": table_quad,
                "image_quad": image_quad,
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
    for placement in placements:
        _alpha_composite(scene, placement["warped_rgba"], placement["full_mask"])
    ok, encoded = cv2.imencode(".jpg", scene, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise SyntheticVisibleRegionPlanarGeometryError(f"could not encode scene {scene_id}")
    image_path = output_root / "images" / f"{scene_id}.jpg"
    image_digest = _write_bytes(image_path, encoded.tobytes())

    instances: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    for placement, visible_mask in zip(placements, visible_masks, strict=True):
        visible_pixels = int(np.count_nonzero(visible_mask))
        if visible_pixels < MIN_VISIBLE_PIXELS:
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"{scene_id} creates a card below the visible-pixel threshold"
            )
        polygons = _mask_polygons(visible_mask)
        if not polygons:
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"{scene_id} creates a card with no visible polygon"
            )
        mask_path = (
            output_root / "masks" / f"{scene_id}-instance-{placement['instance_index']:02d}.png"
        )
        ok, encoded_mask = cv2.imencode(".png", visible_mask)
        if not ok:
            raise SyntheticVisibleRegionPlanarGeometryError(f"could not encode {scene_id} mask")
        mask_digest = _write_bytes(mask_path, encoded_mask.tobytes())
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
            "table_quadrilateral": _quad_to_records(placement["table_quad"]),
            "target_quadrilateral": _quad_to_records(placement["image_quad"]),
            "full_mask_pixels": int(np.count_nonzero(placement["full_mask"])),
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
                "reference_revision_id": "synthetic-visible-region-planar-geometry-v1",
                "card_id": placement["cutout_id"],
                "source_video_sha256": str(background["source_group"]["source_sha256"]),
                "source_frame_sha256": image_digest,
                "target_geometry_sha256": _sha256_bytes(
                    canonical_json_bytes(placement["image_quad"].tolist())
                ),
                "split": "train",
                "card_side": placement["side"],
                "session_id": f"synthetic-planar-{background['background_id']}",
                "source_asset_id": placement["source_asset_id"],
                "video_id": scene_id,
                "table_setup": str(background["source_group"]["table_setup"]),
                "source_group_key": str(background["source_group"]["key"]),
            }
        )
    receipt_core = {
        "schema_version": SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_CAMPAIGN_ID,
        "milestone": "M5-geometry-revision",
        "scene_id": scene_id,
        "layout": layout_name,
        "background": {
            "strategy": BACKGROUND_STRATEGY,
            "background_id": background["background_id"],
            "reviewed_decision": background["reviewed_decision"],
            "source_group": background["source_group"],
            "frame_identity": background["frame_identity"],
            "path": _relative(background_path, repository),
            "sha256": background_sha256,
        },
        "table_calibration": {
            key: value
            for key, value in calibration.items()
            if key
            not in {
                "image_to_table",
                "table_to_image",
                "oriented_image_quads",
                "table_quads",
                "inlier_indices",
            }
        },
        "placements": instances,
        "photometric_effects": {},
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
                {str(background["source_group"]["key"])}
                | {str(item["source_group"]["key"]) for item in instances}
            ),
        },
        "renderer": {
            "opencv_version": cv2.__version__,
            "numpy_version": np.__version__,
            "python_version": platform.python_version(),
            "mask_policy": "opaque-card-z-order-and-frame-clipping-v1",
            "photometric_policy": "none-geometry-review-only-v1",
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
        "layout": layout_name,
        "card_count": len(instances),
        "background": {
            "background_id": background["background_id"],
            "strategy": BACKGROUND_STRATEGY,
            "reviewed_decision": background["reviewed_decision"],
        },
        "table_calibration_digest": calibration["calibration_digest"],
        "photometric_effects": {},
        "image_path": _relative(image_path, repository),
        "image_sha256": image_digest,
        "receipt_path": _relative(receipt_path, repository),
        "receipt_digest": receipt["receipt_digest"],
        "instance_count": len(instances),
    }
    image = {
        "id": image_id,
        "file_name": _relative(image_path, output_root),
        "width": width,
        "height": height,
        "sha256": image_digest,
        "recording_id": scene_id,
        "event_id": scene_id,
        "item_id": background["background_id"],
        "reference_revision_id": "synthetic-visible-region-planar-geometry-v1",
        "source_video_sha256": str(background["source_group"]["source_sha256"]),
        "source_frame_sha256": image_digest,
        "split": "train",
        "trainer_partition": "train",
        "session_id": f"synthetic-planar-{background['background_id']}",
        "source_asset_id": background["background_id"],
        "video_id": scene_id,
        "table_setup": str(background["source_group"]["table_setup"]),
        "source_group_key": str(background["source_group"]["key"]),
        "dataset_origin": "synthetic",
        "background_strategy": BACKGROUND_STRATEGY,
    }
    return summary, image, annotations


def build_synthetic_visible_region_planar_geometry_samples(
    repository_root: str | Path,
    *,
    source_manifest_path: str | Path = SOURCE_MANIFEST_DEFAULT,
    m1_manifest_path: str | Path = M1_MANIFEST_DEFAULT,
    output_directory: str | Path = OUTPUT_DIRECTORY_DEFAULT,
    sample_count: int = SAMPLE_COUNT_DEFAULT,
    recording_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Create a bounded, geometry-only review set from selected stable recordings."""

    if not 1 <= sample_count <= 3:
        raise SyntheticVisibleRegionPlanarGeometryError(
            "sample_count must be between one and three"
        )
    repository = Path(repository_root).expanduser().resolve()
    requested_recordings = set(recording_ids) if recording_ids is not None else None
    discovery = build_synthetic_visible_region_recording_discovery(
        repository, source_manifest_path=source_manifest_path, max_card_count=MAX_CARD_COUNT_DEFAULT
    )
    m1_path = _resolve(repository, m1_manifest_path)
    m1 = _read_json(m1_path, "M1 input manifest")
    try:
        validate_synthetic_visible_region_inputs(m1)
    except ValueError as error:
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"M1 input manifest is invalid: {error}"
        ) from error
    backgrounds = _empty_backgrounds(repository, m1, requested_recordings)
    if not backgrounds:
        raise SyntheticVisibleRegionPlanarGeometryError(
            "no accepted reviewed empty training table matches the selected recordings"
        )
    output_root = _resolve(repository, output_directory)
    output_root.mkdir(parents=True, exist_ok=True)
    usable_assets = _usable_cutouts(repository, m1)

    calibrations: list[dict[str, Any]] = []
    plans: list[tuple[Mapping[str, Any], dict[str, Any], str, list[np.ndarray]]] = []
    for background_item in backgrounds:
        background = background_item["record"]
        background_image = cv2.imread(str(background_item["path"]), cv2.IMREAD_COLOR)
        if background_image is None:
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"could not decode empty background {background_item['path']}"
            )
        quads, provenance = _recording_geometry(discovery, background)
        calibration = fit_table_plane(quads)
        calibration_summary = {
            key: value
            for key, value in calibration.items()
            if key
            not in {
                "image_to_table",
                "table_to_image",
                "oriented_image_quads",
                "table_quads",
                "inlier_indices",
            }
        }
        calibration_summary.update(
            {
                "recording_id": str(background["source_group"]["id"]),
                "table_setup": str(background["source_group"]["table_setup"]),
                "background_id": str(background["background_id"]),
                "background_strategy": BACKGROUND_STRATEGY,
                "accepted_geometry_sources": [
                    provenance[index] for index in calibration["inlier_indices"]
                ],
            }
        )
        calibrations.append(calibration_summary)
        anchor = _anchor_pose(calibration, background_image.shape[1], background_image.shape[0])
        for layout_name, layout_quads in _sample_layouts(anchor):
            plans.append((background_item, calibration, layout_name, layout_quads))
    plans = plans[:sample_count]
    if len(plans) < sample_count:
        raise SyntheticVisibleRegionPlanarGeometryError(
            "selected recordings do not provide enough geometry sample layouts"
        )

    summaries: list[dict[str, Any]] = []
    coco_images: list[dict[str, Any]] = []
    coco_annotations: list[dict[str, Any]] = []
    for index, (background_item, calibration, layout_name, table_quads) in enumerate(plans):
        background = background_item["record"]
        recording_id = str(background["source_group"]["id"])
        assets = _selected_assets(usable_assets, recording_id, len(table_quads), index)
        scene_id = f"scene-{index:02d}-{recording_id}-{layout_name}"
        summary, image, annotations = _render_scene(
            repository,
            output_root,
            scene_id=scene_id,
            image_id=index + 1,
            background=background,
            background_path=background_item["path"],
            background_sha256=background_item["sha256"],
            layout_name=layout_name,
            table_quads=table_quads,
            table_to_image=np.asarray(calibration["table_to_image"], dtype=np.float64),
            assets=assets,
            calibration=calibration,
        )
        summaries.append(summary)
        coco_images.append(image)
        coco_annotations.extend(annotations)
    coco = {
        "info": {
            "description": "Geometry-only synthetic visible-card samples on reviewed empty tables",
            "version": SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_SCHEMA_VERSION,
            "coco_version": "coco-2017",
            "campaign_id": SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_CAMPAIGN_ID,
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
        "schema_version": SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_CAMPAIGN_ID,
        "milestone": "M5-geometry-revision",
        "freeze_state": "geometry_samples_ready_for_operator_review",
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
            "table_geometry_method": "multi-card-planar-metric-rectification-v1",
            "card_aspect_ratio": CARD_ASPECT_RATIO,
            "geometry_sources": "complete-reviewed-four-point-cards-from-the-same-recording",
            "photometric_effects": "none",
            "sample_count": sample_count,
            "recording_ids": sorted(requested_recordings) if requested_recordings else None,
        },
        "inventory": {
            "empty_background_count": len(backgrounds),
            "calibrated_recording_count": len(calibrations),
            "sample_scene_count": len(summaries),
            "sample_annotation_count": len(coco_annotations),
            "sample_scene_counts_by_card_count": dict(
                sorted(Counter(str(item["card_count"]) for item in summaries).items())
            ),
        },
        "calibrations": calibrations,
        "outputs": {
            "directory": _relative(output_root, repository),
            "coco": {"path": _relative(coco_path, repository), "sha256": coco_digest},
            "scene_count": len(summaries),
            "image_count": len(coco_images),
            "annotation_count": len(coco_annotations),
        },
        "scenes": summaries,
        "coverage_gaps": [
            "only recordings with an accepted full-frame-reviewed empty training table can render",
            "camera height, distance, and intrinsics are not identified; the calibrated "
            "table-plane homography is sufficient for planar card placement",
            "lighting, color, blur, shadow, and compression changes are intentionally absent "
            "from this geometry review",
        ],
    }
    return {**core, "manifest_digest": _sha256_bytes(canonical_json_bytes(core))}


def write_synthetic_visible_region_planar_geometry_manifest(
    path: str | Path, manifest: Mapping[str, Any]
) -> Path:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(manifest) + b"\n")
    return destination


def render_synthetic_visible_region_planar_geometry_human(manifest: Mapping[str, Any]) -> str:
    inventory = manifest["inventory"]
    return "\n".join(
        [
            "Epic 0070 planar table-geometry review samples",
            f"state: {manifest['freeze_state']}",
            f"reviewed empty tables: {inventory['empty_background_count']}",
            f"calibrated recordings: {inventory['calibrated_recording_count']}",
            f"geometry-only samples: {inventory['sample_scene_count']}",
            f"COCO: {manifest['outputs']['coco']['path']}",
        ]
    ) + "\n"


__all__ = [
    "MANIFEST_DEFAULT",
    "M1_MANIFEST_DEFAULT",
    "OUTPUT_DIRECTORY_DEFAULT",
    "SAMPLE_COUNT_DEFAULT",
    "SyntheticVisibleRegionPlanarGeometryError",
    "_apply_homography",
    "build_synthetic_visible_region_planar_geometry_samples",
    "fit_table_plane",
    "render_synthetic_visible_region_planar_geometry_human",
    "write_synthetic_visible_region_planar_geometry_manifest",
]
