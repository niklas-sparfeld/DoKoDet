"""Locking and retention policy for runtime derived-view cache entries."""

from pathlib import Path
from threading import RLock

from doko_operations.derived_view import DerivedViewCache, DerivedViewCacheRetention

DERIVED_VIEW_CACHE_LOCK = RLock()
DERIVED_VIEW_CACHE_MAX_BYTES = 8 * 1024 * 1024 * 1024
DERIVED_VIEW_CACHE_IDLE_SECONDS = 30 * 24 * 60 * 60


def runtime_derived_view_cache(root: str | Path) -> DerivedViewCache:
    """Return the bounded cache used by the runtime pipeline storage root."""

    return DerivedViewCache(
        root,
        retention=DerivedViewCacheRetention(
            max_bytes=DERIVED_VIEW_CACHE_MAX_BYTES,
            idle_seconds=DERIVED_VIEW_CACHE_IDLE_SECONDS,
        ),
    )


__all__ = [
    "DERIVED_VIEW_CACHE_IDLE_SECONDS",
    "DERIVED_VIEW_CACHE_LOCK",
    "DERIVED_VIEW_CACHE_MAX_BYTES",
    "runtime_derived_view_cache",
]
