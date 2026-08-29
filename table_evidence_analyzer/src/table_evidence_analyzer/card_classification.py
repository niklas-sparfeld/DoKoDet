"""Gemini identity classification for transformed visible-card crops.

This is deliberately a narrow proof-of-concept boundary.  It accepts the deterministic binary
PPM crop produced by the visible-card transform and returns either one canonical visual card
identity or no identity.  A no-identity result is evidence that the crop is unreadable, not a
guess about the physical card.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from PIL import Image, UnidentifiedImageError

from .cards import CARD_IDENTITIES
from .table_observation import IdentityCandidate
from .visible_cards import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_S,
    GEMINI_API_VERSION,
    GEMINI_THINKING_LEVEL,
    MissingCredentialError,
    ProviderUsage,
    VisibleCardError,
)

CARD_CLASSIFICATION_SCHEMA = "gemini-card-classification/v1"
CARD_CLASSIFICATION_CACHE_SCHEMA = "gemini-card-classification-cache/v1"
UNKNOWN_CARD = "UNKNOWN"

PROMPT = """This image is a transformed crop of one visible Doppelkopf playing card.

Identify its visible suit and rank using the canonical card label in the response schema. Return
UNKNOWN when the crop is face-down, too occluded, too blurred, or otherwise cannot support a
reliable visual card identity. Do not guess. This is visual evidence only; do not infer a physical
card, a card play, a trick, or game state.
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "card": {"type": "string", "enum": [*CARD_IDENTITIES, UNKNOWN_CARD]},
    },
    "required": ["card"],
    "additionalProperties": False,
}


class CardClassificationError(VisibleCardError):
    """Raised when a transformed-card classification request is invalid."""


@dataclass(frozen=True, slots=True)
class CardClassificationResult:
    """One bounded classification response for one transformed card crop."""

    status: Literal["ok", "unavailable"]
    candidates: tuple[IdentityCandidate, ...] = ()
    usage: ProviderUsage = ProviderUsage()
    latency_ms: float = 0.0
    retry_count: int = 0
    estimated_cost_usd: float = 0.0
    error: str | None = None
    raw_response: dict[str, Any] | None = None
    cache_hit: bool = False

    def __post_init__(self) -> None:
        if self.status == "unavailable" and self.candidates:
            raise CardClassificationError("unavailable classification cannot contain candidates")


@runtime_checkable
class CardIdentityClassifier(Protocol):
    """Classify one binary PPM transformed card crop."""

    name: str
    version: str
    calibration: str

    def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult: ...


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ppm_to_png(crop_bytes: bytes) -> bytes:
    if not crop_bytes.startswith(b"P6\n"):
        raise CardClassificationError("Gemini card classifier expects a binary PPM crop")
    try:
        with Image.open(BytesIO(crop_bytes)) as image:
            output = BytesIO()
            image.convert("RGB").save(output, format="PNG")
            return output.getvalue()
    except (UnidentifiedImageError, OSError) as error:
        raise CardClassificationError("transformed card crop is not a valid PPM image") from error


@dataclass(frozen=True, slots=True)
class CardClassificationRequest:
    """Stable Gemini request inputs derived from one transformed card crop."""

    crop_bytes: bytes
    model: str = DEFAULT_MODEL
    prompt: str = PROMPT
    response_schema: dict[str, Any] | None = None
    api_version: str = GEMINI_API_VERSION
    thinking_level: str = GEMINI_THINKING_LEVEL

    def __post_init__(self) -> None:
        if not self.crop_bytes:
            raise CardClassificationError("transformed card crop bytes must be non-empty")
        if not self.model:
            raise CardClassificationError("Gemini model must be non-empty")
        if not self.prompt:
            raise CardClassificationError("classification prompt must be non-empty")
        if not self.api_version or not self.thinking_level:
            raise CardClassificationError("Gemini request configuration must be non-empty")
        if self.response_schema is None:
            object.__setattr__(self, "response_schema", RESPONSE_SCHEMA)

    @property
    def crop_sha256(self) -> str:
        return _sha256(self.crop_bytes)

    @property
    def request_key(self) -> str:
        return _sha256(
            json.dumps(self.to_mapping(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": CARD_CLASSIFICATION_SCHEMA,
            "crop_sha256": self.crop_sha256,
            "model": self.model,
            "prompt": self.prompt,
            "response_schema": self.response_schema,
            "api_version": self.api_version,
            "thinking_level": self.thinking_level,
        }


class GeminiCardClassifier:
    """Gemini structured-output classifier for transformed card crops."""

    name = "gemini"
    version = CARD_CLASSIFICATION_SCHEMA
    calibration = "uncalibrated"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        urlopen: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise MissingCredentialError("GEMINI_API_KEY is not set.")
        if not model:
            raise CardClassificationError("Gemini model must be non-empty")
        if timeout_s <= 0:
            raise CardClassificationError("timeout_s must be greater than zero")
        if not 0 <= max_retries <= 5:
            raise CardClassificationError("max_retries must be between zero and five")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._urlopen = urllib.request.urlopen if urlopen is None else urlopen
        self._sleep = sleep

    @classmethod
    def from_environment(cls, **kwargs: Any) -> "GeminiCardClassifier":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise MissingCredentialError("GEMINI_API_KEY is not set.")
        return cls(api_key=api_key, **kwargs)

    def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
        return self.classify(CardClassificationRequest(crop_bytes=crop_bytes, model=self.model))

    def classify(self, request: CardClassificationRequest) -> CardClassificationResult:
        png_bytes = _ppm_to_png(request.crop_bytes)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": request.prompt},
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": base64.b64encode(png_bytes).decode("ascii"),
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
        http_request = urllib.request.Request(
            (
                f"https://generativelanguage.googleapis.com/{request.api_version}/models/"
                f"{request.model}:generateContent"
            ),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        started = time.monotonic()
        last_error = "Gemini returned a malformed classification response."
        last_raw_response: dict[str, Any] | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with self._urlopen(http_request, timeout=self.timeout_s) as response:
                    raw_response = json.loads(response.read().decode("utf-8"))
                if not isinstance(raw_response, dict):
                    raise CardClassificationError("response must be an object")
                last_raw_response = raw_response
                text = raw_response["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text)
                if not isinstance(parsed, dict) or set(parsed) != {"card"}:
                    raise CardClassificationError("response must contain only card")
                card = parsed["card"]
                if card not in {*CARD_IDENTITIES, UNKNOWN_CARD}:
                    raise CardClassificationError("response card is not in the shared card set")
                usage = ProviderUsage.from_usage_metadata(raw_response.get("usageMetadata"))
                candidates = (
                    ()
                    if card == UNKNOWN_CARD
                    else (IdentityCandidate(card=card, probability=1.0),)
                )
                return CardClassificationResult(
                    status="ok",
                    candidates=candidates,
                    usage=usage,
                    latency_ms=_elapsed_ms(started),
                    retry_count=attempt,
                    estimated_cost_usd=_estimate_cost(usage),
                    raw_response=raw_response,
                )
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                last_error = f"Gemini HTTP {error.code}: {body[:1000]}"
                if error.code not in {429, 500, 502, 503, 504}:
                    break
            except (
                CardClassificationError,
                IndexError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ) as error:
                last_error = f"Gemini returned a malformed classification response: {error}"
            except (TimeoutError, urllib.error.URLError, OSError) as error:
                last_error = f"Gemini classification request failed: {error}"
            if attempt < self.max_retries:
                self._sleep(2**attempt)
        return CardClassificationResult(
            status="unavailable",
            latency_ms=_elapsed_ms(started),
            retry_count=attempt,
            error=last_error,
            raw_response=last_raw_response,
        )


class CachedCardClassifier:
    """Cache Gemini classification results by their full transformed-crop request."""

    def __init__(self, classifier: GeminiCardClassifier, cache_dir: str | Path) -> None:
        self.classifier = classifier
        self.cache_dir = Path(cache_dir)
        self.name = classifier.name
        self.version = classifier.version
        self.calibration = classifier.calibration

    def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
        request = CardClassificationRequest(crop_bytes=crop_bytes, model=self.classifier.model)
        path = self.cache_dir / request.request_key[:2] / f"{request.request_key}.json"
        cached = self._load(path, request)
        if cached is not None:
            return replace(cached, cache_hit=True)
        result = self.classifier.classify(request)
        self._store(path, request, result)
        return result

    def _load(
        self, path: Path, request: CardClassificationRequest
    ) -> CardClassificationResult | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(value, dict)
                or value.get("schema_version") != CARD_CLASSIFICATION_CACHE_SCHEMA
                or value.get("request") != request.to_mapping()
                or value.get("request_key") != request.request_key
                or value.get("classifier")
                != {"name": self.classifier.name, "version": self.classifier.version}
            ):
                return None
            candidates = tuple(
                IdentityCandidate.model_validate(item) for item in value["candidates"]
            )
            return CardClassificationResult(
                status=value["status"],
                candidates=candidates,
                usage=ProviderUsage(**value["usage"]),
                latency_ms=value["latency_ms"],
                retry_count=value["retry_count"],
                estimated_cost_usd=value["estimated_cost_usd"],
                error=value["error"],
                raw_response=value["raw_response"],
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _store(
        self, path: Path, request: CardClassificationRequest, result: CardClassificationResult
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": CARD_CLASSIFICATION_CACHE_SCHEMA,
            "request_key": request.request_key,
            "request": request.to_mapping(),
            "classifier": {"name": self.classifier.name, "version": self.classifier.version},
            "status": result.status,
            "candidates": [candidate.model_dump(mode="json") for candidate in result.candidates],
            "usage": result.usage.to_mapping(),
            "latency_ms": result.latency_ms,
            "retry_count": result.retry_count,
            "estimated_cost_usd": result.estimated_cost_usd,
            "error": result.error,
            "raw_response": result.raw_response,
        }
        temporary_path: str | None = None
        try:
            fd, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            with open(fd, "w", encoding="utf-8", closefd=True) as output:
                json.dump(payload, output, sort_keys=True)
                output.write("\n")
            Path(temporary_path).replace(path)
        finally:
            if temporary_path is not None:
                Path(temporary_path).unlink(missing_ok=True)


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, time.monotonic() - started) * 1000.0, 3)


def _estimate_cost(usage: ProviderUsage) -> float:
    return round(usage.input_tokens * 0.75 / 1_000_000 + usage.output_tokens * 3.75 / 1_000_000, 10)


__all__ = [
    "CARD_CLASSIFICATION_CACHE_SCHEMA",
    "CARD_CLASSIFICATION_SCHEMA",
    "UNKNOWN_CARD",
    "CachedCardClassifier",
    "CardClassificationError",
    "CardClassificationRequest",
    "CardClassificationResult",
    "CardIdentityClassifier",
    "GeminiCardClassifier",
]
