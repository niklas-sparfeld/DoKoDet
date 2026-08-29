"""Create offline evidence packages from reviewed CardEventNet annotations."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import tempfile
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Sequence

from .annotation import AnnotationEvent, load_annotation, validate_annotation
from .manifest import DatasetRecord, load_dataset_manifest
from .splits import load_split
from .video import _import_cv2, read_video_metadata

DEFAULT_TARGET_OFFSETS_MS = (-800, -400, -100, 150, 400, 700)
EXTRACTION_SCHEMA_VERSION = "annotation-evidence-extraction/v1"
_PACKAGE_NAMESPACE = uuid.UUID("268ed957-9a44-48f6-8c6e-ec86af291893")
_SESSION_NAMESPACE = uuid.UUID("ff679b09-b859-473c-ae29-1be3158252e9")


class EvidenceExtractionError(RuntimeError):
    """Annotation evidence could not be extracted without ambiguous output."""


@dataclass(frozen=True, slots=True)
class EvidenceExtractionResult:
    output_dir: Path
    package_count: int
    excluded_event_count: int
    incomplete_package_count: int


@dataclass(frozen=True, slots=True)
class _PackageDefinition:
    package_id: str
    package_path: Path
    event: AnnotationEvent
    annotation_event_index: int
    event_sequence: int
    event_time_ms: int


@dataclass(frozen=True, slots=True)
class _FrameRequest:
    package_id: str
    target_index: int
    target_offset_ms: int
    frame_index: int


@dataclass(slots=True)
class _PackageFrames:
    definition: _PackageDefinition
    frames: list[dict[str, Any]] = field(default_factory=list)
    missing: set[int] = field(default_factory=set)


def extract_annotation_evidence(
    *,
    videos_dir: str | Path,
    annotations_dir: str | Path,
    dataset_manifest: str | Path,
    output_dir: str | Path,
    video_ids: Sequence[str] = (),
    split_path: str | Path | None = None,
    partitions: Sequence[str] = ("train", "val"),
    target_offsets_ms: Sequence[int] = DEFAULT_TARGET_OFFSETS_MS,
    jpeg_quality: float = 0.85,
) -> EvidenceExtractionResult:
    """Extract source-resolution frames around reviewed card-play annotations.

    The output contains lightweight ``cardevent-evidence/v2`` package directories and one
    extraction manifest that preserves their annotation and recording lineage. It does not publish
    the packages into repository intake or make visual card identity claims.
    """

    videos_root = Path(videos_dir).expanduser().resolve()
    annotations_root = Path(annotations_dir).expanduser().resolve()
    manifest_path = Path(dataset_manifest).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    offsets = _validate_options(target_offsets_ms, jpeg_quality)
    if destination.exists():
        raise EvidenceExtractionError(f"Output directory already exists: {destination}")
    if not videos_root.is_dir():
        raise EvidenceExtractionError(f"Video directory does not exist: {videos_root}")
    if not annotations_root.is_dir():
        raise EvidenceExtractionError(f"Annotation directory does not exist: {annotations_root}")

    selected_partitions = tuple(partitions)
    records = _select_records(
        load_dataset_manifest(manifest_path),
        video_ids,
        split_path=split_path,
        partitions=selected_partitions,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}.", dir=destination.parent
    ) as temporary:
        working = Path(temporary) / "output"
        working.mkdir()
        package_rows: list[dict[str, Any]] = []
        excluded_event_count = 0
        incomplete_package_count = 0
        for record in records:
            rows, excluded, incomplete = _extract_record(
                record,
                videos_root=videos_root,
                annotations_root=annotations_root,
                output_root=working,
                target_offsets_ms=offsets,
                jpeg_quality=jpeg_quality,
            )
            package_rows.extend(rows)
            excluded_event_count += excluded
            incomplete_package_count += incomplete

        extraction_manifest = {
            "schema_version": EXTRACTION_SCHEMA_VERSION,
            "source_kind": "reviewed_event_annotations",
            "created_at_utc": _utc_text(datetime.now(UTC)),
            "dataset_manifest": str(manifest_path),
            "dataset_manifest_sha256": _sha256_file(manifest_path),
            "split": None if split_path is None else str(Path(split_path).expanduser().resolve()),
            "split_sha256": (
                None
                if split_path is None
                else _sha256_file(Path(split_path).expanduser().resolve())
            ),
            "partitions": list(selected_partitions) if split_path is not None else [],
            "event_types": ["card_played"],
            "accepted_confidences": [None, "confirmed"],
            "target_offsets_ms": list(offsets),
            "jpeg_quality": jpeg_quality,
            "package_count": len(package_rows),
            "excluded_event_count": excluded_event_count,
            "incomplete_package_count": incomplete_package_count,
            "packages": package_rows,
        }
        _write_json(working / "extraction-manifest.json", extraction_manifest)
        working.replace(destination)

    return EvidenceExtractionResult(
        output_dir=destination,
        package_count=len(package_rows),
        excluded_event_count=excluded_event_count,
        incomplete_package_count=incomplete_package_count,
    )


def _extract_record(
    record: DatasetRecord,
    *,
    videos_root: Path,
    annotations_root: Path,
    output_root: Path,
    target_offsets_ms: tuple[int, ...],
    jpeg_quality: float,
) -> tuple[list[dict[str, Any]], int, int]:
    if record.file_name is None:
        raise EvidenceExtractionError(f"Dataset record {record.video_id} has no file_name.")
    video_path = videos_root / record.file_name
    annotation_path = annotations_root / f"{record.video_id}.json"
    _reject_lfs_pointer(video_path)
    metadata = read_video_metadata(video_path)
    annotation = load_annotation(annotation_path)
    validate_annotation(annotation, metadata)
    video_sha256 = _sha256_file(video_path)
    annotation_sha256 = _sha256_file(annotation_path)
    recording_start = _recording_start(record)
    selected_events = [
        (index, event)
        for index, event in enumerate(annotation.events)
        if event.type == "card_played" and event.confidence in {None, "confirmed"}
    ]
    excluded_event_count = len(annotation.events) - len(selected_events)

    packages: dict[str, _PackageFrames] = {}
    requests_by_frame: dict[int, list[_FrameRequest]] = defaultdict(list)
    for event_sequence, (event_index, event) in enumerate(selected_events, start=1):
        package_id = str(
            uuid.uuid5(
                _PACKAGE_NAMESPACE,
                ":".join(
                    (
                        video_sha256,
                        annotation_sha256,
                        str(event_index),
                        f"{event.time_s:.9f}",
                        ",".join(str(value) for value in target_offsets_ms),
                    )
                ),
            )
        )
        definition = _PackageDefinition(
            package_id=package_id,
            package_path=output_root / package_id,
            event=event,
            annotation_event_index=event_index,
            event_sequence=event_sequence,
            event_time_ms=_milliseconds(event.time_s),
        )
        state = _PackageFrames(definition=definition)
        packages[package_id] = state
        (definition.package_path / "frames").mkdir(parents=True)
        for target_index, target_offset_ms in enumerate(target_offsets_ms):
            target_time_s = event.time_s + target_offset_ms / 1000.0
            frame_index = _nearest_frame_index(target_time_s, metadata.fps)
            if frame_index < 0 or frame_index >= metadata.frame_count:
                state.missing.add(target_offset_ms)
                continue
            requests_by_frame[frame_index].append(
                _FrameRequest(package_id, target_index, target_offset_ms, frame_index)
            )

    _decode_requested_frames(
        video_path,
        requests_by_frame=requests_by_frame,
        packages=packages,
        fps=metadata.fps,
        recording_start=recording_start,
        jpeg_quality=jpeg_quality,
    )

    rows: list[dict[str, Any]] = []
    incomplete_count = 0
    for state in packages.values():
        state.frames.sort(key=lambda frame: target_offsets_ms.index(frame["target_offset_ms"]))
        missing = [offset for offset in target_offsets_ms if offset in state.missing]
        if missing:
            incomplete_count += 1
        _write_json(
            state.definition.package_path / "manifest.json",
            _evidence_manifest(
                state,
                record=record,
                metadata_width=metadata.width,
                metadata_height=metadata.height,
                fps=metadata.fps,
                annotation_sha256=annotation_sha256,
                target_offsets_ms=target_offsets_ms,
                jpeg_quality=jpeg_quality,
                missing=missing,
            ),
        )
        rows.append(
            {
                "package_id": state.definition.package_id,
                "relative_path": state.definition.package_id,
                "video_id": record.video_id,
                "source_video": record.file_name,
                "source_video_sha256": video_sha256,
                "annotation_file": annotation_path.name,
                "annotation_sha256": annotation_sha256,
                "annotation_event_index": state.definition.annotation_event_index,
                "event_sequence": state.definition.event_sequence,
                "event_time_s": state.definition.event.time_s,
                "event_type": state.definition.event.type,
                "event_confidence": state.definition.event.confidence,
                "session_id": record.session_id,
                "table_setup": record.table_setup,
                "card_deck": record.card_deck,
                "evidence_complete": not missing,
                "missing_frame_targets_ms": missing,
            }
        )
    return rows, excluded_event_count, incomplete_count


def _decode_requested_frames(
    video_path: Path,
    *,
    requests_by_frame: dict[int, list[_FrameRequest]],
    packages: dict[str, _PackageFrames],
    fps: float,
    recording_start: datetime,
    jpeg_quality: float,
) -> None:
    if not requests_by_frame:
        return
    cv2 = _import_cv2()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise EvidenceExtractionError(f"OpenCV could not open source video: {video_path}")
    unresolved = set(requests_by_frame)
    maximum_index = max(unresolved)
    quality = int(round(jpeg_quality * 100.0))
    try:
        frame_index = 0
        while frame_index <= maximum_index:
            ok, frame = capture.read()
            if not ok:
                break
            requests = requests_by_frame.get(frame_index)
            if requests:
                encoded, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
                if not encoded:
                    raise EvidenceExtractionError(
                        f"OpenCV could not encode frame {frame_index} from {video_path}"
                    )
                jpeg = buffer.tobytes()
                digest = hashlib.sha256(jpeg).hexdigest()
                actual_elapsed_ms = _milliseconds(frame_index / fps)
                captured_at = recording_start + timedelta(milliseconds=actual_elapsed_ms)
                height, width = frame.shape[:2]
                for request in requests:
                    state = packages[request.package_id]
                    part_name = f"frame_{request.target_index:02d}"
                    frame_path = state.definition.package_path / "frames" / f"{part_name}.jpg"
                    frame_path.write_bytes(jpeg)
                    state.frames.append(
                        {
                            "part_name": part_name,
                            "target_offset_ms": request.target_offset_ms,
                            "actual_offset_ms": (
                                actual_elapsed_ms - state.definition.event_time_ms
                            ),
                            "session_elapsed_ms": actual_elapsed_ms,
                            "captured_at_utc": _utc_text(captured_at),
                            "width": width,
                            "height": height,
                            "byte_length": len(jpeg),
                            "content_type": "image/jpeg",
                            "sha256": digest,
                        }
                    )
                unresolved.discard(frame_index)
                if not unresolved:
                    break
            frame_index += 1
    finally:
        capture.release()

    for frame_index in unresolved:
        for request in requests_by_frame[frame_index]:
            packages[request.package_id].missing.add(request.target_offset_ms)


def _evidence_manifest(
    state: _PackageFrames,
    *,
    record: DatasetRecord,
    metadata_width: int,
    metadata_height: int,
    fps: float,
    annotation_sha256: str,
    target_offsets_ms: tuple[int, ...],
    jpeg_quality: float,
    missing: list[int],
) -> dict[str, Any]:
    start_offset = min(-1000, min(target_offsets_ms))
    end_offset = max(1000, max(target_offsets_ms))
    session_uuid = uuid.uuid5(_SESSION_NAMESPACE, f"{record.session_id}:{record.video_id}")
    return {
        "schema_version": "cardevent-evidence/v2",
        "package_id": state.definition.package_id,
        "session": {
            "session_id": str(session_uuid),
            "event_sequence": state.definition.event_sequence,
        },
        "event": {
            "event_time_ms": state.definition.event_time_ms,
            "emitted_at_ms": state.definition.event_time_ms,
            "evidence_complete": not missing,
        },
        "model": {
            "name": "HumanAnnotation",
            "version": "cardevent-annotation/v2",
            # V2 calls this a weights digest. Annotation-derived packages use the source
            # annotation digest so the required generator digest still has exact provenance.
            "weights_sha256": annotation_sha256,
            "preprocessing": "reviewed_event_timestamp_v1",
        },
        "event_decoder": {
            "algorithm": "reviewed_annotation_v1",
            "threshold": 1.0,
            "peak_confirmation_ms": 0,
            "minimum_event_gap_ms": 0,
            "target_inference_hz": fps,
        },
        "evidence_capture": {
            "sample_hz": fps,
            "jpeg_quality": jpeg_quality,
            "ring_duration_ms": max(3000, end_offset - start_offset),
            "target_offsets_ms": list(target_offsets_ms),
            "maximum_lookup_distance_ms": max(1, math.ceil(500.0 / fps)),
            "finalization_delay_ms": max(0, max(target_offsets_ms)),
        },
        "video_capture": {
            "requested_start_offset_ms": start_offset,
            "requested_end_offset_ms": end_offset,
            "max_duration_ms": end_offset - start_offset,
            "max_width": metadata_width,
            "max_height": metadata_height,
            "max_nominal_frame_rate": fps,
            "encoder_average_bit_rate": 1_200_000,
            "max_byte_length": 750_000,
            "temporary_byte_capacity": 83_886_080,
            "queued_byte_capacity": 10 * 1024 * 1024,
            "container": "mp4",
            "video_codec": "h264",
            "content_type": "video/mp4",
        },
        "camera": {
            "position": "back",
            "orientation": record.orientation or "other",
            "width": metadata_width,
            "height": metadata_height,
        },
        "frames": state.frames,
        "video_snippet": None,
        "missing_frame_targets_ms": missing,
        "score_trace": [],
        "client": {
            "app_version": "cardevent",
            "build": "annotation-evidence-extraction-v1",
            "device_model_identifier": "offline-extractor",
            "os_version": platform.platform()[:128] or os.name,
        },
    }


def _validate_options(target_offsets_ms: Sequence[int], jpeg_quality: float) -> tuple[int, ...]:
    offsets = tuple(target_offsets_ms)
    invalid_offset = any(isinstance(value, bool) or not isinstance(value, int) for value in offsets)
    if not offsets or invalid_offset:
        raise EvidenceExtractionError("Target offsets must be a non-empty list of integers.")
    if len(offsets) != len(set(offsets)):
        raise EvidenceExtractionError("Target offsets must not contain duplicates.")
    if not math.isfinite(jpeg_quality) or not 0.0 < jpeg_quality <= 1.0:
        raise EvidenceExtractionError("JPEG quality must be greater than 0 and at most 1.")
    return offsets


def _select_records(
    records: Sequence[DatasetRecord],
    requested_video_ids: Sequence[str],
    *,
    split_path: str | Path | None,
    partitions: Sequence[str],
) -> tuple[DatasetRecord, ...]:
    by_id = {record.video_id: record for record in records}
    if requested_video_ids:
        missing = set(requested_video_ids) - set(by_id)
        if missing:
            raise EvidenceExtractionError(
                f"Video IDs are missing from the dataset manifest: {', '.join(sorted(missing))}"
            )
        selected = (by_id[video_id] for video_id in requested_video_ids)
    else:
        selected = iter(records)
    selected_records = tuple(selected)
    if split_path is None:
        return tuple(sorted(selected_records, key=lambda record: record.video_id))
    if not partitions:
        raise EvidenceExtractionError("At least one split partition is required with --split.")
    split = load_split(split_path)
    unknown_partitions = set(partitions) - {"train", "val", "test", "unassigned"}
    if unknown_partitions:
        raise EvidenceExtractionError(
            f"Unknown split partitions: {', '.join(sorted(unknown_partitions))}"
        )
    included_ids = {video_id for partition in partitions for video_id in split.names(partition)}
    missing = included_ids - set(by_id)
    if missing:
        raise EvidenceExtractionError(
            f"Split video IDs are missing from the dataset manifest: {', '.join(sorted(missing))}"
        )
    return tuple(
        sorted(
            (record for record in selected_records if record.video_id in included_ids),
            key=lambda record: record.video_id,
        )
    )


def _recording_start(record: DatasetRecord) -> datetime:
    value = record.recording_date
    if value is None:
        raise EvidenceExtractionError(
            f"Dataset record {record.video_id} needs recording_date for frame timestamps."
        )
    if "T" not in value:
        return datetime.combine(date.fromisoformat(value), time(), tzinfo=UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise EvidenceExtractionError(
            f"Dataset record {record.video_id} recording_date needs a UTC offset."
        )
    return parsed.astimezone(UTC)


def _nearest_frame_index(time_s: float, fps: float) -> int:
    if time_s < 0.0:
        return -1
    return math.floor(time_s * fps + 0.5)


def _milliseconds(seconds: float) -> int:
    return math.floor(seconds * 1000.0 + 0.5)


def _reject_lfs_pointer(path: Path) -> None:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(128)
    except OSError as error:
        raise EvidenceExtractionError(f"Could not read source video: {path}") from error
    if prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
        raise EvidenceExtractionError(
            f"Source video is a Git LFS pointer, not media: {path}. Fetch the LFS object first."
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise EvidenceExtractionError(f"Could not hash source file: {path}") from error
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = [
    "DEFAULT_TARGET_OFFSETS_MS",
    "EvidenceExtractionError",
    "EvidenceExtractionResult",
    "extract_annotation_evidence",
]
