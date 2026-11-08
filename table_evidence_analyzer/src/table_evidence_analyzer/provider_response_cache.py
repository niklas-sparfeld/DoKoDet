"""Bounded lifecycle for disposable provider-response cache files."""

from __future__ import annotations

import fcntl
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


@dataclass(frozen=True, slots=True)
class ProviderResponseCacheRetention:
    """Idle expiry and logical-byte budget for one provider-cache root."""

    max_bytes: int = 4 * 1024 * 1024 * 1024
    idle_seconds: float = 180 * 24 * 60 * 60
    clock: Callable[[], float] = time.time
    sweep_interval_seconds: float = 60 * 60

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_bytes, bool)
            or not isinstance(self.max_bytes, int)
            or self.max_bytes < 1
        ):
            raise ValueError("provider-cache max_bytes must be a positive integer")
        if (
            isinstance(self.idle_seconds, bool)
            or not isinstance(self.idle_seconds, (int, float))
            or self.idle_seconds <= 0
        ):
            raise ValueError("provider-cache idle_seconds must be positive")
        if not callable(self.clock):
            raise ValueError("provider-cache clock must be callable")
        if (
            isinstance(self.sweep_interval_seconds, bool)
            or not isinstance(self.sweep_interval_seconds, (int, float))
            or self.sweep_interval_seconds <= 0
        ):
            raise ValueError("provider-cache sweep_interval_seconds must be positive")


class ProviderResponseCacheLifecycle:
    """Protect active cache reads/writes and prune only disposable response JSON."""

    def __init__(self, root: str | Path, retention: ProviderResponseCacheRetention) -> None:
        self.root = Path(root).expanduser()
        self.retention = retention
        key = str(self.root.resolve())
        with _LOCKS_GUARD:
            self._process_lock = _PROCESS_LOCKS.setdefault(key, threading.RLock())

    @contextmanager
    def access(self) -> Iterator[None]:
        """Hold the shared thread/process lock while accessing a cache entry."""

        self.root.mkdir(parents=True, exist_ok=True)
        with self._process_lock:
            descriptor = os.open(self.root / ".lifecycle.lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def load(self, path: Path, loader: Callable[[], Any]) -> Any:
        """Load one hit under lock, refresh its idle timestamp, and sweep periodically."""

        with self.access():
            now = self.retention.clock()
            if self._expired(path, now):
                path.unlink(missing_ok=True)
            result = loader()
            if result is not None:
                os.utime(path, (now, now), follow_symlinks=False)
            self._sweep_if_due(now)
            return result

    def stored(self) -> None:
        """Apply expiry and the root byte budget after an atomic cache write."""

        with self.access():
            now = self.retention.clock()
            self._prune(now)
            self._mark_sweep(now)

    def store(self, path: Path, writer: Callable[[], None]) -> bool:
        """Publish a cache entry unless that exact stored response is pinned."""

        with self.access():
            if self._is_pinned(path) and path.is_file():
                return False
            writer()
            now = self.retention.clock()
            self._prune(now)
            self._mark_sweep(now)
            return True

    def _expired(self, path: Path, now: float) -> bool:
        if self._is_pinned(path):
            return False
        try:
            age = now - path.stat(follow_symlinks=False).st_mtime
        except OSError:
            return False
        return age >= self.retention.idle_seconds

    @staticmethod
    def _is_pinned(path: Path) -> bool:
        return path.with_name(f"{path.name}.pin").is_file()

    def _sweep_if_due(self, now: float) -> None:
        marker = self.root / ".last-sweep"
        try:
            due = (
                now - marker.stat(follow_symlinks=False).st_mtime
                >= self.retention.sweep_interval_seconds
            )
        except OSError:
            due = True
        if due:
            self._prune(now)
            self._mark_sweep(now)

    def _mark_sweep(self, now: float) -> None:
        marker = self.root / ".last-sweep"
        marker.touch(exist_ok=True)
        os.utime(marker, (now, now), follow_symlinks=False)

    def _prune(self, now: float) -> None:
        files = [
            path for path in self.root.rglob("*.json") if path.is_file() and not path.is_symlink()
        ]
        live: list[tuple[float, Path, int]] = []
        total = 0
        for path in files:
            try:
                stat = path.stat(follow_symlinks=False)
            except OSError:
                continue
            if self._expired(path, now):
                path.unlink(missing_ok=True)
                continue
            if not self._is_pinned(path):
                total += stat.st_size
                live.append((stat.st_mtime, path, stat.st_size))

        for _, path, size in sorted(live):
            if total <= self.retention.max_bytes:
                break
            path.unlink(missing_ok=True)
            total -= size


__all__ = ["ProviderResponseCacheLifecycle", "ProviderResponseCacheRetention"]
