"""Explicit request and provider adapter for visual card identity classification."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .card_classification import (
    CardClassificationError,
    CardClassificationResult,
    CardIdentityClassifier,
)

VISUAL_IDENTITY_ADAPTER_SCHEMA = "visual-identity-classifier-adapter/v1"


@dataclass(frozen=True, slots=True)
class VisualIdentityRequest:
    """The frozen request sent to one visual identity provider."""

    card_id: str
    provider: str
    model: str
    crop_bytes: bytes

    def __post_init__(self) -> None:
        for value, field in (
            (self.card_id, "card_id"),
            (self.provider, "provider"),
            (self.model, "model"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise CardClassificationError(f"visual identity {field} must be non-empty")
        if not isinstance(self.crop_bytes, bytes) or not self.crop_bytes:
            raise CardClassificationError("visual identity crop bytes must be non-empty")

    @property
    def crop_sha256(self) -> str:
        return hashlib.sha256(self.crop_bytes).hexdigest()

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": VISUAL_IDENTITY_ADAPTER_SCHEMA,
            "card_id": self.card_id,
            "provider": self.provider,
            "model": self.model,
            "crop_sha256": self.crop_sha256,
        }


@runtime_checkable
class VisualIdentityClassifierProvider(Protocol):
    """Provider boundary with a provider-bound request."""

    name: str
    version: str
    model: str

    def classify(self, request: VisualIdentityRequest) -> CardClassificationResult:
        """Classify one exact crop without changing the frozen provider."""


class CardIdentityClassifierProvider:
    """Adapt the existing local and Gemini classifiers to the request boundary."""

    def __init__(self, classifier: CardIdentityClassifier) -> None:
        if not isinstance(classifier, CardIdentityClassifier):
            raise CardClassificationError(
                "the visual identity classifier does not implement classify_ppm"
            )
        name = getattr(classifier, "name", None)
        version = getattr(classifier, "version", None)
        if not isinstance(name, str) or not name:
            raise CardClassificationError("the visual identity classifier has no name")
        if not isinstance(version, str) or not version:
            raise CardClassificationError("the visual identity classifier has no version")
        self.classifier = classifier
        self.name = name
        self.version = version
        self.model = _model_name(classifier, fallback=name)

    def classify(self, request: VisualIdentityRequest) -> CardClassificationResult:
        if request.provider != self.name:
            raise CardClassificationError(
                f"request provider {request.provider!r} does not match {self.name!r}"
            )
        if request.model != self.model:
            raise CardClassificationError(
                f"request model {request.model!r} does not match {self.model!r}"
            )
        result = self.classifier.classify_ppm(request.crop_bytes)
        if not isinstance(result, CardClassificationResult):
            raise CardClassificationError(
                "the visual identity classifier returned an invalid result"
            )
        return result


def _model_name(classifier: Any, *, fallback: str) -> str:
    model = getattr(classifier, "model", None)
    if isinstance(model, str) and model:
        return model
    nested = getattr(classifier, "classifier", None)
    model = getattr(nested, "model", None)
    if isinstance(model, str) and model:
        return model
    bundle_identity = getattr(classifier, "bundle_identity", None)
    if isinstance(bundle_identity, dict):
        model_id = bundle_identity.get("model_id")
        if isinstance(model_id, str) and model_id:
            return model_id
    return fallback


__all__ = [
    "VISUAL_IDENTITY_ADAPTER_SCHEMA",
    "CardIdentityClassifierProvider",
    "VisualIdentityClassifierProvider",
    "VisualIdentityRequest",
]
