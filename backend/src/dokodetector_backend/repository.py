"""SQLite repository for evidence package metadata."""

from __future__ import annotations

import json
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
from dokodetector_backend.contract import (
    EvidenceManifest,
    FrameManifest,
    parse_manifest_bytes,
)
from dokodetector_backend.evidence_package_storage import (
    EvidencePackageStorage,
    calculate_bundle_fingerprint,
)
from dokodetector_backend.intake_contract import (
    EvidencePackageBundle,
    IntakeContractError,
    parse_evidence_package_bundle,
    validate_evidence_package_bundle,
)
from dokodetector_backend.models import (
    EvidenceFrame,
    EvidencePackage,
    RoundAnalysis,
)
from dokodetector_backend.models import (
    TableObservation as TableObservationRow,
)
from dokodetector_backend.round_analysis_contract import (
    RoundAnalysisCreateRequest,
    canonical_analysis_request_bytes,
    canonical_analysis_request_sha256,
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


@dataclass(frozen=True, slots=True)
class StoredRoundAnalysis:
    """Durable analysis status and artifact metadata stored in SQLite."""

    analysis_id: UUID
    recording_id: str
    round_id: str
    session_id: UUID
    request_json: str
    request_sha256: str
    state: str
    total_evidence_packages: int
    completed_evidence_packages: int
    result_status: str | None
    result_json: str | None
    error: str | None
    input_artifact_id: str | None
    input_artifact_sha256: str | None
    result_artifact_id: str | None
    result_artifact_sha256: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_request(
        cls,
        request: RoundAnalysisCreateRequest,
        *,
        created_at: datetime | None = None,
    ) -> StoredRoundAnalysis:
        """Build a queued row from one validated client request."""

        if created_at is None:
            created_at = datetime.now(timezone.utc)
        request_bytes = canonical_analysis_request_bytes(request)
        return cls(
            analysis_id=request.analysis_id,
            recording_id=request.recording_id,
            round_id=request.round_id,
            session_id=request.session_id,
            request_json=request_bytes.decode("utf-8"),
            request_sha256=canonical_analysis_request_sha256(request),
            state="queued",
            total_evidence_packages=len(request.evidence_package_ids),
            completed_evidence_packages=0,
            result_status=None,
            result_json=None,
            error=None,
            input_artifact_id=None,
            input_artifact_sha256=None,
            result_artifact_id=None,
            result_artifact_sha256=None,
            created_at=created_at,
            started_at=None,
            completed_at=None,
        )


@dataclass(frozen=True, slots=True)
class RoundAnalysisInsert:
    """The result of an idempotent analysis insert."""

    analysis: StoredRoundAnalysis
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


class RoundAnalysisConflict(RepositoryConflict):
    """An analysis ID is already stored with different request content."""


class RoundAnalysisNotFound(RepositoryError):
    """The requested round analysis does not exist."""


class RepositoryRebuildError(RepositoryError):
    """The canonical evidence-package intake cannot rebuild the index."""


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

    def rebuild_from_intake(self, storage: EvidencePackageStorage) -> tuple[StoredPackage, ...]:
        """Rebuild package search rows from canonical repository bundles."""

        rebuilt: list[StoredPackage] = []
        root = storage.root
        for package_path in (
            sorted(root.iterdir(), key=lambda item: item.name) if root.is_dir() else ()
        ):
            if not package_path.is_dir() or package_path.name.startswith("."):
                continue
            try:
                files = storage.file_digests(package_path.name)
                manifest_bytes = (package_path / "manifest.json").read_bytes()
                bundle = parse_evidence_package_bundle(manifest_bytes)
                package_files = {
                    relative_path: (package_path / relative_path).read_bytes()
                    for relative_path in files
                    if relative_path != "manifest.json"
                }
                evidence_manifest = package_files[bundle.files.evidence_manifest.relative_path]
                package_record = package_files[bundle.files.package_record.relative_path]
                task_enrollment = package_files[bundle.files.task_enrollment.relative_path]
                lineage = package_files[bundle.files.lineage.relative_path]
                validate_evidence_package_bundle(
                    manifest_bytes,
                    evidence_manifest,
                    package_record,
                    task_enrollment,
                    lineage,
                    package_files,
                )
                original = parse_manifest_bytes(evidence_manifest)
                if str(original.package_id) != bundle.package_id:
                    raise RepositoryRebuildError(
                        "evidence manifest package_id differs from repository bundle"
                    )
                _assert_evidence_package_files(bundle, original, files)
                enrollment_document = json.loads(task_enrollment.decode("utf-8"))
                received_at = min(
                    datetime.fromisoformat(item["created_at_utc"].replace("Z", "+00:00"))
                    for item in enrollment_document["enrollments"]
                )
                frames = tuple(
                    StoredFrame.from_manifest(
                        frame,
                        relative_path=f"frames/{frame.part_name}.jpg",
                    )
                    for frame in original.frames
                )
                rebuilt.append(
                    StoredPackage.from_manifest(
                        original,
                        evidence_manifest,
                        package_fingerprint=calculate_bundle_fingerprint(files),
                        frames=frames,
                        received_at=_as_utc(received_at),
                    )
                )
            except RepositoryRebuildError:
                raise
            except (OSError, KeyError, TypeError, ValueError, IntakeContractError) as error:
                raise RepositoryRebuildError(
                    f"Canonical evidence package {package_path.name} is invalid: {error}"
                ) from error

        try:
            with self._session_factory.begin() as session:
                session.query(TableObservationRow).delete()
                session.query(EvidencePackage).delete()
                session.add_all(_package_to_model(item) for item in rebuilt)
        except IntegrityError as error:
            raise RepositoryRebuildError(
                "The evidence package index could not be rebuilt."
            ) from error
        return tuple(rebuilt)

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


class RoundAnalysisRepository:
    """Persist the lifecycle and result metadata for round analyses."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._session_factory = sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
        )

    def get(self, analysis_id: UUID | str) -> StoredRoundAnalysis | None:
        """Read one analysis row."""

        with self._session_factory() as session:
            row = session.get(RoundAnalysis, str(UUID(str(analysis_id))))
            return _round_analysis_from_model(row) if row is not None else None

    def create(
        self,
        request: RoundAnalysisCreateRequest,
        *,
        created_at: datetime | None = None,
    ) -> RoundAnalysisInsert:
        """Canonicalize and insert one validated client request."""

        return_value, created = self.insert(
            StoredRoundAnalysis.from_request(request, created_at=created_at)
        )
        return RoundAnalysisInsert(analysis=return_value, created=created)

    def insert(self, analysis: StoredRoundAnalysis) -> tuple[StoredRoundAnalysis, bool]:
        """Insert one analysis or return an identical existing request."""

        try:
            with self._session_factory.begin() as session:
                existing = session.get(RoundAnalysis, str(analysis.analysis_id))
                if existing is not None:
                    stored = _round_analysis_from_model(existing)
                    if (
                        stored.request_sha256 != analysis.request_sha256
                        or stored.request_json != analysis.request_json
                    ):
                        raise RoundAnalysisConflict(
                            "The analysis ID is already stored with different request content."
                        )
                    return stored, False
                row = _round_analysis_to_model(analysis)
                session.add(row)
                session.flush()
                return _round_analysis_from_model(row), True
        except RoundAnalysisConflict:
            raise
        except IntegrityError as error:
            existing = self.get(analysis.analysis_id)
            if existing is not None and (
                existing.request_sha256 == analysis.request_sha256
                and existing.request_json == analysis.request_json
            ):
                return existing, False
            if existing is not None:
                raise RoundAnalysisConflict(
                    "The analysis ID is already stored with different request content."
                ) from error
            raise RepositoryError("The round analysis could not be stored.") from error

    def update_progress(
        self,
        analysis_id: UUID | str,
        *,
        state: str,
        completed: int,
        started_at: datetime | None = None,
    ) -> StoredRoundAnalysis:
        """Update a non-terminal state and its completed package count."""

        if state not in {"queued", "analyzing_evidence", "reconstructing"}:
            raise ValueError("progress state must be non-terminal.")
        if completed < 0:
            raise ValueError("completed evidence packages must not be negative.")
        with self._session_factory.begin() as session:
            row = _get_round_analysis_row(session, analysis_id)
            if row.state in {"complete", "failed"}:
                raise ValueError("a terminal analysis cannot receive progress updates.")
            allowed_states = {
                "queued": {"queued", "analyzing_evidence"},
                "analyzing_evidence": {"analyzing_evidence", "reconstructing"},
                "reconstructing": {"reconstructing"},
            }
            if state not in allowed_states[row.state]:
                raise ValueError(f"analysis state cannot change from {row.state} to {state}.")
            if completed > row.total_evidence_packages:
                raise ValueError("completed evidence packages cannot exceed the total.")
            row.state = state
            row.completed_evidence_packages = completed
            if started_at is not None:
                row.started_at = started_at
            elif state != "queued" and row.started_at is None:
                row.started_at = datetime.now(timezone.utc)
            return _round_analysis_from_model(row)

    def mark_complete(
        self,
        analysis_id: UUID | str,
        *,
        result_status: str,
        result_json: str,
        input_artifact_id: str,
        input_artifact_sha256: str,
        result_artifact_id: str,
        result_artifact_sha256: str,
        completed_at: datetime | None = None,
    ) -> StoredRoundAnalysis:
        """Store a complete reconstruction result and its artifact references."""

        if result_status not in {"resolved", "ambiguous", "incomplete", "impossible"}:
            raise ValueError("invalid reconstruction result status.")
        if not result_json:
            raise ValueError("a complete analysis needs a result status and JSON.")
        if completed_at is None:
            completed_at = datetime.now(timezone.utc)
        with self._session_factory.begin() as session:
            row = _get_round_analysis_row(session, analysis_id)
            if row.state in {"complete", "failed"}:
                raise ValueError("a terminal analysis cannot be completed again.")
            row.state = "complete"
            row.completed_evidence_packages = row.total_evidence_packages
            row.result_status = result_status
            row.result_json = result_json
            row.error = None
            row.input_artifact_id = input_artifact_id
            row.input_artifact_sha256 = input_artifact_sha256
            row.result_artifact_id = result_artifact_id
            row.result_artifact_sha256 = result_artifact_sha256
            row.completed_at = completed_at
            return _round_analysis_from_model(row)

    def mark_failed(
        self,
        analysis_id: UUID | str,
        error: str,
        *,
        completed_at: datetime | None = None,
    ) -> StoredRoundAnalysis:
        """Store a short safe terminal failure message."""

        if not error or len(error) > 512:
            raise ValueError("analysis errors must contain 1 to 512 characters.")
        if completed_at is None:
            completed_at = datetime.now(timezone.utc)
        with self._session_factory.begin() as session:
            row = _get_round_analysis_row(session, analysis_id)
            if row.state in {"complete", "failed"}:
                raise ValueError("a terminal analysis cannot be failed again.")
            row.state = "failed"
            row.result_status = None
            row.result_json = None
            row.error = error
            row.result_artifact_id = None
            row.result_artifact_sha256 = None
            row.completed_at = completed_at
            return _round_analysis_from_model(row)

    def fail_non_terminal(self, *, now: datetime | None = None) -> int:
        """Convert all interrupted analyses to a clear restart failure."""

        if now is None:
            now = datetime.now(timezone.utc)
        converted = 0
        with self._session_factory.begin() as session:
            rows = session.scalars(
                select(RoundAnalysis).where(RoundAnalysis.state.not_in(("complete", "failed")))
            )
            for row in rows:
                row.state = "failed"
                row.result_status = None
                row.result_json = None
                row.error = RESTART_ANALYSIS_ERROR
                row.result_artifact_id = None
                row.result_artifact_sha256 = None
                row.completed_at = now
                converted += 1
        return converted


RESTART_ANALYSIS_ERROR = "The analysis did not finish before the backend restarted."


def _get_round_analysis_row(session: Session, analysis_id: UUID | str) -> RoundAnalysis:
    row = session.get(RoundAnalysis, str(UUID(str(analysis_id))))
    if row is None:
        raise RoundAnalysisNotFound("The round analysis was not found.")
    return row


def _round_analysis_to_model(analysis: StoredRoundAnalysis) -> RoundAnalysis:
    return RoundAnalysis(
        analysis_id=str(analysis.analysis_id),
        recording_id=analysis.recording_id,
        round_id=analysis.round_id,
        session_id=str(analysis.session_id),
        request_json=analysis.request_json,
        request_sha256=analysis.request_sha256,
        state=analysis.state,
        total_evidence_packages=analysis.total_evidence_packages,
        completed_evidence_packages=analysis.completed_evidence_packages,
        result_status=analysis.result_status,
        result_json=analysis.result_json,
        error=analysis.error,
        input_artifact_id=analysis.input_artifact_id,
        input_artifact_sha256=analysis.input_artifact_sha256,
        result_artifact_id=analysis.result_artifact_id,
        result_artifact_sha256=analysis.result_artifact_sha256,
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
    )


def _round_analysis_from_model(row: RoundAnalysis) -> StoredRoundAnalysis:
    return StoredRoundAnalysis(
        analysis_id=UUID(row.analysis_id),
        recording_id=row.recording_id,
        round_id=row.round_id,
        session_id=UUID(row.session_id),
        request_json=row.request_json,
        request_sha256=row.request_sha256,
        state=row.state,
        total_evidence_packages=row.total_evidence_packages,
        completed_evidence_packages=row.completed_evidence_packages,
        result_status=row.result_status,
        result_json=row.result_json,
        error=row.error,
        input_artifact_id=row.input_artifact_id,
        input_artifact_sha256=row.input_artifact_sha256,
        result_artifact_id=row.result_artifact_id,
        result_artifact_sha256=row.result_artifact_sha256,
        created_at=_as_utc(row.created_at),
        started_at=_as_utc(row.started_at) if row.started_at is not None else None,
        completed_at=_as_utc(row.completed_at) if row.completed_at is not None else None,
    )


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


def _assert_evidence_package_files(
    bundle: EvidencePackageBundle,
    evidence_manifest: EvidenceManifest,
    files: dict[str, object],
) -> None:
    """Verify that canonical paths and media descriptors match the original manifest."""

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
        raise RepositoryRebuildError("canonical evidence package has unexpected files")

    descriptors = [
        bundle.files.evidence_manifest,
        bundle.files.package_record,
        bundle.files.task_enrollment,
        bundle.files.lineage,
        *bundle.files.frames,
    ]
    if bundle.files.video_snippet is not None:
        descriptors.append(bundle.files.video_snippet)
    for descriptor in descriptors:
        stored = files.get(descriptor.relative_path)
        if stored is None or (
            stored.byte_length != descriptor.byte_length or stored.sha256 != descriptor.sha256
        ):
            raise RepositoryRebuildError(
                f"canonical evidence package member {descriptor.relative_path!r} is invalid"
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
    "RepositoryRebuildError",
    "RESTART_ANALYSIS_ERROR",
    "RoundAnalysisConflict",
    "RoundAnalysisInsert",
    "RoundAnalysisNotFound",
    "RoundAnalysisRepository",
    "StoredFrame",
    "StoredPackage",
    "StoredRoundAnalysis",
    "StoredTableObservation",
    "TableObservationConflict",
    "TableObservationInsert",
    "create_database_engine",
    "upgrade_database",
]
