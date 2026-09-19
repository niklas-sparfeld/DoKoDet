"""Calibrate one stable table plane and render review-scale synthetic cards.

The renderer uses only an explicit reviewed empty table frame as its background.  It extracts a
per-table paper colour from several reviewed cards in the same recording.  It then applies that
one colour response, a soft rounded alpha edge, and card-scale blur to upright scanned deck cards.
It does not add shadows, glare, or random per-card lighting changes.

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

from .derived_view import DerivedViewCache, FFmpegFrameResolver, resolve_exact_event
from .pipeline_data import RecordingVideoSource
from .reviewed_rfdetr_detector_campaign import canonical_json_bytes
from .rfdetr_segmentation_materialization import validate_rfdetr_coco_annotations
from .synthetic_visible_region_materialization import (
    validate_synthetic_visible_region_inputs,
)
from .synthetic_visible_region_recording_synthesis import (
    MAX_CARD_COUNT_DEFAULT,
    SOURCE_MANIFEST_DEFAULT,
    _quad_array,
    build_synthetic_visible_region_recording_discovery,
)
from .synthetic_visible_region_rendering import (
    CANONICAL_HEIGHT,
    CANONICAL_WIDTH,
    MIN_VISIBLE_PIXELS,
    _alpha_composite,
    _mask_bbox,
    _mask_polygons,
    _occlusion_ratio,
    _polygon_area,
    _quad_to_records,
    _read_cutout,
    _remove_small_components,
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
SCANNED_DECK_SOURCE_DEFAULT = "data/decks/ass-altenburger-romme-french/source"
SAMPLE_COUNT_DEFAULT = 3
CARD_ASPECT_RATIO = 1.5
BACKGROUND_STRATEGY = "explicit-reviewed-empty-table-only-v1"
REFERENCE_CARD_LIMIT = 8
REFERENCE_FRAME_LIMIT = 4
SCAN_ALPHA_INSET_FRACTION = 0.01
SCAN_CORNER_RADIUS_FRACTION = 0.075
SCAN_ALPHA_FEATHER_PIXELS = 1.2
MIN_MASK_ALPHA = 128
CARD_SATURATION_FACTOR = 0.68
CARD_BLUR_REDUCTION_FACTOR = 0.42
CARD_SHADOW_OPACITY = 0.045
CARD_SHADOW_BLUR_SIGMA = 1.4
CARD_SHADOW_OFFSET_PIXELS = (2.0, 2.0)
_SHA256_LENGTH = 64
_REVIEW_CARD_STEMS = (
    "SPADES_ten",
    "DIAMONDS_queen",
    "HEARTS_jack",
    "CLUBS_king",
    "DIAMONDS_ace",
    "HEARTS_ten",
)


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


def _rounded_scan_alpha(width: int, height: int) -> np.ndarray:
    """Return a feathered matte that removes the scan bed and its dark perimeter."""

    inset_x = max(1, int(round(width * SCAN_ALPHA_INSET_FRACTION)))
    inset_y = max(1, int(round(height * SCAN_ALPHA_INSET_FRACTION)))
    radius = max(2, int(round(min(width, height) * SCAN_CORNER_RADIUS_FRACTION)))
    radius = min(radius, (width - 2 * inset_x) // 2, (height - 2 * inset_y) // 2)
    mask = np.zeros((height, width), dtype=np.uint8)
    right, bottom = width - inset_x - 1, height - inset_y - 1
    cv2.rectangle(mask, (inset_x + radius, inset_y), (right - radius, bottom), 255, -1)
    cv2.rectangle(mask, (inset_x, inset_y + radius), (right, bottom - radius), 255, -1)
    for center in (
        (inset_x + radius, inset_y + radius),
        (right - radius, inset_y + radius),
        (inset_x + radius, bottom - radius),
        (right - radius, bottom - radius),
    ):
        cv2.circle(mask, center, radius, 255, thickness=cv2.FILLED, lineType=cv2.LINE_AA)
    return cv2.GaussianBlur(mask, (0, 0), SCAN_ALPHA_FEATHER_PIXELS)


def _scanned_deck_assets(repository: Path, source_directory: str | Path) -> list[dict[str, Any]]:
    """Load upright canonical cards directly from the supplied deck scans."""

    directory = _resolve(repository, source_directory)
    if not directory.is_dir():
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"scanned card source directory is missing: {directory}"
        )
    source_paths = {
        path.stem: path
        for path in sorted(directory.glob("*.webp"))
        if not path.stem.startswith(("BACK_", "JOKER_"))
    }
    missing = [stem for stem in _REVIEW_CARD_STEMS if stem not in source_paths]
    if missing:
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"scanned card source is missing review cards: {', '.join(missing)}"
        )
    source_digest = _sha256_bytes(
        canonical_json_bytes(
            {
                stem: _sha256_file(path)
                for stem, path in sorted(source_paths.items())
            }
        )
    )
    source_group = {
        "id": "0070-ass-altenburger-romme-french-scans",
        "key": source_digest,
        "permission": "training_only",
        "split": "train",
        "table_setup": "canonical-scanned-deck",
    }
    assets: list[dict[str, Any]] = []
    for stem in _REVIEW_CARD_STEMS:
        path = source_paths[stem]
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None or image.ndim != 3 or image.shape[2] != 3:
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"could not decode scanned card {path}"
            )
        source_height, source_width = image.shape[:2]
        canonical = cv2.resize(
            image,
            (CANONICAL_WIDTH, CANONICAL_HEIGHT),
            interpolation=cv2.INTER_CUBIC,
        )
        alpha = _rounded_scan_alpha(CANONICAL_WIDTH, CANONICAL_HEIGHT)
        rgba = np.dstack((canonical, alpha))
        source_sha256 = _sha256_file(path)
        record = {
            "cutout_id": f"scanned-ass-altenburger-romme-french-{stem.lower()}",
            "source_asset_id": f"ass-altenburger-romme-french-{stem.lower()}",
            "deck_card_name": stem,
            "reviewed_decision": {"card_side": "face_up"},
            "source_group": source_group,
            "source_frame": {
                "path": _relative(path, repository),
                "width": source_width,
                "height": source_height,
                "source_file_sha256": source_sha256,
            },
            "source_quadrilateral": [
                {"x": 0.0, "y": 0.0},
                {"x": float(source_width - 1), "y": 0.0},
                {"x": float(source_width - 1), "y": float(source_height - 1)},
                {"x": 0.0, "y": float(source_height - 1)},
            ],
        }
        assets.append({"record": record, "rgba": rgba, "alpha": alpha})
    return assets


def _read_card_asset(asset: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    if "rgba" in asset and "alpha" in asset:
        return np.asarray(asset["rgba"]), np.asarray(asset["alpha"])
    return _read_cutout(asset)


def _selected_scan_assets(
    assets: Sequence[Mapping[str, Any]], card_count: int, scene_index: int
) -> list[Mapping[str, Any]]:
    start = sum(range(scene_index + 1))
    return [assets[(start + offset) % len(assets)] for offset in range(card_count)]


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


def _paper_bgr(image: np.ndarray, support: np.ndarray | None = None) -> np.ndarray:
    """Estimate paper colour from bright, low-saturation pixels inside one card."""

    if image.ndim != 3 or image.shape[2] != 3:
        raise SyntheticVisibleRegionPlanarGeometryError("paper sample is not a BGR image")
    if support is None:
        support = np.full(image.shape[:2], 255, dtype=np.uint8)
    if support.shape != image.shape[:2]:
        raise SyntheticVisibleRegionPlanarGeometryError("paper sample support has wrong dimensions")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    values = hsv[:, :, 2][support >= MIN_MASK_ALPHA]
    if values.size < 64:
        raise SyntheticVisibleRegionPlanarGeometryError("paper sample has too few supported pixels")
    value_floor = float(np.percentile(values, 60))
    selected = (support >= MIN_MASK_ALPHA) & (hsv[:, :, 2] >= value_floor) & (hsv[:, :, 1] <= 96)
    pixels = image[selected]
    if len(pixels) < 64:
        selected = (support >= MIN_MASK_ALPHA) & (hsv[:, :, 2] >= value_floor)
        pixels = image[selected]
    if len(pixels) < 64:
        raise SyntheticVisibleRegionPlanarGeometryError("paper sample has too few white pixels")
    return np.median(pixels.astype(np.float32), axis=0)


def _reference_card_sources(
    discovery: Mapping[str, Any], background: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Select unoccluded face-up reviewed cards from this exact table recording."""

    source_group = background["source_group"]
    recording_id = str(source_group["id"])
    width = int(background["frame_identity"]["width"])
    height = int(background["frame_identity"]["height"])
    dimensions = np.asarray([width, height], dtype=np.float64)
    candidates = []
    for candidate in discovery["candidates"]:
        if (
            not isinstance(candidate, Mapping)
            or candidate.get("source_split") != "train"
            or candidate.get("recording_id") != recording_id
            or candidate.get("table_setup") != source_group.get("table_setup")
            or float(candidate.get("metrics", {}).get("maximum_pairwise_overlap_ratio", 1.0)) > 0.02
        ):
            continue
        candidates.append(candidate)
    cards: list[dict[str, Any]] = []
    used_events: set[str] = set()
    for candidate in sorted(
        candidates, key=lambda item: float(item["selection_score"]), reverse=True
    ):
        event_id = str(candidate["event_id"])
        if len(used_events) >= REFERENCE_FRAME_LIMIT and event_id not in used_events:
            continue
        sides = candidate["card_sides"]
        for card_index, (side, normalized_quad) in enumerate(
            zip(sides, candidate["normalized_quadrilaterals"], strict=True)
        ):
            if side != "face_up":
                continue
            cards.append(
                {
                    "candidate_id": str(candidate["candidate_id"]),
                    "event_id": event_id,
                    "frame_identity": dict(candidate["frame_identity"]),
                    "card_index": card_index,
                    "image_quad": _quad_array(normalized_quad) * dimensions,
                }
            )
            used_events.add(event_id)
            if len(cards) >= REFERENCE_CARD_LIMIT:
                return cards
    if not cards:
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"recording {recording_id} has no usable face-up cards for appearance calibration"
        )
    return cards


def _recording_video_source(
    repository: Path,
    source_manifest_path: str | Path,
    recording_id: str,
    requested_time_us: int,
) -> tuple[Path, RecordingVideoSource]:
    source_manifest = _read_json(
        _resolve(repository, source_manifest_path), "recording source manifest"
    )
    record = next(
        (
            item
            for item in source_manifest.get("recordings", [])
            if isinstance(item, Mapping) and item.get("recording_id") == recording_id
        ),
        None,
    )
    if not isinstance(record, Mapping):
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"recording {recording_id} is absent from the source manifest"
        )
    video_path = _resolve(repository, str(record["source_video_path"]))
    source = RecordingVideoSource(
        recording_id=recording_id,
        relative_path=str(record["source_video_path"]),
        video_sha256=str(record["source_sha256"]),
        byte_length=int(record["source_byte_length"]),
        duration_us=requested_time_us + 1,
    )
    return video_path, source


def _rectified_card_paper(frame: np.ndarray, image_quad: np.ndarray) -> np.ndarray:
    """Rectify a reviewed card so its paper can be sampled without table pixels."""

    source = _cyclic_quad(image_quad).astype(np.float32)
    destination = np.asarray(
        [[0, 0], [159, 0], [159, 239], [0, 239]], dtype=np.float32
    )
    rectified = cv2.warpPerspective(
        frame, cv2.getPerspectiveTransform(source, destination), (160, 240)
    )
    support = np.zeros((240, 160), dtype=np.uint8)
    cv2.rectangle(support, (12, 16), (147, 223), 255, thickness=cv2.FILLED)
    return _paper_bgr(rectified, support)


def _reference_card_short_side(image_quad: np.ndarray) -> float:
    cyclic = _cyclic_quad(image_quad)
    lengths = [
        float(np.linalg.norm(cyclic[(index + 1) % 4] - cyclic[index]))
        for index in range(4)
    ]
    return min(lengths)


def _table_card_appearance(
    repository: Path,
    output_root: Path,
    discovery: Mapping[str, Any],
    background: Mapping[str, Any],
    source_manifest_path: str | Path,
) -> dict[str, Any]:
    """Measure the table's real card paper response from exact reviewed event frames."""

    references = _reference_card_sources(discovery, background)
    recording_id = str(background["source_group"]["id"])
    last_time = max(int(item["frame_identity"]["requested_time_us"]) for item in references)
    video_path, source = _recording_video_source(
        repository, source_manifest_path, recording_id, last_time
    )
    cache = DerivedViewCache(output_root / "appearance-reference-frame-cache")
    resolver = FFmpegFrameResolver()
    frames: dict[str, np.ndarray] = {}
    frame_identities: dict[str, Mapping[str, Any]] = {}
    for index, reference in enumerate(references):
        event_id = str(reference["event_id"])
        if event_id in frames:
            continue
        resolved = resolve_exact_event(
            video_path,
            source=source,
            requested_time_us=int(reference["frame_identity"]["requested_time_us"]),
            cache=cache,
            resolver=resolver,
            validate_source=index == 0,
        )
        expected = reference["frame_identity"]
        if resolved.identity_mapping() != expected:
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"appearance reference frame changed for {event_id}"
            )
        frame = cv2.imdecode(np.frombuffer(resolved.image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"could not decode appearance reference frame {event_id}"
            )
        frames[event_id] = frame
        frame_identities[event_id] = resolved.identity_mapping()
    samples = [
        _rectified_card_paper(frames[str(item["event_id"])], item["image_quad"])
        for item in references
    ]
    paper_bgr = np.median(np.asarray(samples, dtype=np.float32), axis=0)
    short_sides = [_reference_card_short_side(item["image_quad"]) for item in references]
    return {
        "method": "reviewed-face-up-card-paper-median-v1",
        "paper_bgr": [_round(value) for value in paper_bgr],
        "reference_card_count": len(references),
        "reference_frame_count": len(frames),
        "median_short_side_pixels": _round(float(np.median(short_sides))),
        "references": [
            {
                "candidate_id": item["candidate_id"],
                "event_id": item["event_id"],
                "card_index": item["card_index"],
                "frame_identity": frame_identities[str(item["event_id"])],
                "paper_bgr": [_round(value) for value in sample],
            }
            for item, sample in zip(references, samples, strict=True)
        ],
    }


def _white_balanced_scan(
    rgba: np.ndarray, alpha: np.ndarray, target_paper_bgr: Sequence[float]
) -> tuple[np.ndarray, list[float]]:
    source_paper_bgr = _paper_bgr(rgba[:, :, :3], alpha)
    gain = np.clip(
        np.asarray(target_paper_bgr, dtype=np.float32) / np.maximum(source_paper_bgr, 1.0),
        0.55,
        1.20,
    )
    adjusted = np.clip(rgba[:, :, :3].astype(np.float32) * gain, 0, 255).astype(np.uint8)
    return np.dstack((adjusted, alpha)), [_round(value) for value in gain]


def _reduce_scan_saturation(rgba: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Reduce scan pigment saturation to the softer response of the recorded cards."""

    hsv = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] *= CARD_SATURATION_FACTOR
    adjusted = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)
    return np.dstack((adjusted, alpha))


def _card_blur_sigma(image_quad: np.ndarray, appearance: Mapping[str, Any]) -> float:
    short_side = max(_reference_card_short_side(image_quad), 1.0)
    reference_short_side = max(float(appearance["median_short_side_pixels"]), 1.0)
    baseline = np.clip(160.0 / reference_short_side, 0.65, 1.15)
    return float(
        np.clip(
            baseline * np.sqrt(reference_short_side / short_side) * CARD_BLUR_REDUCTION_FACTOR,
            0.22,
            0.58,
        )
    )


def _warp_soft_card(
    rgba: np.ndarray,
    alpha: np.ndarray,
    destination_quad: np.ndarray,
    output_width: int,
    output_height: int,
    blur_sigma: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Warp premultiplied pixels so transparent scan-bed pixels cannot form a hard border."""

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
    alpha_float = alpha.astype(np.float32) / 255.0
    premultiplied = rgba[:, :, :3].astype(np.float32) * alpha_float[:, :, None]
    warped_alpha = cv2.warpPerspective(
        alpha_float, transform, (output_width, output_height), flags=cv2.INTER_LINEAR
    )
    warped_premultiplied = cv2.warpPerspective(
        premultiplied, transform, (output_width, output_height), flags=cv2.INTER_LINEAR
    )
    if blur_sigma > 0:
        warped_alpha = cv2.GaussianBlur(warped_alpha, (0, 0), blur_sigma)
        warped_premultiplied = cv2.GaussianBlur(
            warped_premultiplied, (0, 0), blur_sigma
        )
    result = np.zeros((output_height, output_width, 4), dtype=np.uint8)
    supported = warped_alpha > 1e-5
    result[:, :, :3][supported] = np.clip(
        warped_premultiplied[supported] / warped_alpha[supported][:, None], 0, 255
    ).astype(np.uint8)
    result[:, :, 3] = np.clip(warped_alpha * 255.0, 0, 255).astype(np.uint8)
    return result, result[:, :, 3]


def _apply_subtle_card_shadow(scene: np.ndarray, alpha: np.ndarray) -> None:
    """Put one small, soft table shadow below a card without changing its target mask."""

    shadow = cv2.GaussianBlur(alpha, (0, 0), CARD_SHADOW_BLUR_SIGMA)
    translation = np.float32(
        [[1, 0, CARD_SHADOW_OFFSET_PIXELS[0]], [0, 1, CARD_SHADOW_OFFSET_PIXELS[1]]]
    )
    shadow = cv2.warpAffine(shadow, translation, (scene.shape[1], scene.shape[0]))
    weight = shadow.astype(np.float32) / 255.0 * CARD_SHADOW_OPACITY
    scene[:] = np.clip(scene.astype(np.float32) * (1.0 - weight[:, :, None]), 0, 255).astype(
        np.uint8
    )


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
    appearance: Mapping[str, Any],
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
        rgba, alpha = _read_card_asset(asset)
        image_quad = _apply_homography(table_to_image, table_quad)
        balanced_rgba, white_balance_gain = _white_balanced_scan(
            rgba, alpha, appearance["paper_bgr"]
        )
        adjusted_rgba = _reduce_scan_saturation(balanced_rgba, alpha)
        blur_sigma = _card_blur_sigma(image_quad, appearance)
        warped, warped_alpha = _warp_soft_card(
            adjusted_rgba, alpha, image_quad, width, height, blur_sigma
        )
        full_mask = np.where(warped_alpha >= MIN_MASK_ALPHA, 255, 0).astype(np.uint8)
        full_mask = _remove_small_components(full_mask, MIN_VISIBLE_PIXELS)
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
                "full_mask": full_mask,
                "warped_rgba": warped,
                "alpha": warped_alpha,
                "white_balance_gain_bgr": white_balance_gain,
                "saturation_factor": CARD_SATURATION_FACTOR,
                "blur_sigma": _round(blur_sigma),
                "deck_card_name": record.get("deck_card_name"),
                "source_frame": record.get("source_frame"),
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
        _apply_subtle_card_shadow(scene, placement["alpha"])
    for placement in placements:
        _alpha_composite(scene, placement["warped_rgba"], placement["alpha"])
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
            "deck_card_name": placement["deck_card_name"],
            "side": placement["side"],
            "z_order": placement["z_order"],
            "source_group": placement["source_group"],
            "source_frame": placement["source_frame"],
            "source_quadrilateral": placement["source_quadrilateral"],
            "table_quadrilateral": _quad_to_records(placement["table_quad"]),
            "target_quadrilateral": _quad_to_records(placement["image_quad"]),
            "full_mask_pixels": int(np.count_nonzero(placement["full_mask"])),
            "visible_mask_pixels": visible_pixels,
            "occlusion_ratio": _occlusion_ratio(placement["full_mask"], visible_mask),
            "appearance": {
                "white_balance_gain_bgr": placement["white_balance_gain_bgr"],
                "saturation_factor": placement["saturation_factor"],
                "blur_sigma": placement["blur_sigma"],
                "mask_alpha_threshold": MIN_MASK_ALPHA,
            },
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
        "card_appearance": dict(appearance),
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
            "mask_policy": "rounded-alpha-card-z-order-and-frame-clipping-v1",
            "photometric_policy": (
                "table-paper-white-balance-desaturation-card-scale-blur-and-subtle-shadow-v1"
            ),
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
        "photometric_effects": {
            "table_paper_bgr": appearance["paper_bgr"],
            "reference_card_count": appearance["reference_card_count"],
            "card_saturation_factor": CARD_SATURATION_FACTOR,
            "card_shadow_opacity": CARD_SHADOW_OPACITY,
        },
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
    card_source_directory: str | Path = SCANNED_DECK_SOURCE_DEFAULT,
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
    scanned_assets = _scanned_deck_assets(repository, card_source_directory)

    calibrations: list[dict[str, Any]] = []
    appearances: dict[str, dict[str, Any]] = {}
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
        appearances[str(background["background_id"])] = _table_card_appearance(
            repository,
            output_root,
            discovery,
            background,
            source_manifest_path,
        )
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
        assets = _selected_scan_assets(scanned_assets, len(table_quads), index)
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
            appearance=appearances[str(background["background_id"])],
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
            "card_source_directory": _relative(
                _resolve(repository, card_source_directory), repository
            ),
            "card_source": "upright-ass-altenburger-romme-french-scans-v1",
            "geometry_sources": "complete-reviewed-four-point-cards-from-the-same-recording",
            "photometric_effects": (
                "same-table reviewed-card paper white balance, scan desaturation, rounded alpha, "
                "reduced card-scale blur, and a subtle shadow"
            ),
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
            "shadow, glare, random scene lighting, and compression changes are intentionally "
            "absent from this appearance review",
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
