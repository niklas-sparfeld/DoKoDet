"""Read-only discovery and validation of repository intake bundles.

The strict M0 documents remain the canonical source contract.  This module is an operations
adapter: it reads those documents and member bytes, then returns inspection data.  It does not
write a central index, SQLite rows, or repaired manifests.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

TASKS = ("cardevent_event_detection", "table_evidence_analysis")
SELECTED_LIFECYCLE_STATES = ("intake", "annotating", "review_required")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


@dataclass(frozen=True, slots=True)
class TaskState:
    """One task's independent enrollment and lifecycle state."""

    source_asset_id: str
    task: str
    disposition: str
    lifecycle_state: str
    enrollment_id: str

    def to_mapping(self) -> dict[str, str]:
        return {
            "source_asset_id": self.source_asset_id,
            "task": self.task,
            "disposition": self.disposition,
            "lifecycle_state": self.lifecycle_state,
            "task_enrollment_id": self.enrollment_id,
        }


@dataclass(frozen=True, slots=True)
class BundleInspection:
    """Stable inspection result for one candidate bundle directory."""

    path: str
    state: str
    source_asset_id: str | None
    recording_id: str | None
    session_id: str | None
    source_sha256: str | None
    tasks: tuple[TaskState, ...]
    errors: tuple[str, ...]

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "path": self.path,
            "state": self.state,
            "source_asset_id": self.source_asset_id,
            "recording_id": self.recording_id,
            "session_id": self.session_id,
            "source_sha256": self.source_sha256,
            "tasks": [item.to_mapping() for item in self.tasks],
            "errors": list(self.errors),
        }
        return result


@dataclass(frozen=True, slots=True)
class ReviewWork:
    """Pending task work found from enrollment or a review-run state file."""

    source_asset_id: str
    task: str
    state: str
    resumable: bool
    run_path: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "source_asset_id": self.source_asset_id,
            "task": self.task,
            "state": self.state,
            "resumable": self.resumable,
            "review_run": self.run_path,
        }


@dataclass(frozen=True, slots=True)
class Failure:
    """A validation or permission failure reported by status and validate."""

    path: str
    kind: str
    message: str

    def to_mapping(self) -> dict[str, str]:
        return {"path": self.path, "kind": self.kind, "message": self.message}


@dataclass(frozen=True, slots=True)
class InspectionResult:
    """All deterministic read-only observations for one repository root."""

    bundles: tuple[BundleInspection, ...]
    pending_review: tuple[ReviewWork, ...]
    failures: tuple[Failure, ...]
    unassigned_eligible_groups: tuple[str, ...]
    stale_derived_artifacts: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.failures

    def to_mapping(self, *, repository_root: Path, bundle_root: Path) -> dict[str, Any]:
        return {
            "schema_version": "doko-data-status/v1",
            "repository_root": ".",
            "bundle_root": _relative_path(bundle_root, repository_root),
            "bundles": [item.to_mapping() for item in self.bundles],
            "pending_review": [item.to_mapping() for item in self.pending_review],
            "failures": [item.to_mapping() for item in self.failures],
            "unassigned_eligible_groups": list(self.unassigned_eligible_groups),
            "stale_derived_artifacts": list(self.stale_derived_artifacts),
            "valid": self.valid,
        }


class IntakeInspectionError(ValueError):
    """Raised only for programmer/configuration errors, not malformed user data."""


def discover_bundle_paths(root: str | Path) -> tuple[Path, ...]:
    """Discover candidate bundle directories in deterministic path order.

    A candidate is a directory with ``manifest.json`` or one of the known member locations.  This
    includes incomplete bundles so validation can report them instead of silently ignoring them.
    """

    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        return ()
    if root_path.is_file():
        return (root_path.parent,) if root_path.name == "manifest.json" else ()
    candidates: set[Path] = set()
    if _looks_like_bundle(root_path):
        candidates.add(root_path)
    try:
        entries = sorted(root_path.rglob("*"), key=lambda item: item.as_posix())
    except OSError:
        return ()
    for entry in entries:
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if _looks_like_bundle(entry):
            candidates.add(entry)
    return tuple(sorted(candidates, key=lambda item: _relative_path(item, root_path)))


def inspect_repository(
    repository_root: str | Path,
    *,
    bundle_root: str | Path | None = None,
    artifacts_root: str | Path | None = None,
) -> InspectionResult:
    """Inspect bundles, pending work, permissions, splits, and stale artifacts.

    The function opens files only.  It never creates directories, writes state, imports a model,
    opens media, connects to a service, or touches SQLite.
    """

    repo = Path(repository_root).expanduser().resolve()
    root = (
        repo / bundle_root
        if bundle_root is not None and not Path(bundle_root).is_absolute()
        else Path(bundle_root or repo / "data/intake/recordings")
    )
    root = root.expanduser().resolve()
    artifact_path = (
        repo / artifacts_root
        if artifacts_root is not None and not Path(artifacts_root).is_absolute()
        else Path(artifacts_root or repo / "data/operations")
    )
    artifact_path = artifact_path.expanduser().resolve()
    inspections: list[BundleInspection] = []
    for candidate in discover_bundle_paths(root):
        inspections.append(_inspect_bundle(candidate, repo))
    inspections.sort(key=lambda item: item.path)
    failures = [
        Failure(item.path, "validation", message) for item in inspections for message in item.errors
    ]
    for item in inspections:
        if item.state != "complete":
            continue
        if _bundle_permission_failure(item, repo):
            failures.append(
                Failure(
                    item.path, "permission", "source retention state does not permit processing"
                )
            )
    pending = _pending_review(inspections, artifact_path, repo)
    unassigned = _unassigned_groups(inspections, artifact_path)
    stale = _stale_artifacts(inspections, artifact_path, repo)
    failures.extend(Failure(path, "stale_artifact", "derived artifact is stale") for path in stale)
    return InspectionResult(
        bundles=tuple(inspections),
        pending_review=tuple(pending),
        failures=tuple(sorted(failures, key=lambda item: (item.path, item.kind, item.message))),
        unassigned_eligible_groups=tuple(unassigned),
        stale_derived_artifacts=tuple(stale),
    )


def _looks_like_bundle(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(
        (
            (path / "manifest.json").exists(),
            (path / "source-record.json").exists(),
            (path / "initial-task-enrollment.json").exists(),
            (path / "videos").is_dir(),
            (path / "predictions").is_dir(),
        )
    )


def _inspect_bundle(path: Path, repository_root: Path) -> BundleInspection:
    relative = _relative_path(path, repository_root)
    errors: list[str] = []
    manifest = _read_json(path / "manifest.json", errors, "manifest.json")
    source = _read_json(path / "source-record.json", errors, "source-record.json")
    enrollment = _read_json(
        path / "initial-task-enrollment.json", errors, "initial-task-enrollment.json"
    )
    source_id = _optional_identifier(source, "source_asset_id")
    recording_id = _optional_identifier(source, "recording_id")
    session_id = _optional_identifier(source, "session_id")
    source_digest = source.get("sha256") if isinstance(source, dict) else None
    if not isinstance(source_digest, str):
        source_digest = None
    tasks = _task_states(enrollment, source_id, errors)
    if manifest is None:
        errors.append("missing manifest.json")
        return BundleInspection(
            relative,
            "incomplete",
            source_id,
            recording_id,
            session_id,
            source_digest,
            tuple(tasks),
            tuple(sorted(set(errors))),
        )
    if not isinstance(manifest, dict):
        errors.append("manifest.json must contain an object")
        return BundleInspection(
            relative,
            "invalid",
            source_id,
            recording_id,
            session_id,
            source_digest,
            tuple(tasks),
            tuple(sorted(set(errors))),
        )
    manifest_state = manifest.get("state")
    if manifest_state != "complete":
        errors.append("manifest state is not complete")
    manifest_identity = {
        field: manifest.get(field)
        for field in ("source_asset_id", "recording_id", "video_id", "session_id")
    }
    if source_id is not None and manifest_identity["source_asset_id"] != source_id:
        errors.append("manifest and source record source_asset_id differ")
    if recording_id is not None and manifest_identity["recording_id"] != recording_id:
        errors.append("manifest and source record recording_id differ")
    if session_id is not None and manifest_identity["session_id"] != session_id:
        errors.append("manifest and source record session_id differ")
    _validate_manifest_shape(manifest, errors)
    files = manifest.get("files")
    descriptors = _manifest_descriptors(files, errors)
    for label, descriptor in descriptors:
        _verify_descriptor(path, label, descriptor, errors)
    if isinstance(manifest.get("source_sha256"), str):
        if source_digest is not None and manifest["source_sha256"] != source_digest:
            errors.append("manifest and source record source digest differ")
        source_digest = manifest["source_sha256"]
    if source is not None:
        _validate_source_shape(source, errors)
    if enrollment is not None:
        _validate_enrollment_shape(enrollment, source_id, errors)
    for label, descriptor in descriptors:
        if label.startswith("proposal_generator_runs["):
            proposal_path = _descriptor_path(path, descriptor)
            if proposal_path is not None and proposal_path.is_file():
                proposal = _read_json(proposal_path, errors, label)
                _validate_proposal_shape(proposal, manifest, label, errors)
    if source is not None and isinstance(source_digest, str):
        video_descriptor = _descriptor_value(files, "video")
        if isinstance(video_descriptor, dict):
            video_path = _descriptor_path(path, video_descriptor)
            if video_path is not None and video_path.is_file():
                video_digest = _sha256_file(video_path)
                if video_digest != source_digest:
                    errors.append("video bytes do not match source digest")
                if source.get("sha256") != video_digest:
                    errors.append("source record digest does not match video bytes")
                if source.get("byte_length") != video_path.stat().st_size:
                    errors.append("source record byte_length does not match video bytes")
    state = "invalid" if any(_is_invalid_error(message) for message in errors) else "complete"
    if errors and state == "complete":
        state = "incomplete"
    return BundleInspection(
        relative,
        state,
        source_id,
        recording_id,
        session_id,
        source_digest,
        tuple(sorted(tasks, key=lambda item: item.task)),
        tuple(sorted(set(errors))),
    )


def _is_invalid_error(message: str) -> bool:
    return not (
        message.startswith("missing ")
        or message.startswith("member file is missing")
        or message.startswith("manifest state")
        or message.startswith("video bytes")
        or message.startswith("source record digest")
        or message.startswith("source record byte_length")
    )


def _read_json(path: Path, errors: list[str], label: str) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append(f"missing {label}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        errors.append(f"{label} is not valid UTF-8 JSON")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must contain an object")
        return None
    return value


def _validate_manifest_shape(manifest: Mapping[str, Any], errors: list[str]) -> None:
    required = {
        "schema_version",
        "source_asset_id",
        "recording_id",
        "video_id",
        "session_id",
        "state",
        "source_sha256",
        "files",
    }
    _exact_fields(manifest, required, "manifest.json", errors)
    if manifest.get("schema_version") != "repository-bundle/v1":
        errors.append("manifest schema_version is unsupported")
    if manifest.get("state") not in {"complete", None}:
        errors.append("manifest state is invalid")
    for field in ("source_asset_id", "recording_id", "video_id", "session_id"):
        if not _valid_identifier(manifest.get(field)):
            errors.append(f"manifest {field} is invalid")
    if not _valid_digest(manifest.get("source_sha256")):
        errors.append("manifest source_sha256 is invalid")


def _manifest_descriptors(files: Any, errors: list[str]) -> list[tuple[str, Mapping[str, Any]]]:
    if not isinstance(files, dict):
        errors.append("manifest files must be an object")
        return []
    _exact_fields(
        files,
        {"video", "source_record", "task_enrollment", "proposal_generator_runs"},
        "manifest.files",
        errors,
    )
    result: list[tuple[str, Mapping[str, Any]]] = []
    for label in ("video", "source_record", "task_enrollment"):
        descriptor = files.get(label)
        if isinstance(descriptor, dict):
            result.append((label, descriptor))
        else:
            errors.append(f"manifest.files.{label} is missing or invalid")
    runs = files.get("proposal_generator_runs")
    if not isinstance(runs, list):
        errors.append("manifest.files.proposal_generator_runs must be a list")
    else:
        for index, descriptor in enumerate(runs):
            if isinstance(descriptor, dict):
                result.append((f"proposal_generator_runs[{index}]", descriptor))
            else:
                errors.append(f"manifest.files.proposal_generator_runs[{index}] is invalid")
    return result


def _verify_descriptor(
    bundle: Path, label: str, descriptor: Mapping[str, Any], errors: list[str]
) -> None:
    _exact_fields(
        descriptor,
        {"relative_path", "type", "byte_length", "sha256"}
        | (
            {"proposal_generator_run_id"} if label.startswith("proposal_generator_runs[") else set()
        ),
        f"manifest.files.{label}",
        errors,
    )
    relative = descriptor.get("relative_path")
    if not isinstance(relative, str) or not _safe_relative_path(relative):
        errors.append(f"manifest.files.{label}.relative_path is unsafe")
        return
    path = _descriptor_path(bundle, descriptor)
    if path is None or not path.is_file():
        errors.append(f"member file is missing: {relative}")
        return
    byte_length = descriptor.get("byte_length")
    digest = descriptor.get("sha256")
    if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length <= 0:
        errors.append(f"manifest.files.{label}.byte_length is invalid")
    if not _valid_digest(digest):
        errors.append(f"manifest.files.{label}.sha256 is invalid")
    if isinstance(byte_length, int) and path.stat().st_size != byte_length:
        errors.append(f"member file length differs: {relative}")
    if isinstance(digest, str) and _sha256_file(path) != digest:
        errors.append(f"member file digest differs: {relative}")
    expected_type = "video/quicktime" if label == "video" else "application/json"
    if descriptor.get("type") != expected_type:
        errors.append(f"manifest.files.{label}.type is invalid")
    if label == "video" and (not relative.startswith("videos/") or not relative.endswith(".mov")):
        errors.append("video descriptor must point to videos/*.mov")
    if label == "source_record" and relative != "source-record.json":
        errors.append("source record descriptor path is invalid")
    if label == "task_enrollment" and relative != "initial-task-enrollment.json":
        errors.append("task enrollment descriptor path is invalid")
    if label.startswith("proposal_generator_runs[") and (
        not relative.startswith("predictions/") or not relative.endswith(".json")
    ):
        errors.append("proposal descriptor must point to predictions/*.json")


def _validate_source_shape(source: Mapping[str, Any], errors: list[str]) -> None:
    required = {
        "schema_version",
        "source_asset_id",
        "sha256",
        "byte_length",
        "media_type",
        "original_filename",
        "acquisition_method",
        "source_permission",
        "allowed_uses",
        "session_id",
        "recording_id",
        "video_id",
        "game_id",
        "round_id",
        "table_setup",
        "content_type",
        "retention_state",
        "notes",
    }
    _exact_fields(source, required, "source-record.json", errors)
    if source.get("schema_version") != "source-record/v1":
        errors.append("source record schema_version is unsupported")
    for field in ("media_type", "original_filename", "acquisition_method"):
        if not isinstance(source.get(field), str) or not source.get(field):
            errors.append(f"source record {field} is invalid")
    if source.get("source_permission") not in {
        "training_only",
        "training_and_evaluation",
        "project_use",
        "unrestricted",
    }:
        errors.append("source record source_permission is invalid")
    for field in (
        "source_asset_id",
        "session_id",
        "recording_id",
        "video_id",
        "game_id",
        "round_id",
        "table_setup",
    ):
        value = source.get(field)
        if value is not None and not _valid_identifier(value):
            errors.append(f"source record {field} is invalid")
    if not _valid_digest(source.get("sha256")):
        errors.append("source record sha256 is invalid")
    if (
        not isinstance(source.get("byte_length"), int)
        or isinstance(source.get("byte_length"), bool)
        or source.get("byte_length", 0) <= 0
    ):
        errors.append("source record byte_length is invalid")
    if source.get("retention_state") not in {"active", "deletion_requested", "deleted", "retired"}:
        errors.append("source record retention_state is invalid")
    if source.get("content_type") not in {
        None,
        "real_game",
        "staged_trick_sequence",
        "staged_scenario",
        "synthetic_render",
        "other",
    }:
        errors.append("source record content_type is invalid")
    if source.get("notes") is not None and not isinstance(source.get("notes"), str):
        errors.append("source record notes is invalid")
    if (
        not isinstance(source.get("allowed_uses"), list)
        or not source.get("allowed_uses")
        or len(source["allowed_uses"]) != len(set(source["allowed_uses"]))
        or not set(source["allowed_uses"]) <= {"train", "validation", "test", "evaluation"}
    ):
        errors.append("source record allowed_uses is invalid")
    if source.get("content_type") in {"staged_scenario", "staged_trick_sequence"} and (
        source.get("game_id") is not None or source.get("round_id") is not None
    ):
        errors.append("staged source must not have game_id or round_id")


def _task_states(
    enrollment: Mapping[str, Any] | None, source_id: str | None, errors: list[str]
) -> list[TaskState]:
    if enrollment is None:
        return []
    _validate_enrollment_shape(enrollment, source_id, errors)
    result: list[TaskState] = []
    raw_items = enrollment.get("enrollments")
    if not isinstance(raw_items, list):
        return result
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        values = (
            item.get("task_enrollment_id"),
            item.get("task"),
            item.get("disposition"),
            item.get("lifecycle_state"),
        )
        if all(isinstance(value, str) for value in values):
            result.append(
                TaskState(
                    source_id or str(enrollment.get("source_asset_id", "")),
                    values[1],
                    values[2],
                    values[3],
                    values[0],
                )
            )
    return result


def _validate_enrollment_shape(
    enrollment: Mapping[str, Any], source_id: str | None, errors: list[str]
) -> None:
    _exact_fields(
        enrollment,
        {"schema_version", "source_asset_id", "enrollments"},
        "initial-task-enrollment.json",
        errors,
    )
    if enrollment.get("schema_version") != "task-enrollment/v1":
        errors.append("task enrollment schema_version is unsupported")
    if source_id is not None and enrollment.get("source_asset_id") != source_id:
        errors.append("task enrollment and source record source_asset_id differ")
    raw_items = enrollment.get("enrollments")
    if not isinstance(raw_items, list) or len(raw_items) != 2:
        errors.append("task enrollment must contain two enrollments")
        return
    seen: set[str] = set()
    seen_ids: set[str] = set()
    required = {
        "task_enrollment_id",
        "task",
        "disposition",
        "lifecycle_state",
        "operator",
        "created_at_utc",
        "reason",
    }
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            errors.append(f"task enrollment {index} is invalid")
            continue
        _exact_fields(item, required, f"task enrollment {index}", errors)
        task = item.get("task")
        enrollment_id = item.get("task_enrollment_id")
        if task not in TASKS:
            errors.append(f"task enrollment {index} task is invalid")
        elif task in seen:
            errors.append("task enrollment tasks must be unique")
        else:
            seen.add(task)
        if not _valid_identifier(enrollment_id):
            errors.append(f"task enrollment {index} ID is invalid")
        elif enrollment_id in seen_ids:
            errors.append("task enrollment IDs must be unique")
        else:
            seen_ids.add(enrollment_id)
        disposition = item.get("disposition")
        lifecycle = item.get("lifecycle_state")
        if disposition not in {"selected", "deferred", "excluded"}:
            errors.append(f"task enrollment {index} disposition is invalid")
        if lifecycle not in {
            "intake",
            "annotating",
            "review_required",
            "reviewed",
            "eligible",
            "excluded",
            "retired",
        }:
            errors.append(f"task enrollment {index} lifecycle_state is invalid")
        if disposition in {"selected", "deferred"} and (
            lifecycle != "intake" or item.get("reason") is not None
        ):
            errors.append(f"task enrollment {index} initial state is invalid")
        if disposition == "excluded" and (
            lifecycle != "excluded"
            or not isinstance(item.get("reason"), str)
            or not item.get("reason")
        ):
            errors.append(f"task enrollment {index} excluded state is invalid")
        if not isinstance(item.get("operator"), str) or not item.get("operator"):
            errors.append(f"task enrollment {index} operator is invalid")
        if not _valid_utc_timestamp(item.get("created_at_utc")):
            errors.append(f"task enrollment {index} created_at_utc is invalid")
        if item.get("reason") is not None and not isinstance(item.get("reason"), str):
            errors.append(f"task enrollment {index} reason is invalid")
    if seen != set(TASKS):
        errors.append("task enrollment must include both data tasks")


def _validate_proposal_shape(
    proposal: Mapping[str, Any] | None, manifest: Mapping[str, Any], label: str, errors: list[str]
) -> None:
    if proposal is None:
        return
    required = {
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
    _exact_fields(proposal, required, label, errors)
    if (
        proposal.get("schema_version") != "proposal-generator-run/v1"
        or proposal.get("purpose") != "proposal_only"
    ):
        errors.append(f"{label} is not proposal-only")
    for field in (
        "proposal_generator_run_id",
        "source_asset_id",
        "recording_id",
        "video_id",
        "model_bundle_id",
    ):
        if not _valid_identifier(proposal.get(field)):
            errors.append(f"{label} {field} is invalid")
    for field in ("source_sha256", "weights_sha256", "output_sha256"):
        if not _valid_digest(proposal.get(field)):
            errors.append(f"{label} {field} is invalid")
    for field in ("source_asset_id", "recording_id", "video_id"):
        manifest_field = field
        if proposal.get(field) != manifest.get(manifest_field):
            errors.append(f"{label} lineage differs from manifest")
    if proposal.get("source_sha256") != manifest.get("source_sha256"):
        errors.append(f"{label} source digest differs from manifest")
    decoder = proposal.get("decoder")
    if not isinstance(decoder, dict):
        errors.append(f"{label} decoder is invalid")
    else:
        _exact_fields(
            decoder,
            {"algorithm", "threshold", "peak_confirmation_s", "minimum_event_gap_s"},
            f"{label}.decoder",
            errors,
        )
        if not isinstance(decoder.get("algorithm"), str) or not decoder.get("algorithm"):
            errors.append(f"{label}.decoder.algorithm is invalid")
        _finite_number(decoder.get("threshold"), f"{label}.decoder.threshold", errors, maximum=1)
        _finite_number(
            decoder.get("peak_confirmation_s"),
            f"{label}.decoder.peak_confirmation_s",
            errors,
        )
        _finite_number(
            decoder.get("minimum_event_gap_s"),
            f"{label}.decoder.minimum_event_gap_s",
            errors,
        )
    sampling = proposal.get("sampling")
    if not isinstance(sampling, dict):
        errors.append(f"{label} sampling is invalid")
    else:
        _exact_fields(sampling, {"strategy", "target_hz"}, f"{label}.sampling", errors)
        if not isinstance(sampling.get("strategy"), str) or not sampling.get("strategy"):
            errors.append(f"{label}.sampling.strategy is invalid")
        _finite_number(
            sampling.get("target_hz"),
            f"{label}.sampling.target_hz",
            errors,
            minimum=0,
            strict_minimum=True,
        )
    environment = proposal.get("execution_environment")
    if not isinstance(environment, dict):
        errors.append(f"{label} execution_environment is invalid")
    else:
        _exact_fields(
            environment,
            {"platform", "device", "os_version", "runtime_version"},
            f"{label}.execution_environment",
            errors,
        )
        if environment.get("platform") not in {"ios", "macos", "linux"}:
            errors.append(f"{label} execution_environment.platform is invalid")
        for field in ("device", "os_version", "runtime_version"):
            if not isinstance(environment.get(field), str) or not environment.get(field):
                errors.append(f"{label} execution_environment.{field} is invalid")
    _validate_probability_items(proposal.get("probabilities"), label, errors)
    _validate_event_items(proposal.get("event_proposals"), label, errors)


def _exact_fields(
    value: Mapping[str, Any], required: set[str], label: str, errors: list[str]
) -> None:
    missing = required - set(value)
    unknown = set(value) - required
    if missing:
        errors.append(f"{label} missing fields: {', '.join(sorted(missing))}")
    if unknown:
        errors.append(f"{label} has unknown fields: {', '.join(sorted(unknown))}")


def _valid_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.utcoffset() == timedelta(0)


def _finite_number(
    value: Any,
    label: str,
    errors: list[str],
    *,
    minimum: float = 0,
    maximum: float | None = None,
    strict_minimum: bool = False,
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        errors.append(f"{label} is invalid")
        return
    if (strict_minimum and value <= minimum) or (not strict_minimum and value < minimum):
        errors.append(f"{label} is invalid")
    if maximum is not None and value > maximum:
        errors.append(f"{label} is invalid")


def _validate_probability_items(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{label}.probabilities is invalid")
        return
    previous = -1.0
    for index, item in enumerate(value):
        item_label = f"{label}.probabilities[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} is invalid")
            continue
        _exact_fields(item, {"time_s", "probability", "inference_ms"}, item_label, errors)
        _finite_number(item.get("time_s"), f"{item_label}.time_s", errors)
        _finite_number(item.get("probability"), f"{item_label}.probability", errors, maximum=1)
        _finite_number(item.get("inference_ms"), f"{item_label}.inference_ms", errors)
        time_s = item.get("time_s")
        if isinstance(time_s, (int, float)) and not isinstance(time_s, bool):
            if time_s < previous:
                errors.append(f"{label}.probabilities are not ordered")
            previous = float(time_s)


def _validate_event_items(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{label}.event_proposals is invalid")
        return
    previous = -1.0
    for index, item in enumerate(value):
        item_label = f"{label}.event_proposals[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} is invalid")
            continue
        _exact_fields(item, {"time_s", "emitted_at_s", "probability"}, item_label, errors)
        _finite_number(item.get("time_s"), f"{item_label}.time_s", errors)
        _finite_number(item.get("emitted_at_s"), f"{item_label}.emitted_at_s", errors)
        _finite_number(item.get("probability"), f"{item_label}.probability", errors, maximum=1)
        time_s = item.get("time_s")
        emitted_at_s = item.get("emitted_at_s")
        if isinstance(time_s, (int, float)) and not isinstance(time_s, bool):
            if time_s < previous:
                errors.append(f"{label}.event_proposals are not ordered")
            previous = float(time_s)
        if (
            isinstance(time_s, (int, float))
            and not isinstance(time_s, bool)
            and isinstance(emitted_at_s, (int, float))
            and not isinstance(emitted_at_s, bool)
            and emitted_at_s < time_s
        ):
            errors.append(f"{item_label}.emitted_at_s precedes time_s")


def _valid_identifier(value: Any) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def _optional_identifier(value: Mapping[str, Any] | None, field: str) -> str | None:
    candidate = value.get(field) if isinstance(value, Mapping) else None
    return candidate if _valid_identifier(candidate) else None


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return not (
        not value
        or "\\" in value
        or path.is_absolute()
        or ".." in path.parts
        or path.name in {"", "."}
    )


def _descriptor_value(files: Any, field: str) -> Any:
    return files.get(field) if isinstance(files, Mapping) else None


def _descriptor_path(bundle: Path, descriptor: Mapping[str, Any]) -> Path | None:
    relative = descriptor.get("relative_path")
    if not isinstance(relative, str) or not _safe_relative_path(relative):
        return None
    path = (bundle / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        path.relative_to(bundle.resolve())
    except ValueError:
        return None
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix() or "."
    except ValueError:
        return path.resolve().as_posix()


def _bundle_permission_failure(inspection: BundleInspection, repository_root: Path) -> bool:
    bundle = repository_root / inspection.path
    try:
        source = json.loads((bundle / "source-record.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return source.get("retention_state") != "active"


def _pending_review(
    inspections: Iterable[BundleInspection], artifacts_root: Path, repository_root: Path
) -> list[ReviewWork]:
    result: dict[tuple[str, str], ReviewWork] = {}
    for bundle in inspections:
        for task in bundle.tasks:
            if task.disposition == "selected" and task.lifecycle_state in SELECTED_LIFECYCLE_STATES:
                key = (task.source_asset_id, task.task)
                result[key] = ReviewWork(
                    task.source_asset_id,
                    task.task,
                    task.lifecycle_state,
                    task.lifecycle_state != "intake",
                )
    if artifacts_root.is_dir():
        for path in sorted(artifacts_root.rglob("*.json"), key=lambda item: item.as_posix()):
            payload = _read_optional_json(path)
            if not isinstance(payload, dict):
                continue
            if payload.get("schema_version") == "doko-review-run/v1":
                _add_review_run_work(result, payload, path, repository_root)
                continue
            task = payload.get("task")
            source_id = payload.get("source_asset_id")
            state = payload.get("state", payload.get("status"))
            if (
                task not in TASKS
                or not isinstance(source_id, str)
                or state not in {"new", "pending", "in_progress", "interrupted", "failed"}
            ):
                continue
            key = (source_id, task)
            result[key] = ReviewWork(
                source_id, task, str(state), True, _relative_path(path, repository_root)
            )
    return sorted(
        result.values(), key=lambda item: (item.source_asset_id, item.task, item.run_path or "")
    )


def _add_review_run_work(
    result: dict[tuple[str, str], ReviewWork],
    payload: Mapping[str, Any],
    path: Path,
    repository_root: Path,
) -> None:
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        return
    run_state = payload.get("state")
    if run_state == "complete":
        return
    for task_state in tasks:
        if not isinstance(task_state, Mapping):
            continue
        task = task_state.get("task")
        if task not in TASKS or task_state.get("state") == "complete":
            continue
        inputs = task_state.get("inputs")
        if not isinstance(inputs, list):
            continue
        source_ids = sorted(
            {
                item.get("source_asset_id")
                for item in inputs
                if isinstance(item, Mapping) and isinstance(item.get("source_asset_id"), str)
            }
        )
        for source_id in source_ids:
            result[(source_id, task)] = ReviewWork(
                source_id,
                task,
                str(task_state.get("state", run_state or "in_progress")),
                run_state != "complete",
                _relative_path(path, repository_root),
            )


def _unassigned_groups(inspections: Iterable[BundleInspection], artifacts_root: Path) -> list[str]:
    groups: set[str] = set()
    for bundle in inspections:
        for task in bundle.tasks:
            if task.disposition == "selected" and task.lifecycle_state == "eligible":
                groups.add(f"{task.task}:{bundle.session_id or bundle.source_asset_id}")
    if artifacts_root.is_dir():
        for path in sorted(
            (
                *artifacts_root.rglob("*.json"),
                *artifacts_root.rglob("*.yaml"),
                *artifacts_root.rglob("*.yml"),
            ),
            key=lambda item: item.as_posix(),
        ):
            payload = _read_split_document(path)
            if not isinstance(payload, Mapping):
                continue
            unassigned = payload.get("unassigned")
            if not isinstance(unassigned, list):
                continue
            task = payload.get("task") or payload.get("data_task") or "unknown"
            for entry in unassigned:
                if isinstance(entry, str) and entry:
                    groups.add(f"{task}:{entry}")
                elif isinstance(entry, Mapping):
                    value = (
                        entry.get("group_id")
                        or entry.get("source_lineage_group")
                        or entry.get("source_asset_id")
                        or entry.get("video_id")
                    )
                    if isinstance(value, str) and value:
                        groups.add(f"{task}:{value}")
    return sorted(groups)


def _stale_artifacts(
    inspections: Iterable[BundleInspection], artifacts_root: Path, repository_root: Path
) -> list[str]:
    current_by_source = {
        item.source_asset_id: item.source_sha256
        for item in inspections
        if item.state == "complete" and item.source_asset_id and item.source_sha256
    }
    stale: set[str] = set()
    if not artifacts_root.is_dir():
        return []
    for path in sorted(artifacts_root.rglob("*.json"), key=lambda item: item.as_posix()):
        payload = _read_optional_json(path)
        if not isinstance(payload, Mapping):
            continue
        if payload.get("stale") is True or payload.get("status") == "stale":
            stale.add(_relative_path(path, repository_root))
            continue
        source_id = payload.get("source_asset_id")
        expected = current_by_source.get(source_id) if isinstance(source_id, str) else None
        if isinstance(source_id, str) and source_id not in current_by_source:
            stale.add(_relative_path(path, repository_root))
            continue
        digest_values: list[str] = []
        for key in ("source_sha256", "source_digest", "input_sha256", "input_digest"):
            value = payload.get(key)
            if isinstance(value, str):
                digest_values.append(value)
        if expected and digest_values and any(value != expected for value in digest_values):
            stale.add(_relative_path(path, repository_root))
    return sorted(stale)


def _read_optional_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _read_split_document(path: Path) -> Any:
    if path.suffix == ".json":
        return _read_optional_json(path)
    # Split fixtures use a deliberately small YAML subset.  Parse only the partition lists.  A
    # malformed or richer YAML document is ignored here and remains the component validator's job.
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    values: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line and not line[0].isspace() and stripped.endswith(":"):
            current = stripped[:-1]
            values[current] = []
        elif current == "unassigned" and stripped.startswith("-"):
            value = stripped[1:].strip().strip("\"'")
            if value:
                values[current].append(value)
    return values if values else None


__all__ = [
    "BundleInspection",
    "Failure",
    "InspectionResult",
    "IntakeInspectionError",
    "ReviewWork",
    "TaskState",
    "discover_bundle_paths",
    "inspect_repository",
]
