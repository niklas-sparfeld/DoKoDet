"""Construct the configured table-evidence analyzer."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from threading import Lock
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
_RFDETR_CASCADE_VARIANTS = frozenset(
    {
        "local-rfdetr-cascade",
        "local-rfdetr-cascade-0068",
        "local-rfdetr-cascade-0070",
    }
)


class LazyProcessorRegistry(Mapping[str, Any]):
    """Construct configured processor implementations only when they are selected."""

    def __init__(self, factories: Mapping[str, Callable[[], Any]]) -> None:
        self._factories = dict(factories)
        self._instances: dict[str, Any] = {}
        self._lock = Lock()

    def __getitem__(self, key: str) -> Any:
        if key not in self._factories:
            raise KeyError(key)
        instance = self._instances.get(key)
        if instance is None:
            with self._lock:
                instance = self._instances.get(key)
                if instance is None:
                    try:
                        instance = self._factories[key]()
                    except ConfigurationError:
                        raise
                    except Exception as error:
                        raise ConfigurationError(
                            f"The {key} processor could not start: {error}"
                        ) from error
                    self._instances[key] = instance
        return instance

    def __iter__(self) -> Iterator[str]:
        return iter(self._factories)

    def __len__(self) -> int:
        return len(self._factories)

    def register(self, key: str, processor: Any) -> None:
        """Override one lazy option with an explicitly injected processor."""

        with self._lock:
            self._factories[key] = lambda: processor
            self._instances[key] = processor


class LazyConfiguredAnalyzer:
    """Build the configured analyzer only when an analysis needs it."""

    name = VisibleCardTableAnalyzer.name
    version = VisibleCardTableAnalyzer.version

    def __init__(
        self,
        settings: Settings,
        visible_card_providers: LazyProcessorRegistry,
        visible_card_identity_classifiers: LazyProcessorRegistry,
    ) -> None:
        self._settings = settings
        self._visible_card_providers = visible_card_providers
        self._visible_card_identity_classifiers = visible_card_identity_classifiers
        self._analyzer: TableEvidenceAnalyzer | None = None
        self._lock = Lock()

    def _get(self) -> TableEvidenceAnalyzer:
        analyzer = self._analyzer
        if analyzer is None:
            with self._lock:
                analyzer = self._analyzer
                if analyzer is None:
                    provider = self._visible_card_providers[self._settings.visible_card_provider]
                    classifier = self._visible_card_identity_classifiers[
                        self._settings.visible_card_identity_classifier
                    ]
                    analyzer = VisibleCardTableAnalyzer(
                        provider,
                        classifier,
                        model=self._settings.gemini_model,
                        max_concurrent_requests=self._settings.gemini_max_concurrent_requests,
                    )
                    self._analyzer = analyzer
        return analyzer

    @property
    def provider(self) -> Any:
        """Return the configured detector, loading the analyzer on first access."""

        return self._get().provider

    @property
    def classifier(self) -> Any:
        """Return the configured identity classifier, loading it on first access."""

        return self._get().classifier

    def analyze(self, evidence: Any) -> Any:
        """Analyze evidence with the shared, on-demand analyzer instance."""

        return self._get().analyze(evidence)


def validate_configured_processor_settings(settings: Settings) -> None:
    """Validate cheap local processor settings without loading model weights."""

    if settings.visible_card_provider != "gemini":
        if _bundle_path_for_provider(settings, settings.visible_card_provider) is None:
            raise ConfigurationError(
                f"{_bundle_setting_name(settings.visible_card_provider)} is required when the "
                f"{settings.visible_card_provider} visible-card processor is selected."
            )
        if settings.visible_card_device is None:
            raise ConfigurationError(
                "VISIBLE_CARD_DEVICE must be set to cpu or mps when the Local visible-card "
                "processor is selected."
            )

    if settings.visible_card_identity_classifier == "local":
        if settings.visible_card_identity_bundle_path is None:
            raise ConfigurationError(
                "VISIBLE_CARD_IDENTITY_BUNDLE_PATH is required when the Local identity "
                "processor is selected."
            )
        if settings.visible_card_identity_device is None:
            raise ConfigurationError(
                "VISIBLE_CARD_IDENTITY_DEVICE must be set to cpu or mps when the Local "
                "identity processor is selected."
            )


class _UnconfiguredGeminiVisibleCardProvider:
    """Stand in for Gemini until a Cloud request needs the API key."""

    name = "gemini"
    version = "gemini-visible-cards-v1"

    def propose(self, request: Any) -> Any:
        raise ConfigurationError(
            "GEMINI_API_KEY is required when the Cloud visible-card processor is selected."
        )


class _UnconfiguredGeminiCardClassifier:
    """Stand in for Gemini identity until a Cloud request needs the API key."""

    name = "gemini"
    version = "gemini-card-classification/v2"
    calibration = "uncalibrated"

    def __init__(self, *, model: str) -> None:
        self.model = model

    def classify_ppm(self, crop_bytes: bytes) -> Any:
        raise ConfigurationError(
            "GEMINI_API_KEY is required when the Cloud identity processor is selected."
        )

    def classify(self, request: Any) -> Any:
        raise ConfigurationError(
            "GEMINI_API_KEY is required when the Cloud identity processor is selected."
        )


def _create_visible_card_provider(
    settings: Settings,
    provider_name: str,
    *,
    cache_root: Any,
    request_limiter: Any,
) -> Any:
    if provider_name == "gemini":
        if not settings.gemini_api_key:
            provider = _UnconfiguredGeminiVisibleCardProvider()
        else:
            provider = GeminiVisibleCardProvider(
                api_key=settings.gemini_api_key,
                timeout_s=settings.gemini_timeout_seconds,
                max_retries=settings.gemini_max_retries,
                request_limiter=request_limiter,
            )
    elif provider_name in {
        "local",
        "local-rfdetr-segmentation",
        *_RFDETR_CASCADE_VARIANTS,
    }:
        bundle_path = _bundle_path_for_provider(settings, provider_name)
        if bundle_path is None:
            raise ConfigurationError(
                f"{_bundle_setting_name(provider_name)} is required when the "
                f"{provider_name} visible-card processor is selected."
            )
        if settings.visible_card_device is None:
            raise ConfigurationError(
                "VISIBLE_CARD_DEVICE must be set to cpu or mps when the Local "
                "visible-card processor is selected."
            )
        try:
            provider_class = {
                "local": LocalVisibleCardProvider,
                "local-rfdetr-segmentation": LocalVisibleCardSegmentationProvider,
                "local-rfdetr-cascade": LocalVisibleCardCascadeProvider,
                "local-rfdetr-cascade-0068": LocalVisibleCardCascadeProvider,
                "local-rfdetr-cascade-0070": LocalVisibleCardCascadeProvider,
            }[provider_name]
            provider_kwargs: dict[str, Any] = {"device": settings.visible_card_device}
            if (
                provider_name in _RFDETR_CASCADE_VARIANTS
                and provider_name != "local-rfdetr-cascade"
            ):
                provider_kwargs["provider_name"] = provider_name
            provider = provider_class(bundle_path, **provider_kwargs)
        except Exception as error:
            raise ConfigurationError(
                f"The {provider_name} visible-card provider could not start: {error}"
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
            classifier: Any = _UnconfiguredGeminiCardClassifier(model=settings.gemini_model)
        else:
            classifier = GeminiCardClassifier(
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
                timeout_s=settings.gemini_timeout_seconds,
                max_retries=settings.gemini_max_retries,
                request_limiter=request_limiter,
            )
        return CachedCardClassifier(
            classifier,
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
        *_RFDETR_CASCADE_VARIANTS,
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
    if settings.visible_card_cascade_bundle_path is not None:
        return "local-rfdetr-cascade"
    if settings.visible_card_segmentation_bundle_path is not None:
        return "local-rfdetr-segmentation"
    return "local"


def _bundle_path_for_provider(settings: Settings, provider_name: str) -> Path | None:
    if provider_name == "local-rfdetr-segmentation":
        return settings.visible_card_segmentation_bundle_path or settings.visible_card_bundle_path
    if provider_name == "local-rfdetr-cascade":
        return settings.visible_card_cascade_bundle_path or settings.visible_card_bundle_path
    if provider_name == "local-rfdetr-cascade-0068":
        return settings.visible_card_cascade_0068_bundle_path
    if provider_name == "local-rfdetr-cascade-0070":
        return settings.visible_card_cascade_0070_bundle_path
    return settings.visible_card_bundle_path


def _bundle_setting_name(provider_name: str) -> str:
    if provider_name == "local-rfdetr-segmentation":
        return "VISIBLE_CARD_SEGMENTATION_BUNDLE_PATH"
    if provider_name == "local-rfdetr-cascade":
        return "VISIBLE_CARD_CASCADE_BUNDLE_PATH"
    if provider_name == "local-rfdetr-cascade-0068":
        return "VISIBLE_CARD_CASCADE_0068_BUNDLE_PATH"
    if provider_name == "local-rfdetr-cascade-0070":
        return "VISIBLE_CARD_CASCADE_0070_BUNDLE_PATH"
    return "VISIBLE_CARD_BUNDLE_PATH"


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
            "local-rfdetr-cascade-0068": lambda: _create_visible_card_provider(
                settings,
                "local-rfdetr-cascade-0068",
                cache_root=cache_root,
                request_limiter=request_limiter,
            ),
            "local-rfdetr-cascade-0070": lambda: _create_visible_card_provider(
                settings,
                "local-rfdetr-cascade-0070",
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


def create_lazy_configured_analyzer(
    settings: Settings,
    visible_card_providers: LazyProcessorRegistry,
    visible_card_identity_classifiers: LazyProcessorRegistry,
) -> LazyConfiguredAnalyzer:
    """Create an analyzer facade that shares the processor registries."""

    return LazyConfiguredAnalyzer(
        settings,
        visible_card_providers,
        visible_card_identity_classifiers,
    )


def create_gemini_analyzer(settings: Settings) -> TableEvidenceAnalyzer:
    """Create the legacy Gemini-only analyzer entry point."""

    return create_configured_analyzer(settings)


__all__ = [
    "LazyConfiguredAnalyzer",
    "LazyProcessorRegistry",
    "create_configured_analyzer",
    "create_configured_processor_registries",
    "create_gemini_analyzer",
    "create_lazy_configured_analyzer",
    "validate_configured_processor_settings",
]
