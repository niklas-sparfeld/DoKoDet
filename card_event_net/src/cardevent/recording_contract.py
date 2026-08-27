"""Validation for the shared training-recording and device-prediction contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping


class RecordingContractError(ValueError):
    """Raised when a training recording bundle is not valid."""


RECORDING_SCHEMA_VERSION = "cardevent-recording/v1"
DEVICE_PREDICTIONS_SCHEMA_VERSION = "cardevent-device-predictions/v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_PERMISSIONS = {"training_only", "training_and_evaluation", "project_use", "unrestricted"}


def _object(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RecordingContractError(f"{context} must be an object.")
    return value


def _closed(data: Mapping[str, Any], required: set[str], context: str) -> None:
    missing = required - set(data)
    unknown = set(data) - required
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise RecordingContractError(f"{context} has invalid fields ({'; '.join(details)}).")


def _string(data: Mapping[str, Any], field: str, context: str) -> str:
    value = data[field]
    if not isinstance(value, str) or not value:
        raise RecordingContractError(f"{context}.{field} must be a non-empty string.")
    return value


def _identifier(data: Mapping[str, Any], field: str, context: str) -> str:
    value = _string(data, field, context)
    if _IDENTIFIER.fullmatch(value) is None:
        raise RecordingContractError(f"{context}.{field} must be a safe identifier.")
    return value


def _filename(data: Mapping[str, Any], field: str, context: str) -> str:
    value = _string(data, field, context)
    if _FILENAME.fullmatch(value) is None:
        raise RecordingContractError(f"{context}.{field} must be a safe filename.")
    return value


def _sha256(data: Mapping[str, Any], field: str, context: str) -> str:
    value = _string(data, field, context)
    if _SHA256.fullmatch(value) is None:
        raise RecordingContractError(f"{context}.{field} must be a lower-case SHA-256 digest.")
    return value


def _number(data: Mapping[str, Any], field: str, context: str, *, minimum: float = 0.0) -> float:
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RecordingContractError(f"{context}.{field} must be a finite number.")
    if value < minimum:
        raise RecordingContractError(f"{context}.{field} must be at least {minimum}.")
    return float(value)


def _integer(data: Mapping[str, Any], field: str, context: str, *, minimum: int = 0) -> int:
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RecordingContractError(f"{context}.{field} must be an integer of at least {minimum}.")
    return value


def _utc_timestamp(data: Mapping[str, Any], field: str, context: str) -> datetime:
    value = _string(data, field, context)
    if not value.endswith("Z"):
        raise RecordingContractError(f"{context}.{field} must use UTC with a Z suffix.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise RecordingContractError(f"{context}.{field} must be an ISO-8601 timestamp.") from error
    if parsed.utcoffset() != timedelta(0):
        raise RecordingContractError(f"{context}.{field} must use UTC.")
    return parsed


@dataclass(frozen=True, slots=True)
class RecordingFile:
    name: str
    type: str
    byte_length: int
    sha256: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], context: str) -> "RecordingFile":
        _closed(data, {"name", "type", "byte_length", "sha256"}, context)
        return cls(
            name=_filename(data, "name", context),
            type=_string(data, "type", context),
            byte_length=_integer(data, "byte_length", context, minimum=1),
            sha256=_sha256(data, "sha256", context),
        )


@dataclass(frozen=True, slots=True)
class RecordingVideo(RecordingFile):
    codec: str
    width: int
    height: int
    frame_rate: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RecordingVideo":
        _closed(
            data,
            {"name", "type", "byte_length", "sha256", "codec", "width", "height", "frame_rate"},
            "manifest.video",
        )
        base = RecordingFile.from_mapping(
            {key: data[key] for key in ("name", "type", "byte_length", "sha256")},
            "manifest.video",
        )
        if base.type != "video/quicktime":
            raise RecordingContractError("manifest.video.type must be video/quicktime.")
        if data["codec"] != "h264":
            raise RecordingContractError("manifest.video.codec must be h264.")
        return cls(
            name=base.name,
            type=base.type,
            byte_length=base.byte_length,
            sha256=base.sha256,
            codec="h264",
            width=_integer(data, "width", "manifest.video", minimum=1),
            height=_integer(data, "height", "manifest.video", minimum=1),
            frame_rate=_number(data, "frame_rate", "manifest.video", minimum=0.000001),
        )


@dataclass(frozen=True, slots=True)
class RecordingPredictionsFile(RecordingFile):
    sample_count: int
    event_proposal_count: int

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RecordingPredictionsFile":
        _closed(
            data,
            {"name", "type", "byte_length", "sha256", "sample_count", "event_proposal_count"},
            "manifest.predictions",
        )
        base = RecordingFile.from_mapping(
            {key: data[key] for key in ("name", "type", "byte_length", "sha256")},
            "manifest.predictions",
        )
        if base.type != "application/json":
            raise RecordingContractError("manifest.predictions.type must be application/json.")
        return cls(
            name=base.name,
            type=base.type,
            byte_length=base.byte_length,
            sha256=base.sha256,
            sample_count=_integer(data, "sample_count", "manifest.predictions"),
            event_proposal_count=_integer(data, "event_proposal_count", "manifest.predictions"),
        )


@dataclass(frozen=True, slots=True)
class RecordingModel:
    name: str
    version: str
    weights_sha256: str
    preprocessing: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], context: str) -> "RecordingModel":
        _closed(data, {"name", "version", "weights_sha256", "preprocessing"}, context)
        return cls(
            name=_string(data, "name", context),
            version=_string(data, "version", context),
            weights_sha256=_sha256(data, "weights_sha256", context),
            preprocessing=_string(data, "preprocessing", context),
        )


@dataclass(frozen=True, slots=True)
class RecordingDecoder:
    algorithm: str
    threshold: float
    peak_confirmation_s: float
    minimum_event_gap_s: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], context: str) -> "RecordingDecoder":
        _closed(
            data,
            {"algorithm", "threshold", "peak_confirmation_s", "minimum_event_gap_s"},
            context,
        )
        threshold = _number(data, "threshold", context)
        if threshold > 1.0:
            raise RecordingContractError(f"{context}.threshold must be at most 1.0.")
        return cls(
            algorithm=_string(data, "algorithm", context),
            threshold=threshold,
            peak_confirmation_s=_number(data, "peak_confirmation_s", context),
            minimum_event_gap_s=_number(data, "minimum_event_gap_s", context),
        )


@dataclass(frozen=True, slots=True)
class RecordingCamera:
    position: str
    orientation: str
    source_width: int
    source_height: int

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RecordingCamera":
        _closed(
            data, {"position", "orientation", "source_width", "source_height"}, "manifest.camera"
        )
        position = _string(data, "position", "manifest.camera")
        if position not in {"back", "front"}:
            raise RecordingContractError("manifest.camera.position is not supported.")
        return cls(
            position=position,
            orientation=_string(data, "orientation", "manifest.camera"),
            source_width=_integer(data, "source_width", "manifest.camera", minimum=1),
            source_height=_integer(data, "source_height", "manifest.camera", minimum=1),
        )


@dataclass(frozen=True, slots=True)
class RecordingClient:
    app_version: str
    build: str
    device_model: str
    os_version: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RecordingClient":
        _closed(data, {"app_version", "build", "device_model", "os_version"}, "manifest.client")
        return cls(
            app_version=_string(data, "app_version", "manifest.client"),
            build=_string(data, "build", "manifest.client"),
            device_model=_string(data, "device_model", "manifest.client"),
            os_version=_string(data, "os_version", "manifest.client"),
        )


@dataclass(frozen=True, slots=True)
class CaptureMetrics:
    received_frame_count: int
    written_frame_count: int
    dropped_frame_count: int

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CaptureMetrics":
        _closed(
            data,
            {"received_frame_count", "written_frame_count", "dropped_frame_count"},
            "manifest.capture_metrics",
        )
        result = cls(
            received_frame_count=_integer(data, "received_frame_count", "manifest.capture_metrics"),
            written_frame_count=_integer(data, "written_frame_count", "manifest.capture_metrics"),
            dropped_frame_count=_integer(data, "dropped_frame_count", "manifest.capture_metrics"),
        )
        if result.written_frame_count + result.dropped_frame_count != result.received_frame_count:
            raise RecordingContractError(
                "manifest.capture_metrics written and dropped frame counts must equal received."
            )
        return result


@dataclass(frozen=True, slots=True)
class RecordingManifest:
    recording_id: str
    session_id: str
    video_id: str
    started_at_utc: str
    ended_at_utc: str
    duration_s: float
    video: RecordingVideo
    predictions: RecordingPredictionsFile
    model: RecordingModel
    decoder: RecordingDecoder
    camera: RecordingCamera
    client: RecordingClient
    capture_metrics: CaptureMetrics
    source_permission: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RecordingManifest":
        fields = {
            "schema_version",
            "recording_id",
            "session_id",
            "video_id",
            "started_at_utc",
            "ended_at_utc",
            "duration_s",
            "state",
            "video",
            "predictions",
            "model",
            "decoder",
            "camera",
            "client",
            "capture_metrics",
            "source",
            "source_permission",
        }
        _closed(data, fields, "recording manifest")
        if data["schema_version"] != RECORDING_SCHEMA_VERSION:
            raise RecordingContractError("Unsupported recording manifest schema.")
        if data["state"] != "complete":
            raise RecordingContractError("recording manifest state must be complete.")
        if data["source"] != "self_recorded":
            raise RecordingContractError("recording manifest source must be self_recorded.")
        permission = _string(data, "source_permission", "recording manifest")
        if permission not in _SOURCE_PERMISSIONS:
            raise RecordingContractError("recording manifest source_permission is not supported.")

        started = _utc_timestamp(data, "started_at_utc", "recording manifest")
        ended = _utc_timestamp(data, "ended_at_utc", "recording manifest")
        duration = _number(data, "duration_s", "recording manifest", minimum=0.000001)
        elapsed = (ended - started).total_seconds()
        if ended <= started or not math.isclose(duration, elapsed, abs_tol=0.001):
            raise RecordingContractError(
                "recording manifest duration does not match its UTC times."
            )

        video_id = _identifier(data, "video_id", "recording manifest")
        video = RecordingVideo.from_mapping(_object(data["video"], "manifest.video"))
        predictions = RecordingPredictionsFile.from_mapping(
            _object(data["predictions"], "manifest.predictions")
        )
        if video.name != f"{video_id}.mov" or predictions.name != f"{video_id}.json":
            raise RecordingContractError("recording file names must be derived from video_id.")
        return cls(
            recording_id=_identifier(data, "recording_id", "recording manifest"),
            session_id=_identifier(data, "session_id", "recording manifest"),
            video_id=video_id,
            started_at_utc=_string(data, "started_at_utc", "recording manifest"),
            ended_at_utc=_string(data, "ended_at_utc", "recording manifest"),
            duration_s=duration,
            video=video,
            predictions=predictions,
            model=RecordingModel.from_mapping(
                _object(data["model"], "manifest.model"), "manifest.model"
            ),
            decoder=RecordingDecoder.from_mapping(
                _object(data["decoder"], "manifest.decoder"), "manifest.decoder"
            ),
            camera=RecordingCamera.from_mapping(_object(data["camera"], "manifest.camera")),
            client=RecordingClient.from_mapping(_object(data["client"], "manifest.client")),
            capture_metrics=CaptureMetrics.from_mapping(
                _object(data["capture_metrics"], "manifest.capture_metrics")
            ),
            source_permission=permission,
        )


@dataclass(frozen=True, slots=True)
class ProbabilitySample:
    time_s: float
    probability: float
    inference_ms: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ProbabilitySample":
        _closed(data, {"time_s", "probability", "inference_ms"}, "prediction probability")
        probability = _number(data, "probability", "prediction probability")
        if probability > 1.0:
            raise RecordingContractError("prediction probability.probability must be at most 1.0.")
        return cls(
            time_s=_number(data, "time_s", "prediction probability"),
            probability=probability,
            inference_ms=_number(data, "inference_ms", "prediction probability"),
        )


@dataclass(frozen=True, slots=True)
class EventProposal:
    time_s: float
    emitted_at_s: float
    probability: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EventProposal":
        _closed(data, {"time_s", "emitted_at_s", "probability"}, "event proposal")
        probability = _number(data, "probability", "event proposal")
        if probability > 1.0:
            raise RecordingContractError("event proposal.probability must be at most 1.0.")
        result = cls(
            time_s=_number(data, "time_s", "event proposal"),
            emitted_at_s=_number(data, "emitted_at_s", "event proposal"),
            probability=probability,
        )
        if result.emitted_at_s < result.time_s:
            raise RecordingContractError("event proposal emitted_at_s must be causal.")
        return result


@dataclass(frozen=True, slots=True)
class DevicePredictions:
    source_video: str
    model: RecordingModel
    decoder: RecordingDecoder
    probabilities: tuple[ProbabilitySample, ...]
    event_proposals: tuple[EventProposal, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DevicePredictions":
        fields = {
            "schema_version",
            "source_video",
            "model",
            "decoder",
            "probabilities",
            "event_proposals",
        }
        _closed(data, fields, "device predictions")
        if data["schema_version"] != DEVICE_PREDICTIONS_SCHEMA_VERSION:
            raise RecordingContractError("Unsupported device predictions schema.")
        probabilities_data = data["probabilities"]
        proposals_data = data["event_proposals"]
        if not isinstance(probabilities_data, list) or not isinstance(proposals_data, list):
            raise RecordingContractError("device prediction streams must be arrays.")
        result = cls(
            source_video=_filename(data, "source_video", "device predictions"),
            model=RecordingModel.from_mapping(
                _object(data["model"], "predictions.model"), "predictions.model"
            ),
            decoder=RecordingDecoder.from_mapping(
                _object(data["decoder"], "predictions.decoder"), "predictions.decoder"
            ),
            probabilities=tuple(
                ProbabilitySample.from_mapping(_object(item, "prediction probability"))
                for item in probabilities_data
            ),
            event_proposals=tuple(
                EventProposal.from_mapping(_object(item, "event proposal"))
                for item in proposals_data
            ),
        )
        _require_ordered([sample.time_s for sample in result.probabilities], "probability times")
        _require_ordered(
            [proposal.time_s for proposal in result.event_proposals], "event proposal times"
        )
        return result


def _require_ordered(values: list[float], context: str) -> None:
    if values != sorted(values):
        raise RecordingContractError(f"{context} must be ordered on the recording timeline.")


def _parse_json(raw: bytes, context: str) -> Mapping[str, Any]:
    if not isinstance(raw, bytes):
        raise TypeError(f"{context} must be bytes.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecordingContractError(f"{context} must be UTF-8 JSON.") from error
    return _object(value, context)


def parse_recording_manifest_bytes(raw: bytes) -> RecordingManifest:
    return RecordingManifest.from_mapping(_parse_json(raw, "recording manifest"))


def parse_device_predictions_bytes(raw: bytes) -> DevicePredictions:
    return DevicePredictions.from_mapping(_parse_json(raw, "device predictions"))


def validate_recording_bundle(
    manifest_bytes: bytes, predictions_bytes: bytes, video_bytes: bytes
) -> tuple[RecordingManifest, DevicePredictions]:
    """Validate both JSON documents, their relationship, and their declared file bytes."""

    manifest = parse_recording_manifest_bytes(manifest_bytes)
    predictions = parse_device_predictions_bytes(predictions_bytes)
    if manifest.video.name != predictions.source_video:
        raise RecordingContractError("predictions.source_video does not match manifest.video.name.")
    if manifest.model != predictions.model or manifest.decoder != predictions.decoder:
        raise RecordingContractError("prediction provenance does not match the recording manifest.")
    if len(predictions.probabilities) != manifest.predictions.sample_count:
        raise RecordingContractError("prediction sample count does not match the manifest.")
    if len(predictions.event_proposals) != manifest.predictions.event_proposal_count:
        raise RecordingContractError("event proposal count does not match the manifest.")
    for sample in predictions.probabilities:
        if sample.time_s > manifest.duration_s:
            raise RecordingContractError("probability time is outside the recording duration.")
    for proposal in predictions.event_proposals:
        if proposal.emitted_at_s > manifest.duration_s:
            raise RecordingContractError("event proposal time is outside the recording duration.")
    _verify_bytes(video_bytes, manifest.video.byte_length, manifest.video.sha256, "video")
    _verify_bytes(
        predictions_bytes,
        manifest.predictions.byte_length,
        manifest.predictions.sha256,
        "predictions",
    )
    return manifest, predictions


def _verify_bytes(value: bytes, expected_length: int, expected_sha256: str, name: str) -> None:
    if len(value) != expected_length or hashlib.sha256(value).hexdigest() != expected_sha256:
        raise RecordingContractError(f"{name} bytes do not match the manifest.")


def validate_recording_directory(directory: Path) -> tuple[RecordingManifest, DevicePredictions]:
    """Validate a finalized directory without accepting paths from the manifest as identity."""

    manifest_bytes = (directory / "manifest.json").read_bytes()
    manifest = parse_recording_manifest_bytes(manifest_bytes)
    video_bytes = (directory / manifest.video.name).read_bytes()
    predictions_bytes = (directory / manifest.predictions.name).read_bytes()
    return validate_recording_bundle(manifest_bytes, predictions_bytes, video_bytes)


__all__ = [
    "DEVICE_PREDICTIONS_SCHEMA_VERSION",
    "RECORDING_SCHEMA_VERSION",
    "DevicePredictions",
    "RecordingContractError",
    "RecordingManifest",
    "parse_device_predictions_bytes",
    "parse_recording_manifest_bytes",
    "validate_recording_bundle",
    "validate_recording_directory",
]
