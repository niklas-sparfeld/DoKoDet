"""Shared concurrency control for interactive Gemini requests."""

from __future__ import annotations

import time
from contextlib import contextmanager
from threading import BoundedSemaphore, Lock
from typing import Iterator


class GeminiRequestLimiter:
    """Bound the number of in-flight interactive Gemini HTTP requests."""

    def __init__(self, max_concurrent_requests: int) -> None:
        if (
            isinstance(max_concurrent_requests, bool)
            or not isinstance(max_concurrent_requests, int)
            or max_concurrent_requests < 1
        ):
            raise ValueError("max_concurrent_requests must be a positive integer")
        self.max_concurrent_requests = max_concurrent_requests
        self._semaphore = BoundedSemaphore(max_concurrent_requests)

    @contextmanager
    def request_slot(self) -> Iterator[float]:
        """Acquire one HTTP slot and yield the wait time in milliseconds."""

        started = time.monotonic()
        self._semaphore.acquire()
        wait_ms = round(max(0.0, time.monotonic() - started) * 1000.0, 3)
        try:
            yield wait_ms
        finally:
            self._semaphore.release()


_shared_limiter: GeminiRequestLimiter | None = None
_shared_limiter_lock = Lock()


def get_shared_gemini_request_limiter(max_concurrent_requests: int = 4) -> GeminiRequestLimiter:
    """Return the process-wide limiter for the configured interactive request cap."""

    global _shared_limiter
    with _shared_limiter_lock:
        if (
            _shared_limiter is None
            or _shared_limiter.max_concurrent_requests != max_concurrent_requests
        ):
            _shared_limiter = GeminiRequestLimiter(max_concurrent_requests)
        return _shared_limiter


__all__ = ["GeminiRequestLimiter", "get_shared_gemini_request_limiter"]
