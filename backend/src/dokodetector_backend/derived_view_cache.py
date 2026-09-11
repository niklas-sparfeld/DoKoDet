"""Process-local locking for derived-view cache reads and writes."""

from threading import RLock

DERIVED_VIEW_CACHE_LOCK = RLock()


__all__ = ["DERIVED_VIEW_CACHE_LOCK"]
