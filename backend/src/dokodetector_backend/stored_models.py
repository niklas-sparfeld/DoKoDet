"""Typed projections of canonical filesystem resources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from dokodetector_backend.contract import EvidenceManifest, FrameManifest
from dokodetector_backend.round_analysis_contract import (
    RoundAnalysisCreateRequest,
    canonical_analysis_request_bytes,
    canonical_analysis_request_sha256,
)


@dataclass(frozen=True, slots=True)
class StoredFrame:
    """Frame metadata projected from an accepted evidence package."""

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
        """Build a stored frame from one validated manifest frame."""

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
    """Evidence-package metadata projected from canonical files."""

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
        """Build a stored package from validated canonical files."""

        import hashlib

        return cls(
            package_id=manifest.package_id,
            schema_version=manifest.schema_version,
            session_id=manifest.session.session_id,
            event_sequence=manifest.session.event_sequence,
            event_time_ms=manifest.event.event_time_ms,
            manifest_json=manifest_bytes.decode("utf-8"),
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            package_fingerprint=package_fingerprint,
            state="stored",
            received_at=received_at,
            frames=frames,
        )


@dataclass(frozen=True, slots=True)
class StoredTableObservation:
    """Table-observation metadata projected from an immutable observation file."""

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
class StoredRoundAnalysis:
    """Round-analysis lifecycle and result metadata projected from state.json."""

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
        """Build a queued analysis projection from one validated request."""

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


__all__ = ["StoredFrame", "StoredPackage", "StoredRoundAnalysis", "StoredTableObservation"]
