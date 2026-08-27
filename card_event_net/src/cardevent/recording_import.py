"""Import validated backend training recordings into CardEventNet intake."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .events import DetectedEvent, ProbabilitySample
from .manifest import MANIFEST_SCHEMA_VERSION, DatasetRecord, ManifestError, load_dataset_manifest
from .recording_contract import (
    DevicePredictions,
    RecordingContractError,
    RecordingManifest,
    parse_device_predictions_bytes,
    parse_recording_manifest_bytes,
    validate_recording_documents,
)
from .review_session import ReviewSessionError, validate_review_queue

IMPORT_SCHEMA_VERSION = "cardevent-recording-import/v1"


class RecordingImportError(ValueError):
    """Raised when a backend recording cannot be imported safely."""


@dataclass(frozen=True, slots=True)
class RecordingImportResult:
    recording_id: str
    session_id: str
    video_id: str
    video_path: Path
    predictions_path: Path
    manifest_path: Path
    review_queue_path: Path | None
    receipt_path: Path
    receipt: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _Bundle:
    directory: Path
    manifest_path: Path
    manifest_bytes: bytes
    manifest: RecordingManifest
    video_path: Path
    video_sha256: str
    video_byte_length: int
    predictions_path: Path
    predictions_bytes: bytes
    predictions: DevicePredictions
    predictions_sha256: str
    candidate_queue_path: Path | None
    candidate_queue_bytes: bytes | None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_length = 0
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                byte_length += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise RecordingImportError(f"Could not read recording file {path}: {exc}") from exc
    return byte_length, digest.hexdigest()


def _read_file(path: Path, description: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RecordingImportError(f"Could not read {description} {path}: {exc}") from exc


def _bundle_file(root: Path, name: str, directory: str) -> Path:
    candidates = (root / directory / name, root / name)
    existing = tuple(path for path in candidates if path.is_file())
    if not existing:
        raise RecordingImportError(f"Recording is missing {directory}/{name}.")
    if len(existing) > 1:
        raise RecordingImportError(f"Recording contains duplicate copies of {name}.")
    return existing[0]


def _load_candidate_queue(
    root: Path, manifest: RecordingManifest
) -> tuple[Path | None, bytes | None]:
    path = root / "intake" / "candidate-review-queue.json"
    if not path.exists():
        return None, None
    if not path.is_file():
        raise RecordingImportError(f"Candidate review queue is not a file: {path}")
    raw = _read_file(path, "candidate review queue")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecordingImportError(f"Candidate review queue is not valid JSON: {exc}") from exc
    try:
        validate_review_queue(payload)
    except (ReviewSessionError, TypeError, ValueError) as exc:
        raise RecordingImportError(f"Candidate review queue is invalid: {exc}") from exc
    if payload.get("provenance") != "candidate_only":
        raise RecordingImportError("Candidate review queue must have candidate_only provenance.")
    if payload.get("recording_id") != manifest.recording_id:
        raise RecordingImportError("Candidate review queue recording_id does not match the bundle.")
    items = payload.get("items", [])
    if any(item.get("video") != manifest.video.name for item in items):
        raise RecordingImportError("Candidate review queue contains a different source video.")
    return path, raw


def _load_bundle(recording_dir: str | Path) -> _Bundle:
    root = Path(recording_dir).expanduser()
    if not root.is_dir():
        raise RecordingImportError(f"Recording directory does not exist: {root}")
    manifest_path = root / "manifest.json"
    manifest_bytes = _read_file(manifest_path, "recording manifest")
    try:
        manifest = parse_recording_manifest_bytes(manifest_bytes)
    except RecordingContractError as exc:
        raise RecordingImportError(f"Recording manifest is invalid: {exc}") from exc

    video_path = _bundle_file(root, manifest.video.name, "videos")
    predictions_path = _bundle_file(root, manifest.predictions.name, "predictions")
    predictions_bytes = _read_file(predictions_path, "device predictions")
    try:
        _manifest, predictions = validate_recording_documents(manifest_bytes, predictions_bytes)
    except RecordingContractError as exc:
        raise RecordingImportError(f"Recording documents are invalid: {exc}") from exc
    video_byte_length, video_sha256 = _sha256_file(video_path)
    if video_byte_length != manifest.video.byte_length or video_sha256 != manifest.video.sha256:
        raise RecordingImportError("Video bytes do not match the recording manifest.")
    predictions_byte_length = len(predictions_bytes)
    predictions_sha256 = _sha256_bytes(predictions_bytes)
    if (
        predictions_byte_length != manifest.predictions.byte_length
        or predictions_sha256 != manifest.predictions.sha256
    ):
        raise RecordingImportError("Prediction bytes do not match the recording manifest.")
    candidate_queue_path, candidate_queue_bytes = _load_candidate_queue(root, manifest)
    return _Bundle(
        directory=root,
        manifest_path=manifest_path,
        manifest_bytes=manifest_bytes,
        manifest=manifest,
        video_path=video_path,
        video_sha256=video_sha256,
        video_byte_length=video_byte_length,
        predictions_path=predictions_path,
        predictions_bytes=predictions_bytes,
        predictions=predictions,
        predictions_sha256=predictions_sha256,
        candidate_queue_path=candidate_queue_path,
        candidate_queue_bytes=candidate_queue_bytes,
    )


def _load_complete_metadata(path: str | Path, video_id: str) -> DatasetRecord:
    metadata_path = Path(path).expanduser()
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RecordingImportError("PyYAML is required to read complete metadata.") from exc
    try:
        data = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RecordingImportError(f"Could not read metadata {metadata_path}: {exc}") from exc

    if isinstance(data, Mapping) and "videos" in data:
        schema_version = data.get("schema_version")
        if schema_version != MANIFEST_SCHEMA_VERSION:
            raise RecordingImportError(f"Metadata schema must be {MANIFEST_SCHEMA_VERSION}.")
        rows = data.get("videos")
    elif isinstance(data, Mapping):
        rows = [data]
    elif isinstance(data, list):
        rows = data
    else:
        rows = None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise RecordingImportError(
            "Metadata must contain one complete operator-approved video record."
        )
    try:
        record = DatasetRecord.from_mapping(rows[0], require_complete=True)
    except (ManifestError, TypeError, ValueError) as exc:
        raise RecordingImportError(
            "Metadata must be a complete operator-approved video record: " + str(exc)
        ) from exc
    if record.video_id != video_id:
        raise RecordingImportError(
            f"Metadata video_id {record.video_id} does not match recording video_id {video_id}."
        )
    return record


def _ensure_directory(path: Path, description: str) -> None:
    if path.exists() and not path.is_dir():
        raise RecordingImportError(f"{description} is not a directory: {path}")


def _ensure_outside_bundle(root: Path, *paths: Path) -> None:
    bundle_root = root.resolve()
    for path in paths:
        resolved = path.resolve()
        if resolved == bundle_root or bundle_root in resolved.parents:
            raise RecordingImportError(
                f"Import destination must be outside the recording directory: {path}"
            )


def _existing_file_state(
    path: Path, expected_length: int, expected_sha256: str, description: str
) -> bool:
    if not path.exists():
        return False
    if not path.is_file():
        raise RecordingImportError(f"Import destination is not a file: {path}")
    length, digest = _sha256_file(path)
    if length != expected_length or digest != expected_sha256:
        suffix = " (video ID collision)" if description == "video" else ""
        raise RecordingImportError(
            f"Import destination {description} conflicts with the recording{suffix}."
        )
    return True


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        raise RecordingImportError(f"Could not write import artifact {path}: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        shutil.copyfile(source, temporary_path)
        os.replace(temporary_path, destination)
    except OSError as exc:
        raise RecordingImportError(
            f"Could not copy recording file to {destination}: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _restore_or_remove(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
    else:
        _atomic_write(path, previous)


def _load_existing_manifest(path: Path) -> tuple[DatasetRecord, ...]:
    if not path.exists():
        return ()
    if not path.is_file():
        raise RecordingImportError(f"Dataset manifest is not a file: {path}")
    try:
        return load_dataset_manifest(path)
    except (ManifestError, OSError, ValueError) as exc:
        raise RecordingImportError(f"Dataset manifest is invalid: {exc}") from exc


def _validate_existing_targets(
    bundle: _Bundle,
    record: DatasetRecord,
    records: tuple[DatasetRecord, ...],
    video_destination: Path,
    predictions_destination: Path,
    queue_destination: Path | None,
    queue_bytes: bytes | None,
) -> tuple[bool, bool, bool]:
    by_video_id = {item.video_id: item for item in records}
    existing_record = by_video_id.get(record.video_id)
    if existing_record is not None:
        if existing_record.to_mapping() != record.to_mapping():
            raise RecordingImportError(
                f"Video ID collision for {record.video_id}: existing metadata differs."
            )
        if existing_record.file_name != record.file_name:
            raise RecordingImportError(
                f"Video ID collision for {record.video_id}: file name differs."
            )
    for other in records:
        if other.video_id != record.video_id and other.file_name == record.file_name:
            raise RecordingImportError(f"File name collision for {record.file_name}.")
    video_exists = _existing_file_state(
        video_destination,
        bundle.video_byte_length,
        bundle.video_sha256,
        "video",
    )
    predictions_exists = _existing_file_state(
        predictions_destination,
        len(bundle.predictions_bytes),
        bundle.predictions_sha256,
        "predictions",
    )
    queue_exists = False
    if queue_destination is not None and queue_bytes is not None:
        queue_exists = _existing_file_state(
            queue_destination,
            len(queue_bytes),
            _sha256_bytes(queue_bytes),
            "candidate review queue",
        )
    return video_exists, predictions_exists, queue_exists


def _receipt_matches(path: Path, bundle: _Bundle) -> bool:
    if not path.exists():
        return False
    if not path.is_file():
        raise RecordingImportError(f"Import receipt is not a file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecordingImportError(f"Import receipt is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != IMPORT_SCHEMA_VERSION:
        return False
    files = payload.get("files")
    if not isinstance(files, Mapping):
        return False
    video = files.get("video")
    predictions = files.get("predictions")
    return (
        payload.get("recording_id") == bundle.manifest.recording_id
        and isinstance(files.get("manifest"), Mapping)
        and files["manifest"].get("sha256") == _sha256_bytes(bundle.manifest_bytes)
        and isinstance(video, Mapping)
        and video.get("sha256") == bundle.video_sha256
        and isinstance(predictions, Mapping)
        and predictions.get("sha256") == bundle.predictions_sha256
    )


def _build_receipt(
    bundle: _Bundle,
    record: DatasetRecord,
    *,
    manifest_path: Path,
    video_path: Path,
    predictions_path: Path,
    review_queue_path: Path | None,
    metadata_path: Path,
    operator: str,
) -> dict[str, Any]:
    files: dict[str, Any] = {
        "manifest": {
            "name": "manifest.json",
            "byte_length": len(bundle.manifest_bytes),
            "sha256": _sha256_bytes(bundle.manifest_bytes),
        },
        "video": {
            "name": bundle.manifest.video.name,
            "byte_length": bundle.video_byte_length,
            "sha256": bundle.video_sha256,
        },
        "predictions": {
            "name": bundle.manifest.predictions.name,
            "byte_length": len(bundle.predictions_bytes),
            "sha256": bundle.predictions_sha256,
        },
    }
    candidate_queue = None
    if bundle.candidate_queue_bytes is not None:
        candidate_queue = {
            "name": bundle.candidate_queue_path.name if bundle.candidate_queue_path else None,
            "byte_length": len(bundle.candidate_queue_bytes),
            "sha256": _sha256_bytes(bundle.candidate_queue_bytes),
        }
    return {
        "schema_version": IMPORT_SCHEMA_VERSION,
        "recording_id": bundle.manifest.recording_id,
        "session_id": bundle.manifest.session_id,
        "video_id": bundle.manifest.video_id,
        "operator": operator,
        "imported_at_utc": datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "source": {"recording_id": bundle.manifest.recording_id},
        "files": files,
        "outputs": {
            "manifest": str(manifest_path),
            "video": str(video_path),
            "predictions": str(predictions_path),
            "candidate_review_queue": (
                str(review_queue_path) if review_queue_path is not None else None
            ),
        },
        "metadata": {
            "video_record": record.to_mapping(),
            "source_metadata_sha256": _sha256_file(metadata_path)[1],
        },
        "candidate_queue": candidate_queue,
    }


def import_recording(
    recording_dir: str | Path,
    *,
    videos_dir: str | Path,
    predictions_dir: str | Path,
    metadata: str | Path,
    manifest: str | Path,
    review_dir: str | Path | None = None,
    receipt: str | Path | None = None,
    operator: str = "operator",
) -> RecordingImportResult:
    """Validate and atomically import one immutable backend recording bundle."""

    bundle = _load_bundle(recording_dir)
    record = _load_complete_metadata(metadata, bundle.manifest.video_id)
    if record.file_name != bundle.manifest.video.name:
        raise RecordingImportError("Metadata file_name does not match the recording video name.")
    if record.session_id != bundle.manifest.session_id:
        raise RecordingImportError("Metadata session_id does not match the recording session.")

    manifest_path = Path(manifest).expanduser()
    videos_root = Path(videos_dir).expanduser()
    predictions_root = Path(predictions_dir).expanduser()
    _ensure_directory(videos_root, "Videos destination")
    _ensure_directory(predictions_root, "Predictions destination")
    review_root = (
        Path(review_dir).expanduser()
        if review_dir is not None
        else manifest_path.parent / "review-intake"
    )
    queue_destination = (
        review_root / f"{bundle.manifest.recording_id}-candidate-review-queue.json"
        if bundle.candidate_queue_bytes is not None
        else None
    )
    video_destination = videos_root / record.file_name
    predictions_destination = predictions_root / bundle.manifest.predictions.name
    receipt_path = (
        Path(receipt).expanduser()
        if receipt is not None
        else manifest_path.with_name(f"{bundle.manifest.video_id}-recording-import-receipt.json")
    )
    _ensure_outside_bundle(
        bundle.directory,
        manifest_path,
        videos_root,
        predictions_root,
        review_root,
        receipt_path,
    )
    records = _load_existing_manifest(manifest_path)
    video_exists, predictions_exists, queue_exists = _validate_existing_targets(
        bundle,
        record,
        records,
        video_destination,
        predictions_destination,
        queue_destination,
        bundle.candidate_queue_bytes,
    )
    if receipt_path.exists() and not _receipt_matches(receipt_path, bundle):
        raise RecordingImportError(f"Import receipt conflicts with the recording: {receipt_path}")

    existing_by_id = {item.video_id: item for item in records}
    merged_records = records if record.video_id in existing_by_id else (*records, record)
    merged_records = tuple(sorted(merged_records, key=lambda item: item.video_id))
    manifest_content: bytes | None = None
    if record.video_id not in existing_by_id:
        try:
            import yaml

            manifest_content = yaml.safe_dump(
                {
                    "schema_version": MANIFEST_SCHEMA_VERSION,
                    "videos": [item.to_mapping() for item in merged_records],
                },
                sort_keys=False,
                allow_unicode=True,
            ).encode("utf-8")
        except ModuleNotFoundError as exc:
            raise RecordingImportError(f"Could not write dataset manifest: {exc}") from exc
        except yaml.YAMLError as exc:
            raise RecordingImportError(f"Could not write dataset manifest: {exc}") from exc

    receipt_payload = _build_receipt(
        bundle,
        record,
        manifest_path=manifest_path,
        video_path=video_destination,
        predictions_path=predictions_destination,
        review_queue_path=queue_destination,
        metadata_path=Path(metadata),
        operator=operator,
    )
    receipt_content = (json.dumps(receipt_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")

    changed: list[tuple[Path, bytes | None]] = []
    try:
        if not video_exists:
            _atomic_copy(bundle.video_path, video_destination)
            changed.append((video_destination, None))
        if not predictions_exists:
            _atomic_copy(bundle.predictions_path, predictions_destination)
            changed.append((predictions_destination, None))
        if (
            queue_destination is not None
            and bundle.candidate_queue_bytes is not None
            and not queue_exists
        ):
            _atomic_write(queue_destination, bundle.candidate_queue_bytes)
            changed.append((queue_destination, None))
        if manifest_content is not None:
            previous = manifest_path.read_bytes() if manifest_path.exists() else None
            _atomic_write(manifest_path, manifest_content)
            changed.append((manifest_path, previous))
        if not receipt_path.exists():
            _atomic_write(receipt_path, receipt_content)
            changed.append((receipt_path, None))
        elif not _receipt_matches(receipt_path, bundle):
            raise RecordingImportError(
                f"Import receipt conflicts with the recording: {receipt_path}"
            )
    except (OSError, RecordingImportError) as exc:
        for path, previous in reversed(changed):
            with suppress(OSError, RecordingImportError):
                _restore_or_remove(path, previous)
        if isinstance(exc, RecordingImportError):
            raise
        raise RecordingImportError(f"Recording import failed: {exc}") from exc

    if receipt_path.exists():
        try:
            stored_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecordingImportError(f"Could not read import receipt: {exc}") from exc
    else:
        stored_receipt = receipt_payload
    return RecordingImportResult(
        recording_id=bundle.manifest.recording_id,
        session_id=bundle.manifest.session_id,
        video_id=bundle.manifest.video_id,
        video_path=video_destination,
        predictions_path=predictions_destination,
        manifest_path=manifest_path,
        review_queue_path=queue_destination,
        receipt_path=receipt_path,
        receipt=stored_receipt,
    )


def load_device_predictions(path: str | Path) -> DevicePredictions:
    """Load the versioned device-prediction contract from an imported file."""

    raw = _read_file(Path(path), "device predictions")
    try:
        return parse_device_predictions_bytes(raw)
    except RecordingContractError as exc:
        raise RecordingImportError(f"Device predictions are invalid: {exc}") from exc


def probability_stream_from_device_predictions(
    predictions: DevicePredictions,
) -> tuple[ProbabilitySample, ...]:
    """Convert device probabilities to CardEventNet's probability-stream type."""

    return tuple(
        ProbabilitySample(sample.time_s, sample.probability) for sample in predictions.probabilities
    )


def event_proposals_from_device_predictions(
    predictions: DevicePredictions,
) -> tuple[DetectedEvent, ...]:
    """Convert device event proposals to CardEventNet's decoded-event type."""

    return tuple(
        DetectedEvent(proposal.time_s, proposal.probability, proposal.emitted_at_s)
        for proposal in predictions.event_proposals
    )


def load_device_probability_stream(path: str | Path) -> tuple[ProbabilitySample, ...]:
    """Load device probabilities as the existing CardEventNet stream type."""

    return probability_stream_from_device_predictions(load_device_predictions(path))


__all__ = [
    "IMPORT_SCHEMA_VERSION",
    "RecordingImportError",
    "RecordingImportResult",
    "import_recording",
    "event_proposals_from_device_predictions",
    "load_device_predictions",
    "load_device_probability_stream",
    "probability_stream_from_device_predictions",
]
