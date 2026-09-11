"""Import a bounded CardEventNet dataset slice into the local Doko pipeline."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from doko_operations.pipeline_data import (
    CARD_STATE_CHANGED_EVENT_TYPE,
    DataRevision,
    EventData,
    EventDataRevision,
    EventRecord,
    HumanProducer,
    RecordingVideoSource,
    canonical_event_data_bytes,
    sha256_bytes,
)

from dokodetector_backend.config import Settings
from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.pipeline_reference_service import PipelineReferenceService
from dokodetector_backend.pipeline_reference_store import PipelineReferenceStore
from dokodetector_backend.pipeline_store import (
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    PipelineSelectionStore,
    ProcessorRunStore,
)
from dokodetector_backend.recording_bundle_store import RecordingBundleStore
from dokodetector_backend.repository_bundle_storage import (
    RepositoryBundleStorage,
    StoredRepositoryFile,
)

IMPORT_OPERATOR = "cardeventnet-import"
IMPORT_TIMESTAMP = "2026-09-06T00:00:00.000Z"
DEFAULT_PARTITIONS = ("train", "val")
DEFAULT_SPLIT = "default.yaml"
ANNOTATION_SCHEMA = "cardevent-annotation/v2"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class CardEventNetMigrationError(RuntimeError):
    """The CardEventNet import could not be completed safely."""


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    video_id: str
    file_name: str
    session_id: str
    duration_s: float
    content_type: str
    table_setup: str
    source_permission: str
    recording_date: str | None
    notes: str | None


@dataclass(frozen=True, slots=True)
class MigrationResult:
    recording_id: str
    source_video: str
    split: str
    event_count: int
    video_bytes: int
    annotation_sha256: str
    published: bool


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise CardEventNetMigrationError(f"{field} is not a safe identifier: {value!r}")
    return value


def _yaml_scalar(block: str, key: str) -> str | None:
    match = re.search(rf"^\s+{re.escape(key)}:\s*(.*?)\s*$", block, re.MULTILINE)
    if match is None:
        return None
    value = match.group(1).strip()
    if value in {"null", "~"}:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_dataset_metadata(path: Path) -> dict[str, SourceMetadata]:
    """Read the small scalar subset needed from the CardEventNet YAML manifest.

    The source project uses YAML anchors to share defaults.  The importer supplies the known
    defaults and reads per-video overrides, so it does not add a YAML runtime dependency to the
    backend.
    """

    text = path.read_text(encoding="utf-8")
    result: dict[str, SourceMetadata] = {}
    for block in re.split(r"\n(?=\s+-\s)", text):
        video_id = _yaml_scalar(block, "video_id")
        if video_id is None:
            continue
        file_name = _yaml_scalar(block, "file_name") or f"{video_id}.mov"
        session_id = _yaml_scalar(block, "session_id") or f"capture-{video_id.lower()}"
        duration_value = _yaml_scalar(block, "duration_s")
        if duration_value is None:
            raise CardEventNetMigrationError(f"{video_id} has no duration_s in {path}")
        try:
            duration_s = float(duration_value)
        except ValueError as error:
            raise CardEventNetMigrationError(f"{video_id} has an invalid duration_s") from error
        if duration_s <= 0:
            raise CardEventNetMigrationError(f"{video_id} has a non-positive duration_s")
        result[video_id] = SourceMetadata(
            video_id=video_id,
            file_name=file_name,
            session_id=session_id,
            duration_s=duration_s,
            content_type=_yaml_scalar(block, "content_type") or "staged_trick_sequence",
            table_setup=_yaml_scalar(block, "table_setup") or f"setup-{video_id.lower()}",
            source_permission=_yaml_scalar(block, "source_permission") or "project_use",
            recording_date=_yaml_scalar(block, "recording_date"),
            notes=_yaml_scalar(block, "notes"),
        )
    if not result:
        raise CardEventNetMigrationError(f"No video metadata found in {path}")
    return result


def read_split(path: Path, partitions: Sequence[str] = DEFAULT_PARTITIONS) -> list[tuple[str, str]]:
    """Read the simple partition lists from a CardEventNet split file."""

    requested = tuple(partitions)
    allowed = {"val" if partition == "validation" else partition for partition in requested}
    current: str | None = None
    selected: list[tuple[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.endswith(":") and not line.startswith("-"):
            current = line[:-1].strip()
            continue
        if current not in allowed or not line.startswith("-"):
            continue
        video_id = line[1:].strip().strip("'\"")
        if video_id:
            selected.append(
                (video_id, "validation" if current in {"val", "validation"} else current)
            )
    if not selected:
        raise CardEventNetMigrationError(
            f"No recordings found in {path} for partitions: {', '.join(requested)}"
        )
    return selected


def filter_selected_videos(
    selected: Sequence[tuple[str, str]], video_ids: Sequence[str] | None
) -> list[tuple[str, str]]:
    """Limit a split selection to explicitly requested video IDs."""

    if not video_ids:
        return list(selected)
    requested = tuple(_safe_id(video_id, "video_id") for video_id in video_ids)
    if len(set(requested)) != len(requested):
        raise CardEventNetMigrationError("A requested video_id occurs more than once")
    available = {video_id for video_id, _partition in selected}
    missing = sorted(set(requested) - available)
    if missing:
        raise CardEventNetMigrationError(
            "Requested video IDs are not in the selected split partitions: " + ", ".join(missing)
        )
    requested_set = set(requested)
    return [item for item in selected if item[0] in requested_set]


def _load_events(
    annotation_path: Path, *, video_name: str, duration_us: int
) -> tuple[tuple[EventRecord, ...], str]:
    try:
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventNetMigrationError(f"Could not read annotation: {annotation_path}") from error
    if not isinstance(annotation, dict):
        raise CardEventNetMigrationError(f"Unsupported annotation schema: {annotation_path}")
    annotation_schema = annotation.get("schema_version")
    if annotation_schema is None:
        # IMG_2780/IMG_2781 predate the v2 envelope but contain the same human event list.
        annotation_schema = "cardevent-annotation/legacy-v1"
    elif annotation_schema != ANNOTATION_SCHEMA:
        raise CardEventNetMigrationError(f"Unsupported annotation schema: {annotation_path}")
    if Path(str(annotation.get("video", ""))).name != video_name:
        raise CardEventNetMigrationError(f"Annotation video does not match {video_name}")
    raw_events = annotation.get("events")
    if not isinstance(raw_events, list):
        raise CardEventNetMigrationError(f"Annotation events are not a list: {annotation_path}")

    events: list[EventRecord] = []
    previous_time = -1
    for index, raw_event in enumerate(raw_events):
        if not isinstance(raw_event, dict):
            raise CardEventNetMigrationError(f"Invalid event {index}: {annotation_path}")
        event_type = raw_event.get("type")
        time_s = raw_event.get("time_s")
        if event_type != CARD_STATE_CHANGED_EVENT_TYPE:
            raise CardEventNetMigrationError(
                f"Event {index} does not use {CARD_STATE_CHANGED_EVENT_TYPE}: {annotation_path}"
            )
        if isinstance(time_s, bool) or not isinstance(time_s, (int, float)):
            raise CardEventNetMigrationError(f"Invalid event time {index}: {annotation_path}")
        time_us = round(float(time_s) * 1_000_000)
        if time_us < previous_time or time_us > duration_us:
            raise CardEventNetMigrationError(f"Event time is outside video: {annotation_path}")
        previous_time = time_us
        events.append(
            EventRecord(
                event_id=f"cardeventnet-event-{video_name.rsplit('.', 1)[0].lower()}-{index:03d}",
                event_type=CARD_STATE_CHANGED_EVENT_TYPE,
                start_us=time_us,
                end_us=time_us,
            )
        )
    return tuple(events), annotation_schema


def _write_import_sidecar(
    operations_root: Path,
    recording_id: str,
    *,
    source_video: Path,
    source_annotation: Path,
    split: str,
    duration_us: int,
    event_count: int,
    video_sha256: str,
    annotation_schema: str,
) -> str:
    destination = operations_root / "cardeventnet-imports" / recording_id
    destination.mkdir(parents=True, exist_ok=True)
    annotation_bytes = source_annotation.read_bytes()
    annotation_sha256 = hashlib.sha256(annotation_bytes).hexdigest()
    (destination / "annotation.json").write_bytes(annotation_bytes)
    atomic_replace_json(
        destination / "import.json",
        _json_bytes(
            {
                "schema_version": "cardeventnet-import/v1",
                "recording_id": recording_id,
                "source_video": str(source_video),
                "source_annotation": str(source_annotation),
                "source_annotation_schema": annotation_schema,
                "split": split,
                "video_sha256": video_sha256,
                "annotation_sha256": annotation_sha256,
                "duration_us": duration_us,
                "events_total": event_count,
                "events_imported": event_count,
            }
        ),
    )
    return annotation_sha256


def _bundle_json_files(
    recording_id: str,
    source_asset_id: str,
    video_id: str,
    session_id: str,
    video_file: StoredRepositoryFile,
    source_file: StoredRepositoryFile,
    enrollment_file: StoredRepositoryFile,
    proposal_files: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "schema_version": "repository-bundle/v1",
        "source_asset_id": source_asset_id,
        "recording_id": recording_id,
        "video_id": video_id,
        "session_id": session_id,
        "state": "complete",
        "source_sha256": video_file.sha256,
        "files": {
            "video": {
                "relative_path": video_file.relative_path,
                "type": "video/quicktime",
                "byte_length": video_file.byte_length,
                "sha256": video_file.sha256,
            },
            "source_record": {
                "relative_path": source_file.relative_path,
                "type": "application/json",
                "byte_length": source_file.byte_length,
                "sha256": source_file.sha256,
            },
            "task_enrollment": {
                "relative_path": enrollment_file.relative_path,
                "type": "application/json",
                "byte_length": enrollment_file.byte_length,
                "sha256": enrollment_file.sha256,
            },
            "proposal_generator_runs": list(proposal_files),
        },
    }


def _publish_bundle(
    storage: RepositoryBundleStorage,
    recording_store: RecordingBundleStore,
    *,
    recording_id: str,
    video_path: Path,
    source_record: Mapping[str, Any],
    enrollment: Mapping[str, Any],
) -> tuple[str, int, bool]:
    with storage.start_bundle(recording_id) as staged:
        with video_path.open("rb") as source:
            video_file = staged.write_part(
                f"videos/video-{recording_id}{video_path.suffix.lower()}", source
            )
        source_file = staged.write_part(
            "source-record.json", io.BytesIO(_json_bytes(source_record))
        )
        enrollment_file = staged.write_part(
            "initial-task-enrollment.json", io.BytesIO(_json_bytes(enrollment))
        )
        manifest = _bundle_json_files(
            recording_id,
            str(source_record["source_asset_id"]),
            str(source_record["video_id"]),
            str(source_record["session_id"]),
            video_file,
            source_file,
            enrollment_file,
        )
        staged.write_part("manifest.json", io.BytesIO(_json_bytes(manifest)))
        files = staged.file_digests()
        stored, published = recording_store.publish(staged, staged_files=files)
    return stored.source_sha256, video_file.byte_length, published


def _pipeline_services(
    *,
    backend_root: Path,
) -> tuple[Settings, PipelineRevisionStore, PipelineReferenceService]:
    settings = Settings(
        repository_root=backend_root,
        evidence_root=backend_root / ".runtime",
        operations_root=backend_root / "data" / "operations",
        repository_intake_root=backend_root / "data" / "intake" / "recordings",
    )
    storage = RepositoryBundleStorage(settings.repository_intake_root)
    recording_store = RecordingBundleStore(storage)
    pipeline_storage = PipelineRuntimeStorage(settings.evidence_root, settings.operations_root)
    revision_store = PipelineRevisionStore(pipeline_storage)
    run_store = ProcessorRunStore(pipeline_storage, revision_store=revision_store)
    selection_store = PipelineSelectionStore(
        pipeline_storage,
        revision_store=revision_store,
        run_store=run_store,
    )
    return (
        settings,
        revision_store,
        PipelineReferenceService(
            settings,
            recording_store,
            storage,
            reference_store=PipelineReferenceStore(
                settings.operations_root / "pipeline-references"
            ),
            revision_store=revision_store,
            selection_store=selection_store,
        ),
    )


def _publish_event_reference(
    service: PipelineReferenceService,
    revision_store: PipelineRevisionStore,
    *,
    recording_id: str,
    revision: EventDataRevision,
) -> None:
    existing = service.reference_store.get(recording_id, "events")
    if existing is not None and existing.state.draft_state == "completed":
        return
    if existing is None:
        current = service.create_reference(
            recording_id,
            "events",
            {"operator_id": IMPORT_OPERATOR, "source_revision_id": revision.manifest.revision_id},
        )
    else:
        current = service.update_draft(
            recording_id,
            "events",
            {
                "expected_revision": existing.state.draft_revision,
                "operator_id": IMPORT_OPERATOR,
                "operations": [
                    {"operation": "rebase", "source_revision_id": revision.manifest.revision_id}
                ],
            },
        )
    pending = [item.item_id for item in current.draft.items if item.review_state == "pending"]
    if pending:
        current = service.update_draft(
            recording_id,
            "events",
            {
                "expected_revision": current.state.draft_revision,
                "operator_id": IMPORT_OPERATOR,
                "operations": [{"operation": "accept", "item_id": item_id} for item_id in pending],
            },
        )
    service.complete_reference(
        recording_id,
        "events",
        {
            "expected_revision": current.state.draft_revision,
            "operator_id": IMPORT_OPERATOR,
            "coverage": {"kind": "full_recording"},
        },
    )
    del revision_store


def migrate(
    *,
    source_root: Path,
    backend_root: Path,
    partitions: Sequence[str] = DEFAULT_PARTITIONS,
    split_name: str = DEFAULT_SPLIT,
    video_ids: Sequence[str] | None = None,
) -> tuple[MigrationResult, ...]:
    """Import CardEventNet train/validation recordings and their human events."""

    source_root = source_root.expanduser().resolve()
    backend_root = backend_root.expanduser().resolve()
    split_path = source_root / "splits" / split_name
    metadata = read_dataset_metadata(source_root / "dataset-manifest.v1.yaml")
    selected = filter_selected_videos(read_split(split_path, partitions), video_ids)
    settings, revision_store, reference_service = _pipeline_services(backend_root=backend_root)
    storage = RepositoryBundleStorage(settings.repository_intake_root)
    recording_store = RecordingBundleStore(storage)
    results: list[MigrationResult] = []

    for video_id, split in selected:
        if video_id not in metadata:
            raise CardEventNetMigrationError(f"Split references unknown video: {video_id}")
        details = metadata[video_id]
        video_path = source_root / "raw" / details.file_name
        annotation_path = source_root / "annotations" / f"{video_id}.json"
        if not video_path.is_file() or not annotation_path.is_file():
            raise CardEventNetMigrationError(f"Missing source pair for {video_id}")
        recording_id = _safe_id(f"cardeventnet-{video_id}", "recording_id")
        source_asset_id = f"source-{recording_id}"
        video_asset_id = f"video-{recording_id}"
        duration_us = round(details.duration_s * 1_000_000)
        events, annotation_schema = _load_events(
            annotation_path,
            video_name=details.file_name,
            duration_us=duration_us,
        )
        video_sha256 = _sha256_path(video_path)
        annotation_sha256 = _write_import_sidecar(
            settings.operations_root,
            recording_id,
            source_video=video_path,
            source_annotation=annotation_path,
            split=split,
            duration_us=duration_us,
            event_count=len(events),
            video_sha256=video_sha256,
            annotation_schema=annotation_schema,
        )
        source_record = {
            "schema_version": "source-record/v1",
            "source_asset_id": source_asset_id,
            "sha256": video_sha256,
            "byte_length": video_path.stat().st_size,
            "media_type": "video/quicktime",
            "original_filename": details.file_name,
            "acquisition_method": "cardeventnet_import",
            "source_permission": details.source_permission,
            "allowed_uses": [split],
            "session_id": details.session_id,
            "recording_id": recording_id,
            "video_id": video_asset_id,
            "game_id": None,
            "round_id": None,
            "table_setup": details.table_setup,
            "content_type": details.content_type,
            "retention_state": "active",
            "notes": (
                f"Imported from card_event_net/data using {split_name}; "
                f"human annotation preserved in "
                f"data/operations/cardeventnet-imports/{recording_id}. "
                f"{details.notes or ''}"
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
                    "operator": IMPORT_OPERATOR,
                    "created_at_utc": IMPORT_TIMESTAMP,
                    "reason": None,
                },
                {
                    "task_enrollment_id": f"{recording_id}-table_evidence_analysis",
                    "task": "table_evidence_analysis",
                    "disposition": "selected",
                    "lifecycle_state": "intake",
                    "operator": IMPORT_OPERATOR,
                    "created_at_utc": IMPORT_TIMESTAMP,
                    "reason": None,
                },
            ],
        }
        source_sha256, byte_length, published = _publish_bundle(
            storage,
            recording_store,
            recording_id=recording_id,
            video_path=video_path,
            source_record=source_record,
            enrollment=enrollment,
        )
        if source_sha256 != video_sha256:
            raise CardEventNetMigrationError(f"Bundle digest changed while importing {video_id}")

        relative_path = (
            (
                settings.repository_intake_root
                / recording_id
                / f"videos/video-{recording_id}{video_path.suffix.lower()}"
            )
            .resolve()
            .relative_to(settings.repository_root)
            .as_posix()
        )
        event_data = EventData(events=events)
        content_bytes = canonical_event_data_bytes(event_data)
        revision = DataRevision(
            revision_id=f"cardeventnet-events-{video_id.lower()}",
            content_type="events",
            content_schema="event-data/v1",
            recording_id=recording_id,
            source=RecordingVideoSource(
                recording_id=recording_id,
                relative_path=relative_path,
                video_sha256=video_sha256,
                byte_length=byte_length,
                duration_us=duration_us,
            ),
            content_sha256=sha256_bytes(content_bytes),
            input_revision_ids=(),
            origin="manual",
            producer=HumanProducer(
                review_id=f"cardeventnet-review-{video_id.lower()}",
                operator_id=IMPORT_OPERATOR,
            ),
            coverage={
                "kind": "full_recording",
                "source_annotation_schema": annotation_schema,
                "source_annotation_sha256": annotation_sha256,
            },
            created_at=IMPORT_TIMESTAMP,
        )
        event_revision = EventDataRevision(manifest=revision, content=event_data)
        revision_store.publish(event_revision)
        _publish_event_reference(
            reference_service,
            revision_store,
            recording_id=recording_id,
            revision=event_revision,
        )
        results.append(
            MigrationResult(
                recording_id=recording_id,
                source_video=details.file_name,
                split=split,
                event_count=len(events),
                video_bytes=byte_length,
                annotation_sha256=annotation_sha256,
                published=published,
            )
        )
    return tuple(results)


def _default_repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=_default_repository_root() / "card_event_net" / "data",
    )
    parser.add_argument("--backend-root", type=Path, default=_default_repository_root())
    parser.add_argument("--split", default=DEFAULT_SPLIT)
    parser.add_argument(
        "--partition",
        dest="partitions",
        action="append",
        choices=("train", "val", "validation", "test", "evaluation"),
        default=None,
    )
    parser.add_argument(
        "--video-id",
        dest="video_ids",
        action="append",
        default=None,
        help="Import only this video ID from the selected split partitions; repeat as needed.",
    )
    args = parser.parse_args(argv)
    results = migrate(
        source_root=args.source_root,
        backend_root=args.backend_root,
        partitions=tuple(args.partitions or DEFAULT_PARTITIONS),
        split_name=args.split,
        video_ids=args.video_ids,
    )
    total_bytes = sum(item.video_bytes for item in results)
    print(
        f"Imported {len(results)} recordings ({total_bytes / 1_000_000_000:.2f} GB) "
        f"with {sum(item.event_count for item in results)} human events."
    )
    for item in results:
        print(f"- {item.recording_id}: {item.split}, {item.event_count} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
