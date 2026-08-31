"""Visible-card proposals for the first TableEvidenceAnalyzer capability baseline.

The provider output is evidence, not a reviewed event, annotation, or table observation.  The
module keeps the cloud boundary small so a deterministic fake provider can exercise the same cache,
artifact, overlay, and review paths as Gemini.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import html
import importlib.metadata
import json
import math
import mimetypes
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from PIL import Image, UnidentifiedImageError

DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_MAX_RETRIES = 2
INPUT_PRICE_PER_MILLION = 0.75
OUTPUT_PRICE_PER_MILLION = 3.75

REQUEST_SCHEMA_VERSION = "visible-card-request/v1"
PREDICTION_SCHEMA_VERSION = "visible-card-prediction/v1"
CACHE_SCHEMA_VERSION = "visible-card-cache/v1"
RUN_SCHEMA_VERSION = "visible-card-run/v1"
REVIEW_QUEUE_SCHEMA_VERSION = "visible-card-review-queue/v1"
GEMINI_API_VERSION = "v1beta"
GEMINI_PROVIDER_NAME = "gemini"
GEMINI_THINKING_LEVEL = "minimal"
LOCAL_PROVIDER_NAME = "local"
LOCAL_PROVIDER_VERSION = "local-visible-cards-v1"
LOCAL_DEVICE_NAMES = frozenset({"cpu", "mps"})
LOCAL_INPUT_SIZE = 704
LOCAL_CONFIDENCE_THRESHOLD = 0.5
LOCAL_RFDETR_VERSION = "1.9.4"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SIDES = frozenset({"face_up", "face_down", "unknown"})

PROMPT = """Find every visible physical playing card in this image.

Include both face-up and face-down cards. Include cards that overlap, cards in a pile, and cards
that are partly occluded when a visible card region can be separated. Return one instance for each
separately visible card. Exclude card-shaped packaging, printed pictures of cards, paper, keyboards,
and other non-card objects.

For each instance, trace only its visible boundary. Do not infer a hidden boundary behind another
card or object. Coordinates use the full source image. x is horizontal, y is vertical, and both are
integers normalized from 0 through 1000. Use the named x and y fields exactly as specified. List
polygon points around the visible boundary in order. Classify side as face_up, face_down, or
unknown. Use a short label that describes the card without inventing an unreadable identity.
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "box_2d": {
                        "type": "object",
                        "properties": {
                            "y_min": {"type": "integer"},
                            "x_min": {"type": "integer"},
                            "y_max": {"type": "integer"},
                            "x_max": {"type": "integer"},
                        },
                        "required": ["y_min", "x_min", "y_max", "x_max"],
                        "additionalProperties": False,
                    },
                    "polygon": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "integer"},
                                "y": {"type": "integer"},
                            },
                            "required": ["x", "y"],
                            "additionalProperties": False,
                        },
                        "minItems": 3,
                    },
                    "side": {
                        "type": "string",
                        "enum": ["face_up", "face_down", "unknown"],
                    },
                    "label": {"type": "string"},
                },
                "required": ["box_2d", "polygon", "side", "label"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cards"],
    "additionalProperties": False,
}


class VisibleCardError(RuntimeError):
    """Raised when a visible-card request or artifact is invalid."""


class VisibleCardValidationError(VisibleCardError, ValueError):
    """Raised when a provider response is not a valid visible-card prediction."""


class MissingCredentialError(VisibleCardError):
    """Raised when a cloud provider credential is not available at runtime."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or _IDENTIFIER.fullmatch(value) is None:
        raise VisibleCardError(f"{field} must be a simple non-empty identifier.")
    return value


def _require_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VisibleCardError(f"{field} must be a positive integer.")
    return value


def _require_non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VisibleCardError(f"{field} must be a non-negative integer.")
    return value


def _require_finite_non_negative(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VisibleCardError(f"{field} must be a finite non-negative number.")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise VisibleCardError(f"{field} must be a finite non-negative number.")
    return result


@dataclass(frozen=True, slots=True)
class NormalizedPoint:
    """One x/y point normalized to the full source frame."""

    x: int
    y: int

    def __post_init__(self) -> None:
        _validate_coordinate(self.x, "point x")
        _validate_coordinate(self.y, "point y")

    def to_mapping(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True, slots=True)
class NormalizedBox:
    """One positive normalized bounding box."""

    y_min: int
    x_min: int
    y_max: int
    x_max: int

    def __post_init__(self) -> None:
        for name, value in (
            ("box y_min", self.y_min),
            ("box x_min", self.x_min),
            ("box y_max", self.y_max),
            ("box x_max", self.x_max),
        ):
            _validate_coordinate(value, name)
        if self.y_min >= self.y_max or self.x_min >= self.x_max:
            raise VisibleCardValidationError("box must have positive width and height.")

    def to_mapping(self) -> dict[str, int]:
        return {
            "y_min": self.y_min,
            "x_min": self.x_min,
            "y_max": self.y_max,
            "x_max": self.x_max,
        }


def _validate_coordinate(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise VisibleCardValidationError(f"{field} must be a normalized integer coordinate.")


@dataclass(frozen=True, slots=True)
class VisibleCardProposal:
    """One anonymous visible-card polygon proposal."""

    box_2d: NormalizedBox
    polygon: tuple[NormalizedPoint, ...]
    side: Literal["face_up", "face_down", "unknown"]
    label: str

    def __post_init__(self) -> None:
        if len(self.polygon) < 3:
            raise VisibleCardValidationError("polygon needs at least three points.")
        if self.side not in _SIDES:
            raise VisibleCardValidationError("side must be face_up, face_down, or unknown.")
        if not isinstance(self.label, str) or not self.label.strip():
            raise VisibleCardValidationError("label must be a non-empty string.")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "box_2d": self.box_2d.to_mapping(),
            "polygon": [point.to_mapping() for point in self.polygon],
            "side": self.side,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class VisibleCardPrediction:
    """Strict, normalized visible-card provider output."""

    cards: tuple[VisibleCardProposal, ...]

    def to_mapping(self) -> dict[str, list[dict[str, Any]]]:
        return {"cards": [card.to_mapping() for card in self.cards]}


def normalize_prediction(value: Any) -> VisibleCardPrediction:
    """Validate and normalize the provider's closed JSON response shape."""

    if not isinstance(value, dict) or set(value) != {"cards"}:
        raise VisibleCardValidationError("prediction must be an object containing only cards.")
    cards = value["cards"]
    if not isinstance(cards, list):
        raise VisibleCardValidationError("prediction cards must be a list.")

    proposals: list[VisibleCardProposal] = []
    for index, card in enumerate(cards):
        context = f"card {index}"
        if not isinstance(card, dict) or set(card) != {"box_2d", "polygon", "side", "label"}:
            raise VisibleCardValidationError(f"{context} has an unexpected shape.")
        box_value = card["box_2d"]
        expected_box = {"y_min", "x_min", "y_max", "x_max"}
        if not isinstance(box_value, dict) or set(box_value) != expected_box:
            raise VisibleCardValidationError(f"{context} box_2d has an unexpected shape.")
        box = NormalizedBox(
            y_min=box_value["y_min"],
            x_min=box_value["x_min"],
            y_max=box_value["y_max"],
            x_max=box_value["x_max"],
        )
        polygon_value = card["polygon"]
        if not isinstance(polygon_value, list) or len(polygon_value) < 3:
            raise VisibleCardValidationError(f"{context} polygon needs at least three points.")
        points: list[NormalizedPoint] = []
        for point_index, point_value in enumerate(polygon_value):
            if not isinstance(point_value, dict) or set(point_value) != {"x", "y"}:
                raise VisibleCardValidationError(
                    f"{context} polygon point {point_index} has an unexpected shape."
                )
            points.append(NormalizedPoint(x=point_value["x"], y=point_value["y"]))
        proposals.append(
            VisibleCardProposal(
                box_2d=box,
                polygon=tuple(points),
                side=card["side"],
                label=card["label"],
            )
        )
    return VisibleCardPrediction(cards=tuple(proposals))


def validate_prediction(value: Any) -> dict[str, list[dict[str, Any]]]:
    """Return a canonical mapping after strict provider-response validation."""

    return normalize_prediction(value).to_mapping()


@dataclass(frozen=True, slots=True)
class VisibleCardRequest:
    """All inputs that define one visible-card provider request."""

    package_id: str
    frame_part_name: str
    target_offset_ms: int
    image_bytes: bytes
    width: int
    height: int
    model: str = DEFAULT_MODEL
    prompt: str = PROMPT
    response_schema: Mapping[str, Any] = field(default_factory=lambda: dict(RESPONSE_SCHEMA))
    image_mime_type: str = "image/jpeg"
    provider: str = GEMINI_PROVIDER_NAME
    api_version: str = GEMINI_API_VERSION
    thinking_level: str = GEMINI_THINKING_LEVEL

    def __post_init__(self) -> None:
        _require_identifier(self.package_id, "package_id")
        _require_identifier(self.frame_part_name, "frame_part_name")
        if isinstance(self.target_offset_ms, bool) or not isinstance(self.target_offset_ms, int):
            raise VisibleCardError("target_offset_ms must be an integer.")
        if not isinstance(self.image_bytes, bytes) or not self.image_bytes:
            raise VisibleCardError("image_bytes must contain source image bytes.")
        _require_positive_int(self.width, "width")
        _require_positive_int(self.height, "height")
        for field_name, value in (
            ("model", self.model),
            ("provider", self.provider),
            ("api_version", self.api_version),
            ("thinking_level", self.thinking_level),
        ):
            if not isinstance(value, str) or not value:
                raise VisibleCardError(f"{field_name} must be a non-empty string.")
        if not isinstance(self.prompt, str) or not self.prompt:
            raise VisibleCardError("prompt must be a non-empty string.")
        if not isinstance(self.response_schema, Mapping):
            raise VisibleCardError("response_schema must be a JSON object.")
        if not isinstance(self.image_mime_type, str) or not self.image_mime_type.startswith(
            "image/"
        ):
            raise VisibleCardError("image_mime_type must be an image MIME type.")

    @property
    def image_sha256(self) -> str:
        return _sha256(self.image_bytes)

    @property
    def request_key(self) -> str:
        return _sha256(_canonical_json(self.to_mapping()))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "package_id": self.package_id,
            "frame_part_name": self.frame_part_name,
            "target_offset_ms": self.target_offset_ms,
            "image_sha256": self.image_sha256,
            "image_mime_type": self.image_mime_type,
            "width": self.width,
            "height": self.height,
            "provider": self.provider,
            "api_version": self.api_version,
            "model": self.model,
            "prompt": self.prompt,
            "response_schema": self.response_schema,
            "thinking_level": self.thinking_level,
            "prompt_sha256": _sha256(self.prompt.encode("utf-8")),
            "response_schema_sha256": _sha256(_canonical_json(self.response_schema)),
        }


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    """Token counts reported by a provider."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        for field_name, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
            ("total_tokens", self.total_tokens),
        ):
            _require_non_negative_int(value, field_name)

    @classmethod
    def from_usage_metadata(cls, metadata: Any) -> "ProviderUsage":
        if metadata is None:
            return cls()
        if not isinstance(metadata, dict):
            raise VisibleCardValidationError("usageMetadata must be an object.")
        input_tokens = metadata.get("promptTokenCount", 0)
        output_tokens = metadata.get("candidatesTokenCount", 0)
        total_tokens = metadata.get("totalTokenCount", input_tokens + output_tokens)
        return cls(
            input_tokens=_require_non_negative_int(input_tokens, "promptTokenCount"),
            output_tokens=_require_non_negative_int(output_tokens, "candidatesTokenCount"),
            total_tokens=_require_non_negative_int(total_tokens, "totalTokenCount"),
        )

    def to_mapping(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """One successful or explicitly unavailable provider result."""

    status: Literal["ok", "unavailable"]
    proposals: tuple[VisibleCardProposal, ...] = ()
    raw_response: dict[str, Any] | None = None
    usage: ProviderUsage = ProviderUsage()
    latency_ms: float = 0.0
    retry_count: int = 0
    estimated_cost_usd: float = 0.0
    error: str | None = None
    cache_hit: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"ok", "unavailable"}:
            raise VisibleCardError("provider result status must be ok or unavailable.")
        if self.status == "ok" and self.error is not None:
            raise VisibleCardError("an ok provider result cannot contain an error.")
        if self.status == "unavailable" and not self.error:
            raise VisibleCardError("an unavailable provider result needs an error.")
        if self.raw_response is not None and not isinstance(self.raw_response, dict):
            raise VisibleCardError("raw_response must be an object or null.")
        _require_finite_non_negative(self.latency_ms, "latency_ms")
        _require_non_negative_int(self.retry_count, "retry_count")
        _require_finite_non_negative(self.estimated_cost_usd, "estimated_cost_usd")
        if not isinstance(self.cache_hit, bool):
            raise VisibleCardError("cache_hit must be a boolean.")
        if self.status == "unavailable" and self.proposals:
            raise VisibleCardError("unavailable results must not contain proposals.")

    @property
    def prediction(self) -> VisibleCardPrediction:
        return VisibleCardPrediction(cards=self.proposals)

    def to_mapping(self, *, include_raw_response: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "prediction": self.prediction.to_mapping(),
            "usage": self.usage.to_mapping(),
            "latency_ms": self.latency_ms,
            "retry_count": self.retry_count,
            "estimated_cost_usd": self.estimated_cost_usd,
            "error": self.error,
        }
        if include_raw_response:
            result["raw_response"] = self.raw_response
        return result

    @classmethod
    def from_mapping(cls, value: Any) -> "ProviderResult":
        if not isinstance(value, dict):
            raise VisibleCardError("provider result must be an object.")
        expected = {
            "status",
            "prediction",
            "usage",
            "latency_ms",
            "retry_count",
            "estimated_cost_usd",
            "error",
            "raw_response",
        }
        if set(value) != expected:
            raise VisibleCardError("provider result has unexpected fields.")
        prediction = normalize_prediction(value["prediction"])
        usage_value = value["usage"]
        if not isinstance(usage_value, dict) or set(usage_value) != {
            "input_tokens",
            "output_tokens",
            "total_tokens",
        }:
            raise VisibleCardError("provider result usage has unexpected fields.")
        return cls(
            status=value["status"],
            proposals=prediction.cards,
            raw_response=value["raw_response"],
            usage=ProviderUsage(**usage_value),
            latency_ms=value["latency_ms"],
            retry_count=value["retry_count"],
            estimated_cost_usd=value["estimated_cost_usd"],
            error=value["error"],
        )


@runtime_checkable
class VisibleCardProvider(Protocol):
    """Provider boundary for one exact-event source frame."""

    name: str
    version: str

    def propose(self, request: VisibleCardRequest) -> ProviderResult:
        """Return visible-card proposals or an explicit unavailable result."""


class FakeVisibleCardProvider:
    """Deterministic provider for local development and tests."""

    name = "fake"
    version = "fake-v1"

    def __init__(self, predictions: Mapping[str, Any] | None = None) -> None:
        self._predictions = {
            image_sha256: normalize_prediction(prediction)
            for image_sha256, prediction in (predictions or {}).items()
        }

    def propose(self, request: VisibleCardRequest) -> ProviderResult:
        prediction = self._predictions.get(request.image_sha256, VisibleCardPrediction(cards=()))
        return ProviderResult(
            status="ok",
            proposals=prediction.cards,
            raw_response={"provider": self.name, "prediction": prediction.to_mapping()},
        )


class GeminiVisibleCardProvider:
    """Gemini structured-output provider with bounded retries and runtime credentials."""

    name = GEMINI_PROVIDER_NAME
    version = "gemini-visible-cards-v1"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        urlopen: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise MissingCredentialError("GEMINI_API_KEY is not set.")
        self.api_key = api_key
        self.timeout_s = _require_finite_non_negative(timeout_s, "timeout_s")
        if self.timeout_s <= 0:
            raise VisibleCardError("timeout_s must be greater than zero.")
        _require_non_negative_int(max_retries, "max_retries")
        if max_retries > 5:
            raise VisibleCardError("max_retries must be at most 5.")
        self.max_retries = max_retries
        self._urlopen = urllib.request.urlopen if urlopen is None else urlopen
        self._sleep = sleep

    @classmethod
    def from_environment(cls, **kwargs: Any) -> "GeminiVisibleCardProvider":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise MissingCredentialError("GEMINI_API_KEY is not set.")
        return cls(api_key=api_key, **kwargs)

    def propose(self, request: VisibleCardRequest) -> ProviderResult:
        if request.provider != self.name:
            raise VisibleCardError(
                f"request provider {request.provider!r} does not match {self.name!r}."
            )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": request.prompt},
                        {
                            "inlineData": {
                                "mimeType": request.image_mime_type,
                                "data": base64.b64encode(request.image_bytes).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": request.response_schema,
                "thinkingConfig": {"thinkingLevel": request.thinking_level},
            },
        }
        request_url = (
            f"https://generativelanguage.googleapis.com/{request.api_version}/models/"
            f"{request.model}:generateContent"
        )
        http_request = urllib.request.Request(
            request_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )

        started = time.monotonic()
        last_error = "Gemini returned a malformed response."
        last_raw_response: dict[str, Any] | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with self._urlopen(http_request, timeout=self.timeout_s) as response:
                    raw_response = json.loads(response.read().decode("utf-8"))
                if not isinstance(raw_response, dict):
                    raise VisibleCardValidationError("Gemini response must be an object.")
                last_raw_response = raw_response
                parts = raw_response["candidates"][0]["content"]["parts"]
                raw_text = next(
                    part["text"]
                    for part in parts
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                )
                if not isinstance(raw_text, str):
                    raise VisibleCardValidationError("Gemini candidate text must be a string.")
                prediction = normalize_prediction(json.loads(raw_text))
                usage = ProviderUsage.from_usage_metadata(raw_response.get("usageMetadata"))
                return ProviderResult(
                    status="ok",
                    proposals=prediction.cards,
                    raw_response=raw_response,
                    usage=usage,
                    latency_ms=_elapsed_ms(started),
                    retry_count=attempt,
                    estimated_cost_usd=_estimate_cost(usage),
                )
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                last_error = f"Gemini HTTP {error.code}: {body[:1000]}"
                if error.code not in {429, 500, 502, 503, 504}:
                    break
            except (
                IndexError,
                KeyError,
                json.JSONDecodeError,
                StopIteration,
                UnicodeDecodeError,
                TypeError,
            ) as error:
                last_error = f"Gemini returned a malformed response: {error}"
            except VisibleCardValidationError as error:
                last_error = f"Gemini returned a malformed response: {error}"
            except (TimeoutError, urllib.error.URLError, OSError) as error:
                last_error = f"Gemini request failed: {error}"
            if attempt < self.max_retries:
                self._sleep(2**attempt)

        return ProviderResult(
            status="unavailable",
            raw_response=last_raw_response,
            latency_ms=_elapsed_ms(started),
            retry_count=attempt,
            error=last_error,
        )


def _import_torch() -> Any:
    try:
        import torch
    except ImportError as error:
        raise VisibleCardError(
            "local visible-card inference requires PyTorch; install the inference dependency group"
        ) from error
    return torch


def _local_device_available(device: str, torch_module: Any) -> bool:
    if device == "cpu":
        return True
    backends = getattr(torch_module, "backends", None)
    mps = getattr(backends, "mps", None)
    is_available = getattr(mps, "is_available", None)
    return bool(callable(is_available) and is_available())


def _load_local_rfdetr(bundle: Any, device: str) -> Any:
    try:
        from rfdetr import RFDETRLarge
    except ImportError as error:
        raise VisibleCardError(
            f"local visible-card inference requires rfdetr {LOCAL_RFDETR_VERSION}; "
            "install the inference dependency group"
        ) from error
    try:
        package_version = importlib.metadata.version("rfdetr")
    except importlib.metadata.PackageNotFoundError as error:
        raise VisibleCardError("RF-DETR package metadata is not installed") from error
    if package_version != LOCAL_RFDETR_VERSION:
        raise VisibleCardError(
            f"installed rfdetr version {package_version} does not match the frozen "
            f"{LOCAL_RFDETR_VERSION} bundle"
        )
    try:
        model = RFDETRLarge.from_checkpoint(
            str(bundle.checkpoint_path),
            num_classes=1,
            resolution=LOCAL_INPUT_SIZE,
            device=device,
        )
    except Exception as error:
        raise VisibleCardError(f"could not load the local RF-DETR bundle: {error}") from error
    model_context = getattr(model, "model", None)
    actual_device = getattr(model_context, "device", None)
    if actual_device is not None:
        actual_device_name = str(actual_device).split(":", 1)[0]
        if actual_device_name != device:
            raise VisibleCardError(
                f"RF-DETR loaded on {actual_device!s}, but the requested device is {device}"
            )
    return model


def _sequence(value: Any, field_name: str) -> list[Any]:
    if value is None:
        raise VisibleCardError(f"detector output is missing {field_name}")
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        value = tolist()
    if not isinstance(value, (list, tuple)):
        raise VisibleCardError(f"detector output {field_name} must be a sequence")
    return list(value)


def _detections_field(detections: Any, field_name: str) -> Any:
    if isinstance(detections, Mapping):
        return detections.get(field_name)
    return getattr(detections, field_name, None)


def _normalise_detection_rows(value: Any, field_name: str) -> list[list[Any]]:
    rows = _sequence(value, field_name)
    if rows and not isinstance(rows[0], (list, tuple)):
        if len(rows) != 4:
            raise VisibleCardError(f"detector output {field_name} must contain four coordinates")
        return [rows]
    return [list(row) if isinstance(row, (list, tuple)) else [] for row in rows]


def _local_bundle_identity(bundle: Any) -> dict[str, Any]:
    manifest = bundle.manifest
    return {
        "schema_version": manifest["schema_version"],
        "bundle_digest": manifest["bundle_digest"],
        "checkpoint_sha256": manifest["checkpoint_sha256"],
        "run_id": manifest.get("run_id"),
    }


def _normalised_box_from_pixels(
    coordinates: list[Any], *, width: int, height: int
) -> tuple[NormalizedBox, list[float]]:
    if len(coordinates) != 4:
        raise VisibleCardError("detector output box must contain x_min, y_min, x_max, y_max")
    try:
        x_min_pixel, y_min_pixel, x_max_pixel, y_max_pixel = (float(value) for value in coordinates)
    except (TypeError, ValueError) as error:
        raise VisibleCardError("detector output box must contain numeric coordinates") from error
    if not all(
        math.isfinite(value) for value in (x_min_pixel, y_min_pixel, x_max_pixel, y_max_pixel)
    ):
        raise VisibleCardError("detector output box must contain finite coordinates")
    x_min_pixel = max(0.0, min(float(width), x_min_pixel))
    x_max_pixel = max(0.0, min(float(width), x_max_pixel))
    y_min_pixel = max(0.0, min(float(height), y_min_pixel))
    y_max_pixel = max(0.0, min(float(height), y_max_pixel))
    if x_min_pixel >= x_max_pixel or y_min_pixel >= y_max_pixel:
        raise VisibleCardError("detector output box must have positive width and height")
    x_min = max(0, min(1000, math.floor(x_min_pixel * 1000 / width)))
    y_min = max(0, min(1000, math.floor(y_min_pixel * 1000 / height)))
    x_max = max(0, min(1000, math.ceil(x_max_pixel * 1000 / width)))
    y_max = max(0, min(1000, math.ceil(y_max_pixel * 1000 / height)))
    if x_min >= x_max or y_min >= y_max:
        raise VisibleCardError("detector output box is too small for normalized geometry")
    return (
        NormalizedBox(y_min=y_min, x_min=x_min, y_max=y_max, x_max=x_max),
        [x_min_pixel, y_min_pixel, x_max_pixel, y_max_pixel],
    )


class LocalVisibleCardProvider:
    """Run one bundled RF-DETR detector on an explicitly selected local device."""

    name = LOCAL_PROVIDER_NAME
    version = LOCAL_PROVIDER_VERSION

    def __init__(
        self,
        bundle: str | Path,
        *,
        device: Literal["cpu", "mps"] = "cpu",
        detector: Any | None = None,
        model_loader: Callable[[Any, str], Any] | None = None,
        torch_module: Any | None = None,
    ) -> None:
        if device not in LOCAL_DEVICE_NAMES:
            raise VisibleCardError("local device must be cpu or mps")
        from .visible_card_training import load_visible_card_detector_bundle

        try:
            loaded_bundle = load_visible_card_detector_bundle(bundle)
        except Exception as error:
            raise VisibleCardError(
                f"could not validate the local visible-card bundle: {error}"
            ) from error
        self.bundle = loaded_bundle
        self.device = device
        self.confidence_threshold = LOCAL_CONFIDENCE_THRESHOLD
        self.input_size = LOCAL_INPUT_SIZE
        if torch_module is None and device == "mps":
            torch_module = _import_torch()
        if torch_module is not None and not _local_device_available(device, torch_module):
            raise VisibleCardError(f"requested local device is unavailable: {device}")
        self._torch = torch_module
        self._detector = detector
        started = time.monotonic()
        if self._detector is None:
            loader = model_loader or _load_local_rfdetr
            self._detector = loader(self.bundle, device)
        self.load_latency_ms = _elapsed_ms(started)

    @property
    def bundle_identity(self) -> dict[str, Any]:
        return _local_bundle_identity(self.bundle)

    def _unavailable(
        self, error: str, started: float, *, raw: dict[str, Any] | None = None
    ) -> ProviderResult:
        response = {
            "provider": self.name,
            "version": self.version,
            "device": self.device,
            "bundle_identity": self.bundle_identity,
            "load_latency_ms": self.load_latency_ms,
        }
        if raw:
            response.update(raw)
        return ProviderResult(
            status="unavailable",
            raw_response=response,
            latency_ms=_elapsed_ms(started),
            error=error,
        )

    def propose(self, request: VisibleCardRequest) -> ProviderResult:
        if request.provider != self.name:
            raise VisibleCardError(
                f"request provider {request.provider!r} does not match {self.name!r}."
            )
        started = time.monotonic()
        try:
            with Image.open(BytesIO(request.image_bytes)) as source:
                if source.size != (request.width, request.height):
                    raise VisibleCardError(
                        "decoded source image dimensions do not match the request dimensions"
                    )
                image = source.convert("RGB").copy()
        except (UnidentifiedImageError, OSError, ValueError) as error:
            return self._unavailable(
                f"local visible-card input could not be decoded: {error}", started
            )
        try:
            detections = self._detector.predict(
                image,
                threshold=self.confidence_threshold,
                shape=(self.input_size, self.input_size),
                include_source_image=False,
            )
            boxes = _normalise_detection_rows(_detections_field(detections, "xyxy"), "xyxy")
            confidence = _sequence(_detections_field(detections, "confidence"), "confidence")
            class_ids = _sequence(_detections_field(detections, "class_id"), "class_id")
            if not (len(boxes) == len(confidence) == len(class_ids)):
                raise VisibleCardError("detector output fields have different lengths")
            proposals: list[VisibleCardProposal] = []
            output_detections: list[dict[str, Any]] = []
            for coordinates, raw_score, raw_class_id in zip(
                boxes, confidence, class_ids, strict=True
            ):
                score = float(raw_score)
                class_id = int(raw_class_id)
                if not math.isfinite(score) or not 0 <= score <= 1:
                    raise VisibleCardError("detector output confidence must be finite in [0, 1]")
                if class_id != 0:
                    raise VisibleCardError(f"detector returned unsupported class id: {class_id}")
                if score <= self.confidence_threshold:
                    continue
                box, pixel_box = _normalised_box_from_pixels(
                    coordinates, width=request.width, height=request.height
                )
                proposals.append(
                    VisibleCardProposal(
                        box_2d=box,
                        polygon=(
                            NormalizedPoint(x=box.x_min, y=box.y_min),
                            NormalizedPoint(x=box.x_max, y=box.y_min),
                            NormalizedPoint(x=box.x_max, y=box.y_max),
                            NormalizedPoint(x=box.x_min, y=box.y_max),
                        ),
                        side="unknown",
                        label="visible_card",
                    )
                )
                output_detections.append(
                    {"class_id": class_id, "score": score, "box_xyxy": pixel_box}
                )
        except Exception as error:
            return self._unavailable(f"local visible-card inference failed: {error}", started)
        return ProviderResult(
            status="ok",
            proposals=tuple(proposals),
            raw_response={
                "provider": self.name,
                "version": self.version,
                "device": self.device,
                "bundle_identity": self.bundle_identity,
                "load_latency_ms": self.load_latency_ms,
                "confidence_threshold": self.confidence_threshold,
                "detector_scores": [detection["score"] for detection in output_detections],
                "detections": output_detections,
            },
            latency_ms=_elapsed_ms(started),
        )


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, time.monotonic() - started) * 1000.0, 3)


def _estimate_cost(usage: ProviderUsage) -> float:
    return round(
        usage.input_tokens * INPUT_PRICE_PER_MILLION / 1_000_000
        + usage.output_tokens * OUTPUT_PRICE_PER_MILLION / 1_000_000,
        10,
    )


class CachedVisibleCardProvider:
    """Cache raw provider responses and normalized predictions by the full request key."""

    name = "cached"
    version = CACHE_SCHEMA_VERSION

    def __init__(self, provider: VisibleCardProvider, cache_dir: str | Path) -> None:
        self.provider = provider
        self.cache_dir = Path(cache_dir)

    def propose(self, request: VisibleCardRequest) -> ProviderResult:
        cache_path = self._cache_path(request)
        cached = self._load(cache_path, request)
        if cached is not None:
            return replace(cached, cache_hit=True)
        result = self.provider.propose(request)
        self._store(cache_path, request, result)
        return result

    def _cache_path(self, request: VisibleCardRequest) -> Path:
        return self.cache_dir / request.request_key[:2] / f"{request.request_key}.json"

    def _load(self, path: Path, request: VisibleCardRequest) -> ProviderResult | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                return None
            expected_fields = {
                "schema_version",
                "request_key",
                "request",
                "prediction_schema_version",
                "status",
                "prediction",
                "usage",
                "latency_ms",
                "retry_count",
                "estimated_cost_usd",
                "error",
                "raw_response",
                "provider",
            }
            if set(value) != expected_fields:
                return None
            if value.get("schema_version") != CACHE_SCHEMA_VERSION:
                return None
            if value.get("prediction_schema_version") != PREDICTION_SCHEMA_VERSION:
                return None
            if value.get("request_key") != request.request_key:
                return None
            if value.get("request") != request.to_mapping():
                return None
            if value.get("provider") != {
                "name": self.provider.name,
                "version": self.provider.version,
            }:
                return None
            return ProviderResult.from_mapping(
                {
                    key: value[key]
                    for key in (
                        "status",
                        "prediction",
                        "usage",
                        "latency_ms",
                        "retry_count",
                        "estimated_cost_usd",
                        "error",
                        "raw_response",
                    )
                }
            )
        except (OSError, ValueError, KeyError, TypeError, VisibleCardError, json.JSONDecodeError):
            return None

    def _store(self, path: Path, request: VisibleCardRequest, result: ProviderResult) -> None:
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "request_key": request.request_key,
            "request": request.to_mapping(),
            "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
            **result.to_mapping(),
            "provider": {
                "name": self.provider.name,
                "version": self.provider.version,
            },
        }
        _atomic_write_json(path, payload)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        fd, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_path)


def render_overlay_svg(request: VisibleCardRequest, prediction: VisibleCardPrediction) -> str:
    """Render a self-contained SVG overlay without adding an image-processing dependency."""

    image_data = base64.b64encode(request.image_bytes).decode("ascii")
    elements = [
        f'<image href="data:{html.escape(request.image_mime_type)};base64,{image_data}" '
        f'width="{request.width}" height="{request.height}" '
        f'preserveAspectRatio="none" />'
    ]
    colors = {"face_up": "#3cbe46", "face_down": "#288cf0", "unknown": "#d25ab4"}
    for index, card in enumerate(prediction.cards, start=1):
        points = " ".join(
            f"{round(point.x * request.width / 1000)},{round(point.y * request.height / 1000)}"
            for point in card.polygon
        )
        color = colors[card.side]
        elements.append(
            f'<polygon points="{points}" fill="{color}" fill-opacity="0.30" '
            f'stroke="{color}" stroke-width="4" />'
        )
        center_x = round(
            sum(point.x for point in card.polygon) / len(card.polygon) * request.width / 1000
        )
        center_y = round(
            sum(point.y for point in card.polygon) / len(card.polygon) * request.height / 1000
        )
        label = html.escape(f"{index} {card.side.upper()}: {card.label}")
        elements.append(
            f'<text x="{center_x}" y="{max(24, center_y)}" fill="white" stroke="black" '
            f'stroke-width="3" paint-order="stroke" font-family="sans-serif" font-size="20">'
            f"{label}</text>"
        )
    body = "".join(elements)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{request.width}" '
        f'height="{request.height}" viewBox="0 0 {request.width} {request.height}">{body}</svg>\n'
    )


def write_overlay_svg(
    request: VisibleCardRequest, prediction: VisibleCardPrediction, destination: str | Path
) -> Path:
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        fd, temporary_path = tempfile.mkstemp(
            prefix=f".{destination_path.name}.", dir=destination_path.parent
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(render_overlay_svg(request, prediction))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_path)
    return destination_path


@dataclass(frozen=True, slots=True)
class VisibleCardReviewItem:
    item_id: str
    package_id: str
    frame_part_name: str
    target_offset_ms: int
    image: str
    overlay: str | None
    prediction: dict[str, Any]
    prediction_sha256: str
    decision: Literal["GOOD", "BAD"] | None = None
    reviewer: str | None = None
    decision_at_utc: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "package_id": self.package_id,
            "frame_part_name": self.frame_part_name,
            "target_offset_ms": self.target_offset_ms,
            "image": self.image,
            "overlay": self.overlay,
            "prediction": self.prediction,
            "prediction_sha256": self.prediction_sha256,
            "decision": self.decision,
            "reviewer": self.reviewer,
            "decision_at_utc": self.decision_at_utc,
        }


@dataclass(frozen=True, slots=True)
class VisibleCardReviewQueue:
    run_id: str
    items: tuple[VisibleCardReviewItem, ...]
    created_at_utc: str
    schema_version: str = REVIEW_QUEUE_SCHEMA_VERSION

    @property
    def pending_items(self) -> tuple[VisibleCardReviewItem, ...]:
        return tuple(item for item in self.items if item.decision is None)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at_utc": self.created_at_utc,
            "items": [item.to_mapping() for item in self.items],
        }


def build_review_queue(
    results: Sequence[Mapping[str, Any]],
    destination: str | Path,
    *,
    run_id: str,
) -> VisibleCardReviewQueue:
    """Create a deterministic queue from provider run records without overwriting one."""

    _require_identifier(run_id, "run_id")
    destination_path = Path(destination)
    if destination_path.exists():
        raise VisibleCardError(f"review queue already exists: {destination_path}")
    items: list[VisibleCardReviewItem] = []
    for source in results:
        package_id = _require_identifier(source.get("package_id"), "package_id")
        frame_part_name = _require_identifier(source.get("frame_part_name"), "frame_part_name")
        item_id = f"{package_id}:{frame_part_name}"
        prediction_value = source.get("prediction")
        if isinstance(prediction_value, ProviderResult):
            prediction = prediction_value.prediction.to_mapping()
        elif isinstance(prediction_value, VisibleCardPrediction):
            prediction = prediction_value.to_mapping()
        else:
            prediction = normalize_prediction(prediction_value).to_mapping()
        if any(item.item_id == item_id for item in items):
            raise VisibleCardError(f"review queue contains duplicate item: {item_id}")
        target_offset_ms = source.get("target_offset_ms")
        if isinstance(target_offset_ms, bool) or not isinstance(target_offset_ms, int):
            raise VisibleCardError("target_offset_ms must be an integer.")
        image = source.get("image")
        if not isinstance(image, str) or not image:
            raise VisibleCardError(f"review item {item_id} needs an image path.")
        overlay = source.get("overlay")
        if overlay is not None and (not isinstance(overlay, str) or not overlay):
            raise VisibleCardError(f"review item {item_id} has an invalid overlay path.")
        items.append(
            VisibleCardReviewItem(
                item_id=item_id,
                package_id=package_id,
                frame_part_name=frame_part_name,
                target_offset_ms=target_offset_ms,
                image=image,
                overlay=overlay,
                prediction=prediction,
                prediction_sha256=_sha256(_canonical_json(prediction)),
            )
        )
    items.sort(key=lambda item: item.item_id)
    queue = VisibleCardReviewQueue(
        run_id=run_id,
        items=tuple(items),
        created_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    _atomic_write_json(destination_path, queue.to_mapping())
    return queue


def load_review_queue(path: str | Path) -> VisibleCardReviewQueue:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardError(f"could not read review queue: {path}") from error
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "run_id",
        "created_at_utc",
        "items",
    }:
        raise VisibleCardError("review queue has unexpected fields.")
    if value["schema_version"] != REVIEW_QUEUE_SCHEMA_VERSION:
        raise VisibleCardError("unsupported review queue schema version.")
    if not isinstance(value["created_at_utc"], str) or not value["created_at_utc"]:
        raise VisibleCardError("review queue created_at_utc must be a non-empty string.")
    if not isinstance(value["items"], list):
        raise VisibleCardError("review queue items must be a list.")
    items = tuple(_review_item_from_mapping(item) for item in value["items"])
    if len({item.item_id for item in items}) != len(items):
        raise VisibleCardError("review queue item IDs must be unique.")
    return VisibleCardReviewQueue(
        run_id=_require_identifier(value["run_id"], "run_id"),
        items=items,
        created_at_utc=value["created_at_utc"],
    )


def _review_item_from_mapping(value: Any) -> VisibleCardReviewItem:
    if not isinstance(value, dict):
        raise VisibleCardError("review queue item must be an object.")
    expected = {
        "item_id",
        "package_id",
        "frame_part_name",
        "target_offset_ms",
        "image",
        "overlay",
        "prediction",
        "prediction_sha256",
        "decision",
        "reviewer",
        "decision_at_utc",
    }
    if set(value) != expected:
        raise VisibleCardError("review queue item has unexpected fields.")
    item_id = _require_identifier(value["item_id"], "item_id")
    package_id = _require_identifier(value["package_id"], "package_id")
    frame_part_name = _require_identifier(value["frame_part_name"], "frame_part_name")
    if item_id != f"{package_id}:{frame_part_name}":
        raise VisibleCardError("review queue item_id does not match its source identifiers.")
    if isinstance(value["target_offset_ms"], bool) or not isinstance(
        value["target_offset_ms"], int
    ):
        raise VisibleCardError("review item target_offset_ms must be an integer.")
    image = value["image"]
    overlay = value["overlay"]
    if not isinstance(image, str) or not image:
        raise VisibleCardError(f"review item {item_id} needs an image path.")
    if overlay is not None and (not isinstance(overlay, str) or not overlay):
        raise VisibleCardError(f"review item {item_id} has an invalid overlay path.")
    prediction = normalize_prediction(value["prediction"]).to_mapping()
    prediction_sha256 = value["prediction_sha256"]
    if prediction_sha256 != _sha256(_canonical_json(prediction)):
        raise VisibleCardError(f"review item {item_id} prediction digest does not match.")
    decision = value["decision"]
    if decision not in {None, "GOOD", "BAD"}:
        raise VisibleCardError("review decision must be GOOD, BAD, or null.")
    reviewer = value["reviewer"]
    decision_at_utc = value["decision_at_utc"]
    if decision is None and (reviewer is not None or decision_at_utc is not None):
        raise VisibleCardError("an unreviewed item must not contain review metadata.")
    if decision is not None and (
        not isinstance(reviewer, str)
        or not reviewer.strip()
        or not isinstance(decision_at_utc, str)
        or not decision_at_utc
    ):
        raise VisibleCardError("a reviewed item needs reviewer and decision time.")
    return VisibleCardReviewItem(
        item_id=item_id,
        package_id=package_id,
        frame_part_name=frame_part_name,
        target_offset_ms=value["target_offset_ms"],
        image=image,
        overlay=overlay,
        prediction=prediction,
        prediction_sha256=prediction_sha256,
        decision=decision,
        reviewer=reviewer,
        decision_at_utc=decision_at_utc,
    )


def record_review(
    path: str | Path,
    item_id: str,
    decision: Literal["GOOD", "BAD"],
    *,
    reviewer: str,
) -> VisibleCardReviewQueue:
    """Record one decision and atomically preserve all other queue state."""

    _require_identifier(item_id, "item_id")
    if decision not in {"GOOD", "BAD"}:
        raise VisibleCardError("decision must be GOOD or BAD.")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise VisibleCardError("reviewer must be a non-empty string.")
    queue = load_review_queue(path)
    if not any(item.item_id == item_id for item in queue.items):
        raise VisibleCardError(f"review queue item does not exist: {item_id}")
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    updated: list[VisibleCardReviewItem] = []
    for item in queue.items:
        if item.item_id != item_id:
            updated.append(item)
            continue
        if item.decision is not None and item.decision != decision:
            raise VisibleCardError(f"review queue item already has decision {item.decision}.")
        updated.append(replace(item, decision=decision, reviewer=reviewer, decision_at_utc=now))
    result = replace(queue, items=tuple(updated))
    _atomic_write_json(Path(path), result.to_mapping())
    return result


def image_dimensions(image_bytes: bytes, mime_type: str = "image/jpeg") -> tuple[int, int]:
    """Read PNG or JPEG dimensions without an image-processing dependency."""

    if mime_type == "image/png" and image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(image_bytes) < 24 or image_bytes[12:16] != b"IHDR":
            raise VisibleCardError("PNG image is missing an IHDR chunk.")
        width = int.from_bytes(image_bytes[16:20], "big")
        height = int.from_bytes(image_bytes[20:24], "big")
        return _image_size(width, height)
    if image_bytes[:2] != b"\xff\xd8":
        raise VisibleCardError("cannot infer image dimensions; pass --width and --height.")
    position = 2
    while position + 9 <= len(image_bytes):
        if image_bytes[position] != 0xFF:
            position += 1
            continue
        while position < len(image_bytes) and image_bytes[position] == 0xFF:
            position += 1
        if position >= len(image_bytes):
            break
        marker = image_bytes[position]
        position += 1
        if marker in {0xD8, 0xD9}:
            continue
        if position + 2 > len(image_bytes):
            break
        segment_length = int.from_bytes(image_bytes[position : position + 2], "big")
        if segment_length < 2 or position + segment_length > len(image_bytes):
            break
        if marker in set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(
            range(0xCD, 0xD0)
        ):
            if segment_length < 7:
                break
            height = int.from_bytes(image_bytes[position + 3 : position + 5], "big")
            width = int.from_bytes(image_bytes[position + 5 : position + 7], "big")
            return _image_size(width, height)
        position += segment_length
    raise VisibleCardError("could not read JPEG dimensions; pass --width and --height.")


def _image_size(width: int, height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise VisibleCardError("image dimensions must be positive.")
    return width, height


def build_request_from_image(
    image_path: str | Path,
    *,
    package_id: str,
    frame_part_name: str,
    target_offset_ms: int,
    width: int | None = None,
    height: int | None = None,
    model: str = DEFAULT_MODEL,
    provider: str = GEMINI_PROVIDER_NAME,
) -> VisibleCardRequest:
    path = Path(image_path)
    image_bytes = path.read_bytes()
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    if width is None or height is None:
        inferred_width, inferred_height = image_dimensions(image_bytes, mime_type)
        width = inferred_width if width is None else width
        height = inferred_height if height is None else height
    return VisibleCardRequest(
        package_id=package_id,
        frame_part_name=frame_part_name,
        target_offset_ms=target_offset_ms,
        image_bytes=image_bytes,
        width=width,
        height=height,
        model=model,
        provider=provider,
        image_mime_type=mime_type,
    )


def write_run_artifact(
    request: VisibleCardRequest,
    result: ProviderResult,
    destination: str | Path,
    *,
    image: str | None = None,
    overlay: str | None = None,
) -> Path:
    payload = {
        "schema_version": RUN_SCHEMA_VERSION,
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "request_key": request.request_key,
        "request": request.to_mapping(),
        "provider": {"name": request.provider, "model": request.model},
        "image": image,
        "overlay": overlay,
        **result.to_mapping(),
    }
    destination_path = Path(destination)
    _atomic_write_json(destination_path, payload)
    return destination_path


def load_run_artifact(path: str | Path) -> dict[str, Any]:
    """Load and strictly validate one visible-card run artifact."""

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardError(f"could not read visible-card run: {path}") from error
    if not isinstance(value, dict):
        raise VisibleCardError("visible-card run must be an object.")
    result_fields = {
        "status",
        "prediction",
        "usage",
        "latency_ms",
        "retry_count",
        "estimated_cost_usd",
        "error",
        "raw_response",
    }
    expected_fields = {
        "schema_version",
        "prediction_schema_version",
        "request_key",
        "request",
        "provider",
        "image",
        "overlay",
        *result_fields,
    }
    if set(value) != expected_fields:
        raise VisibleCardError("visible-card run has unexpected fields.")
    if value["schema_version"] != RUN_SCHEMA_VERSION:
        raise VisibleCardError("unsupported visible-card run schema version.")
    if value["prediction_schema_version"] != PREDICTION_SCHEMA_VERSION:
        raise VisibleCardError("unsupported visible-card prediction schema version.")
    request = _validate_request_mapping(value["request"])
    if value["request_key"] != _sha256(_canonical_json(request)):
        raise VisibleCardError("visible-card run request key does not match its request.")
    provider = value["provider"]
    if not isinstance(provider, dict) or set(provider) != {"name", "model"}:
        raise VisibleCardError("visible-card run provider has unexpected fields.")
    if provider != {"name": request["provider"], "model": request["model"]}:
        raise VisibleCardError("visible-card run provider does not match its request.")
    for field_name in ("image", "overlay"):
        field_value = value[field_name]
        if field_value is not None and (not isinstance(field_value, str) or not field_value):
            raise VisibleCardError(f"visible-card run {field_name} must be a path or null.")
    ProviderResult.from_mapping({field_name: value[field_name] for field_name in result_fields})
    return value


def _validate_request_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VisibleCardError("visible-card request must be an object.")
    expected_fields = {
        "schema_version",
        "package_id",
        "frame_part_name",
        "target_offset_ms",
        "image_sha256",
        "image_mime_type",
        "width",
        "height",
        "provider",
        "api_version",
        "model",
        "prompt",
        "response_schema",
        "thinking_level",
        "prompt_sha256",
        "response_schema_sha256",
    }
    if set(value) != expected_fields:
        raise VisibleCardError("visible-card request has unexpected fields.")
    if value["schema_version"] != REQUEST_SCHEMA_VERSION:
        raise VisibleCardError("unsupported visible-card request schema version.")
    _require_identifier(value["package_id"], "package_id")
    _require_identifier(value["frame_part_name"], "frame_part_name")
    if isinstance(value["target_offset_ms"], bool) or not isinstance(
        value["target_offset_ms"], int
    ):
        raise VisibleCardError("target_offset_ms must be an integer.")
    if (
        not isinstance(value["image_sha256"], str)
        or _SHA256.fullmatch(value["image_sha256"]) is None
    ):
        raise VisibleCardError("image_sha256 must be a lowercase SHA-256 digest.")
    if not isinstance(value["image_mime_type"], str) or not value["image_mime_type"].startswith(
        "image/"
    ):
        raise VisibleCardError("image_mime_type must be an image MIME type.")
    _require_positive_int(value["width"], "width")
    _require_positive_int(value["height"], "height")
    for field_name in ("provider", "api_version", "model", "thinking_level"):
        if not isinstance(value[field_name], str) or not value[field_name]:
            raise VisibleCardError(f"{field_name} must be a non-empty string.")
    if not isinstance(value["prompt"], str) or not value["prompt"]:
        raise VisibleCardError("prompt must be a non-empty string.")
    if not isinstance(value["response_schema"], dict):
        raise VisibleCardError("response_schema must be a JSON object.")
    try:
        prompt_sha256 = _sha256(value["prompt"].encode("utf-8"))
        response_schema_sha256 = _sha256(_canonical_json(value["response_schema"]))
    except (TypeError, ValueError) as error:
        raise VisibleCardError("visible-card request contains non-JSON values.") from error
    if value["prompt_sha256"] != prompt_sha256:
        raise VisibleCardError("visible-card request prompt digest does not match.")
    if value["response_schema_sha256"] != response_schema_sha256:
        raise VisibleCardError("visible-card request response-schema digest does not match.")
    return value


__all__ = [
    "CACHE_SCHEMA_VERSION",
    "DEFAULT_MODEL",
    "FakeVisibleCardProvider",
    "GeminiVisibleCardProvider",
    "LocalVisibleCardProvider",
    "LOCAL_PROVIDER_NAME",
    "LOCAL_PROVIDER_VERSION",
    "LOCAL_RFDETR_VERSION",
    "MissingCredentialError",
    "NormalizedBox",
    "NormalizedPoint",
    "PREDICTION_SCHEMA_VERSION",
    "PROMPT",
    "ProviderResult",
    "ProviderUsage",
    "RESPONSE_SCHEMA",
    "RUN_SCHEMA_VERSION",
    "VisibleCardError",
    "VisibleCardPrediction",
    "VisibleCardProposal",
    "VisibleCardProvider",
    "VisibleCardRequest",
    "VisibleCardReviewItem",
    "VisibleCardReviewQueue",
    "VisibleCardValidationError",
    "build_request_from_image",
    "build_review_queue",
    "image_dimensions",
    "load_run_artifact",
    "load_review_queue",
    "normalize_prediction",
    "record_review",
    "render_overlay_svg",
    "validate_prediction",
    "write_overlay_svg",
    "write_run_artifact",
]
