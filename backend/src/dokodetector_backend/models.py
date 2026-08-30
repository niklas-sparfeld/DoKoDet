"""SQLAlchemy models for stored evidence metadata."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    table_observations: Mapped[list[TableObservation]] = relationship(
        back_populates="package",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TableObservation.created_at",
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


class TableObservation(Base):
    """One immutable table observation for an accepted evidence package."""

    __tablename__ = "table_observations"
    __table_args__ = (
        UniqueConstraint(
            "package_id",
            "analyzer_name",
            "analyzer_version",
            name="uq_table_observations_package_analyzer",
        ),
    )

    observation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    package_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("evidence_packages.package_id", ondelete="CASCADE"),
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analyzer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    calibration: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_json: Mapped[str] = mapped_column(Text, nullable=False)
    observation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    package: Mapped[EvidencePackage] = relationship(back_populates="table_observations")


class RepositoryBundleIndex(Base):
    """Search metadata for one accepted shared repository bundle."""

    __tablename__ = "repository_bundles"

    recording_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    source_asset_id: Mapped[str] = mapped_column(String(256), nullable=False)
    video_id: Mapped[str] = mapped_column(String(256), nullable=False)
    session_id: Mapped[str] = mapped_column(String(256), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    task_enrollment_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_run_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    bundle_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RoundAnalysis(Base):
    """Durable status and result metadata for one round analysis."""

    __tablename__ = "round_analyses"

    analysis_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recording_id: Mapped[str] = mapped_column(String(256), nullable=False)
    round_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    total_evidence_packages: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_evidence_packages: Mapped[int] = mapped_column(Integer, nullable=False)
    result_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    input_artifact_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    input_artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_artifact_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    result_artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "Base",
    "EvidenceFrame",
    "EvidencePackage",
    "RepositoryBundleIndex",
    "RoundAnalysis",
    "TableObservation",
]
