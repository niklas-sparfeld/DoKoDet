"""Strict standard-library models for shared repository intake documents."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Mapping

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DATA_TASKS = frozenset({"cardevent_event_detection", "table_evidence_analysis"})
USES = frozenset({"train", "validation", "test", "evaluation"})


class IntakeContractError(ValueError):
    """Raised when a repository intake document is not strict and valid."""


def _strict(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    if set(value) != expected:
        missing = expected - set(value)
        unknown = set(value) - expected
        detail = []
        if missing:
            detail.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            detail.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise IntakeContractError(f"{context} has invalid fields ({'; '.join(detail)}).")


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntakeContractError(f"{context} must be an object.")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise IntakeContractError(f"{field} must be a non-empty string.")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if IDENTIFIER.fullmatch(result) is None:
        raise IntakeContractError(f"{field} must be a safe identifier.")
    return result


def _digest(value: Any, field: str) -> str:
    result = _text(value, field)
    if SHA256.fullmatch(result) is None:
        raise IntakeContractError(f"{field} must be a lower-case SHA-256 digest.")
    return result


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise IntakeContractError(f"{field} must be a positive integer.")
    return value


def _nullable_identifier(value: Any, field: str) -> str | None:
    return None if value is None else _identifier(value, field)


def _timestamp(value: Any, field: str) -> str:
    result = _text(value, field)
    if not result.endswith("Z"):
        raise IntakeContractError(f"{field} must use UTC with a Z suffix.")
    try:
        parsed = datetime.fromisoformat(result[:-1] + "+00:00")
    except ValueError as error:
        raise IntakeContractError(f"{field} must be an ISO-8601 timestamp.") from error
    if parsed.utcoffset() != timedelta(0):
        raise IntakeContractError(f"{field} must use UTC.")
    return result


@dataclass(frozen=True, slots=True)
class PendingVideoMediaFacts:
    container: str
    video_codec: str
    width: int
    height: int
    nominal_frame_rate: float
    duration_ms: int
    frame_count: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "PendingVideoMediaFacts":
        data = _mapping(raw, "media_facts")
        fields = {
            "container",
            "video_codec",
            "width",
            "height",
            "nominal_frame_rate",
            "duration_ms",
            "frame_count",
        }
        _strict(data, fields, "media_facts")
        frame_rate = data["nominal_frame_rate"]
        if (
            isinstance(frame_rate, bool)
            or not isinstance(frame_rate, (int, float))
            or not math.isfinite(float(frame_rate))
            or frame_rate <= 0
        ):
            raise IntakeContractError("media_facts.nominal_frame_rate must be finite and positive.")
        return cls(
            container=_text(data["container"], "media_facts.container"),
            video_codec=_text(data["video_codec"], "media_facts.video_codec"),
            width=_positive_int(data["width"], "media_facts.width"),
            height=_positive_int(data["height"], "media_facts.height"),
            nominal_frame_rate=float(frame_rate),
            duration_ms=_positive_int(data["duration_ms"], "media_facts.duration_ms"),
            frame_count=_positive_int(data["frame_count"], "media_facts.frame_count"),
        )


@dataclass(frozen=True, slots=True)
class PendingVideo:
    upload_id: str
    original_filename: str
    byte_length: int
    sha256: str
    media_type: str
    received_at_utc: str
    media_facts: PendingVideoMediaFacts

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "PendingVideo":
        data = _mapping(raw, "pending video")
        _strict(
            data,
            {
                "schema_version",
                "upload_id",
                "state",
                "original_filename",
                "byte_length",
                "sha256",
                "media_type",
                "received_at_utc",
                "media_facts",
            },
            "pending video",
        )
        if data["schema_version"] != "pending-video/v1" or data["state"] != "pending":
            raise IntakeContractError("pending video must use pending-video/v1 and pending state.")
        filename = _text(data["original_filename"], "original_filename")
        if FILENAME.fullmatch(filename) is None:
            raise IntakeContractError("original_filename must be a safe filename.")
        media_type = data["media_type"]
        if media_type not in {"video/quicktime", "video/mp4"}:
            raise IntakeContractError("media_type is not supported.")
        return cls(
            upload_id=_identifier(data["upload_id"], "upload_id"),
            original_filename=filename,
            byte_length=_positive_int(data["byte_length"], "byte_length"),
            sha256=_digest(data["sha256"], "sha256"),
            media_type=media_type,
            received_at_utc=_timestamp(data["received_at_utc"], "received_at_utc"),
            media_facts=PendingVideoMediaFacts.from_mapping(data["media_facts"]),
        )


@dataclass(frozen=True, slots=True)
class EvidencePackageFile:
    relative_path: str
    type: str
    byte_length: int
    sha256: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> "EvidencePackageFile":
        data = _mapping(raw, context)
        _strict(data, {"relative_path", "type", "byte_length", "sha256"}, context)
        relative_path = _text(data["relative_path"], f"{context}.relative_path")
        path = PurePosixPath(relative_path)
        if path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
            raise IntakeContractError(f"{context}.relative_path is unsafe.")
        return cls(
            relative_path=relative_path,
            type=_text(data["type"], f"{context}.type"),
            byte_length=_positive_int(data["byte_length"], f"{context}.byte_length"),
            sha256=_digest(data["sha256"], f"{context}.sha256"),
        )


@dataclass(frozen=True, slots=True)
class EvidencePackageFiles:
    evidence_manifest: EvidencePackageFile
    package_record: EvidencePackageFile
    task_enrollment: EvidencePackageFile
    lineage: EvidencePackageFile
    frames: tuple[EvidencePackageFile, ...]
    video_snippet: EvidencePackageFile | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "EvidencePackageFiles":
        data = _mapping(raw, "evidence package files")
        _strict(
            data,
            {
                "evidence_manifest",
                "package_record",
                "task_enrollment",
                "lineage",
                "frames",
                "video_snippet",
            },
            "evidence package files",
        )
        fixed = {
            "evidence_manifest": ("evidence-manifest.json", "application/json"),
            "package_record": ("package-record.json", "application/json"),
            "task_enrollment": ("initial-task-enrollment.json", "application/json"),
            "lineage": ("lineage.json", "application/json"),
        }
        values: dict[str, EvidencePackageFile] = {}
        for name, expected in fixed.items():
            member = EvidencePackageFile.from_mapping(data[name], f"files.{name}")
            if (member.relative_path, member.type) != expected:
                raise IntakeContractError(f"files.{name} has an invalid path or media type.")
            values[name] = member
        raw_frames = data["frames"]
        if not isinstance(raw_frames, list):
            raise IntakeContractError("files.frames must be a list.")
        frames = tuple(
            EvidencePackageFile.from_mapping(value, f"files.frames[{index}]")
            for index, value in enumerate(raw_frames)
        )
        if len({item.relative_path for item in frames}) != len(frames) or any(
            not item.relative_path.startswith("frames/")
            or not item.relative_path.endswith(".jpg")
            or item.type != "image/jpeg"
            for item in frames
        ):
            raise IntakeContractError("files.frames must be unique JPEG members below frames/.")
        snippet = data["video_snippet"]
        video_snippet = (
            None
            if snippet is None
            else EvidencePackageFile.from_mapping(snippet, "files.video_snippet")
        )
        if video_snippet is not None and (
            not video_snippet.relative_path.startswith("video/")
            or not video_snippet.relative_path.endswith(".mp4")
            or video_snippet.type != "video/mp4"
        ):
            raise IntakeContractError("files.video_snippet must be an MP4 member below video/.")
        return cls(
            evidence_manifest=values["evidence_manifest"],
            package_record=values["package_record"],
            task_enrollment=values["task_enrollment"],
            lineage=values["lineage"],
            frames=frames,
            video_snippet=video_snippet,
        )


@dataclass(frozen=True, slots=True)
class EvidencePackageBundle:
    package_id: str
    source_asset_id: str
    files: EvidencePackageFiles

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "EvidencePackageBundle":
        data = _mapping(raw, "evidence package bundle")
        _strict(
            data,
            {"schema_version", "package_id", "source_asset_id", "state", "files"},
            "evidence package bundle",
        )
        if data["schema_version"] != "evidence-package-bundle/v1" or data["state"] != "complete":
            raise IntakeContractError("evidence package bundle must be complete v1.")
        return cls(
            package_id=_identifier(data["package_id"], "package_id"),
            source_asset_id=_identifier(data["source_asset_id"], "source_asset_id"),
            files=EvidencePackageFiles.from_mapping(data["files"]),
        )


@dataclass(frozen=True, slots=True)
class EvidencePackageRecord:
    package_id: str
    source_asset_id: str
    source_permission: str
    allowed_uses: tuple[str, ...]
    retention_state: str
    notes: str | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "EvidencePackageRecord":
        data = _mapping(raw, "evidence package record")
        _strict(
            data,
            {
                "schema_version",
                "package_id",
                "source_asset_id",
                "source_permission",
                "allowed_uses",
                "retention_state",
                "notes",
            },
            "evidence package record",
        )
        if data["schema_version"] != "evidence-package-record/v1":
            raise IntakeContractError("evidence package record schema is unsupported.")
        uses = data["allowed_uses"]
        if (
            not isinstance(uses, list)
            or not uses
            or any(use not in USES for use in uses)
            or len(set(uses)) != len(uses)
        ):
            raise IntakeContractError("evidence package allowed_uses is invalid.")
        if data["source_permission"] not in {
            "training_only",
            "training_and_evaluation",
            "project_use",
            "unrestricted",
        }:
            raise IntakeContractError("evidence package source_permission is invalid.")
        if data["retention_state"] not in {"active", "deletion_requested", "deleted", "retired"}:
            raise IntakeContractError("evidence package retention_state is invalid.")
        notes = data["notes"]
        if notes is not None and not isinstance(notes, str):
            raise IntakeContractError("evidence package notes must be text or null.")
        return cls(
            package_id=_identifier(data["package_id"], "package_id"),
            source_asset_id=_identifier(data["source_asset_id"], "source_asset_id"),
            source_permission=data["source_permission"],
            allowed_uses=tuple(uses),
            retention_state=data["retention_state"],
            notes=notes,
        )


@dataclass(frozen=True, slots=True)
class EvidencePackageLineage:
    package_id: str
    parent_source_asset_id: str | None
    parent_recording_id: str | None
    parent_video_id: str | None
    session_id: str | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "EvidencePackageLineage":
        data = _mapping(raw, "evidence package lineage")
        _strict(
            data,
            {
                "schema_version",
                "package_id",
                "parent_source_asset_id",
                "parent_recording_id",
                "parent_video_id",
                "session_id",
            },
            "evidence package lineage",
        )
        if data["schema_version"] != "evidence-package-lineage/v1":
            raise IntakeContractError("evidence package lineage schema is unsupported.")
        return cls(
            package_id=_identifier(data["package_id"], "package_id"),
            parent_source_asset_id=_nullable_identifier(
                data["parent_source_asset_id"], "parent_source_asset_id"
            ),
            parent_recording_id=_nullable_identifier(
                data["parent_recording_id"], "parent_recording_id"
            ),
            parent_video_id=_nullable_identifier(data["parent_video_id"], "parent_video_id"),
            session_id=_nullable_identifier(data["session_id"], "session_id"),
        )


def parse_json_bytes(raw: bytes, context: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IntakeContractError(f"{context} must be UTF-8 JSON.") from error
    return _mapping(value, context)


def parse_pending_video(raw: bytes) -> PendingVideo:
    return PendingVideo.from_mapping(parse_json_bytes(raw, "pending video"))


def parse_evidence_package_bundle(raw: bytes) -> EvidencePackageBundle:
    return EvidencePackageBundle.from_mapping(parse_json_bytes(raw, "evidence package bundle"))


def parse_evidence_package_record(raw: bytes) -> EvidencePackageRecord:
    return EvidencePackageRecord.from_mapping(parse_json_bytes(raw, "evidence package record"))


def parse_evidence_package_lineage(raw: bytes) -> EvidencePackageLineage:
    return EvidencePackageLineage.from_mapping(parse_json_bytes(raw, "evidence package lineage"))


__all__ = [
    "EvidencePackageBundle",
    "EvidencePackageFile",
    "EvidencePackageFiles",
    "EvidencePackageLineage",
    "EvidencePackageRecord",
    "IntakeContractError",
    "PendingVideo",
    "PendingVideoMediaFacts",
    "parse_evidence_package_bundle",
    "parse_evidence_package_lineage",
    "parse_evidence_package_record",
    "parse_pending_video",
]
