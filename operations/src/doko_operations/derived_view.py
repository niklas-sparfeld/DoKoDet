"""Resolve reproducible frames and crops from recording video.

The module owns the application boundary for visual derived views.  It does not know about review
batches, device evidence packages, or backend storage.  A cache is an optional performance layer;
the source video remains the only visual input.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError

from .pipeline_data import RecordingVideoSource, canonical_json_bytes

EXACT_EVENT_SCHEMA = "exact-event/v1"
VISIBLE_REGION_CROP_SCHEMA = "visible-region-crop/v1"
DERIVED_VIEW_CACHE_SCHEMA = "derived-view-cache/v1"

# These values are pinned by the repository root mise.toml and operations/uv.lock.
FFMPEG_TOOLCHAIN_VERSION = "8.1.2"
PILLOW_TOOLCHAIN_VERSION = "12.3.0"
DEFAULT_DECODER_VERSION = f"ffmpeg/{FFMPEG_TOOLCHAIN_VERSION}"
DEFAULT_FRAME_TRANSFORM_VERSION = f"ffmpeg-mjpeg/{FFMPEG_TOOLCHAIN_VERSION}"
DEFAULT_TRANSFORM_VERSION = f"pillow/{PILLOW_TOOLCHAIN_VERSION}/crop-conditions-v2"

SUPPORTED_FRAME_ENCODINGS = frozenset({"jpeg", "png"})
SUPPORTED_CROP_ENCODINGS = frozenset({"jpeg", "png", "ppm"})
SUPPORTED_CROP_POLICIES = frozenset(
    {
        "raw_rectangular",
        "predicted_visible_region",
        "generated_other_region_exclusion",
        "predicted_region_with_other_exclusion",
        "reviewed_other_region_exclusion",
        "oracle_visible_region",
        "conservative_box_only",
    }
)
_CACHE_KEY = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_GEOMETRY_KINDS = frozenset({"detector-box/v1", "visible-region/v1", "reviewed-visible-region/v1"})
_EXCLUSION_SOURCES = frozenset({"generated", "reviewed"})
SUPPORTED_CORRUPTION_FAMILIES = frozenset(
    {
        "erosion_missing_boundary_pixels",
        "dilation_into_background_or_neighbor",
        "position_shift",
        "holes_missing_connected_components",
        "false_disconnected_components",
        "pixels_from_another_visible_card",
        "complete_derived_box_fallback",
    }
)
_EXCLUSION_EROSION_FRACTION = 0.10
_MATERIAL_OVERLAP_FRACTION = 0.25
_EXCLUSION_ELIGIBILITY_RULE = "recorded-provider-confidence-and-geometry-diagnostics/v1"
_NEUTRAL_FILL_RGB = (128, 128, 128)
_CORRUPTION_TRANSFORM_VERSION = "visible-region-corruption/v1"


class DerivedViewError(ValueError):
    """Raised when a derived view request or result is invalid."""


class DerivedViewSourceError(DerivedViewError):
    """Raised when the requested source video is not the accepted source."""


class DerivedViewProbeError(RuntimeError):
    """Raised when the decoder cannot provide frame presentation timestamps."""


class DerivedViewMissingFrameError(DerivedViewError):
    """Raised when no decoded frame is available at or after the requested time."""


class DerivedViewCacheError(DerivedViewError):
    """Raised when a cache key or cache write is invalid."""


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise DerivedViewError(f"{field} must be a non-empty string")
    return value


def _require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise DerivedViewError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _require_int(value: Any, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DerivedViewError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise DerivedViewError(f"{field} must be at least {minimum}")
    return value


def _require_coordinate(value: Any, field: str) -> int:
    result = _require_int(value, field, minimum=0)
    if result > 1000:
        raise DerivedViewError(f"{field} must be from 0 through 1000")
    return result


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise DerivedViewError(f"{field} must be an object")
    return value


def _strict(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing or unknown:
        detail: list[str] = []
        if missing:
            detail.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            detail.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise DerivedViewError(f"{field} has invalid fields ({'; '.join(detail)})")


def _content_type(encoding: str) -> str:
    return {
        "jpeg": "image/jpeg",
        "png": "image/png",
        "ppm": "image/x-portable-pixmap",
    }[encoding]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _timestamp_us(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.strip():
        raise DerivedViewProbeError(f"ffprobe returned an invalid {field}")
    try:
        timestamp = Decimal(value) * Decimal(1_000_000)
        result = int(timestamp.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError) as error:
        raise DerivedViewProbeError(f"ffprobe returned an invalid {field}") from error
    if result < 0:
        raise DerivedViewProbeError(f"ffprobe returned a negative {field}")
    return result


def _write_fsync(path: Path, value: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _validate_source_video(path: Path, source: RecordingVideoSource) -> None:
    if not path.is_file():
        raise DerivedViewSourceError(f"source video does not exist: {path}")
    try:
        stat = path.stat()
    except OSError as error:
        raise DerivedViewSourceError(f"source video cannot be inspected: {path}") from error
    if stat.st_size != source.byte_length:
        raise DerivedViewSourceError("source video byte length does not match the accepted source")
    try:
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError as error:
        raise DerivedViewSourceError(f"source video cannot be read: {path}") from error
    if digest != source.video_sha256:
        raise DerivedViewSourceError("source video digest does not match the accepted source")


@dataclass(frozen=True, slots=True)
class ExactEventRequest:
    """Frozen input values for one exact-event frame resolution."""

    source: RecordingVideoSource
    requested_time_us: int
    output_encoding: str = "jpeg"
    policy: str = EXACT_EVENT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.source, RecordingVideoSource):
            raise DerivedViewError("exact-event source must be a recording video source")
        _require_int(self.requested_time_us, "requested_time_us", minimum=0)
        if self.requested_time_us > self.source.duration_us:
            raise DerivedViewError("requested_time_us is outside the source duration")
        if self.output_encoding not in SUPPORTED_FRAME_ENCODINGS:
            raise DerivedViewError("unsupported exact-event output encoding")
        if self.policy != EXACT_EVENT_SCHEMA:
            raise DerivedViewError("exact-event policy is unsupported")

    def to_mapping(
        self,
        *,
        decoder_version: str,
        transform_version: str = DEFAULT_FRAME_TRANSFORM_VERSION,
    ) -> dict[str, Any]:
        return {
            "schema_version": EXACT_EVENT_SCHEMA,
            "source_video_sha256": self.source.video_sha256,
            "requested_time_us": self.requested_time_us,
            "output_encoding": self.output_encoding,
            "policy": self.policy,
            "decoder_version": decoder_version,
            "transform_version": transform_version,
        }


@dataclass(frozen=True, slots=True)
class ResolvedFrame:
    """One source frame and its reproducible presentation identity."""

    requested_time_us: int
    frame_index: int
    presentation_timestamp_us: int
    source_video_sha256: str
    width: int
    height: int
    decoder_version: str
    transform_version: str
    output_encoding: str
    image_bytes: bytes
    policy: str = EXACT_EVENT_SCHEMA

    def __post_init__(self) -> None:
        if self.policy != EXACT_EVENT_SCHEMA:
            raise DerivedViewError("resolved frame has an unsupported policy")
        _require_int(self.requested_time_us, "requested_time_us", minimum=0)
        _require_int(self.frame_index, "frame_index", minimum=0)
        _require_int(self.presentation_timestamp_us, "presentation_timestamp_us", minimum=0)
        _require_digest(self.source_video_sha256, "source_video_sha256")
        _require_int(self.width, "width", minimum=1)
        _require_int(self.height, "height", minimum=1)
        _require_text(self.decoder_version, "decoder_version")
        _require_text(self.transform_version, "transform_version")
        if self.output_encoding not in SUPPORTED_FRAME_ENCODINGS:
            raise DerivedViewError("resolved frame has an unsupported output encoding")
        if not isinstance(self.image_bytes, bytes) or not self.image_bytes:
            raise DerivedViewError("resolved frame bytes must be non-empty")

    @property
    def image_sha256(self) -> str:
        return _sha256(self.image_bytes)

    @property
    def content_type(self) -> str:
        return _content_type(self.output_encoding)

    def identity_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": EXACT_EVENT_SCHEMA,
            "source_video_sha256": self.source_video_sha256,
            "requested_time_us": self.requested_time_us,
            "frame_index": self.frame_index,
            "presentation_timestamp_us": self.presentation_timestamp_us,
            "width": self.width,
            "height": self.height,
            "decoder_version": self.decoder_version,
            "transform_version": self.transform_version,
            "output_encoding": self.output_encoding,
            "content_type": self.content_type,
            "image_sha256": self.image_sha256,
            "policy": self.policy,
        }


@dataclass(frozen=True, slots=True)
class PixelBounds:
    """An exclusive pixel rectangle."""

    x_min: int
    y_min: int
    x_max: int
    y_max: int

    def __post_init__(self) -> None:
        _require_int(self.x_min, "pixel_bounds.x_min", minimum=0)
        _require_int(self.y_min, "pixel_bounds.y_min", minimum=0)
        _require_int(self.x_max, "pixel_bounds.x_max", minimum=1)
        _require_int(self.y_max, "pixel_bounds.y_max", minimum=1)
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise DerivedViewError("pixel bounds must have positive dimensions")

    @property
    def width(self) -> int:
        return self.x_max - self.x_min

    @property
    def height(self) -> int:
        return self.y_max - self.y_min

    def to_mapping(self) -> dict[str, int]:
        return {
            "x_min": self.x_min,
            "y_min": self.y_min,
            "x_max": self.x_max,
            "y_max": self.y_max,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PixelBounds":
        data = _require_mapping(value, "pixel_bounds")
        _strict(data, {"x_min", "y_min", "x_max", "y_max"}, "pixel_bounds")
        try:
            return cls(**dict(data))
        except (TypeError, DerivedViewError) as error:
            raise DerivedViewError("pixel_bounds are invalid") from error


@dataclass(frozen=True, slots=True)
class DetectorBoxGeometry:
    """A detector-produced normalized box, kept distinct from a reviewed region."""

    x_min: int
    y_min: int
    x_max: int
    y_max: int

    kind: str = "detector-box/v1"

    def __post_init__(self) -> None:
        if self.kind != "detector-box/v1":
            raise DerivedViewError("detector geometry has an unsupported kind")
        for name, value in (
            ("x_min", self.x_min),
            ("y_min", self.y_min),
            ("x_max", self.x_max),
            ("y_max", self.y_max),
        ):
            _require_coordinate(value, f"detector_box.{name}")
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise DerivedViewError("detector box must have positive dimensions")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "box_2d": {
                "x_min": self.x_min,
                "y_min": self.y_min,
                "x_max": self.x_max,
                "y_max": self.y_max,
            },
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "DetectorBoxGeometry":
        data = _require_mapping(value, "detector geometry")
        _strict(data, {"kind", "box_2d"}, "detector geometry")
        box = _require_mapping(data["box_2d"], "detector geometry.box_2d")
        _strict(box, {"x_min", "y_min", "x_max", "y_max"}, "detector geometry.box_2d")
        try:
            return cls(
                x_min=box["x_min"],
                y_min=box["y_min"],
                x_max=box["x_max"],
                y_max=box["y_max"],
                kind=data["kind"],
            )
        except (TypeError, DerivedViewError) as error:
            raise DerivedViewError("detector geometry is invalid") from error


@dataclass(frozen=True, slots=True)
class ReviewedVisibleRegionGeometry:
    """One or more reviewed polygons containing only visible card pixels."""

    polygons: tuple[tuple[tuple[int, int], ...], ...]
    kind: str = "reviewed-visible-region/v1"

    def __post_init__(self) -> None:
        if self.kind != "reviewed-visible-region/v1":
            raise DerivedViewError("reviewed geometry has an unsupported kind")
        if not isinstance(self.polygons, tuple) or not self.polygons:
            raise DerivedViewError("reviewed visible region needs one or more polygons")
        for polygon_index, polygon in enumerate(self.polygons):
            if not isinstance(polygon, tuple) or len(polygon) < 3:
                raise DerivedViewError(f"reviewed polygon {polygon_index} needs three points")
            for point_index, point in enumerate(polygon):
                if (
                    not isinstance(point, tuple)
                    or len(point) != 2
                    or isinstance(point[0], bool)
                    or isinstance(point[1], bool)
                ):
                    raise DerivedViewError(
                        f"reviewed polygon {polygon_index} point {point_index} is invalid"
                    )
                _require_coordinate(point[0], "reviewed point x")
                _require_coordinate(point[1], "reviewed point y")
            if abs(_polygon_area(polygon)) <= 0.0:
                raise DerivedViewError(f"reviewed polygon {polygon_index} must have positive area")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "visible_region": {
                "polygons": [
                    [{"x": point[0], "y": point[1]} for point in polygon]
                    for polygon in self.polygons
                ]
            },
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "ReviewedVisibleRegionGeometry":
        data = _require_mapping(value, "reviewed geometry")
        _strict(data, {"kind", "visible_region"}, "reviewed geometry")
        region = _require_mapping(data["visible_region"], "reviewed geometry.visible_region")
        _strict(region, {"polygons"}, "reviewed geometry.visible_region")
        polygons_value = region["polygons"]
        if not isinstance(polygons_value, list):
            raise DerivedViewError("reviewed geometry polygons must be a list")
        polygons: list[tuple[tuple[int, int], ...]] = []
        for polygon_value in polygons_value:
            if not isinstance(polygon_value, list):
                raise DerivedViewError("reviewed geometry polygon must be a list")
            points: list[tuple[int, int]] = []
            for point_value in polygon_value:
                point = _require_mapping(point_value, "reviewed geometry point")
                _strict(point, {"x", "y"}, "reviewed geometry point")
                points.append((point["x"], point["y"]))
            polygons.append(tuple(points))
        try:
            return cls(polygons=tuple(polygons), kind=data["kind"])
        except (TypeError, DerivedViewError) as error:
            raise DerivedViewError("reviewed geometry is invalid") from error


@dataclass(frozen=True, slots=True)
class PredictedVisibleRegionGeometry:
    """One or more predicted polygons containing visible card pixels."""

    polygons: tuple[tuple[tuple[int, int], ...], ...]
    kind: str = "visible-region/v1"

    def __post_init__(self) -> None:
        if self.kind != "visible-region/v1":
            raise DerivedViewError("predicted geometry has an unsupported kind")
        if not isinstance(self.polygons, tuple) or not self.polygons:
            raise DerivedViewError("predicted visible region needs one or more polygons")
        for polygon_index, polygon in enumerate(self.polygons):
            if not isinstance(polygon, tuple) or len(polygon) < 3:
                raise DerivedViewError(f"predicted polygon {polygon_index} needs three points")
            for point_index, point in enumerate(polygon):
                if (
                    not isinstance(point, tuple)
                    or len(point) != 2
                    or isinstance(point[0], bool)
                    or isinstance(point[1], bool)
                ):
                    raise DerivedViewError(
                        f"predicted polygon {polygon_index} point {point_index} is invalid"
                    )
                _require_coordinate(point[0], "predicted point x")
                _require_coordinate(point[1], "predicted point y")
            if abs(_polygon_area(polygon)) <= 0.0:
                raise DerivedViewError(f"predicted polygon {polygon_index} must have positive area")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "visible_region": {
                "polygons": [
                    [{"x": point[0], "y": point[1]} for point in polygon]
                    for polygon in self.polygons
                ]
            },
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PredictedVisibleRegionGeometry":
        data = _require_mapping(value, "predicted geometry")
        _strict(data, {"kind", "visible_region"}, "predicted geometry")
        region = _require_mapping(data["visible_region"], "predicted geometry.visible_region")
        _strict(region, {"polygons"}, "predicted geometry.visible_region")
        polygons_value = region["polygons"]
        if not isinstance(polygons_value, list):
            raise DerivedViewError("predicted geometry polygons must be a list")
        polygons: list[tuple[tuple[int, int], ...]] = []
        for polygon_value in polygons_value:
            if not isinstance(polygon_value, list):
                raise DerivedViewError("predicted geometry polygon must be a list")
            points: list[tuple[int, int]] = []
            for point_value in polygon_value:
                point = _require_mapping(point_value, "predicted geometry point")
                _strict(point, {"x", "y"}, "predicted geometry point")
                points.append((point["x"], point["y"]))
            polygons.append(tuple(points))
        try:
            return cls(polygons=tuple(polygons), kind=data["kind"])
        except (TypeError, DerivedViewError) as error:
            raise DerivedViewError("predicted geometry is invalid") from error


RegionGeometry = PredictedVisibleRegionGeometry | ReviewedVisibleRegionGeometry
CropGeometry = DetectorBoxGeometry | RegionGeometry


@dataclass(frozen=True, slots=True)
class VisibleRegionExclusionInput:
    """One recorded neighboring region considered for visible-region exclusion."""

    proposal_id: str
    geometry: RegionGeometry
    source: str
    eligible: bool = True
    eligibility_reason: str = "eligible"
    provider_confidence: float | None = None
    geometry_diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.proposal_id, "exclusion proposal_id")
        if not isinstance(
            self.geometry, (PredictedVisibleRegionGeometry, ReviewedVisibleRegionGeometry)
        ):
            raise DerivedViewError("exclusion geometry must be a visible region")
        if self.source not in _EXCLUSION_SOURCES:
            raise DerivedViewError("exclusion source must be generated or reviewed")
        expected_kind = (
            "visible-region/v1" if self.source == "generated" else "reviewed-visible-region/v1"
        )
        if self.geometry.kind != expected_kind:
            raise DerivedViewError("exclusion source does not match geometry kind")
        if not isinstance(self.eligible, bool):
            raise DerivedViewError("exclusion eligible must be a boolean")
        _require_text(self.eligibility_reason, "exclusion eligibility_reason")
        if self.provider_confidence is not None and (
            isinstance(self.provider_confidence, bool)
            or not isinstance(self.provider_confidence, (int, float))
            or not math.isfinite(float(self.provider_confidence))
            or not 0.0 <= float(self.provider_confidence) <= 1.0
        ):
            raise DerivedViewError("exclusion provider_confidence must be from 0 through 1")
        if not isinstance(self.geometry_diagnostics, tuple) or any(
            not isinstance(item, str) or not item for item in self.geometry_diagnostics
        ):
            raise DerivedViewError("exclusion geometry_diagnostics must be non-empty strings")
        if len(set(self.geometry_diagnostics)) != len(self.geometry_diagnostics):
            raise DerivedViewError("exclusion geometry_diagnostics must be unique")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "geometry": self.geometry.to_mapping(),
            "source": self.source,
            "eligible": self.eligible,
            "eligibility_reason": self.eligibility_reason,
            "provider_confidence": self.provider_confidence,
            "geometry_diagnostics": list(self.geometry_diagnostics),
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "VisibleRegionExclusionInput":
        data = _require_mapping(value, "exclusion input")
        _strict(
            data,
            {
                "proposal_id",
                "geometry",
                "source",
                "eligible",
                "eligibility_reason",
                "provider_confidence",
                "geometry_diagnostics",
            },
            "exclusion input",
        )
        diagnostics = data["geometry_diagnostics"]
        if not isinstance(diagnostics, list):
            raise DerivedViewError("exclusion geometry_diagnostics must be a list")
        try:
            return cls(
                proposal_id=data["proposal_id"],
                geometry=parse_geometry(data["geometry"]),
                source=data["source"],
                eligible=data["eligible"],
                eligibility_reason=data["eligibility_reason"],
                provider_confidence=data["provider_confidence"],
                geometry_diagnostics=tuple(diagnostics),
            )
        except (TypeError, DerivedViewError) as error:
            raise DerivedViewError("exclusion input is invalid") from error


@dataclass(frozen=True, slots=True)
class VisibleRegionCorruption:
    """One deterministic predicted geometry derived from a reviewed region."""

    family: str
    severity: int | float
    seed: int
    source_geometry: ReviewedVisibleRegionGeometry
    output_geometry: CropGeometry
    transform_version: str = _CORRUPTION_TRANSFORM_VERSION

    def __post_init__(self) -> None:
        if self.family not in SUPPORTED_CORRUPTION_FAMILIES:
            raise DerivedViewError("unsupported visible-region corruption family")
        if (
            isinstance(self.severity, bool)
            or not isinstance(self.severity, (int, float))
            or not math.isfinite(float(self.severity))
            or self.severity <= 0
        ):
            raise DerivedViewError("corruption severity must be a positive finite number")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise DerivedViewError("corruption seed must be an integer")
        _require_text(self.transform_version, "corruption transform_version")
        if not isinstance(self.source_geometry, ReviewedVisibleRegionGeometry):
            raise DerivedViewError("corruption source must be reviewed geometry")
        if not isinstance(
            self.output_geometry,
            (DetectorBoxGeometry, PredictedVisibleRegionGeometry, ReviewedVisibleRegionGeometry),
        ):
            raise DerivedViewError("corruption output geometry is invalid")

    @property
    def source_geometry_sha256(self) -> str:
        return _geometry_digest(self.source_geometry)

    @property
    def output_geometry_sha256(self) -> str:
        return _geometry_digest(self.output_geometry)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "severity": self.severity,
            "seed": self.seed,
            "source_geometry": self.source_geometry.to_mapping(),
            "output_geometry": self.output_geometry.to_mapping(),
            "source_geometry_sha256": self.source_geometry_sha256,
            "output_geometry_sha256": self.output_geometry_sha256,
            "transform_version": self.transform_version,
        }


def generate_visible_region_corruption(
    geometry: ReviewedVisibleRegionGeometry | Mapping[str, Any],
    family: str,
    severity: int | float,
    *,
    seed: int,
    donor_geometry: ReviewedVisibleRegionGeometry | PredictedVisibleRegionGeometry | None = None,
) -> VisibleRegionCorruption:
    """Create a deterministic predicted geometry without reading an identity label."""

    source = (
        geometry
        if isinstance(geometry, ReviewedVisibleRegionGeometry)
        else parse_geometry(geometry)
    )
    if not isinstance(source, ReviewedVisibleRegionGeometry):
        raise DerivedViewError("corruption source geometry must be reviewed geometry")
    if family not in SUPPORTED_CORRUPTION_FAMILIES:
        raise DerivedViewError("unsupported visible-region corruption family")
    if (
        isinstance(severity, bool)
        or not isinstance(severity, (int, float))
        or not math.isfinite(float(severity))
        or severity <= 0
    ):
        raise DerivedViewError("corruption severity must be a positive finite number")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise DerivedViewError("corruption seed must be an integer")

    if family == "complete_derived_box_fallback":
        output: CropGeometry = _derived_box_geometry(source)
    else:
        polygons = list(source.polygons)
        if family == "erosion_missing_boundary_pixels":
            polygons = _scale_polygons(polygons, max(0.05, 1.0 - float(severity)))
        elif family == "dilation_into_background_or_neighbor":
            polygons = _scale_polygons(polygons, 1.0 + float(severity))
        elif family == "position_shift":
            polygons = _shift_polygons(polygons, severity=float(severity), seed=seed)
        elif family == "holes_missing_connected_components":
            polygons = _remove_components(polygons, severity=float(severity), seed=seed)
        elif family == "false_disconnected_components":
            polygons.append(_synthetic_component(polygons, severity=float(severity), seed=seed))
        elif family == "pixels_from_another_visible_card":
            if donor_geometry is not None:
                polygons.extend(donor_geometry.polygons)
            else:
                polygons.append(_synthetic_component(polygons, severity=float(severity), seed=seed))
        output = PredictedVisibleRegionGeometry(polygons=tuple(polygons))
    return VisibleRegionCorruption(
        family=family,
        severity=severity,
        seed=seed,
        source_geometry=source,
        output_geometry=output,
    )


def _scale_polygons(
    polygons: Sequence[tuple[tuple[int, int], ...]], scale: float
) -> list[tuple[tuple[int, int], ...]]:
    points = [point for polygon in polygons for point in polygon]
    center_x = sum(point[0] for point in points) / len(points)
    center_y = sum(point[1] for point in points) / len(points)
    return [
        tuple(
            (
                _clamp_coordinate(round(center_x + (point[0] - center_x) * scale)),
                _clamp_coordinate(round(center_y + (point[1] - center_y) * scale)),
            )
            for point in polygon
        )
        for polygon in polygons
    ]


def _shift_polygons(
    polygons: Sequence[tuple[tuple[int, int], ...]], *, severity: float, seed: int
) -> list[tuple[tuple[int, int], ...]]:
    points = [point for polygon in polygons for point in polygon]
    width = max(point[0] for point in points) - min(point[0] for point in points)
    height = max(point[1] for point in points) - min(point[1] for point in points)
    generator = random.Random(seed)
    shift_x = round(width * severity * (0.5 + generator.random())) * generator.choice((-1, 1))
    shift_y = round(height * severity * (0.5 + generator.random())) * generator.choice((-1, 1))
    return [
        tuple(
            (
                _clamp_coordinate(point[0] + shift_x),
                _clamp_coordinate(point[1] + shift_y),
            )
            for point in polygon
        )
        for polygon in polygons
    ]


def _remove_components(
    polygons: Sequence[tuple[tuple[int, int], ...]], *, severity: float, seed: int
) -> list[tuple[tuple[int, int], ...]]:
    if len(polygons) <= 1:
        return _scale_polygons(polygons, max(0.05, 1.0 - severity))
    remove_count = min(len(polygons) - 1, max(1, round(len(polygons) * severity)))
    generator = random.Random(seed)
    removed = set(generator.sample(range(len(polygons)), remove_count))
    return [polygon for index, polygon in enumerate(polygons) if index not in removed]


def _synthetic_component(
    polygons: Sequence[tuple[tuple[int, int], ...]], *, severity: float, seed: int
) -> tuple[tuple[int, int], ...]:
    points = [point for polygon in polygons for point in polygon]
    generator = random.Random(seed)
    size = max(
        4,
        round(
            min(
                1000,
                max(
                    1,
                    min(
                        max(point[0] for point in points) - min(point[0] for point in points),
                        max(point[1] for point in points) - min(point[1] for point in points),
                    ),
                ),
            )
            * min(1.0, severity)
            / 2
        ),
    )
    x = generator.randrange(0, max(1, 1001 - size))
    y = generator.randrange(0, max(1, 1001 - size))
    return ((x, y), (x + size, y), (x + size, y + size), (x, y + size))


def _derived_box_geometry(geometry: ReviewedVisibleRegionGeometry) -> DetectorBoxGeometry:
    points = [point for polygon in geometry.polygons for point in polygon]
    return DetectorBoxGeometry(
        x_min=min(point[0] for point in points),
        y_min=min(point[1] for point in points),
        x_max=max(point[0] for point in points),
        y_max=max(point[1] for point in points),
    )


def _clamp_coordinate(value: int) -> int:
    return max(0, min(1000, value))


def parse_geometry(value: Any) -> CropGeometry:
    """Parse one tagged detector, predicted, or reviewed geometry."""

    data = _require_mapping(value, "geometry")
    kind = data.get("kind")
    if kind == "detector-box/v1":
        return DetectorBoxGeometry.from_mapping(data)
    if kind == "visible-region/v1":
        return PredictedVisibleRegionGeometry.from_mapping(data)
    if kind == "reviewed-visible-region/v1":
        return ReviewedVisibleRegionGeometry.from_mapping(data)
    raise DerivedViewError(f"geometry kind must be one of {sorted(_GEOMETRY_KINDS)}")


@dataclass(frozen=True, slots=True)
class VisibleRegionCropRequest:
    """Frozen input values for one identity crop derived from a resolved frame."""

    frame_identity: Mapping[str, Any]
    geometry: CropGeometry
    width: int
    height: int
    crop_policy: str
    output_encoding: str = "ppm"
    decoder_version: str = DEFAULT_DECODER_VERSION
    transform_version: str = DEFAULT_TRANSFORM_VERSION
    identity_usable: bool = True
    failure_tags: tuple[str, ...] = ()
    exclusion_inputs: tuple[VisibleRegionExclusionInput, ...] = ()

    def __post_init__(self) -> None:
        _require_mapping(self.frame_identity, "crop frame_identity")
        if not isinstance(
            self.geometry,
            (DetectorBoxGeometry, PredictedVisibleRegionGeometry, ReviewedVisibleRegionGeometry),
        ):
            raise DerivedViewError("crop geometry must be tagged detector or reviewed geometry")
        _require_int(self.width, "crop width", minimum=1)
        _require_int(self.height, "crop height", minimum=1)
        if self.crop_policy not in SUPPORTED_CROP_POLICIES:
            raise DerivedViewError("unsupported crop policy")
        expected_geometry = {
            "raw_rectangular": DetectorBoxGeometry,
            "generated_other_region_exclusion": DetectorBoxGeometry,
            "reviewed_other_region_exclusion": DetectorBoxGeometry,
            "predicted_visible_region": PredictedVisibleRegionGeometry,
            "predicted_region_with_other_exclusion": PredictedVisibleRegionGeometry,
            "oracle_visible_region": ReviewedVisibleRegionGeometry,
        }.get(self.crop_policy)
        if expected_geometry is not None and not isinstance(self.geometry, expected_geometry):
            raise DerivedViewError(
                f"{self.crop_policy} needs {expected_geometry.__name__} geometry"
            )
        if self.output_encoding not in SUPPORTED_CROP_ENCODINGS:
            raise DerivedViewError("unsupported crop output encoding")
        _require_text(self.decoder_version, "crop decoder_version")
        _require_text(self.transform_version, "crop transform_version")
        if not isinstance(self.identity_usable, bool):
            raise DerivedViewError("identity_usable must be a boolean")
        if not isinstance(self.failure_tags, tuple) or any(
            not isinstance(tag, str) or not tag for tag in self.failure_tags
        ):
            raise DerivedViewError("failure_tags must be a tuple of non-empty strings")
        if len(set(self.failure_tags)) != len(self.failure_tags):
            raise DerivedViewError("failure_tags must be unique")
        if not isinstance(self.exclusion_inputs, tuple) or any(
            not isinstance(item, VisibleRegionExclusionInput) for item in self.exclusion_inputs
        ):
            raise DerivedViewError("exclusion_inputs must contain visible-region inputs")
        proposal_ids = [item.proposal_id for item in self.exclusion_inputs]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise DerivedViewError("exclusion_inputs must have unique proposal IDs")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": VISIBLE_REGION_CROP_SCHEMA,
            "frame_identity": dict(self.frame_identity),
            "geometry": self.geometry.to_mapping(),
            "width": self.width,
            "height": self.height,
            "crop_policy": self.crop_policy,
            "output_encoding": self.output_encoding,
            "decoder_version": self.decoder_version,
            "transform_version": self.transform_version,
            "identity_usable": self.identity_usable,
            "failure_tags": list(self.failure_tags),
            "exclusion_inputs": [item.to_mapping() for item in self.exclusion_inputs],
            "exclusion_policy": _exclusion_policy_mapping(),
        }


@dataclass(frozen=True, slots=True)
class ResolvedCrop:
    """A usable or explicit unusable crop result."""

    status: str
    frame_identity: Mapping[str, Any]
    geometry: CropGeometry
    pixel_bounds: PixelBounds | None
    crop_policy: str
    output_encoding: str
    decoder_version: str
    transform_version: str
    image_bytes: bytes | None
    unusable_reason: str | None = None
    exclusion_inputs: tuple[VisibleRegionExclusionInput, ...] = ()
    exclusion_decisions: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"usable", "unusable"}:
            raise DerivedViewError("crop status must be usable or unusable")
        _require_mapping(self.frame_identity, "crop frame_identity")
        if not isinstance(
            self.geometry,
            (DetectorBoxGeometry, PredictedVisibleRegionGeometry, ReviewedVisibleRegionGeometry),
        ):
            raise DerivedViewError("crop geometry is invalid")
        if self.crop_policy not in SUPPORTED_CROP_POLICIES:
            raise DerivedViewError("crop policy is invalid")
        if self.output_encoding not in SUPPORTED_CROP_ENCODINGS:
            raise DerivedViewError("crop output encoding is invalid")
        _require_text(self.decoder_version, "crop decoder_version")
        _require_text(self.transform_version, "crop transform_version")
        if self.status == "usable":
            if self.pixel_bounds is None or not isinstance(self.image_bytes, bytes):
                raise DerivedViewError("usable crop needs bounds and bytes")
            if not self.image_bytes:
                raise DerivedViewError("usable crop bytes must be non-empty")
            if self.unusable_reason is not None:
                raise DerivedViewError("usable crop cannot have an unusable reason")
        elif self.image_bytes is not None or not self.unusable_reason:
            raise DerivedViewError("unusable crop needs a reason and no bytes")
        if not isinstance(self.exclusion_inputs, tuple) or any(
            not isinstance(item, VisibleRegionExclusionInput) for item in self.exclusion_inputs
        ):
            raise DerivedViewError("exclusion_inputs must contain visible-region inputs")
        if not isinstance(self.exclusion_decisions, tuple) or any(
            not isinstance(item, Mapping) for item in self.exclusion_decisions
        ):
            raise DerivedViewError("exclusion_decisions must contain objects")

    @property
    def image_sha256(self) -> str | None:
        return None if self.image_bytes is None else _sha256(self.image_bytes)

    @property
    def content_type(self) -> str:
        return _content_type(self.output_encoding)

    def identity_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": VISIBLE_REGION_CROP_SCHEMA,
            "status": self.status,
            "frame_identity": dict(self.frame_identity),
            "geometry": self.geometry.to_mapping(),
            "pixel_bounds": None if self.pixel_bounds is None else self.pixel_bounds.to_mapping(),
            "crop_policy": self.crop_policy,
            "output_encoding": self.output_encoding,
            "content_type": self.content_type,
            "decoder_version": self.decoder_version,
            "transform_version": self.transform_version,
            "image_sha256": self.image_sha256,
            "unusable_reason": self.unusable_reason,
            "exclusion_inputs": [item.to_mapping() for item in self.exclusion_inputs],
            "exclusion_decisions": [dict(item) for item in self.exclusion_decisions],
            "exclusion_policy": _exclusion_policy_mapping(),
        }


@dataclass(frozen=True, slots=True)
class DerivedViewCacheEntry:
    """Verified bytes and manifest read from a derived-view cache directory."""

    manifest: Mapping[str, Any]
    content: bytes


class DerivedViewCache:
    """A disposable, digest-verified cache below ``derived-views``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise DerivedViewCacheError(f"cache root is not a directory: {self.root}")

    def path(self, cache_key: str) -> Path:
        if _CACHE_KEY.fullmatch(cache_key) is None:
            raise DerivedViewCacheError("cache_key must be a lower-case SHA-256 digest")
        return self.root / cache_key

    def read(self, cache_key: str) -> DerivedViewCacheEntry | None:
        directory = self.path(cache_key)
        if not directory.is_dir() or directory.is_symlink():
            return None
        manifest_path = directory / "manifest.json"
        content_path = directory / "content.bin"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            content = content_path.read_bytes()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(manifest, dict):
            return None
        expected = {
            "schema_version",
            "cache_key",
            "view_kind",
            "identity",
            "content_sha256",
            "byte_length",
        }
        if set(manifest) != expected:
            return None
        if manifest.get("schema_version") != DERIVED_VIEW_CACHE_SCHEMA:
            return None
        if manifest.get("cache_key") != cache_key:
            return None
        try:
            digest = _require_digest(manifest["content_sha256"], "cache content_sha256")
            length = _require_int(manifest["byte_length"], "cache byte_length", minimum=0)
        except DerivedViewError:
            return None
        if length != len(content) or digest != _sha256(content):
            return None
        return DerivedViewCacheEntry(manifest=manifest, content=content)

    def write(
        self,
        cache_key: str,
        manifest: Mapping[str, Any],
        content: bytes,
    ) -> DerivedViewCacheEntry:
        destination = self.path(cache_key)
        if not isinstance(content, bytes):
            raise DerivedViewCacheError("cache content must be bytes")
        data = dict(_require_mapping(manifest, "cache manifest"))
        _strict(data, {"schema_version", "cache_key", "view_kind", "identity"}, "cache manifest")
        if data.get("schema_version") != DERIVED_VIEW_CACHE_SCHEMA:
            raise DerivedViewCacheError("cache manifest has an unsupported schema")
        if data.get("cache_key") != cache_key:
            raise DerivedViewCacheError("cache manifest key does not match the path")
        data["content_sha256"] = _sha256(content)
        data["byte_length"] = len(content)
        manifest_bytes = canonical_json_bytes(data)
        parent = self.root.resolve()
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=parent))
        try:
            _write_fsync(staging / "manifest.json", manifest_bytes)
            _write_fsync(staging / "content.bin", content)
            if destination.is_symlink():
                destination.unlink()
            elif destination.exists():
                shutil.rmtree(destination)
            os.replace(staging, destination)
            staging = Path()
        finally:
            if staging != Path() and (staging.exists() or staging.is_symlink()):
                shutil.rmtree(staging)
        return DerivedViewCacheEntry(manifest=data, content=content)


class FrameResolver(Protocol):
    """Provider boundary for exact-event frame resolution."""

    decoder_version: str
    transform_version: str

    def resolve(self, request: ExactEventRequest, video_path: Path) -> ResolvedFrame:
        """Resolve one request from a source video without using a cache."""


class FFmpegFrameResolver:
    """Resolve exact-event frames with FFmpeg presentation timestamps."""

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        decoder_version: str = DEFAULT_DECODER_VERSION,
    ) -> None:
        self.ffmpeg_binary = _require_text(ffmpeg_binary, "ffmpeg_binary")
        self.ffprobe_binary = _require_text(ffprobe_binary, "ffprobe_binary")
        self.decoder_version = _require_text(decoder_version, "decoder_version")
        self.transform_version = DEFAULT_FRAME_TRANSFORM_VERSION

    def resolve(self, request: ExactEventRequest, video_path: Path) -> ResolvedFrame:
        if not isinstance(request, ExactEventRequest):
            raise DerivedViewError("frame resolver needs an exact-event request")
        path = Path(video_path)
        if not path.is_file():
            raise DerivedViewSourceError(f"source video does not exist: {path}")
        frames = self._probe_frames(path)
        selected_candidates = [
            (frame_index, timestamp_us, width, height)
            for frame_index, (timestamp_us, width, height) in enumerate(frames)
            if timestamp_us >= request.requested_time_us
        ]
        selected = min(selected_candidates, key=lambda value: (value[1], value[0]), default=None)
        if selected is None:
            raise DerivedViewMissingFrameError(
                "no presentation timestamp is at or after the requested event time"
            )
        frame_index, timestamp_us, width, height = selected
        image_bytes = self._decode_frame(path, frame_index, request.output_encoding)
        actual_width, actual_height = _image_dimensions(image_bytes)
        if (actual_width, actual_height) != (width, height):
            raise DerivedViewProbeError("decoded frame dimensions do not match ffprobe")
        return ResolvedFrame(
            requested_time_us=request.requested_time_us,
            frame_index=frame_index,
            presentation_timestamp_us=timestamp_us,
            source_video_sha256=request.source.video_sha256,
            width=width,
            height=height,
            decoder_version=self.decoder_version,
            transform_version=self.transform_version,
            output_encoding=request.output_encoding,
            image_bytes=image_bytes,
        )

    def _probe_frames(self, video_path: Path) -> list[tuple[int, int, int]]:
        command = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time,width,height",
            "-of",
            "json",
            str(video_path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, check=False)
        except (OSError, subprocess.SubprocessError) as error:
            raise DerivedViewProbeError(
                f"ffprobe could not inspect source video: {error}"
            ) from error
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise DerivedViewProbeError(
                f"ffprobe could not inspect source video: {detail or 'unknown error'}"
            )
        try:
            payload = json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DerivedViewProbeError("ffprobe returned invalid frame metadata") from error
        if not isinstance(payload, Mapping) or not isinstance(payload.get("frames"), list):
            raise DerivedViewProbeError("ffprobe returned incomplete frame metadata")
        frames: list[tuple[int, int, int]] = []
        for index, raw in enumerate(payload["frames"]):
            frame = _require_mapping(raw, f"ffprobe frame {index}")
            if "best_effort_timestamp_time" not in frame:
                raise DerivedViewProbeError(f"ffprobe frame {index} has no presentation timestamp")
            timestamp_us = _timestamp_us(
                frame["best_effort_timestamp_time"], "presentation timestamp"
            )
            width = _require_positive_probe_int(frame.get("width"), "frame width")
            height = _require_positive_probe_int(frame.get("height"), "frame height")
            frames.append((timestamp_us, width, height))
        if not frames:
            raise DerivedViewProbeError("source video has no decoded frames")
        return frames

    def _decode_frame(self, video_path: Path, frame_index: int, encoding: str) -> bytes:
        if encoding != "jpeg":
            raise DerivedViewError("the FFmpeg frame provider currently emits JPEG frames")
        filter_expression = f"select=eq(n\\,{frame_index})"
        command = [
            self.ffmpeg_binary,
            "-v",
            "error",
            "-i",
            str(video_path),
            "-vf",
            filter_expression,
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-c:v",
            "mjpeg",
            "-q:v",
            "2",
            "-",
        ]
        try:
            result = subprocess.run(command, capture_output=True, check=False)
        except (OSError, subprocess.SubprocessError) as error:
            raise DerivedViewProbeError(
                f"ffmpeg could not extract frame {frame_index}: {error}"
            ) from error
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise DerivedViewProbeError(
                f"ffmpeg could not extract frame {frame_index}: {detail or 'unknown error'}"
            )
        if not result.stdout:
            raise DerivedViewMissingFrameError(f"ffmpeg returned no frame for index {frame_index}")
        return result.stdout


class OpenCVFrameResolver:
    """Optional OpenCV adapter for existing local paths that need it."""

    def __init__(self, *, jpeg_quality: int = 85, decoder_version: str = "opencv/optional") -> None:
        if (
            isinstance(jpeg_quality, bool)
            or not isinstance(jpeg_quality, int)
            or not 1 <= jpeg_quality <= 100
        ):
            raise DerivedViewError("jpeg_quality must be an integer from 1 through 100")
        self.jpeg_quality = jpeg_quality
        self.decoder_version = _require_text(decoder_version, "decoder_version")
        self.transform_version = f"opencv-jpeg/{jpeg_quality}/v1"

    def resolve(self, request: ExactEventRequest, video_path: Path) -> ResolvedFrame:
        if request.output_encoding != "jpeg":
            raise DerivedViewError("the OpenCV frame provider currently emits JPEG frames")
        try:
            import cv2
        except ModuleNotFoundError as error:
            raise DerivedViewProbeError(
                "OpenCV is required for the OpenCV frame provider"
            ) from error
        path = Path(video_path)
        if not path.is_file():
            raise DerivedViewSourceError(f"source video does not exist: {path}")
        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                raise DerivedViewProbeError(f"OpenCV could not open source video: {path}")
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            if not math.isfinite(fps) or fps <= 0:
                raise DerivedViewProbeError("OpenCV returned an invalid frame rate")
            frame_index = 0
            selected: tuple[int, int, Any] | None = None
            while True:
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                timestamp_us = int(round(frame_index / fps * 1_000_000))
                if timestamp_us >= request.requested_time_us:
                    selected = (frame_index, timestamp_us, frame)
                    break
                frame_index += 1
            if selected is None:
                raise DerivedViewMissingFrameError(
                    "no OpenCV frame is at or after the requested event time"
                )
            frame_index, timestamp_us, frame = selected
            encoded, buffer = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            )
            if not encoded:
                raise DerivedViewProbeError(f"OpenCV could not encode frame {frame_index}")
            height, width = frame.shape[:2]
            return ResolvedFrame(
                requested_time_us=request.requested_time_us,
                frame_index=frame_index,
                presentation_timestamp_us=timestamp_us,
                source_video_sha256=request.source.video_sha256,
                width=int(width),
                height=int(height),
                decoder_version=self.decoder_version,
                transform_version=self.transform_version,
                output_encoding="jpeg",
                image_bytes=buffer.tobytes(),
            )
        finally:
            capture.release()


def frame_cache_key(
    request: ExactEventRequest,
    *,
    decoder_version: str,
    transform_version: str = DEFAULT_FRAME_TRANSFORM_VERSION,
) -> str:
    """Return the cache key for an exact-event request."""

    return _sha256(
        canonical_json_bytes(
            request.to_mapping(
                decoder_version=decoder_version,
                transform_version=transform_version,
            )
        )
    )


def resolve_exact_event(
    video_path: str | Path,
    *,
    source: RecordingVideoSource | Mapping[str, Any],
    requested_time_us: int,
    cache: DerivedViewCache | str | Path | None = None,
    resolver: FrameResolver | None = None,
    output_encoding: str = "jpeg",
) -> ResolvedFrame:
    """Resolve the first source presentation timestamp at or after an event time."""

    accepted_source = (
        source
        if isinstance(source, RecordingVideoSource)
        else RecordingVideoSource.from_mapping(source)
    )
    request = ExactEventRequest(
        source=accepted_source,
        requested_time_us=requested_time_us,
        output_encoding=output_encoding,
    )
    provider = resolver or FFmpegFrameResolver()
    decoder_version = _require_text(provider.decoder_version, "resolver.decoder_version")
    path = Path(video_path)
    _validate_source_video(path, accepted_source)
    cache_store = _cache_store(cache)
    key = frame_cache_key(
        request,
        decoder_version=decoder_version,
        transform_version=provider.transform_version,
    )
    if cache_store is not None:
        cached = cache_store.read(key)
        if cached is not None:
            try:
                return _frame_from_cache(cached, key)
            except DerivedViewError:
                pass
    frame = provider.resolve(request, path)
    if frame.source_video_sha256 != accepted_source.video_sha256:
        raise DerivedViewError("frame resolver returned a different source digest")
    if cache_store is not None:
        manifest = {
            "schema_version": DERIVED_VIEW_CACHE_SCHEMA,
            "cache_key": key,
            "view_kind": EXACT_EVENT_SCHEMA,
            "identity": frame.identity_mapping(),
        }
        cache_store.write(key, manifest, frame.image_bytes)
    return frame


def crop_cache_key(request: VisibleRegionCropRequest) -> str:
    """Return the cache key for a visible-region crop request."""

    return _sha256(canonical_json_bytes(request.to_mapping()))


def resolve_visible_region_crop(
    frame: ResolvedFrame,
    geometry: CropGeometry | Mapping[str, Any],
    *,
    crop_policy: str,
    width: int | None = None,
    height: int | None = None,
    output_encoding: str = "ppm",
    cache: DerivedViewCache | str | Path | None = None,
    identity_usable: bool = True,
    failure_tags: Sequence[str] = (),
    exclusion_inputs: Sequence[VisibleRegionExclusionInput | Mapping[str, Any]] = (),
    transform_version: str = DEFAULT_TRANSFORM_VERSION,
) -> ResolvedCrop:
    """Derive a crop from tagged geometry without changing the stored geometry."""

    if not isinstance(frame, ResolvedFrame):
        raise DerivedViewError("crop needs a resolved frame")
    accepted_geometry = (
        geometry
        if isinstance(
            geometry,
            (DetectorBoxGeometry, PredictedVisibleRegionGeometry, ReviewedVisibleRegionGeometry),
        )
        else parse_geometry(geometry)
    )
    accepted_exclusion_inputs = tuple(
        item
        if isinstance(item, VisibleRegionExclusionInput)
        else VisibleRegionExclusionInput.from_mapping(item)
        for item in exclusion_inputs
    )
    request = VisibleRegionCropRequest(
        frame_identity=frame.identity_mapping(),
        geometry=accepted_geometry,
        width=frame.width if width is None else width,
        height=frame.height if height is None else height,
        crop_policy=crop_policy,
        output_encoding=output_encoding,
        decoder_version=frame.decoder_version,
        transform_version=transform_version,
        identity_usable=identity_usable,
        failure_tags=tuple(failure_tags),
        exclusion_inputs=accepted_exclusion_inputs,
    )
    if (request.width, request.height) != (frame.width, frame.height):
        raise DerivedViewError("crop dimensions must match the resolved frame")
    key = crop_cache_key(request)
    cache_store = _cache_store(cache)
    if cache_store is not None:
        cached = cache_store.read(key)
        if cached is not None:
            try:
                return _crop_from_cache(cached, key)
            except DerivedViewError:
                pass
    result = _crop_uncached(frame, request)
    if cache_store is not None:
        manifest = {
            "schema_version": DERIVED_VIEW_CACHE_SCHEMA,
            "cache_key": key,
            "view_kind": VISIBLE_REGION_CROP_SCHEMA,
            "identity": result.identity_mapping(),
        }
        cache_store.write(key, manifest, result.image_bytes or b"")
    return result


def _crop_uncached(frame: ResolvedFrame, request: VisibleRegionCropRequest) -> ResolvedCrop:
    exclusion_decisions, eligible_exclusions = _resolve_exclusion_decisions(request)
    if request.crop_policy == "conservative_box_only" and (
        not request.identity_usable or request.failure_tags
    ):
        return ResolvedCrop(
            status="unusable",
            frame_identity=request.frame_identity,
            geometry=request.geometry,
            pixel_bounds=None,
            crop_policy=request.crop_policy,
            output_encoding=request.output_encoding,
            decoder_version=request.decoder_version,
            transform_version=request.transform_version,
            image_bytes=None,
            unusable_reason="identity evidence is not usable under the conservative policy",
            exclusion_inputs=request.exclusion_inputs,
            exclusion_decisions=exclusion_decisions,
        )
    bounds = _geometry_pixel_bounds(
        request.geometry,
        width=request.width,
        height=request.height,
    )
    if bounds.width < 4 or bounds.height < 4:
        return ResolvedCrop(
            status="unusable",
            frame_identity=request.frame_identity,
            geometry=request.geometry,
            pixel_bounds=bounds,
            crop_policy=request.crop_policy,
            output_encoding=request.output_encoding,
            decoder_version=request.decoder_version,
            transform_version=request.transform_version,
            image_bytes=None,
            unusable_reason="crop is smaller than the minimum identity size",
            exclusion_inputs=request.exclusion_inputs,
            exclusion_decisions=exclusion_decisions,
        )
    try:
        with Image.open(BytesIO(frame.image_bytes)) as image:
            if image.size != (request.width, request.height):
                raise DerivedViewError("decoded frame dimensions do not match crop dimensions")
            crop = image.convert("RGB").crop(
                (bounds.x_min, bounds.y_min, bounds.x_max, bounds.y_max)
            )
            if request.crop_policy in {
                "predicted_visible_region",
                "predicted_region_with_other_exclusion",
                "oracle_visible_region",
            }:
                if not isinstance(
                    request.geometry,
                    (PredictedVisibleRegionGeometry, ReviewedVisibleRegionGeometry),
                ):
                    raise DerivedViewError(
                        "visible-region crop policy needs visible-region geometry"
                    )
                target_mask = _geometry_mask(
                    request.geometry,
                    width=request.width,
                    height=request.height,
                    bounds=bounds,
                )
                neutral = Image.new("RGB", crop.size, _NEUTRAL_FILL_RGB)
                crop = Image.composite(crop, neutral, target_mask)
            if eligible_exclusions:
                exclusion_mask = Image.new("L", crop.size, 0)
                for exclusion in eligible_exclusions:
                    region_mask = _geometry_mask(
                        exclusion.geometry,
                        width=request.width,
                        height=request.height,
                        bounds=bounds,
                    )
                    erosion_radius = _erosion_radius_pixels(
                        exclusion.geometry,
                        width=request.width,
                        height=request.height,
                    )
                    applied_erosion_radius = min(erosion_radius, max(0, (min(crop.size) - 1) // 2))
                    if applied_erosion_radius:
                        from PIL import ImageFilter

                        region_mask = region_mask.filter(
                            ImageFilter.MinFilter(size=2 * applied_erosion_radius + 1)
                        )
                    exclusion_mask = _mask_union(exclusion_mask, region_mask)
                neutral = Image.new("RGB", crop.size, _NEUTRAL_FILL_RGB)
                crop = Image.composite(neutral, crop, exclusion_mask)
            image_bytes = _encode_crop(crop, request.output_encoding)
    except UnidentifiedImageError as error:
        raise DerivedViewError("resolved frame cannot be decoded") from error
    except OSError as error:
        raise DerivedViewError(f"resolved frame cannot be decoded: {error}") from error
    return ResolvedCrop(
        status="usable",
        frame_identity=request.frame_identity,
        geometry=request.geometry,
        pixel_bounds=bounds,
        crop_policy=request.crop_policy,
        output_encoding=request.output_encoding,
        decoder_version=request.decoder_version,
        transform_version=request.transform_version,
        image_bytes=image_bytes,
        exclusion_inputs=request.exclusion_inputs,
        exclusion_decisions=exclusion_decisions,
    )


def _resolve_exclusion_decisions(
    request: VisibleRegionCropRequest,
) -> tuple[tuple[dict[str, Any], ...], tuple[VisibleRegionExclusionInput, ...]]:
    exclusion_policies = {
        "generated_other_region_exclusion": "generated",
        "predicted_region_with_other_exclusion": "generated",
        "reviewed_other_region_exclusion": "reviewed",
    }
    expected_source = exclusion_policies.get(request.crop_policy)
    decisions: list[dict[str, Any]] = []
    candidates: list[tuple[int, VisibleRegionExclusionInput]] = []
    target_digest = _geometry_digest(request.geometry)
    seen_geometry: dict[str, str] = {}
    for input_index, exclusion in enumerate(request.exclusion_inputs):
        geometry_digest = _geometry_digest(exclusion.geometry)
        decision: dict[str, Any] = {
            "proposal_id": exclusion.proposal_id,
            "source": exclusion.source,
            "geometry_sha256": geometry_digest,
            "eligible_input": exclusion.eligible,
            "eligibility_reason": exclusion.eligibility_reason,
            "provider_confidence": exclusion.provider_confidence,
            "geometry_diagnostics": list(exclusion.geometry_diagnostics),
            "decision": "not_used_by_policy",
        }
        if expected_source is None:
            decisions.append(decision)
            continue
        if exclusion.source != expected_source:
            decision.update(
                decision="ineligible_source",
                decision_reason=f"policy requires {expected_source} exclusion geometry",
            )
        elif not exclusion.eligible:
            decision.update(
                decision="ineligible_input", decision_reason=exclusion.eligibility_reason
            )
        elif geometry_digest == target_digest:
            decision.update(
                decision="target_geometry",
                decision_reason="target geometry is never excluded from itself",
            )
        elif geometry_digest in seen_geometry:
            decision.update(
                decision="duplicate_geometry",
                decision_reason=f"duplicate of {seen_geometry[geometry_digest]}",
            )
        else:
            seen_geometry[geometry_digest] = exclusion.proposal_id
            decision.update(
                decision="eligible_pending_overlap",
                erosion_fraction=_EXCLUSION_EROSION_FRACTION,
            )
            candidates.append((input_index, exclusion))
        decisions.append(decision)

    disputed: set[int] = set()
    for left_offset, (left_index, left) in enumerate(candidates):
        for right_index, right in candidates[left_offset + 1 :]:
            overlap = _geometry_overlap_fraction(left.geometry, right.geometry)
            if overlap >= _MATERIAL_OVERLAP_FRACTION:
                disputed.update({left_index, right_index})
                decisions[left_index].update(
                    decision="disputed_overlap",
                    decision_reason=(
                        f"overlap fraction {overlap:.6f} meets or exceeds "
                        f"{_MATERIAL_OVERLAP_FRACTION:.2f}"
                    ),
                    overlap_fraction=overlap,
                )
                decisions[right_index].update(
                    decision="disputed_overlap",
                    decision_reason=(
                        f"overlap fraction {overlap:.6f} meets or exceeds "
                        f"{_MATERIAL_OVERLAP_FRACTION:.2f}"
                    ),
                    overlap_fraction=overlap,
                )

    eligible: list[VisibleRegionExclusionInput] = []
    target_bounds = _geometry_pixel_bounds(
        request.geometry,
        width=request.width,
        height=request.height,
    )
    for candidate_index, exclusion in candidates:
        if candidate_index in disputed:
            continue
        erosion_radius = _erosion_radius_pixels(
            exclusion.geometry,
            width=request.width,
            height=request.height,
        )
        decisions[candidate_index].update(
            decision="excluded",
            erosion_radius_px=erosion_radius,
            applied_erosion_radius_px=min(
                erosion_radius, max(0, (min(target_bounds.width, target_bounds.height) - 1) // 2)
            ),
            erosion_rule="fixed fraction of exclusion derived-box minimum dimension",
        )
        eligible.append(exclusion)
    if expected_source is not None and not eligible:
        decisions.append(
            {
                "decision": "no_eligible_exclusion_region",
                "decision_reason": "no exclusion input passed the declared eligibility rules",
            }
        )
    return tuple(decisions), tuple(eligible)


def _exclusion_policy_mapping() -> dict[str, Any]:
    return {
        "schema_version": "visible-region-exclusion/v1",
        "eligibility_rule": _EXCLUSION_ELIGIBILITY_RULE,
        "erosion_fraction_of_derived_box": _EXCLUSION_EROSION_FRACTION,
        "material_overlap_fraction": _MATERIAL_OVERLAP_FRACTION,
        "disputed_overlap": "leave_unresolved",
        "deduplicate_geometry": True,
        "recursive_exclusion": False,
        "fill_value_rgb": list(_NEUTRAL_FILL_RGB),
    }


def _geometry_digest(geometry: CropGeometry) -> str:
    return _sha256(canonical_json_bytes(geometry.to_mapping()))


def _geometry_mask(
    geometry: RegionGeometry,
    *,
    width: int,
    height: int,
    bounds: PixelBounds,
):
    from PIL import ImageDraw

    mask = Image.new("L", (bounds.width, bounds.height), 0)
    draw = ImageDraw.Draw(mask)
    for polygon in geometry.polygons:
        draw.polygon(
            [
                (
                    point[0] * width / 1000 - bounds.x_min,
                    point[1] * height / 1000 - bounds.y_min,
                )
                for point in polygon
            ],
            fill=255,
        )
    return mask


def _mask_union(left, right):
    from PIL import ImageChops

    return ImageChops.lighter(left, right)


def _geometry_overlap_fraction(left: RegionGeometry, right: RegionGeometry) -> float:
    scale = 1001
    bounds = PixelBounds(0, 0, scale, scale)
    left_mask = _geometry_mask(left, width=scale, height=scale, bounds=bounds)
    right_mask = _geometry_mask(right, width=scale, height=scale, bounds=bounds)
    from PIL import ImageChops

    intersection = ImageChops.multiply(left_mask, right_mask)
    left_area = sum(bool(pixel) for pixel in left_mask.tobytes())
    right_area = sum(bool(pixel) for pixel in right_mask.tobytes())
    overlap_area = sum(bool(pixel) for pixel in intersection.tobytes())
    smallest_area = min(left_area, right_area)
    return overlap_area / smallest_area if smallest_area else 0.0


def _erosion_radius_pixels(geometry: RegionGeometry, *, width: int, height: int) -> int:
    points = [point for polygon in geometry.polygons for point in polygon]
    region_width = (
        (max(point[0] for point in points) - min(point[0] for point in points)) * width / 1000
    )
    region_height = (
        (max(point[1] for point in points) - min(point[1] for point in points)) * height / 1000
    )
    return max(0, round(min(region_width, region_height) * _EXCLUSION_EROSION_FRACTION))


def _encode_crop(image: Image.Image, encoding: str) -> bytes:
    if encoding == "ppm":
        return f"P6\n{image.width} {image.height}\n255\n".encode("ascii") + image.tobytes()
    output = BytesIO()
    if encoding == "jpeg":
        image.save(output, format="JPEG", quality=90)
    else:
        image.save(output, format="PNG")
    return output.getvalue()


def _geometry_pixel_bounds(
    geometry: CropGeometry,
    *,
    width: int,
    height: int,
) -> PixelBounds:
    if isinstance(geometry, DetectorBoxGeometry):
        points = ((geometry.x_min, geometry.y_min), (geometry.x_max, geometry.y_max))
    else:
        points = [point for polygon in geometry.polygons for point in polygon]
    return PixelBounds(
        x_min=max(0, math.floor(min(point[0] for point in points) * width / 1000)),
        y_min=max(0, math.floor(min(point[1] for point in points) * height / 1000)),
        x_max=min(width, math.ceil(max(point[0] for point in points) * width / 1000)),
        y_max=min(height, math.ceil(max(point[1] for point in points) * height / 1000)),
    )


def _polygon_area(points: Sequence[tuple[int, int]]) -> float:
    return (
        sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )
        / 2.0
    )


def _require_positive_probe_int(value: Any, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise DerivedViewProbeError(f"ffprobe returned an invalid {field}") from error
    if isinstance(value, bool) or result <= 0:
        raise DerivedViewProbeError(f"ffprobe returned an invalid {field}")
    return result


def _image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            return image.size
    except (UnidentifiedImageError, OSError) as error:
        raise DerivedViewProbeError("decoded frame is not a readable image") from error


def _cache_store(cache: DerivedViewCache | str | Path | None) -> DerivedViewCache | None:
    if cache is None:
        return None
    return cache if isinstance(cache, DerivedViewCache) else DerivedViewCache(cache)


def _frame_from_cache(entry: DerivedViewCacheEntry, cache_key: str) -> ResolvedFrame:
    manifest = _require_mapping(entry.manifest, "frame cache manifest")
    if manifest.get("view_kind") != EXACT_EVENT_SCHEMA or manifest.get("cache_key") != cache_key:
        raise DerivedViewError("cache entry is for a different derived view")
    identity = _require_mapping(manifest.get("identity"), "frame cache identity")
    expected = {
        "schema_version",
        "source_video_sha256",
        "requested_time_us",
        "frame_index",
        "presentation_timestamp_us",
        "width",
        "height",
        "decoder_version",
        "transform_version",
        "output_encoding",
        "content_type",
        "image_sha256",
        "policy",
    }
    _strict(identity, expected, "frame cache identity")
    if identity["schema_version"] != EXACT_EVENT_SCHEMA:
        raise DerivedViewError("frame cache identity has an unsupported schema")
    frame = ResolvedFrame(
        requested_time_us=identity["requested_time_us"],
        frame_index=identity["frame_index"],
        presentation_timestamp_us=identity["presentation_timestamp_us"],
        source_video_sha256=identity["source_video_sha256"],
        width=identity["width"],
        height=identity["height"],
        decoder_version=identity["decoder_version"],
        transform_version=identity["transform_version"],
        output_encoding=identity["output_encoding"],
        image_bytes=entry.content,
        policy=identity["policy"],
    )
    if (
        identity["content_type"] != frame.content_type
        or identity["image_sha256"] != frame.image_sha256
    ):
        raise DerivedViewError("frame cache identity does not match its bytes")
    return frame


def _crop_from_cache(entry: DerivedViewCacheEntry, cache_key: str) -> ResolvedCrop:
    manifest = _require_mapping(entry.manifest, "crop cache manifest")
    if (
        manifest.get("view_kind") != VISIBLE_REGION_CROP_SCHEMA
        or manifest.get("cache_key") != cache_key
    ):
        raise DerivedViewError("cache entry is for a different derived view")
    identity = _require_mapping(manifest.get("identity"), "crop cache identity")
    expected = {
        "schema_version",
        "status",
        "frame_identity",
        "geometry",
        "pixel_bounds",
        "crop_policy",
        "output_encoding",
        "content_type",
        "decoder_version",
        "transform_version",
        "image_sha256",
        "unusable_reason",
        "exclusion_inputs",
        "exclusion_decisions",
        "exclusion_policy",
    }
    _strict(identity, expected, "crop cache identity")
    if identity["schema_version"] != VISIBLE_REGION_CROP_SCHEMA:
        raise DerivedViewError("crop cache identity has an unsupported schema")
    if identity["exclusion_policy"] != _exclusion_policy_mapping():
        raise DerivedViewError("crop cache identity has an unsupported exclusion policy")
    exclusion_inputs = identity["exclusion_inputs"]
    if not isinstance(exclusion_inputs, list):
        raise DerivedViewError("crop cache exclusion_inputs must be a list")
    exclusion_decisions = identity["exclusion_decisions"]
    if not isinstance(exclusion_decisions, list) or any(
        not isinstance(item, Mapping) for item in exclusion_decisions
    ):
        raise DerivedViewError("crop cache exclusion_decisions must be a list of objects")
    result = ResolvedCrop(
        status=identity["status"],
        frame_identity=_require_mapping(identity["frame_identity"], "crop frame identity"),
        geometry=parse_geometry(identity["geometry"]),
        pixel_bounds=(
            None
            if identity["pixel_bounds"] is None
            else PixelBounds.from_mapping(identity["pixel_bounds"])
        ),
        crop_policy=identity["crop_policy"],
        output_encoding=identity["output_encoding"],
        decoder_version=identity["decoder_version"],
        transform_version=identity["transform_version"],
        image_bytes=None if identity["status"] == "unusable" else entry.content,
        unusable_reason=identity["unusable_reason"],
        exclusion_inputs=tuple(
            VisibleRegionExclusionInput.from_mapping(item) for item in exclusion_inputs
        ),
        exclusion_decisions=tuple(dict(item) for item in exclusion_decisions),
    )
    if (
        identity["content_type"] != result.content_type
        or identity["image_sha256"] != result.image_sha256
    ):
        raise DerivedViewError("crop cache identity does not match its bytes")
    return result


__all__ = [
    "DEFAULT_DECODER_VERSION",
    "DEFAULT_FRAME_TRANSFORM_VERSION",
    "DEFAULT_TRANSFORM_VERSION",
    "DERIVED_VIEW_CACHE_SCHEMA",
    "DetectorBoxGeometry",
    "DerivedViewCache",
    "DerivedViewCacheEntry",
    "DerivedViewCacheError",
    "DerivedViewError",
    "DerivedViewMissingFrameError",
    "DerivedViewProbeError",
    "DerivedViewSourceError",
    "EXACT_EVENT_SCHEMA",
    "ExactEventRequest",
    "FFMPEG_TOOLCHAIN_VERSION",
    "FFmpegFrameResolver",
    "FrameResolver",
    "OpenCVFrameResolver",
    "PILLOW_TOOLCHAIN_VERSION",
    "PixelBounds",
    "ResolvedCrop",
    "ResolvedFrame",
    "PredictedVisibleRegionGeometry",
    "ReviewedVisibleRegionGeometry",
    "SUPPORTED_CORRUPTION_FAMILIES",
    "SUPPORTED_CROP_ENCODINGS",
    "SUPPORTED_CROP_POLICIES",
    "VISIBLE_REGION_CROP_SCHEMA",
    "VisibleRegionCorruption",
    "VisibleRegionExclusionInput",
    "VisibleRegionCropRequest",
    "crop_cache_key",
    "frame_cache_key",
    "generate_visible_region_corruption",
    "parse_geometry",
    "resolve_exact_event",
    "resolve_visible_region_crop",
]
