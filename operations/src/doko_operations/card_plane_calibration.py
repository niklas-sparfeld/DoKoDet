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
    GEOMETRY_ALGORITHM_VERSION,
    CalibrationCandidateReceipt,
    CardPlaneGeometryError,
    TablePlaneCalibration,
    apply_homography,
    card_residual,
    card_vectors,
    fit_table_plane,
    polygon_area,
    project_fixed_card,
    project_rounded_card,
    quadrilateral_orientations,
    rasterize_polygon,
    rounded_card_outline,
)
from .pipeline_data import canonical_json_bytes

CALIBRATION_PROCESSOR_SCHEMA_VERSION = "card-plane-calibration-processor/v8"
CALIBRATION_RUN_SCHEMA_VERSION = "card-plane-calibration-run/v3"
CALIBRATION_RUN_SCHEMA_V2 = "card-plane-calibration-run/v2"
CALIBRATION_FIT_CANDIDATE_SCHEMA_VERSION = "card-plane-calibration-fit-candidate/v1"
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
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-:/"
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
    minimum_quad_coverage: float = 0.84
    minimum_boundary_straightness: float = 0.65
    minimum_corner_support: float = 0.50
    minimum_notch_depth_over_short_side: float = 0.12
    minimum_notch_area_fraction: float = 0.06
    maximum_occluded_boundary_fraction: float = 0.18
    maximum_scale_deviation_log: float = 0.30
    maximum_observations_per_frame: int = 4
    maximum_observations_per_temporal_bin: int = 8
    maximum_observations_per_position_bin: int = 8
    boundary_sample_count: int = 64
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
    minimum_size_reference_candidates: int = 2
    holdout_modulus: int = 4
    minimum_spatial_coverage_x: float = 0.25
    minimum_spatial_coverage_y: float = 0.25
    maximum_held_out_median_boundary_error_px: float = 2.0
    maximum_held_out_p90_boundary_fraction: float = 0.08
    minimum_held_out_boundary_pass_fraction: float = 0.60
    maximum_median_short_side_bias: float = 0.02
    maximum_median_area_bias: float = 0.02
    maximum_median_angle_error_degrees: float = 10.0
    maximum_median_aspect_error: float = 0.10
    maximum_median_parallel_error: float = 0.10

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise CardPlaneCalibrationError("confidence_threshold must be between zero and one")
        if not 0.0 < self.minimum_quad_coverage <= 1.0:
            raise CardPlaneCalibrationError("minimum_quad_coverage must be in (0, 1]")
        for field in (
            "minimum_boundary_straightness",
            "minimum_corner_support",
            "maximum_occluded_boundary_fraction",
        ):
            if not 0.0 <= getattr(self, field) <= 1.0:
                raise CardPlaneCalibrationError(f"{field} must be between zero and one")
        if self.maximum_scale_deviation_log <= 0:
            raise CardPlaneCalibrationError("maximum_scale_deviation_log must be positive")
        if self.minimum_notch_depth_over_short_side <= 0:
            raise CardPlaneCalibrationError("minimum_notch_depth_over_short_side must be positive")
        if not 0.0 <= self.minimum_notch_area_fraction <= 1.0:
            raise CardPlaneCalibrationError("minimum_notch_area_fraction must be in [0, 1]")
        for field in (
            "temporal_bin_us",
            "temporal_bin_frames",
            "table_position_grid",
            "minimum_candidates",
            "minimum_temporal_bins",
            "minimum_position_bins",
            "minimum_orientation_bins",
            "minimum_held_out_candidates",
            "minimum_size_reference_candidates",
            "holdout_modulus",
            "maximum_observations_per_frame",
            "maximum_observations_per_temporal_bin",
            "maximum_observations_per_position_bin",
            "boundary_sample_count",
        ):
            _positive_int(getattr(self, field), field)
        if self.scale_bin_octaves <= 0 or self.orientation_bin_degrees <= 0:
            raise CardPlaneCalibrationError("scale and orientation bins must be positive")
        for field in (
            "minimum_spatial_coverage_x",
            "minimum_spatial_coverage_y",
            "minimum_held_out_boundary_pass_fraction",
        ):
            value = getattr(self, field)
            if not 0.0 <= value <= 1.0:
                raise CardPlaneCalibrationError(f"{field} must be between zero and one")
        if self.maximum_held_out_median_boundary_error_px <= 0:
            raise CardPlaneCalibrationError(
                "maximum_held_out_median_boundary_error_px must be positive"
            )
        if self.maximum_held_out_p90_boundary_fraction <= 0:
            raise CardPlaneCalibrationError(
                "maximum_held_out_p90_boundary_fraction must be positive"
            )
        if self.maximum_median_short_side_bias <= 0 or self.maximum_median_area_bias <= 0:
            raise CardPlaneCalibrationError("absolute size-bias limits must be positive")
        for field in (
            "maximum_median_angle_error_degrees",
            "maximum_median_aspect_error",
            "maximum_median_parallel_error",
        ):
            if getattr(self, field) <= 0:
                raise CardPlaneCalibrationError(f"{field} must be positive")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": CALIBRATION_PROCESSOR_SCHEMA_VERSION,
            "confidence_threshold": self.confidence_threshold,
            "minimum_quad_coverage": self.minimum_quad_coverage,
            "minimum_boundary_straightness": self.minimum_boundary_straightness,
            "minimum_corner_support": self.minimum_corner_support,
            "minimum_notch_depth_over_short_side": self.minimum_notch_depth_over_short_side,
            "minimum_notch_area_fraction": self.minimum_notch_area_fraction,
            "maximum_occluded_boundary_fraction": self.maximum_occluded_boundary_fraction,
            "maximum_scale_deviation_log": self.maximum_scale_deviation_log,
            "maximum_observations_per_frame": self.maximum_observations_per_frame,
            "maximum_observations_per_temporal_bin": self.maximum_observations_per_temporal_bin,
            "maximum_observations_per_position_bin": self.maximum_observations_per_position_bin,
            "boundary_sample_count": self.boundary_sample_count,
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
            "minimum_size_reference_candidates": self.minimum_size_reference_candidates,
            "holdout_modulus": self.holdout_modulus,
            "minimum_spatial_coverage_x": self.minimum_spatial_coverage_x,
            "minimum_spatial_coverage_y": self.minimum_spatial_coverage_y,
            "maximum_held_out_median_boundary_error_px": (
                self.maximum_held_out_median_boundary_error_px
            ),
            "maximum_held_out_p90_boundary_fraction": self.maximum_held_out_p90_boundary_fraction,
            "minimum_held_out_boundary_pass_fraction": self.minimum_held_out_boundary_pass_fraction,
            "maximum_median_short_side_bias": self.maximum_median_short_side_bias,
            "maximum_median_area_bias": self.maximum_median_area_bias,
            "maximum_median_angle_error_degrees": self.maximum_median_angle_error_degrees,
            "maximum_median_aspect_error": self.maximum_median_aspect_error,
            "maximum_median_parallel_error": self.maximum_median_parallel_error,
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
    boundary_samples: np.ndarray
    quality_metrics: Mapping[str, float]
    quality_score: float
    record_index: int
    frame_width: int
    frame_height: int
    temporal_bin: str
    table_position_bin: str
    scale_bin: str
    orientation_bin: str


@dataclass(frozen=True, slots=True)
class CalibrationFitCandidate:
    """Run-scoped diagnostic fit. This value is not a publishable calibration revision."""

    recording_id: str
    source_revision: str
    frame_width: int
    frame_height: int
    image_to_table: tuple[tuple[float, ...], ...]
    table_to_image: tuple[tuple[float, ...], ...]
    card_short_size: float
    card_long_size: float
    recipe_digest: str
    geometry_algorithm_version: str
    fit_digest: str
    fit_observation_ids: tuple[str, ...]
    held_out_observation_ids: tuple[str, ...]
    candidate_receipt_digests: tuple[str, ...]
    size_reference_digest: str | None
    fit_lineage: Mapping[str, Any]
    candidate_digest: str

    @classmethod
    def create(
        cls,
        *,
        recording_id: str,
        source_revision: str,
        frame_width: int,
        frame_height: int,
        image_to_table: Sequence[Sequence[float]],
        table_to_image: Sequence[Sequence[float]],
        card_short_size: float,
        card_long_size: float,
        recipe_digest: str,
        fit_digest: str,
        fit_observation_ids: Sequence[str],
        held_out_observation_ids: Sequence[str],
        candidate_receipt_digests: Sequence[str],
        size_reference_digest: str | None,
        fit_lineage: Mapping[str, Any],
    ) -> "CalibrationFitCandidate":
        def matrix(value: Sequence[Sequence[float]], field: str) -> tuple[tuple[float, ...], ...]:
            array = np.asarray(value, dtype=np.float64)
            if array.shape != (3, 3) or not np.all(np.isfinite(array)):
                raise CardPlaneCalibrationError(f"{field} must be a finite 3 by 3 matrix")
            return tuple(tuple(_finite(item, field) for item in row) for row in array.tolist())

        core: dict[str, Any] = {
            "schema_version": CALIBRATION_FIT_CANDIDATE_SCHEMA_VERSION,
            "recording_id": _identifier(recording_id, "recording_id"),
            "source_revision": _identifier(source_revision, "source_revision"),
            "frame_width": _positive_int(frame_width, "frame_width"),
            "frame_height": _positive_int(frame_height, "frame_height"),
            "image_to_table": [list(row) for row in matrix(image_to_table, "image_to_table")],
            "table_to_image": [list(row) for row in matrix(table_to_image, "table_to_image")],
            "card_short_size": _finite(card_short_size, "card_short_size"),
            "card_long_size": _finite(card_long_size, "card_long_size"),
            "recipe_digest": _identifier(recipe_digest, "recipe_digest"),
            "geometry_algorithm_version": _identifier(
                GEOMETRY_ALGORITHM_VERSION, "geometry_algorithm_version"
            ),
            "fit_digest": _identifier(fit_digest, "fit_digest"),
            "fit_observation_ids": [
                _identifier(value, "fit_observation_id") for value in fit_observation_ids
            ],
            "held_out_observation_ids": [
                _identifier(value, "held_out_observation_id") for value in held_out_observation_ids
            ],
            "candidate_receipt_digests": [
                _identifier(value, "candidate_receipt_digest")
                for value in candidate_receipt_digests
            ],
            "size_reference_digest": None
            if size_reference_digest is None
            else _identifier(size_reference_digest, "size_reference_digest"),
            "fit_lineage": _copy_json(fit_lineage),
        }
        if core["card_short_size"] <= 0 or core["card_long_size"] <= 0:
            raise CardPlaneCalibrationError("fit candidate card sizes must be positive")
        if not np.allclose(
            np.asarray(core["image_to_table"]) @ np.asarray(core["table_to_image"]),
            np.eye(3),
            atol=1e-3,
        ):
            raise CardPlaneCalibrationError("fit candidate transforms must be reciprocal")
        return cls(
            recording_id=core["recording_id"],
            source_revision=core["source_revision"],
            frame_width=core["frame_width"],
            frame_height=core["frame_height"],
            image_to_table=tuple(tuple(row) for row in core["image_to_table"]),
            table_to_image=tuple(tuple(row) for row in core["table_to_image"]),
            card_short_size=core["card_short_size"],
            card_long_size=core["card_long_size"],
            recipe_digest=core["recipe_digest"],
            geometry_algorithm_version=core["geometry_algorithm_version"],
            fit_digest=core["fit_digest"],
            fit_observation_ids=tuple(core["fit_observation_ids"]),
            held_out_observation_ids=tuple(core["held_out_observation_ids"]),
            candidate_receipt_digests=tuple(core["candidate_receipt_digests"]),
            size_reference_digest=core["size_reference_digest"],
            fit_lineage=core["fit_lineage"],
            candidate_digest=_digest(core),
        )

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": CALIBRATION_FIT_CANDIDATE_SCHEMA_VERSION,
            "recording_id": self.recording_id,
            "source_revision": self.source_revision,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "image_to_table": [list(row) for row in self.image_to_table],
            "table_to_image": [list(row) for row in self.table_to_image],
            "card_short_size": self.card_short_size,
            "card_long_size": self.card_long_size,
            "recipe_digest": self.recipe_digest,
            "geometry_algorithm_version": self.geometry_algorithm_version,
            "fit_digest": self.fit_digest,
            "fit_observation_ids": list(self.fit_observation_ids),
            "held_out_observation_ids": list(self.held_out_observation_ids),
            "candidate_receipt_digests": list(self.candidate_receipt_digests),
            "size_reference_digest": self.size_reference_digest,
            "fit_lineage": _copy_json(self.fit_lineage),
        }
        return {**core, "candidate_digest": _digest(core)}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CalibrationFitCandidate":
        data = _mapping(raw, "calibration fit candidate")
        expected = {
            "schema_version",
            "recording_id",
            "source_revision",
            "frame_width",
            "frame_height",
            "image_to_table",
            "table_to_image",
            "card_short_size",
            "card_long_size",
            "recipe_digest",
            "geometry_algorithm_version",
            "fit_digest",
            "fit_observation_ids",
            "held_out_observation_ids",
            "candidate_receipt_digests",
            "size_reference_digest",
            "fit_lineage",
            "candidate_digest",
        }
        if (
            set(data) != expected
            or data["schema_version"] != CALIBRATION_FIT_CANDIDATE_SCHEMA_VERSION
        ):
            raise CardPlaneCalibrationError("calibration fit candidate has an unsupported contract")
        lists = (
            "fit_observation_ids",
            "held_out_observation_ids",
            "candidate_receipt_digests",
        )
        if any(not isinstance(data[name], list) for name in lists):
            raise CardPlaneCalibrationError("fit candidate observation lineage must be lists")
        result = cls.create(
            recording_id=data["recording_id"],
            source_revision=data["source_revision"],
            frame_width=data["frame_width"],
            frame_height=data["frame_height"],
            image_to_table=data["image_to_table"],
            table_to_image=data["table_to_image"],
            card_short_size=data["card_short_size"],
            card_long_size=data["card_long_size"],
            recipe_digest=data["recipe_digest"],
            fit_digest=data["fit_digest"],
            fit_observation_ids=data["fit_observation_ids"],
            held_out_observation_ids=data["held_out_observation_ids"],
            candidate_receipt_digests=data["candidate_receipt_digests"],
            size_reference_digest=data["size_reference_digest"],
            fit_lineage=_mapping(data["fit_lineage"], "fit_lineage"),
        )
        if data["candidate_digest"] != result.candidate_digest:
            raise CardPlaneCalibrationError("fit candidate digest does not match its contents")
        return result


@dataclass(frozen=True, slots=True)
class CalibrationRun:
    """Deterministic calibration output or diagnostics for an automatic failure."""

    recording_id: str
    source_revision: str
    status: str
    candidate_receipts: tuple[CalibrationCandidateReceipt, ...]
    diagnostics: Mapping[str, Any]
    calibration: TablePlaneCalibration | None
    calibration_fit_candidate: CalibrationFitCandidate | None
    failure: CalibrationFailure | None
    run_digest: str
    run_schema_version: str = CALIBRATION_RUN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status not in {"published", "failed"}:
            raise CardPlaneCalibrationError("calibration run status is unsupported")
        if (self.status == "published") != (self.calibration is not None):
            raise CardPlaneCalibrationError("published status must match calibration presence")
        if (self.status == "failed") != (self.failure is not None):
            raise CardPlaneCalibrationError("failed status must match failure presence")
        if self.run_schema_version not in {
            CALIBRATION_RUN_SCHEMA_V2,
            CALIBRATION_RUN_SCHEMA_VERSION,
        }:
            raise CardPlaneCalibrationError("calibration run schema is unsupported")
        if self.run_schema_version == CALIBRATION_RUN_SCHEMA_V2 and self.calibration_fit_candidate:
            raise CardPlaneCalibrationError("legacy calibration runs cannot contain fit candidates")

    def to_mapping(self) -> dict[str, Any]:
        core: dict[str, Any] = {
            "schema_version": self.run_schema_version,
            "recording_id": self.recording_id,
            "source_revision": self.source_revision,
            "status": self.status,
            "candidate_receipts": [item.to_mapping() for item in self.candidate_receipts],
            "diagnostics": _copy_json(self.diagnostics),
            "calibration": None if self.calibration is None else self.calibration.to_mapping(),
            "failure": None if self.failure is None else self.failure.to_mapping(),
        }
        if self.run_schema_version == CALIBRATION_RUN_SCHEMA_VERSION:
            core["calibration_fit_candidate"] = (
                None
                if self.calibration_fit_candidate is None
                else self.calibration_fit_candidate.to_mapping()
            )
        return {**core, "run_digest": _digest(core)}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CalibrationRun":
        data = _mapping(raw, "calibration run")
        schema_version = data.get("schema_version")
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
        if schema_version == CALIBRATION_RUN_SCHEMA_VERSION:
            expected.add("calibration_fit_candidate")
        elif schema_version != CALIBRATION_RUN_SCHEMA_V2:
            raise CardPlaneCalibrationError("calibration run schema is unsupported")
        if set(data) != expected:
            raise CardPlaneCalibrationError("calibration run has invalid fields")
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
        candidate_raw = data.get("calibration_fit_candidate")
        fit_candidate = (
            None
            if candidate_raw is None
            else CalibrationFitCandidate.from_mapping(
                _mapping(candidate_raw, "calibration_fit_candidate")
            )
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
            calibration_fit_candidate=fit_candidate,
            failure=failure,
            run_digest=_text(data["run_digest"], "run_digest"),
            run_schema_version=schema_version,
        )
        if result.run_digest != _digest(result.to_mapping_without_digest()):
            raise CardPlaneCalibrationError("calibration run digest does not match its contents")
        if calibration is not None and calibration.recording_id != result.recording_id:
            raise CardPlaneCalibrationError("calibration recording does not match the run")
        if fit_candidate is not None and (
            fit_candidate.recording_id != result.recording_id
            or fit_candidate.source_revision != result.source_revision
        ):
            raise CardPlaneCalibrationError("fit candidate lineage does not match the run")
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
    calibration_fit_candidate: CalibrationFitCandidate | None = None,
) -> CalibrationRun:
    core = {
        "schema_version": CALIBRATION_RUN_SCHEMA_VERSION,
        "recording_id": recording_id,
        "source_revision": source_revision,
        "status": "failed",
        "candidate_receipts": [item.to_mapping() for item in receipts],
        "diagnostics": _copy_json(diagnostics),
        "calibration": None,
        "calibration_fit_candidate": None
        if calibration_fit_candidate is None
        else calibration_fit_candidate.to_mapping(),
        "failure": failure.to_mapping(),
    }
    return CalibrationRun(
        recording_id=recording_id,
        source_revision=source_revision,
        status="failed",
        candidate_receipts=tuple(receipts),
        diagnostics=_copy_json(diagnostics),
        calibration=None,
        calibration_fit_candidate=calibration_fit_candidate,
        failure=failure,
        run_digest=_digest(core),
    )


def _published_run(
    recording_id: str,
    source_revision: str,
    receipts: Sequence[CalibrationCandidateReceipt],
    diagnostics: Mapping[str, Any],
    calibration: TablePlaneCalibration,
    calibration_fit_candidate: CalibrationFitCandidate,
) -> CalibrationRun:
    core = {
        "schema_version": CALIBRATION_RUN_SCHEMA_VERSION,
        "recording_id": recording_id,
        "source_revision": source_revision,
        "status": "published",
        "candidate_receipts": [item.to_mapping() for item in receipts],
        "diagnostics": _copy_json(diagnostics),
        "calibration": calibration.to_mapping(),
        "calibration_fit_candidate": calibration_fit_candidate.to_mapping(),
        "failure": None,
    }
    return CalibrationRun(
        recording_id=recording_id,
        source_revision=source_revision,
        status="published",
        candidate_receipts=tuple(receipts),
        diagnostics=_copy_json(diagnostics),
        calibration=calibration,
        calibration_fit_candidate=calibration_fit_candidate,
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
    value = _finite(prediction.get("confidence", prediction.get("score")), "prediction.confidence")
    if not 0.0 <= value <= 1.0:
        raise CardPlaneCalibrationError("prediction.confidence must be between zero and one")
    return value


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


def _uniform_boundary_samples(mask: np.ndarray, count: int) -> np.ndarray:
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise CardPlaneCalibrationError("mask has no supported boundary")
    contour = max(contours, key=lambda item: (cv2.arcLength(item, True), len(item)))
    points = contour.reshape(-1, 2).astype(np.float64)
    if len(points) < 3:
        raise CardPlaneCalibrationError("mask boundary has too few samples")
    closed = np.vstack((points, points[0]))
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    total = float(np.sum(lengths))
    if total <= 0:
        raise CardPlaneCalibrationError("mask boundary has zero length")
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    targets = np.arange(count, dtype=np.float64) * total / count
    indices = np.minimum(np.searchsorted(cumulative, targets, side="right") - 1, len(points) - 1)
    fractions = (targets - cumulative[indices]) / np.maximum(lengths[indices], 1e-9)
    return closed[indices] + fractions[:, None] * (closed[indices + 1] - closed[indices])


def _candidate_quality(
    mask: np.ndarray,
    quad: np.ndarray,
    *,
    component_dominance: float,
    recipe: CalibrationRecipe,
) -> tuple[np.ndarray, dict[str, float], float]:
    quad_mask = rasterize_polygon(quad, mask.shape[1], mask.shape[0])
    mask_values = mask > 0
    quad_values = quad_mask > 0
    intersection = int(np.count_nonzero(mask_values & quad_values))
    union = int(np.count_nonzero(mask_values | quad_values))
    mask_area = max(int(np.count_nonzero(mask_values)), 1)
    iou = intersection / max(union, 1)
    coverage = intersection / mask_area

    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise CardPlaneCalibrationError("mask has no supported boundary")
    contour = max(contours, key=lambda item: (cv2.arcLength(item, True), len(item)))
    contour_points = contour.reshape(-1, 2).astype(np.float64)
    hull = cv2.convexHull(contour).reshape(-1, 2).astype(np.float64)
    convex_hull_area = max(polygon_area(hull), 1.0)
    convexity = min(1.0, polygon_area(contour_points) / convex_hull_area)

    short, long = card_vectors(quad)
    short_size = max(float(np.linalg.norm(short)), 1.0)
    inward_reference_size = max(min(float(np.linalg.norm(short)), float(np.linalg.norm(long))), 1.0)
    hull_indices = cv2.convexHull(contour, returnPoints=False)
    defects = (
        None
        if hull_indices is None or len(hull_indices) < 3
        else cv2.convexityDefects(contour, hull_indices)
    )
    maximum_inward_defect = (
        0.0 if defects is None else float(np.max(defects.reshape(-1, 4)[:, 3])) / 256.0
    )
    edge_starts = quad
    edge_vectors = np.roll(quad, -1, axis=0) - edge_starts
    edge_lengths_squared = np.maximum(np.sum(edge_vectors * edge_vectors, axis=1), 1e-9)
    offsets = contour_points[:, None, :] - edge_starts[None, :, :]
    fractions = np.clip(
        np.sum(offsets * edge_vectors[None, :, :], axis=2) / edge_lengths_squared[None, :],
        0.0,
        1.0,
    )
    nearest_edges = edge_starts[None, :, :] + fractions[:, :, None] * edge_vectors[None, :, :]
    boundary_distances = np.min(
        np.linalg.norm(contour_points[:, None, :] - nearest_edges, axis=2), axis=1
    )
    straightness = float(np.mean(boundary_distances <= max(1.5, 0.025 * short_size)))
    corner_distances = np.min(
        np.linalg.norm(quad[:, None, :] - contour_points[None, :, :], axis=2), axis=1
    )
    corner_support = float(np.mean(np.exp(-corner_distances / max(0.05 * short_size, 1.0))))
    samples = _uniform_boundary_samples(mask, recipe.boundary_sample_count)
    metrics = {
        "mask_quad_iou": float(iou),
        "quad_mask_coverage": float(coverage),
        "convexity": float(convexity),
        "maximum_inward_defect_over_short_side": maximum_inward_defect / inward_reference_size,
        "boundary_straightness": straightness,
        "corner_support": corner_support,
        "component_dominance": float(component_dominance),
        "overlap_fraction": 0.0,
        "nearest_card_center_distance_over_size": 0.0,
        "separation_reference_available": 0.0,
        "local_scale_log_deviation": 0.0,
        "local_scale_reference_available": 0.0,
    }
    geometry_score = (
        0.30 * iou
        + 0.15 * coverage
        + 0.15 * convexity
        + 0.20 * straightness
        + 0.10 * corner_support
        + 0.10 * component_dominance
    )
    return samples, metrics, float(geometry_score)


def _polygon_overlap_fraction(left: np.ndarray, right: np.ndarray) -> float:
    left_area = polygon_area(left)
    right_area = polygon_area(right)
    if min(left_area, right_area) <= 0:
        return 0.0
    try:
        overlap_area, _intersection = cv2.intersectConvexConvex(
            left.astype(np.float32), right.astype(np.float32)
        )
    except cv2.error:
        return 0.0
    return float(overlap_area) / min(left_area, right_area)


def _projected_peer_boundary_fraction(
    outline: np.ndarray,
    candidate_id: str,
    peers: Sequence[tuple[str, Sequence[np.ndarray]]],
    width: int,
    height: int,
    sample_count: int,
) -> float:
    """Measure how much of a projected card edge is covered by peer detections."""
    x0 = max(0, int(math.floor(float(np.min(outline[:, 0])))))
    y0 = max(0, int(math.floor(float(np.min(outline[:, 1])))))
    x1 = min(width, int(math.ceil(float(np.max(outline[:, 0])))) + 1)
    y1 = min(height, int(math.ceil(float(np.max(outline[:, 1])))) + 1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    offset = np.asarray([x0, y0], dtype=np.float64)
    shape = (y1 - y0, x1 - x0)
    own_mask = np.zeros(shape, dtype=np.uint8)
    peer_mask = np.zeros(shape, dtype=np.uint8)
    for peer_id, polygons in peers:
        if peer_id == candidate_id:
            for polygon in polygons:
                cv2.fillPoly(own_mask, [np.rint(polygon - offset).astype(np.int32)], 1)
            continue
        for polygon in polygons:
            peer_hull = cv2.convexHull(polygon.astype(np.float32)).reshape(-1, 2)
            try:
                intersection, _ = cv2.intersectConvexConvex(
                    outline.astype(np.float32), peer_hull.astype(np.float32)
                )
            except cv2.error:
                intersection = 0.0
            union = polygon_area(outline) + polygon_area(peer_hull) - float(intersection)
            if union > 0 and float(intersection) / union > 0.8:
                # Two detections of the same full card are handled by duplicate selection.
                continue
            cv2.fillPoly(peer_mask, [np.rint(polygon - offset).astype(np.int32)], 1)
    short_size = min(
        float(np.linalg.norm(outline[1] - outline[0])),
        float(np.linalg.norm(outline[2] - outline[1])),
    )
    radius = max(2, min(8, int(round(0.015 * short_size))))
    own_support = cv2.dilate(own_mask, np.ones((2 * radius + 1, 2 * radius + 1), np.uint8))
    boundary = _sample_polygon_boundary(outline, sample_count) - offset
    indices = np.rint(boundary).astype(np.int64)
    indices[:, 0] = np.clip(indices[:, 0], 0, shape[1] - 1)
    indices[:, 1] = np.clip(indices[:, 1], 0, shape[0] - 1)
    return float(
        np.mean(
            (peer_mask[indices[:, 1], indices[:, 0]] > 0)
            & (own_support[indices[:, 1], indices[:, 0]] == 0)
        )
    )


def _local_scale_deviations(
    observations: Sequence[_Observation], confidence_threshold: float
) -> dict[int, float]:
    confident = [item for item in observations if item.confidence >= confidence_threshold]
    centers = [np.mean(item.quadrilateral, axis=0) for item in confident]
    scales = [math.log(max(polygon_area(item.quadrilateral), 1.0)) / 2.0 for item in confident]
    deviations: dict[int, float] = {}
    for index, item in enumerate(confident):
        center = centers[index]
        nearby = sorted(
            (
                (
                    float(
                        np.linalg.norm(
                            (other - center) / np.asarray([item.frame_width, item.frame_height])
                        )
                    ),
                    j,
                )
                for j, other in enumerate(centers)
                if j != index
            ),
            key=lambda pair: (pair[0], confident[pair[1]].candidate_id),
        )
        neighbours = [j for distance, j in nearby if distance <= 0.30][:5]
        if len(neighbours) >= 3:
            deviations[item.record_index] = scales[index] - float(
                np.median([scales[j] for j in neighbours])
            )
    return deviations


def _cap_grouped_observations(
    observations: Sequence[_Observation],
    *,
    group_key: str,
    maximum_count: int,
) -> tuple[list[_Observation], list[_Observation]]:
    grouped: dict[str, list[_Observation]] = {}
    for observation in observations:
        key = observation.source_frame_id if group_key == "frame" else observation.temporal_bin
        grouped.setdefault(key, []).append(observation)

    kept: list[_Observation] = []
    rejected: list[_Observation] = []

    def rank(item: _Observation) -> tuple[float, float, str]:
        return (-item.quality_score, -item.confidence, item.candidate_id)

    for key in sorted(grouped):
        group = sorted(grouped[key], key=rank)
        best_by_region: dict[str, _Observation] = {}
        for observation in group:
            best_by_region.setdefault(observation.table_position_bin, observation)
        selected = sorted(best_by_region.values(), key=rank)[:maximum_count]
        selected_ids = {item.record_index for item in selected}
        if len(selected) < maximum_count:
            selected.extend(
                item
                for item in group
                if item.record_index not in selected_ids and len(selected) < maximum_count
            )
        selected_ids = {item.record_index for item in selected}
        kept.extend(selected)
        rejected.extend(item for item in group if item.record_index not in selected_ids)
    return kept, rejected


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


def _candidate_receipt(
    observation: _Observation, accepted: bool, reason: str | None
) -> CalibrationCandidateReceipt:
    return CalibrationCandidateReceipt.create(
        candidate_id=observation.candidate_id,
        source_revision=observation.source_revision,
        source_frame_id=observation.source_frame_id,
        confidence=observation.confidence,
        quadrilateral=observation.quadrilateral.tolist(),
        boundary_samples=observation.boundary_samples.tolist(),
        quality_metrics=observation.quality_metrics,
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
    calibration_fit_candidate: CalibrationFitCandidate | None = None,
) -> CalibrationRun:
    return _failure_run(
        recording_id,
        source_revision,
        sorted(receipts, key=lambda item: item.candidate_id),
        diagnostics,
        CalibrationFailure(code, message, action),
        calibration_fit_candidate,
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


def _sample_polygon_boundary(polygon: np.ndarray, count: int) -> np.ndarray:
    closed = np.vstack((polygon, polygon[0]))
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    total = float(np.sum(lengths))
    if total <= 1e-12:
        raise CardPlaneCalibrationError("polygon boundary has zero length")
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    targets = np.arange(count, dtype=np.float64) * total / count
    indices = np.minimum(np.searchsorted(cumulative, targets, side="right") - 1, len(lengths) - 1)
    fractions = (targets - cumulative[indices]) / np.maximum(lengths[indices], 1e-12)
    return closed[indices] + fractions[:, None] * (closed[indices + 1] - closed[indices])


def _point_segment_distances(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    starts = polygon
    vectors = np.roll(polygon, -1, axis=0) - starts
    offsets = points[:, None, :] - starts[None, :, :]
    fractions = np.sum(offsets * vectors[None, :, :], axis=2) / np.maximum(
        np.sum(vectors * vectors, axis=1)[None, :], 1e-12
    )
    closest = starts[None, :, :] + np.clip(fractions, 0.0, 1.0)[:, :, None] * vectors[None, :, :]
    return np.min(np.linalg.norm(points[:, None, :] - closest, axis=2), axis=1)


def _boundary_metrics(
    observed_boundary: np.ndarray,
    projected_quad: np.ndarray,
    projected_outline: np.ndarray,
    *,
    sample_count: int,
) -> dict[str, float]:
    projected_boundary = _sample_polygon_boundary(projected_outline, sample_count)
    observed_points = observed_boundary[
        np.linspace(0, len(observed_boundary), sample_count, endpoint=False, dtype=np.int64)
    ]
    distances = np.concatenate(
        [
            _point_segment_distances(observed_points, projected_outline),
            _point_segment_distances(projected_boundary, observed_boundary),
        ]
    )
    short_size = min(
        (
            np.linalg.norm(projected_quad[1] - projected_quad[0])
            + np.linalg.norm(projected_quad[2] - projected_quad[3])
        )
        / 2,
        (
            np.linalg.norm(projected_quad[2] - projected_quad[1])
            + np.linalg.norm(projected_quad[3] - projected_quad[0])
        )
        / 2,
    )
    return {
        "median_boundary_distance_px": float(np.median(distances)),
        "p90_boundary_distance_px": float(np.percentile(distances, 90)),
        "maximum_boundary_distance_px": float(np.max(distances)),
        "median_boundary_distance_over_short_side": float(
            np.median(distances) / max(short_size, 1e-9)
        ),
        "p90_boundary_distance_over_short_side": float(
            np.percentile(distances, 90) / max(short_size, 1e-9)
        ),
    }


def _projected_card_for_observation(
    observation: _Observation,
    image_to_table: np.ndarray,
    table_to_image: np.ndarray,
    *,
    rounded: bool = False,
) -> np.ndarray:
    possibilities: list[tuple[float, np.ndarray]] = []
    for orientation in quadrilateral_orientations(observation.quadrilateral):
        table_quad = apply_homography(image_to_table, orientation)
        angle_error, aspect_error, parallel_error = card_residual(table_quad)
        score = angle_error / 10.0 + aspect_error + parallel_error
        possibilities.append((score, table_quad))
    if not possibilities:
        raise CardPlaneCalibrationError("candidate has no quadrilateral orientation")
    _score, table_quad = min(possibilities, key=lambda item: item[0])
    short, _long = card_vectors(table_quad)
    center = np.mean(table_quad, axis=0)
    angle = math.degrees(math.atan2(float(short[1]), float(short[0])))
    projection = project_rounded_card if rounded else project_fixed_card
    return projection(table_to_image, center, angle, 1.0, 1.5)


def _outline_within_frame(outline: np.ndarray, width: int, height: int) -> bool:
    points = np.asarray(outline, dtype=np.float64).reshape(-1, 2)
    tolerance = 1e-6
    return bool(
        np.all(points[:, 0] >= -tolerance)
        and np.all(points[:, 0] <= width + tolerance)
        and np.all(points[:, 1] >= -tolerance)
        and np.all(points[:, 1] <= height + tolerance)
    )


def _size_reference_metrics(projected: np.ndarray, reference: np.ndarray) -> dict[str, float]:
    predicted_short, predicted_long = card_vectors(projected)
    reference_short, reference_long = card_vectors(reference)
    return {
        "short_side_bias": float(
            np.linalg.norm(predicted_short) / max(np.linalg.norm(reference_short), 1e-9) - 1.0
        ),
        "long_side_bias": float(
            np.linalg.norm(predicted_long) / max(np.linalg.norm(reference_long), 1e-9) - 1.0
        ),
        "area_bias": float(polygon_area(projected) / max(polygon_area(reference), 1e-9) - 1.0),
    }


def calibrate_recording(
    result: Mapping[str, Any],
    *,
    recipe: CalibrationRecipe | None = None,
    size_reference: Mapping[str, Any] | None = None,
    size_reference_revision: str | None = None,
) -> CalibrationRun:
    """Mine and validate one deterministic recording-global table calibration."""

    selected_recipe = CalibrationRecipe() if recipe is None else recipe
    if not isinstance(selected_recipe, CalibrationRecipe):
        raise CardPlaneCalibrationError("recipe must be a CalibrationRecipe")
    if size_reference is not None and size_reference_revision is None:
        raise CardPlaneCalibrationError(
            "size_reference_revision is required with independent full-card outlines"
        )
    if size_reference is None and size_reference_revision is not None:
        raise CardPlaneCalibrationError("size_reference_revision requires independent outlines")
    validated_reference_revision = (
        None
        if size_reference_revision is None
        else _identifier(size_reference_revision, "size_reference_revision")
    )
    reference_polygons: dict[str, np.ndarray] = {}
    if size_reference is not None:
        for candidate_id, raw_polygon in _mapping(size_reference, "size_reference").items():
            safe_id = _identifier(candidate_id, "size_reference candidate_id")
            polygons = _polygon_list(raw_polygon, f"size_reference[{safe_id}]")
            if len(polygons) != 1 or polygons[0].shape != (4, 2):
                raise CardPlaneCalibrationError(
                    f"size_reference[{safe_id}] must be one four-corner full-card outline"
                )
            reference_polygons[safe_id] = polygons[0]
    size_reference_input_digest = (
        None
        if size_reference is None
        else _digest(
            {
                "source_revision": validated_reference_revision,
                "outlines": {
                    key: value.tolist() for key, value in sorted(reference_polygons.items())
                },
            }
        )
    )
    recording_id, source_revision, frames = _parse_result(_mapping(result, "local result"))
    diagnostics: dict[str, Any] = {
        "processor_schema_version": CALIBRATION_PROCESSOR_SCHEMA_VERSION,
        "run_schema_version": CALIBRATION_RUN_SCHEMA_VERSION,
        "recipe": selected_recipe.to_mapping(),
        "recording_id": recording_id,
        "source_revision": source_revision,
        "candidate_yield": {
            "raw_count": 0,
            "confidence_count": 0,
            "geometry_count": 0,
            "quality_count": 0,
            "deduplicated_count": 0,
            "accepted_count": 0,
        },
        "rejections": {},
        "selection_refit_rounds": [],
        "candidate_evidence": [],
        "size_reference_input": {
            "source_revision": validated_reference_revision,
            "digest": size_reference_input_digest,
            "outline_count": len(reference_polygons),
        },
        "fit_candidate_availability": {"available": False, "reason": "fit_not_attempted"},
    }
    receipts: list[CalibrationCandidateReceipt] = []
    observations: list[_Observation] = []
    frame_prediction_polygons: dict[str, list[tuple[str, list[np.ndarray]]]] = {}
    expected_dimensions: tuple[int, int] | None = None
    expected_transform: str | None = None

    def mark_structural_fit_unavailable(reason: str) -> None:
        for evidence in diagnostics["candidate_evidence"]:
            if evidence["fit_decision"] == "fit_not_attempted":
                evidence["fit_decision"] = f"not_fit:{reason}"

    for frame_index, (frame, identity) in enumerate(frames):
        width = _positive_int(identity["width"], f"frames[{frame_index}].width")
        height = _positive_int(identity["height"], f"frames[{frame_index}].height")
        transform = _source_transform_key(frame, identity)
        if expected_dimensions is None:
            expected_dimensions = (width, height)
            expected_transform = transform
        elif (width, height) != expected_dimensions:
            diagnostics["observed_dimensions"] = [width, height]
            mark_structural_fit_unavailable("changed_frame_dimensions")
            diagnostics["fit_candidate_availability"] = {
                "available": False,
                "reason": "changed_frame_dimensions",
            }
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
            mark_structural_fit_unavailable("changed_source_transform")
            diagnostics["fit_candidate_availability"] = {
                "available": False,
                "reason": "changed_source_transform",
            }
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
            frame_id = _identifier(frame.get("frame_id", f"frame-{frame_index:06d}"), "frame_id")
            try:
                confidence = _prediction_confidence(prediction)
                confidence_error = False
            except CardPlaneCalibrationError:
                confidence = None
                confidence_error = True
            evidence: dict[str, Any] = {
                "candidate_id": candidate_id,
                "source_revision": source_revision,
                "source_frame_id": frame_id,
                "confidence": confidence,
                "accepted": False,
                "rejection_reason": (
                    "invalid_confidence" if confidence_error else "geometry_not_usable"
                ),
                "boundary_samples": [],
                "projected_full_card_outline": None,
                "quality_metrics": {},
                "quality_weight": None,
                "residual": None,
                "fit_residual": None,
                "fit_decision": "selector_rejected:invalid_confidence"
                if confidence_error
                else "selector_rejected:geometry_not_usable",
            }
            record_index = len(diagnostics["candidate_evidence"])
            diagnostics["candidate_evidence"].append(evidence)
            if confidence_error:
                diagnostics["rejections"][candidate_id] = "invalid_confidence"
                continue
            try:
                polygons = _prediction_polygons(prediction)
                mask = _mask_for_prediction(polygons, prediction, width, height)
                if confidence >= selected_recipe.confidence_threshold:
                    frame_prediction_polygons.setdefault(frame_id, []).append(
                        (candidate_id, polygons)
                    )
                components, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
                dominant = max(
                    (int(stats[index, cv2.CC_STAT_AREA]) for index in range(1, components)),
                    default=0,
                )
                total = int(np.count_nonzero(mask))
                component_dominance = dominant / max(total, 1)
                if components > 2:
                    raise CardPlaneCalibrationError("multiple disconnected components")
                fitted = _fit_quad(polygons, mask, selected_recipe.minimum_quad_coverage)
                if fitted is None:
                    raise CardPlaneCalibrationError(
                        "quadrilateral fit coverage is below the frozen limit"
                    )
                quad, _fit_error = fitted
                samples, quality_metrics, geometry_score = _candidate_quality(
                    mask,
                    quad,
                    component_dominance=component_dominance,
                    recipe=selected_recipe,
                )
            except (CardPlaneCalibrationError, CardPlaneGeometryError, ValueError) as error:
                reason = (
                    "disconnected_components"
                    if "disconnected components" in str(error)
                    else "weak_quadrilateral_support"
                    if "coverage is below" in str(error)
                    else "invalid_geometry"
                )
                evidence["rejection_reason"] = reason
                evidence["fit_decision"] = f"selector_rejected:{reason}"
                diagnostics["rejections"][candidate_id] = reason
                continue
            diagnostics["candidate_yield"]["geometry_count"] += 1
            diagnostics["candidate_yield"]["quality_count"] += 1
            evidence["boundary_samples"] = samples.tolist()
            evidence["quality_metrics"] = quality_metrics
            quality_score = 0.85 * geometry_score + 0.15 * confidence
            quality_metrics["quality_score"] = quality_score
            evidence["quality_weight"] = float(round(quality_score, 6))
            evidence["fit_decision"] = "fit_not_attempted"
            observation = _Observation(
                candidate_id=candidate_id,
                source_revision=source_revision,
                source_frame_id=frame_id,
                confidence=confidence,
                quadrilateral=quad,
                boundary_samples=samples,
                quality_metrics=quality_metrics,
                quality_score=quality_score,
                record_index=record_index,
                frame_width=width,
                frame_height=height,
                temporal_bin=_bin_observation(quad, width, height, frame, selected_recipe)[0],
                table_position_bin=_bin_observation(quad, width, height, frame, selected_recipe)[1],
                scale_bin=_bin_observation(quad, width, height, frame, selected_recipe)[2],
                orientation_bin=_bin_observation(quad, width, height, frame, selected_recipe)[3],
            )
            observations.append(observation)
            rejection_reason: str | None = None
            if confidence < selected_recipe.confidence_threshold:
                rejection_reason = "confidence_below_threshold"
            elif (
                any(np.any(mask[edge]) for edge in (0, -1))
                or np.any(mask[:, 0])
                or np.any(mask[:, -1])
            ):
                rejection_reason = "frame_boundary"
            elif (
                quality_metrics["maximum_inward_defect_over_short_side"]
                > selected_recipe.minimum_notch_depth_over_short_side
                and 1.0 - quality_metrics["convexity"] > selected_recipe.minimum_notch_area_fraction
            ):
                rejection_reason = "localized_inward_notch"
            elif (
                quality_metrics["boundary_straightness"]
                < selected_recipe.minimum_boundary_straightness
            ):
                rejection_reason = "unstable_boundary"
            elif quality_metrics["corner_support"] < selected_recipe.minimum_corner_support:
                rejection_reason = "weak_corner_support"
            else:
                diagnostics["candidate_yield"]["confidence_count"] += 1

            if rejection_reason is None:
                valid_in_frame.append(observation)
            else:
                diagnostics["rejections"][candidate_id] = rejection_reason
                evidence["rejection_reason"] = rejection_reason
                evidence["fit_decision"] = f"selector_rejected:{rejection_reason}"

        for observation in valid_in_frame:
            peers = [item for item in valid_in_frame if item is not observation]
            if peers:
                center = np.mean(observation.quadrilateral, axis=0)
                size = max(math.sqrt(polygon_area(observation.quadrilateral)), 1.0)
                observation.quality_metrics["nearest_card_center_distance_over_size"] = min(
                    float(np.linalg.norm(np.mean(peer.quadrilateral, axis=0) - center) / size)
                    for peer in peers
                )
                observation.quality_metrics["separation_reference_available"] = 1.0
                observation.quality_metrics["overlap_fraction"] = max(
                    _polygon_overlap_fraction(observation.quadrilateral, peer.quadrilateral)
                    for peer in peers
                )
                diagnostics["candidate_evidence"][observation.record_index]["quality_metrics"] = (
                    dict(observation.quality_metrics)
                )

        retained: list[_Observation] = []
        for observation in sorted(
            valid_in_frame,
            key=lambda item: (-item.quality_score, -item.confidence, item.candidate_id),
        ):
            overlaps = [
                _polygon_overlap_fraction(observation.quadrilateral, item.quadrilateral)
                for item in retained
            ]
            overlap_fraction = max(overlaps, default=0.0)
            evidence = diagnostics["candidate_evidence"][observation.record_index]
            evidence["quality_metrics"] = dict(observation.quality_metrics)
            if overlap_fraction > 0.12:
                diagnostics["rejections"][observation.candidate_id] = "overlaps_prediction"
                evidence["rejection_reason"] = "overlaps_prediction"
            else:
                retained.append(observation)

    scale_deviations = _local_scale_deviations(observations, selected_recipe.confidence_threshold)
    for observation in observations:
        deviation = scale_deviations.get(observation.record_index)
        if deviation is None:
            continue
        observation.quality_metrics["local_scale_log_deviation"] = float(deviation)
        observation.quality_metrics["local_scale_reference_available"] = 1.0
        evidence = diagnostics["candidate_evidence"][observation.record_index]
        evidence["quality_metrics"] = dict(observation.quality_metrics)
        if (
            observation.candidate_id not in diagnostics["rejections"]
            and abs(deviation) > selected_recipe.maximum_scale_deviation_log
        ):
            diagnostics["rejections"][observation.candidate_id] = "inconsistent_apparent_card_scale"
            evidence["rejection_reason"] = "inconsistent_apparent_card_scale"

    eligible = [item for item in observations if item.candidate_id not in diagnostics["rejections"]]
    eligible, frame_capped = _cap_grouped_observations(
        eligible,
        group_key="frame",
        maximum_count=selected_recipe.maximum_observations_per_frame,
    )
    eligible, time_capped = _cap_grouped_observations(
        eligible,
        group_key="time",
        maximum_count=selected_recipe.maximum_observations_per_temporal_bin,
    )
    for capped, reason in (
        (frame_capped, "frame_observation_cap"),
        (time_capped, "temporal_bin_observation_cap"),
    ):
        for observation in capped:
            diagnostics["rejections"][observation.candidate_id] = reason
            evidence = diagnostics["candidate_evidence"][observation.record_index]
            evidence["accepted"] = False
            evidence["rejection_reason"] = reason

    by_bin: dict[tuple[str, str, str, str], _Observation] = {}
    for observation in sorted(
        eligible, key=lambda item: (-item.quality_score, -item.confidence, item.candidate_id)
    ):
        key = (
            observation.temporal_bin,
            observation.table_position_bin,
            observation.scale_bin,
            observation.orientation_bin,
        )
        if key in by_bin:
            diagnostics["rejections"][observation.candidate_id] = "duplicate_bin_lower_quality"
            diagnostics["candidate_evidence"][observation.record_index]["rejection_reason"] = (
                "duplicate_bin_lower_quality"
            )
        else:
            by_bin[key] = observation
    region_counts: dict[str, int] = {}
    accepted: list[_Observation] = []
    for observation in sorted(
        by_bin.values(), key=lambda item: (-item.quality_score, -item.confidence, item.candidate_id)
    ):
        count = region_counts.get(observation.table_position_bin, 0)
        if count >= selected_recipe.maximum_observations_per_position_bin:
            diagnostics["rejections"][observation.candidate_id] = "position_bin_observation_cap"
            diagnostics["candidate_evidence"][observation.record_index]["rejection_reason"] = (
                "position_bin_observation_cap"
            )
            continue
        region_counts[observation.table_position_bin] = count + 1
        accepted.append(observation)
    accepted.sort(key=lambda item: item.candidate_id)
    diagnostics["candidate_yield"]["deduplicated_count"] = len(accepted)
    diagnostics["candidate_yield"]["accepted_count"] = len(accepted)
    for observation in observations:
        reason = diagnostics["rejections"].get(observation.candidate_id)
        evidence = diagnostics["candidate_evidence"][observation.record_index]
        evidence["accepted"] = reason is None
        evidence["rejection_reason"] = reason
        evidence["quality_metrics"] = dict(observation.quality_metrics)
        receipts.append(_candidate_receipt(observation, reason is None, reason))
    receipts.sort(key=lambda item: item.candidate_id)
    diagnostics["candidate_evidence"].sort(
        key=lambda item: (item["source_frame_id"], item["candidate_id"])
    )

    dimensions = expected_dimensions or (0, 0)

    def refresh_population_metrics(
        current: Sequence[_Observation],
    ) -> tuple[list[str], list[str], list[str], float, float]:
        diagnostics["candidate_yield"]["deduplicated_count"] = len(current)
        diagnostics["candidate_yield"]["accepted_count"] = len(current)
        temporal = sorted({item.temporal_bin for item in current})
        positions = sorted({item.table_position_bin for item in current})
        orientations = sorted({item.orientation_bin for item in current})
        coverage_x_value = (
            (
                max(np.mean(item.quadrilateral, axis=0)[0] for item in current)
                - min(np.mean(item.quadrilateral, axis=0)[0] for item in current)
            )
            / dimensions[0]
            if current
            else 0.0
        )
        coverage_y_value = (
            (
                max(np.mean(item.quadrilateral, axis=0)[1] for item in current)
                - min(np.mean(item.quadrilateral, axis=0)[1] for item in current)
            )
            / dimensions[1]
            if current
            else 0.0
        )
        diagnostics["diversity"] = {
            "temporal_bin_count": len(temporal),
            "table_position_bin_count": len(positions),
            "orientation_bin_count": len(orientations),
            "spatial_coverage_x": float(round(float(coverage_x_value), 6)),
            "spatial_coverage_y": float(round(float(coverage_y_value), 6)),
        }
        return temporal, positions, orientations, coverage_x_value, coverage_y_value

    temporal_bins, position_bins, orientation_bins, coverage_x, coverage_y = (
        refresh_population_metrics(accepted)
    )
    ordered = sorted(
        accepted, key=lambda item: (item.temporal_bin, item.table_position_bin, item.candidate_id)
    )
    if len(ordered) >= 4:
        held_out = [
            item
            for index, item in enumerate(ordered)
            if index % selected_recipe.holdout_modulus == 0
        ]
        fit_observations = [
            item
            for index, item in enumerate(ordered)
            if index % selected_recipe.holdout_modulus != 0
        ]
    else:
        # Small populations still produce a diagnostic fit. They cannot provide independent
        # held-out validation, so publication gates will fail below.
        held_out = []
        fit_observations = ordered
    diagnostics["validation"] = {
        "fit_count": len(fit_observations),
        "held_out_count": len(held_out),
        "fit_candidate_ids": [item.candidate_id for item in fit_observations],
        "held_out_candidate_ids": [item.candidate_id for item in held_out],
    }
    if not fit_observations:
        diagnostics["fit_candidate_availability"] = {
            "available": False,
            "reason": "no_usable_geometry",
        }
        return _failure(
            "insufficient_candidates",
            "no isolated-card candidate remains usable for a diagnostic fit",
            "provide at least one complete, finite card boundary",
            diagnostics,
            recording_id,
            source_revision,
            receipts,
        )

    evidence_by_id = {item["candidate_id"]: item for item in diagnostics["candidate_evidence"]}
    while True:
        try:
            fit = fit_table_plane(
                [item.quadrilateral for item in fit_observations],
                boundary_samples=[item.boundary_samples for item in fit_observations],
                observation_weights=[max(item.quality_score, 0.01) for item in fit_observations],
            )
        except (CardPlaneGeometryError, ValueError) as error:
            diagnostics["fit_error"] = str(error)
            diagnostics["fit_candidate_availability"] = {
                "available": False,
                "reason": "no_finite_invertible_transform",
            }
            return _failure(
                "calibration_fit_failed",
                "the shared table-plane fit could not explain the isolated-card population",
                "check for camera movement, zoom, stabilization drift, or a changed table setup",
                diagnostics,
                recording_id,
                source_revision,
                receipts,
            )

        excluded: list[tuple[_Observation, np.ndarray, str]] = []
        for observation in [*fit_observations, *held_out]:
            outline = _projected_card_for_observation(
                observation, fit["image_to_table"], fit["table_to_image"], rounded=True
            )
            if not _outline_within_frame(
                outline, observation.frame_width, observation.frame_height
            ):
                excluded.append((observation, outline, "frame_boundary"))
                continue
            peer_fraction = _projected_peer_boundary_fraction(
                outline,
                observation.candidate_id,
                frame_prediction_polygons.get(observation.source_frame_id, []),
                observation.frame_width,
                observation.frame_height,
                selected_recipe.boundary_sample_count,
            )
            evidence_by_id[observation.candidate_id].setdefault(
                "initial_occluded_boundary_fraction", float(round(peer_fraction, 6))
            )
            evidence_by_id[observation.candidate_id]["occluded_boundary_fraction"] = float(
                round(peer_fraction, 6)
            )
            if peer_fraction > selected_recipe.maximum_occluded_boundary_fraction:
                excluded.append((observation, outline, "occluded_by_card"))
        if not excluded:
            break
        diagnostics["selection_refit_rounds"].append(
            {
                "fit_count": len(fit_observations),
                "rejections": {
                    reason: sum(item_reason == reason for _item, _outline, item_reason in excluded)
                    for reason in sorted({item_reason for _item, _outline, item_reason in excluded})
                },
            }
        )

        excluded_ids = {item.candidate_id for item, _outline, _reason in excluded}
        excluded_fit_ids = excluded_ids & {item.candidate_id for item in fit_observations}
        for observation, outline, reason in excluded:
            diagnostics["rejections"][observation.candidate_id] = reason
            evidence_by_id[observation.candidate_id]["accepted"] = False
            evidence_by_id[observation.candidate_id]["rejection_reason"] = reason
            evidence_by_id[observation.candidate_id]["projected_full_card_outline"] = (
                outline.tolist()
            )

        accepted = [item for item in accepted if item.candidate_id not in excluded_ids]
        fit_observations = [
            item for item in fit_observations if item.candidate_id not in excluded_ids
        ]
        held_out = [item for item in held_out if item.candidate_id not in excluded_ids]
        temporal_bins, position_bins, orientation_bins, coverage_x, coverage_y = (
            refresh_population_metrics(accepted)
        )
        diagnostics["validation"] = {
            **diagnostics["validation"],
            "fit_count": len(fit_observations),
            "held_out_count": len(held_out),
            "fit_candidate_ids": [item.candidate_id for item in fit_observations],
            "held_out_candidate_ids": [item.candidate_id for item in held_out],
        }
        receipts = [
            _candidate_receipt(
                item,
                item.candidate_id not in diagnostics["rejections"],
                diagnostics["rejections"].get(item.candidate_id),
            )
            for item in observations
        ]
        receipts.sort(key=lambda item: item.candidate_id)
        if not fit_observations:
            diagnostics["fit_candidate_availability"] = {
                "available": False,
                "reason": "no_eligible_fit_observations",
            }
            return _failure(
                "insufficient_candidates",
                "no complete calibration candidate remains for the diagnostic fit",
                "use complete, isolated card outlines inside the source frame",
                diagnostics,
                recording_id,
                source_revision,
                receipts,
            )
        if not excluded_fit_ids:
            # Held-out observations did not influence this fit.
            break

    diagnostics["fit"] = {
        key: fit[key]
        for key in (
            "method",
            "accepted_card_count",
            "rejected_card_indices",
            "median_angle_error_degrees",
            "median_aspect_error",
            "median_parallel_error",
            "median_boundary_error_px",
            "p90_boundary_error_px",
            "maximum_boundary_error_px",
            "median_boundary_error_over_short_side",
            "observation_residuals",
            "fit_attempt_count",
            "selected_attempt_seed",
            "convergence_reason",
        )
    }
    fit_quality = bool(
        fit["quality_gate_passed"]
        and fit["median_angle_error_degrees"] <= selected_recipe.maximum_median_angle_error_degrees
        and fit["median_aspect_error"] <= selected_recipe.maximum_median_aspect_error
        and fit["median_parallel_error"] <= selected_recipe.maximum_median_parallel_error
    )
    diagnostics["fit"]["quality_passed"] = fit_quality
    table_to_image = fit["table_to_image"]
    image_to_table = fit["image_to_table"]
    accepted_receipt_digests = [item.receipt_digest for item in receipts if item.accepted]
    receipt_by_id = {item.candidate_id: item for item in receipts}
    fit_indices = {item.candidate_id: index for index, item in enumerate(fit_observations)}
    fit_rejected = {int(index) for index in fit["rejected_card_indices"]}
    fit_residuals = {int(item["observation_index"]): item for item in fit["observation_residuals"]}
    evidence_by_id = {item["candidate_id"]: item for item in diagnostics["candidate_evidence"]}
    held_out_metrics: dict[str, dict[str, float]] = {}
    held_out_projected: dict[str, np.ndarray] = {}
    for item in held_out:
        projected = _projected_card_for_observation(item, image_to_table, table_to_image)
        projected_outline = _projected_card_for_observation(
            item, image_to_table, table_to_image, rounded=True
        )
        held_out_projected[item.candidate_id] = projected
        metrics = _boundary_metrics(
            item.boundary_samples,
            projected,
            projected_outline,
            sample_count=selected_recipe.boundary_sample_count,
        )
        held_out_metrics[item.candidate_id] = metrics
        evidence = evidence_by_id[item.candidate_id]
        evidence["projected_full_card_outline"] = projected_outline.tolist()
        evidence["quality_weight"] = float(round(item.quality_score, 6))
        evidence["residual"] = metrics
        evidence["boundary_metrics"] = metrics
        evidence["fit_decision"] = "held_out"

    for item in fit_observations:
        index = fit_indices[item.candidate_id]
        projected = fit["oriented_image_quads"][index]
        projected_outline = apply_homography(
            table_to_image, rounded_card_outline(fit["table_quads"][index])
        )
        metrics = _boundary_metrics(
            item.boundary_samples,
            projected,
            projected_outline,
            sample_count=selected_recipe.boundary_sample_count,
        )
        evidence = evidence_by_id[item.candidate_id]
        evidence["projected_full_card_outline"] = projected_outline.tolist()
        evidence["quality_weight"] = float(round(item.quality_score, 6))
        evidence["residual"] = metrics
        evidence["boundary_metrics"] = metrics
        evidence["fit_decision"] = "fit_outlier" if index in fit_rejected else "fit_inlier"
        residual = fit_residuals.get(index)
        evidence["fit_residual"] = None if residual is None else dict(residual)

    held_values = list(held_out_metrics.values())
    held_errors = [item["median_boundary_distance_px"] for item in held_values]
    held_p90_fractions = [item["p90_boundary_distance_over_short_side"] for item in held_values]
    held_pass_count = sum(
        item["median_boundary_distance_px"]
        <= selected_recipe.maximum_held_out_median_boundary_error_px
        and item["p90_boundary_distance_over_short_side"]
        <= selected_recipe.maximum_held_out_p90_boundary_fraction
        for item in held_values
    )
    held_fraction = held_pass_count / len(held_values) if held_values else 0.0
    regions: dict[str, list[dict[str, float]]] = {"center": [], "view_edges": []}

    def observation_region(item: _Observation) -> str:
        center = np.mean(item.quadrilateral, axis=0)
        if (
            0.25 * item.frame_width <= center[0] <= 0.75 * item.frame_width
            and 0.25 * item.frame_height <= center[1] <= 0.75 * item.frame_height
        ):
            return "center"
        return "view_edges"

    for item in held_out:
        regions[observation_region(item)].append(held_out_metrics[item.candidate_id])

    def summarize_region(values: Sequence[Mapping[str, float]]) -> dict[str, Any]:
        return {
            "count": len(values),
            "median_boundary_distance_px": None
            if not values
            else float(np.median([item["median_boundary_distance_px"] for item in values])),
            "p90_boundary_distance_px": None
            if not values
            else float(np.percentile([item["p90_boundary_distance_px"] for item in values], 90)),
            "worst_boundary_distance_px": None
            if not values
            else float(max(item["maximum_boundary_distance_px"] for item in values)),
            "p90_boundary_distance_over_short_side": None
            if not values
            else float(
                np.percentile(
                    [item["p90_boundary_distance_over_short_side"] for item in values], 90
                )
            ),
        }

    size_metrics: dict[str, dict[str, float]] = {}
    for candidate_id in sorted(
        set(item.candidate_id for item in held_out) & reference_polygons.keys()
    ):
        size_metrics[candidate_id] = _size_reference_metrics(
            held_out_projected[candidate_id], reference_polygons[candidate_id]
        )
    size_reference_core = {
        candidate_id: reference_polygons[candidate_id].tolist()
        for candidate_id in sorted(size_metrics)
    }
    size_reference_digest = (
        None
        if not size_metrics
        else _digest(
            {
                "source_revision": validated_reference_revision,
                "outlines": size_reference_core,
            }
        )
    )
    size_short_bias = [item["short_side_bias"] for item in size_metrics.values()]
    size_area_bias = [item["area_bias"] for item in size_metrics.values()]
    size_reference_available = (
        len(size_metrics) >= selected_recipe.minimum_size_reference_candidates
    )
    size_comparison_passed = bool(
        size_reference_available
        and abs(float(np.median(size_short_bias))) <= selected_recipe.maximum_median_short_side_bias
        and abs(float(np.median(size_area_bias))) <= selected_recipe.maximum_median_area_bias
    )
    diagnostics["validation"] = {
        **diagnostics["validation"],
        "held_out_observations": [
            {
                "candidate_id": item.candidate_id,
                "source_frame_id": item.source_frame_id,
                "region": observation_region(item),
                **held_out_metrics[item.candidate_id],
                "fit_decision": "held_out_pass"
                if item.candidate_id in held_out_metrics
                and held_out_metrics[item.candidate_id]["median_boundary_distance_px"]
                <= selected_recipe.maximum_held_out_median_boundary_error_px
                and held_out_metrics[item.candidate_id]["p90_boundary_distance_over_short_side"]
                <= selected_recipe.maximum_held_out_p90_boundary_fraction
                else "held_out_fail",
                "size_reference_metrics": size_metrics.get(item.candidate_id),
            }
            for item in held_out
        ],
        "held_out_summary": {
            "count": len(held_values),
            "median_boundary_distance_px": None
            if not held_errors
            else float(np.median(held_errors)),
            "p90_boundary_distance_px": None
            if not held_values
            else float(
                np.percentile([item["p90_boundary_distance_px"] for item in held_values], 90)
            ),
            "worst_boundary_distance_px": None
            if not held_values
            else float(max(item["maximum_boundary_distance_px"] for item in held_values)),
            "p90_boundary_distance_over_short_side": None
            if not held_p90_fractions
            else float(np.percentile(held_p90_fractions, 90)),
            "pass_count": held_pass_count,
            "pass_fraction": float(held_fraction),
        },
        "regional_metrics": {
            region: summarize_region(values) for region, values in regions.items()
        },
        "absolute_size": {
            "status": "passed"
            if size_comparison_passed
            else "failed"
            if size_reference_available
            else "unavailable",
            "reference_source_revision": validated_reference_revision if size_metrics else None,
            "input_digest": size_reference_input_digest,
            "reference_digest": size_reference_digest,
            "reference_count": len(size_metrics),
            "short_side_bias": None if not size_short_bias else float(np.median(size_short_bias)),
            "area_bias": None if not size_area_bias else float(np.median(size_area_bias)),
            "reason": None
            if size_comparison_passed
            else "measured short-side or area bias exceeds the frozen limit"
            if size_reference_available
            else "independent held-out full-card outlines are unavailable",
        },
    }
    candidate = CalibrationFitCandidate.create(
        recording_id=recording_id,
        source_revision=source_revision,
        frame_width=dimensions[0],
        frame_height=dimensions[1],
        image_to_table=image_to_table,
        table_to_image=table_to_image,
        card_short_size=fit["card_short_size"],
        card_long_size=fit["card_long_size"],
        recipe_digest=selected_recipe.digest,
        fit_digest=fit["calibration_digest"],
        fit_observation_ids=[item.candidate_id for item in fit_observations],
        held_out_observation_ids=[item.candidate_id for item in held_out],
        candidate_receipt_digests=[
            receipt_by_id[item].receipt_digest for item in sorted(receipt_by_id)
        ],
        size_reference_digest=size_reference_input_digest,
        fit_lineage={
            "source_revision": source_revision,
            "size_reference_revision": validated_reference_revision,
            "size_reference_input_digest": size_reference_input_digest,
            "size_reference_used_digest": size_reference_digest,
            "fit_observations": [
                {
                    "candidate_id": item.candidate_id,
                    "source_frame_id": item.source_frame_id,
                    "receipt_digest": receipt_by_id[item.candidate_id].receipt_digest,
                }
                for item in fit_observations
            ],
            "held_out_observations": [
                {
                    "candidate_id": item.candidate_id,
                    "source_frame_id": item.source_frame_id,
                    "receipt_digest": receipt_by_id[item.candidate_id].receipt_digest,
                }
                for item in held_out
            ],
            "selected_attempt_seed": fit["selected_attempt_seed"],
            "convergence_reason": fit["convergence_reason"],
        },
    )
    diagnostics["fit_candidate_availability"] = {
        "available": True,
        "reason": None,
        "candidate_digest": candidate.candidate_digest,
    }
    for item in observations:
        evidence = evidence_by_id[item.candidate_id]
        if item.candidate_id not in fit_indices and item.candidate_id not in held_out_metrics:
            evidence["quality_weight"] = float(round(item.quality_score, 6))
            reason = diagnostics["rejections"].get(item.candidate_id)
            evidence["fit_decision"] = f"selector_rejected:{reason or 'not_selected'}"
            projected = _projected_card_for_observation(item, image_to_table, table_to_image)
            projected_outline = _projected_card_for_observation(
                item, image_to_table, table_to_image, rounded=True
            )
            evidence["projected_full_card_outline"] = projected_outline.tolist()
            evidence["boundary_metrics"] = _boundary_metrics(
                item.boundary_samples,
                projected,
                projected_outline,
                sample_count=selected_recipe.boundary_sample_count,
            )
            evidence["residual"] = evidence["boundary_metrics"]

    gates = {
        "fit_quality": fit_quality,
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
        "held_out_boundary": bool(
            held_fraction >= selected_recipe.minimum_held_out_boundary_pass_fraction
        ),
    }
    diagnostics["gates"] = gates
    diagnostics["failed_gates"] = sorted(name for name, passed in gates.items() if not passed)
    diagnostics["unavailable_gates"] = []
    if not all(gates.values()):
        if not gates["candidate_count"]:
            code = "insufficient_candidates"
            message = f"only {len(accepted)} isolated-card candidates passed the frozen filter"
            action = (
                "select a complete local result with more high-confidence, "
                "isolated card observations"
            )
        elif not all(
            gates[name]
            for name in ("temporal_diversity", "table_position_diversity", "orientation_diversity")
        ):
            code = "insufficient_diversity"
            message = (
                "isolated-card candidates do not cover enough time, table position, and orientation"
            )
            action = "use a stable recording with separated card positions and orientations"
        elif not gates["spatial_coverage"]:
            code = "insufficient_spatial_coverage"
            message = "isolated-card candidates do not cover enough of the source table"
            action = "use a stable recording with isolated cards distributed across the table"
        elif not gates["fit_quality"]:
            code = "inconsistent_card_geometry"
            message = (
                "the accepted calibration candidates do not describe one stable standard-card plane"
            )
            action = (
                "inspect the candidate boundaries for crop-only regions, camera movement, "
                "or a changed table setup"
            )
        elif not gates["held_out_population"]:
            code = "insufficient_validation_population"
            message = "the fit has too few independent held-out card boundaries"
            action = (
                "collect more isolated-card observations across independent temporal "
                "and spatial bins"
            )
        elif not gates["held_out_boundary"]:
            code = "held_out_boundary_failed"
            message = "held-out card boundaries exceed the source-pixel validation limits"
            action = "inspect camera movement, zoom, stabilization drift, and the worst-fit frames"
        return _failure(
            code,
            message,
            action,
            diagnostics,
            recording_id,
            source_revision,
            receipts,
            candidate,
        )

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
    try:
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
    except CardPlaneGeometryError as error:
        diagnostics["calibration_error"] = str(error)
        return _failure(
            "unstable_table_transform",
            "the fitted table transform is too unstable to publish",
            (
                "reject crop-only regions that destabilize the fit, or split the recording "
                "at a camera change"
            ),
            diagnostics,
            recording_id,
            source_revision,
            receipts,
            candidate,
        )
    return _published_run(
        recording_id, source_revision, receipts, diagnostics, calibration, candidate
    )


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
    "CALIBRATION_FIT_CANDIDATE_SCHEMA_VERSION",
    "CALIBRATION_PROCESSOR_SCHEMA_VERSION",
    "CALIBRATION_RUN_SCHEMA_VERSION",
    "CALIBRATION_STORE_DIRECTORY",
    "CalibrationFitCandidate",
    "CalibrationFailure",
    "CalibrationRecipe",
    "CalibrationRevisionStore",
    "CalibrationRun",
    "CardPlaneCalibrationError",
    "calibrate_recording",
]
