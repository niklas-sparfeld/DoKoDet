"""Validated reads and publication for accepted evidence-package bundles."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import UUID

from dokodetector_backend.contract import EvidenceManifest, parse_manifest_bytes
from dokodetector_backend.evidence_package_storage import (
    EvidencePackageStorage,
    TemporaryEvidencePackage,
    calculate_bundle_fingerprint,
)
from dokodetector_backend.filesystem import enumerate_resource_directories
from dokodetector_backend.intake_contract import (
    EvidencePackageBundle,
    IntakeContractError,
    parse_evidence_package_bundle,
    parse_task_enrollment,
    validate_evidence_package_bundle,
)
from dokodetector_backend.logging_config import log_event
from dokodetector_backend.repository_bundle_storage import StoredRepositoryFile
from dokodetector_backend.stored_models import StoredFrame, StoredPackage
from dokodetector_backend.table_observation_store import TableObservationStore

LOGGER = logging.getLogger(__name__)


class EvidencePackageStoreError(RuntimeError):
    """The canonical evidence-package resource could not be read or published."""


class EvidencePackageConflict(EvidencePackageStoreError):
    """A package ID is already stored with different content."""


class EvidencePackageLogicalEventConflict(EvidencePackageStoreError):
    """A session and event sequence are already stored for another package."""


class EvidencePackageStore:
    """Read and publish accepted evidence packages from the canonical intake root."""

    def __init__(self, storage: EvidencePackageStorage) -> None:
        self.storage = storage
        self._publish_lock = RLock()

    def get(self, package_id: UUID | str) -> StoredPackage | None:
        """Return one valid package, or ``None`` when it is absent or invalid."""

        try:
            raw_package_path = self.storage.root / str(UUID(str(package_id)))
            if raw_package_path.is_symlink():
                return None
            package_path = self.storage.package_path(package_id)
        except (TypeError, ValueError):
            return None
        try:
            return self._read_path(package_path, require_canonical_name=True)
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            if package_path.exists():
                self._log_invalid(package_path, error)
            return None

    def get_package(self, package_id: UUID | str) -> StoredPackage | None:
        """Return one package using the legacy resource verb."""

        return self.get(package_id)

    def list(self) -> tuple[StoredPackage, ...]:
        """Return valid packages in deterministic intake order."""

        enumeration = enumerate_resource_directories(
            self.storage.root,
            validate=lambda path: self._read_path(path, require_canonical_name=True),
        )
        for diagnostic in enumeration.diagnostics:
            self._log_invalid(diagnostic.path, ValueError(diagnostic.reason))

        packages: list[StoredPackage] = []
        for path in enumeration.paths:
            try:
                packages.append(self._read_path(path, require_canonical_name=True))
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                self._log_invalid(path, error)
        return tuple(
            sorted(
                packages,
                key=lambda package: (
                    package.received_at,
                    package.event_sequence,
                    str(package.package_id),
                ),
            )
        )

    def get_by_logical_event(
        self, session_id: UUID | str, event_sequence: int
    ) -> StoredPackage | None:
        """Return the package for one session and logical event."""

        expected_session_id = str(session_id)
        return next(
            (
                package
                for package in self.list()
                if str(package.session_id) == expected_session_id
                and package.event_sequence == event_sequence
            ),
            None,
        )

    def get_pending(
        self,
        analyzer_name: str,
        analyzer_version: str,
        observation_store: TableObservationStore,
    ) -> StoredPackage | None:
        """Return the first package without this analyzer observation."""

        pending = self.list_pending(analyzer_name, analyzer_version, observation_store)
        return pending[0] if pending else None

    def list_pending(
        self,
        analyzer_name: str,
        analyzer_version: str,
        observation_store: TableObservationStore,
    ) -> tuple[StoredPackage, ...]:
        """Return all packages without this analyzer observation in stable order."""

        return tuple(
            package
            for package in self.list()
            if package.state == "stored"
            and observation_store.get_for_analyzer(
                package.package_id,
                analyzer_name,
                analyzer_version,
            )
            is None
        )

    def publish(
        self,
        staged: TemporaryEvidencePackage,
    ) -> tuple[StoredPackage, bool]:
        """Validate and publish one staged package, or replay an identical package."""

        with self._publish_lock:
            staged_package = self._read_path(
                staged.temporary_path,
                expected_package_id=staged.package_id,
                require_canonical_name=False,
            )
            existing = self.get(staged.package_id)
            if existing is not None:
                if existing.package_fingerprint == staged_package.package_fingerprint:
                    return existing, False
                raise EvidencePackageConflict(
                    "The package ID is already stored with different content."
                )
            existing_event = self.get_by_logical_event(
                staged_package.session_id,
                staged_package.event_sequence,
            )
            if existing_event is not None:
                raise EvidencePackageLogicalEventConflict(
                    "The session and event sequence are already stored for another package."
                )
            try:
                staged.commit()
            except FileExistsError as error:
                existing = self.get(staged.package_id)
                if existing is not None and (
                    existing.package_fingerprint == staged_package.package_fingerprint
                ):
                    return existing, False
                raise EvidencePackageConflict(
                    "The package ID is already stored with different content."
                ) from error
            except (OSError, ValueError) as error:
                raise EvidencePackageStoreError(
                    "The evidence package could not be published."
                ) from error

            stored = self.get(staged.package_id)
            if stored is None or stored.package_fingerprint != staged_package.package_fingerprint:
                raise EvidencePackageStoreError(
                    "The published evidence package failed validation."
                )
            return stored, True

    def _read_path(
        self,
        package_path: Path,
        *,
        expected_package_id: UUID | None = None,
        require_canonical_name: bool,
    ) -> StoredPackage:
        """Validate one complete package directory and project its metadata."""

        if (
            require_canonical_name and package_path.name.startswith(".")
        ) or not package_path.is_dir():
            raise IntakeContractError("evidence package directory is unavailable")
        files = self.storage.file_digests(package_path)
        manifest_bytes = (package_path / "manifest.json").read_bytes()
        evidence_manifest_bytes = (package_path / "evidence-manifest.json").read_bytes()
        package_record_bytes = (package_path / "package-record.json").read_bytes()
        task_enrollment_bytes = (package_path / "initial-task-enrollment.json").read_bytes()
        lineage_bytes = (package_path / "lineage.json").read_bytes()
        bundle = parse_evidence_package_bundle(manifest_bytes)
        if expected_package_id is not None and bundle.package_id != str(expected_package_id):
            raise IntakeContractError("evidence package ID differs from its staged identity")
        if require_canonical_name and bundle.package_id != package_path.name:
            raise IntakeContractError("evidence package ID differs from its directory name")

        member_files = {
            path: (package_path / path).read_bytes()
            for path in files
            if path != "manifest.json"
        }
        validate_evidence_package_bundle(
            manifest_bytes,
            evidence_manifest_bytes,
            package_record_bytes,
            task_enrollment_bytes,
            lineage_bytes,
            member_files,
        )
        evidence_manifest = parse_manifest_bytes(evidence_manifest_bytes)
        _assert_package_files(bundle, evidence_manifest, files)
        enrollments = parse_task_enrollment(task_enrollment_bytes)
        received_at = min(
            datetime.fromisoformat(item.created_at_utc.replace("Z", "+00:00"))
            for item in enrollments.enrollments
        ).astimezone(timezone.utc)
        frames = tuple(
            StoredFrame.from_manifest(
                frame,
                relative_path=f"frames/{frame.part_name}.jpg",
            )
            for frame in evidence_manifest.frames
        )
        return StoredPackage.from_manifest(
            evidence_manifest,
            evidence_manifest_bytes,
            package_fingerprint=calculate_bundle_fingerprint(files),
            frames=frames,
            received_at=received_at,
        )

    @staticmethod
    def _log_invalid(path: Path, error: BaseException) -> None:
        log_event(
            LOGGER,
            logging.WARNING,
            "evidence_package_catalog_skipped",
            package_id=path.name,
            reason=str(error),
        )


def _assert_package_files(
    bundle: EvidencePackageBundle,
    evidence_manifest: EvidenceManifest,
    files: dict[str, StoredRepositoryFile],
) -> None:
    """Require the exact declared package members and their digests."""

    expected_paths = {
        "manifest.json",
        bundle.files.evidence_manifest.relative_path,
        bundle.files.package_record.relative_path,
        bundle.files.task_enrollment.relative_path,
        bundle.files.lineage.relative_path,
        *(f"frames/{frame.part_name}.jpg" for frame in evidence_manifest.frames),
    }
    if (
        evidence_manifest.video_snippet is not None
        and evidence_manifest.video_snippet.capture_complete
    ):
        assert evidence_manifest.video_snippet.part_name is not None
        expected_paths.add(f"video/{evidence_manifest.video_snippet.part_name}.mp4")
    if set(files) != expected_paths:
        raise IntakeContractError("canonical evidence package contains unexpected or missing files")

    descriptors = {
        bundle.files.evidence_manifest.relative_path: bundle.files.evidence_manifest,
        bundle.files.package_record.relative_path: bundle.files.package_record,
        bundle.files.task_enrollment.relative_path: bundle.files.task_enrollment,
        bundle.files.lineage.relative_path: bundle.files.lineage,
        **{member.relative_path: member for member in bundle.files.frames},
    }
    if bundle.files.video_snippet is not None:
        descriptors[bundle.files.video_snippet.relative_path] = bundle.files.video_snippet
    for relative_path, descriptor in descriptors.items():
        stored = files.get(relative_path)
        if stored is None or (
            stored.byte_length != descriptor.byte_length
            or stored.sha256 != descriptor.sha256
        ):
            raise IntakeContractError(
                f"canonical file does not match its manifest: {relative_path}"
            )


__all__ = [
    "EvidencePackageConflict",
    "EvidencePackageLogicalEventConflict",
    "EvidencePackageStore",
    "EvidencePackageStoreError",
]
