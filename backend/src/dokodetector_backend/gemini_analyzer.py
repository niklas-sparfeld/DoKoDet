"""Construct the always-on Gemini table-evidence analyzer."""

from __future__ import annotations

from table_evidence_analyzer import (
    CachedCardClassifier,
    CachedVisibleCardProvider,
    GeminiCardClassifier,
    GeminiVisibleCardProvider,
    TableEvidenceAnalyzer,
    VisibleCardTableAnalyzer,
)

from dokodetector_backend.config import ConfigurationError, Settings


def create_gemini_analyzer(settings: Settings) -> TableEvidenceAnalyzer:
    """Create the backend analyzer without a non-Gemini fallback."""

    if not settings.gemini_api_key:
        raise ConfigurationError(
            "GEMINI_API_KEY is required. The round-analysis backend always uses Gemini."
        )

    cache_root = settings.evidence_root / "gemini-cache"
    provider = CachedVisibleCardProvider(
        GeminiVisibleCardProvider(
            api_key=settings.gemini_api_key,
            timeout_s=settings.gemini_timeout_seconds,
            max_retries=settings.gemini_max_retries,
        ),
        cache_root / "visible-cards",
    )
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


__all__ = ["create_gemini_analyzer"]
