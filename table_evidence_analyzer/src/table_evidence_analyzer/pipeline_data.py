"""Strict content contracts for recording-pipeline vision results."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .cards import CARD_IDENTITIES
from .table_observation import TableObservation, parse_observation_bytes

VISIBLE_CARD_DATA_SCHEMA_VERSION = "visible-card-data/v1"
VISUAL_IDENTITY_DATA_SCHEMA_VERSION = "visual-identity-data/v1"
TABLE_OBSERVATION_DATA_SCHEMA_VERSION = "table-observation-data/v1"
EXACT_EVENT_FRAME_SCHEMA_VERSION = "exact-event/v1"
DETECTOR_BOX_GEOMETRY_KIND = "detector-box/v1"
PREDICTED_VISIBLE_REGION_GEOMETRY_KIND = "visible-region/v1"
VISIBLE_CARD_SIDES = frozenset({"face_up", "face_down", "unknown"})

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_QUALIFIED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CARD_IDENTITIES = frozenset(CARD_IDENTITIES)


class PipelineDataError(ValueError):
    """Raised when a vision pipeline content payload is invalid."""


def canonical_json_bytes(value: Any) -> bytes:
    _validate_json(value, "value")
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    if not isinstance(value, bytes):
        raise TypeError("digest input must be bytes")
    return hashlib.sha256(value).hexdigest()


def _validate_json(value: Any, field: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PipelineDataError(f"{field} must contain finite JSON values")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise PipelineDataError(f"{field} object keys must be strings")
            _validate_json(child, f"{field}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json(child, f"{field}[{index}]")
        return
    raise PipelineDataError(f"{field} must contain JSON-compatible values")


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise PipelineDataError(f"{field} must be an object")
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
        raise PipelineDataError(f"{field} has invalid fields ({'; '.join(details)})")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PipelineDataError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or _IDENTIFIER.fullmatch(result) is None:
        raise PipelineDataError(f"{field} must be a safe identifier")
    return result


def _digest(value: Any, field: str) -> str:
    result = _text(value, field)
    if _DIGEST.fullmatch(result) is None:
        raise PipelineDataError(f"{field} must be a lower-case SHA-256 digest")
    return result


def _optional_digest(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _digest(value, field)


def _qualified(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or _QUALIFIED.fullmatch(result) is None:
        raise PipelineDataError(f"{field} must be a qualified identifier")
    return result


def _card_identity(value: Any, field: str) -> str:
    result = _text(value, field)
    if result not in _CARD_IDENTITIES:
        raise PipelineDataError(f"{field} is not in the canonical visual card set")
    return result


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PipelineDataError(f"{field} must be a non-negative integer")
    return value


def _positive_int(value: Any, field: str) -> int:
    result = _non_negative_int(value, field)
    if result == 0:
        raise PipelineDataError(f"{field} must be a positive integer")
    return result


def _coordinate(value: Any, field: str) -> int:
    result = _non_negative_int(value, field)
    if result > 1000:
        raise PipelineDataError(f"{field} must be from 0 through 1000")
    return result


def _finite_number(value: Any, field: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PipelineDataError(f"{field} must be a finite number")
    if not math.isfinite(float(value)):
        raise PipelineDataError(f"{field} must be a finite number")
    return value


@dataclass(frozen=True, slots=True)
class VisibleCardModelScore:
    """One optional score attributed to a detector or model producer."""

    producer_id: str
    score: int | float

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> "VisibleCardModelScore":
        data = _mapping(raw, context)
        _strict(data, {"producer_id", "score"}, context)
        return cls(
            producer_id=_identifier(data["producer_id"], f"{context}.producer_id"),
            score=_finite_number(data["score"], f"{context}.score"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {"producer_id": self.producer_id, "score": self.score}


@dataclass(frozen=True, slots=True)
class DetectorBoxGeometry:
    """A detector box, kept distinct from a reviewed visible region."""

    x_min: int
    y_min: int
    x_max: int
    y_max: int

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "geometry"
    ) -> "DetectorBoxGeometry":
        data = _mapping(raw, context)
        _strict(data, {"kind", "box_2d"}, context)
        if data["kind"] != DETECTOR_BOX_GEOMETRY_KIND:
            raise PipelineDataError(f"{context}.kind is unsupported")
        box = _mapping(data["box_2d"], f"{context}.box_2d")
        _strict(box, {"x_min", "y_min", "x_max", "y_max"}, f"{context}.box_2d")
        x_min = _coordinate(box["x_min"], f"{context}.box_2d.x_min")
        y_min = _coordinate(box["y_min"], f"{context}.box_2d.y_min")
        x_max = _coordinate(box["x_max"], f"{context}.box_2d.x_max")
        y_max = _coordinate(box["y_max"], f"{context}.box_2d.y_max")
        if x_min >= x_max or y_min >= y_max:
            raise PipelineDataError(f"{context}.box_2d must have positive dimensions")
        return cls(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "kind": DETECTOR_BOX_GEOMETRY_KIND,
            "box_2d": {
                "x_min": self.x_min,
                "y_min": self.y_min,
                "x_max": self.x_max,
                "y_max": self.y_max,
            },
        }


@dataclass(frozen=True, slots=True)
class PredictedVisibleRegionGeometry:
    """One or more detector-produced polygons containing visible card pixels."""

    polygons: tuple[tuple[tuple[int, int], ...], ...]

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "geometry"
    ) -> "PredictedVisibleRegionGeometry":
        data = _mapping(raw, context)
        _strict(data, {"kind", "visible_region"}, context)
        if data["kind"] != PREDICTED_VISIBLE_REGION_GEOMETRY_KIND:
            raise PipelineDataError(f"{context}.kind is unsupported")
        region = _mapping(data["visible_region"], f"{context}.visible_region")
        _strict(region, {"polygons"}, f"{context}.visible_region")
        raw_polygons = region["polygons"]
        if not isinstance(raw_polygons, list) or not raw_polygons:
            raise PipelineDataError(f"{context}.visible_region.polygons must be non-empty")
        polygons: list[tuple[tuple[int, int], ...]] = []
        for polygon_index, raw_polygon in enumerate(raw_polygons):
            if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
                raise PipelineDataError(
                    f"{context}.visible_region.polygons[{polygon_index}] needs three points"
                )
            points: list[tuple[int, int]] = []
            for point_index, raw_point in enumerate(raw_polygon):
                point = _mapping(
                    raw_point,
                    f"{context}.visible_region.polygons[{polygon_index}][{point_index}]",
                )
                _strict(
                    point,
                    {"x", "y"},
                    f"{context}.visible_region.polygons[{polygon_index}][{point_index}]",
                )
                points.append(
                    (
                        _coordinate(
                            point["x"],
                            f"{context}.visible_region.polygons[{polygon_index}][{point_index}].x",
                        ),
                        _coordinate(
                            point["y"],
                            f"{context}.visible_region.polygons[{polygon_index}][{point_index}].y",
                        ),
                    )
                )
            area = sum(
                points[index][0] * points[(index + 1) % len(points)][1]
                - points[(index + 1) % len(points)][0] * points[index][1]
                for index in range(len(points))
            )
            if area == 0:
                raise PipelineDataError(
                    f"{context}.visible_region.polygons[{polygon_index}] must have positive area"
                )
            polygons.append(tuple(points))
        return cls(polygons=tuple(polygons))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "kind": PREDICTED_VISIBLE_REGION_GEOMETRY_KIND,
            "visible_region": {
                "polygons": [
                    [{"x": point[0], "y": point[1]} for point in polygon]
                    for polygon in self.polygons
                ]
            },
        }


@dataclass(frozen=True, slots=True)
class ReviewedVisibleRegionGeometry:
    """One or more reviewed polygons containing visible card pixels."""

    polygons: tuple[tuple[tuple[int, int], ...], ...]

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "geometry"
    ) -> "ReviewedVisibleRegionGeometry":
        data = _mapping(raw, context)
        _strict(data, {"kind", "visible_region"}, context)
        if data["kind"] != "reviewed-visible-region/v1":
            raise PipelineDataError(f"{context}.kind is unsupported")
        region = _mapping(data["visible_region"], f"{context}.visible_region")
        _strict(region, {"polygons"}, f"{context}.visible_region")
        raw_polygons = region["polygons"]
        if not isinstance(raw_polygons, list) or not raw_polygons:
            raise PipelineDataError(f"{context}.visible_region.polygons must be non-empty")
        polygons: list[tuple[tuple[int, int], ...]] = []
        for polygon_index, raw_polygon in enumerate(raw_polygons):
            if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
                raise PipelineDataError(
                    f"{context}.visible_region.polygons[{polygon_index}] needs three points"
                )
            points: list[tuple[int, int]] = []
            for point_index, raw_point in enumerate(raw_polygon):
                point = _mapping(
                    raw_point,
                    f"{context}.visible_region.polygons[{polygon_index}][{point_index}]",
                )
                _strict(
                    point,
                    {"x", "y"},
                    f"{context}.visible_region.polygons[{polygon_index}][{point_index}]",
                )
                points.append(
                    (
                        _coordinate(
                            point["x"],
                            f"{context}.visible_region.polygons[{polygon_index}][{point_index}].x",
                        ),
                        _coordinate(
                            point["y"],
                            f"{context}.visible_region.polygons[{polygon_index}][{point_index}].y",
                        ),
                    )
                )
            area = sum(
                points[index][0] * points[(index + 1) % len(points)][1]
                - points[(index + 1) % len(points)][0] * points[index][1]
                for index in range(len(points))
            )
            if area == 0:
                raise PipelineDataError(
                    f"{context}.visible_region.polygons[{polygon_index}] must have positive area"
                )
            polygons.append(tuple(points))
        return cls(polygons=tuple(polygons))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "kind": "reviewed-visible-region/v1",
            "visible_region": {
                "polygons": [
                    [{"x": point[0], "y": point[1]} for point in polygon]
                    for polygon in self.polygons
                ]
            },
        }


PipelineGeometry = (
    DetectorBoxGeometry | PredictedVisibleRegionGeometry | ReviewedVisibleRegionGeometry
)


def parse_pipeline_geometry(raw: Mapping[str, Any], context: str = "geometry") -> PipelineGeometry:
    """Parse detector or reviewed geometry used by pipeline content."""

    data = _mapping(raw, context)
    kind = data.get("kind")
    if kind == DETECTOR_BOX_GEOMETRY_KIND:
        return DetectorBoxGeometry.from_mapping(data, context)
    if kind == PREDICTED_VISIBLE_REGION_GEOMETRY_KIND:
        return PredictedVisibleRegionGeometry.from_mapping(data, context)
    if kind == "reviewed-visible-region/v1":
        return ReviewedVisibleRegionGeometry.from_mapping(data, context)
    raise PipelineDataError(f"{context}.kind is unsupported")


@dataclass(frozen=True, slots=True)
class VisibleCardFrameIdentity:
    """The exact source-frame identity used for one detector outcome."""

    source_video_sha256: str
    requested_time_us: int
    frame_index: int
    presentation_timestamp_us: int
    width: int
    height: int
    decoder_version: str
    transform_version: str
    output_encoding: str
    content_type: str
    image_sha256: str
    policy: str = EXACT_EVENT_FRAME_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "VisibleCardFrameIdentity":
        data = _mapping(raw, "frame_identity")
        _strict(
            data,
            {
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
            },
            "frame_identity",
        )
        if data["schema_version"] != EXACT_EVENT_FRAME_SCHEMA_VERSION:
            raise PipelineDataError("frame_identity has an unsupported schema")
        if data["policy"] != EXACT_EVENT_FRAME_SCHEMA_VERSION:
            raise PipelineDataError("frame_identity policy is unsupported")
        return cls(
            source_video_sha256=_digest(
                data["source_video_sha256"], "frame_identity.source_video_sha256"
            ),
            requested_time_us=_non_negative_int(
                data["requested_time_us"], "frame_identity.requested_time_us"
            ),
            frame_index=_non_negative_int(data["frame_index"], "frame_identity.frame_index"),
            presentation_timestamp_us=_non_negative_int(
                data["presentation_timestamp_us"],
                "frame_identity.presentation_timestamp_us",
            ),
            width=_positive_int(data["width"], "frame_identity.width"),
            height=_positive_int(data["height"], "frame_identity.height"),
            decoder_version=_text(data["decoder_version"], "frame_identity.decoder_version"),
            transform_version=_text(data["transform_version"], "frame_identity.transform_version"),
            output_encoding=_text(data["output_encoding"], "frame_identity.output_encoding"),
            content_type=_text(data["content_type"], "frame_identity.content_type"),
            image_sha256=_digest(data["image_sha256"], "frame_identity.image_sha256"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": EXACT_EVENT_FRAME_SCHEMA_VERSION,
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
class VisibleCardCandidate:
    """One run-local detector candidate."""

    card_id: str
    geometry: PipelineGeometry
    normalization: dict[str, Any]
    side: Literal["face_up", "face_down", "unknown"]
    model_scores: tuple[VisibleCardModelScore, ...] | None = None

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "candidate"
    ) -> "VisibleCardCandidate":
        data = _mapping(raw, context)
        expected = {"card_id", "geometry", "normalization", "side", "model_scores"}
        _strict(data, expected if "model_scores" in data else expected - {"model_scores"}, context)
        normalization = _mapping(data["normalization"], f"{context}.normalization")
        _strict(normalization, {"width", "height", "policy_id"}, f"{context}.normalization")
        normalized = {
            "width": _positive_int(normalization["width"], f"{context}.normalization.width"),
            "height": _positive_int(normalization["height"], f"{context}.normalization.height"),
            "policy_id": _qualified(
                normalization["policy_id"], f"{context}.normalization.policy_id"
            ),
        }
        side = data["side"]
        if side not in VISIBLE_CARD_SIDES:
            raise PipelineDataError(f"{context}.side must be face_up, face_down, or unknown")
        raw_scores = data.get("model_scores")
        scores: tuple[VisibleCardModelScore, ...] | None = None
        if raw_scores is not None:
            if not isinstance(raw_scores, list):
                raise PipelineDataError(f"{context}.model_scores must be a list")
            parsed = tuple(
                VisibleCardModelScore.from_mapping(item, f"{context}.model_scores[{index}]")
                for index, item in enumerate(raw_scores)
            )
            if len({item.producer_id for item in parsed}) != len(parsed):
                raise PipelineDataError(f"{context}.model_scores must have unique producers")
            scores = parsed
        return cls(
            card_id=_identifier(data["card_id"], f"{context}.card_id"),
            geometry=parse_pipeline_geometry(
                _mapping(data["geometry"], f"{context}.geometry"), f"{context}.geometry"
            ),
            normalization=normalized,
            side=side,
            model_scores=scores,
        )

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "card_id": self.card_id,
            "geometry": self.geometry.to_mapping(),
            "normalization": self.normalization,
            "side": self.side,
        }
        if self.model_scores is not None:
            value["model_scores"] = [score.to_mapping() for score in self.model_scores]
        return value


@dataclass(frozen=True, slots=True)
class VisualIdentityClassifierIdentity:
    """The frozen classifier provider and model lineage for one outcome."""

    provider: str
    implementation_name: str
    implementation_version: str
    model_name: str
    model_version: str

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "classifier"
    ) -> "VisualIdentityClassifierIdentity":
        data = _mapping(raw, context)
        _strict(data, {"provider", "implementation", "model"}, context)
        implementation = _mapping(data["implementation"], f"{context}.implementation")
        _strict(implementation, {"name", "version"}, f"{context}.implementation")
        model = _mapping(data["model"], f"{context}.model")
        _strict(model, {"name", "version"}, f"{context}.model")
        return cls(
            provider=_qualified(data["provider"], f"{context}.provider"),
            implementation_name=_qualified(
                implementation["name"], f"{context}.implementation.name"
            ),
            implementation_version=_text(
                implementation["version"], f"{context}.implementation.version"
            ),
            model_name=_text(model["name"], f"{context}.model.name"),
            model_version=_text(model["version"], f"{context}.model.version"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "implementation": {
                "name": self.implementation_name,
                "version": self.implementation_version,
            },
            "model": {"name": self.model_name, "version": self.model_version},
        }


@dataclass(frozen=True, slots=True)
class VisualIdentityCropIdentity:
    """The verified M2 crop identity used by one classifier request."""

    status: Literal["usable", "unusable"]
    frame_identity: VisibleCardFrameIdentity
    geometry: PipelineGeometry
    pixel_bounds: dict[str, int] | None
    crop_policy: str
    output_encoding: str
    content_type: str
    decoder_version: str
    transform_version: str
    image_sha256: str | None
    unusable_reason: str | None

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "crop_identity"
    ) -> "VisualIdentityCropIdentity":
        data = _mapping(raw, context)
        _strict(
            data,
            {
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
            },
            context,
        )
        if data["schema_version"] != "visible-region-crop/v1":
            raise PipelineDataError(f"{context}.schema_version is unsupported")
        status = data["status"]
        if status not in {"usable", "unusable"}:
            raise PipelineDataError(f"{context}.status is unsupported")
        frame = VisibleCardFrameIdentity.from_mapping(
            _mapping(data["frame_identity"], f"{context}.frame_identity")
        )
        geometry = parse_pipeline_geometry(
            _mapping(data["geometry"], f"{context}.geometry"), f"{context}.geometry"
        )
        raw_bounds = data["pixel_bounds"]
        bounds: dict[str, int] | None
        if raw_bounds is None:
            bounds = None
        else:
            bound_data = _mapping(raw_bounds, f"{context}.pixel_bounds")
            _strict(
                bound_data,
                {"x_min", "y_min", "x_max", "y_max"},
                f"{context}.pixel_bounds",
            )
            bounds = {
                key: _non_negative_int(bound_data[key], f"{context}.pixel_bounds.{key}")
                for key in ("x_min", "y_min", "x_max", "y_max")
            }
            if bounds["x_min"] >= bounds["x_max"] or bounds["y_min"] >= bounds["y_max"]:
                raise PipelineDataError(f"{context}.pixel_bounds must have positive dimensions")
        image_sha256 = _optional_digest(data["image_sha256"], f"{context}.image_sha256")
        reason = data["unusable_reason"]
        if reason is not None:
            reason = _text(reason, f"{context}.unusable_reason")
        if status == "usable" and (bounds is None or image_sha256 is None or reason is not None):
            raise PipelineDataError(f"{context}.usable crop identity is incomplete")
        if status == "unusable" and (image_sha256 is not None or reason is None):
            raise PipelineDataError(f"{context}.unusable crop identity is incomplete")
        return cls(
            status=status,
            frame_identity=frame,
            geometry=geometry,
            pixel_bounds=bounds,
            crop_policy=_qualified(data["crop_policy"], f"{context}.crop_policy"),
            output_encoding=_text(data["output_encoding"], f"{context}.output_encoding"),
            content_type=_text(data["content_type"], f"{context}.content_type"),
            decoder_version=_text(data["decoder_version"], f"{context}.decoder_version"),
            transform_version=_text(data["transform_version"], f"{context}.transform_version"),
            image_sha256=image_sha256,
            unusable_reason=reason,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": "visible-region-crop/v1",
            "status": self.status,
            "frame_identity": self.frame_identity.to_mapping(),
            "geometry": self.geometry.to_mapping(),
            "pixel_bounds": self.pixel_bounds,
            "crop_policy": self.crop_policy,
            "output_encoding": self.output_encoding,
            "content_type": self.content_type,
            "decoder_version": self.decoder_version,
            "transform_version": self.transform_version,
            "image_sha256": self.image_sha256,
            "unusable_reason": self.unusable_reason,
        }


@dataclass(frozen=True, slots=True)
class VisualIdentityCandidate:
    """One ordered canonical visual card identity candidate."""

    identity: str
    score: int | float | None
    score_meaning: str | None
    producer_id: str

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "candidate"
    ) -> "VisualIdentityCandidate":
        data = _mapping(raw, context)
        optional = {key for key in ("score", "score_meaning") if key in data}
        _strict(data, {"identity", "producer_id", *optional}, context)
        score = data.get("score")
        if score is not None:
            score = _finite_number(score, f"{context}.score")
        meaning = data.get("score_meaning")
        if meaning is not None:
            meaning = _text(meaning, f"{context}.score_meaning")
        if (score is None) != (meaning is None):
            raise PipelineDataError(f"{context}.score and score_meaning must be paired")
        return cls(
            identity=_card_identity(data["identity"], f"{context}.identity"),
            score=score,
            score_meaning=meaning,
            producer_id=_identifier(data["producer_id"], f"{context}.producer_id"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "score": self.score,
            "score_meaning": self.score_meaning,
            "producer_id": self.producer_id,
        }


@dataclass(frozen=True, slots=True)
class VisualIdentityOutcome:
    """The durable classifier result for one visible-card candidate."""

    card_id: str
    frame_identity: VisibleCardFrameIdentity
    geometry: PipelineGeometry
    crop_identity: VisualIdentityCropIdentity | None
    classifier: VisualIdentityClassifierIdentity
    status: Literal["classified", "unusable", "failed"]
    candidates: tuple[VisualIdentityCandidate, ...]
    unusable_reason: str | None = None
    error: str | None = None

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "outcome"
    ) -> "VisualIdentityOutcome":
        data = _mapping(raw, context)
        _strict(
            data,
            {
                "card_id",
                "frame_identity",
                "geometry",
                "crop_identity",
                "classifier",
                "status",
                "candidates",
                "unusable_reason",
                "error",
            },
            context,
        )
        status = data["status"]
        if status not in {"classified", "unusable", "failed"}:
            raise PipelineDataError(f"{context}.status is unsupported")
        frame = VisibleCardFrameIdentity.from_mapping(
            _mapping(data["frame_identity"], f"{context}.frame_identity")
        )
        geometry = parse_pipeline_geometry(
            _mapping(data["geometry"], f"{context}.geometry"), f"{context}.geometry"
        )
        crop = (
            None
            if data["crop_identity"] is None
            else VisualIdentityCropIdentity.from_mapping(
                _mapping(data["crop_identity"], f"{context}.crop_identity")
            )
        )
        if crop is not None and (
            crop.frame_identity.to_mapping() != frame.to_mapping()
            or crop.geometry.to_mapping() != geometry.to_mapping()
        ):
            raise PipelineDataError(f"{context}.crop_identity does not match frame or geometry")
        raw_candidates = data["candidates"]
        if not isinstance(raw_candidates, list):
            raise PipelineDataError(f"{context}.candidates must be a list")
        candidates = tuple(
            VisualIdentityCandidate.from_mapping(item, f"{context}.candidates[{index}]")
            for index, item in enumerate(raw_candidates)
        )
        if len({item.identity for item in candidates}) != len(candidates):
            raise PipelineDataError(f"{context}.candidates must have unique identities")
        unusable_reason = data["unusable_reason"]
        if unusable_reason is not None:
            unusable_reason = _text(unusable_reason, f"{context}.unusable_reason")
        error = data["error"]
        if error is not None:
            error = _text(error, f"{context}.error")
        if status == "classified" and (
            not candidates or unusable_reason is not None or error is not None
        ):
            raise PipelineDataError(f"{context}.classified outcome has a failure reason")
        if status in {"classified", "unusable"} and crop is None:
            raise PipelineDataError(f"{context}.{status} outcome needs a crop identity")
        if status == "unusable" and (candidates or unusable_reason is None or error is not None):
            raise PipelineDataError(f"{context}.unusable outcome is invalid")
        if status == "failed" and (candidates or error is None or unusable_reason is not None):
            raise PipelineDataError(f"{context}.failed outcome is invalid")
        return cls(
            card_id=_identifier(data["card_id"], f"{context}.card_id"),
            frame_identity=frame,
            geometry=geometry,
            crop_identity=crop,
            classifier=VisualIdentityClassifierIdentity.from_mapping(
                _mapping(data["classifier"], f"{context}.classifier")
            ),
            status=status,
            candidates=candidates,
            unusable_reason=unusable_reason,
            error=error,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "frame_identity": self.frame_identity.to_mapping(),
            "geometry": self.geometry.to_mapping(),
            "crop_identity": None
            if self.crop_identity is None
            else self.crop_identity.to_mapping(),
            "classifier": self.classifier.to_mapping(),
            "status": self.status,
            "candidates": [candidate.to_mapping() for candidate in self.candidates],
            "unusable_reason": self.unusable_reason,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class VisualIdentityData:
    """The concrete visual card identity classifier content payload."""

    outcomes: tuple[VisualIdentityOutcome, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "VisualIdentityData":
        data = _mapping(raw, "visual-identity data")
        _strict(data, {"schema_version", "outcomes"}, "visual-identity data")
        if data["schema_version"] != VISUAL_IDENTITY_DATA_SCHEMA_VERSION:
            raise PipelineDataError("visual-identity data has an unsupported schema")
        raw_outcomes = data["outcomes"]
        if not isinstance(raw_outcomes, list):
            raise PipelineDataError("visual-identity data.outcomes must be a list")
        outcomes = tuple(
            VisualIdentityOutcome.from_mapping(item, f"outcomes[{index}]")
            for index, item in enumerate(raw_outcomes)
        )
        if len({item.card_id for item in outcomes}) != len(outcomes):
            raise PipelineDataError("visual-identity outcome card IDs must be unique")
        return cls(outcomes=outcomes)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": VISUAL_IDENTITY_DATA_SCHEMA_VERSION,
            "outcomes": [outcome.to_mapping() for outcome in self.outcomes],
        }


@dataclass(frozen=True, slots=True)
class TableObservationData:
    """The ordered table observations produced by one assembly run."""

    observations: tuple[TableObservation, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TableObservationData":
        data = _mapping(raw, "table-observation data")
        _strict(data, {"schema_version", "observations"}, "table-observation data")
        if data["schema_version"] != TABLE_OBSERVATION_DATA_SCHEMA_VERSION:
            raise PipelineDataError("table-observation data has an unsupported schema")
        raw_observations = data["observations"]
        if not isinstance(raw_observations, list):
            raise PipelineDataError("table-observation data.observations must be a list")
        observations: list[TableObservation] = []
        for index, item in enumerate(raw_observations):
            try:
                observations.append(
                    parse_observation_bytes(
                        canonical_json_bytes(_mapping(item, f"observations[{index}]"))
                    )
                )
            except (TypeError, ValueError) as error:
                raise PipelineDataError(f"observations[{index}] is invalid") from error
        identifiers = [observation.observation_id for observation in observations]
        if len(identifiers) != len(set(identifiers)):
            raise PipelineDataError("table-observation data IDs must be unique")
        times = [observation.observed_at_ms for observation in observations]
        if times != sorted(times):
            raise PipelineDataError("table-observation data must be ordered by observed_at_ms")
        return cls(observations=tuple(observations))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": TABLE_OBSERVATION_DATA_SCHEMA_VERSION,
            "observations": [
                observation.model_dump(mode="json", exclude_none=True)
                for observation in self.observations
            ],
        }


@dataclass(frozen=True, slots=True)
class VisibleCardOutcome:
    """The durable result for one requested event."""

    event_id: str
    frame_identity: VisibleCardFrameIdentity | None
    status: Literal["detected", "empty", "failed"]
    candidates: tuple[VisibleCardCandidate, ...]
    error: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "outcome") -> "VisibleCardOutcome":
        data = _mapping(raw, context)
        _strict(data, {"event_id", "frame_identity", "status", "candidates", "error"}, context)
        status = data["status"]
        if status not in {"detected", "empty", "failed"}:
            raise PipelineDataError(f"{context}.status is unsupported")
        raw_candidates = data["candidates"]
        if not isinstance(raw_candidates, list):
            raise PipelineDataError(f"{context}.candidates must be a list")
        candidates = tuple(
            VisibleCardCandidate.from_mapping(item, f"{context}.candidates[{index}]")
            for index, item in enumerate(raw_candidates)
        )
        if len({item.card_id for item in candidates}) != len(candidates):
            raise PipelineDataError(f"{context}.candidates must have unique card IDs")
        frame = (
            None
            if data["frame_identity"] is None
            else VisibleCardFrameIdentity.from_mapping(
                _mapping(data["frame_identity"], f"{context}.frame_identity")
            )
        )
        error = data["error"]
        if error is not None:
            error = _text(error, f"{context}.error")
        if status == "detected" and not candidates:
            raise PipelineDataError(f"{context}.detected outcome needs candidates")
        if status == "empty" and (candidates or error is not None):
            raise PipelineDataError(f"{context}.empty outcome must have no candidates or error")
        if status == "failed" and (candidates or error is None):
            raise PipelineDataError(f"{context}.failed outcome needs an error and no candidates")
        if status in {"detected", "empty"} and frame is None:
            raise PipelineDataError(f"{context}.{status} outcome needs a frame identity")
        return cls(
            event_id=_identifier(data["event_id"], f"{context}.event_id"),
            frame_identity=frame,
            status=status,
            candidates=candidates,
            error=error,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "frame_identity": None
            if self.frame_identity is None
            else self.frame_identity.to_mapping(),
            "status": self.status,
            "candidates": [candidate.to_mapping() for candidate in self.candidates],
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class VisibleCardData:
    """The concrete visible-card detector content payload."""

    outcomes: tuple[VisibleCardOutcome, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "VisibleCardData":
        data = _mapping(raw, "visible-card data")
        _strict(data, {"schema_version", "outcomes"}, "visible-card data")
        if data["schema_version"] != VISIBLE_CARD_DATA_SCHEMA_VERSION:
            raise PipelineDataError("visible-card data has an unsupported schema")
        raw_outcomes = data["outcomes"]
        if not isinstance(raw_outcomes, list):
            raise PipelineDataError("visible-card data.outcomes must be a list")
        outcomes = tuple(
            VisibleCardOutcome.from_mapping(item, f"outcomes[{index}]")
            for index, item in enumerate(raw_outcomes)
        )
        if len({item.event_id for item in outcomes}) != len(outcomes):
            raise PipelineDataError("visible-card outcome event IDs must be unique")
        return cls(outcomes=outcomes)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": VISIBLE_CARD_DATA_SCHEMA_VERSION,
            "outcomes": [outcome.to_mapping() for outcome in self.outcomes],
        }


def parse_visible_card_data_bytes(raw: bytes) -> VisibleCardData:
    if not isinstance(raw, bytes):
        raise TypeError("visible-card data must be bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                PipelineDataError(f"visible-card data contains a non-finite JSON number: {value}")
            ),
        )
    except PipelineDataError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineDataError("visible-card data must be valid UTF-8 JSON") from error
    return VisibleCardData.from_mapping(_mapping(value, "visible-card data"))


def parse_visual_identity_data_bytes(raw: bytes) -> VisualIdentityData:
    if not isinstance(raw, bytes):
        raise TypeError("visual-identity data must be bytes")

    def reject_constant(value: str) -> None:
        raise PipelineDataError(f"visual-identity data contains a non-finite JSON number: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PipelineDataError(f"visual-identity data contains a duplicate field: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except PipelineDataError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineDataError("visual-identity data must be valid UTF-8 JSON") from error
    return VisualIdentityData.from_mapping(_mapping(value, "visual-identity data"))


def parse_table_observation_data_bytes(raw: bytes) -> TableObservationData:
    if not isinstance(raw, bytes):
        raise TypeError("table-observation data must be bytes")

    def reject_constant(value: str) -> None:
        raise PipelineDataError(
            f"table-observation data contains a non-finite JSON number: {value}"
        )

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PipelineDataError(f"table-observation data contains a duplicate field: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except PipelineDataError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineDataError("table-observation data must be valid UTF-8 JSON") from error
    return TableObservationData.from_mapping(_mapping(value, "table-observation data"))


def canonical_visible_card_data_bytes(value: VisibleCardData | Mapping[str, Any]) -> bytes:
    data = value if isinstance(value, VisibleCardData) else VisibleCardData.from_mapping(value)
    return canonical_json_bytes(data.to_mapping())


def canonical_visual_identity_data_bytes(
    value: VisualIdentityData | Mapping[str, Any],
) -> bytes:
    data = (
        value if isinstance(value, VisualIdentityData) else VisualIdentityData.from_mapping(value)
    )
    return canonical_json_bytes(data.to_mapping())


def canonical_table_observation_data_bytes(
    value: TableObservationData | Mapping[str, Any],
) -> bytes:
    data = (
        value
        if isinstance(value, TableObservationData)
        else TableObservationData.from_mapping(value)
    )
    return canonical_json_bytes(data.to_mapping())


__all__ = [
    "DETECTOR_BOX_GEOMETRY_KIND",
    "EXACT_EVENT_FRAME_SCHEMA_VERSION",
    "PREDICTED_VISIBLE_REGION_GEOMETRY_KIND",
    "PipelineDataError",
    "PipelineGeometry",
    "TABLE_OBSERVATION_DATA_SCHEMA_VERSION",
    "VISIBLE_CARD_DATA_SCHEMA_VERSION",
    "VISUAL_IDENTITY_DATA_SCHEMA_VERSION",
    "VisibleCardCandidate",
    "VISIBLE_CARD_SIDES",
    "VisibleCardData",
    "VisibleCardFrameIdentity",
    "VisibleCardModelScore",
    "VisibleCardOutcome",
    "PredictedVisibleRegionGeometry",
    "ReviewedVisibleRegionGeometry",
    "VisualIdentityCandidate",
    "VisualIdentityClassifierIdentity",
    "VisualIdentityCropIdentity",
    "VisualIdentityData",
    "VisualIdentityOutcome",
    "TableObservationData",
    "canonical_json_bytes",
    "canonical_table_observation_data_bytes",
    "canonical_visible_card_data_bytes",
    "canonical_visual_identity_data_bytes",
    "parse_pipeline_geometry",
    "parse_visible_card_data_bytes",
    "parse_visual_identity_data_bytes",
    "parse_table_observation_data_bytes",
    "sha256_bytes",
]
