"""Durable storage for independent visible-card reviews."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from threading import RLock, local
from typing import Any

from doko_operations.pipeline_reference import (
    canonical_json_bytes,
    canonical_reference_draft_bytes,
    canonical_reference_state_bytes,
    parse_reference_draft_bytes,
    parse_reference_state_bytes,
)

from dokodetector_backend.filesystem import (
    atomic_write_json,
    commit_staged_directory,
    contained_path,
    staging_directory,
)
from dokodetector_backend.pipeline_reference_store import (
    PipelineReferenceNotFound,
    PipelineReferenceStore,
    StoredPipelineReference,
)

try:
    from fcntl import LOCK_EX, LOCK_UN, flock
except ImportError:  # pragma: no cover - supported platforms provide fcntl.
    LOCK_EX = LOCK_UN = 0

    def flock(_descriptor: int, _operation: int) -> None:
        return None


LOGGER = logging.getLogger(__name__)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SOURCES = frozenset({"visible_regions", "card_scenes"})
_LEGACY_REVIEW_ID = "legacy-visible-cards"


class VisibleCardReviewStoreError(RuntimeError):
    """A visible-card review could not be read or written safely."""


class VisibleCardReviewConflict(VisibleCardReviewStoreError):
    """A review ID already exists or a review record conflicts with its path."""


@dataclass(frozen=True, slots=True)
class StoredVisibleCardReview:
    """One review's metadata, editable draft, and isolated command ledger."""

    review_id: str
    recording_id: str
    status: str
    source: str
    lineage: dict[str, Any]
    created_at: str
    updated_at: str
    reference: StoredPipelineReference
    commands: dict[str, str]
    legacy: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "recording_id": self.recording_id,
            "status": self.status,
            "source": self.source,
            "lineage": self.lineage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "state": self.reference.state.to_mapping(),
            "draft": self.reference.draft.to_mapping(),
            "commands": self.commands,
            "legacy": self.legacy,
        }


class VisibleCardReviewStore:
    """Store reviews as atomically published, recording-scoped directories."""

    def __init__(
        self,
        root: Path | str,
        *,
        legacy_reference_store: PipelineReferenceStore | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.legacy_reference_store = legacy_reference_store
        self._lock = RLock()
        self._lock_state = local()

    def review_root(self, recording_id: str, review_id: str) -> Path:
        _safe_id(recording_id, "recording_id")
        _safe_id(review_id, "review_id")
        return contained_path(self.root, Path(recording_id) / "visible_cards" / review_id)

    def find_idempotent(
        self, recording_id: str, idempotency_key: str, request_digest: str
    ) -> StoredVisibleCardReview | None:
        """Return a prior create or reject reuse of its key with different request bytes."""

        _safe_id(recording_id, "recording_id")
        _safe_id(idempotency_key, "idempotency_key")
        if not re.fullmatch(r"[0-9a-f]{64}", request_digest):
            raise ValueError("request_digest must be a SHA-256 digest")
        parent = contained_path(self.root, Path(recording_id) / "visible_cards")
        with self._recording_lock(recording_id):
            if not parent.is_dir() or parent.is_symlink():
                return None
            for path in sorted(parent.iterdir(), key=lambda item: item.name):
                if path.name.startswith(".") or not path.is_dir() or path.is_symlink():
                    continue
                try:
                    manifest = _read_json(path / "review.json")
                except (OSError, ValueError):
                    continue
                if manifest.get("idempotency_key") == idempotency_key:
                    if manifest.get("request_digest") != request_digest:
                        raise VisibleCardReviewConflict(
                            "idempotency_key was already used with a different request"
                        )
                    return self.get(recording_id, manifest["review_id"])
        return None

    def create(
        self,
        *,
        recording_id: str,
        review_id: str,
        source: str,
        lineage: Mapping[str, Any],
        reference: StoredPipelineReference,
        commands: Mapping[str, str] | None = None,
        created_at: str | None = None,
        idempotency_key: str | None = None,
        request_digest: str | None = None,
    ) -> StoredVisibleCardReview:
        """Publish one complete review directory; a failed write leaves prior reviews intact."""

        _safe_id(recording_id, "recording_id")
        _safe_id(review_id, "review_id")
        if review_id == _LEGACY_REVIEW_ID:
            raise ValueError("review_id is reserved for the legacy visible-card review")
        if source not in _SOURCES:
            raise ValueError("source must be visible_regions or card_scenes")
        if (
            reference.state.recording_id != recording_id
            or reference.state.content_type != "visible_cards"
        ):
            raise ValueError("review reference identity does not match recording_id")
        if reference.state.draft_revision != reference.draft.revision:
            raise ValueError("review state and draft revisions differ")
        if reference.state.source_revision_id != reference.draft.source_revision_id:
            raise ValueError("review state and draft source revisions differ")
        lineage_value = _validated_mapping(lineage, "lineage")
        command_values = _validated_commands(commands or {})
        timestamp = created_at or reference.draft.updated_at
        _validate_timestamp(timestamp, "created_at")
        destination = self.review_root(recording_id, review_id)

        with self._recording_lock(recording_id):
            if idempotency_key is not None:
                _safe_id(idempotency_key, "idempotency_key")
                if request_digest is None or not re.fullmatch(r"[0-9a-f]{64}", request_digest):
                    raise ValueError("request_digest must be a SHA-256 digest")
                for existing_path in (
                    destination.parent.iterdir() if destination.parent.exists() else ()
                ):
                    if existing_path.name.startswith(".") or not existing_path.is_dir():
                        continue
                    try:
                        prior = _read_json(existing_path / "review.json")
                    except (OSError, ValueError):
                        continue
                    if prior.get("idempotency_key") == idempotency_key:
                        if prior.get("request_digest") != request_digest:
                            raise VisibleCardReviewConflict(
                                "idempotency_key was already used with a different request"
                            )
                        return self.get(recording_id, prior["review_id"])
            if destination.exists() or destination.is_symlink():
                raise VisibleCardReviewConflict(f"visible-card review already exists: {review_id}")
            manifest = {
                "schema_version": "visible-card-review/v1",
                "review_id": review_id,
                "recording_id": recording_id,
                "status": "completed" if reference.state.draft_state == "completed" else "draft",
                "source": source,
                "lineage": lineage_value,
                "created_at": timestamp,
                "updated_at": reference.draft.updated_at,
                "idempotency_key": idempotency_key,
                "request_digest": request_digest,
            }
            try:
                with staging_directory(destination.parent, prefix=f".{review_id}-") as staging:
                    _write_json(staging / "review.json", manifest)
                    _write_json(staging / "state.json", reference.state.to_mapping())
                    _write_bytes(
                        staging / "draft.json",
                        canonical_reference_draft_bytes(reference.draft),
                    )
                    _write_json(staging / "commands.json", command_values)
                    commit_staged_directory(
                        staging,
                        destination,
                        validate=lambda path: self._read_directory(path, recording_id, review_id),
                    )
            except FileExistsError as error:
                raise VisibleCardReviewConflict(
                    f"visible-card review already exists: {review_id}"
                ) from error
            return self.get(recording_id, review_id)

    def get(self, recording_id: str, review_id: str) -> StoredVisibleCardReview:
        """Read a review by its stable ID, or adapt the current legacy draft without migration."""

        if review_id == _LEGACY_REVIEW_ID:
            return self._legacy_review(recording_id)
        path = self.review_root(recording_id, review_id)
        if path.is_symlink() or not path.is_dir():
            raise PipelineReferenceNotFound(
                f"The visible-card review was not found: {recording_id}/{review_id}"
            )
        try:
            return self._read_directory(path, recording_id, review_id)
        except (OSError, TypeError, UnicodeError, ValueError, KeyError) as error:
            raise VisibleCardReviewStoreError(
                f"The visible-card review is unavailable: {recording_id}/{review_id}"
            ) from error

    def list_reviews(self, recording_id: str) -> tuple[StoredVisibleCardReview, ...]:
        """List valid reviews newest-updated first, then by review ID."""

        _safe_id(recording_id, "recording_id")
        reviews: list[StoredVisibleCardReview] = []
        parent = contained_path(self.root, Path(recording_id) / "visible_cards")
        if parent.is_dir() and not parent.is_symlink():
            for path in sorted(parent.iterdir(), key=lambda item: item.name):
                if path.name.startswith(".") or path.name == _LEGACY_REVIEW_ID:
                    continue
                try:
                    reviews.append(self.get(recording_id, path.name))
                except (
                    OSError,
                    PipelineReferenceNotFound,
                    TypeError,
                    UnicodeError,
                    ValueError,
                ) as error:
                    self._log_invalid(path, error)
        if self.legacy_reference_store is not None:
            with suppress(PipelineReferenceNotFound):
                reviews.append(self._legacy_review(recording_id))
        reviews.sort(key=lambda item: item.review_id)
        reviews.sort(key=lambda item: item.updated_at, reverse=True)
        return tuple(reviews)

    def _legacy_review(self, recording_id: str) -> StoredVisibleCardReview:
        if self.legacy_reference_store is None:
            raise PipelineReferenceNotFound("The legacy visible-card review was not configured")
        with self.legacy_reference_store.locked(recording_id, "visible_cards"):
            reference = self.legacy_reference_store.read_locked(recording_id, "visible_cards")
            commands = self.legacy_reference_store.read_commands_locked(
                recording_id, "visible_cards"
            )
        source = (
            "card_scenes" if reference.draft.proposal_revision_id is not None else "visible_regions"
        )
        lineage: dict[str, Any] = {
            "source_revision_id": reference.draft.source_revision_id,
            "proposal_revision_id": reference.draft.proposal_revision_id,
        }
        return StoredVisibleCardReview(
            review_id=_LEGACY_REVIEW_ID,
            recording_id=recording_id,
            status="completed" if reference.state.draft_state == "completed" else "draft",
            source=source,
            lineage=lineage,
            created_at=reference.draft.updated_at,
            updated_at=reference.draft.updated_at,
            reference=reference,
            commands=commands,
            legacy=True,
        )

    def _read_directory(
        self, path: Path, recording_id: str, review_id: str
    ) -> StoredVisibleCardReview:
        if path.is_symlink() or any(item.is_symlink() for item in path.iterdir()):
            raise OSError("visible-card review contains a symlink")
        manifest = _read_json(path / "review.json")
        expected = {
            "schema_version",
            "review_id",
            "recording_id",
            "status",
            "source",
            "lineage",
            "created_at",
            "updated_at",
            "idempotency_key",
            "request_digest",
        }
        if set(manifest) != expected or manifest.get("schema_version") != "visible-card-review/v1":
            raise ValueError("visible-card review manifest has invalid fields")
        if manifest["recording_id"] != recording_id or manifest["review_id"] != review_id:
            raise ValueError("visible-card review identity differs from its path")
        if manifest["status"] not in {"draft", "completed"} or manifest["source"] not in _SOURCES:
            raise ValueError("visible-card review status or source is invalid")
        _validate_timestamp(manifest["created_at"], "created_at")
        _validate_timestamp(manifest["updated_at"], "updated_at")
        lineage = _validated_mapping(manifest["lineage"], "lineage")
        state_raw = (path / "state.json").read_bytes()
        draft_raw = (path / "draft.json").read_bytes()
        state = parse_reference_state_bytes(state_raw)
        draft = parse_reference_draft_bytes(draft_raw)
        if state_raw != canonical_reference_state_bytes(state) or draft_raw != (
            canonical_reference_draft_bytes(draft)
        ):
            raise ValueError("visible-card review data is not canonical")
        if (
            state.recording_id != recording_id
            or state.content_type != "visible_cards"
            or draft.recording_id != recording_id
            or draft.content_type != "visible_cards"
            or state.draft_revision != draft.revision
            or state.source_revision_id != draft.source_revision_id
        ):
            raise ValueError("visible-card review state and draft disagree")
        status = "completed" if state.draft_state == "completed" else "draft"
        if manifest["status"] != status or manifest["updated_at"] != draft.updated_at:
            raise ValueError("visible-card review manifest is stale")
        commands = _validated_commands(_read_json(path / "commands.json"))
        return StoredVisibleCardReview(
            review_id=review_id,
            recording_id=recording_id,
            status=status,
            source=manifest["source"],
            lineage=lineage,
            created_at=manifest["created_at"],
            updated_at=manifest["updated_at"],
            reference=StoredPipelineReference(state=state, draft=draft),
            commands=commands,
        )

    @contextmanager
    def locked_review(self, recording_id: str, review_id: str) -> Iterator[None]:
        """Lock one review while a service applies and persists a command."""

        with self._recording_lock(recording_id):
            self.get(recording_id, review_id)
            yield

    def update_review(
        self,
        recording_id: str,
        review_id: str,
        reference: StoredPipelineReference,
        commands: Mapping[str, str],
    ) -> StoredVisibleCardReview:
        """Persist one edited review and its command ledger under the review lock."""

        if review_id == _LEGACY_REVIEW_ID:
            raise VisibleCardReviewConflict("the legacy visible-card review is read-only")
        path = self.review_root(recording_id, review_id)
        with self._recording_lock(recording_id):
            current = self.get(recording_id, review_id)
            if reference.draft.revision not in {
                current.reference.state.draft_revision,
                current.reference.state.draft_revision + 1,
            }:
                raise VisibleCardReviewConflict("review revision changed before publication")
            manifest = _read_json(path / "review.json")
            manifest["status"] = (
                "completed" if reference.state.draft_state == "completed" else "draft"
            )
            manifest["updated_at"] = reference.draft.updated_at
            atomic_write_json(path / "draft.json", canonical_reference_draft_bytes(reference.draft))
            atomic_write_json(path / "state.json", canonical_reference_state_bytes(reference.state))
            atomic_write_json(path / "commands.json", canonical_json_bytes(dict(commands)))
            atomic_write_json(path / "review.json", canonical_json_bytes(manifest))
            return self.get(recording_id, review_id)

    @contextmanager
    def _recording_lock(self, recording_id: str) -> Iterator[None]:
        path = contained_path(self.root, Path(recording_id) / ".visible-card-reviews.lock")
        with self._lock:
            held = getattr(self._lock_state, "recordings", set())
            if recording_id in held:
                yield
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a+b") as handle:
                flock(handle.fileno(), LOCK_EX)
                self._lock_state.recordings = {*held, recording_id}
                try:
                    yield
                finally:
                    self._lock_state.recordings = held
                    flock(handle.fileno(), LOCK_UN)

    @staticmethod
    def _log_invalid(path: Path, error: BaseException) -> None:
        LOGGER.warning(
            "visible_card_review_catalog_skipped",
            extra={"path": str(path), "reason": str(error)},
        )


def _safe_id(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) > 128 or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a safe identifier")
    return value


def _validated_mapping(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return json.loads(canonical_json_bytes(dict(value)).decode("utf-8"))


def _validated_commands(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or not key or not isinstance(digest, str)
        for key, digest in value.items()
    ):
        raise ValueError("review command ledger is invalid")
    return dict(sorted(value.items()))


def _validate_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be a UTC timestamp")
    from datetime import datetime

    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{field} must be a UTC timestamp") from error


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_bytes(path, canonical_json_bytes(dict(value)))


def _write_bytes(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or raw != canonical_json_bytes(value):
        raise ValueError("visible-card review JSON is not canonical")
    return value


__all__ = [
    "StoredVisibleCardReview",
    "VisibleCardReviewConflict",
    "VisibleCardReviewStore",
    "VisibleCardReviewStoreError",
]
