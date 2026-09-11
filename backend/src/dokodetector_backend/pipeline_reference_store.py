"""Durable drafts for maintained recording-pipeline references."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from doko_operations.pipeline_reference import (
    PipelineReferenceContractError,
    PipelineReferenceDraft,
    PipelineReferenceState,
    canonical_reference_draft_bytes,
    canonical_reference_state_bytes,
    parse_reference_draft_bytes,
    parse_reference_state_bytes,
)

from dokodetector_backend.filesystem import atomic_replace_json, contained_path

try:
    from fcntl import LOCK_EX, LOCK_UN, flock
except ImportError:  # pragma: no cover - supported platforms provide fcntl.
    LOCK_EX = LOCK_UN = 0

    def flock(_descriptor: int, _operation: int) -> None:
        return None


LOGGER = logging.getLogger(__name__)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_CONTENT_TYPES = {"events", "visible_cards", "visual_identities"}


class PipelineReferenceStoreError(RuntimeError):
    """A maintained reference could not be read or saved."""


class PipelineReferenceNotFound(PipelineReferenceStoreError):
    """The requested maintained reference does not exist."""


@dataclass(frozen=True, slots=True)
class StoredPipelineReference:
    """The validated state and current draft of one maintained reference."""

    state: PipelineReferenceState
    draft: PipelineReferenceDraft

    def to_mapping(self) -> dict[str, object]:
        return {"state": self.state.to_mapping(), "draft": self.draft.to_mapping()}


def _safe_id(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or _SAFE_ID.fullmatch(value) is None
    ):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def _content_type(value: str) -> str:
    if value not in _CONTENT_TYPES:
        raise ValueError("content_type is not referenceable")
    return value


@contextmanager
def _resource_lock(path: Path, lock: RLock) -> Iterator[None]:
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            flock(handle.fileno(), LOCK_EX)
            try:
                yield
            finally:
                flock(handle.fileno(), LOCK_UN)


class PipelineReferenceStore:
    """Persist one mutable draft and its completed pointer per recording and content type."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self._lock = RLock()

    def reference_root(self, recording_id: str, content_type: str) -> Path:
        _safe_id(recording_id, "recording_id")
        _content_type(content_type)
        return contained_path(self.root, Path(recording_id) / content_type)

    def state_path(self, recording_id: str, content_type: str) -> Path:
        return self.reference_root(recording_id, content_type) / "state.json"

    def draft_path(self, recording_id: str, content_type: str) -> Path:
        return self.reference_root(recording_id, content_type) / "draft.json"

    def command_path(self, recording_id: str, content_type: str) -> Path:
        """Return the replay ledger for optimistic draft commands."""

        return self.reference_root(recording_id, content_type) / "commands.json"

    def get(self, recording_id: str, content_type: str) -> StoredPipelineReference | None:
        try:
            state_path = self.state_path(recording_id, content_type)
            draft_path = self.draft_path(recording_id, content_type)
        except (TypeError, ValueError):
            return None
        if not state_path.is_file() and not draft_path.exists():
            return None
        with _resource_lock(self._lock_path(recording_id, content_type), self._lock):
            try:
                return self.read_locked(recording_id, content_type)
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                self._log_invalid(state_path, error)
                return None

    def require(self, recording_id: str, content_type: str) -> StoredPipelineReference:
        reference = self.get(recording_id, content_type)
        if reference is None:
            raise PipelineReferenceNotFound(
                f"The maintained reference was not found: {recording_id}/{content_type}"
            )
        return reference

    @contextmanager
    def locked(self, recording_id: str, content_type: str) -> Iterator[None]:
        """Hold a resource lock while a service performs a validated mutation."""

        _content_type(content_type)
        _safe_id(recording_id, "recording_id")
        with _resource_lock(self._lock_path(recording_id, content_type), self._lock):
            yield

    def read_locked(self, recording_id: str, content_type: str) -> StoredPipelineReference:
        state_path = self.state_path(recording_id, content_type)
        draft_path = self.draft_path(recording_id, content_type)
        if not state_path.is_file() or not draft_path.is_file():
            raise PipelineReferenceNotFound(
                f"The maintained reference was not found: {recording_id}/{content_type}"
            )
        state_raw = state_path.read_bytes()
        draft_raw = draft_path.read_bytes()
        state = parse_reference_state_bytes(state_raw)
        draft = parse_reference_draft_bytes(draft_raw)
        if state_raw != canonical_reference_state_bytes(state):
            raise PipelineReferenceContractError("pipeline reference state is not canonical JSON")
        if draft_raw != canonical_reference_draft_bytes(draft):
            raise PipelineReferenceContractError("pipeline reference draft is not canonical JSON")
        if (
            state.recording_id != recording_id
            or state.content_type != content_type
            or draft.recording_id != recording_id
            or draft.content_type != content_type
            or state.draft_revision != draft.revision
            or state.source_revision_id != draft.source_revision_id
        ):
            raise PipelineReferenceContractError("pipeline reference state and draft disagree")
        return StoredPipelineReference(state=state, draft=draft)

    def write_locked(self, reference: StoredPipelineReference) -> StoredPipelineReference:
        state_path = self.state_path(reference.state.recording_id, reference.state.content_type)
        draft_path = self.draft_path(reference.draft.recording_id, reference.draft.content_type)
        if reference.state.draft_revision != reference.draft.revision:
            raise PipelineReferenceContractError("pipeline reference revision does not match draft")
        if reference.state.source_revision_id != reference.draft.source_revision_id:
            raise PipelineReferenceContractError("pipeline reference source does not match draft")
        state_bytes = canonical_reference_state_bytes(reference.state)
        draft_bytes = canonical_reference_draft_bytes(reference.draft)
        atomic_replace_json(
            draft_path,
            draft_bytes,
            validate=lambda raw: _assert_bytes(raw, draft_bytes, "pipeline reference draft"),
        )
        atomic_replace_json(
            state_path,
            state_bytes,
            validate=lambda raw: _assert_bytes(raw, state_bytes, "pipeline reference state"),
        )
        # Both documents were written from the validated reference and each atomic write checks
        # the exact bytes that it published. Re-reading and parsing the complete draft here adds a
        # second O(n) pass for every review command, which is costly for large identity drafts.
        return reference

    def read_commands_locked(self, recording_id: str, content_type: str) -> dict[str, str]:
        """Read command digests while the reference lock is held."""

        path = self.command_path(recording_id, content_type)
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise PipelineReferenceStoreError(
                "the pipeline reference command ledger is invalid"
            ) from error
        if not isinstance(value, dict) or any(
            not isinstance(key, str) or not isinstance(digest, str) for key, digest in value.items()
        ):
            raise PipelineReferenceStoreError("the pipeline reference command ledger is invalid")
        return dict(value)

    def write_commands_locked(
        self,
        recording_id: str,
        content_type: str,
        commands: dict[str, str],
    ) -> None:
        """Durably record command digests while the reference lock is held."""

        atomic_replace_json(self.command_path(recording_id, content_type), commands)

    def _lock_path(self, recording_id: str, content_type: str) -> Path:
        return self.reference_root(recording_id, content_type).parent / (
            f".{self.reference_root(recording_id, content_type).name}.lock"
        )

    @staticmethod
    def _log_invalid(path: Path, error: BaseException) -> None:
        LOGGER.warning(
            "pipeline_reference_catalog_skipped",
            extra={"path": str(path), "reason": str(error)},
        )


def _assert_bytes(raw: bytes, expected: bytes, context: str) -> None:
    if raw != expected:
        raise PipelineReferenceContractError(f"{context} is not canonical JSON")


__all__ = [
    "PipelineReferenceNotFound",
    "PipelineReferenceStore",
    "PipelineReferenceStoreError",
    "StoredPipelineReference",
]
