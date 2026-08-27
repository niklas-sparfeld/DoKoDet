"""SQLite metadata for immutable training-recording bundles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from dokodetector_backend.models import EvidencePackage, TrainingRecording
from dokodetector_backend.recording_storage import StoredFile


@dataclass(frozen=True, slots=True)
class StoredTrainingRecording:
    """Metadata for one accepted recording and its derived files."""

    recording_id: str
    schema_version: str
    session_id: str
    video_id: str
    started_at_utc: str
    ended_at_utc: str
    duration_s: float
    manifest_json: str
    manifest_sha256: str
    video: StoredFile
    predictions: StoredFile
    recording_fingerprint: str
    state: str
    received_at: datetime
    derived_state: str
    dataset_record: StoredFile
    candidate_queue: StoredFile | None


class TrainingRecordingRepositoryError(RuntimeError):
    """Unexpected database failure while storing recording metadata."""


class TrainingRecordingConflict(TrainingRecordingRepositoryError):
    """A recording ID is already used by different content."""


class TrainingRecordingRepository:
    """Read and write training-recording metadata in SQLite."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._session_factory = sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
        )

    def get(self, recording_id: str) -> StoredTrainingRecording | None:
        """Return one recording by its client-generated ID."""

        with self._session_factory() as session:
            row = session.get(TrainingRecording, recording_id)
            return _from_model(row) if row is not None else None

    def count_evidence_packages(self, session_id: str) -> int:
        """Count evidence packages related by canonical session ID."""

        with self._session_factory() as session:
            count = session.scalar(
                select(func.count())
                .select_from(EvidencePackage)
                .where(EvidencePackage.session_id == session_id)
            )
            return int(count or 0)

    def insert(self, recording: StoredTrainingRecording) -> StoredTrainingRecording:
        """Insert one recording atomically, rejecting a different replay."""

        row = _to_model(recording)
        try:
            with self._session_factory.begin() as session:
                existing = session.get(TrainingRecording, recording.recording_id)
                if existing is not None:
                    raise TrainingRecordingConflict(
                        "The recording ID is already stored with different content."
                    )
                session.add(row)
                session.flush()
                return _from_model(row)
        except TrainingRecordingConflict:
            raise
        except IntegrityError as error:
            existing = self.get(recording.recording_id)
            if existing is not None:
                raise TrainingRecordingConflict(
                    "The recording ID is already stored with different content."
                ) from error
            raise TrainingRecordingRepositoryError(
                "The recording metadata could not be stored."
            ) from error


def _to_model(recording: StoredTrainingRecording) -> TrainingRecording:
    return TrainingRecording(
        recording_id=recording.recording_id,
        schema_version=recording.schema_version,
        session_id=recording.session_id,
        video_id=recording.video_id,
        started_at_utc=recording.started_at_utc,
        ended_at_utc=recording.ended_at_utc,
        duration_s=recording.duration_s,
        manifest_json=recording.manifest_json,
        manifest_sha256=recording.manifest_sha256,
        video_byte_length=recording.video.byte_length,
        video_sha256=recording.video.sha256,
        video_relative_path=recording.video.relative_path,
        predictions_byte_length=recording.predictions.byte_length,
        predictions_sha256=recording.predictions.sha256,
        predictions_relative_path=recording.predictions.relative_path,
        recording_fingerprint=recording.recording_fingerprint,
        state=recording.state,
        received_at=recording.received_at,
        derived_state=recording.derived_state,
        dataset_record_byte_length=recording.dataset_record.byte_length,
        dataset_record_sha256=recording.dataset_record.sha256,
        dataset_record_relative_path=recording.dataset_record.relative_path,
        candidate_queue_byte_length=(
            recording.candidate_queue.byte_length if recording.candidate_queue is not None else None
        ),
        candidate_queue_sha256=(
            recording.candidate_queue.sha256 if recording.candidate_queue is not None else None
        ),
        candidate_queue_relative_path=(
            recording.candidate_queue.relative_path
            if recording.candidate_queue is not None
            else None
        ),
    )


def _from_model(row: TrainingRecording) -> StoredTrainingRecording:
    return StoredTrainingRecording(
        recording_id=row.recording_id,
        schema_version=row.schema_version,
        session_id=row.session_id,
        video_id=row.video_id,
        started_at_utc=row.started_at_utc,
        ended_at_utc=row.ended_at_utc,
        duration_s=row.duration_s,
        manifest_json=row.manifest_json,
        manifest_sha256=row.manifest_sha256,
        video=StoredFile(
            relative_path=row.video_relative_path,
            byte_length=row.video_byte_length,
            sha256=row.video_sha256,
        ),
        predictions=StoredFile(
            relative_path=row.predictions_relative_path,
            byte_length=row.predictions_byte_length,
            sha256=row.predictions_sha256,
        ),
        recording_fingerprint=row.recording_fingerprint,
        state=row.state,
        received_at=_as_utc(row.received_at),
        derived_state=row.derived_state,
        dataset_record=StoredFile(
            relative_path=row.dataset_record_relative_path,
            byte_length=row.dataset_record_byte_length,
            sha256=row.dataset_record_sha256,
        ),
        candidate_queue=(
            StoredFile(
                relative_path=row.candidate_queue_relative_path,
                byte_length=row.candidate_queue_byte_length,
                sha256=row.candidate_queue_sha256,
            )
            if row.candidate_queue_relative_path is not None
            and row.candidate_queue_byte_length is not None
            and row.candidate_queue_sha256 is not None
            else None
        ),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "StoredTrainingRecording",
    "TrainingRecordingConflict",
    "TrainingRecordingRepository",
    "TrainingRecordingRepositoryError",
]
