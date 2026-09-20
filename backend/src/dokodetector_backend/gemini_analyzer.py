"""Construct the always-on Gemini table-evidence analyzer."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

from table_evidence_analyzer import (
    CachedCardClassifier,
    CachedVisibleCardProvider,
    DinoV3IdentityClassifier,
    GeminiCardClassifier,
    GeminiVisibleCardProvider,
    LocalVisibleCardCascadeProvider,
    LocalVisibleCardProvider,
    LocalVisibleCardSegmentationProvider,
    TableEvidenceAnalyzer,
    VisibleCardTableAnalyzer,
    get_shared_gemini_request_limiter,
)

from dokodetector_backend.config import ConfigurationError, Settings

_RFDETR_SEGMENTATION_BUNDLE_SCHEMA = "rfdetr-segmentation-bundle/v1"
_RFDETR_CASCADE_BUNDLE_SCHEMA = "rfdetr-cascade-bundle/v1"


class LazyProcessorRegistry(Mapping[str, Any]):
    """Construct configured processor implementations only when they are selected."""

    def __init__(self, factories: Mapping[str, Callable[[], Any]]) -> None:
        self._factories = dict(factories)
        self._instances: dict[str, Any] = {}

    def __getitem__(self, key: str) -> Any:
        if key not in self._factories:
            raise KeyError(key)
        if key not in self._instances:
            try:
                self._instances[key] = self._factories[key]()
            except ConfigurationError:
                raise
            except Exception as error:
                raise ConfigurationError(f"The {key} processor could not start: {error}") from error
        return self._instances[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._factories)

    def __len__(self) -> int:
        return len(self._factories)

    def register(self, key: str, processor: Any) -> None:
        """Override one lazy option with an explicitly injected processor."""

        self._factories[key] = lambda: processor
        self._instances[key] = processor


def _create_visible_card_provider(
    settings: Settings,
    provider_name: str,
    *,
    cache_root: Any,
    request_limiter: Any,
) -> Any:
    if provider_name == "gemini":
        if not settings.gemini_api_key:
            raise ConfigurationError(
                "GEMINI_API_KEY is required when the Cloud visible-card processor is selected."
            )
        provider = GeminiVisibleCardProvider(
            api_key=settings.gemini_api_key,
            timeout_s=settings.gemini_timeout_seconds,
            max_retries=settings.gemini_max_retries,
            request_limiter=request_limiter,
        )
    elif provider_name == "local":
        if settings.visible_card_bundle_path is None:
            raise ConfigurationError(
                "VISIBLE_CARD_BUNDLE_PATH is required when the Local visible-card "
                "processor is selected."
            )
        if settings.visible_card_device is None:
            raise ConfigurationError(
                "VISIBLE_CARD_DEVICE must be set to cpu or mps when the Local "
                "visible-card processor is selected."
            )
        try:
            provider = LocalVisibleCardProvider(
                settings.visible_card_bundle_path,
                device=settings.visible_card_device,
            )
        except Exception as error:
            raise ConfigurationError(
                f"The local visible-card provider could not start: {error}"
            ) from error
    elif provider_name == "local-rfdetr-segmentation":
        if settings.visible_card_bundle_path is None:
            raise ConfigurationError(
                "VISIBLE_CARD_BUNDLE_PATH is required when the Local visible-card "
                "processor is selected."
            )
        if settings.visible_card_device is None:
            raise ConfigurationError(
                "VISIBLE_CARD_DEVICE must be set to cpu or mps when the Local "
                "visible-card processor is selected."
            )
        try:
            provider = LocalVisibleCardSegmentationProvider(
                settings.visible_card_bundle_path,
                device=settings.visible_card_device,
            )
        except Exception as error:
            raise ConfigurationError(
                f"The local visible-card provider could not start: {error}"
            ) from error
    elif provider_name == "local-rfdetr-cascade":
        if settings.visible_card_bundle_path is None:
            raise ConfigurationError(
                "VISIBLE_CARD_BUNDLE_PATH is required when the Local RF-DETR cascade "
                "processor is selected."
            )
        if settings.visible_card_device is None:
            raise ConfigurationError(
                "VISIBLE_CARD_DEVICE must be set to cpu or mps when the Local RF-DETR "
                "cascade processor is selected."
            )
        try:
            provider = LocalVisibleCardCascadeProvider(
                settings.visible_card_bundle_path,
                device=settings.visible_card_device,
            )
        except Exception as error:
            raise ConfigurationError(
                f"The local RF-DETR cascade provider could not start: {error}"
            ) from error
    else:
        raise ConfigurationError(f"Unsupported visible-card provider: {provider_name}.")
    return CachedVisibleCardProvider(provider, cache_root / "visible-cards")


def _create_identity_classifier(
    settings: Settings,
    provider_name: str,
    *,
    cache_root: Any,
    request_limiter: Any,
) -> Any:
    if provider_name == "gemini":
        if not settings.gemini_api_key:
            raise ConfigurationError(
                "GEMINI_API_KEY is required when the Cloud identity processor is selected."
            )
        return CachedCardClassifier(
            GeminiCardClassifier(
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
                timeout_s=settings.gemini_timeout_seconds,
                max_retries=settings.gemini_max_retries,
                request_limiter=request_limiter,
            ),
            cache_root / "card-classification",
        )
    if provider_name == "local":
        if settings.visible_card_identity_bundle_path is None:
            raise ConfigurationError(
                "VISIBLE_CARD_IDENTITY_BUNDLE_PATH is required when the Local "
                "identity processor is selected."
            )
        if settings.visible_card_identity_device is None:
            raise ConfigurationError(
                "VISIBLE_CARD_IDENTITY_DEVICE must be set to cpu or mps when the "
                "Local identity processor is selected."
            )
        try:
            return DinoV3IdentityClassifier(
                settings.visible_card_identity_bundle_path,
                device=settings.visible_card_identity_device,
            )
        except Exception as error:
            raise ConfigurationError(
                f"The local visible-card identity classifier could not start: {error}"
            ) from error
    raise ConfigurationError(f"Unsupported identity provider: {provider_name}.")


def _configured_local_visible_provider(settings: Settings) -> str:
    """Select the local adapter that matches the configured bundle."""

    if settings.visible_card_provider in {
        "local",
        "local-rfdetr-segmentation",
        "local-rfdetr-cascade",
    }:
        return settings.visible_card_provider
    bundle_path = settings.visible_card_bundle_path
    if bundle_path is not None:
        try:
            manifest = json.loads(
                (Path(bundle_path).expanduser() / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            manifest = None
        if (
            isinstance(manifest, dict)
            and manifest.get("schema_version") == _RFDETR_SEGMENTATION_BUNDLE_SCHEMA
        ):
            return "local-rfdetr-segmentation"
        if (
            isinstance(manifest, dict)
            and manifest.get("schema_version") == _RFDETR_CASCADE_BUNDLE_SCHEMA
        ):
            return "local-rfdetr-cascade"
    return "local"


def create_configured_processor_registries(
    settings: Settings,
) -> tuple[LazyProcessorRegistry, LazyProcessorRegistry]:
    """Create independently selectable visible-card and identity processors."""

    cache_root = settings.evidence_root / "gemini-cache"
    request_limiter = get_shared_gemini_request_limiter(settings.gemini_max_concurrent_requests)
    local_visible_provider = _configured_local_visible_provider(settings)
    visible = LazyProcessorRegistry(
        {
            "cloud": lambda: _create_visible_card_provider(
                settings,
                "gemini",
                cache_root=cache_root,
                request_limiter=request_limiter,
            ),
            "gemini": lambda: _create_visible_card_provider(
                settings,
                "gemini",
                cache_root=cache_root,
                request_limiter=request_limiter,
            ),
            "local": lambda: _create_visible_card_provider(
                settings,
                local_visible_provider,
                cache_root=cache_root,
                request_limiter=request_limiter,
            ),
            "local-rfdetr-segmentation": lambda: _create_visible_card_provider(
                settings,
                "local-rfdetr-segmentation",
                cache_root=cache_root,
                request_limiter=request_limiter,
            ),
            "local-rfdetr-cascade": lambda: _create_visible_card_provider(
                settings,
                "local-rfdetr-cascade",
                cache_root=cache_root,
                request_limiter=request_limiter,
            ),
        }
    )
    identities = LazyProcessorRegistry(
        {
            "cloud": lambda: _create_identity_classifier(
                settings,
                "gemini",
                cache_root=cache_root,
                request_limiter=request_limiter,
            ),
            "gemini": lambda: _create_identity_classifier(
                settings,
                "gemini",
                cache_root=cache_root,
                request_limiter=request_limiter,
            ),
            "local": lambda: _create_identity_classifier(
                settings,
                "local",
                cache_root=cache_root,
                request_limiter=request_limiter,
            ),
        }
    )
    return visible, identities


def create_configured_analyzer(settings: Settings) -> TableEvidenceAnalyzer:
    """Create the analyzer with independent detector and identity selections."""

    cache_root = settings.evidence_root / "gemini-cache"
    request_limiter = get_shared_gemini_request_limiter(settings.gemini_max_concurrent_requests)
    provider = _create_visible_card_provider(
        settings,
        settings.visible_card_provider,
        cache_root=cache_root,
        request_limiter=request_limiter,
    )
    classifier = _create_identity_classifier(
        settings,
        settings.visible_card_identity_classifier,
        cache_root=cache_root,
        request_limiter=request_limiter,
    )
    return VisibleCardTableAnalyzer(
        provider,
        classifier,
        model=settings.gemini_model,
        max_concurrent_requests=settings.gemini_max_concurrent_requests,
    )


def create_gemini_analyzer(settings: Settings) -> TableEvidenceAnalyzer:
    """Create the legacy Gemini-only analyzer entry point."""

    return create_configured_analyzer(settings)


__all__ = [
    "LazyProcessorRegistry",
    "create_configured_analyzer",
    "create_configured_processor_registries",
    "create_gemini_analyzer",
]
