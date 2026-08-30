"""SQLite index metadata for accepted shared repository bundles."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from dokodetector_backend.intake_contract import parse_repository_bundle, validate_repository_bundle
from dokodetector_backend.logging_config import log_event
from dokodetector_backend.models import RepositoryBundleIndex
from dokodetector_backend.repository_bundle_storage import (
    RepositoryBundleStorage,
    bundle_fingerprint,
)

LOGGER = logging.getLogger(__name__)


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


class RepositoryBundleRebuildError(RepositoryBundleRepositoryError):
    """A canonical bundle cannot be used to rebuild the index."""


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

    def rebuild_from_intake(
        self, storage: RepositoryBundleStorage
    ) -> tuple[StoredRepositoryBundle, ...]:
        """Rebuild searchable rows from complete canonical bundle files only."""

        rebuilt: list[StoredRepositoryBundle] = []
        for bundle_path in sorted(storage.root.iterdir()) if storage.root.is_dir() else ():
            if not bundle_path.is_dir() or bundle_path.name.startswith("."):
                continue
            try:
                files = storage.file_digests(bundle_path.name)
                manifest_bytes = (bundle_path / "manifest.json").read_bytes()
                source_bytes = (bundle_path / "source-record.json").read_bytes()
                enrollment_bytes = (bundle_path / "initial-task-enrollment.json").read_bytes()
                descriptors = parse_repository_bundle(manifest_bytes).files.proposal_generator_runs
                proposal_bytes = {
                    descriptor.proposal_generator_run_id: (
                        bundle_path / descriptor.relative_path
                    ).read_bytes()
                    for descriptor in descriptors
                }
                bundle, _, enrollments, runs = validate_repository_bundle(
                    manifest_bytes, source_bytes, enrollment_bytes, proposal_bytes
                )
                _assert_bundle_files(bundle, files)
                received_at = min(
                    datetime.fromisoformat(item.created_at_utc.replace("Z", "+00:00"))
                    for item in enrollments.enrollments
                )
                rebuilt.append(
                    StoredRepositoryBundle(
                        recording_id=bundle.recording_id,
                        source_asset_id=bundle.source_asset_id,
                        video_id=bundle.video_id,
                        session_id=bundle.session_id,
                        source_sha256=bundle.source_sha256,
                        manifest_sha256=files["manifest.json"].sha256,
                        source_record_sha256=files["source-record.json"].sha256,
                        task_enrollment_sha256=files["initial-task-enrollment.json"].sha256,
                        proposal_run_ids=tuple(run.proposal_generator_run_id for run in runs),
                        bundle_fingerprint=bundle_fingerprint(files),
                        state=bundle.state,
                        received_at=received_at,
                    )
                )
            except RepositoryBundleRebuildError as error:
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "repository_bundle_rebuild_skipped",
                    recording_id=bundle_path.name,
                    reason=str(error),
                )
            except (OSError, KeyError, TypeError, ValueError) as error:
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "repository_bundle_rebuild_skipped",
                    recording_id=bundle_path.name,
                    reason=str(error),
                )

        with self._session_factory.begin() as session:
            session.query(RepositoryBundleIndex).delete()
            session.add_all(_to_model(item) for item in rebuilt)
        return tuple(rebuilt)


def _assert_bundle_files(bundle: object, files: dict[str, object]) -> None:
    expected = {
        "manifest.json",
        "source-record.json",
        "initial-task-enrollment.json",
        *(item.relative_path for item in bundle.files.proposal_generator_runs),
        bundle.files.video.relative_path,
    }
    if set(files) != expected:
        raise RepositoryBundleRebuildError("canonical bundle contains unexpected or missing files")
    descriptors = {
        "manifest.json": None,
        "source-record.json": bundle.files.source_record,
        "initial-task-enrollment.json": bundle.files.task_enrollment,
        bundle.files.video.relative_path: bundle.files.video,
        **{item.relative_path: item for item in bundle.files.proposal_generator_runs},
    }
    for relative_path, descriptor in descriptors.items():
        if descriptor is None:
            continue
        stored = files[relative_path]
        if stored.byte_length != descriptor.byte_length or stored.sha256 != descriptor.sha256:
            raise RepositoryBundleRebuildError(
                f"canonical file does not match manifest: {relative_path}"
            )


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
