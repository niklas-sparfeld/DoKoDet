"""Shared filesystem rules for pipeline persistence owners."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from doko_operations.pipeline_data import PipelineDataContractError

try:
    from fcntl import LOCK_EX, LOCK_UN, flock
except ImportError:  # pragma: no cover - supported backends run on macOS and Linux.
    LOCK_EX = LOCK_UN = 0

    def flock(_descriptor: int, _operation: int) -> None:
        return None


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_UTC_ZERO = timezone.utc


class PipelineStoreError(RuntimeError):
    """The canonical pipeline resource could not be read or written."""


class PipelineConflict(PipelineStoreError):
    """A resource ID or optimistic pointer is already used by different content."""


class PipelineNotFound(PipelineStoreError, ValueError):
    """The requested pipeline resource does not exist."""


class PipelineStateError(PipelineStoreError, ValueError):
    """A run state transition or state invariant is invalid."""


class PipelineSelectionConflict(PipelineConflict):
    """A selection update used an old expected revision."""


@dataclass(frozen=True, slots=True)
class PipelineRuntimeStorage:
    """Separate durable pipeline records from rebuildable derived views."""

    runtime_root: Path
    operations_root: Path

    def __init__(self, runtime_root: Path | str, operations_root: Path | str | None = None) -> None:
        object.__setattr__(self, "runtime_root", Path(runtime_root).expanduser().resolve())
        object.__setattr__(
            self,
            "operations_root",
            (
                Path(operations_root).expanduser().resolve()
                if operations_root is not None
                else Path(runtime_root).expanduser().resolve()
            ),
        )

    @property
    def pipeline_root(self) -> Path:
        return self.operations_root / "pipeline"

    @property
    def derived_views_root(self) -> Path:
        return self.runtime_root / "pipeline" / "derived-views"

    @property
    def revisions_root(self) -> Path:
        return self.pipeline_root / "revisions"

    @property
    def runs_root(self) -> Path:
        return self.pipeline_root / "runs"

    @property
    def selections_root(self) -> Path:
        return self.pipeline_root / "selections"


def _storage(value: PipelineRuntimeStorage | Path | str) -> PipelineRuntimeStorage:
    return value if isinstance(value, PipelineRuntimeStorage) else PipelineRuntimeStorage(value)


def _safe_id(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or _SAFE_ID.fullmatch(value) is None
    ):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def _safe_content_type(value: str) -> str:
    if value not in {
        "events",
        "visible_cards",
        "visual_identities",
        "table_observations",
        "card_scene_proposals",
    }:
        raise ValueError("content_type is unsupported")
    return value


def _canonical_timestamp(value: datetime | str | None) -> str:
    if value is None:
        parsed = datetime.now(_UTC_ZERO)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError as error:
            raise ValueError("timestamp must be ISO-8601") from error
    else:
        raise TypeError("timestamp must be a datetime or ISO-8601 string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("timestamp must use UTC")
    return parsed.astimezone(_UTC_ZERO).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _timestamp_value(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)


@contextmanager
def _process_lock(path: Path, thread_lock: RLock) -> Iterator[None]:
    """Hold one in-process and one local-process lock for a resource."""

    with thread_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            flock(handle.fileno(), LOCK_EX)
            try:
                yield
            finally:
                flock(handle.fileno(), LOCK_UN)


def _parse_json_object(raw: bytes, context: str) -> dict[str, Any]:
    """Parse one strict JSON object for the split processor-run storage format."""

    def reject_constant(value: str) -> None:
        raise PipelineDataContractError(f"{context} contains a non-finite JSON number: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PipelineDataContractError(f"{context} contains duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineDataContractError(f"{context} is not valid JSON") from error
    if not isinstance(value, dict):
        raise PipelineDataContractError(f"{context} must be a JSON object")
    return value


def _strict_json_file(raw: bytes, expected: bytes, context: str) -> None:
    if raw != expected:
        raise PipelineDataContractError(f"{context} is not canonical JSON")


def _parse_json_object(raw: bytes, context: str) -> dict[str, Any]:
    """Parse one strict JSON object for the split processor-run storage format."""

    def reject_constant(value: str) -> None:
        raise PipelineDataContractError(f"{context} contains a non-finite JSON number: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PipelineDataContractError(f"{context} contains duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineDataContractError(f"{context} is not valid JSON") from error
    if not isinstance(value, dict):
        raise PipelineDataContractError(f"{context} must be a JSON object")
    return value
