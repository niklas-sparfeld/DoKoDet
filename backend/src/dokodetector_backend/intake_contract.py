"""Backend typed models for the shared repository-intake contract.

This module validates the same strict JSON documents as the app and CardEventNet package.  It is
intentionally independent from SQLAlchemy and from any analyzer or training implementation.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Literal, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)


class IntakeContractError(ValueError):
    """Raised when an intake document or its cross-document references are invalid."""


TASK_CARD_EVENT = "cardevent_event_detection"
TASK_TABLE_EVIDENCE = "table_evidence_analysis"
DataTask = Literal["cardevent_event_detection", "table_evidence_analysis"]
Disposition = Literal["selected", "deferred", "excluded"]
LifecycleState = Literal[
    "intake", "annotating", "review_required", "reviewed", "eligible", "excluded", "retired"
]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class IntakeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=False)


class SourceRecord(IntakeModel):
    schema_version: Literal["source-record/v1"]
    source_asset_id: Identifier
    sha256: Sha256
    byte_length: int = Field(gt=0)
    media_type: str = Field(min_length=1)
    original_filename: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
    acquisition_method: str = Field(min_length=1)
    source_permission: Literal[
        "training_only", "training_and_evaluation", "project_use", "unrestricted"
    ]
    allowed_uses: list[Literal["train", "validation", "test", "evaluation"]] = Field(min_length=1)
    session_id: Identifier | None
    recording_id: Identifier | None
    video_id: Identifier | None
    game_id: Identifier | None
    round_id: Identifier | None
    table_setup: Identifier | None
    content_type: (
        Literal[
            "real_game", "staged_trick_sequence", "staged_scenario", "synthetic_render", "other"
        ]
        | None
    )
    retention_state: Literal["active", "deletion_requested", "deleted", "retired"]
    notes: str | None

    @field_validator("allowed_uses")
    @classmethod
    def allowed_uses_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("allowed_uses must not contain duplicate values")
        return value

    @model_validator(mode="after")
    def staged_activity_has_no_game(self) -> SourceRecord:
        if self.content_type in {"staged_scenario", "staged_trick_sequence"} and (
            self.game_id is not None or self.round_id is not None
        ):
            raise ValueError("staged activity must not have a game_id or round_id")
        return self


class TaskEnrollment(IntakeModel):
    task_enrollment_id: Identifier
    task: DataTask
    disposition: Disposition
    lifecycle_state: LifecycleState
    operator: str = Field(min_length=1)
    created_at_utc: str
    reason: str | None

    @field_validator("created_at_utc")
    @classmethod
    def utc_timestamp(cls, value: str) -> str:
        if not value.endswith("Z"):
            raise ValueError("created_at_utc must use UTC with a Z suffix")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as error:
            raise ValueError("created_at_utc must be an ISO-8601 timestamp") from error
        if parsed.utcoffset() != timedelta(0):
            raise ValueError("created_at_utc must use UTC")
        return value

    @model_validator(mode="after")
    def disposition_matches_initial_state(self) -> TaskEnrollment:
        if self.disposition == "excluded":
            if self.lifecycle_state != "excluded" or self.reason is None:
                raise ValueError("excluded enrollment needs excluded state and reason")
        elif self.lifecycle_state != "intake" or self.reason is not None:
            raise ValueError(
                "selected or deferred enrollment must start in intake without a reason"
            )
        return self


class TaskEnrollmentDocument(IntakeModel):
    schema_version: Literal["task-enrollment/v1"]
    source_asset_id: Identifier
    enrollments: list[TaskEnrollment] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def contains_one_enrollment_per_task(self) -> TaskEnrollmentDocument:
        if {item.task for item in self.enrollments} != {TASK_CARD_EVENT, TASK_TABLE_EVIDENCE}:
            raise ValueError("task enrollment must contain both data tasks exactly once")
        if len({item.task_enrollment_id for item in self.enrollments}) != 2:
            raise ValueError("task enrollment IDs must be unique")
        return self


class BundleFile(IntakeModel):
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


class ProposalFile(BundleFile):
    proposal_generator_run_id: Identifier

    @model_validator(mode="after")
    def is_json(self) -> ProposalFile:
        if self.type != "application/json":
            raise ValueError("proposal file must be JSON")
        return self


class BundleFiles(IntakeModel):
    video: BundleFile
    source_record: BundleFile
    task_enrollment: BundleFile
    proposal_generator_runs: list[ProposalFile]

    @model_validator(mode="after")
    def file_types_are_explicit(self) -> BundleFiles:
        if self.video.type != "video/quicktime":
            raise ValueError("video file must be video/quicktime")
        if (
            self.source_record.type != "application/json"
            or self.task_enrollment.type != "application/json"
        ):
            raise ValueError("source record and task enrollment files must be JSON")
        if len({item.proposal_generator_run_id for item in self.proposal_generator_runs}) != len(
            self.proposal_generator_runs
        ):
            raise ValueError("proposal generator run IDs must be unique")
        return self


class RepositoryBundle(IntakeModel):
    schema_version: Literal["repository-bundle/v1"]
    source_asset_id: Identifier
    recording_id: Identifier
    video_id: Identifier
    session_id: Identifier
    state: Literal["complete"]
    source_sha256: Sha256
    files: BundleFiles

    @model_validator(mode="after")
    def video_matches_source_digest(self) -> RepositoryBundle:
        if self.files.video.sha256 != self.source_sha256:
            raise ValueError("video and source digest must match")
        return self


class Decoder(IntakeModel):
    algorithm: str = Field(min_length=1)
    threshold: float = Field(ge=0, le=1)
    peak_confirmation_s: float = Field(ge=0)
    minimum_event_gap_s: float = Field(ge=0)

    @field_validator("threshold", "peak_confirmation_s", "minimum_event_gap_s")
    @classmethod
    def finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("decoder values must be finite")
        return value


class Sampling(IntakeModel):
    strategy: str = Field(min_length=1)
    target_hz: float = Field(gt=0)

    @field_validator("target_hz")
    @classmethod
    def finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("target_hz must be finite")
        return value


class ExecutionEnvironment(IntakeModel):
    platform: Literal["ios", "macos", "linux"]
    device: str = Field(min_length=1)
    os_version: str = Field(min_length=1)
    runtime_version: str = Field(min_length=1)


class Probability(IntakeModel):
    time_s: float = Field(ge=0)
    probability: float = Field(ge=0, le=1)
    inference_ms: float = Field(ge=0)

    @field_validator("time_s", "probability", "inference_ms")
    @classmethod
    def finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("probability values must be finite")
        return value


class EventProposal(IntakeModel):
    time_s: float = Field(ge=0)
    emitted_at_s: float = Field(ge=0)
    probability: float = Field(ge=0, le=1)

    @field_validator("time_s", "emitted_at_s", "probability")
    @classmethod
    def finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("event proposal values must be finite")
        return value

    @model_validator(mode="after")
    def is_causal(self) -> EventProposal:
        if self.emitted_at_s < self.time_s:
            raise ValueError("emitted_at_s must be at or after time_s")
        return self


class ProposalGeneratorRun(IntakeModel):
    schema_version: Literal["proposal-generator-run/v1"]
    proposal_generator_run_id: Identifier
    purpose: Literal["proposal_only"]
    source_asset_id: Identifier
    recording_id: Identifier
    video_id: Identifier
    source_sha256: Sha256
    model_bundle_id: Identifier
    weights_sha256: Sha256
    decoder: Decoder
    preprocessing: str = Field(min_length=1)
    sampling: Sampling
    execution_environment: ExecutionEnvironment
    probabilities: list[Probability]
    event_proposals: list[EventProposal]
    output_sha256: Sha256

    @model_validator(mode="after")
    def timelines_are_ordered(self) -> ProposalGeneratorRun:
        if [item.time_s for item in self.probabilities] != sorted(
            item.time_s for item in self.probabilities
        ):
            raise ValueError("probability times must be ordered")
        if [item.time_s for item in self.event_proposals] != sorted(
            item.time_s for item in self.event_proposals
        ):
            raise ValueError("event proposal times must be ordered")
        return self


def _parse(raw: bytes, context: str) -> dict[str, object]:
    if not isinstance(raw, bytes):
        raise TypeError(f"{context} must be bytes")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IntakeContractError(f"{context} must be UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise IntakeContractError(f"{context} must be an object")
    return value


def _validated(model: type[BaseModel], raw: bytes, context: str) -> BaseModel:
    try:
        return model.model_validate(_parse(raw, context))
    except ValidationError as error:
        raise IntakeContractError(f"{context} failed validation") from error


def parse_source_record(raw: bytes) -> SourceRecord:
    return _validated(SourceRecord, raw, "source record")  # type: ignore[return-value]


def parse_task_enrollment(raw: bytes) -> TaskEnrollmentDocument:
    return _validated(TaskEnrollmentDocument, raw, "task enrollment")  # type: ignore[return-value]


def parse_repository_bundle(raw: bytes) -> RepositoryBundle:
    return _validated(RepositoryBundle, raw, "repository bundle")  # type: ignore[return-value]


def parse_proposal_generator_run(raw: bytes) -> ProposalGeneratorRun:
    return _validated(ProposalGeneratorRun, raw, "proposal generator run")  # type: ignore[return-value]


def validate_repository_bundle(
    manifest: bytes,
    source_record: bytes,
    task_enrollment: bytes,
    proposal_runs: Mapping[str, bytes],
) -> tuple[
    RepositoryBundle, SourceRecord, TaskEnrollmentDocument, tuple[ProposalGeneratorRun, ...]
]:
    """Validate one complete repository bundle and every referenced proposal run."""

    bundle = parse_repository_bundle(manifest)
    source = parse_source_record(source_record)
    enrollments = parse_task_enrollment(task_enrollment)
    runs = tuple(parse_proposal_generator_run(value) for value in proposal_runs.values())
    if source.source_asset_id != bundle.source_asset_id or source.sha256 != bundle.source_sha256:
        raise IntakeContractError("bundle and source record identity or digest differ")
    if (source.recording_id, source.video_id, source.session_id) != (
        bundle.recording_id,
        bundle.video_id,
        bundle.session_id,
    ):
        raise IntakeContractError("bundle and source record recording identity differs")
    if enrollments.source_asset_id != bundle.source_asset_id:
        raise IntakeContractError("task enrollment source_asset_id differs from bundle")
    expected = {item.proposal_generator_run_id for item in bundle.files.proposal_generator_runs}
    if expected != set(proposal_runs):
        raise IntakeContractError("proposal files and supplied runs differ")
    for run in runs:
        if (run.source_asset_id, run.recording_id, run.video_id, run.source_sha256) != (
            bundle.source_asset_id,
            bundle.recording_id,
            bundle.video_id,
            bundle.source_sha256,
        ):
            raise IntakeContractError("proposal generator run lineage differs from bundle")
    return bundle, source, enrollments, runs


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "TASK_CARD_EVENT",
    "TASK_TABLE_EVIDENCE",
    "IntakeContractError",
    "SourceRecord",
    "TaskEnrollment",
    "TaskEnrollmentDocument",
    "BundleFile",
    "ProposalFile",
    "BundleFiles",
    "RepositoryBundle",
    "ProposalGeneratorRun",
    "parse_source_record",
    "parse_task_enrollment",
    "parse_repository_bundle",
    "parse_proposal_generator_run",
    "validate_repository_bundle",
    "sha256_bytes",
]
