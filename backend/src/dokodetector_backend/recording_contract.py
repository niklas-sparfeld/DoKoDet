"""Pydantic validation for the shared training-recording contract."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from typing import Annotated, Literal

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

RECORDING_SCHEMA_VERSION = "cardevent-recording/v1"
DEVICE_PREDICTIONS_SCHEMA_VERSION = "cardevent-device-predictions/v1"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Filename = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


class RecordingContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class RecordingFile(RecordingContractModel):
    name: Filename
    type: str = Field(min_length=1)
    byte_length: int = Field(gt=0)
    sha256: Sha256


class RecordingVideo(RecordingFile):
    type: Literal["video/quicktime"]
    codec: Literal["h264"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    frame_rate: float = Field(gt=0)

    @field_validator("frame_rate")
    @classmethod
    def frame_rate_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("frame_rate must be finite.")
        return value


class RecordingPredictionsFile(RecordingFile):
    type: Literal["application/json"]
    sample_count: int = Field(ge=0)
    event_proposal_count: int = Field(ge=0)


class RecordingModel(RecordingContractModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    weights_sha256: Sha256
    preprocessing: str = Field(min_length=1)


class RecordingDecoder(RecordingContractModel):
    algorithm: str = Field(min_length=1)
    threshold: float = Field(ge=0, le=1)
    peak_confirmation_s: float = Field(ge=0)
    minimum_event_gap_s: float = Field(ge=0)

    @field_validator("threshold", "peak_confirmation_s", "minimum_event_gap_s")
    @classmethod
    def decoder_values_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("decoder values must be finite.")
        return value


class RecordingCamera(RecordingContractModel):
    position: Literal["back", "front"]
    orientation: str = Field(min_length=1)
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)


class RecordingClient(RecordingContractModel):
    app_version: str = Field(min_length=1)
    build: str = Field(min_length=1)
    device_model: str = Field(min_length=1)
    os_version: str = Field(min_length=1)


class CaptureMetrics(RecordingContractModel):
    received_frame_count: int = Field(ge=0)
    written_frame_count: int = Field(ge=0)
    dropped_frame_count: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_must_balance(self) -> CaptureMetrics:
        if self.written_frame_count + self.dropped_frame_count != self.received_frame_count:
            raise ValueError("written and dropped frame counts must equal received.")
        return self


class RecordingManifest(RecordingContractModel):
    schema_version: Literal["cardevent-recording/v1"]
    recording_id: Identifier
    session_id: Identifier
    video_id: Identifier
    started_at_utc: str
    ended_at_utc: str
    duration_s: float = Field(gt=0)
    state: Literal["complete"]
    video: RecordingVideo
    predictions: RecordingPredictionsFile
    model: RecordingModel
    decoder: RecordingDecoder
    camera: RecordingCamera
    client: RecordingClient
    capture_metrics: CaptureMetrics
    source: Literal["self_recorded"]
    source_permission: Literal[
        "training_only", "training_and_evaluation", "project_use", "unrestricted"
    ]

    @field_validator("duration_s")
    @classmethod
    def duration_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("duration_s must be finite.")
        return value

    @model_validator(mode="after")
    def validate_consistency(self) -> RecordingManifest:
        started = _parse_utc(self.started_at_utc, "started_at_utc")
        ended = _parse_utc(self.ended_at_utc, "ended_at_utc")
        elapsed = (ended - started).total_seconds()
        if ended <= started or not math.isclose(self.duration_s, elapsed, abs_tol=0.001):
            raise ValueError("duration_s must match the UTC start and end times.")
        if self.video.name != f"{self.video_id}.mov":
            raise ValueError("video.name must be derived from video_id.")
        if self.predictions.name != f"{self.video_id}.json":
            raise ValueError("predictions.name must be derived from video_id.")
        return self


class ProbabilitySample(RecordingContractModel):
    time_s: float = Field(ge=0)
    probability: float = Field(ge=0, le=1)
    inference_ms: float = Field(ge=0)

    @field_validator("time_s", "probability", "inference_ms")
    @classmethod
    def values_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("prediction values must be finite.")
        return value


class EventProposal(RecordingContractModel):
    time_s: float = Field(ge=0)
    emitted_at_s: float = Field(ge=0)
    probability: float = Field(ge=0, le=1)

    @field_validator("time_s", "emitted_at_s", "probability")
    @classmethod
    def values_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("event proposal values must be finite.")
        return value

    @model_validator(mode="after")
    def emitted_time_must_be_causal(self) -> EventProposal:
        if self.emitted_at_s < self.time_s:
            raise ValueError("emitted_at_s must be at or after time_s.")
        return self


class DevicePredictions(RecordingContractModel):
    schema_version: Literal["cardevent-device-predictions/v1"]
    source_video: Filename
    model: RecordingModel
    decoder: RecordingDecoder
    probabilities: list[ProbabilitySample]
    event_proposals: list[EventProposal]

    @model_validator(mode="after")
    def timelines_must_be_ordered(self) -> DevicePredictions:
        if [item.time_s for item in self.probabilities] != sorted(
            item.time_s for item in self.probabilities
        ):
            raise ValueError("probability times must be ordered on the recording timeline.")
        if [item.time_s for item in self.event_proposals] != sorted(
            item.time_s for item in self.event_proposals
        ):
            raise ValueError("event proposal times must be ordered on the recording timeline.")
        return self


class TrainingRecordingUploadResponse(RecordingContractModel):
    """The response returned after a recording is accepted."""

    recording_id: Identifier
    state: Literal["stored"]
    created: bool
    received_at: datetime


class StoredRecordingFileResponse(RecordingContractModel):
    """One immutable recording file returned by the read endpoint."""

    name: Filename
    type: str = Field(min_length=1)
    byte_length: int = Field(gt=0)
    sha256: Sha256
    relative_path: str = Field(min_length=1)


class DerivedArtifactResponse(RecordingContractModel):
    """One derived intake file and its current state."""

    state: Literal["ready"]
    name: Filename
    byte_length: int = Field(gt=0)
    sha256: Sha256
    relative_path: str = Field(min_length=1)


class RecordingDerivedArtifactsResponse(RecordingContractModel):
    """The derived artifacts generated from one immutable recording."""

    state: Literal["ready"]
    dataset_record: DerivedArtifactResponse
    candidate_review_queue: DerivedArtifactResponse | None


class TrainingRecordingMetadataResponse(RecordingContractModel):
    """Metadata and derived-artifact state for one accepted recording."""

    recording_id: Identifier
    session_id: Identifier
    video_id: Identifier
    state: Literal["stored"]
    received_at: datetime
    schema_version: Literal["cardevent-recording/v1"]
    started_at_utc: str
    ended_at_utc: str
    duration_s: float = Field(gt=0)
    manifest_sha256: Sha256
    manifest: dict[str, object]
    video: StoredRecordingFileResponse
    predictions: StoredRecordingFileResponse
    derived_artifacts: RecordingDerivedArtifactsResponse
    evidence_package_count: int = Field(ge=0)


def _parse_utc(value: str, field: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError(f"{field} must use UTC with a Z suffix.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO-8601 timestamp.") from error
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must use UTC.")
    return parsed


def _parse_bytes(raw: bytes, context: str) -> dict[str, object]:
    if not isinstance(raw, bytes):
        raise TypeError(f"{context} must be bytes.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError(
            f"invalid_{context}", f"The {context.replace('_', ' ')} is not UTF-8 JSON."
        ) from error
    if not isinstance(value, dict):
        raise ContractError(
            f"invalid_{context}", f"The {context.replace('_', ' ')} must be an object."
        )
    return value


def parse_recording_manifest_bytes(raw: bytes) -> RecordingManifest:
    payload = _parse_bytes(raw, "recording_manifest")
    try:
        return RecordingManifest.model_validate(payload)
    except ValidationError as error:
        raise ContractError(
            "invalid_recording_manifest",
            "The recording manifest failed validation.",
            details=validation_details(error),
        ) from error


def parse_device_predictions_bytes(raw: bytes) -> DevicePredictions:
    payload = _parse_bytes(raw, "device_predictions")
    try:
        return DevicePredictions.model_validate(payload)
    except ValidationError as error:
        raise ContractError(
            "invalid_device_predictions",
            "The device predictions failed validation.",
            details=validation_details(error),
        ) from error


def validate_recording_bundle(
    manifest_bytes: bytes, predictions_bytes: bytes, video_bytes: bytes
) -> tuple[RecordingManifest, DevicePredictions]:
    """Validate both documents, their relationship, and their declared bytes."""

    manifest, predictions = validate_recording_documents(manifest_bytes, predictions_bytes)
    _verify_bytes(video_bytes, manifest.video, "video")
    _verify_bytes(predictions_bytes, manifest.predictions, "predictions")
    return manifest, predictions


def validate_recording_documents(
    manifest_bytes: bytes, predictions_bytes: bytes
) -> tuple[RecordingManifest, DevicePredictions]:
    """Validate the JSON documents and their relationship without reading video bytes."""

    manifest = parse_recording_manifest_bytes(manifest_bytes)
    predictions = parse_device_predictions_bytes(predictions_bytes)
    if manifest.video.name != predictions.source_video:
        raise ContractError(
            "recording_identity_mismatch",
            "predictions.source_video does not match manifest.video.name.",
        )
    if manifest.model != predictions.model or manifest.decoder != predictions.decoder:
        raise ContractError(
            "recording_provenance_mismatch",
            "Prediction provenance does not match the recording manifest.",
        )
    if len(predictions.probabilities) != manifest.predictions.sample_count:
        raise ContractError(
            "recording_count_mismatch",
            "The prediction sample count does not match the manifest.",
        )
    if len(predictions.event_proposals) != manifest.predictions.event_proposal_count:
        raise ContractError(
            "recording_count_mismatch",
            "The event proposal count does not match the manifest.",
        )
    for sample in predictions.probabilities:
        if sample.time_s > manifest.duration_s:
            raise ContractError(
                "recording_time_mismatch", "A probability time is outside the recording."
            )
    for proposal in predictions.event_proposals:
        if proposal.emitted_at_s > manifest.duration_s:
            raise ContractError(
                "recording_time_mismatch", "An event proposal time is outside the recording."
            )
    return manifest, predictions


def _verify_bytes(value: bytes, descriptor: RecordingFile, name: str) -> None:
    if (
        len(value) != descriptor.byte_length
        or hashlib.sha256(value).hexdigest() != descriptor.sha256
    ):
        raise ContractError(
            "recording_hash_mismatch", f"The {name} bytes do not match the manifest."
        )


def calculate_recording_fingerprint(
    manifest_bytes: bytes, video_sha256: str, predictions_sha256: str
) -> str:
    """Return the idempotency fingerprint for one complete recording bundle."""

    digest = hashlib.sha256()
    for value in (
        manifest_bytes,
        b"\0",
        video_sha256.encode("ascii"),
        b"\0",
        predictions_sha256.encode("ascii"),
    ):
        digest.update(value)
    return digest.hexdigest()


__all__ = [
    "DEVICE_PREDICTIONS_SCHEMA_VERSION",
    "RECORDING_SCHEMA_VERSION",
    "DevicePredictions",
    "DerivedArtifactResponse",
    "RecordingDerivedArtifactsResponse",
    "RecordingContractModel",
    "RecordingManifest",
    "StoredRecordingFileResponse",
    "TrainingRecordingMetadataResponse",
    "TrainingRecordingUploadResponse",
    "calculate_recording_fingerprint",
    "parse_device_predictions_bytes",
    "parse_recording_manifest_bytes",
    "validate_recording_documents",
    "validate_recording_bundle",
]
