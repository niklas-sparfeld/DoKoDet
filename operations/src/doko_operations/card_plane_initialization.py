"""Deterministic pose and stacking-order initialization for visible-card review.

This processor converts one exact-frame model result into an editor prefill.  The returned poses
are not reviewed truth.  The source polygons, confidence, provider, and bundle stay attached as
immutable suggestion diagnostics so an operator can compare the prefill with the model evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from .card_plane_geometry import (
    CardPlaneGeometryError,
    CardPose,
    CardStackingOrder,
    PoseFitDiagnostics,
    ReviewedCardScene,
    TablePlaneCalibration,
    apply_homography,
    card_vectors,
    project_fixed_card,
    rasterize_polygon,
)
from .pipeline_data import canonical_json_bytes

INITIALIZATION_PROCESSOR_SCHEMA_VERSION = "card-plane-initialization-processor/v1"
INITIALIZATION_RUN_SCHEMA_VERSION = "card-plane-initialization-run/v1"
POSE_FIT_RECIPE_VERSION = "fixed-card-pose-grid-search/v1"


class CardPlaneInitializationError(ValueError):
    """Raised when a pose-initialization input is invalid."""


class InitializationFailure(CardPlaneInitializationError):
    """An automatic initialization failure that leaves manual card creation available."""

    def __init__(self, code: str, message: str, action: str) -> None:
        self.code = code
        self.message = message
        self.action = action
        super().__init__(f"{code}: {message} Action: {action}")

    def to_mapping(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "action": self.action}


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _copy_json(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value).decode("utf-8"))


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise CardPlaneInitializationError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CardPlaneInitializationError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-:/"
        for character in result
    ):
        raise CardPlaneInitializationError(f"{field} must be a safe identifier")
    return result


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CardPlaneInitializationError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CardPlaneInitializationError(f"{field} must be a finite number")
    return result


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CardPlaneInitializationError(f"{field} must be a positive integer")
    return value


def _point(value: Any, field: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise CardPlaneInitializationError(f"{field} must contain two coordinates")
    return (_finite(value[0], f"{field}[0]"), _finite(value[1], f"{field}[1]"))


def _round(value: float) -> float:
    return round(float(value), 6)


def _polygon_list(value: Any, field: str) -> list[np.ndarray]:
    if (
        isinstance(value, (list, tuple))
        and value
        and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
    ):
        if len(value) % 2 != 0:
            raise CardPlaneInitializationError(f"{field} flat coordinates must be even")
        value = [value[index : index + 2] for index in range(0, len(value), 2)]
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        raise CardPlaneInitializationError(f"{field} must contain at least three points")
    try:
        points = np.asarray([_point(item, f"{field}[{index}]") for index, item in enumerate(value)])
    except (TypeError, ValueError) as error:
        raise CardPlaneInitializationError(f"{field} is malformed") from error
    if points.shape != (len(value), 2) or len(points) < 3:
        raise CardPlaneInitializationError(f"{field} is malformed")
    if abs(float(cv2.contourArea(points.astype(np.float32)))) <= 1e-6:
        raise CardPlaneInitializationError(f"{field} must have positive area")
    return [points]


def _prediction_polygons(prediction: Mapping[str, Any]) -> list[np.ndarray]:
    for field in ("polygon", "points", "segmentation"):
        if field not in prediction:
            continue
        value = prediction[field]
        if (
            field == "segmentation"
            and isinstance(value, (list, tuple))
            and value
            and isinstance(value[0], (list, tuple))
            and value[0]
            and isinstance(value[0][0], (list, tuple))
        ):
            return [
                _polygon_list(item, f"prediction.{field}[{index}]")[0]
                for index, item in enumerate(value)
            ]
        return _polygon_list(value, f"prediction.{field}")
    polygons = prediction.get("polygons")
    if polygons is not None:
        if not isinstance(polygons, (list, tuple)):
            raise CardPlaneInitializationError("prediction.polygons must be a list")
        return [
            _polygon_list(item, f"prediction.polygons[{index}]")[0]
            for index, item in enumerate(polygons)
        ]
    raise CardPlaneInitializationError("prediction has no polygon geometry")


def _confidence(prediction: Mapping[str, Any]) -> float:
    return _finite(prediction.get("confidence", prediction.get("score")), "prediction.confidence")


def _source_frame(result: Mapping[str, Any], source_frame_id: str | None) -> Mapping[str, Any]:
    direct = result.get("frame")
    if isinstance(direct, Mapping):
        frame = direct
    else:
        frames = result.get("frames")
        if not isinstance(frames, list) or not frames:
            raise CardPlaneInitializationError("local result must contain one or more frames")
        if source_frame_id is None and len(frames) != 1:
            raise CardPlaneInitializationError(
                "source_frame_id is required when a local result contains multiple frames"
            )
        selected = frames[0] if source_frame_id is None else None
        if source_frame_id is not None:
            for candidate in frames:
                if not isinstance(candidate, Mapping):
                    continue
                candidate_identity = _frame_identity(candidate)
                if candidate.get("frame_id", candidate_identity.get("frame_id")) == source_frame_id:
                    selected = candidate
                    break
        if not isinstance(selected, Mapping):
            raise CardPlaneInitializationError(f"source frame is missing: {source_frame_id}")
        frame = selected
    identity = _frame_identity(frame)
    actual_id = frame.get("frame_id", identity.get("frame_id", source_frame_id))
    if source_frame_id is not None and actual_id != source_frame_id:
        raise CardPlaneInitializationError("selected source frame ID does not match the frame")
    return frame


def _frame_identity(frame: Mapping[str, Any]) -> Mapping[str, Any]:
    identity = frame.get("frame_identity")
    return identity if isinstance(identity, Mapping) else frame


def _unique_suggestion_id(raw: Any, fallback: str, counts: dict[str, int]) -> str:
    base = _identifier(raw if raw is not None else fallback, "source_suggestion_id")
    occurrence = counts.get(base, 0) + 1
    counts[base] = occurrence
    return base if occurrence == 1 else f"{base}-{occurrence}"


def _model_identity(prediction: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "provider",
        "provider_revision",
        "model",
        "model_id",
        "bundle",
        "bundle_id",
        "model_bundle",
    )
    return {key: _copy_json(prediction[key]) for key in keys if key in prediction}


@dataclass(frozen=True, slots=True)
class PoseFitRecipe:
    """Frozen bounded fitting policy for one initialization processor revision."""

    center_search_radius: float = 0.45
    angle_search_degrees: float = 20.0
    center_steps: int = 7
    angle_steps: int = 9
    refinement_stages: int = 2
    minimum_score: float = 0.18
    low_confidence_score: float = 0.48
    weak_order_margin: float = 0.12
    minimum_order_support: float = 0.08
    minimum_overlap_pixels: int = 4
    edge_width_pixels: int = 3
    occlusion_margin_pixels: int = 4
    edge_distance_tolerance_pixels: float = 8.0

    def __post_init__(self) -> None:
        if self.center_search_radius <= 0.0 or self.angle_search_degrees <= 0.0:
            raise CardPlaneInitializationError("pose search ranges must be positive")
        if self.center_steps < 3 or self.center_steps % 2 == 0:
            raise CardPlaneInitializationError("center_steps must be an odd integer of at least 3")
        if self.angle_steps < 3 or self.angle_steps % 2 == 0:
            raise CardPlaneInitializationError("angle_steps must be an odd integer of at least 3")
        if self.refinement_stages < 0:
            raise CardPlaneInitializationError("refinement_stages must be non-negative")
        if not 0.0 <= self.minimum_score <= self.low_confidence_score <= 1.0:
            raise CardPlaneInitializationError("fit score thresholds must be ordered in [0, 1]")
        if not 0.0 <= self.weak_order_margin <= 1.0:
            raise CardPlaneInitializationError("weak_order_margin must be in [0, 1]")
        if not 0.0 <= self.minimum_order_support <= 1.0:
            raise CardPlaneInitializationError("minimum_order_support must be in [0, 1]")
        if self.minimum_overlap_pixels < 1:
            raise CardPlaneInitializationError("minimum_overlap_pixels must be positive")
        if self.edge_width_pixels < 1:
            raise CardPlaneInitializationError("edge_width_pixels must be positive")
        if self.occlusion_margin_pixels < 0:
            raise CardPlaneInitializationError("occlusion_margin_pixels must not be negative")
        if self.edge_distance_tolerance_pixels <= 0.0:
            raise CardPlaneInitializationError("edge_distance_tolerance_pixels must be positive")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "recipe_version": POSE_FIT_RECIPE_VERSION,
            "center_search_radius": _round(self.center_search_radius),
            "angle_search_degrees": _round(self.angle_search_degrees),
            "center_steps": self.center_steps,
            "angle_steps": self.angle_steps,
            "refinement_stages": self.refinement_stages,
            "minimum_score": _round(self.minimum_score),
            "low_confidence_score": _round(self.low_confidence_score),
            "weak_order_margin": _round(self.weak_order_margin),
            "minimum_order_support": _round(self.minimum_order_support),
            "minimum_overlap_pixels": self.minimum_overlap_pixels,
            "edge_width_pixels": self.edge_width_pixels,
            "occlusion_margin_pixels": self.occlusion_margin_pixels,
            "edge_distance_tolerance_pixels": _round(self.edge_distance_tolerance_pixels),
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_mapping())


@dataclass(frozen=True, slots=True)
class _Candidate:
    suggestion_id: str
    frame_id: str
    polygons: tuple[np.ndarray, ...]
    source_mask: np.ndarray
    confidence: float
    model_identity: Mapping[str, Any]
    table_points: np.ndarray


@dataclass(frozen=True, slots=True)
class _FittedCandidate:
    candidate: _Candidate
    pose: CardPose
    diagnostic: PoseFitDiagnostics
    score: float
    low_confidence: bool
    full_mask: np.ndarray


def _mask_for_prediction(
    polygons: Sequence[np.ndarray], prediction: Mapping[str, Any], width: int, height: int
) -> np.ndarray:
    raw_mask = prediction.get("mask")
    if raw_mask is not None and not isinstance(raw_mask, Mapping):
        mask = np.asarray(raw_mask)
        if mask.ndim == 2 and mask.shape == (height, width):
            return np.where(mask > 0, 255, 0).astype(np.uint8)
    mask = np.zeros((height, width), dtype=np.uint8)
    for polygon in polygons:
        mask = np.maximum(mask, rasterize_polygon(polygon, width, height))
    return mask


def _boundary_mask(mask: np.ndarray, width: int = 1) -> np.ndarray:
    """Return a bounded inner boundary band of a binary source mask."""

    values = np.where(np.asarray(mask) > 0, 255, 0).astype(np.uint8)
    if values.ndim != 2:
        raise CardPlaneInitializationError("source mask must be two-dimensional")
    if width < 1:
        raise CardPlaneInitializationError("boundary width must be positive")
    eroded = cv2.erode(
        values,
        np.ones((width * 2 + 1, width * 2 + 1), dtype=np.uint8),
        borderType=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return np.where((values > 0) & (eroded == 0), 255, 0).astype(np.uint8)


def _dilate_mask(mask: np.ndarray, radius: int) -> np.ndarray:
    """Grow an occluder mask by a bounded source-pixel margin."""

    values = np.where(np.asarray(mask) > 0, 255, 0).astype(np.uint8)
    if values.ndim != 2:
        raise CardPlaneInitializationError("occlusion mask must be two-dimensional")
    if radius == 0:
        return values
    size = radius * 2 + 1
    return cv2.dilate(values, np.ones((size, size), dtype=np.uint8))


def _fit_evidence_mask(
    source_mask: np.ndarray,
    occluder_mask: np.ndarray | None,
    edge_width_pixels: int,
    occlusion_margin_pixels: int,
) -> np.ndarray:
    """Keep only original source-boundary pixels outside fitted-card occlusion."""

    boundary = _boundary_mask(source_mask, edge_width_pixels)
    if occluder_mask is None:
        return boundary
    if np.asarray(occluder_mask).shape != boundary.shape:
        raise CardPlaneInitializationError("occlusion mask shape must match the source mask")
    ignored = _dilate_mask(occluder_mask, occlusion_margin_pixels)
    return np.where((boundary > 0) & (ignored == 0), 255, 0).astype(np.uint8)


def _initial_pose(table_points: np.ndarray) -> tuple[np.ndarray, float]:
    hull = cv2.convexHull(table_points.astype(np.float32)).reshape(-1, 2)
    if len(hull) < 3:
        raise CardPlaneInitializationError("polygon support has fewer than three hull points")
    center = np.median(table_points, axis=0)
    rectangle = cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float64)
    short, long = card_vectors(rectangle)
    short_vector = short if np.linalg.norm(short) <= np.linalg.norm(long) else long
    angle = math.degrees(math.atan2(float(short_vector[1]), float(short_vector[0]))) % 180.0
    return center.astype(np.float64), angle


def _normalized_angle(value: float) -> float:
    return float(value % 180.0)


def _fit_score(full_mask: np.ndarray, source_mask: np.ndarray, source_area: int) -> float:
    intersection = int(np.count_nonzero((full_mask > 0) & (source_mask > 0)))
    if intersection == 0:
        return 0.0
    union = int(np.count_nonzero((full_mask > 0) | (source_mask > 0)))
    full_area = max(int(np.count_nonzero(full_mask)), 1)
    target_area = max(source_area, 1)
    iou = intersection / max(union, 1)
    target_coverage = intersection / target_area
    full_coverage = intersection / full_area
    return float(0.55 * iou + 0.30 * target_coverage + 0.15 * full_coverage)


def _fit_score_projected(
    projected: np.ndarray,
    source_mask: np.ndarray,
    source_area: int,
    source_bounds: tuple[int, int, int, int],
    width: int,
    height: int,
    *,
    edge_only: bool = False,
    edge_width_pixels: int = 1,
    edge_distance_tolerance_pixels: float = 8.0,
    occlusion_mask: np.ndarray | None = None,
) -> float:
    """Score only the union of the source and projected pixel bounds."""

    rounded = np.rint(projected).astype(np.int32)
    source_x, source_y, source_width, source_height = source_bounds
    projected_x0 = max(0, min(width, int(np.min(rounded[:, 0]))))
    projected_y0 = max(0, min(height, int(np.min(rounded[:, 1]))))
    projected_x1 = max(0, min(width, int(np.max(rounded[:, 0])) + 1))
    projected_y1 = max(0, min(height, int(np.max(rounded[:, 1])) + 1))
    x0 = min(source_x, projected_x0)
    y0 = min(source_y, projected_y0)
    x1 = max(source_x + source_width, projected_x1)
    y1 = max(source_y + source_height, projected_y1)
    projected_mask = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    cv2.fillPoly(projected_mask, [rounded - np.asarray([x0, y0], dtype=np.int32)], 255)
    if edge_only:
        projected_boundary = _boundary_mask(projected_mask, edge_width_pixels)
        if occlusion_mask is not None:
            if np.asarray(occlusion_mask).shape != (height, width):
                raise CardPlaneInitializationError("occlusion mask shape must match the frame")
            visible = occlusion_mask[y0:y1, x0:x1] == 0
            projected_mask = np.where((projected_mask > 0) & visible, 255, 0).astype(np.uint8)
            projected_boundary = np.where(
                (projected_boundary > 0) & visible, 255, 0
            ).astype(np.uint8)
        source_evidence = np.where(source_mask[y0:y1, x0:x1] > 0, 255, 0).astype(np.uint8)
        source_points = np.count_nonzero(source_evidence)
        projected_points = np.count_nonzero(projected_boundary)
        if source_points == 0 or projected_points == 0:
            return 0.0

        # Use both directions. This rewards edge alignment and penalizes a card that merely
        # encloses the segment. Clip large gaps so a small amount of missing segmentation does
        # not dominate the score.
        tolerance = max(float(edge_distance_tolerance_pixels), 1e-6)
        source_distance = cv2.distanceTransform(
            np.where(projected_boundary > 0, 0, 255).astype(np.uint8),
            cv2.DIST_L2,
            3,
        )
        projected_distance = cv2.distanceTransform(
            np.where(source_evidence > 0, 0, 255).astype(np.uint8),
            cv2.DIST_L2,
            3,
        )
        source_to_projected = float(
            np.mean(np.minimum(source_distance[source_evidence > 0], tolerance))
        )
        projected_to_source = float(
            np.mean(np.minimum(projected_distance[projected_boundary > 0], tolerance))
        )
        source_edge_score = 1.0 - source_to_projected / tolerance
        projected_edge_score = 1.0 - projected_to_source / tolerance
        source_coverage = float(
            np.count_nonzero((projected_mask > 0) & (source_evidence > 0))
            / max(source_area, 1)
        )
        return float(
            0.55 * source_edge_score
            + 0.30 * projected_edge_score
            + 0.15 * source_coverage
        )
    if edge_only:
        projected_mask = projected_boundary
    return _fit_score(projected_mask, source_mask[y0:y1, x0:x1], source_area)


def _fit_candidate(
    candidate: _Candidate,
    calibration: TablePlaneCalibration,
    recipe: PoseFitRecipe,
    width: int,
    height: int,
    occluder_mask: np.ndarray | None = None,
) -> _FittedCandidate | None:
    try:
        occlusion_aware = occluder_mask is not None
        fit_evidence = (
            _fit_evidence_mask(
                candidate.source_mask,
                occluder_mask,
                recipe.edge_width_pixels,
                recipe.occlusion_margin_pixels,
            )
            if occlusion_aware
            else candidate.source_mask
        )
        source_area = int(np.count_nonzero(fit_evidence))
        if source_area == 0:
            raise CardPlaneInitializationError(
                "prediction has no non-occluded boundary evidence"
            )
        center, angle = _initial_pose(candidate.table_points)
        source_bounds = tuple(int(value) for value in cv2.boundingRect(fit_evidence))
        best: tuple[float, np.ndarray, float] | None = None
        center_radius = recipe.center_search_radius
        angle_radius = recipe.angle_search_degrees
        for _stage in range(recipe.refinement_stages + 1):
            offsets = np.linspace(-1.0, 1.0, recipe.center_steps)
            angle_offsets = np.linspace(-1.0, 1.0, recipe.angle_steps)
            for center_x in offsets:
                for center_y in offsets:
                    trial_center = center + np.asarray(
                        [center_x * center_radius, center_y * center_radius], dtype=np.float64
                    )
                    for angle_offset in angle_offsets:
                        trial_angle = _normalized_angle(angle + angle_offset * angle_radius)
                        projected = project_fixed_card(
                            np.asarray(calibration.table_to_image, dtype=np.float64),
                            trial_center,
                            trial_angle,
                            calibration.card_short_size,
                            calibration.card_long_size,
                        )
                        score = _fit_score_projected(
                            projected,
                            fit_evidence,
                            source_area,
                            source_bounds,
                            width,
                            height,
                            edge_only=occlusion_aware,
                            edge_width_pixels=recipe.edge_width_pixels,
                            edge_distance_tolerance_pixels=recipe.edge_distance_tolerance_pixels,
                            occlusion_mask=occluder_mask,
                        )
                        tie_break = (
                            score,
                            -float(np.linalg.norm(trial_center - center)),
                            -abs(angle_offset * angle_radius),
                            -trial_angle,
                            -float(trial_center[0]),
                            -float(trial_center[1]),
                        )
                        if best is None:
                            best = (score, trial_center.copy(), trial_angle)
                        else:
                            best_score, best_center, best_angle = best
                            best_key = (
                                best_score,
                                -float(np.linalg.norm(best_center - center)),
                                -abs(_normalized_angle(best_angle - angle)),
                                -best_angle,
                                -float(best_center[0]),
                                -float(best_center[1]),
                            )
                            if tie_break > best_key:
                                best = (score, trial_center.copy(), trial_angle)
            if best is None:
                raise CardPlaneInitializationError("pose search produced no candidate")
            center = best[1]
            angle = best[2]
            center_radius /= 3.0
            angle_radius /= 3.0
        score, center, angle = best
        projected = project_fixed_card(
            np.asarray(calibration.table_to_image, dtype=np.float64),
            center,
            angle,
            calibration.card_short_size,
            calibration.card_long_size,
        )
        full_mask = rasterize_polygon(projected, width, height)
        accepted = score >= recipe.minimum_score
        failure_reason = None if accepted else "fit_score_below_threshold"
        card_id = f"pose-{candidate.suggestion_id}"
        diagnostic = PoseFitDiagnostics(
            card_id=card_id,
            source_suggestion_id=candidate.suggestion_id,
            residual=_round(1.0 - score),
            accepted=accepted,
            failure_reason=failure_reason,
            diagnostics_digest="",
        )
        diagnostic = PoseFitDiagnostics.from_mapping(diagnostic.to_mapping())
        pose = CardPose(
            card_id=card_id,
            center=(_round(float(center[0])), _round(float(center[1]))),
            rotation_degrees=_round(angle),
            source_suggestion_id=candidate.suggestion_id,
            fit_diagnostics_digest=diagnostic.diagnostics_digest,
        )
        return _FittedCandidate(
            candidate=candidate,
            pose=pose,
            diagnostic=diagnostic,
            score=_round(score),
            low_confidence=score < recipe.low_confidence_score,
            full_mask=full_mask,
        )
    except (CardPlaneGeometryError, CardPlaneInitializationError, ValueError):
        return None


def _order_candidates(
    candidates: Sequence[_FittedCandidate], recipe: PoseFitRecipe
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...], tuple[str, ...], list[dict[str, Any]]]:
    ordered_candidates = sorted(candidates, key=lambda item: item.pose.card_id)
    ids = [item.pose.card_id for item in ordered_candidates]
    by_id = {item.pose.card_id: item for item in ordered_candidates}
    edges: dict[str, set[str]] = {card_id: set() for card_id in ids}
    indegree = {card_id: 0 for card_id in ids}
    uncertain: set[tuple[str, str]] = set()
    edge_diagnostics: list[dict[str, Any]] = []
    for index, left_id in enumerate(ids):
        for right_id in ids[index + 1 :]:
            left = by_id[left_id]
            right = by_id[right_id]
            overlap = np.where((left.full_mask > 0) & (right.full_mask > 0), 255, 0).astype(
                np.uint8
            )
            overlap_pixels = int(np.count_nonzero(overlap))
            if overlap_pixels < recipe.minimum_overlap_pixels:
                continue
            left_support = (
                int(np.count_nonzero((left.candidate.source_mask > 0) & (overlap > 0)))
                / overlap_pixels
            )
            right_support = (
                int(np.count_nonzero((right.candidate.source_mask > 0) & (overlap > 0)))
                / overlap_pixels
            )
            difference = left_support - right_support
            weak = (
                abs(difference) < recipe.weak_order_margin
                or max(left_support, right_support) < recipe.minimum_order_support
            )
            record = {
                "front_candidate_ids": [left_id, right_id],
                "overlap_pixels": overlap_pixels,
                "left_support": _round(left_support),
                "right_support": _round(right_support),
                "difference": _round(difference),
                "decision": "uncertain" if weak else ("left" if difference > 0 else "right"),
            }
            edge_diagnostics.append(record)
            if weak:
                uncertain.add(tuple(sorted((left_id, right_id))))
                continue
            front, back = (left_id, right_id) if difference > 0 else (right_id, left_id)
            if back not in edges[front]:
                edges[front].add(back)
                indegree[back] += 1

    remaining = set(ids)
    result: list[str] = []
    contradictions: list[str] = []
    while remaining:
        available = sorted(card_id for card_id in remaining if indegree[card_id] == 0)
        if not available:
            cycle = tuple(sorted(remaining))
            contradictions.append("cycle:" + ",".join(cycle))
            available = [cycle[0]]
        selected = available[0]
        result.append(selected)
        remaining.remove(selected)
        for successor in edges[selected]:
            indegree[successor] -= 1
    return tuple(result), tuple(sorted(uncertain)), tuple(sorted(contradictions)), edge_diagnostics


@dataclass(frozen=True, slots=True)
class InitializationRun:
    """Deterministic initial scene plus all fit and order diagnostics."""

    source_frame_id: str
    calibration_revision_id: str
    status: str
    scene: ReviewedCardScene | None
    suggestions: tuple[Mapping[str, Any], ...]
    fit_diagnostics: tuple[PoseFitDiagnostics, ...]
    diagnostics: Mapping[str, Any]
    failure: InitializationFailure | None
    run_digest: str

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": INITIALIZATION_RUN_SCHEMA_VERSION,
            "source_frame_id": self.source_frame_id,
            "calibration_revision_id": self.calibration_revision_id,
            "status": self.status,
            "scene": self.scene.to_mapping() if self.scene is not None else None,
            "suggestions": [_copy_json(value) for value in self.suggestions],
            "fit_diagnostics": [value.to_mapping() for value in self.fit_diagnostics],
            "diagnostics": _copy_json(self.diagnostics),
            "failure": self.failure.to_mapping() if self.failure is not None else None,
        }
        return {**core, "run_digest": _digest(core)}


def initialize_card_scene(
    result: Mapping[str, Any],
    calibration: TablePlaneCalibration | Mapping[str, Any],
    *,
    source_frame_id: str | None = None,
    recipe: PoseFitRecipe | None = None,
) -> InitializationRun:
    """Initialize fixed-size poses and a frame-local front-to-back order."""

    local_result = _mapping(result, "local result")
    selected_calibration = (
        calibration
        if isinstance(calibration, TablePlaneCalibration)
        else TablePlaneCalibration.from_mapping(_mapping(calibration, "calibration"))
    )
    selected_recipe = PoseFitRecipe() if recipe is None else recipe
    if not isinstance(selected_recipe, PoseFitRecipe):
        raise CardPlaneInitializationError("recipe must be a PoseFitRecipe")
    frame = _source_frame(local_result, source_frame_id)
    identity = _frame_identity(frame)
    frame_id = _identifier(
        frame.get("frame_id", identity.get("frame_id", source_frame_id)), "source_frame_id"
    )
    width = _positive_int(identity.get("width"), "source_frame.width")
    height = _positive_int(identity.get("height"), "source_frame.height")
    if (width, height) != (
        selected_calibration.frame_width,
        selected_calibration.frame_height,
    ):
        raise CardPlaneInitializationError(
            "source frame dimensions do not match the selected calibration revision"
        )
    result_revision = local_result.get("source_revision", local_result.get("revision_id"))
    if result_revision is not None and result_revision != selected_calibration.source_revision:
        raise CardPlaneInitializationError(
            "local result source revision does not match the selected calibration revision"
        )
    predictions = frame.get("predictions", frame.get("cards", frame.get("candidates", [])))
    if not isinstance(predictions, list):
        raise CardPlaneInitializationError("source frame predictions must be a list")

    counts: dict[str, int] = {}
    suggestions: list[Mapping[str, Any]] = []
    fit_diagnostics: list[PoseFitDiagnostics] = []
    fitted: list[_FittedCandidate] = []
    failures: dict[str, str] = {}
    low_confidence: list[str] = []
    for index, raw_prediction in enumerate(predictions):
        fit_result: _FittedCandidate | None = None
        prediction = _mapping(raw_prediction, f"predictions[{index}]")
        suggestion_id = _unique_suggestion_id(
            prediction.get("candidate_id", prediction.get("prediction_id")),
            f"{frame_id}-{index:04d}",
            counts,
        )
        confidence_error: str | None = None
        try:
            prediction_confidence = _round(_confidence(prediction))
        except CardPlaneInitializationError as error:
            prediction_confidence = 0.0
            confidence_error = str(error)
            failures[suggestion_id] = confidence_error
        base_suggestion: dict[str, Any] = {
            "source_suggestion_id": suggestion_id,
            "source_frame_id": frame_id,
            "confidence": prediction_confidence,
            "model_identity": _model_identity(prediction),
        }
        try:
            if confidence_error is not None:
                raise CardPlaneInitializationError(confidence_error)
            polygons = tuple(_prediction_polygons(prediction))
            source_mask = _mask_for_prediction(polygons, prediction, width, height)
            table_points = apply_homography(
                np.asarray(selected_calibration.image_to_table, dtype=np.float64),
                np.concatenate(polygons, axis=0),
            )
            candidate = _Candidate(
                suggestion_id=suggestion_id,
                frame_id=frame_id,
                polygons=polygons,
                source_mask=source_mask,
                confidence=prediction_confidence,
                model_identity=base_suggestion["model_identity"],
                table_points=table_points,
            )
            base_suggestion["polygons"] = [
                [[_round(float(point[0])), _round(float(point[1]))] for point in polygon]
                for polygon in polygons
            ]
            fit_result = _fit_candidate(
                candidate, selected_calibration, selected_recipe, width, height
            )
            if fit_result is None:
                failures[suggestion_id] = "pose_fit_failed"
            elif not fit_result.diagnostic.accepted:
                failures[suggestion_id] = fit_result.diagnostic.failure_reason or "pose_fit_failed"
                fit_diagnostics.append(fit_result.diagnostic)
            else:
                fitted.append(fit_result)
        except (CardPlaneInitializationError, CardPlaneGeometryError, ValueError) as error:
            failures[suggestion_id] = str(error)
        suggestions.append(base_suggestion)
        if fit_result is None:
            card_id = f"pose-{suggestion_id}"
            diagnostic = PoseFitDiagnostics.from_mapping(
                PoseFitDiagnostics(
                    card_id=card_id,
                    source_suggestion_id=suggestion_id,
                    residual=1.0,
                    accepted=False,
                    failure_reason=failures.get(suggestion_id, "pose_fit_failed"),
                    diagnostics_digest="",
                ).to_mapping()
            )
            if not any(item.source_suggestion_id == suggestion_id for item in fit_diagnostics):
                fit_diagnostics.append(diagnostic)
    fitted.sort(key=lambda item: item.pose.card_id)
    provisional_order, _provisional_uncertain, _provisional_contradictions, _ = (
        _order_candidates(fitted, selected_recipe) if fitted else ((), (), (), [])
    )
    provisional_by_id = {item.pose.card_id: item for item in fitted}
    occluder = np.zeros((height, width), dtype=np.uint8)
    refitted: list[_FittedCandidate] = []
    occlusion_refit_count = 0
    for card_id in provisional_order:
        provisional = provisional_by_id[card_id]
        occlusion_overlap = int(
            np.count_nonzero(
                (provisional.candidate.source_mask > 0)
                & (_dilate_mask(occluder, selected_recipe.occlusion_margin_pixels) > 0)
            )
        )
        refined = (
            _fit_candidate(
                provisional.candidate,
                selected_calibration,
                selected_recipe,
                width,
                height,
                occluder_mask=occluder,
            )
            if occlusion_overlap > 0
            else None
        )
        selected = (
            refined
            if refined is not None and refined.diagnostic.accepted
            else provisional
        )
        if refined is not None and refined.diagnostic.accepted:
            occlusion_refit_count += 1
        refitted.append(selected)
        occluder = np.maximum(occluder, selected.full_mask)
    fitted = sorted(refitted, key=lambda item: item.pose.card_id)
    fit_diagnostics.extend(item.diagnostic for item in fitted)
    fit_diagnostics.sort(key=lambda item: item.source_suggestion_id)
    low_confidence = [
        item.candidate.suggestion_id for item in fitted if item.low_confidence
    ]
    order, uncertain_edges, contradictions, edge_diagnostics = (
        _order_candidates(fitted, selected_recipe) if fitted else ((), (), (), [])
    )
    by_id = {item.pose.card_id: item for item in fitted}
    ordered_fitted = [by_id[card_id] for card_id in order]
    scene = None
    failure: InitializationFailure | None = None
    if ordered_fitted:
        stacking = CardStackingOrder(
            card_ids=order,
            uncertain_edges=uncertain_edges,
            contradictions=contradictions,
        )
        scene = ReviewedCardScene.create(
            source_frame_id=frame_id,
            source_frame_width=width,
            source_frame_height=height,
            calibration_revision_id=selected_calibration.calibration_revision_id,
            calibration_digest=selected_calibration.calibration_digest,
            poses=[item.pose for item in ordered_fitted],
            stacking_order=stacking,
        )
        status = "initialized"
    else:
        failure = InitializationFailure(
            "no_initialized_candidates",
            "no model polygon produced an initial fixed-size card pose",
            "create a card manually on the calibrated table or mark the frame unusable",
        )
        status = "failed"
    diagnostics = {
        "processor_schema_version": INITIALIZATION_PROCESSOR_SCHEMA_VERSION,
        "recipe": selected_recipe.to_mapping(),
        "recipe_digest": selected_recipe.digest,
        "source_frame_id": frame_id,
        "calibration_revision_id": selected_calibration.calibration_revision_id,
        "candidate_count": len(predictions),
        "initialized_count": len(fitted),
        "failed_suggestion_ids": sorted(failures),
        "failure_reasons": {key: failures[key] for key in sorted(failures)},
        "low_confidence_suggestion_ids": sorted(low_confidence),
        "occlusion_refit": {
            "margin_pixels": selected_recipe.occlusion_margin_pixels,
            "provisional_order": list(provisional_order),
            "refitted_count": occlusion_refit_count,
        },
        "order": {
            "edges": edge_diagnostics,
            "uncertain_edges": [list(edge) for edge in uncertain_edges],
            "contradictions": list(contradictions),
        },
    }
    core = {
        "schema_version": INITIALIZATION_RUN_SCHEMA_VERSION,
        "source_frame_id": frame_id,
        "calibration_revision_id": selected_calibration.calibration_revision_id,
        "status": status,
        "scene": scene.to_mapping() if scene is not None else None,
        "suggestions": [_copy_json(value) for value in suggestions],
        "fit_diagnostics": [value.to_mapping() for value in fit_diagnostics],
        "diagnostics": _copy_json(diagnostics),
        "failure": failure.to_mapping() if failure is not None else None,
    }
    return InitializationRun(
        source_frame_id=frame_id,
        calibration_revision_id=selected_calibration.calibration_revision_id,
        status=status,
        scene=scene,
        suggestions=tuple(_copy_json(value) for value in suggestions),
        fit_diagnostics=tuple(fit_diagnostics),
        diagnostics=diagnostics,
        failure=failure,
        run_digest=_digest(core),
    )


__all__ = [
    "INITIALIZATION_PROCESSOR_SCHEMA_VERSION",
    "INITIALIZATION_RUN_SCHEMA_VERSION",
    "POSE_FIT_RECIPE_VERSION",
    "CardPlaneInitializationError",
    "InitializationFailure",
    "InitializationRun",
    "PoseFitRecipe",
    "initialize_card_scene",
]
