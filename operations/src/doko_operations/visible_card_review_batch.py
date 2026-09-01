"""Prepare exact-event visible-card review batches.

This module joins one immutable, completed CardEvent review to the local visible-card provider.
It writes only below the operations workspace.  The accepted recording bundle and the completed
CardEvent artifact are read-only inputs.  A v2 review queue is published only after every selected
event has a source frame and a successful provider result.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from table_evidence_analyzer.visible_card_review_workflow import (
    VISIBLE_CARD_REVIEW_QUEUE_SCHEMA,
    build_visible_card_review_queue,
    load_visible_card_review_queue,
)
from table_evidence_analyzer.visible_cards import (
    IMPROVED_REQUEST_SCHEMA_VERSION,
    REQUEST_SCHEMA_VERSION,
    ProviderResult,
    VisibleCardProvider,
    build_request_from_image,
)

VISIBLE_CARD_BATCH_SCHEMA_VERSION = "visible-card-review-batch/v1"
VISIBLE_CARD_BATCH_SCHEMA = VISIBLE_CARD_BATCH_SCHEMA_VERSION
VISIBLE_CARD_BATCH_STATUSES = frozenset({"preparing", "ready", "failed", "blocked"})
VISIBLE_CARD_BATCH_PHASES = frozenset(
    {"validating_inputs", "extracting_frames", "running_finder", "ready", "failed", "blocked"}
)
VISIBLE_CARD_BATCH_FAILURE_CODES = frozenset(
    {
        "disallowed_source_use",
        "non_local_provider",
        "stale_annotation",
        "protected_source_group",
        "missing_source_video",
        "source_digest_mismatch",
        "task_enrollment_not_selected",
        "no_reviewed_card_events",
        "missing_frame",
        "frame_extraction_error",
        "provider_error",
        "provider_unavailable",
        "invalid_provider_result",
        "queue_error",
    }
)
_CARD_EVENT_REVIEWED_SCHEMA = "cardevent-reviewed-annotation/v1"
_CARD_EVENT_ANNOTATION_SCHEMA = "cardevent-annotation/v2"
_SHA256_LENGTH = 64
_SOURCE_PERMISSIONS = frozenset(
    {"training_only", "training_and_evaluation", "project_use", "unrestricted"}
)
_ALLOWED_USES = frozenset({"train", "validation", "test", "evaluation"})
_IDENTIFIER_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-/"
)


class VisibleCardBatchError(ValueError):
    """Raised when a visible-card batch request or stored batch is invalid."""


class VisibleCardBatchWriteError(RuntimeError):
    """Raised when the operations workspace cannot be written safely."""


class VisibleCardFrameExtractionError(RuntimeError):
    """Raised when an exact-event frame cannot be extracted."""


class VisibleCardMissingFrameError(VisibleCardFrameExtractionError):
    """Raised when the requested exact-event frame is outside the source video."""


@dataclass(frozen=True, slots=True)
class VisibleCardDetectorIdentity:
    """The detector identity frozen into one review batch."""

    bundle_id: str
    bundle_digest: str
    model: str
    preprocessing: str
    confidence_threshold: float = 0.5
    provider: str = "local"
    provider_version: str = "local-visible-cards-v1"
    bundle_path: str | None = None
    input_size: int = 704

    def __post_init__(self) -> None:
        _identifier(self.bundle_id, "detector.bundle_id")
        _digest(self.bundle_digest, "detector.bundle_digest")
        _text(self.model, "detector.model")
        _text(self.preprocessing, "detector.preprocessing")
        _text(self.provider, "detector.provider")
        _text(self.provider_version, "detector.provider_version")
        if not math.isfinite(self.confidence_threshold) or not 0 <= self.confidence_threshold <= 1:
            raise VisibleCardBatchError(
                "detector.confidence_threshold must be a finite number in [0, 1]"
            )
        if (
            isinstance(self.input_size, bool)
            or not isinstance(self.input_size, int)
            or self.input_size <= 0
        ):
            raise VisibleCardBatchError("detector.input_size must be a positive integer")
        if self.bundle_path is not None:
            _text(self.bundle_path, "detector.bundle_path")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "bundle_digest": self.bundle_digest,
            "bundle_path": self.bundle_path,
            "model": self.model,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "preprocessing": self.preprocessing,
            "confidence_threshold": self.confidence_threshold,
            "input_size": self.input_size,
        }

    def to_mapping_without_path(self) -> dict[str, Any]:
        """Return the detector identity without a machine-local bundle path."""

        value = self.to_mapping()
        value.pop("bundle_path", None)
        return value

    @classmethod
    def from_mapping(cls, value: Any) -> "VisibleCardDetectorIdentity":
        fields = {
            "bundle_id",
            "bundle_digest",
            "bundle_path",
            "model",
            "provider",
            "provider_version",
            "preprocessing",
            "confidence_threshold",
            "input_size",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise VisibleCardBatchError("detector identity has unexpected fields")
        try:
            return cls(**dict(value))
        except (TypeError, ValueError, VisibleCardBatchError) as error:
            raise VisibleCardBatchError("detector identity is invalid") from error


@dataclass(frozen=True, slots=True)
class VisibleCardBatchRequest:
    """Frozen logical inputs for one recording-scoped visible-card batch."""

    recording_id: str
    source_asset_id: str
    source_sha256: str
    source_lineage_group: str
    video_path: Path
    card_event_review_version_path: Path
    card_event_review_version_id: str
    card_event_review_version_digest: str
    card_event_annotation_digest: str
    detector: VisibleCardDetectorIdentity
    target_offset_ms: int = 0
    request_version: str = REQUEST_SCHEMA_VERSION
    task_enrollment_id: str = "table-evidence-enrollment"
    task_enrollment_selected: bool = True
    source_permission: str = "training_and_evaluation"
    allowed_uses: tuple[str, ...] = ("train", "validation", "evaluation")
    protected_source_lineage_groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.recording_id, "recording_id")
        _identifier(self.source_asset_id, "source_asset_id")
        _digest(self.source_sha256, "source_sha256")
        _identifier(self.source_lineage_group, "source_lineage_group")
        if not isinstance(self.video_path, Path):
            object.__setattr__(self, "video_path", Path(self.video_path))
        if not isinstance(self.card_event_review_version_path, Path):
            object.__setattr__(
                self, "card_event_review_version_path", Path(self.card_event_review_version_path)
            )
        _identifier(self.card_event_review_version_id, "card_event_review_version_id")
        _digest(self.card_event_review_version_digest, "card_event_review_version_digest")
        _digest(self.card_event_annotation_digest, "card_event_annotation_digest")
        if self.target_offset_ms != 0:
            raise VisibleCardBatchError(
                "visible-card batch preparation requires target_offset_ms=0"
            )
        if self.request_version not in {
            REQUEST_SCHEMA_VERSION,
            IMPROVED_REQUEST_SCHEMA_VERSION,
        }:
            raise VisibleCardBatchError("request_version is not a supported visible-card request")
        _identifier(self.task_enrollment_id, "task_enrollment_id")
        if not isinstance(self.task_enrollment_selected, bool):
            raise VisibleCardBatchError("task_enrollment_selected must be a boolean")
        _text(self.source_permission, "source_permission")
        if not self.allowed_uses or any(
            not isinstance(value, str) or not value for value in self.allowed_uses
        ):
            raise VisibleCardBatchError("allowed_uses must contain non-empty strings")
        if len(set(self.allowed_uses)) != len(self.allowed_uses):
            raise VisibleCardBatchError("allowed_uses must not contain duplicates")
        if any(
            not isinstance(value, str) or not value
            for value in self.protected_source_lineage_groups
        ):
            raise VisibleCardBatchError("protected_source_lineage_groups must contain strings")
        if len(set(self.protected_source_lineage_groups)) != len(
            self.protected_source_lineage_groups
        ):
            raise VisibleCardBatchError(
                "protected_source_lineage_groups must not contain duplicates"
            )

    @property
    def identity_mapping(self) -> dict[str, Any]:
        """Return the path-independent mapping used for batch identity."""

        return {
            "schema_version": VISIBLE_CARD_BATCH_SCHEMA_VERSION,
            "recording_id": self.recording_id,
            "source_asset_id": self.source_asset_id,
            "source_sha256": self.source_sha256,
            "source_lineage_group": self.source_lineage_group,
            "video_name": self.video_path.name,
            "card_event_review_version_id": self.card_event_review_version_id,
            "card_event_review_version_digest": self.card_event_review_version_digest,
            "card_event_annotation_digest": self.card_event_annotation_digest,
            "detector": self.detector.to_mapping_without_path(),
            "target_offset_ms": self.target_offset_ms,
            "request_version": self.request_version,
            "task_enrollment_id": self.task_enrollment_id,
            "task_enrollment_selected": self.task_enrollment_selected,
            "source_permission": self.source_permission,
            "allowed_uses": list(self.allowed_uses),
            "protected_source_lineage_groups": list(self.protected_source_lineage_groups),
        }

    @property
    def request_digest(self) -> str:
        return _digest_value(self.identity_mapping)

    @property
    def batch_id(self) -> str:
        return f"visible-card-batch-{self.request_digest[:24]}"

    def to_mapping(self) -> dict[str, Any]:
        return {
            **self.identity_mapping,
            "video_path": str(self.video_path.expanduser().resolve()),
            "card_event_review_version_path": str(
                self.card_event_review_version_path.expanduser().resolve()
            ),
            "detector": self.detector.to_mapping(),
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "VisibleCardBatchRequest":
        fields = {
            "schema_version",
            "recording_id",
            "source_asset_id",
            "source_sha256",
            "source_lineage_group",
            "video_name",
            "video_path",
            "card_event_review_version_path",
            "card_event_review_version_id",
            "card_event_review_version_digest",
            "card_event_annotation_digest",
            "detector",
            "target_offset_ms",
            "request_version",
            "task_enrollment_id",
            "task_enrollment_selected",
            "source_permission",
            "allowed_uses",
            "protected_source_lineage_groups",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise VisibleCardBatchError("batch request has unexpected fields")
        if value["schema_version"] != VISIBLE_CARD_BATCH_SCHEMA_VERSION:
            raise VisibleCardBatchError("unsupported visible-card batch request schema")
        if value["video_name"] != Path(str(value["video_path"])).name:
            raise VisibleCardBatchError("batch request video_name does not match video_path")
        try:
            request = cls(
                recording_id=value["recording_id"],
                source_asset_id=value["source_asset_id"],
                source_sha256=value["source_sha256"],
                source_lineage_group=value["source_lineage_group"],
                video_path=Path(value["video_path"]),
                card_event_review_version_path=Path(value["card_event_review_version_path"]),
                card_event_review_version_id=value["card_event_review_version_id"],
                card_event_review_version_digest=value["card_event_review_version_digest"],
                card_event_annotation_digest=value["card_event_annotation_digest"],
                detector=VisibleCardDetectorIdentity.from_mapping(value["detector"]),
                target_offset_ms=value["target_offset_ms"],
                request_version=value["request_version"],
                task_enrollment_id=value["task_enrollment_id"],
                task_enrollment_selected=value["task_enrollment_selected"],
                source_permission=value["source_permission"],
                allowed_uses=tuple(value["allowed_uses"]),
                protected_source_lineage_groups=tuple(value["protected_source_lineage_groups"]),
            )
        except (KeyError, TypeError, ValueError, VisibleCardBatchError) as error:
            raise VisibleCardBatchError("batch request is invalid") from error
        return request


@dataclass(frozen=True, slots=True)
class ExtractedVisibleCardFrame:
    """One exact-event frame returned by the media boundary."""

    frame_index: int
    actual_offset_ms: int
    image_bytes: bytes
    width: int
    height: int
    target_offset_ms: int = 0
    content_type: str = "image/jpeg"

    def __post_init__(self) -> None:
        if (
            isinstance(self.frame_index, bool)
            or not isinstance(self.frame_index, int)
            or self.frame_index < 0
        ):
            raise VisibleCardBatchError("frame_index must be a non-negative integer")
        if isinstance(self.actual_offset_ms, bool) or not isinstance(self.actual_offset_ms, int):
            raise VisibleCardBatchError("actual_offset_ms must be an integer")
        if not isinstance(self.image_bytes, bytes) or not self.image_bytes:
            raise VisibleCardBatchError("image_bytes must be non-empty bytes")
        if isinstance(self.width, bool) or not isinstance(self.width, int) or self.width <= 0:
            raise VisibleCardBatchError("frame width must be a positive integer")
        if isinstance(self.height, bool) or not isinstance(self.height, int) or self.height <= 0:
            raise VisibleCardBatchError("frame height must be a positive integer")
        if self.target_offset_ms != 0:
            raise VisibleCardBatchError("extracted frame target_offset_ms must be 0")
        if not isinstance(self.content_type, str) or not self.content_type.startswith("image/"):
            raise VisibleCardBatchError("frame content_type must be an image MIME type")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.image_bytes).hexdigest()

    def to_mapping(self, *, path: str) -> dict[str, Any]:
        return {
            "path": path,
            "frame_index": self.frame_index,
            "target_offset_ms": self.target_offset_ms,
            "actual_offset_ms": self.actual_offset_ms,
            "width": self.width,
            "height": self.height,
            "byte_length": len(self.image_bytes),
            "content_type": self.content_type,
            "sha256": self.sha256,
        }


class VisibleCardFrameExtractor(Protocol):
    """Application boundary for exact-event media extraction."""

    def extract(
        self,
        video_path: Path,
        *,
        event_time_s: float,
        target_offset_ms: int,
    ) -> ExtractedVisibleCardFrame | None:
        """Return the nearest decoded source frame, or ``None`` when it is missing."""


class OpenCVVisibleCardFrameExtractor:
    """Decode exact-event frames with the local OpenCV media boundary."""

    def __init__(self, *, jpeg_quality: int = 85) -> None:
        if (
            isinstance(jpeg_quality, bool)
            or not isinstance(jpeg_quality, int)
            or not 1 <= jpeg_quality <= 100
        ):
            raise VisibleCardBatchError("jpeg_quality must be an integer from 1 through 100")
        self.jpeg_quality = jpeg_quality

    def extract(
        self,
        video_path: Path,
        *,
        event_time_s: float,
        target_offset_ms: int,
    ) -> ExtractedVisibleCardFrame | None:
        try:
            import cv2
        except ModuleNotFoundError as error:
            raise VisibleCardFrameExtractionError(
                "OpenCV is required for the default visible-card frame extractor"
            ) from error
        if not video_path.is_file():
            raise VisibleCardFrameExtractionError(f"source video does not exist: {video_path}")
        capture = cv2.VideoCapture(str(video_path))
        try:
            if not capture.isOpened():
                raise VisibleCardFrameExtractionError(
                    f"source video could not be opened: {video_path}"
                )
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if not math.isfinite(fps) or fps <= 0 or frame_count <= 0:
                raise VisibleCardFrameExtractionError("source video has invalid frame metadata")
            frame_index = math.floor((event_time_s + target_offset_ms / 1000.0) * fps + 0.5)
            if frame_index < 0 or frame_index >= frame_count:
                return None
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok or frame is None:
                return None
            encoded, buffer = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            )
            if not encoded:
                raise VisibleCardFrameExtractionError(
                    f"source frame could not be encoded: frame {frame_index}"
                )
            height, width = frame.shape[:2]
            actual_offset_ms = math.floor(frame_index / fps * 1000.0 + 0.5) - math.floor(
                event_time_s * 1000.0 + 0.5
            )
            return ExtractedVisibleCardFrame(
                frame_index=frame_index,
                actual_offset_ms=actual_offset_ms,
                image_bytes=buffer.tobytes(),
                width=int(width),
                height=int(height),
                target_offset_ms=target_offset_ms,
            )
        finally:
            capture.release()


class FFmpegVisibleCardFrameExtractor:
    """Decode an exact source frame with the repository's ffmpeg toolchain."""

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
    ) -> None:
        _text(ffmpeg_binary, "ffmpeg_binary")
        _text(ffprobe_binary, "ffprobe_binary")
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary

    def extract(
        self,
        video_path: Path,
        *,
        event_time_s: float,
        target_offset_ms: int,
    ) -> ExtractedVisibleCardFrame | None:
        if target_offset_ms != 0:
            raise VisibleCardBatchError("exact-event ffmpeg extraction requires target_offset_ms=0")
        if not video_path.is_file():
            raise VisibleCardFrameExtractionError(f"source video does not exist: {video_path}")
        metadata = self._probe(video_path)
        fps = _probe_frame_rate(metadata)
        width = _probe_positive_int(metadata, "width")
        height = _probe_positive_int(metadata, "height")
        frame_index = math.floor(event_time_s * fps + 0.5)
        frame_count = _probe_optional_positive_int(metadata, "nb_frames")
        if frame_count is not None and frame_index >= frame_count:
            return None
        filter_expression = f"select=eq(n\\,{frame_index})"
        try:
            result = subprocess.run(
                [
                    self.ffmpeg_binary,
                    "-v",
                    "error",
                    "-i",
                    str(video_path),
                    "-vf",
                    filter_expression,
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-c:v",
                    "mjpeg",
                    "-q:v",
                    "2",
                    "-",
                ],
                capture_output=True,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise VisibleCardFrameExtractionError(
                f"ffmpeg could not extract frame {frame_index}: {error}"
            ) from error
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise VisibleCardFrameExtractionError(
                f"ffmpeg could not extract frame {frame_index}: {detail or 'unknown error'}"
            )
        if not result.stdout:
            return None
        actual_offset_ms = math.floor(frame_index / fps * 1000.0 + 0.5) - math.floor(
            event_time_s * 1000.0 + 0.5
        )
        return ExtractedVisibleCardFrame(
            frame_index=frame_index,
            actual_offset_ms=actual_offset_ms,
            image_bytes=result.stdout,
            width=width,
            height=height,
            target_offset_ms=target_offset_ms,
        )

    def _probe(self, video_path: Path) -> Mapping[str, Any]:
        try:
            result = subprocess.run(
                [
                    self.ffprobe_binary,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=avg_frame_rate,width,height,nb_frames",
                    "-of",
                    "json",
                    str(video_path),
                ],
                capture_output=True,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise VisibleCardFrameExtractionError(
                f"ffprobe could not inspect source video: {error}"
            ) from error
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise VisibleCardFrameExtractionError(
                f"ffprobe could not inspect source video: {detail or 'unknown error'}"
            )
        try:
            value = json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise VisibleCardFrameExtractionError(
                "ffprobe returned invalid video metadata"
            ) from error
        if not isinstance(value, Mapping) or not isinstance(value.get("streams"), list):
            raise VisibleCardFrameExtractionError("ffprobe returned incomplete video metadata")
        streams = value["streams"]
        if not streams or not isinstance(streams[0], Mapping):
            raise VisibleCardFrameExtractionError("source video has no video stream")
        return streams[0]


@dataclass(frozen=True, slots=True)
class VisibleCardBatchFailure:
    """One explicit batch blocker or item failure."""

    code: str
    message: str
    stage: str
    item_id: str | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        if self.code not in VISIBLE_CARD_BATCH_FAILURE_CODES:
            raise VisibleCardBatchError(f"unknown visible-card batch failure code: {self.code}")
        _text(self.message, "failure.message")
        _text(self.stage, "failure.stage")
        if self.item_id is not None:
            _identifier(self.item_id, "failure.item_id")
        if not isinstance(self.retryable, bool):
            raise VisibleCardBatchError("failure.retryable must be a boolean")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "stage": self.stage,
            "item_id": self.item_id,
            "retryable": self.retryable,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "VisibleCardBatchFailure":
        fields = {"code", "message", "stage", "item_id", "retryable"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise VisibleCardBatchError("batch failure has unexpected fields")
        try:
            return cls(**dict(value))
        except (TypeError, ValueError, VisibleCardBatchError) as error:
            raise VisibleCardBatchError("batch failure is invalid") from error


@dataclass(frozen=True, slots=True)
class _ReviewedCardEvent:
    event_index: int
    event_id: str
    time_s: float
    time_ms: int


@dataclass(frozen=True, slots=True)
class _BatchItemDefinition:
    event: _ReviewedCardEvent
    package_id: str
    frame_part_name: str = "frame_00"

    @property
    def item_id(self) -> str:
        return f"{self.package_id}:{self.frame_part_name}"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest_value(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise VisibleCardBatchError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(character not in _IDENTIFIER_CHARACTERS for character in value)
    ):
        raise VisibleCardBatchError(f"{field} must be a simple non-empty identifier")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisibleCardBatchError(f"{field} must be a non-empty string")
    return value


def _probe_frame_rate(metadata: Mapping[str, Any]) -> float:
    value = metadata.get("avg_frame_rate")
    if not isinstance(value, str) or "/" not in value:
        raise VisibleCardFrameExtractionError("ffprobe returned an invalid frame rate")
    numerator, denominator = value.split("/", 1)
    try:
        fps = float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise VisibleCardFrameExtractionError("ffprobe returned an invalid frame rate") from error
    if not math.isfinite(fps) or fps <= 0:
        raise VisibleCardFrameExtractionError("ffprobe returned an invalid frame rate")
    return fps


def _probe_positive_int(metadata: Mapping[str, Any], field: str) -> int:
    value = metadata.get(field)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise VisibleCardFrameExtractionError(f"ffprobe returned an invalid {field}") from error
    if parsed <= 0:
        raise VisibleCardFrameExtractionError(f"ffprobe returned an invalid {field}")
    return parsed


def _probe_optional_positive_int(metadata: Mapping[str, Any], field: str) -> int | None:
    value = metadata.get(field)
    if value in {None, "N/A"}:
        return None
    return _probe_positive_int(metadata, field)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _file_digest(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as error:
        raise VisibleCardBatchError(f"could not read source file: {path}") from error


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardBatchError(f"could not read {context}: {path}") from error
    if not isinstance(value, dict):
        raise VisibleCardBatchError(f"{context} must be a JSON object: {path}")
    return value


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as error:
        raise VisibleCardBatchWriteError(
            f"could not save visible-card batch state: {path}"
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _immutable_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if path.read_bytes() == value:
                return
        except OSError as error:
            raise VisibleCardBatchWriteError(
                f"could not read immutable artifact: {path}"
            ) from error
        raise VisibleCardBatchWriteError(f"refusing to overwrite immutable batch artifact: {path}")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as error:
        raise VisibleCardBatchWriteError(
            f"could not save immutable batch artifact: {path}"
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _load_card_event_version(
    request: VisibleCardBatchRequest,
) -> tuple[dict[str, Any], tuple[_ReviewedCardEvent, ...]]:
    try:
        version = _read_json(request.card_event_review_version_path, "completed CardEvent review")
    except VisibleCardBatchError as error:
        raise VisibleCardBatchError(f"stale_annotation: {error}") from error
    if version.get("schema_version") != _CARD_EVENT_REVIEWED_SCHEMA:
        raise VisibleCardBatchError(
            "stale_annotation: completed CardEvent review schema is invalid"
        )
    if version.get("version_id") != request.card_event_review_version_id:
        raise VisibleCardBatchError(
            "stale_annotation: completed CardEvent review version ID changed"
        )
    if (
        version.get("recording_id") != request.recording_id
        or version.get("source_asset_id") != request.source_asset_id
        or version.get("source_sha256") != request.source_sha256
    ):
        raise VisibleCardBatchError("stale_annotation: completed CardEvent review source changed")
    version_digest = version.get("version_digest")
    version_core = {key: value for key, value in version.items() if key != "version_digest"}
    if (
        version_digest != request.card_event_review_version_digest
        or _digest_value(version_core) != version_digest
    ):
        raise VisibleCardBatchError("stale_annotation: completed CardEvent review digest changed")
    annotation = version.get("annotation")
    if (
        not isinstance(annotation, dict)
        or annotation.get("schema_version") != _CARD_EVENT_ANNOTATION_SCHEMA
    ):
        raise VisibleCardBatchError("stale_annotation: CardEvent annotation is invalid")
    if annotation.get("video") != request.video_path.name or not isinstance(
        annotation.get("events"), list
    ):
        raise VisibleCardBatchError(
            "stale_annotation: CardEvent annotation video or events changed"
        )
    if (
        version.get("reviewed_annotation_digest") != request.card_event_annotation_digest
        or _digest_value(annotation) != request.card_event_annotation_digest
    ):
        raise VisibleCardBatchError(
            "stale_annotation: reviewed CardEvent annotation digest changed"
        )

    selected: list[_ReviewedCardEvent] = []
    previous_time: float | None = None
    for event_index, event in enumerate(annotation["events"]):
        if not isinstance(event, Mapping):
            raise VisibleCardBatchError("stale_annotation: CardEvent event is invalid")
        time_s = event.get("time_s")
        if isinstance(time_s, bool) or not isinstance(time_s, (int, float)):
            raise VisibleCardBatchError("stale_annotation: CardEvent event time is invalid")
        time_s = float(time_s)
        if (
            not math.isfinite(time_s)
            or time_s < 0
            or (previous_time is not None and time_s < previous_time)
        ):
            raise VisibleCardBatchError("stale_annotation: CardEvent event order is invalid")
        previous_time = time_s
        if event.get("type") != "card_played" or event.get("confidence") not in {
            None,
            "confirmed",
        }:
            continue
        event_id = (
            "cardevent-event-"
            + _digest_value(
                {
                    "recording_id": request.recording_id,
                    "review_version_id": request.card_event_review_version_id,
                    "event_index": event_index,
                    "time_s": time_s,
                }
            )[:20]
        )
        selected.append(
            _ReviewedCardEvent(
                event_index=event_index,
                event_id=event_id,
                time_s=time_s,
                time_ms=math.floor(time_s * 1000.0 + 0.5),
            )
        )
    return version, tuple(selected)


def _item_definitions(
    request: VisibleCardBatchRequest, events: Sequence[_ReviewedCardEvent]
) -> tuple[_BatchItemDefinition, ...]:
    result = []
    for event in events:
        suffix = _digest_value(
            {
                "batch_id": request.batch_id,
                "event_id": event.event_id,
                "event_time_s": event.time_s,
            }
        )[:12]
        package_id = f"{request.recording_id}-vc-{event.event_index:04d}-{suffix}"
        result.append(_BatchItemDefinition(event=event, package_id=package_id))
    return tuple(result)


def _initial_item(item: _BatchItemDefinition) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "event": {
            "event_id": item.event.event_id,
            "event_index": item.event.event_index,
            "event_time_s": item.event.time_s,
            "event_time_ms": item.event.time_ms,
            "target_offset_ms": 0,
        },
        "status": "pending",
        "frame": None,
        "finder": None,
        "finder_attempt": 0,
        "failure": None,
    }


def _lineage_mapping(
    request: VisibleCardBatchRequest, item: Mapping[str, Any]
) -> dict[str, Any]:
    frame = item.get("frame")
    if not isinstance(frame, Mapping):
        raise VisibleCardBatchError("completed finder item has no source frame")
    return {
        "package_id": str(item["item_id"]).rsplit(":", 1)[0],
        "frame_part_name": str(item["item_id"]).rsplit(":", 1)[1],
        "target_offset_ms": request.target_offset_ms,
        "image": frame["path"],
        "frame_sha256": frame["sha256"],
        "source_asset_id": request.source_asset_id,
        "source_lineage_group": request.source_lineage_group,
        "source_asset_sha256": request.source_sha256,
        "width": frame["width"],
        "height": frame["height"],
    }


def _progress(items: Sequence[Mapping[str, Any]], *, phase: str, total: int) -> dict[str, Any]:
    return {
        "phase": phase,
        "total_items": total,
        "frames_extracted": sum(item.get("frame") is not None for item in items),
        "finder_completed": sum(
            item.get("finder") is not None and item.get("failure") is None for item in items
        ),
        "failed_items": sum(item.get("failure") is not None for item in items),
    }


def _state(
    request: VisibleCardBatchRequest,
    *,
    status: str,
    phase: str,
    created_at: str,
    updated_at: str,
    items: Sequence[Mapping[str, Any]],
    failures: Sequence[VisibleCardBatchFailure] = (),
    queue_path: str | None = None,
    queue_digest: str | None = None,
) -> dict[str, Any]:
    if status not in VISIBLE_CARD_BATCH_STATUSES or phase not in VISIBLE_CARD_BATCH_PHASES:
        raise VisibleCardBatchError("invalid visible-card batch state")
    return {
        "schema_version": VISIBLE_CARD_BATCH_SCHEMA_VERSION,
        "batch_id": request.batch_id,
        "request_digest": request.request_digest,
        "status": status,
        "created_at_utc": created_at,
        "updated_at_utc": updated_at,
        "frozen_inputs": request.to_mapping(),
        "progress": _progress(items, phase=phase, total=len(items)),
        "items": list(items),
        "failures": [failure.to_mapping() for failure in failures],
        "queue_schema_version": VISIBLE_CARD_REVIEW_QUEUE_SCHEMA,
        "queue_path": queue_path,
        "queue_digest": queue_digest,
    }


def _validate_batch_state(value: Any) -> dict[str, Any]:
    fields = {
        "schema_version",
        "batch_id",
        "request_digest",
        "status",
        "created_at_utc",
        "updated_at_utc",
        "frozen_inputs",
        "progress",
        "items",
        "failures",
        "queue_schema_version",
        "queue_path",
        "queue_digest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise VisibleCardBatchError("visible-card batch state has unexpected fields")
    if value["schema_version"] != VISIBLE_CARD_BATCH_SCHEMA_VERSION:
        raise VisibleCardBatchError("unsupported visible-card batch schema")
    _identifier(value["batch_id"], "batch_id")
    _digest(value["request_digest"], "request_digest")
    if value["status"] not in VISIBLE_CARD_BATCH_STATUSES:
        raise VisibleCardBatchError("visible-card batch status is invalid")
    for field_name in ("created_at_utc", "updated_at_utc"):
        _utc_timestamp(value[field_name], field_name)
    request = VisibleCardBatchRequest.from_mapping(value["frozen_inputs"])
    if value["batch_id"] != request.batch_id or value["request_digest"] != request.request_digest:
        raise VisibleCardBatchError("visible-card batch identity does not match frozen inputs")
    progress = value["progress"]
    if not isinstance(progress, dict) or set(progress) != {
        "phase",
        "total_items",
        "frames_extracted",
        "finder_completed",
        "failed_items",
    }:
        raise VisibleCardBatchError("visible-card batch progress is invalid")
    if progress["phase"] not in VISIBLE_CARD_BATCH_PHASES:
        raise VisibleCardBatchError("visible-card batch progress phase is invalid")
    for field_name in ("total_items", "frames_extracted", "finder_completed", "failed_items"):
        if (
            isinstance(progress[field_name], bool)
            or not isinstance(progress[field_name], int)
            or progress[field_name] < 0
        ):
            raise VisibleCardBatchError("visible-card batch progress counts are invalid")
    if not isinstance(value["items"], list) or not isinstance(value["failures"], list):
        raise VisibleCardBatchError("visible-card batch items and failures must be lists")
    for failure in value["failures"]:
        VisibleCardBatchFailure.from_mapping(failure)
    if value["queue_schema_version"] != VISIBLE_CARD_REVIEW_QUEUE_SCHEMA:
        raise VisibleCardBatchError("visible-card batch queue schema is invalid")
    if value["queue_path"] is not None:
        _text(value["queue_path"], "queue_path")
    if value["queue_digest"] is not None:
        _digest(value["queue_digest"], "queue_digest")
    if value["status"] == "ready" and (
        value["queue_path"] is None or value["queue_digest"] is None
    ):
        raise VisibleCardBatchError("ready visible-card batch needs a queue artifact")
    return value


def load_visible_card_review_batch(path: str | Path) -> dict[str, Any]:
    """Load and validate one persisted visible-card batch state."""

    return _validate_batch_state(_read_json(Path(path), "visible-card batch state"))


def assess_visible_card_review_readiness(
    *,
    task_enrollment_selected: bool,
    source_permission: str,
    allowed_uses: Sequence[str],
    source_lineage_group: str,
    protected_source_lineage_groups: Sequence[str],
    review_completed: bool,
    reviewed_card_event_count: int,
    detector_provider: str | None,
    detector_available: bool,
) -> tuple[VisibleCardBatchFailure, ...]:
    """Return the plain-language blockers for one recording-scoped batch preview."""

    if isinstance(reviewed_card_event_count, bool) or not isinstance(
        reviewed_card_event_count, int
    ):
        raise VisibleCardBatchError("reviewed_card_event_count must be an integer")
    blockers: list[VisibleCardBatchFailure] = []
    if detector_provider != "local":
        blockers.append(
            VisibleCardBatchFailure(
                code="non_local_provider",
                message="Only the configured local visible-card provider may run.",
                stage="preview",
            )
        )
    elif not detector_available:
        blockers.append(
            VisibleCardBatchFailure(
                code="provider_unavailable",
                message="The local visible-card finder is not available.",
                stage="preview",
            )
        )
    if not task_enrollment_selected:
        blockers.append(
            VisibleCardBatchFailure(
                code="task_enrollment_not_selected",
                message="Select the table-evidence task before creating a visible-card review.",
                stage="preview",
            )
        )
    if source_permission not in _SOURCE_PERMISSIONS or not set(allowed_uses).intersection(
        _ALLOWED_USES
    ):
        blockers.append(
            VisibleCardBatchFailure(
                code="disallowed_source_use",
                message="The source permission does not allow this data task.",
                stage="preview",
            )
        )
    if source_lineage_group in set(protected_source_lineage_groups):
        blockers.append(
            VisibleCardBatchFailure(
                code="protected_source_group",
                message="The source-lineage group is protected and cannot enter review.",
                stage="preview",
            )
        )
    if not review_completed:
        blockers.append(
            VisibleCardBatchFailure(
                code="stale_annotation",
                message="Complete the full CardEvent review before creating a visible-card batch.",
                stage="preview",
            )
        )
    elif reviewed_card_event_count <= 0:
        blockers.append(
            VisibleCardBatchFailure(
                code="no_reviewed_card_events",
                message="The completed CardEvent review has no reviewed card-played events.",
                stage="preview",
            )
        )
    return tuple(blockers)


def preview_visible_card_review_batch(
    request: VisibleCardBatchRequest,
    *,
    reviewed_card_event_count: int,
    development_partition: str | None = None,
    detector_available: bool = True,
) -> dict[str, Any]:
    """Create the path-independent preview that freezes one batch identity."""

    blockers = assess_visible_card_review_readiness(
        task_enrollment_selected=request.task_enrollment_selected,
        source_permission=request.source_permission,
        allowed_uses=request.allowed_uses,
        source_lineage_group=request.source_lineage_group,
        protected_source_lineage_groups=request.protected_source_lineage_groups,
        review_completed=True,
        reviewed_card_event_count=reviewed_card_event_count,
        detector_provider=request.detector.provider,
        detector_available=detector_available,
    )
    core = {
        "schema_version": "visible-card-review-preview/v1",
        "batch_id": request.batch_id,
        "request_digest": request.request_digest,
        "selected_event_count": reviewed_card_event_count,
        "detector": request.detector.to_mapping_without_path(),
    }
    return {
        **core,
        "recording_id": request.recording_id,
        "source_asset_id": request.source_asset_id,
        "source_sha256": request.source_sha256,
        "source_lineage_group": request.source_lineage_group,
        "task_enrollment_id": request.task_enrollment_id,
        "task_enrollment_selected": request.task_enrollment_selected,
        "source_permission": request.source_permission,
        "allowed_uses": list(request.allowed_uses),
        "card_event_review_version_id": request.card_event_review_version_id,
        "card_event_review_version_digest": request.card_event_review_version_digest,
        "card_event_annotation_digest": request.card_event_annotation_digest,
        "development_partition": development_partition,
        "preview_digest": _digest_value(core),
        "validation": {
            "valid": not blockers,
            "blockers": [blocker.to_mapping() for blocker in blockers],
        },
    }


class VisibleCardReviewBatchStore:
    """Persist deterministic batch preparation state below one operations workspace."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()

    def batch_root(self, batch_id: str) -> Path:
        return self.workspace_root / "visible-card-review-batches" / batch_id

    def batch_path(self, batch_id: str) -> Path:
        return self.batch_root(batch_id) / "batch.json"

    def initialize(self, request: VisibleCardBatchRequest) -> dict[str, Any]:
        """Persist a preparing state before extraction starts in a worker."""

        path = self.batch_path(request.batch_id)
        if path.is_file():
            current = load_visible_card_review_batch(path)
            if current["request_digest"] != request.request_digest:
                raise VisibleCardBatchError("stored visible-card batch request identity changed")
            return current
        state = _state(
            request,
            status="preparing",
            phase="validating_inputs",
            created_at=_now(),
            updated_at=_now(),
            items=(),
        )
        _atomic_write_json(path, state)
        return _validate_batch_state(state)

    def begin_retry(self, batch_id: str) -> dict[str, Any]:
        """Mark one failed batch as preparing while keeping its frozen work state."""

        path = self.batch_path(batch_id)
        current = load_visible_card_review_batch(path)
        if current["status"] != "failed":
            raise VisibleCardBatchError("only a failed visible-card batch can be retried")
        request = VisibleCardBatchRequest.from_mapping(current["frozen_inputs"])
        state = _state(
            request,
            status="preparing",
            phase="extracting_frames",
            created_at=current["created_at_utc"],
            updated_at=_now(),
            items=current["items"],
        )
        _atomic_write_json(path, state)
        return _validate_batch_state(state)

    def prepare(
        self,
        request: VisibleCardBatchRequest,
        provider: VisibleCardProvider,
        *,
        frame_extractor: VisibleCardFrameExtractor | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        """Prepare one exact-event queue and return its persisted batch projection.

        Expected source, review, frame, and provider failures become explicit ``blocked`` or
        ``failed`` batch states.  They do not produce a partial completed review queue.
        """

        batch_root = self.batch_root(request.batch_id)
        state_path = batch_root / "batch.json"
        if state_path.is_file():
            current = load_visible_card_review_batch(state_path)
            if current["request_digest"] != request.request_digest:
                raise VisibleCardBatchError("stored visible-card batch request identity changed")
            if current["status"] == "ready" or (
                current["status"] in {"blocked", "failed"} and not resume
            ):
                return current

        created_at = _now()
        existing_state: dict[str, Any] | None = None
        if state_path.is_file():
            existing_state = load_visible_card_review_batch(state_path)
            created_at = existing_state["created_at_utc"]

        if request.source_lineage_group in set(request.protected_source_lineage_groups):
            return self._persist_terminal(
                request,
                status="blocked",
                phase="blocked",
                created_at=created_at,
                failures=(
                    VisibleCardBatchFailure(
                        code="protected_source_group",
                        message="The source-lineage group is protected and cannot enter review.",
                        stage="validation",
                    ),
                ),
            )
        if request.detector.provider != "local":
            return self._persist_terminal(
                request,
                status="blocked",
                phase="blocked",
                created_at=created_at,
                failures=(
                    VisibleCardBatchFailure(
                        code="non_local_provider",
                        message="Only the configured local visible-card provider may run.",
                        stage="validation",
                    ),
                ),
            )
        if not request.task_enrollment_selected:
            return self._persist_terminal(
                request,
                status="blocked",
                phase="blocked",
                created_at=created_at,
                failures=(
                    VisibleCardBatchFailure(
                        code="task_enrollment_not_selected",
                        message="The table-evidence task enrollment is not selected.",
                        stage="validation",
                    ),
                ),
            )
        if request.source_permission not in _SOURCE_PERMISSIONS or not set(
            request.allowed_uses
        ).intersection(_ALLOWED_USES):
            return self._persist_terminal(
                request,
                status="blocked",
                phase="blocked",
                created_at=created_at,
                failures=(
                    VisibleCardBatchFailure(
                        code="disallowed_source_use",
                        message="The source permission does not allow this data task.",
                        stage="validation",
                    ),
                ),
            )
        if not request.video_path.is_file():
            return self._persist_terminal(
                request,
                status="blocked",
                phase="blocked",
                created_at=created_at,
                failures=(
                    VisibleCardBatchFailure(
                        code="missing_source_video",
                        message="The accepted source video is missing.",
                        stage="validation",
                    ),
                ),
            )
        try:
            if _file_digest(request.video_path) != request.source_sha256:
                raise VisibleCardBatchError("source_digest_mismatch: accepted source video changed")
            _, events = _load_card_event_version(request)
        except VisibleCardBatchError as error:
            message = str(error)
            code = (
                "stale_annotation"
                if message.startswith("stale_annotation:")
                else "source_digest_mismatch"
            )
            return self._persist_terminal(
                request,
                status="blocked",
                phase="blocked",
                created_at=created_at,
                failures=(VisibleCardBatchFailure(code=code, message=message, stage="validation"),),
            )
        if not events:
            return self._persist_terminal(
                request,
                status="blocked",
                phase="blocked",
                created_at=created_at,
                failures=(
                    VisibleCardBatchFailure(
                        code="no_reviewed_card_events",
                        message=(
                            "The completed CardEvent review has no reviewed card-played events."
                        ),
                        stage="validation",
                    ),
                ),
            )

        definitions = _item_definitions(request, events)
        previous_items = {
            item["item_id"]: item
            for item in (existing_state or {}).get("items", [])
            if isinstance(item, Mapping) and isinstance(item.get("item_id"), str)
        }
        items: list[dict[str, Any]] = []
        for definition in definitions:
            previous = previous_items.get(definition.item_id)
            if not resume or previous is None:
                items.append(_initial_item(definition))
                continue
            item = dict(previous)
            if item.get("failure") is not None:
                item["failure"] = None
                item["finder"] = None
                item["status"] = "frame_extracted" if item.get("frame") is not None else "pending"
                item["finder_attempt"] = int(item.get("finder_attempt", 0)) + 1
            items.append(item)
        current = _state(
            request,
            status="preparing",
            phase="extracting_frames",
            created_at=created_at,
            updated_at=_now(),
            items=items,
        )
        _atomic_write_json(state_path, current)
        extractor = frame_extractor or FFmpegVisibleCardFrameExtractor()
        artifact_paths: dict[str, tuple[Path, Path]] = {}
        for index, definition in enumerate(definitions):
            item = items[index]
            if item["frame"] is not None:
                artifact_paths[definition.item_id] = (
                    Path(item["frame"]["path"]),
                    batch_root / "finder-results" / f"{definition.package_id}.json",
                )
                continue
            try:
                frame = _call_extractor(
                    extractor,
                    request.video_path,
                    event_time_s=definition.event.time_s,
                    target_offset_ms=request.target_offset_ms,
                )
                if frame is None:
                    raise VisibleCardMissingFrameError(
                        f"exact event frame is missing at {definition.event.time_s:.3f}s"
                    )
                frame_path = (
                    batch_root
                    / "frames"
                    / definition.package_id
                    / f"{definition.frame_part_name}.jpg"
                )
                _immutable_bytes(frame_path, frame.image_bytes)
                item["frame"] = frame.to_mapping(path=str(frame_path.resolve()))
                item["status"] = "frame_extracted"
            except VisibleCardMissingFrameError as error:
                item["failure"] = VisibleCardBatchFailure(
                    code="missing_frame",
                    message=str(error),
                    stage="frame_extraction",
                ).to_mapping()
                item["status"] = "failed"
            except Exception as error:
                item["failure"] = VisibleCardBatchFailure(
                    code="frame_extraction_error",
                    message=str(error),
                    stage="frame_extraction",
                    retryable=True,
                ).to_mapping()
                item["status"] = "failed"
            if item["frame"] is not None:
                artifact_paths[definition.item_id] = (
                    Path(item["frame"]["path"]),
                    batch_root / "finder-results" / f"{definition.package_id}.json",
                )
            current = _state(
                request,
                status="preparing",
                phase="extracting_frames",
                created_at=created_at,
                updated_at=_now(),
                items=items,
            )
            _atomic_write_json(state_path, current)

        if any(item["failure"] is not None for item in items):
            failures = tuple(
                VisibleCardBatchFailure(
                    code=item["failure"]["code"],
                    message=item["failure"]["message"],
                    stage=item["failure"]["stage"],
                    item_id=item["item_id"],
                    retryable=item["failure"]["retryable"],
                )
                for item in items
                if item["failure"] is not None
            )
            return self._persist_terminal(
                request,
                status="failed",
                phase="failed",
                created_at=created_at,
                items=items,
                failures=failures,
            )

        current = _state(
            request,
            status="preparing",
            phase="running_finder",
            created_at=created_at,
            updated_at=_now(),
            items=items,
        )
        _atomic_write_json(state_path, current)
        artifacts: list[Mapping[str, Any]] = []
        lineage_by_item: dict[str, dict[str, Any]] = {}
        failures: list[VisibleCardBatchFailure] = []
        for index, definition in enumerate(definitions):
            item = items[index]
            frame = item["frame"]
            if item["finder"] is not None and item["failure"] is None:
                finder = item["finder"]
                result_path = Path(finder["result_path"])
                artifact = _read_json(result_path, "visible-card finder result")
                artifact["artifact_path"] = str(result_path.resolve())
                artifacts.append(artifact)
                lineage_by_item[definition.item_id] = _lineage_mapping(request, item)
                continue
            attempt = int(item.get("finder_attempt", 0))
            suffix = f"-retry-{attempt}" if attempt else ""
            result_path = batch_root / "finder-results" / f"{definition.package_id}{suffix}.json"
            artifact_paths[definition.item_id] = (Path(frame["path"]), result_path)
            try:
                visible_request = build_request_from_image(
                    frame["path"],
                    package_id=definition.package_id,
                    frame_part_name=definition.frame_part_name,
                    target_offset_ms=request.target_offset_ms,
                    width=frame["width"],
                    height=frame["height"],
                    model=request.detector.model,
                    provider=request.detector.provider,
                    request_version=request.request_version,
                )
            except Exception as error:
                failure = VisibleCardBatchFailure(
                    code="invalid_provider_result",
                    message=str(error),
                    stage="finder",
                    item_id=definition.item_id,
                    retryable=False,
                )
                item["failure"] = failure.to_mapping()
                item["status"] = "failed"
                failures.append(failure)
                current = _state(
                    request,
                    status="preparing",
                    phase="running_finder",
                    created_at=created_at,
                    updated_at=_now(),
                    items=items,
                )
                _atomic_write_json(state_path, current)
                continue

            try:
                result = provider.propose(visible_request)
            except Exception as error:
                result = ProviderResult(
                    status="unavailable",
                    error=f"provider call failed: {error}",
                )
            try:
                if not isinstance(result, ProviderResult):
                    raise VisibleCardBatchError("provider returned a non-ProviderResult value")
                artifact = _run_artifact_mapping(visible_request, result, image=frame["path"])
                artifact_bytes = _canonical(artifact) + b"\n"
                _immutable_bytes(result_path, artifact_bytes)
                item["finder"] = {
                    "provider": {
                        "name": request.detector.provider,
                        "version": request.detector.provider_version,
                    },
                    "detector": request.detector.to_mapping(),
                    "request_digest": visible_request.request_key,
                    "request": visible_request.to_mapping(),
                    "result_path": str(result_path.resolve()),
                    "result_digest": hashlib.sha256(artifact_bytes).hexdigest(),
                    "result": result.to_mapping(),
                    "prediction_sha256": _digest_value(result.prediction.to_mapping()),
                }
                if result.status == "ok":
                    artifact_with_path = dict(artifact)
                    artifact_with_path["artifact_path"] = str(result_path.resolve())
                    artifacts.append(artifact_with_path)
                    item["status"] = "finder_complete"
                else:
                    failure = VisibleCardBatchFailure(
                        code="provider_error",
                        message=result.error or "local visible-card provider failed",
                        stage="finder",
                        item_id=definition.item_id,
                        retryable=True,
                    )
                    item["failure"] = failure.to_mapping()
                    item["status"] = "failed"
                    failures.append(failure)
            except Exception as error:
                failure = VisibleCardBatchFailure(
                    code="invalid_provider_result",
                    message=str(error),
                    stage="finder",
                    item_id=definition.item_id,
                    retryable=False,
                )
                item["failure"] = failure.to_mapping()
                item["status"] = "failed"
                failures.append(failure)
            current = _state(
                request,
                status="preparing",
                phase="running_finder",
                created_at=created_at,
                updated_at=_now(),
                items=items,
            )
            _atomic_write_json(state_path, current)

            if item["failure"] is None:
                lineage_by_item[definition.item_id] = _lineage_mapping(request, item)

        if failures:
            return self._persist_terminal(
                request,
                status="failed",
                phase="failed",
                created_at=created_at,
                items=items,
                failures=failures,
            )

        queue_path = batch_root / "review-queue.json"
        try:
            if queue_path.is_file():
                queue = load_visible_card_review_queue(queue_path)
            else:
                queue = build_visible_card_review_queue(
                    artifacts,
                    queue_path,
                    run_id=request.batch_id,
                    lineage_by_item=lineage_by_item,
                )
            if queue.run_id != request.batch_id:
                raise VisibleCardBatchError("stored review queue batch identity changed")
            queue_bytes = queue_path.read_bytes()
        except Exception as error:
            failure = VisibleCardBatchFailure(
                code="queue_error",
                message=str(error),
                stage="queue",
            )
            return self._persist_terminal(
                request,
                status="failed",
                phase="failed",
                created_at=created_at,
                items=items,
                failures=(failure,),
            )
        return self._persist_terminal(
            request,
            status="ready",
            phase="ready",
            created_at=created_at,
            items=items,
            queue_path=str(queue_path.resolve()),
            queue_digest=hashlib.sha256(queue_bytes).hexdigest(),
        )

    def _persist_terminal(
        self,
        request: VisibleCardBatchRequest,
        *,
        status: str,
        phase: str,
        created_at: str,
        items: Sequence[Mapping[str, Any]] = (),
        failures: Sequence[VisibleCardBatchFailure] = (),
        queue_path: str | None = None,
        queue_digest: str | None = None,
    ) -> dict[str, Any]:
        path = self.batch_path(request.batch_id)
        current = _state(
            request,
            status=status,
            phase=phase,
            created_at=created_at,
            updated_at=_now(),
            items=items,
            failures=failures,
            queue_path=queue_path,
            queue_digest=queue_digest,
        )
        _atomic_write_json(path, current)
        return _validate_batch_state(current)


def _call_extractor(
    extractor: VisibleCardFrameExtractor,
    video_path: Path,
    *,
    event_time_s: float,
    target_offset_ms: int,
) -> ExtractedVisibleCardFrame | None:
    method = getattr(extractor, "extract", None)
    if callable(method):
        return method(video_path, event_time_s=event_time_s, target_offset_ms=target_offset_ms)
    if callable(extractor):
        return extractor(video_path, event_time_s=event_time_s, target_offset_ms=target_offset_ms)  # type: ignore[misc]
    raise VisibleCardFrameExtractionError("frame extractor does not implement extract")


def _run_artifact_mapping(request: Any, result: ProviderResult, *, image: str) -> dict[str, Any]:
    return {
        "schema_version": "visible-card-run/v1",
        "prediction_schema_version": "visible-card-prediction/v1",
        "request_key": request.request_key,
        "request": request.to_mapping(),
        "provider": {"name": request.provider, "model": request.model},
        "image": image,
        "overlay": None,
        **result.to_mapping(),
    }


def _utc_timestamp(value: Any, field: str) -> str:
    _text(value, field)
    if not value.endswith("Z"):
        raise VisibleCardBatchError(f"{field} must use UTC with a Z suffix")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise VisibleCardBatchError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.utcoffset() != datetime.now(UTC).utcoffset():
        raise VisibleCardBatchError(f"{field} must use UTC")
    return value


def prepare_visible_card_review_batch(
    workspace_root: str | Path,
    request: VisibleCardBatchRequest,
    provider: VisibleCardProvider,
    *,
    frame_extractor: VisibleCardFrameExtractor | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Prepare one visible-card review batch through the application boundary."""

    return VisibleCardReviewBatchStore(workspace_root).prepare(
        request,
        provider,
        frame_extractor=frame_extractor,
        resume=resume,
    )


VisibleCardReviewBatchRequest = VisibleCardBatchRequest
VisibleCardBatchStore = VisibleCardReviewBatchStore
run_visible_card_review_batch = prepare_visible_card_review_batch


__all__ = [
    "ExtractedVisibleCardFrame",
    "FFmpegVisibleCardFrameExtractor",
    "OpenCVVisibleCardFrameExtractor",
    "VISIBLE_CARD_BATCH_FAILURE_CODES",
    "VISIBLE_CARD_BATCH_PHASES",
    "VISIBLE_CARD_BATCH_SCHEMA",
    "VISIBLE_CARD_BATCH_SCHEMA_VERSION",
    "VISIBLE_CARD_BATCH_STATUSES",
    "VisibleCardBatchError",
    "VisibleCardBatchFailure",
    "VisibleCardBatchRequest",
    "VisibleCardBatchStore",
    "VisibleCardBatchWriteError",
    "VisibleCardDetectorIdentity",
    "VisibleCardFrameExtractionError",
    "VisibleCardMissingFrameError",
    "VisibleCardReviewBatchRequest",
    "VisibleCardReviewBatchStore",
    "VisibleCardFrameExtractor",
    "assess_visible_card_review_readiness",
    "load_visible_card_review_batch",
    "prepare_visible_card_review_batch",
    "preview_visible_card_review_batch",
    "run_visible_card_review_batch",
]
