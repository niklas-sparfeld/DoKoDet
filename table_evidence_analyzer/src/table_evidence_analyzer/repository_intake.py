"""Typed models for shared pending-video and evidence-package intake contracts."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class RepositoryIntakeModel(BaseModel):
    """A closed, strict JSON contract model."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PendingVideoMediaFacts(RepositoryIntakeModel):
    container: str = Field(min_length=1)
    video_codec: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    nominal_frame_rate: float = Field(gt=0)
    duration_ms: int = Field(gt=0)
    frame_count: int = Field(gt=0)

    @field_validator("nominal_frame_rate")
    @classmethod
    def finite_frame_rate(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("nominal_frame_rate must be finite")
        return value


class PendingVideo(RepositoryIntakeModel):
    schema_version: Literal["pending-video/v1"]
    upload_id: Identifier
    state: Literal["pending"]
    original_filename: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
    byte_length: int = Field(gt=0)
    sha256: Sha256
    media_type: Literal["video/quicktime", "video/mp4"]
    received_at_utc: str
    media_facts: PendingVideoMediaFacts

    @field_validator("received_at_utc")
    @classmethod
    def utc_timestamp(cls, value: str) -> str:
        if not value.endswith("Z"):
            raise ValueError("received_at_utc must use UTC with a Z suffix")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as error:
            raise ValueError("received_at_utc must be an ISO-8601 timestamp") from error
        if parsed.utcoffset() != timedelta(0):
            raise ValueError("received_at_utc must use UTC")
        return value


class EvidencePackageRecord(RepositoryIntakeModel):
    schema_version: Literal["evidence-package-record/v1"]
    package_id: Identifier
    source_asset_id: Identifier
    source_permission: Literal[
        "training_only", "training_and_evaluation", "project_use", "unrestricted"
    ]
    allowed_uses: list[Literal["train", "validation", "test", "evaluation"]] = Field(min_length=1)
    retention_state: Literal["active", "deletion_requested", "deleted", "retired"]
    notes: str | None

    @field_validator("allowed_uses")
    @classmethod
    def unique_allowed_uses(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("allowed_uses must not contain duplicate values")
        return value


class EvidencePackageLineage(RepositoryIntakeModel):
    schema_version: Literal["evidence-package-lineage/v1"]
    package_id: Identifier
    parent_source_asset_id: Identifier | None
    parent_recording_id: Identifier | None
    parent_video_id: Identifier | None
    session_id: Identifier | None


class EvidencePackageFile(RepositoryIntakeModel):
    relative_path: str = Field(min_length=1)
    type: str = Field(min_length=1)
    byte_length: int = Field(gt=0)
    sha256: Sha256

    @field_validator("relative_path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
            raise ValueError("relative_path must be a safe relative path")
        return value


class EvidencePackageFiles(RepositoryIntakeModel):
    evidence_manifest: EvidencePackageFile
    package_record: EvidencePackageFile
    task_enrollment: EvidencePackageFile
    lineage: EvidencePackageFile
    frames: list[EvidencePackageFile]
    video_snippet: EvidencePackageFile | None

    @model_validator(mode="after")
    def validate_member_paths(self) -> EvidencePackageFiles:
        fixed = {
            "evidence_manifest": ("evidence-manifest.json", "application/json"),
            "package_record": ("package-record.json", "application/json"),
            "task_enrollment": ("initial-task-enrollment.json", "application/json"),
            "lineage": ("lineage.json", "application/json"),
        }
        for name, expected in fixed.items():
            member = getattr(self, name)
            if (member.relative_path, member.type) != expected:
                raise ValueError(f"{name} has an invalid path or media type")
        paths = [member.relative_path for member in self.frames]
        if len(paths) != len(set(paths)) or any(
            not member.relative_path.startswith("frames/")
            or not member.relative_path.endswith(".jpg")
            or member.type != "image/jpeg"
            for member in self.frames
        ):
            raise ValueError("frames must be unique JPEG members below frames/")
        if self.video_snippet is not None and (
            not self.video_snippet.relative_path.startswith("video/")
            or not self.video_snippet.relative_path.endswith(".mp4")
            or self.video_snippet.type != "video/mp4"
        ):
            raise ValueError("video_snippet must be an MP4 member below video/")
        return self


class EvidencePackageBundle(RepositoryIntakeModel):
    schema_version: Literal["evidence-package-bundle/v1"]
    package_id: Identifier
    source_asset_id: Identifier
    state: Literal["complete"]
    files: EvidencePackageFiles


def parse_pending_video(raw: bytes) -> PendingVideo:
    return PendingVideo.model_validate(_parse(raw, "pending video"))


def parse_evidence_package_bundle(raw: bytes) -> EvidencePackageBundle:
    return EvidencePackageBundle.model_validate(_parse(raw, "evidence package bundle"))


def parse_evidence_package_record(raw: bytes) -> EvidencePackageRecord:
    return EvidencePackageRecord.model_validate(_parse(raw, "evidence package record"))


def parse_evidence_package_lineage(raw: bytes) -> EvidencePackageLineage:
    return EvidencePackageLineage.model_validate(_parse(raw, "evidence package lineage"))


def _parse(raw: bytes, context: str) -> dict[str, object]:
    if not isinstance(raw, bytes):
        raise TypeError(f"{context} must be bytes")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{context} must be UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


__all__ = [
    "EvidencePackageBundle",
    "EvidencePackageFile",
    "EvidencePackageFiles",
    "EvidencePackageLineage",
    "EvidencePackageRecord",
    "PendingVideo",
    "PendingVideoMediaFacts",
    "parse_evidence_package_bundle",
    "parse_evidence_package_lineage",
    "parse_evidence_package_record",
    "parse_pending_video",
]
