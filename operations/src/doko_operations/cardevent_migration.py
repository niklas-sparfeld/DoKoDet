"""Resumable migration of the legacy CardEventNet corpus into shared data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import yaml

from .cardevent_inventory import CardEventNetInventory, audit_cardeventnet
from .intake import inspect_repository
from .pipeline_data import (
    DataRevision,
    EventData,
    EventDataRevision,
    EventRecord,
    ImportProducer,
    RecordingVideoSource,
    canonical_data_revision_bytes,
    canonical_event_data_bytes,
    parse_data_revision_bytes,
    sha256_bytes,
)
from .pipeline_reference import (
    PipelineReferenceDraft,
    PipelineReferenceState,
    ReferenceDraftItem,
    canonical_reference_draft_bytes,
    canonical_reference_state_bytes,
    parse_reference_draft_bytes,
    parse_reference_state_bytes,
)

CARD_EVENTNET_MIGRATION_SCHEMA_VERSION = "cardeventnet-migration/v2"
MIGRATION_ID = "cardeventnet-shared-data-m1"
MIGRATION_TIMESTAMP = "2026-09-11T00:00:00.000Z"
DEFAULT_LEGACY_ROOT = Path("card_event_net/data")
DEFAULT_OPERATIONS_ROOT = Path("data/operations")
DEFAULT_INTAKE_ROOT = Path("data/intake/recordings")
ANNOTATION_SCHEMA = "cardevent-annotation/v2"
VIDEO_EXTENSIONS = frozenset({".mov", ".m4v", ".mp4"})
ALL_USES = ["train", "validation", "test", "evaluation"]

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_LFS_POINTER = b"version https://git-lfs.github.com/spec/v1\n"


class CardEventNetMigrationError(RuntimeError):
    """The legacy CardEventNet corpus could not be migrated safely."""


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Metadata needed to publish one current recording bundle."""

    video_id: str
    file_name: str
    session_id: str
    duration_s: float
    content_type: str
    table_setup: str
    source_permission: str
    recording_date: str | None
    notes: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MigrationItem:
    """The durable outcome for one source recording."""

    video_id: str
    recording_id: str
    source_video: str
    source_sha256: str
    source_byte_length: int
    annotation_sha256: str | None
    event_count: int
    bundle_action: str
    reference_action: str
    revision_id: str | None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "recording_id": self.recording_id,
            "source_video": self.source_video,
            "source_sha256": self.source_sha256,
            "source_byte_length": self.source_byte_length,
            "annotation_sha256": self.annotation_sha256,
            "event_count": self.event_count,
            "bundle_action": self.bundle_action,
            "reference_action": self.reference_action,
            "revision_id": self.revision_id,
        }


@dataclass(frozen=True, slots=True)
class CardEventNetMigrationResult:
    """Migration result and its parity receipt."""

    state: str
    receipt_path: str
    source_count: int
    annotation_count: int
    draft_reference_count: int
    archived_artifact_count: int
    items: tuple[MigrationItem, ...]
    parity: dict[str, Any]
    no_op: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": CARD_EVENTNET_MIGRATION_SCHEMA_VERSION,
            "migration_id": MIGRATION_ID,
            "state": self.state,
            "no_op": self.no_op,
            "receipt_path": self.receipt_path,
            "source_count": self.source_count,
            "annotation_count": self.annotation_count,
            "draft_reference_count": self.draft_reference_count,
            "archived_artifact_count": self.archived_artifact_count,
            "items": [item.to_mapping() for item in self.items],
            "parity": self.parity,
        }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise CardEventNetMigrationError(f"could not read source file {path}: {error}") from error
    return digest.hexdigest()


def _probe_video_duration_us(path: Path) -> int:
    """Return the canonical video duration with the backend's millisecond rounding."""

    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise CardEventNetMigrationError("ffprobe is required to inspect the canonical video")
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,duration",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CardEventNetMigrationError(
            f"could not probe canonical video duration: {path}"
        ) from error
    if result.returncode != 0:
        raise CardEventNetMigrationError(f"could not probe canonical video duration: {path}")
    payload: Any = None
    try:
        payload = json.loads(result.stdout)
        streams = payload["streams"]
        stream_duration = next(
            stream.get("duration")
            for stream in streams
            if isinstance(stream, Mapping)
            and stream.get("codec_type") == "video"
            and stream.get("duration")
        )
    except (KeyError, TypeError, StopIteration, json.JSONDecodeError):
        try:
            format_payload = payload["format"]
            stream_duration = format_payload["duration"]
        except (KeyError, TypeError) as fallback_error:
            raise CardEventNetMigrationError(
                f"canonical video duration is unavailable: {path}"
            ) from fallback_error
    try:
        seconds = float(stream_duration)
    except (TypeError, ValueError) as error:
        raise CardEventNetMigrationError(
            f"canonical video duration is invalid: {path}"
        ) from error
    if not math.isfinite(seconds) or seconds <= 0:
        raise CardEventNetMigrationError(f"canonical video duration is invalid: {path}")
    duration_ms = round(seconds * 1_000)
    if duration_ms <= 0:
        raise CardEventNetMigrationError(f"canonical video duration is invalid: {path}")
    return duration_ms * 1_000


def _safe_id(value: str, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise CardEventNetMigrationError(f"{field} is not a safe identifier: {value!r}")
    return value


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (root / path if not path.is_absolute() else path).resolve()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except ValueError:
        return path.as_posix()


def _atomic_write(path: Path, raw: bytes, *, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        if path.read_bytes() == raw:
            return
        raise CardEventNetMigrationError(f"destination already contains different bytes: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _copy_once(source: Path, destination: Path) -> None:
    if destination.exists():
        if not destination.is_file() or _sha256_path(destination) != _sha256_path(source):
            raise CardEventNetMigrationError(
                f"migration destination conflicts with source: {destination}"
            )
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.migration-tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        shutil.copyfile(source, temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def read_dataset_metadata(path: Path) -> dict[str, SourceMetadata]:
    """Read the complete legacy metadata manifest with YAML anchor support."""

    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise CardEventNetMigrationError(f"could not read dataset metadata {path}") from error
    if not isinstance(value, Mapping) or not isinstance(value.get("videos"), list):
        raise CardEventNetMigrationError(f"dataset metadata has no videos list: {path}")
    result: dict[str, SourceMetadata] = {}
    for index, raw in enumerate(value["videos"]):
        if not isinstance(raw, Mapping):
            raise CardEventNetMigrationError(f"metadata video {index} is not an object")
        video_id = raw.get("video_id")
        if not isinstance(video_id, str) or not video_id:
            raise CardEventNetMigrationError(f"metadata video {index} has no video_id")
        if video_id in result:
            raise CardEventNetMigrationError(f"metadata repeats video_id {video_id}")
        file_name = raw.get("file_name") or f"{video_id}.mov"
        session_id = raw.get("session_id") or f"capture-{video_id.lower()}"
        duration = raw.get("duration_s")
        content_type = raw.get("content_type") or "staged_trick_sequence"
        table_setup = raw.get("table_setup") or f"setup-{video_id.lower()}"
        permission = raw.get("source_permission") or "project_use"
        if not isinstance(file_name, str) or not isinstance(session_id, str):
            raise CardEventNetMigrationError(f"metadata identity is invalid for {video_id}")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise CardEventNetMigrationError(f"metadata duration_s is invalid for {video_id}")
        if content_type not in {
            "real_game",
            "staged_trick_sequence",
            "staged_scenario",
            "synthetic_render",
            "other",
        }:
            raise CardEventNetMigrationError(f"metadata content_type is invalid for {video_id}")
        if permission not in {
            "training_only",
            "training_and_evaluation",
            "project_use",
            "unrestricted",
        }:
            raise CardEventNetMigrationError(
                f"metadata source_permission is invalid for {video_id}"
            )
        result[video_id] = SourceMetadata(
            video_id=video_id,
            file_name=file_name,
            session_id=session_id,
            duration_s=float(duration),
            content_type=content_type,
            table_setup=str(table_setup),
            source_permission=permission,
            recording_date=raw.get("recording_date")
            if isinstance(raw.get("recording_date"), str)
            else None,
            notes=raw.get("notes") if isinstance(raw.get("notes"), str) else None,
            raw=json.loads(_canonical_json_bytes(dict(raw)).decode("utf-8")),
        )
    if not result:
        raise CardEventNetMigrationError(f"dataset metadata has no videos: {path}")
    return result


def read_split(path: Path, partitions: Sequence[str] = ("train", "val")) -> list[tuple[str, str]]:
    """Read simple legacy split lists for callers of the removed bounded importer."""

    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise CardEventNetMigrationError(f"could not read split {path}") from error
    if not isinstance(value, Mapping):
        raise CardEventNetMigrationError(f"split is not a mapping: {path}")
    allowed = {"val" if item == "validation" else item for item in partitions}
    result: list[tuple[str, str]] = []
    for raw_partition, raw_ids in value.items():
        if raw_partition not in allowed or not isinstance(raw_ids, list):
            continue
        partition = "validation" if raw_partition in {"val", "validation"} else raw_partition
        for video_id in raw_ids:
            if isinstance(video_id, str) and video_id:
                result.append((video_id, partition))
    if not result:
        raise CardEventNetMigrationError(
            f"no recordings found in {path} for partitions: {', '.join(partitions)}"
        )
    return result


def filter_selected_videos(
    selected: Sequence[tuple[str, str]], video_ids: Sequence[str] | None
) -> list[tuple[str, str]]:
    """Keep explicitly requested legacy split items for compatibility tooling."""

    if not video_ids:
        return list(selected)
    requested = tuple(_safe_id(item, "video_id") for item in video_ids)
    if len(set(requested)) != len(requested):
        raise CardEventNetMigrationError("a requested video_id occurs more than once")
    available = {video_id for video_id, _partition in selected}
    missing = sorted(set(requested) - available)
    if missing:
        raise CardEventNetMigrationError(
            "requested video IDs are not in the selected split partitions: " + ", ".join(missing)
        )
    return [item for item in selected if item[0] in set(requested)]


def _load_events(
    annotation_path: Path, *, video_name: str, duration_us: int
) -> tuple[tuple[EventRecord, ...], str]:
    try:
        value = json.loads(annotation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventNetMigrationError(f"could not read annotation {annotation_path}") from error
    if not isinstance(value, Mapping):
        raise CardEventNetMigrationError(f"annotation is not an object: {annotation_path}")
    schema = value.get("schema_version")
    if schema is None:
        schema = "cardevent-annotation/legacy-v1"
    if schema != ANNOTATION_SCHEMA and schema != "cardevent-annotation/legacy-v1":
        raise CardEventNetMigrationError(f"unsupported annotation schema: {annotation_path}")
    if Path(str(value.get("video", ""))).name != video_name:
        raise CardEventNetMigrationError(f"annotation video does not match {video_name}")
    raw_events = value.get("events")
    if not isinstance(raw_events, list):
        raise CardEventNetMigrationError(f"annotation events are not a list: {annotation_path}")
    events: list[EventRecord] = []
    previous = -1
    for index, raw_event in enumerate(raw_events):
        if not isinstance(raw_event, Mapping) or raw_event.get("type") != "card_state_changed":
            raise CardEventNetMigrationError(
                f"annotation event {index} is not {'card_state_changed'}: {annotation_path}"
            )
        time_s = raw_event.get("time_s")
        if isinstance(time_s, bool) or not isinstance(time_s, (int, float)):
            raise CardEventNetMigrationError(
                f"annotation event {index} has invalid time: {annotation_path}"
            )
        time_us = round(float(time_s) * 1_000_000)
        if time_us < previous or time_us > duration_us:
            raise CardEventNetMigrationError(
                f"annotation event {index} is outside the video: {annotation_path}"
            )
        previous = time_us
        events.append(
            EventRecord(
                event_id=f"cardeventnet-event-{Path(video_name).stem.lower()}-{index:03d}",
                event_type="card_state_changed",
                start_us=time_us,
                end_us=time_us,
            )
        )
    return tuple(events), str(schema)


def _allowed_uses(permission: str) -> list[str]:
    return ["train"] if permission == "training_only" else list(ALL_USES)


def _metadata_for(legacy: Path) -> dict[str, SourceMetadata]:
    return read_dataset_metadata(legacy / "dataset-manifest.v1.yaml")


def _recording_id(video_id: str) -> str:
    return _safe_id(f"cardeventnet-{video_id}", "recording_id")


def _source_ids(recording_id: str) -> tuple[str, str]:
    return f"source-{recording_id}", f"video-{recording_id}"


def _write_bundle(
    repository: Path,
    intake: Path,
    details: SourceMetadata,
    recording_id: str,
    source_path: Path,
    source_digest: str,
    source_length: int,
    operator: str,
) -> str:
    source_asset_id, video_asset_id = _source_ids(recording_id)
    video_path = f"videos/video-{recording_id}.mov"
    source_record = {
        "schema_version": "source-record/v1",
        "source_asset_id": source_asset_id,
        "sha256": source_digest,
        "byte_length": source_length,
        "media_type": "video/quicktime",
        "original_filename": details.file_name,
        "acquisition_method": "cardeventnet_import",
        "source_permission": details.source_permission,
        "allowed_uses": _allowed_uses(details.source_permission),
        "session_id": details.session_id,
        "recording_id": recording_id,
        "video_id": video_asset_id,
        "game_id": None,
        "round_id": None,
        "table_setup": details.table_setup,
        "content_type": details.content_type,
        "retention_state": "active",
        "notes": (
            f"Imported from the legacy CardEventNet corpus. Original metadata is retained in "
            f"data/operations/cardeventnet-imports/{recording_id}/metadata.json. "
            f"Imported by {operator}. {details.notes or ''}"
        ).strip(),
    }
    enrollment = {
        "schema_version": "task-enrollment/v1",
        "source_asset_id": source_asset_id,
        "enrollments": [
            {
                "task_enrollment_id": f"{recording_id}-cardevent_event_detection",
                "task": "cardevent_event_detection",
                "disposition": "selected",
                "lifecycle_state": "intake",
                "operator": operator,
                "created_at_utc": MIGRATION_TIMESTAMP,
                "reason": None,
            },
            {
                "task_enrollment_id": f"{recording_id}-table_evidence_analysis",
                "task": "table_evidence_analysis",
                "disposition": "selected",
                "lifecycle_state": "intake",
                "operator": operator,
                "created_at_utc": MIGRATION_TIMESTAMP,
                "reason": None,
            },
        ],
    }
    source_bytes = _json_bytes(source_record)
    enrollment_bytes = _json_bytes(enrollment)
    manifest = {
        "schema_version": "repository-bundle/v1",
        "source_asset_id": source_asset_id,
        "recording_id": recording_id,
        "video_id": video_asset_id,
        "session_id": details.session_id,
        "state": "complete",
        "source_sha256": source_digest,
        "files": {
            "video": {
                "relative_path": video_path,
                "type": "video/quicktime",
                "byte_length": source_length,
                "sha256": source_digest,
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
    destination = intake / recording_id
    if destination.exists():
        existing_manifest = _read_object(destination / "manifest.json")
        existing_digest = existing_manifest.get("source_sha256") if existing_manifest else None
        if existing_digest != source_digest:
            raise CardEventNetMigrationError(
                f"recording {recording_id} already exists with a different source digest"
            )
        existing_video = _find_video(destination, existing_manifest)
        if existing_video is None or _sha256_path(existing_video) != source_digest:
            raise CardEventNetMigrationError(
                f"recording {recording_id} has conflicting or unreadable source bytes"
            )
        inspection = inspect_repository(
            repository,
            bundle_root=destination,
            evidence_package_root=destination / ".no-evidence",
            pending_video_root=destination / ".no-pending",
            artifacts_root=destination / ".no-artifacts",
        )
        if inspection.bundles and inspection.bundles[0].state == "complete":
            return "reused"
        _replace_bundle(
            repository, destination, source_path, manifest, source_bytes, enrollment_bytes
        )
        return "repaired"

    intake.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".cardevent-migration-", dir=intake))
    try:
        video_destination = staging / video_path
        video_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, video_destination)
        if (
            _sha256_path(video_destination) != source_digest
            or video_destination.stat().st_size != source_length
        ):
            raise CardEventNetMigrationError(f"source changed while importing {details.video_id}")
        (staging / "source-record.json").write_bytes(source_bytes)
        (staging / "initial-task-enrollment.json").write_bytes(enrollment_bytes)
        (staging / "manifest.json").write_bytes(_json_bytes(manifest))
        _validate_staged_bundle(repository, staging)
        try:
            os.rename(staging, destination)
        except FileExistsError:
            return _write_bundle(
                repository,
                intake,
                details,
                recording_id,
                source_path,
                source_digest,
                source_length,
                operator,
            )
        staging = Path()
    finally:
        if staging != Path() and staging.exists():
            shutil.rmtree(staging)
    return "published"


def _replace_bundle(
    repository: Path,
    destination: Path,
    source_path: Path,
    manifest: Mapping[str, Any],
    source_bytes: bytes,
    enrollment_bytes: bytes,
) -> None:
    parent = destination.parent
    staging = Path(tempfile.mkdtemp(prefix=".cardevent-repair-", dir=parent))
    backup = parent / f".{destination.name}.migration-backup"
    try:
        video_relative = str(manifest["files"]["video"]["relative_path"])
        video_destination = staging / video_relative
        video_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, video_destination)
        (staging / "source-record.json").write_bytes(source_bytes)
        (staging / "initial-task-enrollment.json").write_bytes(enrollment_bytes)
        (staging / "manifest.json").write_bytes(_json_bytes(manifest))
        _validate_staged_bundle(repository, staging)
        if backup.exists():
            raise CardEventNetMigrationError(f"stale migration backup exists: {backup}")
        os.replace(destination, backup)
        try:
            os.replace(staging, destination)
        except BaseException:
            os.replace(backup, destination)
            raise
        staging = Path()
        shutil.rmtree(backup)
    finally:
        if staging != Path() and staging.exists():
            shutil.rmtree(staging)
        if backup.exists() and not destination.exists():
            os.replace(backup, destination)


def _validate_staged_bundle(repository: Path, staging: Path) -> None:
    inspection = inspect_repository(
        repository,
        bundle_root=staging,
        evidence_package_root=staging / ".no-evidence",
        pending_video_root=staging / ".no-pending",
        artifacts_root=staging / ".no-artifacts",
    )
    if not inspection.bundles or inspection.bundles[0].state != "complete":
        details = [error.message for error in inspection.failures]
        raise CardEventNetMigrationError(
            "current recording bundle failed validation"
            + (f": {'; '.join(details)}" if details else "")
        )


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _find_video(bundle: Path, manifest: Mapping[str, Any] | None) -> Path | None:
    if manifest is not None:
        descriptor = (
            manifest.get("files", {}).get("video")
            if isinstance(manifest.get("files"), Mapping)
            else None
        )
        relative = descriptor.get("relative_path") if isinstance(descriptor, Mapping) else None
        if isinstance(relative, str):
            candidate = bundle / PurePosixPath(relative)
            if candidate.is_file():
                return candidate
    candidates = (
        sorted(
            item
            for item in (bundle / "videos").glob("*")
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
        )
        if (bundle / "videos").is_dir()
        else []
    )
    return candidates[0] if len(candidates) == 1 else None


def _find_shared_recording(
    repository: Path, intake: Path, source_digest: str
) -> tuple[str, Path] | None:
    if not intake.is_dir():
        return None
    for candidate in sorted(
        item for item in intake.iterdir() if item.is_dir() and not item.name.startswith(".")
    ):
        manifest = _read_object(candidate / "manifest.json")
        if manifest is None or manifest.get("source_sha256") != source_digest:
            continue
        video = _find_video(candidate, manifest)
        if video is None or _sha256_path(video) != source_digest:
            continue
        inspection = inspect_repository(
            repository,
            bundle_root=candidate,
            evidence_package_root=candidate / ".no-evidence",
            pending_video_root=candidate / ".no-pending",
            artifacts_root=candidate / ".no-artifacts",
        )
        if inspection.bundles and inspection.bundles[0].state == "complete":
            return candidate.name, candidate
    return None


def _write_revision(
    repository: Path,
    operations: Path,
    recording_id: str,
    source_path: Path,
    source_digest: str,
    source_length: int,
    duration_us: int,
    annotation_bytes: bytes,
    annotation_schema: str,
    events: tuple[EventRecord, ...],
    video_relative_path: str,
    video_id: str,
) -> tuple[str, str]:
    video_source = RecordingVideoSource(
        recording_id=recording_id,
        relative_path=video_relative_path,
        video_sha256=source_digest,
        byte_length=source_length,
        duration_us=duration_us,
    )
    content = EventData(events=events)
    content_bytes = canonical_event_data_bytes(content)
    annotation_digest = _sha256_bytes(annotation_bytes)
    revision_id = _safe_id(f"cardeventnet-import-{video_id.lower()}", "revision_id")
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="events",
        content_schema="event-data/v1",
        recording_id=recording_id,
        source=video_source,
        content_sha256=sha256_bytes(content_bytes),
        input_revision_ids=(),
        origin="processor",
        producer=ImportProducer(
            run_id=f"cardeventnet-import-{video_id.lower()}",
            artifact_id=f"cardeventnet-annotation-{video_id.lower()}",
            artifact_sha256=annotation_digest,
            source_schema=annotation_schema,
        ),
        coverage={
            "kind": "annotation_evidence",
            "review_state": "unreviewed",
            "source_annotation_schema": annotation_schema,
            "source_annotation_sha256": annotation_digest,
            "event_count": len(events),
        },
        created_at=MIGRATION_TIMESTAMP,
    )
    manifest_bytes = canonical_data_revision_bytes(manifest)
    revision = EventDataRevision(manifest=manifest, content=content)
    destination = operations / "pipeline" / "revisions" / revision_id
    if destination.exists():
        try:
            existing_manifest = parse_data_revision_bytes(
                (destination / "manifest.json").read_bytes(),
                (destination / "content.json").read_bytes(),
            )
        except (OSError, ValueError) as error:
            raise CardEventNetMigrationError(
                f"existing event revision is invalid: {destination}"
            ) from error
        if (
            canonical_data_revision_bytes(existing_manifest) != manifest_bytes
            or (destination / "content.json").read_bytes() != content_bytes
        ):
            raise CardEventNetMigrationError(f"event revision conflicts: {revision_id}")
        return revision_id, "reused"
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{revision_id}-", dir=destination.parent))
    try:
        _atomic_write(staging / "content.json", content_bytes)
        _atomic_write(staging / "manifest.json", manifest_bytes)
        # Parsing the complete envelope validates source duration, event ordering, and digest.
        EventDataRevision.from_mapping(revision.to_mapping())
        os.replace(staging, destination)
        staging = Path()
    finally:
        if staging != Path() and staging.exists():
            shutil.rmtree(staging)
    del source_path
    return revision_id, "published"


def _reference_paths(operations: Path, recording_id: str) -> tuple[Path, Path]:
    root = operations / "pipeline-references" / recording_id / "events"
    return root / "state.json", root / "draft.json"


def _write_reference_draft(
    operations: Path,
    recording_id: str,
    revision_id: str | None,
    events: tuple[EventRecord, ...],
) -> str:
    state_path, draft_path = _reference_paths(operations, recording_id)
    existing: tuple[PipelineReferenceState, PipelineReferenceDraft] | None = None
    if state_path.exists() or draft_path.exists():
        if not state_path.is_file() or not draft_path.is_file():
            raise CardEventNetMigrationError(
                f"maintained event reference is incomplete: {recording_id}"
            )
        try:
            state = parse_reference_state_bytes(state_path.read_bytes())
            draft = parse_reference_draft_bytes(draft_path.read_bytes())
        except (OSError, ValueError) as error:
            raise CardEventNetMigrationError(
                f"maintained event reference is invalid: {recording_id}"
            ) from error
        if (
            state.recording_id != recording_id
            or draft.recording_id != recording_id
            or state.content_type != "events"
            or draft.content_type != "events"
            or state.draft_revision != draft.revision
            or state.source_revision_id != draft.source_revision_id
        ):
            raise CardEventNetMigrationError(
                f"maintained event reference disagrees: {recording_id}"
            )
        existing = state, draft
        if state.draft_state == "completed":
            return "completed_preserved"
        if revision_id is not None and draft.source_revision_id == revision_id:
            return "draft_reused"

    if revision_id is None:
        items: tuple[ReferenceDraftItem, ...] = ()
    else:
        raw_items = tuple(
            ReferenceDraftItem(
                item_id=event.event_id,
                base_item_id=None,
                review_state="pending",
                item=event.to_mapping(),
            )
            for event in events
        )
        if existing is None or not existing[1].items:
            items = raw_items
        else:
            previous = {item.item_id: item for item in existing[1].items}
            items = tuple(
                ReferenceDraftItem(
                    item_id=item.item_id,
                    base_item_id=previous[item.item_id].base_item_id
                    if item.item_id in previous
                    else None,
                    review_state=previous[item.item_id].review_state
                    if item.item_id in previous
                    else "affected",
                    item=item.item,
                )
                for item in raw_items
            )
    revision = 0 if existing is None else existing[1].revision + 1
    state = PipelineReferenceState(
        recording_id=recording_id,
        content_type="events",
        draft_revision=revision,
        draft_state="draft",
        source_revision_id=revision_id,
        selected_completed_revision_id=None
        if existing is None
        else existing[0].selected_completed_revision_id,
        updated_at=MIGRATION_TIMESTAMP,
    )
    draft = PipelineReferenceDraft(
        recording_id=recording_id,
        content_type="events",
        revision=revision,
        source_revision_id=revision_id,
        items=items,
        coverage=None,
        impact=(),
        updated_at=MIGRATION_TIMESTAMP,
    )
    _atomic_write(draft_path, canonical_reference_draft_bytes(draft), replace=True)
    _atomic_write(state_path, canonical_reference_state_bytes(state), replace=True)
    return "draft_created" if existing is None else "draft_rebased"


def _preserve_annotation(
    operations: Path,
    recording_id: str,
    annotation_path: Path | None,
    metadata: SourceMetadata,
) -> tuple[str | None, bytes | None]:
    destination = operations / "cardeventnet-imports" / recording_id
    _atomic_write(destination / "metadata.json", _json_bytes(metadata.raw))
    if annotation_path is None:
        return None, None
    annotation_bytes = annotation_path.read_bytes()
    annotation_destination = destination / "annotation.json"
    if annotation_destination.exists() and annotation_destination.read_bytes() != annotation_bytes:
        previous_import = _read_object(destination / "import.json")
        previous_source = (
            previous_import.get("source_annotation")
            if previous_import is not None
            else None
        )
        is_legacy_import = (
            previous_import is not None
            and previous_import.get("schema_version") == "cardeventnet-import/v1"
            and isinstance(previous_source, str)
            and Path(previous_source).expanduser().resolve() == annotation_path.resolve()
        )
        if not is_legacy_import:
            raise CardEventNetMigrationError(
                f"migration destination conflicts with source: {annotation_destination}"
            )
        previous_digest = _sha256_path(annotation_destination)
        _copy_once(
            annotation_destination,
            destination / f"annotation-legacy-{previous_digest}.json",
        )
        _atomic_write(annotation_destination, annotation_bytes, replace=True)
    else:
        _copy_once(annotation_path, annotation_destination)
    return _sha256_bytes(annotation_bytes), annotation_bytes


def _archive_legacy_artifacts(
    repository: Path,
    legacy: Path,
    operations: Path,
    report: CardEventNetInventory,
) -> int:
    archived = 0
    archive_root = operations / "cardeventnet-imports" / "legacy"
    for artifact in report.artifacts:
        if artifact.kind == "raw_video" or artifact.disposition == "obsolete":
            continue
        source = repository / PurePosixPath(artifact.path)
        if not source.is_file() or not source.is_relative_to(legacy):
            continue
        destination = archive_root / PurePosixPath(source.relative_to(legacy))
        _copy_once(source, destination)
        archived += 1
    return archived


def _read_receipt(path: Path) -> dict[str, Any] | None:
    value = _read_object(path)
    if value is None or value.get("schema_version") != CARD_EVENTNET_MIGRATION_SCHEMA_VERSION:
        return None
    return value


def _parity(
    repository: Path,
    intake: Path,
    report: CardEventNetInventory,
    items: Sequence[MigrationItem],
) -> dict[str, Any]:
    expected = {item.video_id: item for item in items}
    failures: list[str] = []
    for video_id, item in sorted(expected.items()):
        recording = next((entry for entry in report.recordings if entry.video_id == video_id), None)
        if recording is None or recording.source_sha256 != item.source_sha256:
            failures.append(f"source digest missing or changed for {video_id}")
            continue
        bundle = intake / item.recording_id
        manifest = _read_object(bundle / "manifest.json")
        video = _find_video(bundle, manifest)
        if manifest is None or video is None:
            failures.append(f"canonical bundle is incomplete for {video_id}")
            continue
        if (
            _sha256_path(video) != item.source_sha256
            or video.stat().st_size != item.source_byte_length
        ):
            failures.append(f"canonical source bytes differ for {video_id}")
    return {
        "source_count": len(items),
        "source_digests_match": not failures,
        "bundle_count": len([item for item in items if (intake / item.recording_id).is_dir()]),
        "failures": failures,
    }


def migrate_cardeventnet(
    repository_root: str | Path,
    *,
    legacy_root: str | Path | None = None,
    intake_root: str | Path | None = None,
    operations_root: str | Path | None = None,
    operator: str,
    video_ids: Sequence[str] | None = None,
) -> CardEventNetMigrationResult:
    """Migrate all legacy source recordings and retain a parity receipt.

    The operation is resumable.  Every source bundle, evidence package, revision, and draft is
    published independently.  A global receipt is written only after the parity check passes.
    """

    _safe_id(operator, "operator")
    repository = Path(repository_root).expanduser().resolve()
    if not repository.is_dir():
        raise CardEventNetMigrationError(f"repository root is not a directory: {repository}")
    legacy = _resolve(repository, legacy_root or DEFAULT_LEGACY_ROOT)
    intake = _resolve(repository, intake_root or DEFAULT_INTAKE_ROOT)
    operations = _resolve(repository, operations_root or DEFAULT_OPERATIONS_ROOT)
    report = audit_cardeventnet(
        repository,
        legacy_root=legacy,
        intake_root=intake,
        operations_root=operations,
    )
    if not report.legacy_root_exists:
        raise CardEventNetMigrationError(f"legacy root does not exist: {legacy}")
    metadata = _metadata_for(legacy)
    selected = set(video_ids or metadata)
    unknown = sorted(selected - set(metadata))
    if unknown:
        raise CardEventNetMigrationError(
            "requested video IDs are not in metadata: " + ", ".join(unknown)
        )
    recordings = [item for item in report.recordings if item.video_id in selected and item.raw_path]
    if len(recordings) != len(selected):
        missing = sorted(selected - {item.video_id for item in recordings})
        raise CardEventNetMigrationError("source recordings are missing: " + ", ".join(missing))
    blocking = [
        item
        for item in report.discrepancies
        if item.severity == "error"
        and item.kind
        not in {
            "annotation_invalid",
            "legacy_manifest_schema_unsupported",
            "shared_bundle_invalid",
            "unclassified_legacy_artifact",
        }
    ]
    if blocking:
        detail = "; ".join(f"{item.kind}: {item.video_id or item.path}" for item in blocking[:8])
        raise CardEventNetMigrationError(f"M0 inventory has blocking discrepancies: {detail}")
    for recording in recordings:
        if recording.raw_content_state == "lfs_pointer":
            raise CardEventNetMigrationError(
                f"source {recording.video_id} is a Git LFS pointer; hydrate it before migration"
            )
        if recording.source_sha256 is None or recording.source_byte_length is None:
            raise CardEventNetMigrationError(
                f"source facts are incomplete for {recording.video_id}"
            )
        if recording.video_id not in metadata:
            raise CardEventNetMigrationError(f"metadata is missing for {recording.video_id}")

    receipt_path = operations / "cardeventnet-imports" / "migration.json"
    existing_receipt = _read_receipt(receipt_path)
    if (
        existing_receipt is not None
        and existing_receipt.get("state") == "complete"
        and not video_ids
    ):
        receipt_items = tuple(
            MigrationItem(
                video_id=item["video_id"],
                recording_id=item["recording_id"],
                source_video=item["source_video"],
                source_sha256=item["source_sha256"],
                source_byte_length=item["source_byte_length"],
                annotation_sha256=item.get("annotation_sha256"),
                event_count=item["event_count"],
                bundle_action="reused",
                reference_action="reused",
                revision_id=item.get("revision_id"),
            )
            for item in existing_receipt.get("items", [])
            if isinstance(item, Mapping)
        )
        parity = _parity(repository, intake, report, receipt_items)
        if parity["source_digests_match"] and parity["source_count"] == len(receipt_items):
            return CardEventNetMigrationResult(
                state="complete",
                receipt_path=_relative(receipt_path, repository),
                source_count=len(receipt_items),
                annotation_count=sum(item.annotation_sha256 is not None for item in receipt_items),
                draft_reference_count=len(receipt_items),
                archived_artifact_count=int(existing_receipt.get("archived_artifact_count", 0)),
                items=receipt_items,
                parity=parity,
                no_op=True,
            )
        raise CardEventNetMigrationError("the completed migration receipt no longer passes parity")

    items: list[MigrationItem] = []
    for recording in sorted(recordings, key=lambda item: item.video_id):
        details = metadata[recording.video_id]
        source_path = repository / PurePosixPath(recording.raw_path or "")
        if _sha256_path(source_path) != recording.source_sha256:
            raise CardEventNetMigrationError(
                f"source changed since the M0 audit: {recording.video_id}"
            )
        recording_id = recording.shared_recording_id or _recording_id(recording.video_id)
        shared = _find_shared_recording(repository, intake, recording.source_sha256)
        if shared is not None:
            recording_id = shared[0]
            bundle_action = "reused"
        else:
            bundle_action = _write_bundle(
                repository,
                intake,
                details,
                recording_id,
                source_path,
                recording.source_sha256,
                recording.source_byte_length,
                operator,
            )
        annotation_path = (
            repository / PurePosixPath(recording.annotation_path)
            if recording.annotation_path
            else None
        )
        annotation_digest, annotation_bytes = _preserve_annotation(
            operations,
            recording_id,
            annotation_path,
            details,
        )
        events: tuple[EventRecord, ...] = ()
        annotation_schema = "missing"
        revision_id: str | None = None
        if (
            annotation_path is not None
            and annotation_bytes is not None
            and recording.annotation_valid
        ):
            events, annotation_schema = _load_events(
                annotation_path,
                video_name=details.file_name,
                duration_us=round(details.duration_s * 1_000_000),
            )
            video = _find_video(
                intake / recording_id, _read_object(intake / recording_id / "manifest.json")
            )
            if video is None:
                raise CardEventNetMigrationError(
                    f"canonical video is unavailable for {recording.video_id}"
                )
            metadata_duration_us = round(details.duration_s * 1_000_000)
            try:
                duration_us = _probe_video_duration_us(video)
            except CardEventNetMigrationError:
                # Keep metadata-only legacy fixtures migratable. Complete video bundles use the
                # probed duration, which is the source identity enforced by the backend.
                duration_us = metadata_duration_us
            video_relative = _relative(video, repository)
            revision_id, _revision_action = _write_revision(
                repository,
                operations,
                recording_id,
                source_path,
                recording.source_sha256,
                recording.source_byte_length,
                duration_us,
                annotation_bytes,
                annotation_schema,
                events,
                video_relative,
                recording.video_id,
            )
        reference_action = _write_reference_draft(operations, recording_id, revision_id, events)
        item = MigrationItem(
            video_id=recording.video_id,
            recording_id=recording_id,
            source_video=details.file_name,
            source_sha256=recording.source_sha256,
            source_byte_length=recording.source_byte_length,
            annotation_sha256=annotation_digest,
            event_count=len(events),
            bundle_action=bundle_action,
            reference_action=reference_action,
            revision_id=revision_id,
        )
        _atomic_write(
            operations / "cardeventnet-imports" / recording_id / "import.json",
            _json_bytes(
                {
                    "schema_version": "cardeventnet-import/v2",
                    "migration_id": MIGRATION_ID,
                    "recording_id": recording_id,
                    "video_id": recording.video_id,
                    "source_video": details.file_name,
                    "source_sha256": recording.source_sha256,
                    "source_byte_length": recording.source_byte_length,
                    "annotation_sha256": annotation_digest,
                    "events_imported": len(events),
                    "review_state": "unreviewed",
                    "revision_id": revision_id,
                    "reference_action": reference_action,
                }
            ),
            replace=True,
        )
        items.append(item)

    archived_count = _archive_legacy_artifacts(repository, legacy, operations, report)
    parity = _parity(repository, intake, report, items)
    if not parity["source_digests_match"] or parity["source_count"] != len(items):
        raise CardEventNetMigrationError(f"migration parity failed: {parity['failures']}")
    receipt = {
        "schema_version": CARD_EVENTNET_MIGRATION_SCHEMA_VERSION,
        "migration_id": MIGRATION_ID,
        "state": "complete",
        "operator": operator,
        "created_at_utc": MIGRATION_TIMESTAMP,
        "legacy_root": _relative(legacy, repository),
        "intake_root": _relative(intake, repository),
        "operations_root": _relative(operations, repository),
        "source_count": len(items),
        "annotation_count": sum(item.annotation_sha256 is not None for item in items),
        "draft_reference_count": len(items),
        "archived_artifact_count": archived_count,
        "items": [item.to_mapping() for item in items],
        "parity": parity,
        "legacy_retirement": {
            "state": "pending_explicit_operator_action",
            "command": "doko data cardevent retire-legacy --confirm",
        },
    }
    receipt["receipt_sha256"] = _sha256_bytes(_canonical_json_bytes(receipt))
    _atomic_write(receipt_path, _json_bytes(receipt))
    return CardEventNetMigrationResult(
        state="complete",
        receipt_path=_relative(receipt_path, repository),
        source_count=len(items),
        annotation_count=sum(item.annotation_sha256 is not None for item in items),
        draft_reference_count=len(items),
        archived_artifact_count=archived_count,
        items=tuple(items),
        parity=parity,
    )


def render_cardevent_migration_human(result: CardEventNetMigrationResult) -> str:
    """Render a concise migration handoff."""

    lines = [
        "CardEventNet shared-data migration",
        f"state: {result.state}{' (no-op)' if result.no_op else ''}",
        f"source recordings: {result.source_count}",
        f"annotation evidence: {result.annotation_count}",
        f"draft references: {result.draft_reference_count}",
        f"archived legacy artifacts: {result.archived_artifact_count}",
        f"receipt: {result.receipt_path}",
        "parity: passed",
        "review: imported annotations remain unreviewed draft evidence",
    ]
    return "\n".join(lines) + "\n"


def _default_repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=_default_repository_root())
    parser.add_argument("--legacy-root", type=Path, default=None)
    parser.add_argument("--intake-root", type=Path, default=None)
    parser.add_argument("--operations-root", type=Path, default=None)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--video-id", action="append", dest="video_ids", default=None)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args(argv)
    result = migrate_cardeventnet(
        args.repository_root,
        legacy_root=args.legacy_root,
        intake_root=args.intake_root,
        operations_root=args.operations_root,
        operator=args.operator,
        video_ids=args.video_ids,
    )
    if args.format == "json":
        print(json.dumps(result.to_mapping(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_cardevent_migration_human(result), end="")
    return 0


__all__ = [
    "CardEventNetMigrationError",
    "CardEventNetMigrationResult",
    "MigrationItem",
    "SourceMetadata",
    "filter_selected_videos",
    "main",
    "migrate_cardeventnet",
    "read_dataset_metadata",
    "read_split",
    "render_cardevent_migration_human",
]


if __name__ == "__main__":
    raise SystemExit(main())
