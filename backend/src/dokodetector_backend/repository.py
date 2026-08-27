"""SQLite repository for evidence package metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from alembic.config import Config
from sqlalchemy import Engine, and_, create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker
from table_evidence_analyzer import TableObservation

from alembic import command
from dokodetector_backend.contract import EvidenceManifest, FrameManifest
from dokodetector_backend.models import (
    EvidenceFrame,
    EvidencePackage,
)
from dokodetector_backend.models import (
    TableObservation as TableObservationRow,
)


@dataclass(frozen=True, slots=True)
class StoredFrame:
    """Frame metadata returned by the repository."""

    part_name: str
    target_offset_ms: int
    actual_offset_ms: int
    session_elapsed_ms: int
    captured_at_utc: datetime
    content_type: str
    byte_length: int
    sha256: str
    relative_path: str

    @classmethod
    def from_manifest(cls, frame: FrameManifest, *, relative_path: str) -> StoredFrame:
        """Build a database record from one validated manifest frame."""

        return cls(
            part_name=frame.part_name,
            target_offset_ms=frame.target_offset_ms,
            actual_offset_ms=frame.actual_offset_ms,
            session_elapsed_ms=frame.session_elapsed_ms,
            captured_at_utc=frame.captured_at_utc,
            content_type=frame.content_type,
            byte_length=frame.byte_length,
            sha256=frame.sha256,
            relative_path=relative_path,
        )


@dataclass(frozen=True, slots=True)
class StoredPackage:
    """Package metadata stored in SQLite."""

    package_id: UUID
    schema_version: str
    session_id: UUID
    event_sequence: int
    event_time_ms: int
    manifest_json: str
    manifest_sha256: str
    package_fingerprint: str
    state: str
    received_at: datetime
    frames: tuple[StoredFrame, ...]

    @classmethod
    def from_manifest(
        cls,
        manifest: EvidenceManifest,
        manifest_bytes: bytes,
        *,
        package_fingerprint: str,
        frames: tuple[StoredFrame, ...],
        received_at: datetime,
    ) -> StoredPackage:
        """Build a database record from a validated manifest and original bytes."""

        return cls(
            package_id=manifest.package_id,
            schema_version=manifest.schema_version,
            session_id=manifest.session.session_id,
            event_sequence=manifest.session.event_sequence,
            event_time_ms=manifest.event.event_time_ms,
            manifest_json=manifest_bytes.decode("utf-8"),
            manifest_sha256=_sha256(manifest_bytes),
            package_fingerprint=package_fingerprint,
            state="stored",
            received_at=received_at,
            frames=frames,
        )


@dataclass(frozen=True, slots=True)
class StoredTableObservation:
    """Immutable table-observation metadata stored in SQLite."""

    observation_id: str
    package_id: UUID
    schema_version: str
    analyzer_name: str
    analyzer_version: str
    status: str
    calibration: str
    observation_json: str
    observation_sha256: str
    relative_path: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TableObservationInsert:
    """The result of an idempotent table-observation insert."""

    observation: StoredTableObservation
    created: bool


class RepositoryError(RuntimeError):
    """Unexpected database failure."""


class RepositoryConflict(RepositoryError):
    """A package cannot be stored because a unique key is already used."""


class PackageConflict(RepositoryConflict):
    """The package ID is already stored."""


class LogicalEventConflict(RepositoryConflict):
    """The session and event sequence are already stored."""


class TableObservationConflict(RepositoryConflict):
    """An analyzer observation key is already used by different content."""


def create_database_engine(database_url: str) -> Engine:
    """Create a SQLite-compatible SQLAlchemy engine."""

    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        _create_sqlite_parent_directory(database_url)

    engine = create_engine(database_url, connect_args=connect_args)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection: Any, _: Any) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def upgrade_database(backend_root: Path, database_url: str) -> None:
    """Apply all Alembic migrations for a local database."""

    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


class EvidenceRepository:
    """Small repository for package and frame metadata."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._session_factory = sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
        )

    def insert_package(self, package: StoredPackage) -> StoredPackage:
        """Insert one package and all its frames in one transaction."""

        try:
            with self._session_factory.begin() as session:
                if session.get(EvidencePackage, str(package.package_id)) is not None:
                    raise PackageConflict("The package ID is already stored.")
                existing_event = session.scalar(
                    select(EvidencePackage).where(
                        EvidencePackage.session_id == str(package.session_id),
                        EvidencePackage.event_sequence == package.event_sequence,
                    )
                )
                if existing_event is not None:
                    raise LogicalEventConflict("The logical event is already stored.")

                row = _package_to_model(package)
                session.add(row)
                session.flush()
                return _package_from_model(row)
        except (PackageConflict, LogicalEventConflict):
            raise
        except IntegrityError as error:
            if self.get_package(package.package_id) is not None:
                raise PackageConflict("The package ID is already stored.") from error
            if self.get_by_logical_event(package.session_id, package.event_sequence) is not None:
                raise LogicalEventConflict("The logical event is already stored.") from error
            raise RepositoryError("The package could not be stored.") from error

    def get_package(self, package_id: UUID | str) -> StoredPackage | None:
        """Read a package and its frame rows."""

        with self._session_factory() as session:
            row = session.scalar(
                select(EvidencePackage)
                .options(selectinload(EvidencePackage.frames))
                .where(EvidencePackage.package_id == str(package_id))
            )
            return _package_from_model(row) if row is not None else None

    def get_by_logical_event(
        self, session_id: UUID | str, event_sequence: int
    ) -> StoredPackage | None:
        """Read the package for one session and event sequence."""

        with self._session_factory() as session:
            row = session.scalar(
                select(EvidencePackage)
                .options(selectinload(EvidencePackage.frames))
                .where(
                    EvidencePackage.session_id == str(session_id),
                    EvidencePackage.event_sequence == event_sequence,
                )
            )
            return _package_from_model(row) if row is not None else None

    def delete_package(self, package_id: UUID | str) -> bool:
        """Delete one package and its frame rows."""

        with self._session_factory.begin() as session:
            row = session.get(EvidencePackage, str(package_id))
            if row is None:
                return False
            session.delete(row)
            return True

    def get_pending_package(
        self, analyzer_name: str, analyzer_version: str
    ) -> StoredPackage | None:
        """Return the first stored package without this analyzer observation."""

        with self._session_factory() as session:
            row = session.scalar(
                select(EvidencePackage)
                .options(selectinload(EvidencePackage.frames))
                .outerjoin(
                    TableObservationRow,
                    and_(
                        TableObservationRow.package_id == EvidencePackage.package_id,
                        TableObservationRow.analyzer_name == analyzer_name,
                        TableObservationRow.analyzer_version == analyzer_version,
                    ),
                )
                .where(
                    EvidencePackage.state == "stored",
                    TableObservationRow.observation_id.is_(None),
                )
                .order_by(EvidencePackage.received_at, EvidencePackage.package_id)
                .limit(1)
            )
            return _package_from_model(row) if row is not None else None

    def list_pending_packages(
        self, analyzer_name: str, analyzer_version: str
    ) -> tuple[StoredPackage, ...]:
        """Return all stored packages without this analyzer observation."""

        with self._session_factory() as session:
            rows = session.scalars(
                select(EvidencePackage)
                .options(selectinload(EvidencePackage.frames))
                .outerjoin(
                    TableObservationRow,
                    and_(
                        TableObservationRow.package_id == EvidencePackage.package_id,
                        TableObservationRow.analyzer_name == analyzer_name,
                        TableObservationRow.analyzer_version == analyzer_version,
                    ),
                )
                .where(
                    EvidencePackage.state == "stored",
                    TableObservationRow.observation_id.is_(None),
                )
                .order_by(EvidencePackage.received_at, EvidencePackage.package_id)
            )
            return tuple(_package_from_model(row) for row in rows)

    def get_table_observation(self, observation_id: str) -> StoredTableObservation | None:
        """Read one stored table observation."""

        with self._session_factory() as session:
            row = session.get(TableObservationRow, observation_id)
            return _table_observation_from_model(row) if row is not None else None

    def get_table_observation_for_analyzer(
        self,
        package_id: UUID | str,
        analyzer_name: str,
        analyzer_version: str,
    ) -> StoredTableObservation | None:
        """Read the observation for one package and analyzer version."""

        with self._session_factory() as session:
            row = session.scalar(
                select(TableObservationRow).where(
                    TableObservationRow.package_id == str(package_id),
                    TableObservationRow.analyzer_name == analyzer_name,
                    TableObservationRow.analyzer_version == analyzer_version,
                )
            )
            return _table_observation_from_model(row) if row is not None else None

    def list_table_observations(self, package_id: UUID | str) -> tuple[StoredTableObservation, ...]:
        """Read all observations in deterministic creation order."""

        with self._session_factory() as session:
            rows = session.scalars(
                select(TableObservationRow)
                .where(TableObservationRow.package_id == str(package_id))
                .order_by(TableObservationRow.created_at, TableObservationRow.observation_id)
            )
            return tuple(_table_observation_from_model(row) for row in rows)

    def insert_table_observation(
        self,
        observation: TableObservation,
        observation_bytes: bytes,
        relative_path: str,
    ) -> TableObservationInsert:
        """Insert one observation, or return an exact existing replay."""

        if not isinstance(observation_bytes, bytes):
            raise TypeError("observation_bytes must be bytes.")
        try:
            observation_json = observation_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("observation_bytes must be UTF-8 JSON.") from error

        existing = self.get_table_observation(observation.observation_id)
        if existing is not None:
            return _resolve_table_observation_replay(existing, observation, observation_json)
        existing = self.get_table_observation_for_analyzer(
            observation.source.package_id,
            observation.analyzer.name,
            observation.analyzer.version,
        )
        if existing is not None:
            return _resolve_table_observation_replay(existing, observation, observation_json)

        row = TableObservationRow(
            observation_id=observation.observation_id,
            package_id=observation.source.package_id,
            schema_version=observation.schema_version,
            analyzer_name=observation.analyzer.name,
            analyzer_version=observation.analyzer.version,
            status=observation.status,
            calibration=observation.calibration,
            observation_json=observation_json,
            observation_sha256=_sha256(observation_bytes),
            relative_path=relative_path,
            created_at=datetime.now(timezone.utc),
        )
        try:
            with self._session_factory.begin() as session:
                session.add(row)
                session.flush()
                stored = _table_observation_from_model(row)
        except IntegrityError as error:
            existing = self.get_table_observation(observation.observation_id) or (
                self.get_table_observation_for_analyzer(
                    observation.source.package_id,
                    observation.analyzer.name,
                    observation.analyzer.version,
                )
            )
            if existing is not None:
                return _resolve_table_observation_replay(existing, observation, observation_json)
            raise RepositoryError("The table observation could not be stored.") from error
        return TableObservationInsert(observation=stored, created=True)

    def delete_table_observation(
        self, observation_id: str, *, observation_sha256: str | None = None
    ) -> bool:
        """Delete one observation during persistence compensation."""

        with self._session_factory.begin() as session:
            row = session.get(TableObservationRow, observation_id)
            if row is None or (
                observation_sha256 is not None and row.observation_sha256 != observation_sha256
            ):
                return False
            session.delete(row)
            return True


def _package_to_model(package: StoredPackage) -> EvidencePackage:
    return EvidencePackage(
        package_id=str(package.package_id),
        schema_version=package.schema_version,
        session_id=str(package.session_id),
        event_sequence=package.event_sequence,
        event_time_ms=package.event_time_ms,
        manifest_json=package.manifest_json,
        manifest_sha256=package.manifest_sha256,
        package_fingerprint=package.package_fingerprint,
        state=package.state,
        received_at=package.received_at,
        frames=[
            EvidenceFrame(
                package_id=str(package.package_id),
                part_name=frame.part_name,
                target_offset_ms=frame.target_offset_ms,
                actual_offset_ms=frame.actual_offset_ms,
                session_elapsed_ms=frame.session_elapsed_ms,
                captured_at_utc=frame.captured_at_utc,
                content_type=frame.content_type,
                byte_length=frame.byte_length,
                sha256=frame.sha256,
                relative_path=frame.relative_path,
            )
            for frame in package.frames
        ],
    )


def _package_from_model(row: EvidencePackage) -> StoredPackage:
    return StoredPackage(
        package_id=UUID(row.package_id),
        schema_version=row.schema_version,
        session_id=UUID(row.session_id),
        event_sequence=row.event_sequence,
        event_time_ms=row.event_time_ms,
        manifest_json=row.manifest_json,
        manifest_sha256=row.manifest_sha256,
        package_fingerprint=row.package_fingerprint,
        state=row.state,
        received_at=_as_utc(row.received_at),
        frames=tuple(
            StoredFrame(
                part_name=frame.part_name,
                target_offset_ms=frame.target_offset_ms,
                actual_offset_ms=frame.actual_offset_ms,
                session_elapsed_ms=frame.session_elapsed_ms,
                captured_at_utc=_as_utc(frame.captured_at_utc),
                content_type=frame.content_type,
                byte_length=frame.byte_length,
                sha256=frame.sha256,
                relative_path=frame.relative_path,
            )
            for frame in row.frames
        ),
    )


def _table_observation_from_model(row: TableObservationRow) -> StoredTableObservation:
    return StoredTableObservation(
        observation_id=row.observation_id,
        package_id=UUID(row.package_id),
        schema_version=row.schema_version,
        analyzer_name=row.analyzer_name,
        analyzer_version=row.analyzer_version,
        status=row.status,
        calibration=row.calibration,
        observation_json=row.observation_json,
        observation_sha256=row.observation_sha256,
        relative_path=row.relative_path,
        created_at=_as_utc(row.created_at),
    )


def _resolve_table_observation_replay(
    existing: StoredTableObservation,
    observation: TableObservation,
    observation_json: str,
) -> TableObservationInsert:
    if (
        str(existing.package_id) == observation.source.package_id
        and existing.analyzer_name == observation.analyzer.name
        and existing.analyzer_version == observation.analyzer.version
        and existing.observation_id == observation.observation_id
        and existing.observation_json == observation_json
    ):
        return TableObservationInsert(observation=existing, created=False)
    raise TableObservationConflict(
        "The table observation key is already stored with different content."
    )


def _sha256(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _create_sqlite_parent_directory(database_url: str) -> None:
    if database_url in {"sqlite://", "sqlite:///:memory:"}:
        return
    database_path = database_url.removeprefix("sqlite:///")
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)


__all__ = [
    "EvidenceRepository",
    "LogicalEventConflict",
    "PackageConflict",
    "RepositoryConflict",
    "RepositoryError",
    "StoredFrame",
    "StoredPackage",
    "StoredTableObservation",
    "TableObservationConflict",
    "TableObservationInsert",
    "create_database_engine",
    "upgrade_database",
]
