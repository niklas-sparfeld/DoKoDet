"""Deterministic recording-global calibration for pose-based card review.

The processor consumes a complete recording-local prediction result and publishes only a
processor-owned table-plane calibration.  It does not infer card identity, gameplay, or reviewed
geometry.  Input predictions remain suggestions and are retained in candidate receipts only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .card_plane_geometry import (
    CalibrationCandidateReceipt,
    CardPlaneGeometryError,
    TablePlaneCalibration,
    apply_homography,
    card_residual,
    card_vectors,
    fit_table_plane,
    polygon_area,
    project_fixed_card,
    quadrilateral_orientations,
    rasterize_polygon,
)
from .pipeline_data import canonical_json_bytes

CALIBRATION_PROCESSOR_SCHEMA_VERSION = "card-plane-calibration-processor/v1"
CALIBRATION_RUN_SCHEMA_VERSION = "card-plane-calibration-run/v1"
CALIBRATION_STORE_DIRECTORY = "table-plane-calibrations"


class CardPlaneCalibrationError(ValueError):
    """Raised when a calibration input or stored revision is invalid."""


class CalibrationFailure(CardPlaneCalibrationError):
    """An actionable automatic calibration failure."""

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


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CardPlaneCalibrationError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-:/"
        for character in result
    ):
        raise CardPlaneCalibrationError(f"{field} must be a safe identifier")
    return result


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise CardPlaneCalibrationError(f"{field} must be an object")
    return value


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CardPlaneCalibrationError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CardPlaneCalibrationError(f"{field} must be a finite number")
    return result


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CardPlaneCalibrationError(f"{field} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class CalibrationRecipe:
    """Frozen candidate and validation policy for one calibration processor revision."""

    confidence_threshold: float = 0.90
    frame_boundary_margin_px: int = 2
    expanded_box_margin_px: int = 6
    minimum_quad_coverage: float = 0.84
    temporal_bin_us: int = 1_000_000
    temporal_bin_frames: int = 30
    table_position_grid: int = 8
    scale_bin_octaves: float = 0.25
    orientation_bin_degrees: float = 15.0
    minimum_candidates: int = 6
    minimum_temporal_bins: int = 3
    minimum_position_bins: int = 3
    minimum_orientation_bins: int = 2
    minimum_held_out_candidates: int = 2
    holdout_modulus: int = 4
    minimum_spatial_coverage_x: float = 0.25
    minimum_spatial_coverage_y: float = 0.25
    maximum_held_out_alignment_px: float = 12.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise CardPlaneCalibrationError("confidence_threshold must be between zero and one")
        if not self.frame_boundary_margin_px >= 0 or not self.expanded_box_margin_px >= 0:
            raise CardPlaneCalibrationError("pixel margins must be non-negative")
        if not 0.0 < self.minimum_quad_coverage <= 1.0:
            raise CardPlaneCalibrationError("minimum_quad_coverage must be in (0, 1]")
        for field in (
            "temporal_bin_us",
            "temporal_bin_frames",
            "table_position_grid",
            "minimum_candidates",
            "minimum_temporal_bins",
            "minimum_position_bins",
            "minimum_orientation_bins",
            "minimum_held_out_candidates",
            "holdout_modulus",
        ):
            _positive_int(getattr(self, field), field)
        if self.scale_bin_octaves <= 0 or self.orientation_bin_degrees <= 0:
            raise CardPlaneCalibrationError("scale and orientation bins must be positive")
        for field in ("minimum_spatial_coverage_x", "minimum_spatial_coverage_y"):
            value = getattr(self, field)
            if not 0.0 <= value <= 1.0:
                raise CardPlaneCalibrationError(f"{field} must be between zero and one")
        if self.maximum_held_out_alignment_px <= 0:
            raise CardPlaneCalibrationError("maximum_held_out_alignment_px must be positive")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": CALIBRATION_PROCESSOR_SCHEMA_VERSION,
            "confidence_threshold": self.confidence_threshold,
            "frame_boundary_margin_px": self.frame_boundary_margin_px,
            "expanded_box_margin_px": self.expanded_box_margin_px,
            "minimum_quad_coverage": self.minimum_quad_coverage,
            "temporal_bin_us": self.temporal_bin_us,
            "temporal_bin_frames": self.temporal_bin_frames,
            "table_position_grid": self.table_position_grid,
            "scale_bin_octaves": self.scale_bin_octaves,
            "orientation_bin_degrees": self.orientation_bin_degrees,
            "minimum_candidates": self.minimum_candidates,
            "minimum_temporal_bins": self.minimum_temporal_bins,
            "minimum_position_bins": self.minimum_position_bins,
            "minimum_orientation_bins": self.minimum_orientation_bins,
            "minimum_held_out_candidates": self.minimum_held_out_candidates,
            "holdout_modulus": self.holdout_modulus,
            "minimum_spatial_coverage_x": self.minimum_spatial_coverage_x,
            "minimum_spatial_coverage_y": self.minimum_spatial_coverage_y,
            "maximum_held_out_alignment_px": self.maximum_held_out_alignment_px,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_mapping())


@dataclass(frozen=True, slots=True)
class _Observation:
    candidate_id: str
    source_revision: str
    source_frame_id: str
    confidence: float
    quadrilateral: np.ndarray
    frame_width: int
    frame_height: int
    temporal_bin: str
    table_position_bin: str
    scale_bin: str
    orientation_bin: str
    expanded_box: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class CalibrationRun:
    """Deterministic calibration output or diagnostics for an automatic failure."""

    recording_id: str
    source_revision: str
    status: str
    candidate_receipts: tuple[CalibrationCandidateReceipt, ...]
    diagnostics: Mapping[str, Any]
    calibration: TablePlaneCalibration | None
    failure: CalibrationFailure | None
    run_digest: str

    def __post_init__(self) -> None:
        if self.status not in {"published", "failed"}:
            raise CardPlaneCalibrationError("calibration run status is unsupported")
        if (self.status == "published") != (self.calibration is not None):
            raise CardPlaneCalibrationError("published status must match calibration presence")
        if (self.status == "failed") != (self.failure is not None):
            raise CardPlaneCalibrationError("failed status must match failure presence")

    def to_mapping(self) -> dict[str, Any]:
        core: dict[str, Any] = {
            "schema_version": CALIBRATION_RUN_SCHEMA_VERSION,
            "recording_id": self.recording_id,
            "source_revision": self.source_revision,
            "status": self.status,
            "candidate_receipts": [item.to_mapping() for item in self.candidate_receipts],
            "diagnostics": _copy_json(self.diagnostics),
            "calibration": None if self.calibration is None else self.calibration.to_mapping(),
            "failure": None if self.failure is None else self.failure.to_mapping(),
        }
        return {**core, "run_digest": _digest(core)}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CalibrationRun":
        data = _mapping(raw, "calibration run")
        expected = {
            "schema_version",
            "recording_id",
            "source_revision",
            "status",
            "candidate_receipts",
            "diagnostics",
            "calibration",
            "failure",
            "run_digest",
        }
        if set(data) != expected:
            raise CardPlaneCalibrationError("calibration run has invalid fields")
        if data["schema_version"] != CALIBRATION_RUN_SCHEMA_VERSION:
            raise CardPlaneCalibrationError("calibration run schema is unsupported")
        receipts_raw = data["candidate_receipts"]
        if not isinstance(receipts_raw, list):
            raise CardPlaneCalibrationError("calibration run candidate receipts must be a list")
        receipts = tuple(CalibrationCandidateReceipt.from_mapping(item) for item in receipts_raw)
        calibration_raw = data["calibration"]
        calibration = (
            None
            if calibration_raw is None
            else TablePlaneCalibration.from_mapping(_mapping(calibration_raw, "calibration"))
        )
        failure_raw = data["failure"]
        failure = None
        if failure_raw is not None:
            failure_data = _mapping(failure_raw, "calibration failure")
            if set(failure_data) != {"code", "message", "action"}:
                raise CardPlaneCalibrationError("calibration failure has invalid fields")
            failure = CalibrationFailure(
                _text(failure_data["code"], "failure.code"),
                _text(failure_data["message"], "failure.message"),
                _text(failure_data["action"], "failure.action"),
            )
        result = cls(
            recording_id=_identifier(data["recording_id"], "recording_id"),
            source_revision=_identifier(data["source_revision"], "source_revision"),
            status=_text(data["status"], "status"),
            candidate_receipts=receipts,
            diagnostics=_mapping(data["diagnostics"], "diagnostics"),
            calibration=calibration,
            failure=failure,
            run_digest=_text(data["run_digest"], "run_digest"),
        )
        if result.run_digest != _digest(result.to_mapping_without_digest()):
            raise CardPlaneCalibrationError("calibration run digest does not match its contents")
        if calibration is not None and calibration.recording_id != result.recording_id:
            raise CardPlaneCalibrationError("calibration recording does not match the run")
        return result

    def to_mapping_without_digest(self) -> dict[str, Any]:
        mapping = self.to_mapping()
        mapping.pop("run_digest", None)
        return mapping


def _failure_run(
    recording_id: str,
    source_revision: str,
    receipts: Sequence[CalibrationCandidateReceipt],
    diagnostics: Mapping[str, Any],
    failure: CalibrationFailure,
) -> CalibrationRun:
    core = {
        "schema_version": CALIBRATION_RUN_SCHEMA_VERSION,
        "recording_id": recording_id,
        "source_revision": source_revision,
        "status": "failed",
        "candidate_receipts": [item.to_mapping() for item in receipts],
        "diagnostics": _copy_json(diagnostics),
        "calibration": None,
        "failure": failure.to_mapping(),
    }
    return CalibrationRun(
        recording_id=recording_id,
        source_revision=source_revision,
        status="failed",
        candidate_receipts=tuple(receipts),
        diagnostics=_copy_json(diagnostics),
        calibration=None,
        failure=failure,
        run_digest=_digest(core),
    )


def _published_run(
    recording_id: str,
    source_revision: str,
    receipts: Sequence[CalibrationCandidateReceipt],
    diagnostics: Mapping[str, Any],
    calibration: TablePlaneCalibration,
) -> CalibrationRun:
    core = {
        "schema_version": CALIBRATION_RUN_SCHEMA_VERSION,
        "recording_id": recording_id,
        "source_revision": source_revision,
        "status": "published",
        "candidate_receipts": [item.to_mapping() for item in receipts],
        "diagnostics": _copy_json(diagnostics),
        "calibration": calibration.to_mapping(),
        "failure": None,
    }
    return CalibrationRun(
        recording_id=recording_id,
        source_revision=source_revision,
        status="published",
        candidate_receipts=tuple(receipts),
        diagnostics=_copy_json(diagnostics),
        calibration=calibration,
        failure=None,
        run_digest=_digest(core),
    )


def _frame_identity(frame: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = frame.get("frame_identity")
    return nested if isinstance(nested, Mapping) else frame


def _frame_value(frame: Mapping[str, Any], identity: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in frame:
            return frame[name]
        if name in identity:
            return identity[name]
    return None


def _source_transform_key(frame: Mapping[str, Any], identity: Mapping[str, Any]) -> str:
    value = _frame_value(
        frame,
        identity,
        "source_transform_digest",
        "source_transform",
        "transform_digest",
    )
    if value is None:
        return "identity"
    if isinstance(value, str):
        return _identifier(value, "source_transform")
    return _digest(value)


def _point(value: Any, field: str) -> tuple[float, float]:
    if isinstance(value, Mapping):
        return (_finite(value.get("x"), f"{field}.x"), _finite(value.get("y"), f"{field}.y"))
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise CardPlaneCalibrationError(f"{field} must contain two coordinates")
    return (_finite(value[0], f"{field}[0]"), _finite(value[1], f"{field}[1]"))


def _polygon_list(value: Any, field: str) -> list[np.ndarray]:
    if (
        isinstance(value, (list, tuple))
        and value
        and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
    ):
        if len(value) % 2 != 0:
            raise CardPlaneCalibrationError(f"{field} flat coordinates must be even")
        value = [value[index : index + 2] for index in range(0, len(value), 2)]
    if not isinstance(value, (list, tuple)):
        raise CardPlaneCalibrationError(f"{field} must be a polygon")
    try:
        points = np.asarray([_point(item, f"{field}[{index}]") for index, item in enumerate(value)])
    except (TypeError, ValueError) as error:
        raise CardPlaneCalibrationError(f"{field} is malformed") from error
    if points.shape != (4, 2) and len(points) < 3:
        raise CardPlaneCalibrationError(f"{field} must contain at least three points")
    return [points]


def _prediction_polygons(prediction: Mapping[str, Any]) -> list[np.ndarray]:
    for field in ("polygon", "points", "segmentation"):
        if field in prediction:
            value = prediction[field]
            if (
                field == "segmentation"
                and isinstance(value, (list, tuple))
                and value
                and isinstance(value[0], (list, tuple))
            ):
                return [
                    _polygon_list(item, f"prediction.{field}[{index}]")[0]
                    for index, item in enumerate(value)
                ]
            return _polygon_list(value, f"prediction.{field}")
    polygons = prediction.get("polygons")
    if polygons is not None:
        if not isinstance(polygons, (list, tuple)):
            raise CardPlaneCalibrationError("prediction.polygons must be a list")
        return [
            _polygon_list(item, f"prediction.polygons[{index}]")[0]
            for index, item in enumerate(polygons)
        ]
    geometry = prediction.get("geometry")
    if isinstance(geometry, Mapping):
        visible = geometry.get("visible_region")
        if isinstance(visible, Mapping) and "polygons" in visible:
            return _prediction_polygons({"polygons": visible["polygons"]})
    raise CardPlaneCalibrationError("prediction has no polygon geometry")


def _prediction_confidence(prediction: Mapping[str, Any]) -> float:
    value = prediction.get("confidence", prediction.get("score"))
    return _finite(value, "prediction.confidence")


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


def _fit_quad(
    polygons: Sequence[np.ndarray], mask: np.ndarray, minimum_coverage: float
) -> tuple[np.ndarray, float] | None:
    points = np.concatenate(polygons, axis=0).astype(np.float32)
    hull = cv2.convexHull(points)
    if len(hull) < 3:
        return None
    perimeter = cv2.arcLength(hull, True)
    candidates: list[tuple[float, np.ndarray]] = []
    for fraction in (0.005, 0.01, 0.02, 0.04, 0.08, 0.12):
        approximation = cv2.approxPolyDP(hull, fraction * perimeter, True).reshape(-1, 2)
        if len(approximation) == 4 and cv2.isContourConvex(approximation.reshape(-1, 1, 2)):
            candidates.append((polygon_area(approximation), approximation.astype(np.float64)))
    if not candidates:
        rectangle = cv2.boxPoints(cv2.minAreaRect(points)).astype(np.float64)
        candidates.append((polygon_area(rectangle), rectangle))
    mask_area = max(float(np.count_nonzero(mask)), 1.0)
    scored: list[tuple[float, np.ndarray, float]] = []
    for _area, candidate in candidates:
        candidate_mask = rasterize_polygon(candidate, mask.shape[1], mask.shape[0])
        intersection = np.count_nonzero((candidate_mask > 0) & (mask > 0))
        coverage = float(intersection) / mask_area
        union = np.count_nonzero((candidate_mask > 0) | (mask > 0))
        iou = float(intersection) / max(float(union), 1.0)
        scored.append((iou, candidate, coverage))
    iou, quad, coverage = max(scored, key=lambda item: (item[0], item[2], -polygon_area(item[1])))
    if iou < minimum_coverage or coverage < minimum_coverage:
        return None
    return quad, 1.0 - iou


def _bin_observation(
    quad: np.ndarray,
    width: int,
    height: int,
    frame: Mapping[str, Any],
    recipe: CalibrationRecipe,
) -> tuple[str, str, str, str]:
    center = np.mean(quad, axis=0)
    x_bin = min(
        recipe.table_position_grid - 1, max(0, int(center[0] / width * recipe.table_position_grid))
    )
    y_bin = min(
        recipe.table_position_grid - 1, max(0, int(center[1] / height * recipe.table_position_grid))
    )
    position = f"p-{x_bin}-{y_bin}"
    short, long = card_vectors(quad)
    scale = max(float(np.sqrt(np.linalg.norm(short) * np.linalg.norm(long))), 1e-9)
    scale_bin = f"s-{math.floor(math.log2(scale) / recipe.scale_bin_octaves)}"
    angle = math.degrees(math.atan2(float(short[1]), float(short[0]))) % 180.0
    orientation_bin = f"o-{math.floor(angle / recipe.orientation_bin_degrees)}"
    timestamp = frame.get("timestamp_us")
    if timestamp is None:
        timestamp = (
            frame.get("frame_index", 0) * recipe.temporal_bin_us / recipe.temporal_bin_frames
        )
    temporal_bin = f"t-{int(float(timestamp) // recipe.temporal_bin_us)}"
    return temporal_bin, position, scale_bin, orientation_bin


def _expanded_box(quad: np.ndarray, margin: int) -> tuple[float, float, float, float]:
    x_min, y_min = np.min(quad, axis=0)
    x_max, y_max = np.max(quad, axis=0)
    return (
        float(x_min - margin),
        float(y_min - margin),
        float(x_max + margin),
        float(y_max + margin),
    )


def _boxes_overlap(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> bool:
    return left[0] < right[2] and right[0] < left[2] and left[1] < right[3] and right[1] < left[3]


def _candidate_receipt(
    observation: _Observation, accepted: bool, reason: str | None
) -> CalibrationCandidateReceipt:
    return CalibrationCandidateReceipt.create(
        candidate_id=observation.candidate_id,
        source_revision=observation.source_revision,
        source_frame_id=observation.source_frame_id,
        confidence=observation.confidence,
        quadrilateral=observation.quadrilateral.tolist(),
        temporal_bin=observation.temporal_bin,
        table_position_bin=observation.table_position_bin,
        scale_bin=observation.scale_bin,
        orientation_bin=observation.orientation_bin,
        accepted=accepted,
        rejection_reason=reason,
    )


def _failure(
    code: str,
    message: str,
    action: str,
    diagnostics: Mapping[str, Any],
    recording_id: str,
    source_revision: str,
    receipts: Sequence[CalibrationCandidateReceipt],
) -> CalibrationRun:
    return _failure_run(
        recording_id,
        source_revision,
        sorted(receipts, key=lambda item: item.candidate_id),
        diagnostics,
        CalibrationFailure(code, message, action),
    )


def _parse_result(
    result: Mapping[str, Any],
) -> tuple[str, str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]]:
    recording_id = _identifier(result.get("recording_id"), "recording_id")
    source_revision = _identifier(
        result.get("source_revision", result.get("revision_id")), "source_revision"
    )
    frames = result.get("frames")
    if not isinstance(frames, list) or not frames:
        raise CardPlaneCalibrationError("selected local result must contain non-empty frames")
    parsed: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for index, raw_frame in enumerate(frames):
        frame = _mapping(raw_frame, f"frames[{index}]")
        identity = _frame_identity(frame)
        if not isinstance(identity.get("width"), int) or not isinstance(
            identity.get("height"), int
        ):
            raise CardPlaneCalibrationError(f"frames[{index}] must declare integer dimensions")
        predictions = frame.get("predictions", frame.get("cards", frame.get("candidates", [])))
        if not isinstance(predictions, list):
            raise CardPlaneCalibrationError(f"frames[{index}].predictions must be a list")
        parsed.append((frame, identity))
    return recording_id, source_revision, parsed


def calibrate_recording(
    result: Mapping[str, Any], *, recipe: CalibrationRecipe | None = None
) -> CalibrationRun:
    """Mine and validate one deterministic recording-global table calibration."""

    selected_recipe = CalibrationRecipe() if recipe is None else recipe
    if not isinstance(selected_recipe, CalibrationRecipe):
        raise CardPlaneCalibrationError("recipe must be a CalibrationRecipe")
    recording_id, source_revision, frames = _parse_result(_mapping(result, "local result"))
    diagnostics: dict[str, Any] = {
        "processor_schema_version": CALIBRATION_PROCESSOR_SCHEMA_VERSION,
        "recipe": selected_recipe.to_mapping(),
        "recording_id": recording_id,
        "source_revision": source_revision,
        "candidate_yield": {
            "raw_count": 0,
            "confidence_count": 0,
            "geometry_count": 0,
            "deduplicated_count": 0,
            "accepted_count": 0,
        },
        "rejections": {},
    }
    receipts: list[CalibrationCandidateReceipt] = []
    observations: list[_Observation] = []
    expected_dimensions: tuple[int, int] | None = None
    expected_transform: str | None = None

    for frame_index, (frame, identity) in enumerate(frames):
        width = _positive_int(identity["width"], f"frames[{frame_index}].width")
        height = _positive_int(identity["height"], f"frames[{frame_index}].height")
        transform = _source_transform_key(frame, identity)
        if expected_dimensions is None:
            expected_dimensions = (width, height)
            expected_transform = transform
        elif (width, height) != expected_dimensions:
            diagnostics["observed_dimensions"] = [width, height]
            return _failure(
                "changed_frame_dimensions",
                "the complete recording contains more than one source-frame resolution",
                (
                    "select one complete local result from a stable recording; do not calibrate "
                    "across a resolution change"
                ),
                diagnostics,
                recording_id,
                source_revision,
                receipts,
            )
        elif transform != expected_transform:
            diagnostics["observed_source_transform"] = transform
            return _failure(
                "changed_source_transform",
                "the complete recording contains more than one source transform",
                (
                    "split the recording at the camera or stabilization change and calibrate "
                    "each stable recording separately"
                ),
                diagnostics,
                recording_id,
                source_revision,
                receipts,
            )
        predictions = frame.get("predictions", frame.get("cards", frame.get("candidates", [])))
        valid_in_frame: list[_Observation] = []
        for prediction_index, raw_prediction in enumerate(predictions):
            prediction = _mapping(
                raw_prediction, f"frames[{frame_index}].predictions[{prediction_index}]"
            )
            diagnostics["candidate_yield"]["raw_count"] += 1
            candidate_id = _identifier(
                prediction.get(
                    "candidate_id",
                    prediction.get(
                        "prediction_id",
                        f"{frame.get('frame_id', f'frame-{frame_index:06d}')}-{prediction_index}",
                    ),
                ),
                "candidate_id",
            )
            confidence = _prediction_confidence(prediction)
            try:
                polygons = _prediction_polygons(prediction)
                mask = _mask_for_prediction(polygons, prediction, width, height)
                components, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
                dominant = max(
                    (int(stats[index, cv2.CC_STAT_AREA]) for index in range(1, components)),
                    default=0,
                )
                total = int(np.count_nonzero(mask))
                if components > 2 and dominant < total * 0.95:
                    raise CardPlaneCalibrationError("multiple disconnected components")
                fitted = _fit_quad(polygons, mask, selected_recipe.minimum_quad_coverage)
                if fitted is None:
                    raise CardPlaneCalibrationError(
                        "quadrilateral fit coverage is below the frozen limit"
                    )
                quad, _fit_error = fitted
            except (CardPlaneCalibrationError, CardPlaneGeometryError, ValueError):
                diagnostics["rejections"][candidate_id] = "quadrilateral_fit"
                continue
            diagnostics["candidate_yield"]["geometry_count"] += 1
            if confidence < selected_recipe.confidence_threshold:
                diagnostics["rejections"][candidate_id] = "confidence_below_threshold"
                observations.append(
                    _Observation(
                        candidate_id,
                        source_revision,
                        _identifier(frame.get("frame_id", f"frame-{frame_index:06d}"), "frame_id"),
                        confidence,
                        quad,
                        width,
                        height,
                        *_bin_observation(quad, width, height, frame, selected_recipe),
                        _expanded_box(quad, selected_recipe.expanded_box_margin_px),
                    )
                )
                continue
            if (
                np.min(quad[:, 0]) < selected_recipe.frame_boundary_margin_px
                or np.min(quad[:, 1]) < selected_recipe.frame_boundary_margin_px
                or np.max(quad[:, 0]) > width - selected_recipe.frame_boundary_margin_px
                or np.max(quad[:, 1]) > height - selected_recipe.frame_boundary_margin_px
            ):
                diagnostics["rejections"][candidate_id] = "frame_boundary"
                observations.append(
                    _Observation(
                        candidate_id,
                        source_revision,
                        _identifier(frame.get("frame_id", f"frame-{frame_index:06d}"), "frame_id"),
                        confidence,
                        quad,
                        width,
                        height,
                        *_bin_observation(quad, width, height, frame, selected_recipe),
                        _expanded_box(quad, selected_recipe.expanded_box_margin_px),
                    )
                )
                continue
            observation = _Observation(
                candidate_id,
                source_revision,
                _identifier(frame.get("frame_id", f"frame-{frame_index:06d}"), "frame_id"),
                confidence,
                quad,
                width,
                height,
                *_bin_observation(quad, width, height, frame, selected_recipe),
                _expanded_box(quad, selected_recipe.expanded_box_margin_px),
            )
            valid_in_frame.append(observation)
            observations.append(observation)
            diagnostics["candidate_yield"]["confidence_count"] += 1
        retained: list[_Observation] = []
        for observation in sorted(
            valid_in_frame, key=lambda item: (-item.confidence, item.candidate_id)
        ):
            if any(
                _boxes_overlap(observation.expanded_box, item.expanded_box) for item in retained
            ):
                diagnostics["rejections"][observation.candidate_id] = "overlaps_prediction"
            else:
                retained.append(observation)

    accepted = [item for item in observations if item.candidate_id not in diagnostics["rejections"]]
    by_bin: dict[tuple[str, str, str, str], _Observation] = {}
    for observation in sorted(accepted, key=lambda item: (-item.confidence, item.candidate_id)):
        key = (
            observation.temporal_bin,
            observation.table_position_bin,
            observation.scale_bin,
            observation.orientation_bin,
        )
        if key in by_bin:
            diagnostics["rejections"][observation.candidate_id] = "duplicate_bin_lower_confidence"
        else:
            by_bin[key] = observation
    accepted = sorted(by_bin.values(), key=lambda item: item.candidate_id)
    diagnostics["candidate_yield"]["deduplicated_count"] = len(accepted)
    diagnostics["candidate_yield"]["accepted_count"] = len(accepted)
    for observation in observations:
        reason = diagnostics["rejections"].get(observation.candidate_id)
        receipts.append(_candidate_receipt(observation, reason is None, reason))
    receipts.sort(key=lambda item: item.candidate_id)

    temporal_bins = sorted({item.temporal_bin for item in accepted})
    position_bins = sorted({item.table_position_bin for item in accepted})
    orientation_bins = sorted({item.orientation_bin for item in accepted})
    dimensions = expected_dimensions or (0, 0)
    coverage_x = (
        (
            max(np.mean(item.quadrilateral, axis=0)[0] for item in accepted)
            - min(np.mean(item.quadrilateral, axis=0)[0] for item in accepted)
        )
        / dimensions[0]
        if accepted
        else 0.0
    )
    coverage_y = (
        (
            max(np.mean(item.quadrilateral, axis=0)[1] for item in accepted)
            - min(np.mean(item.quadrilateral, axis=0)[1] for item in accepted)
        )
        / dimensions[1]
        if accepted
        else 0.0
    )
    diagnostics["diversity"] = {
        "temporal_bin_count": len(temporal_bins),
        "table_position_bin_count": len(position_bins),
        "orientation_bin_count": len(orientation_bins),
        "spatial_coverage_x": float(round(float(coverage_x), 6)),
        "spatial_coverage_y": float(round(float(coverage_y), 6)),
    }
    if len(accepted) < selected_recipe.minimum_candidates:
        return _failure(
            "insufficient_candidates",
            f"only {len(accepted)} isolated-card candidates passed the frozen filter",
            "select a complete local result with more high-confidence, isolated card observations",
            diagnostics,
            recording_id,
            source_revision,
            receipts,
        )
    if (
        len(temporal_bins) < selected_recipe.minimum_temporal_bins
        or len(position_bins) < selected_recipe.minimum_position_bins
        or len(orientation_bins) < selected_recipe.minimum_orientation_bins
    ):
        return _failure(
            "insufficient_diversity",
            "isolated-card candidates do not cover enough time, table position, and orientation",
            (
                "use a complete stable recording with cards observed at separated table positions "
                "and orientations"
            ),
            diagnostics,
            recording_id,
            source_revision,
            receipts,
        )
    if (
        coverage_x < selected_recipe.minimum_spatial_coverage_x
        or coverage_y < selected_recipe.minimum_spatial_coverage_y
    ):
        return _failure(
            "insufficient_spatial_coverage",
            "isolated-card candidates do not cover enough of the source table",
            "use a stable recording with isolated cards distributed across the table",
            diagnostics,
            recording_id,
            source_revision,
            receipts,
        )

    ordered = sorted(
        accepted, key=lambda item: (item.temporal_bin, item.table_position_bin, item.candidate_id)
    )
    held_out = [
        item for index, item in enumerate(ordered) if index % selected_recipe.holdout_modulus == 0
    ]
    fit_observations = [
        item for index, item in enumerate(ordered) if index % selected_recipe.holdout_modulus != 0
    ]
    diagnostics["validation"] = {
        "fit_count": len(fit_observations),
        "held_out_count": len(held_out),
        "held_out_candidate_ids": [item.candidate_id for item in held_out],
    }
    if len(held_out) < selected_recipe.minimum_held_out_candidates or len(fit_observations) < 3:
        return _failure(
            "insufficient_validation_population",
            (
                "the de-duplicated candidate population cannot provide a fit and held-out "
                "validation set"
            ),
            "collect more isolated-card observations across independent temporal and spatial bins",
            diagnostics,
            recording_id,
            source_revision,
            receipts,
        )
    try:
        fit = fit_table_plane([item.quadrilateral for item in fit_observations])
    except (CardPlaneGeometryError, ValueError) as error:
        diagnostics["fit_error"] = str(error)
        return _failure(
            "calibration_fit_failed",
            "the shared table-plane fit could not explain the isolated-card population",
            "check for camera movement, zoom, stabilization drift, or a changed table setup",
            diagnostics,
            recording_id,
            source_revision,
            receipts,
        )
    diagnostics["fit"] = {
        key: fit[key]
        for key in (
            "method",
            "accepted_card_count",
            "rejected_card_indices",
            "median_angle_error_degrees",
            "median_aspect_error",
            "median_parallel_error",
        )
    }
    table_to_image = fit["table_to_image"]
    image_to_table = fit["image_to_table"]

    def alignment_error(item: _Observation) -> float:
        best: float | None = None
        for orientation in quadrilateral_orientations(item.quadrilateral):
            table_quad = apply_homography(image_to_table, orientation)
            angle_error, aspect_error, parallel_error = card_residual(table_quad)
            score = angle_error / 10.0 + aspect_error + parallel_error
            short, _long = card_vectors(table_quad)
            center = np.mean(table_quad, axis=0)
            angle = math.degrees(math.atan2(float(short[1]), float(short[0])))
            projected = project_fixed_card(table_to_image, center, angle, 1.0, 1.5)
            distances = np.linalg.norm(projected[:, None, :] - orientation[None, :, :], axis=2)
            error = float(np.max(np.min(distances, axis=1))) + score
            best = error if best is None else min(best, error)
        if best is None:
            raise CardPlaneCalibrationError("candidate has no quadrilateral orientation")
        return best

    held_out_errors = [alignment_error(item) for item in held_out]
    diagnostics["validation"].update(
        {
            "held_out_alignment_errors_px": [
                float(round(float(value), 6)) for value in held_out_errors
            ],
            "held_out_median_alignment_px": float(round(float(np.median(held_out_errors)), 6)),
            "held_out_max_alignment_px": float(round(float(max(held_out_errors)), 6)),
        }
    )
    gates = {
        "candidate_count": bool(len(accepted) >= selected_recipe.minimum_candidates),
        "temporal_diversity": bool(len(temporal_bins) >= selected_recipe.minimum_temporal_bins),
        "table_position_diversity": bool(
            len(position_bins) >= selected_recipe.minimum_position_bins
        ),
        "orientation_diversity": bool(
            len(orientation_bins) >= selected_recipe.minimum_orientation_bins
        ),
        "spatial_coverage": bool(
            coverage_x >= selected_recipe.minimum_spatial_coverage_x
            and coverage_y >= selected_recipe.minimum_spatial_coverage_y
        ),
        "held_out_population": bool(len(held_out) >= selected_recipe.minimum_held_out_candidates),
        "held_out_alignment": bool(
            max(held_out_errors) <= selected_recipe.maximum_held_out_alignment_px
        ),
    }
    diagnostics["gates"] = gates
    if not gates["held_out_alignment"]:
        return _failure(
            "held_out_alignment_failed",
            "held-out isolated-card candidates exceed the source-pixel alignment tolerance",
            (
                "do not publish this calibration; inspect the recording for camera movement, "
                "zoom, or a changed table setup"
            ),
            diagnostics,
            recording_id,
            source_revision,
            receipts,
        )
    accepted_receipt_digests = [item.receipt_digest for item in receipts if item.accepted]
    calibration_revision_id = (
        "calibration-"
        + _digest(
            {
                "recording_id": recording_id,
                "source_revision": source_revision,
                "recipe_digest": selected_recipe.digest,
                "candidate_receipt_digests": accepted_receipt_digests,
            }
        )[:24]
    )
    diagnostics["calibration_revision_id"] = calibration_revision_id
    calibration = TablePlaneCalibration.create(
        calibration_revision_id=calibration_revision_id,
        recording_id=recording_id,
        source_revision=source_revision,
        frame_width=dimensions[0],
        frame_height=dimensions[1],
        image_to_table=image_to_table,
        table_to_image=table_to_image,
        card_short_size=fit["card_short_size"],
        card_long_size=fit["card_long_size"],
        candidate_receipt_digests=accepted_receipt_digests,
        diagnostics=diagnostics,
    )
    return _published_run(recording_id, source_revision, receipts, diagnostics, calibration)


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


class CalibrationRevisionStore:
    """Store immutable calibration revisions below a recording workspace."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()

    def _path(self, recording_id: str, revision_id: str) -> Path:
        return (
            self.workspace_root
            / _identifier(recording_id, "recording_id")
            / CALIBRATION_STORE_DIRECTORY
            / _identifier(revision_id, "revision_id")
            / "manifest.json"
        )

    def publish(self, run: CalibrationRun) -> Path:
        if not isinstance(run, CalibrationRun):
            raise CardPlaneCalibrationError("store accepts a CalibrationRun")
        if run.status != "published" or run.calibration is None:
            raise CalibrationFailure(
                "calibration_not_publishable",
                "a failed calibration run cannot be stored as a revision",
                "resolve the reported automatic calibration gate and run the processor again",
            )
        path = self._path(run.recording_id, run.calibration.calibration_revision_id)
        payload = canonical_json_bytes(run.to_mapping())
        if path.exists():
            if path.read_bytes() != payload:
                raise CalibrationFailure(
                    "immutable_revision_conflict",
                    "the calibration revision path already contains different immutable content",
                    "create a new calibration revision from the changed generated result",
                )
            return path
        _write_atomic(path, payload)
        return path

    def load(self, recording_id: str, revision_id: str) -> CalibrationRun:
        path = self._path(recording_id, revision_id)
        if not path.is_file():
            raise CardPlaneCalibrationError(f"calibration revision is missing: {revision_id}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CardPlaneCalibrationError(
                "calibration revision manifest is not valid JSON"
            ) from error
        run = CalibrationRun.from_mapping(_mapping(raw, "calibration revision manifest"))
        if run.recording_id != recording_id or run.calibration is None:
            raise CardPlaneCalibrationError("calibration revision identity does not match its path")
        if run.calibration.calibration_revision_id != revision_id:
            raise CardPlaneCalibrationError("calibration revision ID does not match its path")
        return run

    def list_revision_ids(self, recording_id: str) -> tuple[str, ...]:
        root = (
            self.workspace_root
            / _identifier(recording_id, "recording_id")
            / CALIBRATION_STORE_DIRECTORY
        )
        if not root.is_dir():
            return ()
        return tuple(sorted(path.parent.name for path in root.glob("*/manifest.json")))


__all__ = [
    "CALIBRATION_PROCESSOR_SCHEMA_VERSION",
    "CALIBRATION_RUN_SCHEMA_VERSION",
    "CALIBRATION_STORE_DIRECTORY",
    "CalibrationFailure",
    "CalibrationRecipe",
    "CalibrationRevisionStore",
    "CalibrationRun",
    "CardPlaneCalibrationError",
    "calibrate_recording",
]
