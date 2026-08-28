"""SQLite index metadata for accepted shared repository bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from dokodetector_backend.models import RepositoryBundleIndex


@dataclass(frozen=True, slots=True)
class StoredRepositoryBundle:
    """Non-canonical searchable metadata for one accepted bundle."""

    recording_id: str
    source_asset_id: str
    video_id: str
    session_id: str
    source_sha256: str
    manifest_sha256: str
    source_record_sha256: str
    task_enrollment_sha256: str
    proposal_run_ids: tuple[str, ...]
    bundle_fingerprint: str
    state: str
    received_at: datetime


class RepositoryBundleRepositoryError(RuntimeError):
    """Unexpected database failure while indexing a bundle."""


class RepositoryBundleConflict(RepositoryBundleRepositoryError):
    """A recording ID is already indexed with different content."""


class RepositoryBundleRepository:
    """Write one complete index row in a single SQLite transaction."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._session_factory = sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
        )

    def get(self, recording_id: str) -> StoredRepositoryBundle | None:
        with self._session_factory() as session:
            row = session.get(RepositoryBundleIndex, recording_id)
            return _from_model(row) if row is not None else None

    def insert(self, bundle: StoredRepositoryBundle) -> tuple[StoredRepositoryBundle, bool]:
        """Insert an index row, or return an identical existing row."""

        try:
            with self._session_factory.begin() as session:
                existing = session.get(RepositoryBundleIndex, bundle.recording_id)
                if existing is not None:
                    stored = _from_model(existing)
                    if stored.bundle_fingerprint != bundle.bundle_fingerprint:
                        raise RepositoryBundleConflict(
                            "The recording ID is already indexed with different content."
                        )
                    return stored, False
                row = _to_model(bundle)
                session.add(row)
                session.flush()
                return _from_model(row), True
        except RepositoryBundleConflict:
            raise
        except IntegrityError as error:
            existing = self.get(bundle.recording_id)
            if existing is not None and existing.bundle_fingerprint == bundle.bundle_fingerprint:
                return existing, False
            if existing is not None:
                raise RepositoryBundleConflict(
                    "The recording ID is already indexed with different content."
                ) from error
            raise RepositoryBundleRepositoryError(
                "The bundle index could not be stored."
            ) from error


def _to_model(bundle: StoredRepositoryBundle) -> RepositoryBundleIndex:
    return RepositoryBundleIndex(
        recording_id=bundle.recording_id,
        source_asset_id=bundle.source_asset_id,
        video_id=bundle.video_id,
        session_id=bundle.session_id,
        source_sha256=bundle.source_sha256,
        manifest_sha256=bundle.manifest_sha256,
        source_record_sha256=bundle.source_record_sha256,
        task_enrollment_sha256=bundle.task_enrollment_sha256,
        proposal_run_ids_json=json.dumps(bundle.proposal_run_ids, separators=(",", ":")),
        bundle_fingerprint=bundle.bundle_fingerprint,
        state=bundle.state,
        received_at=bundle.received_at,
    )


def _from_model(row: RepositoryBundleIndex) -> StoredRepositoryBundle:
    return StoredRepositoryBundle(
        recording_id=row.recording_id,
        source_asset_id=row.source_asset_id,
        video_id=row.video_id,
        session_id=row.session_id,
        source_sha256=row.source_sha256,
        manifest_sha256=row.manifest_sha256,
        source_record_sha256=row.source_record_sha256,
        task_enrollment_sha256=row.task_enrollment_sha256,
        proposal_run_ids=tuple(json.loads(row.proposal_run_ids_json)),
        bundle_fingerprint=row.bundle_fingerprint,
        state=row.state,
        received_at=_as_utc(row.received_at),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "RepositoryBundleConflict",
    "RepositoryBundleRepository",
    "RepositoryBundleRepositoryError",
    "StoredRepositoryBundle",
]
