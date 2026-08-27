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
from vision_detector import VisionDetectionResult

from alembic import command
from dokodetector_backend.contract import EvidenceManifest, FrameManifest
from dokodetector_backend.models import EvidenceFrame, EvidencePackage, VisionResult


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
class StoredVisionResult:
    """Immutable detector result metadata stored in SQLite."""

    result_id: UUID
    package_id: UUID
    schema_version: str
    detector_name: str
    detector_version: str
    status: str
    selected_card: str | None
    calibration: str
    result_json: str
    result_sha256: str
    relative_path: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class VisionResultInsert:
    """The result of an idempotent vision-result insert."""

    result: StoredVisionResult
    created: bool


class RepositoryError(RuntimeError):
    """Unexpected database failure."""


class RepositoryConflict(RepositoryError):
    """A package cannot be stored because a unique key is already used."""


class PackageConflict(RepositoryConflict):
    """The package ID is already stored."""


class LogicalEventConflict(RepositoryConflict):
    """The session and event sequence are already stored."""


class VisionResultConflict(RepositoryConflict):
    """A detector result key is already used by different content."""


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
        self, detector_name: str, detector_version: str
    ) -> StoredPackage | None:
        """Return the first stored package without this detector result."""

        with self._session_factory() as session:
            row = session.scalar(
                select(EvidencePackage)
                .options(selectinload(EvidencePackage.frames))
                .outerjoin(
                    VisionResult,
                    and_(
                        VisionResult.package_id == EvidencePackage.package_id,
                        VisionResult.detector_name == detector_name,
                        VisionResult.detector_version == detector_version,
                    ),
                )
                .where(
                    EvidencePackage.state == "stored",
                    VisionResult.result_id.is_(None),
                )
                .order_by(EvidencePackage.received_at, EvidencePackage.package_id)
                .limit(1)
            )
            return _package_from_model(row) if row is not None else None

    def list_pending_packages(
        self, detector_name: str, detector_version: str
    ) -> tuple[StoredPackage, ...]:
        """Return all stored packages without this detector result."""

        with self._session_factory() as session:
            rows = session.scalars(
                select(EvidencePackage)
                .options(selectinload(EvidencePackage.frames))
                .outerjoin(
                    VisionResult,
                    and_(
                        VisionResult.package_id == EvidencePackage.package_id,
                        VisionResult.detector_name == detector_name,
                        VisionResult.detector_version == detector_version,
                    ),
                )
                .where(
                    EvidencePackage.state == "stored",
                    VisionResult.result_id.is_(None),
                )
                .order_by(EvidencePackage.received_at, EvidencePackage.package_id)
            )
            return tuple(_package_from_model(row) for row in rows)

    def get_vision_result(self, result_id: UUID | str) -> StoredVisionResult | None:
        """Read one stored detector result."""

        with self._session_factory() as session:
            row = session.get(VisionResult, str(result_id))
            return _vision_result_from_model(row) if row is not None else None

    def get_vision_result_for_detector(
        self,
        package_id: UUID | str,
        detector_name: str,
        detector_version: str,
    ) -> StoredVisionResult | None:
        """Read the result for one package and detector version."""

        with self._session_factory() as session:
            row = session.scalar(
                select(VisionResult).where(
                    VisionResult.package_id == str(package_id),
                    VisionResult.detector_name == detector_name,
                    VisionResult.detector_version == detector_version,
                )
            )
            return _vision_result_from_model(row) if row is not None else None

    def list_vision_results(self, package_id: UUID | str) -> tuple[StoredVisionResult, ...]:
        """Read all results in deterministic creation order."""

        with self._session_factory() as session:
            rows = session.scalars(
                select(VisionResult)
                .where(VisionResult.package_id == str(package_id))
                .order_by(VisionResult.created_at, VisionResult.result_id)
            )
            return tuple(_vision_result_from_model(row) for row in rows)

    def insert_vision_result(
        self,
        result: VisionDetectionResult,
        result_bytes: bytes,
        relative_path: str,
    ) -> VisionResultInsert:
        """Insert one result, or return an exact existing replay."""

        if not isinstance(result_bytes, bytes):
            raise TypeError("result_bytes must be bytes.")
        try:
            result_json = result_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("result_bytes must be UTF-8 JSON.") from error

        existing = self.get_vision_result(result.result_id)
        if existing is not None:
            return _resolve_vision_result_replay(existing, result, result_json)
        existing = self.get_vision_result_for_detector(
            result.package_id,
            result.detector.name,
            result.detector.version,
        )
        if existing is not None:
            return _resolve_vision_result_replay(existing, result, result_json)

        row = VisionResult(
            result_id=str(result.result_id),
            package_id=str(result.package_id),
            schema_version=result.schema_version,
            detector_name=result.detector.name,
            detector_version=result.detector.version,
            status=result.status,
            selected_card=result.selected_card,
            calibration=result.calibration,
            result_json=result_json,
            result_sha256=_sha256(result_bytes),
            relative_path=relative_path,
            created_at=result.created_at,
        )
        try:
            with self._session_factory.begin() as session:
                session.add(row)
                session.flush()
                stored = _vision_result_from_model(row)
        except IntegrityError as error:
            existing = self.get_vision_result(result.result_id) or (
                self.get_vision_result_for_detector(
                    result.package_id,
                    result.detector.name,
                    result.detector.version,
                )
            )
            if existing is not None:
                return _resolve_vision_result_replay(existing, result, result_json)
            raise RepositoryError("The vision result could not be stored.") from error
        return VisionResultInsert(result=stored, created=True)

    def delete_vision_result(
        self, result_id: UUID | str, *, result_sha256: str | None = None
    ) -> bool:
        """Delete one result during persistence compensation."""

        with self._session_factory.begin() as session:
            row = session.get(VisionResult, str(result_id))
            if row is None or (result_sha256 is not None and row.result_sha256 != result_sha256):
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


def _vision_result_from_model(row: VisionResult) -> StoredVisionResult:
    return StoredVisionResult(
        result_id=UUID(row.result_id),
        package_id=UUID(row.package_id),
        schema_version=row.schema_version,
        detector_name=row.detector_name,
        detector_version=row.detector_version,
        status=row.status,
        selected_card=row.selected_card,
        calibration=row.calibration,
        result_json=row.result_json,
        result_sha256=row.result_sha256,
        relative_path=row.relative_path,
        created_at=_as_utc(row.created_at),
    )


def _resolve_vision_result_replay(
    existing: StoredVisionResult,
    result: VisionDetectionResult,
    result_json: str,
) -> VisionResultInsert:
    if (
        existing.package_id == result.package_id
        and existing.detector_name == result.detector.name
        and existing.detector_version == result.detector.version
        and existing.result_id == result.result_id
        and existing.result_json == result_json
    ):
        return VisionResultInsert(result=existing, created=False)
    raise VisionResultConflict("The detector result key is already stored with different content.")


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
    "StoredVisionResult",
    "VisionResultConflict",
    "VisionResultInsert",
    "create_database_engine",
    "upgrade_database",
]
