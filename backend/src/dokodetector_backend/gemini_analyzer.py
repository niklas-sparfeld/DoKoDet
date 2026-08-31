"""Construct the always-on Gemini table-evidence analyzer."""

from __future__ import annotations

from table_evidence_analyzer import (
    CachedCardClassifier,
    CachedVisibleCardProvider,
    GeminiCardClassifier,
    GeminiVisibleCardProvider,
    LocalVisibleCardProvider,
    TableEvidenceAnalyzer,
    VisibleCardTableAnalyzer,
)

from dokodetector_backend.config import ConfigurationError, Settings


def create_configured_analyzer(settings: Settings) -> TableEvidenceAnalyzer:
    """Create the configured analyzer while retaining Gemini for card identity classification."""

    if not settings.gemini_api_key:
        raise ConfigurationError(
            "GEMINI_API_KEY is required for the visible-card identity classifier in every mode."
        )

    cache_root = settings.evidence_root / "gemini-cache"
    if settings.visible_card_provider == "gemini":
        visible_card_provider = GeminiVisibleCardProvider(
            api_key=settings.gemini_api_key,
            timeout_s=settings.gemini_timeout_seconds,
            max_retries=settings.gemini_max_retries,
        )
    else:
        if settings.visible_card_bundle_path is None:
            raise ConfigurationError(
                "VISIBLE_CARD_BUNDLE_PATH is required when VISIBLE_CARD_PROVIDER=local."
            )
        if settings.visible_card_device is None:
            raise ConfigurationError(
                "VISIBLE_CARD_DEVICE must be set to cpu or mps when VISIBLE_CARD_PROVIDER=local."
            )
        try:
            visible_card_provider = LocalVisibleCardProvider(
                settings.visible_card_bundle_path,
                device=settings.visible_card_device,
            )
        except Exception as error:
            raise ConfigurationError(
                f"The local visible-card provider could not start: {error}"
            ) from error

    provider = CachedVisibleCardProvider(visible_card_provider, cache_root / "visible-cards")
    classifier = CachedCardClassifier(
        GeminiCardClassifier(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_s=settings.gemini_timeout_seconds,
            max_retries=settings.gemini_max_retries,
        ),
        cache_root / "card-classification",
    )
    return VisibleCardTableAnalyzer(
        provider,
        classifier,
        model=settings.gemini_model,
    )


def create_gemini_analyzer(settings: Settings) -> TableEvidenceAnalyzer:
    """Create the legacy Gemini-only analyzer entry point."""

    return create_configured_analyzer(settings)


__all__ = ["create_configured_analyzer", "create_gemini_analyzer"]
