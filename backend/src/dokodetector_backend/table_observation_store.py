"""Validated reads and publication for immutable table observations."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import UUID

from table_evidence_analyzer import TableObservation, canonical_json_bytes, parse_observation_bytes

from dokodetector_backend.filesystem import enumerate_resource_directories
from dokodetector_backend.logging_config import log_event
from dokodetector_backend.storage import EvidenceStorage
from dokodetector_backend.stored_models import StoredTableObservation

LOGGER = logging.getLogger(__name__)


class TableObservationStoreError(RuntimeError):
    """The canonical table-observation resource could not be read or published."""


class TableObservationConflict(TableObservationStoreError):
    """An observation ID or package/analyzer key is already used by different content."""


class TableObservationStore:
    """Read and publish immutable observations below the runtime root."""

    def __init__(self, storage: EvidenceStorage) -> None:
        self.storage = storage
        self._publish_lock = RLock()

    def get(self, observation_id: str) -> StoredTableObservation | None:
        """Return one valid observation, or ``None`` when it is absent or invalid."""

        try:
            raw_path = self.storage.table_observations_root / observation_id
            if raw_path.is_symlink():
                return None
            path = self.storage.table_observation_path(observation_id)
        except (TypeError, ValueError):
            return None
        try:
            return self._read_path(path, require_canonical_name=True)
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            if path.exists():
                self._log_invalid(path, error)
            return None

    def list(self) -> tuple[StoredTableObservation, ...]:
        """Return all valid observations in stable creation order."""

        enumeration = enumerate_resource_directories(
            self.storage.table_observations_root,
            validate=lambda path: self._read_path(path, require_canonical_name=True),
        )
        for diagnostic in enumeration.diagnostics:
            self._log_invalid(diagnostic.path, ValueError(diagnostic.reason))

        observations: list[StoredTableObservation] = []
        for path in enumeration.paths:
            try:
                observations.append(self._read_path(path, require_canonical_name=True))
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                self._log_invalid(path, error)
        return tuple(
            sorted(
                observations,
                key=lambda observation: (observation.created_at, observation.observation_id),
            )
        )

    def list_for_package(self, package_id: UUID | str) -> tuple[StoredTableObservation, ...]:
        """Return valid observations for one evidence package."""

        expected_package_id = str(package_id)
        return tuple(
            observation
            for observation in self.list()
            if str(observation.package_id) == expected_package_id
        )

    def get_for_analyzer(
        self,
        package_id: UUID | str,
        analyzer_name: str,
        analyzer_version: str,
    ) -> StoredTableObservation | None:
        """Return the deterministic observation for one package and analyzer."""

        expected_package_id = str(package_id)
        return next(
            (
                observation
                for observation in self.list()
                if str(observation.package_id) == expected_package_id
                and observation.analyzer_name == analyzer_name
                and observation.analyzer_version == analyzer_version
            ),
            None,
        )

    def publish(
        self,
        observation: TableObservation,
        observation_bytes: bytes,
    ) -> tuple[StoredTableObservation, bool]:
        """Validate and publish one observation, or replay an identical observation."""

        expected_bytes = canonical_json_bytes(observation)
        if observation_bytes != expected_bytes:
            raise ValueError("observation bytes must be canonical")
        with self._publish_lock:
            existing = self.get(observation.observation_id)
            if existing is not None:
                return self._resolve_replay(existing, observation, observation_bytes)
            existing = self.get_for_analyzer(
                observation.source.package_id,
                observation.analyzer.name,
                observation.analyzer.version,
            )
            if existing is not None:
                return self._resolve_replay(existing, observation, observation_bytes)

            try:
                with self.storage.start_table_observation(observation.observation_id) as staged:
                    staged.write_observation(observation_bytes)
                    staged.commit()
            except FileExistsError as error:
                existing = self.get(observation.observation_id)
                if existing is not None:
                    return self._resolve_replay(existing, observation, observation_bytes)
                raise TableObservationStoreError(
                    "The table observation could not be published."
                ) from error
            except (OSError, ValueError) as error:
                raise TableObservationStoreError(
                    "The table observation could not be published."
                ) from error

            stored = self.get(observation.observation_id)
            if stored is None:
                raise TableObservationStoreError(
                    "The published table observation failed validation."
                )
            return stored, True

    def _read_path(
        self,
        path: Path,
        *,
        require_canonical_name: bool,
    ) -> StoredTableObservation:
        """Validate one observation document and project its derived metadata."""

        if path.name.startswith(".") or not path.is_dir():
            raise ValueError("table observation directory is unavailable")
        members = [member for member in path.rglob("*") if member.is_file()]
        if any(member.is_symlink() for member in members):
            raise ValueError("table observation members must not be symlinks")
        if {member.relative_to(path).as_posix() for member in members} != {"observation.json"}:
            raise ValueError("table observation has unexpected or missing members")
        observation_path = path / "observation.json"
        observation_bytes = observation_path.read_bytes()
        observation = parse_observation_bytes(observation_bytes)
        if require_canonical_name and observation.observation_id != path.name:
            raise ValueError("observation ID differs from its directory name")
        if observation_bytes != canonical_json_bytes(observation):
            raise ValueError("observation bytes are not canonical")
        try:
            package_id = UUID(observation.source.package_id)
        except (TypeError, ValueError) as error:
            raise ValueError("observation package ID is invalid") from error
        created_at = datetime.fromtimestamp(observation_path.stat().st_mtime, tz=timezone.utc)
        return StoredTableObservation(
            observation_id=observation.observation_id,
            package_id=package_id,
            schema_version=observation.schema_version,
            analyzer_name=observation.analyzer.name,
            analyzer_version=observation.analyzer.version,
            status=observation.status,
            calibration=observation.calibration,
            observation_json=observation_bytes.decode("utf-8"),
            observation_sha256=hashlib.sha256(observation_bytes).hexdigest(),
            relative_path=f"table-observations/{observation.observation_id}/observation.json",
            created_at=created_at,
        )

    @staticmethod
    def _resolve_replay(
        existing: StoredTableObservation,
        observation: TableObservation,
        observation_bytes: bytes,
    ) -> tuple[StoredTableObservation, bool]:
        if (
            str(existing.package_id) == observation.source.package_id
            and existing.analyzer_name == observation.analyzer.name
            and existing.analyzer_version == observation.analyzer.version
            and existing.observation_id == observation.observation_id
            and existing.observation_json.encode("utf-8") == observation_bytes
        ):
            return existing, False
        raise TableObservationConflict(
            "The table observation key is already stored with different content."
        )

    @staticmethod
    def _log_invalid(path: Path, error: BaseException) -> None:
        log_event(
            LOGGER,
            logging.WARNING,
            "table_observation_catalog_skipped",
            observation_id=path.name,
            reason=str(error),
        )


__all__ = [
    "TableObservationConflict",
    "TableObservationStore",
    "TableObservationStoreError",
]
