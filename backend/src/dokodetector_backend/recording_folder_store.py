"""Concrete filesystem store for recording roots."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from dokodetector_backend.filesystem import contained_path
from dokodetector_backend.intake_contract import (
    parse_repository_bundle,
    parse_source_record,
    parse_task_enrollment,
    validate_repository_bundle,
)

RECORDING_SCHEMA = "recording/v1"
MAX_RECORDING_ROOT_BYTES = 1_000_000


class RecordingFolderError(RuntimeError):
    """A recording root could not be safely read or published."""


class RecordingVersionConflict(RecordingFolderError):
    """The recording root changed since the caller read it."""


@dataclass(frozen=True, slots=True)
class RecordingRoot:
    recording_id: str
    version: int
    source_asset_id: str
    video_id: str
    session_id: str
    received_at: datetime
    source: dict[str, Any]
    task_enrollment: dict[str, Any]
    media: dict[str, Any]
    media_facts: dict[str, Any] | None
    proposal_generator_runs: tuple[dict[str, Any], ...]
    head: dict[str, Any]


class RecordingFolderStore:
    """Store one authoritative recording.json and immutable source inputs per recording."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def recording_path(self, recording_id: str) -> Path:
        return contained_path(self.root, recording_id)

    def get(self, recording_id: str) -> RecordingRoot | None:
        try:
            path = self.recording_path(recording_id)
            if path.is_symlink() or not path.is_dir():
                return None
            raw_path = path / "recording.json"
            if raw_path.is_symlink():
                return None
            with raw_path.open("rb") as handle:
                raw = handle.read(MAX_RECORDING_ROOT_BYTES + 1)
            if len(raw) > MAX_RECORDING_ROOT_BYTES:
                raise ValueError("recording root exceeds its read limit")
            value = json.loads(raw)
            return _parse_root(value, recording_id)
        except (OSError, TypeError, ValueError, KeyError):
            return None

    def list(self) -> tuple[RecordingRoot, ...]:
        try:
            paths = sorted(self.root.iterdir(), key=lambda item: item.name)
        except FileNotFoundError:
            return ()
        result = []
        for path in paths:
            if path.name.startswith(".") or path.is_symlink() or not path.is_dir():
                continue
            item = self.get(path.name)
            if item is not None:
                result.append(item)
        return tuple(result)

    def publish_bundle(self, bundle_dir: Path, *, recording_id: str) -> RecordingRoot:
        """Validate a transport bundle and publish a complete folder atomically."""
        if bundle_dir.is_symlink() or not bundle_dir.is_dir():
            raise RecordingFolderError("transport bundle directory is unavailable")
        manifest_bytes = (bundle_dir / "manifest.json").read_bytes()
        source_bytes = (bundle_dir / "source-record.json").read_bytes()
        enrollment_bytes = (bundle_dir / "initial-task-enrollment.json").read_bytes()
        bundle = parse_repository_bundle(manifest_bytes)
        source = parse_source_record(source_bytes)
        enrollment = parse_task_enrollment(enrollment_bytes)
        proposal_bytes = {
            item.proposal_generator_run_id: (bundle_dir / item.relative_path).read_bytes()
            for item in bundle.files.proposal_generator_runs
        }
        validated, _, _, runs = validate_repository_bundle(
            manifest_bytes, source_bytes, enrollment_bytes, proposal_bytes
        )
        if validated.recording_id != recording_id:
            raise RecordingFolderError("bundle recording ID does not match destination")
        received = min(
            datetime.fromisoformat(item.created_at_utc.replace("Z", "+00:00"))
            for item in enrollment.enrollments
        ).astimezone(timezone.utc)
        media_rel = PurePosixPath("source") / source.original_filename
        source_media = bundle_dir / validated.files.video.relative_path
        if source_media.is_symlink() or not source_media.is_file():
            raise RecordingFolderError("source media is missing or unsafe")
        media_byte_length, media_sha256 = _file_identity(source_media)
        if media_byte_length != source.byte_length or media_sha256 != source.sha256:
            raise RecordingFolderError("source media differs from the validated source record")
        proposal_entries = []
        for run in runs:
            declaration = next(
                item
                for item in validated.files.proposal_generator_runs
                if item.proposal_generator_run_id == run.proposal_generator_run_id
            )
            proposal_entries.append(
                {
                    "proposal_generator_run_id": run.proposal_generator_run_id,
                    "relative_path": (
                        f"proposal-inputs/{declaration.proposal_generator_run_id}.json"
                    ),
                    "sha256": declaration.sha256,
                    "byte_length": declaration.byte_length,
                }
            )
        value = {
            "schema_version": RECORDING_SCHEMA,
            "version": 1,
            "recording_id": validated.recording_id,
            "source_asset_id": validated.source_asset_id,
            "video_id": validated.video_id,
            "session_id": validated.session_id,
            "received_at": received.isoformat(),
            "source": source.model_dump(mode="json"),
            "task_enrollment": enrollment.model_dump(mode="json"),
            "media": {
                "relative_path": media_rel.as_posix(),
                "sha256": source.sha256,
                "byte_length": source.byte_length,
                "media_type": source.media_type,
                "original_filename": source.original_filename,
            },
            "media_facts": None,
            "proposal_generator_runs": proposal_entries,
            "head": {},
        }
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.recording_path(recording_id)
        staging = Path(tempfile.mkdtemp(prefix=".recording-", dir=self.root))
        try:
            (staging / "source").mkdir()
            (staging / "proposal-inputs").mkdir()
            shutil.copyfile(source_media, staging / media_rel)
            for entry, declaration in zip(
                proposal_entries, validated.files.proposal_generator_runs, strict=True
            ):
                shutil.copyfile(
                    bundle_dir / declaration.relative_path,
                    staging / entry["relative_path"],
                )
            (staging / "recording.json").write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            for path in staging.rglob("*"):
                if path.is_file():
                    with path.open("rb") as handle:
                        os.fsync(handle.fileno())
            _fsync_directory(staging)
            if destination.exists() or destination.is_symlink():
                existing = self.get(recording_id)
                if (
                    existing is not None
                    and existing.source == source.model_dump(mode="json")
                    and existing.task_enrollment == enrollment.model_dump(mode="json")
                    and existing.media["sha256"] == source.sha256
                    and existing.proposal_generator_runs == tuple(proposal_entries)
                ):
                    return existing
                raise RecordingFolderError("recording ID already exists with different content")
            os.rename(staging, destination)
            _fsync_directory(self.root)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        stored = self.get(recording_id)
        if stored is None:
            raise RecordingFolderError("published recording root failed validation")
        return stored

    def replace_root(
        self, recording_id: str, value: dict[str, Any], *, expected_version: int
    ) -> RecordingRoot:
        """Atomically replace recording.json after a recording-local version check."""
        directory = self.recording_path(recording_id)
        lock_path = directory / ".recording.lock"
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            current = self.get(recording_id)
            if (
                isinstance(expected_version, bool)
                or not isinstance(expected_version, int)
                or current is None
                or current.version != expected_version
            ):
                raise RecordingVersionConflict("recording version does not match expected version")
            if not isinstance(value, dict):
                raise RecordingFolderError("recording root replacement must be an object")
            updated = dict(value)
            persisted = json.loads((directory / "recording.json").read_bytes())
            immutable_fields = set(persisted) - {"version", "head"}
            if any(updated.get(key) != persisted[key] for key in immutable_fields):
                raise RecordingFolderError("recording source facts are immutable")
            if set(updated) != set(persisted):
                raise RecordingFolderError("recording root fields cannot be added or removed")
            updated["version"] = expected_version + 1
            parsed = _parse_root(updated, recording_id)
            temporary = directory / ".recording.json.tmp"
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(updated, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, directory / "recording.json")
            _fsync_directory(directory)
            return parsed


def _parse_root(value: object, recording_id: str) -> RecordingRoot:
    if not isinstance(value, dict) or value.get("schema_version") != RECORDING_SCHEMA:
        raise ValueError("unsupported recording root")
    required = {
        "schema_version",
        "version",
        "recording_id",
        "source_asset_id",
        "video_id",
        "session_id",
        "received_at",
        "source",
        "task_enrollment",
        "media",
        "media_facts",
        "proposal_generator_runs",
        "head",
    }
    if set(value) != required or value["recording_id"] != recording_id:
        raise ValueError("recording root fields or identity are invalid")
    if (
        isinstance(value["version"], bool)
        or not isinstance(value["version"], int)
        or value["version"] < 1
    ):
        raise ValueError("recording version must be a positive integer")
    if not all(
        isinstance(value[key], str) and value[key]
        for key in ("source_asset_id", "video_id", "session_id")
    ):
        raise ValueError("recording identity fields are invalid")
    if not isinstance(value["source"], dict) or not isinstance(value["task_enrollment"], dict):
        raise ValueError("recording source and task enrollment must be objects")
    if not isinstance(value["media"], dict) or not isinstance(value["head"], dict):
        raise ValueError("recording media and head must be objects")
    if value["media_facts"] is not None and not isinstance(value["media_facts"], dict):
        raise ValueError("media facts must be an object or null")
    if not isinstance(value["proposal_generator_runs"], list):
        raise ValueError("proposal generator runs must be a list")
    source = value["source"]
    enrollment = value["task_enrollment"]
    source_model = parse_source_record(
        json.dumps(source, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    enrollment_model = parse_task_enrollment(
        json.dumps(enrollment, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    if (
        source_model.source_asset_id != value["source_asset_id"]
        or source_model.recording_id != recording_id
        or source_model.video_id != value["video_id"]
        or source_model.session_id != value["session_id"]
        or enrollment_model.source_asset_id != value["source_asset_id"]
    ):
        raise ValueError("recording intake facts do not match root identity")
    media = value["media"]
    relative = PurePosixPath(media.get("relative_path", ""))
    if (
        len(relative.parts) != 2
        or relative.parts[0] != "source"
        or relative.parts[1] != source.get("original_filename")
    ):
        raise ValueError("source media path is unsafe")
    if (
        media.get("sha256") != source.get("sha256")
        or media.get("byte_length") != source.get("byte_length")
        or media.get("media_type") != source.get("media_type")
    ):
        raise ValueError("recording media facts do not match source facts")
    received = datetime.fromisoformat(value["received_at"])
    return RecordingRoot(
        recording_id=recording_id,
        version=value["version"],
        source_asset_id=value["source_asset_id"],
        video_id=value["video_id"],
        session_id=value["session_id"],
        received_at=received,
        source=value["source"],
        task_enrollment=value["task_enrollment"],
        media=media,
        media_facts=value["media_facts"],
        proposal_generator_runs=tuple(value["proposal_generator_runs"]),
        head=value["head"],
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_length = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            byte_length += len(chunk)
            digest.update(chunk)
    return byte_length, digest.hexdigest()
