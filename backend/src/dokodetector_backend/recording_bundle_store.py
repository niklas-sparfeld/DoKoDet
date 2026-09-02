"""Filesystem reads and publication for accepted recording bundles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dokodetector_backend.filesystem import enumerate_resource_directories
from dokodetector_backend.intake_contract import (
    IntakeContractError,
    parse_repository_bundle,
    validate_repository_bundle,
)
from dokodetector_backend.logging_config import log_event
from dokodetector_backend.repository_bundle_storage import (
    RepositoryBundleStorage,
    StoredRepositoryFile,
    TemporaryRepositoryBundle,
    bundle_fingerprint,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StoredRecordingBundle:
    """Validated metadata projected from one canonical recording bundle."""

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


class RecordingBundleStoreError(RuntimeError):
    """Unexpected failure while reading or publishing a recording bundle."""


class RecordingBundleConflict(RecordingBundleStoreError):
    """A recording ID is already stored with different content."""


class RecordingBundleStore:
    """Read and publish accepted recording bundles from the canonical intake root."""

    def __init__(self, storage: RepositoryBundleStorage) -> None:
        self.storage = storage

    def get(self, recording_id: str) -> StoredRecordingBundle | None:
        """Return one valid bundle, or ``None`` when it is absent or invalid."""

        try:
            raw_bundle_path = self.storage.root / recording_id
            if raw_bundle_path.is_symlink():
                return None
            bundle_path = self.storage.bundle_path(recording_id)
        except ValueError:
            return None
        try:
            return self._read_path(bundle_path)
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            if bundle_path.exists():
                self._log_invalid(bundle_path, error)
            return None

    def list(self) -> tuple[StoredRecordingBundle, ...]:
        """Return valid bundles in newest-received, stable order."""

        enumeration = enumerate_resource_directories(
            self.storage.root,
            validate=self._read_path,
        )
        for diagnostic in enumeration.diagnostics:
            self._log_invalid(diagnostic.path, ValueError(diagnostic.reason))

        bundles: list[StoredRecordingBundle] = []
        for path in enumeration.paths:
            try:
                bundles.append(self._read_path(path))
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                self._log_invalid(path, error)
        return tuple(
            sorted(
                bundles,
                key=lambda bundle: (-bundle.received_at.timestamp(), bundle.recording_id),
            )
        )

    def publish(
        self,
        staged: TemporaryRepositoryBundle,
        *,
        staged_files: dict[str, StoredRepositoryFile],
    ) -> tuple[StoredRecordingBundle, bool]:
        """Publish a validated staged bundle, or replay an identical existing bundle."""

        incoming_fingerprint = bundle_fingerprint(staged_files)
        try:
            staged.commit()
        except FileExistsError as error:
            existing = self.get(staged.recording_id)
            if existing is not None and existing.bundle_fingerprint == incoming_fingerprint:
                return existing, False
            raise RecordingBundleConflict(
                "The recording ID is already stored with different content."
            ) from error
        except (OSError, ValueError) as error:
            raise RecordingBundleStoreError(
                "The recording bundle could not be published."
            ) from error

        stored = self.get(staged.recording_id)
        if stored is None or stored.bundle_fingerprint != incoming_fingerprint:
            raise RecordingBundleStoreError(
                "The published recording bundle failed validation."
            )
        return stored, True

    def _read_path(self, bundle_path: Path) -> StoredRecordingBundle:
        """Validate one complete canonical bundle and project its searchable metadata."""

        if bundle_path.name.startswith(".") or not bundle_path.is_dir():
            raise IntakeContractError("recording bundle directory is unavailable")
        files = self.storage.file_digests(bundle_path.name)
        manifest_bytes = (bundle_path / "manifest.json").read_bytes()
        source_bytes = (bundle_path / "source-record.json").read_bytes()
        enrollment_bytes = (bundle_path / "initial-task-enrollment.json").read_bytes()
        descriptor = parse_repository_bundle(manifest_bytes)
        proposal_bytes = {
            item.proposal_generator_run_id: (bundle_path / item.relative_path).read_bytes()
            for item in descriptor.files.proposal_generator_runs
        }
        bundle, _, enrollments, runs = validate_repository_bundle(
            manifest_bytes,
            source_bytes,
            enrollment_bytes,
            proposal_bytes,
        )
        if bundle.recording_id != bundle_path.name:
            raise IntakeContractError("bundle recording ID differs from its directory name")
        _assert_bundle_files(bundle, files)
        received_at = min(
            datetime.fromisoformat(item.created_at_utc.replace("Z", "+00:00"))
            for item in enrollments.enrollments
        ).astimezone(timezone.utc)
        return StoredRecordingBundle(
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

    @staticmethod
    def _log_invalid(path: Path, error: BaseException) -> None:
        log_event(
            LOGGER,
            logging.WARNING,
            "recording_bundle_catalog_skipped",
            recording_id=path.name,
            reason=str(error),
        )


def _assert_bundle_files(bundle: object, files: dict[str, StoredRepositoryFile]) -> None:
    """Require the exact declared bundle members and their manifest digests."""

    expected = {
        "manifest.json",
        "source-record.json",
        "initial-task-enrollment.json",
        *(item.relative_path for item in bundle.files.proposal_generator_runs),
        bundle.files.video.relative_path,
    }
    if set(files) != expected:
        raise IntakeContractError("canonical bundle contains unexpected or missing files")

    descriptors = {
        "source-record.json": bundle.files.source_record,
        "initial-task-enrollment.json": bundle.files.task_enrollment,
        bundle.files.video.relative_path: bundle.files.video,
        **{item.relative_path: item for item in bundle.files.proposal_generator_runs},
    }
    for relative_path, descriptor in descriptors.items():
        stored = files[relative_path]
        if stored.byte_length != descriptor.byte_length or stored.sha256 != descriptor.sha256:
            raise IntakeContractError(f"canonical file does not match manifest: {relative_path}")


__all__ = [
    "RecordingBundleConflict",
    "RecordingBundleStore",
    "RecordingBundleStoreError",
    "StoredRecordingBundle",
]
