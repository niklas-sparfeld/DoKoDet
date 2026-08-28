"""Complete pending raw videos into repository recording bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .intake import inspect_repository
from .intake_contract import IntakeContractError, parse_pending_video

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
TASKS = {"cardevent_event_detection", "table_evidence_analysis"}
USES = {"train", "validation", "test", "evaluation"}
PERMISSIONS = {"training_only", "training_and_evaluation", "project_use", "unrestricted"}
CONTENT_TYPES = {
    "real_game",
    "staged_trick_sequence",
    "staged_scenario",
    "synthetic_render",
    "other",
}


class PendingVideoCompletionError(ValueError):
    """Raised when a pending video cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class PendingVideoCompletion:
    """Result of one successful pending-video promotion."""

    upload_id: str
    recording_id: str
    bundle_path: Path
    source_sha256: str
    state: str = "complete"

    def to_mapping(self, repository_root: Path) -> dict[str, str]:
        return {
            "upload_id": self.upload_id,
            "recording_id": self.recording_id,
            "bundle_path": _relative(self.bundle_path, repository_root),
            "source_sha256": self.source_sha256,
            "state": self.state,
        }


def complete_pending_video(
    repository_root: str | Path,
    upload_id: str,
    completion: Mapping[str, Any] | bytes | str | Path,
    *,
    pending_video_root: str | Path | None = None,
    intake_root: str | Path | None = None,
) -> PendingVideoCompletion:
    """Validate operator metadata and atomically promote one pending video.

    The pending video is copied into a private intake directory, validated, and then published by
    one directory rename.  The pending directory is removed only after that rename succeeds.
    """

    repository = Path(repository_root).expanduser().resolve()
    _identifier(upload_id, "upload_id")
    pending_root = _resolve(repository, pending_video_root, "data/incoming/videos")
    canonical_intake = _resolve(repository, intake_root, "data/intake/recordings")
    metadata = _load_completion(completion)
    pending_path = pending_root / upload_id
    receipt_path = pending_path / "manifest.json"
    if not receipt_path.is_file():
        existing = _idempotent_result(canonical_intake, metadata, upload_id)
        if existing is not None:
            return existing
        raise PendingVideoCompletionError(f"pending video {upload_id!r} was not found")

    try:
        pending = parse_pending_video(receipt_path.read_bytes())
    except (IntakeContractError, OSError) as error:
        raise PendingVideoCompletionError(
            f"pending video {upload_id!r} has an invalid receipt"
        ) from error
    if pending.upload_id != upload_id:
        raise PendingVideoCompletionError("pending receipt upload_id differs from its directory")
    video_path = pending_path / pending.original_filename
    if not video_path.is_file():
        raise PendingVideoCompletionError("pending video bytes are missing")
    if (
        video_path.stat().st_size != pending.byte_length
        or _sha256_file(video_path) != pending.sha256
    ):
        raise PendingVideoCompletionError("pending video bytes do not match the receipt")
    if pending.media_type != "video/quicktime" or not pending.original_filename.endswith(".mov"):
        raise PendingVideoCompletionError(
            "only video/quicktime .mov uploads can be promoted to recording intake"
        )

    values = _validate_completion(metadata)
    recording_id = values["recording_id"]
    target = canonical_intake / recording_id
    if target.exists():
        existing = _matching_existing_bundle(target, values, pending.sha256)
        if existing:
            shutil.rmtree(pending_path)
            return PendingVideoCompletion(upload_id, recording_id, target, pending.sha256)
        raise PendingVideoCompletionError(
            f"recording bundle {recording_id!r} already exists with different content"
        )

    canonical_intake.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".upload-", dir=canonical_intake))
    try:
        video_name = f"{values['video_id']}.mov"
        video_destination = staging / "videos" / video_name
        video_destination.parent.mkdir()
        shutil.copyfile(video_path, video_destination)
        _fsync_file(video_destination)

        source_record = _source_record(values, pending, video_name)
        enrollment = {
            "schema_version": "task-enrollment/v1",
            "source_asset_id": values["source_asset_id"],
            "enrollments": values["task_enrollments"],
        }
        source_bytes = _json_bytes(source_record)
        enrollment_bytes = _json_bytes(enrollment)
        (staging / "source-record.json").write_bytes(source_bytes)
        (staging / "initial-task-enrollment.json").write_bytes(enrollment_bytes)
        video_sha256 = _sha256_file(video_destination)
        if video_sha256 != pending.sha256:
            raise PendingVideoCompletionError("promoted video bytes do not match the receipt")
        manifest = _repository_manifest(
            values,
            source_bytes=source_bytes,
            enrollment_bytes=enrollment_bytes,
            video_name=video_name,
            video_byte_length=pending.byte_length,
            video_sha256=video_sha256,
        )
        (staging / "manifest.json").write_bytes(_json_bytes(manifest))

        inspection = inspect_repository(
            repository,
            bundle_root=staging,
            pending_video_root=staging / ".pending-validation",
            artifacts_root=staging / ".artifacts-validation",
        )
        if (
            not inspection.valid
            or not inspection.bundles
            or inspection.bundles[0].state != "complete"
        ):
            messages = [failure.message for failure in inspection.failures]
            raise PendingVideoCompletionError(
                "completed recording bundle failed validation"
                + (f": {'; '.join(messages)}" if messages else "")
            )
        staging.rename(target)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    shutil.rmtree(pending_path)
    return PendingVideoCompletion(upload_id, recording_id, target, pending.sha256)


def _load_completion(value: Mapping[str, Any] | bytes | str | Path) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, (str, Path)):
        try:
            raw = Path(value).read_bytes()
        except OSError as error:
            raise PendingVideoCompletionError(
                f"could not read completion metadata: {error}"
            ) from error
    elif isinstance(value, bytes):
        raw = value
    else:
        raise PendingVideoCompletionError("completion metadata must be a mapping or JSON file")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PendingVideoCompletionError("completion metadata must be UTF-8 JSON") from error
    if not isinstance(parsed, Mapping):
        raise PendingVideoCompletionError("completion metadata must be a JSON object")
    return parsed


def _validate_completion(metadata: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version",
        "source_asset_id",
        "recording_id",
        "video_id",
        "session_id",
        "acquisition_method",
        "source_permission",
        "allowed_uses",
        "game_id",
        "round_id",
        "table_setup",
        "content_type",
        "notes",
        "task_enrollments",
    }
    if set(metadata) != expected:
        raise PendingVideoCompletionError("completion metadata fields are not strict")
    if metadata["schema_version"] != "pending-video-completion/v1":
        raise PendingVideoCompletionError("completion metadata schema is unsupported")
    result: dict[str, Any] = {}
    for field in ("source_asset_id", "recording_id", "video_id", "session_id", "table_setup"):
        result[field] = _identifier(metadata[field], field)
    if FILENAME.fullmatch(result["video_id"] + ".mov") is None:
        raise PendingVideoCompletionError("video_id must produce a safe .mov filename")
    result["acquisition_method"] = _text(metadata["acquisition_method"], "acquisition_method")
    permission = metadata["source_permission"]
    if permission not in PERMISSIONS:
        raise PendingVideoCompletionError("source_permission is invalid")
    result["source_permission"] = permission
    uses = metadata["allowed_uses"]
    if (
        not isinstance(uses, list)
        or not uses
        or any(use not in USES for use in uses)
        or len(set(uses)) != len(uses)
    ):
        raise PendingVideoCompletionError("allowed_uses is invalid")
    result["allowed_uses"] = uses
    for field in ("game_id", "round_id"):
        result[field] = _nullable_identifier(metadata[field], field)
    content_type = metadata["content_type"]
    if content_type not in CONTENT_TYPES:
        raise PendingVideoCompletionError("content_type is invalid")
    if content_type == "real_game" and result["game_id"] is None:
        raise PendingVideoCompletionError("game content needs game_id")
    if content_type in {"staged_scenario", "staged_trick_sequence"} and (
        result["game_id"] is not None or result["round_id"] is not None
    ):
        raise PendingVideoCompletionError("staged activity must not have game or round IDs")
    result["content_type"] = content_type
    notes = metadata["notes"]
    if notes is not None and not isinstance(notes, str):
        raise PendingVideoCompletionError("notes must be text or null")
    result["notes"] = notes
    result["task_enrollments"] = _validate_task_enrollments(
        metadata["task_enrollments"], result["source_asset_id"]
    )
    return result


def _validate_task_enrollments(value: Any, source_asset_id: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 2:
        raise PendingVideoCompletionError("task_enrollments must contain two entries")
    result: list[dict[str, Any]] = []
    tasks: set[str] = set()
    enrollment_ids: set[str] = set()
    expected = {
        "task_enrollment_id",
        "task",
        "disposition",
        "lifecycle_state",
        "operator",
        "created_at_utc",
        "reason",
    }
    for item in value:
        if not isinstance(item, Mapping) or set(item) != expected:
            raise PendingVideoCompletionError("task enrollment fields are not strict")
        task = item["task"]
        if task not in TASKS or task in tasks:
            raise PendingVideoCompletionError("task enrollments must contain each data task once")
        tasks.add(task)
        enrollment_id = _identifier(item["task_enrollment_id"], "task_enrollment_id")
        if enrollment_id in enrollment_ids:
            raise PendingVideoCompletionError("task enrollment IDs must be unique")
        enrollment_ids.add(enrollment_id)
        if item["disposition"] not in {"selected", "deferred", "excluded"}:
            raise PendingVideoCompletionError("task enrollment disposition is invalid")
        if item["disposition"] in {"selected", "deferred"} and (
            item["lifecycle_state"] != "intake" or item["reason"] is not None
        ):
            raise PendingVideoCompletionError(
                "selected or deferred enrollment must start at intake"
            )
        if item["disposition"] == "excluded" and (
            item["lifecycle_state"] != "excluded"
            or not isinstance(item["reason"], str)
            or not item["reason"]
        ):
            raise PendingVideoCompletionError("excluded enrollment needs a reason")
        if item["lifecycle_state"] not in {
            "intake",
            "annotating",
            "review_required",
            "reviewed",
            "eligible",
            "excluded",
            "retired",
        }:
            raise PendingVideoCompletionError("task enrollment lifecycle_state is invalid")
        if not isinstance(item["operator"], str) or not item["operator"]:
            raise PendingVideoCompletionError("task enrollment operator is invalid")
        _timestamp(item["created_at_utc"])
        if item["reason"] is not None and not isinstance(item["reason"], str):
            raise PendingVideoCompletionError("task enrollment reason must be text or null")
        result.append(dict(item, task_enrollment_id=enrollment_id))
    if tasks != TASKS:
        raise PendingVideoCompletionError("task enrollments must contain both data tasks")
    return result


def _source_record(values: Mapping[str, Any], pending, video_name: str) -> dict[str, Any]:
    return {
        "schema_version": "source-record/v1",
        "source_asset_id": values["source_asset_id"],
        "sha256": pending.sha256,
        "byte_length": pending.byte_length,
        "media_type": "video/quicktime",
        "original_filename": video_name,
        "acquisition_method": values["acquisition_method"],
        "source_permission": values["source_permission"],
        "allowed_uses": values["allowed_uses"],
        "session_id": values["session_id"],
        "recording_id": values["recording_id"],
        "video_id": values["video_id"],
        "game_id": values["game_id"],
        "round_id": values["round_id"],
        "table_setup": values["table_setup"],
        "content_type": values["content_type"],
        "retention_state": "active",
        "notes": values["notes"],
    }


def _repository_manifest(
    values: Mapping[str, Any],
    *,
    source_bytes: bytes,
    enrollment_bytes: bytes,
    video_name: str,
    video_byte_length: int,
    video_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": "repository-bundle/v1",
        "source_asset_id": values["source_asset_id"],
        "recording_id": values["recording_id"],
        "video_id": values["video_id"],
        "session_id": values["session_id"],
        "state": "complete",
        "source_sha256": video_sha256,
        "files": {
            "video": {
                "relative_path": f"videos/{video_name}",
                "type": "video/quicktime",
                "byte_length": video_byte_length,
                "sha256": video_sha256,
            },
            "source_record": {
                "relative_path": "source-record.json",
                "type": "application/json",
                "byte_length": len(source_bytes),
                "sha256": _sha256_bytes(source_bytes),
            },
            "task_enrollment": {
                "relative_path": "initial-task-enrollment.json",
                "type": "application/json",
                "byte_length": len(enrollment_bytes),
                "sha256": _sha256_bytes(enrollment_bytes),
            },
            "proposal_generator_runs": [],
        },
    }


def _idempotent_result(
    intake_root: Path, metadata: Mapping[str, Any], upload_id: str
) -> PendingVideoCompletion | None:
    try:
        values = _validate_completion(metadata)
    except PendingVideoCompletionError:
        return None
    target = intake_root / values["recording_id"]
    if not target.is_dir():
        return None
    source = target / "source-record.json"
    if not source.is_file():
        return None
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if any(
        document.get(field) != values[field]
        for field in ("source_asset_id", "recording_id", "video_id", "session_id")
    ):
        return None
    if any(
        document.get(field) != values[field]
        for field in (
            "acquisition_method",
            "source_permission",
            "allowed_uses",
            "game_id",
            "round_id",
            "table_setup",
            "content_type",
            "notes",
        )
    ):
        return None
    video = target / "videos" / f"{values['video_id']}.mov"
    if not video.is_file():
        return None
    digest = _sha256_file(video)
    if document.get("sha256") != digest or document.get("byte_length") != video.stat().st_size:
        return None
    return PendingVideoCompletion(upload_id, values["recording_id"], target, digest)


def _matching_existing_bundle(target: Path, values: Mapping[str, Any], digest: str) -> bool:
    result = _idempotent_result(target.parent, values, "existing")
    return (
        result is not None
        and result.recording_id == values["recording_id"]
        and result.source_sha256 == digest
    )


def _resolve(root: Path, value: str | Path | None, default: str) -> Path:
    path = Path(value or default).expanduser()
    return path if path.is_absolute() else (root / path).resolve()


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise PendingVideoCompletionError(f"{field} must be a safe identifier")
    return value


def _nullable_identifier(value: Any, field: str) -> str | None:
    return None if value is None else _identifier(value, field)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PendingVideoCompletionError(f"{field} must be non-empty text")
    return value


def _timestamp(value: Any) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PendingVideoCompletionError("created_at_utc must use a UTC Z suffix")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise PendingVideoCompletionError("created_at_utc must be ISO-8601") from error
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise PendingVideoCompletionError("created_at_utc must use UTC")


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


__all__ = ["PendingVideoCompletion", "PendingVideoCompletionError", "complete_pending_video"]
