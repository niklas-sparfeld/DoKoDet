"""Shared geometry primitives and contracts for calibrated visible-card review.

This module contains only deterministic table-plane geometry.  It does not know about card
identity, gameplay, or a particular detector.  Pixel coordinates use source-image boundaries and
table coordinates use the calibrated short-card-side unit.  A positive angle turns toward the
positive table ``y`` axis.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from .reviewed_rfdetr_detector_campaign import canonical_json_bytes

CARD_ASPECT_RATIO = 1.5
GEOMETRY_ALGORITHM_VERSION = "card-plane-geometry/v1"
DERIVATION_RECIPE_VERSION = "card-plane-derived-regions/v1"
COORDINATE_SYSTEM_VERSION = "source-pixel-boundary/table-short-side-unit/v1"
CORNER_ORDER_VERSION = "cyclic-short-edge-first/v1"
ANGLE_CONVENTION_VERSION = "positive-toward-positive-y-degrees/v1"
NUMERIC_PRECISION_DECIMALS = 6
MASK_THRESHOLD = 128
MASK_RASTER_POLICY = "pixel-center-even-odd/v1"

TABLE_PLANE_CALIBRATION_SCHEMA_VERSION = "table-plane-calibration/v1"
CALIBRATION_CANDIDATE_SCHEMA_VERSION = "table-plane-calibration-candidate/v1"
CARD_POSE_SCHEMA_VERSION = "card-pose/v1"
CARD_STACKING_ORDER_SCHEMA_VERSION = "card-stacking-order/v1"
POSE_FIT_DIAGNOSTICS_SCHEMA_VERSION = "card-pose-fit-diagnostics/v1"
REVIEWED_CARD_SCENE_SCHEMA_VERSION = "reviewed-card-scene/v1"
DERIVED_REGION_RECEIPT_SCHEMA_VERSION = "derived-visible-region-receipt/v1"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


class CardPlaneGeometryError(ValueError):
    """Raised when shared geometry or a geometry contract is invalid."""


def _round(value: float) -> float:
    return round(float(value), NUMERIC_PRECISION_DECIMALS)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise CardPlaneGeometryError(f"{field} must be an object")
    return value


def _strict(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    fields = set(value)
    missing = expected - fields
    unknown = fields - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise CardPlaneGeometryError(f"{field} has invalid fields ({'; '.join(details)})")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CardPlaneGeometryError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or _IDENTIFIER.fullmatch(result) is None:
        raise CardPlaneGeometryError(f"{field} must be a safe identifier")
    return result


def _digest_value(value: Any, field: str) -> str:
    result = _text(value, field)
    if _DIGEST.fullmatch(result) is None:
        raise CardPlaneGeometryError(f"{field} must be a lower-case SHA-256 digest")
    return result


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CardPlaneGeometryError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CardPlaneGeometryError(f"{field} must be a finite number")
    return result


def _positive(value: Any, field: str) -> float:
    result = _finite(value, field)
    if result <= 0.0:
        raise CardPlaneGeometryError(f"{field} must be positive")
    return result


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CardPlaneGeometryError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CardPlaneGeometryError(f"{field} must be a non-negative integer")
    return value


def _optional_identifier(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field)


def _point(value: Any, field: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise CardPlaneGeometryError(f"{field} must contain two coordinates")
    return (_finite(value[0], f"{field}[0]"), _finite(value[1], f"{field}[1]"))


def _quad(value: Any, field: str) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise CardPlaneGeometryError(f"{field} must contain four corners")
    points = tuple(_point(point, f"{field}[{index}]") for index, point in enumerate(value))
    if abs(polygon_area(points)) <= 1e-9:
        raise CardPlaneGeometryError(f"{field} must have positive area")
    return points


def _matrix(value: Any, field: str) -> tuple[tuple[float, ...], ...]:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise CardPlaneGeometryError(f"{field} must be a 3 by 3 matrix") from error
    if array.shape != (3, 3) or not np.all(np.isfinite(array)):
        raise CardPlaneGeometryError(f"{field} must be a finite 3 by 3 matrix")
    if abs(float(np.linalg.det(array))) < 1e-12:
        raise CardPlaneGeometryError(f"{field} must be invertible")
    return tuple(tuple(float(item) for item in row) for row in array)


def _matrix_array(value: Any, field: str) -> np.ndarray:
    matrix = np.asarray(_matrix(value, field), dtype=np.float64)
    return matrix


def _points_records(points: np.ndarray) -> list[list[float]]:
    return [[_round(point[0]), _round(point[1])] for point in points]


def _mapping_core(mapping: Mapping[str, Any], digest_field: str) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if key != digest_field}


def apply_homography(homography: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Apply one finite, invertible 3 by 3 homography to two-dimensional points."""

    matrix = _matrix_array(homography, "homography")
    values = np.asarray(points, dtype=np.float64)
    if values.size == 0:
        return values.reshape(-1, 2)
    if values.ndim != 2 or values.shape[1] != 2 or not np.all(np.isfinite(values)):
        raise CardPlaneGeometryError("points must be a finite N by 2 array")
    homogeneous = np.column_stack((values, np.ones(len(values), dtype=np.float64)))
    transformed = homogeneous @ matrix.T
    denominator = transformed[:, 2:3]
    if np.any(np.abs(denominator) < 1e-9):
        raise CardPlaneGeometryError("homography projects a point to infinity")
    return transformed[:, :2] / denominator


def invert_homography(homography: np.ndarray) -> np.ndarray:
    """Return the validated inverse of one homography."""

    matrix = _matrix_array(homography, "homography")
    return np.linalg.inv(matrix)


def cyclic_quad(points: np.ndarray) -> np.ndarray:
    """Return four corners in a stable cyclic order."""

    values = np.asarray(points, dtype=np.float64)
    if values.shape != (4, 2) or not np.all(np.isfinite(values)):
        raise CardPlaneGeometryError("quadrilateral must be a finite 4 by 2 array")
    center = np.mean(values, axis=0)
    angles = np.arctan2(values[:, 1] - center[1], values[:, 0] - center[0])
    ordered = values[np.argsort(angles)]
    if polygon_area(ordered) <= 1e-6:
        raise CardPlaneGeometryError("card quadrilateral has zero area")
    return ordered


def quadrilateral_orientations(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the two assignments of adjacent edges to short and long sides."""

    cyclic = cyclic_quad(points)
    return cyclic, np.roll(cyclic, -1, axis=0)


def card_vectors(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return average short- and long-edge vectors for a cyclic quadrilateral."""

    values = np.asarray(points, dtype=np.float64).reshape(4, 2)
    short = ((values[1] - values[0]) + (values[2] - values[3])) / 2.0
    long = ((values[3] - values[0]) + (values[2] - values[1])) / 2.0
    return short, long


def _cross2(left: np.ndarray, right: np.ndarray) -> float:
    return float(left[0] * right[1] - left[1] * right[0])


def card_residual(points: np.ndarray) -> tuple[float, float, float]:
    """Return angle, aspect, and parallelism residuals for one card quadrilateral."""

    short, long = card_vectors(points)
    short_length = float(np.linalg.norm(short))
    long_length = float(np.linalg.norm(long))
    if short_length < 1e-9 or long_length < 1e-9:
        return float("inf"), float("inf"), float("inf")
    cosine = float(abs(np.dot(short, long) / (short_length * long_length)))
    angle_error = float(np.degrees(np.arcsin(min(1.0, cosine))))
    aspect_error = abs(float(np.log((long_length / short_length) / CARD_ASPECT_RATIO)))
    opposite_short = np.asarray(points)[2] - np.asarray(points)[3]
    opposite_long = np.asarray(points)[2] - np.asarray(points)[1]
    opposite_short_length = max(float(np.linalg.norm(opposite_short)), 1e-9)
    opposite_long_length = max(float(np.linalg.norm(opposite_long)), 1e-9)
    parallel_error = abs(_cross2(short, opposite_short)) / (
        short_length * opposite_short_length
    ) + abs(_cross2(long, opposite_long)) / (long_length * opposite_long_length)
    return angle_error, aspect_error, parallel_error


def _best_orientation(points: np.ndarray, image_to_table: np.ndarray) -> np.ndarray:
    candidates: list[tuple[float, np.ndarray]] = []
    for orientation in quadrilateral_orientations(points):
        transformed = apply_homography(image_to_table, orientation)
        angle_error, aspect_error, parallel_error = card_residual(transformed)
        score = angle_error / 10.0 + aspect_error + parallel_error
        candidates.append((score, orientation))
    return min(candidates, key=lambda item: item[0])[1]


def _initial_image_to_table(card_quads: Sequence[np.ndarray]) -> np.ndarray:
    destination = np.asarray(
        [[0.0, 0.0], [1.0, 0.0], [1.0, CARD_ASPECT_RATIO], [0.0, CARD_ASPECT_RATIO]],
        dtype=np.float32,
    )
    choices: list[tuple[float, np.ndarray]] = []
    for raw_quad in card_quads:
        for orientation in quadrilateral_orientations(raw_quad):
            homography = cv2.getPerspectiveTransform(orientation.astype(np.float32), destination)
            residuals: list[float] = []
            for candidate in card_quads:
                best = _best_orientation(candidate, homography)
                transformed = apply_homography(homography, best)
                angle_error, aspect_error, parallel_error = card_residual(transformed)
                residuals.append(angle_error / 10.0 + aspect_error + parallel_error)
            choices.append((float(np.median(residuals)), homography.astype(np.float64)))
    if not choices:
        raise CardPlaneGeometryError("table calibration has no card quadrilateral")
    return min(choices, key=lambda item: item[0])[1]


def _metric_upgrade(points: Sequence[np.ndarray]) -> np.ndarray:
    equations: list[list[float]] = []
    for quad in points:
        short, long = card_vectors(quad)
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
        raise CardPlaneGeometryError("at least three complete card quadrilaterals are required")
    _, _, right = np.linalg.svd(np.asarray(equations, dtype=np.float64))
    values = right[-1]
    metric = np.asarray([[values[0], values[1]], [values[1], values[2]]], dtype=np.float64)
    eigenvalues, eigenvectors = np.linalg.eigh(metric)
    if np.all(eigenvalues < 0.0):
        metric *= -1.0
        eigenvalues *= -1.0
    if np.any(eigenvalues <= 1e-8):
        eigenvalues = np.maximum(np.abs(eigenvalues), 1e-6)
        metric = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
    metric /= np.sqrt(np.linalg.det(metric))
    return np.linalg.cholesky(metric).T


def _robust_inliers(points: Sequence[np.ndarray]) -> list[int]:
    residuals = []
    for quad in points:
        angle_error, aspect_error, parallel_error = card_residual(quad)
        residuals.append(angle_error / 10.0 + aspect_error + parallel_error)
    median = float(np.median(residuals))
    mad = float(np.median(np.abs(np.asarray(residuals) - median)))
    threshold = median + max(0.025, 3.0 * mad)
    return [index for index, residual in enumerate(residuals) if residual <= threshold]


def fit_table_plane(card_quads: Sequence[np.ndarray]) -> dict[str, Any]:
    """Fit one metric table coordinate system from complete card quadrilaterals."""

    raw_quads = [np.asarray(quad, dtype=np.float64).reshape(4, 2) for quad in card_quads]
    if len(raw_quads) < 3:
        raise CardPlaneGeometryError(
            "at least three complete card quadrilaterals are required for table calibration"
        )
    initial = _initial_image_to_table(raw_quads)
    oriented = [_best_orientation(quad, initial) for quad in raw_quads]
    affine_quads = [apply_homography(initial, quad) for quad in oriented]
    upgrade = _metric_upgrade(affine_quads)
    affine_transform = np.eye(3, dtype=np.float64)
    affine_transform[:2, :2] = upgrade
    image_to_table = affine_transform @ initial
    table_quads = [apply_homography(image_to_table, quad) for quad in oriented]
    inlier_indices = _robust_inliers(table_quads)
    if len(inlier_indices) < 3:
        raise CardPlaneGeometryError("table calibration rejected too many card quadrilaterals")
    if len(inlier_indices) != len(raw_quads):
        affine_quads = [affine_quads[index] for index in inlier_indices]
        upgrade = _metric_upgrade(affine_quads)
        affine_transform[:2, :2] = upgrade
        image_to_table = affine_transform @ initial
        table_quads = [apply_homography(image_to_table, quad) for quad in oriented]
        inlier_indices = _robust_inliers(table_quads)
    short_lengths = []
    angle_errors = []
    aspect_errors = []
    parallel_errors = []
    for index in inlier_indices:
        short, _long = card_vectors(table_quads[index])
        short_lengths.append(float(np.linalg.norm(short)))
        angle_error, aspect_error, parallel_error = card_residual(table_quads[index])
        angle_errors.append(angle_error)
        aspect_errors.append(aspect_error)
        parallel_errors.append(parallel_error)
    short_size = float(np.median(short_lengths))
    if short_size < 1e-9:
        raise CardPlaneGeometryError("calibrated card short side is zero")
    scaling = np.diag([1.0 / short_size, 1.0 / short_size, 1.0])
    image_to_table = scaling @ image_to_table
    table_quads = [apply_homography(image_to_table, quad) for quad in oriented]
    long_lengths = [np.linalg.norm(card_vectors(table_quads[index])[1]) for index in inlier_indices]
    long_size = float(np.median(long_lengths))
    calibration_core = {
        "method": "multi-card-planar-metric-rectification-v1",
        "card_aspect_ratio": CARD_ASPECT_RATIO,
        "input_card_count": len(raw_quads),
        "accepted_card_count": len(inlier_indices),
        "rejected_card_indices": [
            index for index in range(len(raw_quads)) if index not in inlier_indices
        ],
        "image_to_table_homography": [[_round(value) for value in row] for row in image_to_table],
        "table_to_image_homography": [
            [_round(value) for value in row] for row in np.linalg.inv(image_to_table)
        ],
        "card_short_size": _round(1.0),
        "card_long_size": _round(long_size),
        "median_angle_error_degrees": _round(float(np.median(angle_errors))),
        "median_aspect_error": _round(float(np.median(aspect_errors))),
        "median_parallel_error": _round(float(np.median(parallel_errors))),
    }
    inverse = np.linalg.inv(image_to_table)
    return {
        **calibration_core,
        "image_to_table": image_to_table,
        "table_to_image": inverse,
        "oriented_image_quads": oriented,
        "table_quads": table_quads,
        "inlier_indices": inlier_indices,
        "calibration_digest": _digest(calibration_core),
    }


def rotate_vector(vector: np.ndarray, degrees: float) -> np.ndarray:
    """Rotate a table-plane vector with the frozen angle convention."""

    radians = np.deg2rad(float(degrees))
    matrix = np.asarray(
        [[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]],
        dtype=np.float64,
    )
    return matrix @ np.asarray(vector, dtype=np.float64)


def card_quad_from_pose(
    center: np.ndarray | Sequence[float],
    rotation_degrees: float,
    short_size: float,
    long_size: float,
) -> np.ndarray:
    """Construct one fixed-size card rectangle in table coordinates."""

    center_array = np.asarray(center, dtype=np.float64)
    if center_array.shape != (2,) or not np.all(np.isfinite(center_array)):
        raise CardPlaneGeometryError("card pose center must contain two finite coordinates")
    short = _positive(short_size, "card short size")
    long = _positive(long_size, "card long size")
    angle = np.deg2rad(_finite(rotation_degrees, "card rotation"))
    short_axis = np.asarray([np.cos(angle), np.sin(angle)], dtype=np.float64)
    long_axis = np.asarray([-np.sin(angle), np.cos(angle)], dtype=np.float64)
    short_vector = short_axis * short / 2.0
    long_vector = long_axis * long / 2.0
    return np.asarray(
        [
            center_array - short_vector - long_vector,
            center_array + short_vector - long_vector,
            center_array + short_vector + long_vector,
            center_array - short_vector + long_vector,
        ],
        dtype=np.float64,
    )


def project_fixed_card(
    table_to_image: np.ndarray,
    center: np.ndarray | Sequence[float],
    rotation_degrees: float,
    short_size: float,
    long_size: float,
) -> np.ndarray:
    """Project one calibrated fixed-size card pose into the source image."""

    return apply_homography(
        table_to_image,
        card_quad_from_pose(center, rotation_degrees, short_size, long_size),
    )


def polygon_area(points: Sequence[tuple[float, float]] | np.ndarray) -> float:
    values = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if len(values) < 3:
        return 0.0
    return abs(float(cv2.contourArea(values.astype(np.float32))))


def rasterize_polygon(points: np.ndarray, width: int, height: int) -> np.ndarray:
    """Rasterize one projected polygon with the shared binary-mask policy."""

    width = _positive_int(width, "mask width")
    height = _positive_int(height, "mask height")
    values = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if len(values) < 3 or not np.all(np.isfinite(values)):
        raise CardPlaneGeometryError("polygon must contain at least three finite points")
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(mask, [np.rint(values).astype(np.int32)], 255, lineType=cv2.LINE_8)
    return mask


def remove_small_components(mask: np.ndarray, minimum_pixels: int) -> np.ndarray:
    """Keep only connected binary-mask components at or above the given area."""

    values = np.asarray(mask)
    if values.ndim != 2:
        raise CardPlaneGeometryError("mask must be a two-dimensional array")
    minimum = _non_negative_int(minimum_pixels, "minimum component pixels")
    components, labels, stats, _ = cv2.connectedComponentsWithStats(
        np.where(values > 0, 255, 0).astype(np.uint8), 8
    )
    cleaned = np.zeros(values.shape, dtype=np.uint8)
    for component in range(1, components):
        if int(stats[component, cv2.CC_STAT_AREA]) >= minimum:
            cleaned[labels == component] = 255
    return cleaned


def mask_to_polygons(mask: np.ndarray) -> list[list[float]]:
    """Extract deterministic pixel-boundary polygons from a binary mask."""

    values = np.where(np.asarray(mask) > 0, 255, 0).astype(np.uint8)
    if values.ndim != 2:
        raise CardPlaneGeometryError("mask must be a two-dimensional array")
    contours, _ = cv2.findContours(values, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    polygons: list[list[float]] = []
    for contour in contours:
        approximation = cv2.approxPolyDP(contour, 0.0, True).reshape(-1, 2)
        if len(approximation) < 3:
            approximation = contour.reshape(-1, 2)
        if len(approximation) < 3:
            continue
        polygon: list[float] = []
        for x, y in approximation:
            polygon.extend([_round(float(x) + 0.5), _round(float(y) + 0.5)])
        if polygon_area(list(zip(polygon[::2], polygon[1::2], strict=True))) > 0:
            polygons.append(polygon)
    polygons.sort(key=lambda item: (-len(item), item))
    return polygons


def mask_bbox(mask: np.ndarray) -> list[int]:
    values = np.asarray(mask)
    if values.ndim != 2:
        raise CardPlaneGeometryError("mask must be a two-dimensional array")
    ys, xs = np.where(values > 0)
    if len(xs) == 0:
        raise CardPlaneGeometryError("visible mask is empty")
    x_min, x_max = int(xs.min()), int(xs.max())
    y_min, y_max = int(ys.min()), int(ys.max())
    return [x_min, y_min, x_max - x_min + 1, y_max - y_min + 1]


def derive_visible_masks(
    full_masks: Sequence[np.ndarray], stacking_order: Sequence[int]
) -> list[np.ndarray]:
    """Subtract front cards from back cards while preserving disconnected components.

    ``stacking_order`` is front-to-back.  A card earlier in the order occludes a card later in
    the order.  The function does not remove small components; that policy belongs to the caller.
    """

    if len(full_masks) != len(stacking_order):
        raise CardPlaneGeometryError("stacking order must contain every mask exactly once")
    if sorted(stacking_order) != list(range(len(full_masks))):
        raise CardPlaneGeometryError("stacking order must be a permutation of mask indices")
    if not full_masks:
        return []
    values = [np.where(np.asarray(mask) > 0, 255, 0).astype(np.uint8) for mask in full_masks]
    shape = values[0].shape
    if any(mask.shape != shape or mask.ndim != 2 for mask in values):
        raise CardPlaneGeometryError("all full masks must have the same two-dimensional shape")
    occluding = np.zeros(shape, dtype=np.uint8)
    visible = [np.zeros(shape, dtype=np.uint8) for _ in values]
    for index in stacking_order:
        visible[index] = np.where((values[index] > 0) & (occluding == 0), 255, 0).astype(np.uint8)
        occluding = np.maximum(occluding, values[index])
    return visible


@dataclass(frozen=True, slots=True)
class CalibrationCandidateReceipt:
    """Immutable audit receipt for one calibration candidate."""

    candidate_id: str
    source_revision: str
    source_frame_id: str
    confidence: float
    quadrilateral: tuple[tuple[float, float], ...]
    temporal_bin: str
    table_position_bin: str
    scale_bin: str
    orientation_bin: str
    accepted: bool
    rejection_reason: str | None
    receipt_digest: str

    @classmethod
    def create(
        cls,
        *,
        candidate_id: str,
        source_revision: str,
        source_frame_id: str,
        confidence: float,
        quadrilateral: Sequence[Sequence[float]],
        temporal_bin: str,
        table_position_bin: str,
        scale_bin: str,
        orientation_bin: str,
        accepted: bool,
        rejection_reason: str | None = None,
    ) -> "CalibrationCandidateReceipt":
        if not isinstance(accepted, bool):
            raise CardPlaneGeometryError("accepted must be a boolean")
        confidence_value = _round(_finite(confidence, "confidence"))
        quadrilateral_value = tuple(
            tuple(_round(value) for value in point)
            for point in _quad(quadrilateral, "quadrilateral")
        )
        core = {
            "schema_version": CALIBRATION_CANDIDATE_SCHEMA_VERSION,
            "candidate_id": _identifier(candidate_id, "candidate_id"),
            "source_revision": _identifier(source_revision, "source_revision"),
            "source_frame_id": _identifier(source_frame_id, "source_frame_id"),
            "confidence": confidence_value,
            "quadrilateral": [list(point) for point in quadrilateral_value],
            "temporal_bin": _identifier(temporal_bin, "temporal_bin"),
            "table_position_bin": _identifier(table_position_bin, "table_position_bin"),
            "scale_bin": _identifier(scale_bin, "scale_bin"),
            "orientation_bin": _identifier(orientation_bin, "orientation_bin"),
            "accepted": accepted,
            "rejection_reason": (
                _text(rejection_reason, "rejection_reason")
                if rejection_reason is not None
                else None
            ),
        }
        if core["accepted"] and core["rejection_reason"] is not None:
            raise CardPlaneGeometryError("accepted candidates cannot have a rejection reason")
        if not core["accepted"] and core["rejection_reason"] is None:
            raise CardPlaneGeometryError("rejected candidates need a rejection reason")
        return cls(
            candidate_id=core["candidate_id"],
            source_revision=core["source_revision"],
            source_frame_id=core["source_frame_id"],
            confidence=core["confidence"],
            quadrilateral=tuple(tuple(point) for point in core["quadrilateral"]),
            temporal_bin=core["temporal_bin"],
            table_position_bin=core["table_position_bin"],
            scale_bin=core["scale_bin"],
            orientation_bin=core["orientation_bin"],
            accepted=core["accepted"],
            rejection_reason=core["rejection_reason"],
            receipt_digest=_digest(core),
        )

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": CALIBRATION_CANDIDATE_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "source_revision": self.source_revision,
            "source_frame_id": self.source_frame_id,
            "confidence": _round(self.confidence),
            "quadrilateral": [list(point) for point in self.quadrilateral],
            "temporal_bin": self.temporal_bin,
            "table_position_bin": self.table_position_bin,
            "scale_bin": self.scale_bin,
            "orientation_bin": self.orientation_bin,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
        }
        return {**core, "receipt_digest": _digest(core)}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CalibrationCandidateReceipt":
        data = _mapping(raw, "calibration candidate")
        expected = {
            "schema_version",
            "candidate_id",
            "source_revision",
            "source_frame_id",
            "confidence",
            "quadrilateral",
            "temporal_bin",
            "table_position_bin",
            "scale_bin",
            "orientation_bin",
            "accepted",
            "rejection_reason",
            "receipt_digest",
        }
        _strict(data, expected, "calibration candidate")
        if data["schema_version"] != CALIBRATION_CANDIDATE_SCHEMA_VERSION:
            raise CardPlaneGeometryError("unsupported calibration candidate schema")
        candidate = cls.create(
            candidate_id=data["candidate_id"],
            source_revision=data["source_revision"],
            source_frame_id=data["source_frame_id"],
            confidence=data["confidence"],
            quadrilateral=data["quadrilateral"],
            temporal_bin=data["temporal_bin"],
            table_position_bin=data["table_position_bin"],
            scale_bin=data["scale_bin"],
            orientation_bin=data["orientation_bin"],
            accepted=data["accepted"],
            rejection_reason=data["rejection_reason"],
        )
        if data["receipt_digest"] != candidate.receipt_digest:
            raise CardPlaneGeometryError("calibration candidate digest does not match its contents")
        return candidate


@dataclass(frozen=True, slots=True)
class TablePlaneCalibration:
    """Recording-scoped calibration and common card dimensions."""

    calibration_revision_id: str
    recording_id: str
    source_revision: str
    frame_width: int
    frame_height: int
    image_to_table: tuple[tuple[float, ...], ...]
    table_to_image: tuple[tuple[float, ...], ...]
    card_short_size: float
    card_long_size: float
    candidate_receipt_digests: tuple[str, ...]
    diagnostics: Mapping[str, Any]
    calibration_digest: str

    @classmethod
    def create(
        cls,
        *,
        calibration_revision_id: str,
        recording_id: str,
        source_revision: str,
        frame_width: int,
        frame_height: int,
        image_to_table: Sequence[Sequence[float]],
        table_to_image: Sequence[Sequence[float]],
        card_short_size: float,
        card_long_size: float,
        candidate_receipt_digests: Sequence[str],
        diagnostics: Mapping[str, Any],
    ) -> "TablePlaneCalibration":
        core = {
            "schema_version": TABLE_PLANE_CALIBRATION_SCHEMA_VERSION,
            "calibration_revision_id": _identifier(
                calibration_revision_id, "calibration_revision_id"
            ),
            "recording_id": _identifier(recording_id, "recording_id"),
            "source_revision": _identifier(source_revision, "source_revision"),
            "frame_width": _positive_int(frame_width, "frame_width"),
            "frame_height": _positive_int(frame_height, "frame_height"),
            "image_to_table": [
                [_round(value) for value in row]
                for row in _matrix(image_to_table, "image_to_table")
            ],
            "table_to_image": [
                [_round(value) for value in row]
                for row in _matrix(table_to_image, "table_to_image")
            ],
            "card_short_size": _round(_positive(card_short_size, "card_short_size")),
            "card_long_size": _round(_positive(card_long_size, "card_long_size")),
            "card_aspect_ratio": CARD_ASPECT_RATIO,
            "candidate_receipt_digests": [
                _digest_value(value, f"candidate_receipt_digests[{index}]")
                for index, value in enumerate(candidate_receipt_digests)
            ],
            "algorithm_version": GEOMETRY_ALGORITHM_VERSION,
            "coordinate_system": COORDINATE_SYSTEM_VERSION,
            "corner_order": CORNER_ORDER_VERSION,
            "angle_convention": ANGLE_CONVENTION_VERSION,
            "diagnostics": dict(diagnostics),
        }
        image_to_table_array = np.asarray(core["image_to_table"], dtype=np.float64)
        table_to_image_array = np.asarray(core["table_to_image"], dtype=np.float64)
        if not np.allclose(
            image_to_table_array @ table_to_image_array,
            np.eye(3),
            # Homographies can contain both sub-pixel perspective terms and large translation
            # terms.  The frozen six-decimal serialization can therefore introduce a small
            # reciprocal error after both matrices are rounded.  Keep the validation strict while
            # allowing that representation error.
            atol=10 ** (-NUMERIC_PRECISION_DECIMALS + 3),
        ):
            raise CardPlaneGeometryError(
                "image_to_table and table_to_image must be reciprocal transforms"
            )
        return cls(
            calibration_revision_id=core["calibration_revision_id"],
            recording_id=core["recording_id"],
            source_revision=core["source_revision"],
            frame_width=core["frame_width"],
            frame_height=core["frame_height"],
            image_to_table=tuple(tuple(row) for row in core["image_to_table"]),
            table_to_image=tuple(tuple(row) for row in core["table_to_image"]),
            card_short_size=core["card_short_size"],
            card_long_size=core["card_long_size"],
            candidate_receipt_digests=tuple(core["candidate_receipt_digests"]),
            diagnostics=core["diagnostics"],
            calibration_digest=_digest(core),
        )

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": TABLE_PLANE_CALIBRATION_SCHEMA_VERSION,
            "calibration_revision_id": self.calibration_revision_id,
            "recording_id": self.recording_id,
            "source_revision": self.source_revision,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "image_to_table": [list(row) for row in self.image_to_table],
            "table_to_image": [list(row) for row in self.table_to_image],
            "card_short_size": _round(self.card_short_size),
            "card_long_size": _round(self.card_long_size),
            "card_aspect_ratio": CARD_ASPECT_RATIO,
            "candidate_receipt_digests": list(self.candidate_receipt_digests),
            "algorithm_version": GEOMETRY_ALGORITHM_VERSION,
            "coordinate_system": COORDINATE_SYSTEM_VERSION,
            "corner_order": CORNER_ORDER_VERSION,
            "angle_convention": ANGLE_CONVENTION_VERSION,
            "diagnostics": dict(self.diagnostics),
        }
        return {**core, "calibration_digest": _digest(core)}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TablePlaneCalibration":
        data = _mapping(raw, "table-plane calibration")
        expected = {
            "schema_version",
            "calibration_revision_id",
            "recording_id",
            "source_revision",
            "frame_width",
            "frame_height",
            "image_to_table",
            "table_to_image",
            "card_short_size",
            "card_long_size",
            "card_aspect_ratio",
            "candidate_receipt_digests",
            "algorithm_version",
            "coordinate_system",
            "corner_order",
            "angle_convention",
            "diagnostics",
            "calibration_digest",
        }
        _strict(data, expected, "table-plane calibration")
        if data["schema_version"] != TABLE_PLANE_CALIBRATION_SCHEMA_VERSION:
            raise CardPlaneGeometryError("unsupported table-plane calibration schema")
        if data["card_aspect_ratio"] != CARD_ASPECT_RATIO:
            raise CardPlaneGeometryError("table-plane calibration card aspect ratio is unsupported")
        if data["algorithm_version"] != GEOMETRY_ALGORITHM_VERSION:
            raise CardPlaneGeometryError("table-plane calibration algorithm is unsupported")
        if data["coordinate_system"] != COORDINATE_SYSTEM_VERSION:
            raise CardPlaneGeometryError("table-plane calibration coordinate system is unsupported")
        if data["corner_order"] != CORNER_ORDER_VERSION:
            raise CardPlaneGeometryError("table-plane calibration corner order is unsupported")
        if data["angle_convention"] != ANGLE_CONVENTION_VERSION:
            raise CardPlaneGeometryError("table-plane calibration angle convention is unsupported")
        calibration = cls.create(
            calibration_revision_id=data["calibration_revision_id"],
            recording_id=data["recording_id"],
            source_revision=data["source_revision"],
            frame_width=data["frame_width"],
            frame_height=data["frame_height"],
            image_to_table=data["image_to_table"],
            table_to_image=data["table_to_image"],
            card_short_size=data["card_short_size"],
            card_long_size=data["card_long_size"],
            candidate_receipt_digests=data["candidate_receipt_digests"],
            diagnostics=data["diagnostics"],
        )
        if data["calibration_digest"] != calibration.calibration_digest:
            raise CardPlaneGeometryError(
                "table-plane calibration digest does not match its contents"
            )
        return calibration


@dataclass(frozen=True, slots=True)
class CardPose:
    """One fixed-size card placement in table coordinates."""

    card_id: str
    center: tuple[float, float]
    rotation_degrees: float
    source_suggestion_id: str | None
    fit_diagnostics_digest: str | None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": CARD_POSE_SCHEMA_VERSION,
            "card_id": self.card_id,
            "center": [_round(self.center[0]), _round(self.center[1])],
            "rotation_degrees": _round(self.rotation_degrees),
            "source_suggestion_id": self.source_suggestion_id,
            "fit_diagnostics_digest": self.fit_diagnostics_digest,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "card pose") -> "CardPose":
        data = _mapping(raw, context)
        _strict(
            data,
            {
                "schema_version",
                "card_id",
                "center",
                "rotation_degrees",
                "source_suggestion_id",
                "fit_diagnostics_digest",
            },
            context,
        )
        if data["schema_version"] != CARD_POSE_SCHEMA_VERSION:
            raise CardPlaneGeometryError(f"{context}.schema_version is unsupported")
        center = _point(data["center"], f"{context}.center")
        digest = data["fit_diagnostics_digest"]
        return cls(
            card_id=_identifier(data["card_id"], f"{context}.card_id"),
            center=center,
            rotation_degrees=_finite(data["rotation_degrees"], f"{context}.rotation_degrees"),
            source_suggestion_id=_optional_identifier(
                data["source_suggestion_id"], f"{context}.source_suggestion_id"
            ),
            fit_diagnostics_digest=(
                None
                if digest is None
                else _digest_value(digest, f"{context}.fit_diagnostics_digest")
            ),
        )


@dataclass(frozen=True, slots=True)
class CardStackingOrder:
    """Frame-local front-to-back order used only for card-card occlusion."""

    card_ids: tuple[str, ...]
    uncertain_edges: tuple[tuple[str, str], ...]
    contradictions: tuple[str, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": CARD_STACKING_ORDER_SCHEMA_VERSION,
            "card_ids": list(self.card_ids),
            "uncertain_edges": [list(edge) for edge in self.uncertain_edges],
            "contradictions": list(self.contradictions),
        }

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "card stacking order"
    ) -> "CardStackingOrder":
        data = _mapping(raw, context)
        _strict(data, {"schema_version", "card_ids", "uncertain_edges", "contradictions"}, context)
        if data["schema_version"] != CARD_STACKING_ORDER_SCHEMA_VERSION:
            raise CardPlaneGeometryError(f"{context}.schema_version is unsupported")
        raw_ids = data["card_ids"]
        if not isinstance(raw_ids, list) or not raw_ids:
            raise CardPlaneGeometryError(f"{context}.card_ids must be a non-empty list")
        card_ids = tuple(
            _identifier(value, f"{context}.card_ids[{index}]")
            for index, value in enumerate(raw_ids)
        )
        if len(card_ids) != len(set(card_ids)):
            raise CardPlaneGeometryError(f"{context}.card_ids must be unique")
        raw_edges = data["uncertain_edges"]
        if not isinstance(raw_edges, list):
            raise CardPlaneGeometryError(f"{context}.uncertain_edges must be a list")
        edges: list[tuple[str, str]] = []
        for index, edge in enumerate(raw_edges):
            if not isinstance(edge, list) or len(edge) != 2:
                raise CardPlaneGeometryError(
                    f"{context}.uncertain_edges[{index}] must contain two ids"
                )
            left = _identifier(edge[0], f"{context}.uncertain_edges[{index}][0]")
            right = _identifier(edge[1], f"{context}.uncertain_edges[{index}][1]")
            if left == right or left not in card_ids or right not in card_ids:
                raise CardPlaneGeometryError(
                    f"{context}.uncertain_edges[{index}] references an unknown card"
                )
            edges.append((left, right))
        if not isinstance(data["contradictions"], list):
            raise CardPlaneGeometryError(f"{context}.contradictions must be a list")
        contradictions = tuple(
            _text(value, f"{context}.contradictions[{index}]")
            for index, value in enumerate(data["contradictions"])
        )
        return cls(card_ids=card_ids, uncertain_edges=tuple(edges), contradictions=contradictions)


@dataclass(frozen=True, slots=True)
class PoseFitDiagnostics:
    """Diagnostics for fitting one pose from one immutable suggestion."""

    card_id: str
    source_suggestion_id: str
    residual: float
    accepted: bool
    failure_reason: str | None
    diagnostics_digest: str

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": POSE_FIT_DIAGNOSTICS_SCHEMA_VERSION,
            "card_id": self.card_id,
            "source_suggestion_id": self.source_suggestion_id,
            "residual": _round(self.residual),
            "accepted": self.accepted,
            "failure_reason": self.failure_reason,
        }
        return {**core, "diagnostics_digest": _digest(core)}

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "pose fit diagnostics"
    ) -> "PoseFitDiagnostics":
        data = _mapping(raw, context)
        _strict(
            data,
            {
                "schema_version",
                "card_id",
                "source_suggestion_id",
                "residual",
                "accepted",
                "failure_reason",
                "diagnostics_digest",
            },
            context,
        )
        if data["schema_version"] != POSE_FIT_DIAGNOSTICS_SCHEMA_VERSION:
            raise CardPlaneGeometryError(f"{context}.schema_version is unsupported")
        failure_reason = data["failure_reason"]
        if failure_reason is not None:
            failure_reason = _text(failure_reason, f"{context}.failure_reason")
        core = {
            "schema_version": POSE_FIT_DIAGNOSTICS_SCHEMA_VERSION,
            "card_id": _identifier(data["card_id"], f"{context}.card_id"),
            "source_suggestion_id": _identifier(
                data["source_suggestion_id"], f"{context}.source_suggestion_id"
            ),
            "residual": _round(_finite(data["residual"], f"{context}.residual")),
            "accepted": data["accepted"],
            "failure_reason": failure_reason,
        }
        if not isinstance(core["accepted"], bool):
            raise CardPlaneGeometryError(f"{context}.accepted must be a boolean")
        expected_digest = _digest(core)
        if data["diagnostics_digest"] != expected_digest:
            raise CardPlaneGeometryError(f"{context} digest does not match its contents")
        return cls(
            card_id=core["card_id"],
            source_suggestion_id=core["source_suggestion_id"],
            residual=core["residual"],
            accepted=core["accepted"],
            failure_reason=core["failure_reason"],
            diagnostics_digest=expected_digest,
        )


@dataclass(frozen=True, slots=True)
class ReviewedCardScene:
    """The geometry authority for one exact source frame."""

    source_frame_id: str
    source_frame_width: int
    source_frame_height: int
    calibration_revision_id: str
    calibration_digest: str
    poses: tuple[CardPose, ...]
    stacking_order: CardStackingOrder
    derivation_recipe_version: str
    scene_digest: str

    @classmethod
    def create(
        cls,
        *,
        source_frame_id: str,
        source_frame_width: int,
        source_frame_height: int,
        calibration_revision_id: str,
        calibration_digest: str,
        poses: Sequence[CardPose],
        stacking_order: CardStackingOrder,
    ) -> "ReviewedCardScene":
        pose_values = tuple(poses)
        pose_ids = tuple(pose.card_id for pose in pose_values)
        if not pose_ids or len(pose_ids) != len(set(pose_ids)):
            raise CardPlaneGeometryError("reviewed card scene poses must have unique card ids")
        if pose_ids != stacking_order.card_ids:
            raise CardPlaneGeometryError(
                "stacking order must contain every scene pose exactly once"
            )
        core = {
            "schema_version": REVIEWED_CARD_SCENE_SCHEMA_VERSION,
            "source_frame_id": _identifier(source_frame_id, "source_frame_id"),
            "source_frame_width": _positive_int(source_frame_width, "source_frame_width"),
            "source_frame_height": _positive_int(source_frame_height, "source_frame_height"),
            "calibration_revision_id": _identifier(
                calibration_revision_id, "calibration_revision_id"
            ),
            "calibration_digest": _digest_value(calibration_digest, "calibration_digest"),
            "poses": [pose.to_mapping() for pose in pose_values],
            "stacking_order": stacking_order.to_mapping(),
            "derivation_recipe_version": DERIVATION_RECIPE_VERSION,
        }
        return cls(
            source_frame_id=core["source_frame_id"],
            source_frame_width=core["source_frame_width"],
            source_frame_height=core["source_frame_height"],
            calibration_revision_id=core["calibration_revision_id"],
            calibration_digest=core["calibration_digest"],
            poses=pose_values,
            stacking_order=stacking_order,
            derivation_recipe_version=DERIVATION_RECIPE_VERSION,
            scene_digest=_digest(core),
        )

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": REVIEWED_CARD_SCENE_SCHEMA_VERSION,
            "source_frame_id": self.source_frame_id,
            "source_frame_width": self.source_frame_width,
            "source_frame_height": self.source_frame_height,
            "calibration_revision_id": self.calibration_revision_id,
            "calibration_digest": self.calibration_digest,
            "poses": [pose.to_mapping() for pose in self.poses],
            "stacking_order": self.stacking_order.to_mapping(),
            "derivation_recipe_version": self.derivation_recipe_version,
        }
        return {**core, "scene_digest": _digest(core)}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ReviewedCardScene":
        data = _mapping(raw, "reviewed card scene")
        expected = {
            "schema_version",
            "source_frame_id",
            "source_frame_width",
            "source_frame_height",
            "calibration_revision_id",
            "calibration_digest",
            "poses",
            "stacking_order",
            "derivation_recipe_version",
            "scene_digest",
        }
        _strict(data, expected, "reviewed card scene")
        if data["schema_version"] != REVIEWED_CARD_SCENE_SCHEMA_VERSION:
            raise CardPlaneGeometryError("unsupported reviewed card scene schema")
        if data["derivation_recipe_version"] != DERIVATION_RECIPE_VERSION:
            raise CardPlaneGeometryError("unsupported reviewed card scene derivation recipe")
        if not isinstance(data["poses"], list) or not data["poses"]:
            raise CardPlaneGeometryError("reviewed card scene poses must be a non-empty list")
        poses = tuple(
            CardPose.from_mapping(value, f"reviewed card scene.poses[{index}]")
            for index, value in enumerate(data["poses"])
        )
        order = CardStackingOrder.from_mapping(data["stacking_order"])
        scene = cls.create(
            source_frame_id=data["source_frame_id"],
            source_frame_width=data["source_frame_width"],
            source_frame_height=data["source_frame_height"],
            calibration_revision_id=data["calibration_revision_id"],
            calibration_digest=data["calibration_digest"],
            poses=poses,
            stacking_order=order,
        )
        if data["scene_digest"] != scene.scene_digest:
            raise CardPlaneGeometryError("reviewed card scene digest does not match its contents")
        return scene


@dataclass(frozen=True, slots=True)
class DerivedRegionReceipt:
    """Receipt binding derived visible regions to one scene and calibration."""

    source_frame_id: str
    scene_digest: str
    calibration_digest: str
    region_digests: tuple[str, ...]
    derivation_recipe_version: str
    derived_region_digest: str

    @classmethod
    def create(
        cls,
        *,
        source_frame_id: str,
        scene_digest: str,
        calibration_digest: str,
        region_digests: Sequence[str],
    ) -> "DerivedRegionReceipt":
        core = {
            "schema_version": DERIVED_REGION_RECEIPT_SCHEMA_VERSION,
            "source_frame_id": _identifier(source_frame_id, "source_frame_id"),
            "scene_digest": _digest_value(scene_digest, "scene_digest"),
            "calibration_digest": _digest_value(calibration_digest, "calibration_digest"),
            "region_digests": [
                _digest_value(value, f"region_digests[{index}]")
                for index, value in enumerate(region_digests)
            ],
            "derivation_recipe_version": DERIVATION_RECIPE_VERSION,
        }
        return cls(
            source_frame_id=core["source_frame_id"],
            scene_digest=core["scene_digest"],
            calibration_digest=core["calibration_digest"],
            region_digests=tuple(core["region_digests"]),
            derivation_recipe_version=DERIVATION_RECIPE_VERSION,
            derived_region_digest=_digest(core),
        )

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": DERIVED_REGION_RECEIPT_SCHEMA_VERSION,
            "source_frame_id": self.source_frame_id,
            "scene_digest": self.scene_digest,
            "calibration_digest": self.calibration_digest,
            "region_digests": list(self.region_digests),
            "derivation_recipe_version": self.derivation_recipe_version,
        }
        return {**core, "derived_region_digest": _digest(core)}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "DerivedRegionReceipt":
        data = _mapping(raw, "derived-region receipt")
        expected = {
            "schema_version",
            "source_frame_id",
            "scene_digest",
            "calibration_digest",
            "region_digests",
            "derivation_recipe_version",
            "derived_region_digest",
        }
        _strict(data, expected, "derived-region receipt")
        if data["schema_version"] != DERIVED_REGION_RECEIPT_SCHEMA_VERSION:
            raise CardPlaneGeometryError("unsupported derived-region receipt schema")
        if data["derivation_recipe_version"] != DERIVATION_RECIPE_VERSION:
            raise CardPlaneGeometryError("unsupported derived-region receipt recipe")
        if not isinstance(data["region_digests"], list):
            raise CardPlaneGeometryError("derived-region receipt region_digests must be a list")
        receipt = cls.create(
            source_frame_id=data["source_frame_id"],
            scene_digest=data["scene_digest"],
            calibration_digest=data["calibration_digest"],
            region_digests=data["region_digests"],
        )
        if data["derived_region_digest"] != receipt.derived_region_digest:
            raise CardPlaneGeometryError(
                "derived-region receipt digest does not match its contents"
            )
        return receipt


def validate_derived_region_receipt(
    receipt: DerivedRegionReceipt | Mapping[str, Any],
    *,
    scene_digest: str,
    calibration_digest: str,
) -> DerivedRegionReceipt:
    """Reject a derived view that was made from another scene or calibration."""

    value = (
        receipt
        if isinstance(receipt, DerivedRegionReceipt)
        else DerivedRegionReceipt.from_mapping(receipt)
    )
    if value.scene_digest != _digest_value(scene_digest, "scene_digest"):
        raise CardPlaneGeometryError("derived regions reference a different scene digest")
    if value.calibration_digest != _digest_value(calibration_digest, "calibration_digest"):
        raise CardPlaneGeometryError("derived regions reference a different calibration digest")
    return value


def geometry_contract_manifest() -> dict[str, Any]:
    """Return the frozen M0 constants recorded by a campaign manifest."""

    return {
        "algorithm_version": GEOMETRY_ALGORITHM_VERSION,
        "coordinate_system": COORDINATE_SYSTEM_VERSION,
        "corner_order": CORNER_ORDER_VERSION,
        "angle_convention": ANGLE_CONVENTION_VERSION,
        "numeric_precision_decimals": NUMERIC_PRECISION_DECIMALS,
        "mask_threshold": MASK_THRESHOLD,
        "mask_raster_policy": MASK_RASTER_POLICY,
        "derivation_recipe_version": DERIVATION_RECIPE_VERSION,
        "card_aspect_ratio": CARD_ASPECT_RATIO,
    }


__all__ = [
    "ANGLE_CONVENTION_VERSION",
    "CALIBRATION_CANDIDATE_SCHEMA_VERSION",
    "CARD_ASPECT_RATIO",
    "CARD_POSE_SCHEMA_VERSION",
    "CARD_STACKING_ORDER_SCHEMA_VERSION",
    "COORDINATE_SYSTEM_VERSION",
    "CORNER_ORDER_VERSION",
    "DERIVATION_RECIPE_VERSION",
    "DERIVED_REGION_RECEIPT_SCHEMA_VERSION",
    "GEOMETRY_ALGORITHM_VERSION",
    "MASK_RASTER_POLICY",
    "MASK_THRESHOLD",
    "NUMERIC_PRECISION_DECIMALS",
    "POSE_FIT_DIAGNOSTICS_SCHEMA_VERSION",
    "REVIEWED_CARD_SCENE_SCHEMA_VERSION",
    "TABLE_PLANE_CALIBRATION_SCHEMA_VERSION",
    "CalibrationCandidateReceipt",
    "CardPlaneGeometryError",
    "CardPose",
    "CardStackingOrder",
    "DerivedRegionReceipt",
    "PoseFitDiagnostics",
    "ReviewedCardScene",
    "TablePlaneCalibration",
    "apply_homography",
    "card_quad_from_pose",
    "card_residual",
    "card_vectors",
    "cyclic_quad",
    "derive_visible_masks",
    "fit_table_plane",
    "geometry_contract_manifest",
    "invert_homography",
    "mask_bbox",
    "mask_to_polygons",
    "polygon_area",
    "project_fixed_card",
    "quadrilateral_orientations",
    "rasterize_polygon",
    "remove_small_components",
    "rotate_vector",
    "validate_derived_region_receipt",
]
