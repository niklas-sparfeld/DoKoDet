"""SQLAlchemy models for stored evidence metadata."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for the backend database models."""


class EvidencePackage(Base):
    """One accepted evidence package."""

    __tablename__ = "evidence_packages"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "event_sequence",
            name="uq_evidence_packages_session_event",
        ),
    )

    package_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    package_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    frames: Mapped[list[EvidenceFrame]] = relationship(
        back_populates="package",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EvidenceFrame.id",
    )
    vision_results: Mapped[list[VisionResult]] = relationship(
        back_populates="package",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="VisionResult.created_at",
    )


class EvidenceFrame(Base):
    """Metadata for one frame stored with an evidence package."""

    __tablename__ = "evidence_frames"
    __table_args__ = (
        UniqueConstraint(
            "package_id",
            "part_name",
            name="uq_evidence_frames_package_part",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("evidence_packages.package_id", ondelete="CASCADE"),
        nullable=False,
    )
    part_name: Mapped[str] = mapped_column(String(64), nullable=False)
    target_offset_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_offset_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    session_elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)

    package: Mapped[EvidencePackage] = relationship(back_populates="frames")


class VisionResult(Base):
    """One immutable detector result for an accepted evidence package."""

    __tablename__ = "vision_results"
    __table_args__ = (
        UniqueConstraint(
            "package_id",
            "detector_name",
            "detector_version",
            name="uq_vision_results_package_detector",
        ),
    )

    result_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    package_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("evidence_packages.package_id", ondelete="CASCADE"),
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    detector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    selected_card: Mapped[str | None] = mapped_column(String(32), nullable=True)
    calibration: Mapped[str] = mapped_column(String(32), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    package: Mapped[EvidencePackage] = relationship(back_populates="vision_results")


class TrainingRecording(Base):
    """One immutable training-recording bundle accepted by the backend."""

    __tablename__ = "training_recordings"

    recording_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(256), nullable=False)
    video_id: Mapped[str] = mapped_column(String(256), nullable=False)
    started_at_utc: Mapped[str] = mapped_column(String(64), nullable=False)
    ended_at_utc: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    video_byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    video_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    video_relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    predictions_byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    predictions_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    predictions_relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    recording_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    derived_state: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_record_byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    dataset_record_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_record_relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    candidate_queue_byte_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidate_queue_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_queue_relative_path: Mapped[str | None] = mapped_column(String(512), nullable=True)


__all__ = [
    "Base",
    "EvidenceFrame",
    "EvidencePackage",
    "TrainingRecording",
    "VisionResult",
]
