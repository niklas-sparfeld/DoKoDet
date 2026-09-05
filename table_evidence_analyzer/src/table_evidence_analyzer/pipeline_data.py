"""Strict content contracts for recording-pipeline vision results."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

VISIBLE_CARD_DATA_SCHEMA_VERSION = "visible-card-data/v1"
EXACT_EVENT_FRAME_SCHEMA_VERSION = "exact-event/v1"
DETECTOR_BOX_GEOMETRY_KIND = "detector-box/v1"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_QUALIFIED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


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


def _qualified(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or _QUALIFIED.fullmatch(result) is None:
        raise PipelineDataError(f"{field} must be a qualified identifier")
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
    geometry: DetectorBoxGeometry
    normalization: dict[str, Any]
    model_scores: tuple[VisibleCardModelScore, ...] | None = None

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "candidate"
    ) -> "VisibleCardCandidate":
        data = _mapping(raw, context)
        expected = {"card_id", "geometry", "normalization", "model_scores"}
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
            geometry=DetectorBoxGeometry.from_mapping(
                _mapping(data["geometry"], f"{context}.geometry"), f"{context}.geometry"
            ),
            normalization=normalized,
            model_scores=scores,
        )

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "card_id": self.card_id,
            "geometry": self.geometry.to_mapping(),
            "normalization": self.normalization,
        }
        if self.model_scores is not None:
            value["model_scores"] = [score.to_mapping() for score in self.model_scores]
        return value


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
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(
            PipelineDataError(f"visible-card data contains a non-finite JSON number: {value}")
        ))
    except PipelineDataError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineDataError("visible-card data must be valid UTF-8 JSON") from error
    return VisibleCardData.from_mapping(_mapping(value, "visible-card data"))


def canonical_visible_card_data_bytes(value: VisibleCardData | Mapping[str, Any]) -> bytes:
    data = value if isinstance(value, VisibleCardData) else VisibleCardData.from_mapping(value)
    return canonical_json_bytes(data.to_mapping())


__all__ = [
    "DETECTOR_BOX_GEOMETRY_KIND",
    "EXACT_EVENT_FRAME_SCHEMA_VERSION",
    "PipelineDataError",
    "VISIBLE_CARD_DATA_SCHEMA_VERSION",
    "VisibleCardCandidate",
    "VisibleCardData",
    "VisibleCardFrameIdentity",
    "VisibleCardModelScore",
    "VisibleCardOutcome",
    "canonical_json_bytes",
    "canonical_visible_card_data_bytes",
    "parse_visible_card_data_bytes",
    "sha256_bytes",
]
