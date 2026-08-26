"""Pydantic models and validation for the shared V1 evidence contract."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from dokodetector_backend.errors import ContractError, validation_details

EVIDENCE_SCHEMA_VERSION = "cardevent-evidence/v1"
SUPPORTED_CONTENT_TYPE = "image/jpeg"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ContractModel(BaseModel):
    """Base model with a closed JSON shape."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SessionMetadata(ContractModel):
    """The capture session and logical event identity."""

    session_id: UUID
    event_sequence: int = Field(ge=1)


class EventMetadata(ContractModel):
    """The causal event selected by the client decoder."""

    event_time_ms: int = Field(ge=0)
    emitted_at_ms: int = Field(ge=0)
    evidence_complete: bool

    @model_validator(mode="after")
    def validate_causal_time(self) -> EventMetadata:
        if self.emitted_at_ms < self.event_time_ms:
            raise ValueError("event.emitted_at_ms must be at or after event.event_time_ms.")
        return self


class ModelMetadata(ContractModel):
    """The client model metadata stored by the backend."""

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=256)
    weights_sha256: Sha256
    preprocessing: str = Field(min_length=1, max_length=128)


class EventDecoderMetadata(ContractModel):
    """The frozen causal decoder configuration."""

    algorithm: str = Field(min_length=1, max_length=128)
    threshold: float = Field(ge=0.0, le=1.0)
    peak_confirmation_ms: int = Field(ge=0)
    minimum_event_gap_ms: int = Field(ge=0)
    target_inference_hz: float = Field(gt=0.0)

    @field_validator("threshold", "target_inference_hz")
    @classmethod
    def require_finite_number(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("decoder values must be finite.")
        return value


class EvidenceCaptureMetadata(ContractModel):
    """The bounded evidence sampler configuration."""

    sample_hz: float = Field(gt=0.0)
    jpeg_quality: float = Field(gt=0.0, le=1.0)
    ring_duration_ms: int = Field(gt=0)
    target_offsets_ms: list[int] = Field(min_length=1)
    maximum_lookup_distance_ms: int = Field(ge=0)
    finalization_delay_ms: int = Field(ge=0)

    @field_validator("sample_hz", "jpeg_quality")
    @classmethod
    def require_finite_number(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("capture values must be finite.")
        return value


class CameraMetadata(ContractModel):
    """The camera format used for evidence capture."""

    position: Literal["back", "front"]
    orientation: str = Field(min_length=1, max_length=64)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class FrameManifest(ContractModel):
    """One submitted JPEG frame declaration."""

    part_name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    target_offset_ms: int
    actual_offset_ms: int
    session_elapsed_ms: int = Field(ge=0)
    captured_at_utc: datetime
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    byte_length: int = Field(gt=0)
    content_type: Literal["image/jpeg"]
    sha256: Sha256

    @field_validator("captured_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at_utc must include a UTC offset.")
        if value.utcoffset() != timedelta(0):
            raise ValueError("captured_at_utc must use UTC.")
        return value.astimezone(timezone.utc)


class ScoreTraceEntry(ContractModel):
    """One decoder score at a session-relative time."""

    session_elapsed_ms: int = Field(ge=0)
    score: float = Field(ge=0.0, le=1.0)

    @field_validator("score")
    @classmethod
    def require_finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite.")
        return value


class ClientMetadata(ContractModel):
    """Client build and device model metadata."""

    app_version: str = Field(min_length=1, max_length=128)
    build: str = Field(min_length=1, max_length=128)
    device_model_identifier: str = Field(min_length=1, max_length=128)
    os_version: str = Field(min_length=1, max_length=128)


class EvidenceManifest(ContractModel):
    """The complete shared V1 manifest."""

    schema_version: Literal["cardevent-evidence/v1"]
    package_id: UUID
    session: SessionMetadata
    event: EventMetadata
    model: ModelMetadata
    event_decoder: EventDecoderMetadata
    evidence_capture: EvidenceCaptureMetadata
    camera: CameraMetadata
    frames: list[FrameManifest]
    missing_frame_targets_ms: list[int]
    score_trace: list[ScoreTraceEntry]
    client: ClientMetadata

    @model_validator(mode="after")
    def validate_consistency(self) -> EvidenceManifest:
        configured = self.evidence_capture.target_offsets_ms
        if len(configured) != len(set(configured)):
            raise ValueError("evidence_capture.target_offsets_ms must not contain duplicates.")

        missing = self.missing_frame_targets_ms
        if len(missing) != len(set(missing)):
            raise ValueError("missing_frame_targets_ms must not contain duplicates.")

        part_names = [frame.part_name for frame in self.frames]
        if len(part_names) != len(set(part_names)):
            raise ValueError("frames.part_name values must be unique.")

        present = [frame.target_offset_ms for frame in self.frames]
        if len(present) != len(set(present)):
            raise ValueError("frame target offsets must be unique.")

        present_targets = set(present)
        missing_targets = set(missing)
        configured_targets = set(configured)
        if present_targets & missing_targets:
            raise ValueError("a frame target cannot be both present and missing.")
        if present_targets | missing_targets != configured_targets:
            raise ValueError(
                "present and missing frame targets must equal the configured target set."
            )

        if self.event.evidence_complete != (not missing):
            raise ValueError(
                "event.evidence_complete must be true only when no frame targets are missing."
            )

        trace_times = [entry.session_elapsed_ms for entry in self.score_trace]
        if trace_times != sorted(trace_times):
            raise ValueError("score_trace session_elapsed_ms values must be ordered.")
        return self


class UploadResponse(ContractModel):
    """The response returned after a package is accepted."""

    package_id: UUID
    state: Literal["stored"]
    created: bool
    received_at: datetime


def parse_manifest_bytes(
    manifest_bytes: bytes, *, max_bytes: int | None = None
) -> EvidenceManifest:
    """Parse and validate immutable manifest bytes."""

    if not isinstance(manifest_bytes, bytes):
        raise TypeError("manifest_bytes must be bytes.")
    if not manifest_bytes:
        raise ContractError("invalid_manifest", "The manifest is empty.")
    if max_bytes is not None and len(manifest_bytes) > max_bytes:
        raise ContractError(
            "manifest_too_large",
            "The manifest exceeds the configured size limit.",
            status_code=413,
        )

    try:
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError("invalid_manifest", "The manifest is not valid UTF-8 JSON.") from error
    if not isinstance(payload, dict):
        raise ContractError("invalid_manifest", "The manifest JSON value must be an object.")

    try:
        return EvidenceManifest.model_validate(payload)
    except ValidationError as error:
        raise ContractError(
            "invalid_manifest",
            "The manifest failed validation.",
            details=validation_details(error),
        ) from error


def validate_manifest(payload: Mapping[str, object]) -> EvidenceManifest:
    """Validate a decoded manifest mapping."""

    try:
        return EvidenceManifest.model_validate(payload)
    except ValidationError as error:
        raise ContractError(
            "invalid_manifest",
            "The manifest failed validation.",
            details=validation_details(error),
        ) from error


def validate_package_id(path_package_id: str | UUID, manifest: EvidenceManifest) -> None:
    """Ensure the URL package ID matches the manifest package ID."""

    try:
        requested_id = UUID(str(path_package_id))
    except (AttributeError, TypeError, ValueError) as error:
        raise ContractError("invalid_package_id", "The package ID is not a valid UUID.") from error
    if requested_id != manifest.package_id:
        raise ContractError(
            "package_id_mismatch",
            "The path package ID does not match the manifest package ID.",
        )


def _fingerprint_frame(frame: FrameManifest | Mapping[str, object]) -> dict[str, object]:
    if isinstance(frame, FrameManifest):
        return {
            "part_name": frame.part_name,
            "byte_length": frame.byte_length,
            "sha256": frame.sha256,
        }
    try:
        return {
            "part_name": str(frame["part_name"]),
            "byte_length": int(frame["byte_length"]),
            "sha256": str(frame["sha256"]),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise TypeError(
            "frame fingerprint entries need part_name, byte_length, and sha256."
        ) from error


def calculate_package_fingerprint(
    manifest_bytes: bytes,
    frames: Iterable[FrameManifest | Mapping[str, object]],
) -> str:
    """Calculate the deterministic package fingerprint."""

    if not isinstance(manifest_bytes, bytes):
        raise TypeError("manifest_bytes must be bytes.")
    entries = sorted(
        (_fingerprint_frame(frame) for frame in frames),
        key=lambda frame: str(frame["part_name"]),
    )
    fingerprint_input = {
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "frames": entries,
    }
    canonical = json.dumps(
        fingerprint_input,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def package_fingerprint(
    manifest_bytes: bytes,
    frames: Iterable[FrameManifest | Mapping[str, object]],
) -> str:
    """Compatibility name for package fingerprint calculation."""

    return calculate_package_fingerprint(manifest_bytes, frames)


__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "SUPPORTED_CONTENT_TYPE",
    "CameraMetadata",
    "ClientMetadata",
    "EvidenceCaptureMetadata",
    "EvidenceManifest",
    "EventDecoderMetadata",
    "EventMetadata",
    "FrameManifest",
    "ModelMetadata",
    "ScoreTraceEntry",
    "SessionMetadata",
    "UploadResponse",
    "calculate_package_fingerprint",
    "package_fingerprint",
    "parse_manifest_bytes",
    "validate_manifest",
    "validate_package_id",
]
