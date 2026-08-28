"""Strict contracts for the shared repository intake bundle.

The intake contract is deliberately separate from CardEventNet dataset membership.  A source
asset can be enrolled in either data task, both tasks, or neither task without changing its
immutable bytes.  Proposal generator output is lineage only; it is never a dataset enrollment.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Mapping

from .data_contract import SourceRecord


class IntakeContractError(ValueError):
    """Raised when a shared intake document or relationship is invalid."""


TASK_CARD_EVENT = "cardevent_event_detection"
TASK_TABLE_EVIDENCE = "table_evidence_analysis"
DATA_TASKS = frozenset({TASK_CARD_EVENT, TASK_TABLE_EVIDENCE})
DISPOSITIONS = frozenset({"selected", "deferred", "excluded"})
LIFECYCLE_STATES = frozenset(
    {"intake", "annotating", "review_required", "reviewed", "eligible", "excluded", "retired"}
)
REPOSITORY_BUNDLE_SCHEMA_VERSION = "repository-bundle/v1"
TASK_ENROLLMENT_SCHEMA_VERSION = "task-enrollment/v1"
PROPOSAL_GENERATOR_RUN_SCHEMA_VERSION = "proposal-generator-run/v1"
SOURCE_RECORD_SCHEMA_VERSION = "source-record/v1"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _object(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntakeContractError(f"{context} must be an object.")
    return value


def _strict(data: Mapping[str, Any], required: set[str], context: str) -> None:
    missing = required - set(data)
    unknown = set(data) - required
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise IntakeContractError(f"{context} has invalid fields ({'; '.join(details)}).")


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise IntakeContractError(f"{field} must be a non-empty string.")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _string(value, field)
    if _IDENTIFIER.fullmatch(result) is None:
        raise IntakeContractError(f"{field} must be a safe identifier.")
    return result


def _sha256(value: Any, field: str) -> str:
    result = _string(value, field)
    if _SHA256.fullmatch(result) is None:
        raise IntakeContractError(f"{field} must be a lower-case SHA-256 digest.")
    return result


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise IntakeContractError(f"{field} must be a positive integer.")
    return value


def _finite_number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IntakeContractError(f"{field} must be a finite number.")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise IntakeContractError(f"{field} must be a finite number at least {minimum}.")
    return result


def _timestamp(value: Any, field: str) -> str:
    result = _string(value, field)
    if not result.endswith("Z"):
        raise IntakeContractError(f"{field} must use UTC with a Z suffix.")
    try:
        parsed = datetime.fromisoformat(result[:-1] + "+00:00")
    except ValueError as error:
        raise IntakeContractError(f"{field} must be an ISO-8601 timestamp.") from error
    if parsed.utcoffset() != timedelta(0):
        raise IntakeContractError(f"{field} must use UTC.")
    return result


def _string_list(value: Any, field: str, allowed: frozenset[str] | None = None) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise IntakeContractError(f"{field} must be a list of non-empty strings.")
    result = tuple(value)
    if len(result) != len(set(result)):
        raise IntakeContractError(f"{field} must not contain duplicate values.")
    if allowed is not None and not set(result) <= allowed:
        raise IntakeContractError(f"{field} contains an unknown value.")
    return result


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True, slots=True)
class TaskEnrollment:
    task_enrollment_id: str
    task: str
    disposition: str
    lifecycle_state: str
    operator: str
    created_at_utc: str
    reason: str | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TaskEnrollment":
        data = _object(raw, "task enrollment")
        fields = {
            "task_enrollment_id",
            "task",
            "disposition",
            "lifecycle_state",
            "operator",
            "created_at_utc",
            "reason",
        }
        _strict(data, fields, "task enrollment")
        task = _string(data["task"], "task")
        disposition = _string(data["disposition"], "disposition")
        lifecycle_state = _string(data["lifecycle_state"], "lifecycle_state")
        if task not in DATA_TASKS:
            raise IntakeContractError(f"Unknown data task: {task}.")
        if disposition not in DISPOSITIONS:
            raise IntakeContractError(f"Unknown disposition: {disposition}.")
        if lifecycle_state not in LIFECYCLE_STATES:
            raise IntakeContractError(f"Unknown lifecycle_state: {lifecycle_state}.")
        reason = data["reason"]
        if reason is not None:
            reason = _string(reason, "reason")
        if disposition == "excluded" and reason is None:
            raise IntakeContractError("Excluded enrollment must record a reason.")
        if disposition != "excluded" and reason is not None:
            raise IntakeContractError("Only excluded enrollment can record a reason.")
        if disposition in {"selected", "deferred"} and lifecycle_state != "intake":
            raise IntakeContractError("Initial selected or deferred enrollment must be in intake.")
        if disposition == "excluded" and lifecycle_state != "excluded":
            raise IntakeContractError("Excluded enrollment must have excluded lifecycle state.")
        return cls(
            task_enrollment_id=_identifier(data["task_enrollment_id"], "task_enrollment_id"),
            task=task,
            disposition=disposition,
            lifecycle_state=lifecycle_state,
            operator=_string(data["operator"], "operator"),
            created_at_utc=_timestamp(data["created_at_utc"], "created_at_utc"),
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class TaskEnrollmentDocument:
    source_asset_id: str
    enrollments: tuple[TaskEnrollment, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TaskEnrollmentDocument":
        data = _object(raw, "task enrollment document")
        _strict(
            data, {"schema_version", "source_asset_id", "enrollments"}, "task enrollment document"
        )
        if data["schema_version"] != TASK_ENROLLMENT_SCHEMA_VERSION:
            raise IntakeContractError("Unsupported task enrollment schema.")
        raw_enrollments = data["enrollments"]
        if not isinstance(raw_enrollments, list) or len(raw_enrollments) != 2:
            raise IntakeContractError("A task enrollment document must contain two enrollments.")
        enrollments = tuple(TaskEnrollment.from_mapping(item) for item in raw_enrollments)
        tasks = {item.task for item in enrollments}
        if tasks != DATA_TASKS:
            raise IntakeContractError("A task enrollment document must enroll both data tasks.")
        if len({item.task_enrollment_id for item in enrollments}) != 2:
            raise IntakeContractError("Task enrollment IDs must be unique.")
        return cls(
            source_asset_id=_identifier(data["source_asset_id"], "source_asset_id"),
            enrollments=enrollments,
        )

    def for_task(self, task: str) -> TaskEnrollment:
        if task not in DATA_TASKS:
            raise IntakeContractError(f"Unknown data task: {task}.")
        return next(item for item in self.enrollments if item.task == task)


@dataclass(frozen=True, slots=True)
class BundleFile:
    relative_path: str
    type: str
    byte_length: int
    sha256: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> "BundleFile":
        data = _object(raw, context)
        _strict(data, {"relative_path", "type", "byte_length", "sha256"}, context)
        relative_path = _string(data["relative_path"], f"{context}.relative_path")
        path = PurePosixPath(relative_path)
        if path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
            raise IntakeContractError(f"{context}.relative_path must be a safe relative path.")
        return cls(
            relative_path=relative_path,
            type=_string(data["type"], f"{context}.type"),
            byte_length=_positive_int(data["byte_length"], f"{context}.byte_length"),
            sha256=_sha256(data["sha256"], f"{context}.sha256"),
        )

    def verify_bytes(self, value: bytes) -> None:
        if len(value) != self.byte_length or sha256_bytes(value) != self.sha256:
            raise IntakeContractError(f"Bundle file does not match {self.relative_path}.")


@dataclass(frozen=True, slots=True)
class ProposalFile(BundleFile):
    proposal_generator_run_id: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> "ProposalFile":
        data = _object(raw, context)
        _strict(
            data,
            {"proposal_generator_run_id", "relative_path", "type", "byte_length", "sha256"},
            context,
        )
        base = BundleFile.from_mapping(
            {key: data[key] for key in ("relative_path", "type", "byte_length", "sha256")}, context
        )
        if base.type != "application/json":
            raise IntakeContractError(f"{context}.type must be application/json.")
        return cls(
            relative_path=base.relative_path,
            type=base.type,
            byte_length=base.byte_length,
            sha256=base.sha256,
            proposal_generator_run_id=_identifier(
                data["proposal_generator_run_id"], f"{context}.proposal_generator_run_id"
            ),
        )


@dataclass(frozen=True, slots=True)
class BundleFiles:
    video: BundleFile
    source_record: BundleFile
    task_enrollment: BundleFile
    proposal_generator_runs: tuple[ProposalFile, ...]


@dataclass(frozen=True, slots=True)
class RepositoryBundle:
    source_asset_id: str
    recording_id: str
    video_id: str
    session_id: str
    source_sha256: str
    files: BundleFiles

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RepositoryBundle":
        data = _object(raw, "repository bundle")
        _strict(
            data,
            {
                "schema_version",
                "source_asset_id",
                "recording_id",
                "video_id",
                "session_id",
                "state",
                "source_sha256",
                "files",
            },
            "repository bundle",
        )
        if (
            data["schema_version"] != REPOSITORY_BUNDLE_SCHEMA_VERSION
            or data["state"] != "complete"
        ):
            raise IntakeContractError(
                "Repository bundle must be a complete repository-bundle/v1 document."
            )
        files = _object(data["files"], "repository bundle.files")
        _strict(
            files,
            {"video", "source_record", "task_enrollment", "proposal_generator_runs"},
            "repository bundle.files",
        )
        raw_runs = files["proposal_generator_runs"]
        if not isinstance(raw_runs, list):
            raise IntakeContractError("proposal_generator_runs must be a list.")
        proposal_runs = tuple(
            ProposalFile.from_mapping(item, f"proposal_generator_runs[{index}]")
            for index, item in enumerate(raw_runs)
        )
        run_ids = [item.proposal_generator_run_id for item in proposal_runs]
        if len(run_ids) != len(set(run_ids)):
            raise IntakeContractError("Proposal generator run IDs must be unique.")
        video = BundleFile.from_mapping(files["video"], "repository bundle.files.video")
        if video.type != "video/quicktime":
            raise IntakeContractError("repository bundle video must be video/quicktime.")
        source_record = BundleFile.from_mapping(
            files["source_record"], "repository bundle.files.source_record"
        )
        task_enrollment = BundleFile.from_mapping(
            files["task_enrollment"], "repository bundle.files.task_enrollment"
        )
        if source_record.type != "application/json" or task_enrollment.type != "application/json":
            raise IntakeContractError("source record and task enrollment files must be JSON.")
        if source_record.relative_path != "source-record.json":
            raise IntakeContractError("source record must be stored at source-record.json.")
        if task_enrollment.relative_path != "initial-task-enrollment.json":
            raise IntakeContractError(
                "task enrollment must be stored at initial-task-enrollment.json."
            )
        return cls(
            source_asset_id=_identifier(data["source_asset_id"], "source_asset_id"),
            recording_id=_identifier(data["recording_id"], "recording_id"),
            video_id=_identifier(data["video_id"], "video_id"),
            session_id=_identifier(data["session_id"], "session_id"),
            source_sha256=_sha256(data["source_sha256"], "source_sha256"),
            files=BundleFiles(video, source_record, task_enrollment, proposal_runs),
        )


@dataclass(frozen=True, slots=True)
class Decoder:
    algorithm: str
    threshold: float
    peak_confirmation_s: float
    minimum_event_gap_s: float


@dataclass(frozen=True, slots=True)
class Sampling:
    strategy: str
    target_hz: float


@dataclass(frozen=True, slots=True)
class ExecutionEnvironment:
    platform: str
    device: str
    os_version: str
    runtime_version: str


@dataclass(frozen=True, slots=True)
class Probability:
    time_s: float
    probability: float
    inference_ms: float


@dataclass(frozen=True, slots=True)
class EventProposal:
    time_s: float
    emitted_at_s: float
    probability: float


@dataclass(frozen=True, slots=True)
class ProposalGeneratorRun:
    proposal_generator_run_id: str
    purpose: str
    source_asset_id: str
    recording_id: str
    video_id: str
    source_sha256: str
    model_bundle_id: str
    weights_sha256: str
    decoder: Decoder
    preprocessing: str
    sampling: Sampling
    execution_environment: ExecutionEnvironment
    probabilities: tuple[Probability, ...]
    event_proposals: tuple[EventProposal, ...]
    output_sha256: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ProposalGeneratorRun":
        data = _object(raw, "proposal generator run")
        fields = {
            "schema_version",
            "proposal_generator_run_id",
            "purpose",
            "source_asset_id",
            "recording_id",
            "video_id",
            "source_sha256",
            "model_bundle_id",
            "weights_sha256",
            "decoder",
            "preprocessing",
            "sampling",
            "execution_environment",
            "probabilities",
            "event_proposals",
            "output_sha256",
        }
        _strict(data, fields, "proposal generator run")
        if (
            data["schema_version"] != PROPOSAL_GENERATOR_RUN_SCHEMA_VERSION
            or data["purpose"] != "proposal_only"
        ):
            raise IntakeContractError(
                "Proposal generator run must be proposal-generator-run/v1 and proposal_only."
            )
        decoder_data = _object(data["decoder"], "decoder")
        _strict(
            decoder_data,
            {"algorithm", "threshold", "peak_confirmation_s", "minimum_event_gap_s"},
            "decoder",
        )
        decoder = Decoder(
            _string(decoder_data["algorithm"], "decoder.algorithm"),
            _finite_number(decoder_data["threshold"], "decoder.threshold", minimum=0),
            _finite_number(
                decoder_data["peak_confirmation_s"], "decoder.peak_confirmation_s", minimum=0
            ),
            _finite_number(
                decoder_data["minimum_event_gap_s"], "decoder.minimum_event_gap_s", minimum=0
            ),
        )
        if decoder.threshold > 1:
            raise IntakeContractError("decoder.threshold must not exceed 1.")
        sampling_data = _object(data["sampling"], "sampling")
        _strict(sampling_data, {"strategy", "target_hz"}, "sampling")
        sampling = Sampling(
            _string(sampling_data["strategy"], "sampling.strategy"),
            _finite_number(sampling_data["target_hz"], "sampling.target_hz", minimum=0.000001),
        )
        environment_data = _object(data["execution_environment"], "execution_environment")
        _strict(
            environment_data,
            {"platform", "device", "os_version", "runtime_version"},
            "execution_environment",
        )
        platform = _string(environment_data["platform"], "execution_environment.platform")
        if platform not in {"ios", "macos", "linux"}:
            raise IntakeContractError("execution_environment.platform is unknown.")
        environment = ExecutionEnvironment(
            platform,
            _string(environment_data["device"], "execution_environment.device"),
            _string(environment_data["os_version"], "execution_environment.os_version"),
            _string(environment_data["runtime_version"], "execution_environment.runtime_version"),
        )

        def probabilities() -> tuple[Probability, ...]:
            raw_items = data["probabilities"]
            if not isinstance(raw_items, list):
                raise IntakeContractError("probabilities must be a list.")
            result = []
            for index, item in enumerate(raw_items):
                value = _object(item, f"probabilities[{index}]")
                _strict(value, {"time_s", "probability", "inference_ms"}, f"probabilities[{index}]")
                result.append(
                    Probability(
                        _finite_number(value["time_s"], "time_s", minimum=0),
                        _finite_number(value["probability"], "probability", minimum=0),
                        _finite_number(value["inference_ms"], "inference_ms", minimum=0),
                    )
                )
            if [item.time_s for item in result] != sorted(item.time_s for item in result):
                raise IntakeContractError("probability times must be ordered.")
            if any(item.probability > 1 for item in result):
                raise IntakeContractError("probability must not exceed 1.")
            return tuple(result)

        def proposals() -> tuple[EventProposal, ...]:
            raw_items = data["event_proposals"]
            if not isinstance(raw_items, list):
                raise IntakeContractError("event_proposals must be a list.")
            result = []
            for index, item in enumerate(raw_items):
                value = _object(item, f"event_proposals[{index}]")
                _strict(
                    value, {"time_s", "emitted_at_s", "probability"}, f"event_proposals[{index}]"
                )
                time_s = _finite_number(value["time_s"], "time_s", minimum=0)
                emitted = _finite_number(value["emitted_at_s"], "emitted_at_s", minimum=0)
                probability = _finite_number(value["probability"], "probability", minimum=0)
                if emitted < time_s or probability > 1:
                    raise IntakeContractError(
                        "event proposal must be causal and within probability bounds."
                    )
                result.append(EventProposal(time_s, emitted, probability))
            if [item.time_s for item in result] != sorted(item.time_s for item in result):
                raise IntakeContractError("event proposal times must be ordered.")
            return tuple(result)

        return cls(
            proposal_generator_run_id=_identifier(
                data["proposal_generator_run_id"], "proposal_generator_run_id"
            ),
            purpose="proposal_only",
            source_asset_id=_identifier(data["source_asset_id"], "source_asset_id"),
            recording_id=_identifier(data["recording_id"], "recording_id"),
            video_id=_identifier(data["video_id"], "video_id"),
            source_sha256=_sha256(data["source_sha256"], "source_sha256"),
            model_bundle_id=_identifier(data["model_bundle_id"], "model_bundle_id"),
            weights_sha256=_sha256(data["weights_sha256"], "weights_sha256"),
            decoder=decoder,
            preprocessing=_string(data["preprocessing"], "preprocessing"),
            sampling=sampling,
            execution_environment=environment,
            probabilities=probabilities(),
            event_proposals=proposals(),
            output_sha256=_sha256(data["output_sha256"], "output_sha256"),
        )


PENDING_VIDEO_SCHEMA_VERSION = "pending-video/v1"
EVIDENCE_PACKAGE_BUNDLE_SCHEMA_VERSION = "evidence-package-bundle/v1"
EVIDENCE_PACKAGE_RECORD_SCHEMA_VERSION = "evidence-package-record/v1"
EVIDENCE_PACKAGE_LINEAGE_SCHEMA_VERSION = "evidence-package-lineage/v1"


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
        data = _object(raw, "media_facts")
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
        return cls(
            container=_string(data["container"], "media_facts.container"),
            video_codec=_string(data["video_codec"], "media_facts.video_codec"),
            width=_positive_int(data["width"], "media_facts.width"),
            height=_positive_int(data["height"], "media_facts.height"),
            nominal_frame_rate=_finite_number(
                data["nominal_frame_rate"], "media_facts.nominal_frame_rate", minimum=0.000001
            ),
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
        data = _object(raw, "pending video")
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
        if data["schema_version"] != PENDING_VIDEO_SCHEMA_VERSION or data["state"] != "pending":
            raise IntakeContractError("Pending video must use pending-video/v1 and pending state.")
        filename = _string(data["original_filename"], "original_filename")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", filename) is None:
            raise IntakeContractError("original_filename must be a safe filename.")
        media_type = _string(data["media_type"], "media_type")
        if media_type not in {"video/quicktime", "video/mp4"}:
            raise IntakeContractError("media_type is not supported.")
        return cls(
            upload_id=_identifier(data["upload_id"], "upload_id"),
            original_filename=filename,
            byte_length=_positive_int(data["byte_length"], "byte_length"),
            sha256=_sha256(data["sha256"], "sha256"),
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
        base = BundleFile.from_mapping(raw, context)
        return cls(base.relative_path, base.type, base.byte_length, base.sha256)


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
        data = _object(raw, "evidence package files")
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
            EvidencePackageFile.from_mapping(item, f"files.frames[{index}]")
            for index, item in enumerate(raw_frames)
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
            values["evidence_manifest"],
            values["package_record"],
            values["task_enrollment"],
            values["lineage"],
            frames,
            video_snippet,
        )


@dataclass(frozen=True, slots=True)
class EvidencePackageBundle:
    package_id: str
    source_asset_id: str
    files: EvidencePackageFiles

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "EvidencePackageBundle":
        data = _object(raw, "evidence package bundle")
        _strict(
            data,
            {"schema_version", "package_id", "source_asset_id", "state", "files"},
            "evidence package bundle",
        )
        if (
            data["schema_version"] != EVIDENCE_PACKAGE_BUNDLE_SCHEMA_VERSION
            or data["state"] != "complete"
        ):
            raise IntakeContractError("Evidence package bundle must be complete v1.")
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
        data = _object(raw, "evidence package record")
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
        if data["schema_version"] != EVIDENCE_PACKAGE_RECORD_SCHEMA_VERSION:
            raise IntakeContractError("Evidence package record schema is unsupported.")
        uses = _string_list(
            data["allowed_uses"],
            "allowed_uses",
            frozenset({"train", "validation", "test", "evaluation"}),
        )
        permission = _string(data["source_permission"], "source_permission")
        if permission not in {
            "training_only",
            "training_and_evaluation",
            "project_use",
            "unrestricted",
        }:
            raise IntakeContractError("source_permission is invalid.")
        retention = _string(data["retention_state"], "retention_state")
        if retention not in {"active", "deletion_requested", "deleted", "retired"}:
            raise IntakeContractError("retention_state is invalid.")
        notes = data["notes"]
        if notes is not None:
            notes = _string(notes, "notes")
        return cls(
            package_id=_identifier(data["package_id"], "package_id"),
            source_asset_id=_identifier(data["source_asset_id"], "source_asset_id"),
            source_permission=permission,
            allowed_uses=uses,
            retention_state=retention,
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
        data = _object(raw, "evidence package lineage")
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
        if data["schema_version"] != EVIDENCE_PACKAGE_LINEAGE_SCHEMA_VERSION:
            raise IntakeContractError("Evidence package lineage schema is unsupported.")
        return cls(
            package_id=_identifier(data["package_id"], "package_id"),
            parent_source_asset_id=None
            if data["parent_source_asset_id"] is None
            else _identifier(data["parent_source_asset_id"], "parent_source_asset_id"),
            parent_recording_id=None
            if data["parent_recording_id"] is None
            else _identifier(data["parent_recording_id"], "parent_recording_id"),
            parent_video_id=None
            if data["parent_video_id"] is None
            else _identifier(data["parent_video_id"], "parent_video_id"),
            session_id=None
            if data["session_id"] is None
            else _identifier(data["session_id"], "session_id"),
        )


def parse_pending_video(raw: bytes) -> PendingVideo:
    return PendingVideo.from_mapping(parse_json_bytes(raw, "pending video"))


def parse_evidence_package_bundle(raw: bytes) -> EvidencePackageBundle:
    return EvidencePackageBundle.from_mapping(parse_json_bytes(raw, "evidence package bundle"))


def parse_evidence_package_record(raw: bytes) -> EvidencePackageRecord:
    return EvidencePackageRecord.from_mapping(parse_json_bytes(raw, "evidence package record"))


def parse_evidence_package_lineage(raw: bytes) -> EvidencePackageLineage:
    return EvidencePackageLineage.from_mapping(parse_json_bytes(raw, "evidence package lineage"))


def parse_json_bytes(raw: bytes, context: str) -> Mapping[str, Any]:
    if not isinstance(raw, bytes):
        raise TypeError(f"{context} must be bytes.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IntakeContractError(f"{context} must be UTF-8 JSON.") from error
    return _object(value, context)


def validate_repository_bundle(
    manifest: Mapping[str, Any],
    source_record: Mapping[str, Any],
    task_enrollment: Mapping[str, Any],
    proposal_runs: Mapping[str, Mapping[str, Any]],
) -> tuple[
    RepositoryBundle, SourceRecord, TaskEnrollmentDocument, tuple[ProposalGeneratorRun, ...]
]:
    """Validate a complete bundle's cross-document identities and lineage."""

    bundle = RepositoryBundle.from_mapping(manifest)
    try:
        source = SourceRecord.from_mapping(source_record)
    except ValueError as error:
        raise IntakeContractError("source record failed validation.") from error
    enrollments = TaskEnrollmentDocument.from_mapping(task_enrollment)
    runs = tuple(ProposalGeneratorRun.from_mapping(item) for item in proposal_runs.values())
    if source.source_asset_id != bundle.source_asset_id or source.sha256 != bundle.source_sha256:
        raise IntakeContractError("Bundle and source record identity or source digest differ.")
    if bundle.files.video.sha256 != bundle.source_sha256:
        raise IntakeContractError("Bundle video and source digest differ.")
    if (
        source.recording_id != bundle.recording_id
        or source.video_id != bundle.video_id
        or source.session_id != bundle.session_id
    ):
        raise IntakeContractError("Bundle and source record recording identity differs.")
    if enrollments.source_asset_id != bundle.source_asset_id:
        raise IntakeContractError("Task enrollment source_asset_id differs from bundle.")
    expected_runs = {
        item.proposal_generator_run_id for item in bundle.files.proposal_generator_runs
    }
    actual_runs = {item.proposal_generator_run_id for item in runs}
    if expected_runs != actual_runs:
        raise IntakeContractError("Bundle proposal files do not match proposal generator runs.")
    for run in runs:
        if (run.source_asset_id, run.recording_id, run.video_id, run.source_sha256) != (
            bundle.source_asset_id,
            bundle.recording_id,
            bundle.video_id,
            bundle.source_sha256,
        ):
            raise IntakeContractError("Proposal generator run lineage differs from bundle.")
    return bundle, source, enrollments, runs


__all__ = [
    "DATA_TASKS",
    "DISPOSITIONS",
    "LIFECYCLE_STATES",
    "TASK_CARD_EVENT",
    "TASK_TABLE_EVIDENCE",
    "REPOSITORY_BUNDLE_SCHEMA_VERSION",
    "TASK_ENROLLMENT_SCHEMA_VERSION",
    "PROPOSAL_GENERATOR_RUN_SCHEMA_VERSION",
    "SOURCE_RECORD_SCHEMA_VERSION",
    "IntakeContractError",
    "SourceRecord",
    "TaskEnrollment",
    "TaskEnrollmentDocument",
    "BundleFile",
    "ProposalFile",
    "RepositoryBundle",
    "ProposalGeneratorRun",
    "PENDING_VIDEO_SCHEMA_VERSION",
    "EVIDENCE_PACKAGE_BUNDLE_SCHEMA_VERSION",
    "EVIDENCE_PACKAGE_RECORD_SCHEMA_VERSION",
    "EVIDENCE_PACKAGE_LINEAGE_SCHEMA_VERSION",
    "PendingVideoMediaFacts",
    "PendingVideo",
    "EvidencePackageFile",
    "EvidencePackageFiles",
    "EvidencePackageBundle",
    "EvidencePackageRecord",
    "EvidencePackageLineage",
    "parse_json_bytes",
    "parse_pending_video",
    "parse_evidence_package_bundle",
    "parse_evidence_package_record",
    "parse_evidence_package_lineage",
    "sha256_bytes",
    "validate_repository_bundle",
]
