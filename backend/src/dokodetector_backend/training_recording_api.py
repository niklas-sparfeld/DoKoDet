"""HTTP routes for immutable training-recording intake."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException

from dokodetector_backend.config import Settings
from dokodetector_backend.errors import ContractError
from dokodetector_backend.recording_contract import (
    TrainingRecordingMetadataResponse,
    TrainingRecordingUploadResponse,
    calculate_recording_fingerprint,
    validate_recording_documents,
)
from dokodetector_backend.recording_derivation import (
    build_candidate_review_queue,
    build_dataset_record_yaml,
)
from dokodetector_backend.recording_repository import (
    StoredTrainingRecording,
    TrainingRecordingConflict,
    TrainingRecordingRepository,
    TrainingRecordingRepositoryError,
)
from dokodetector_backend.recording_storage import (
    StoredFile,
    TrainingRecordingStorage,
)
from dokodetector_backend.storage import COPY_CHUNK_BYTES, StorageLimitError

MULTIPART_MEDIA_TYPE = "multipart/form-data"
JSON_MEDIA_TYPE = "application/json"
VIDEO_MEDIA_TYPE = "video/quicktime"
RECORDING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")

router = APIRouter()


@router.put(
    "/v1/training-recordings/{recording_id}",
    response_model=TrainingRecordingUploadResponse,
    status_code=201,
)
async def upload_training_recording(recording_id: str, request: Request) -> JSONResponse:
    """Validate and persist one immutable recording multipart request."""

    requested_id = _parse_recording_id(recording_id)
    settings: Settings = request.app.state.settings
    if _media_type(request.headers.get("content-type")) != MULTIPART_MEDIA_TYPE:
        raise ContractError(
            "invalid_request",
            "The request must use multipart/form-data.",
            status_code=400,
        )

    try:
        async with request.form(
            max_files=3,
            max_fields=0,
            max_part_size=_multipart_part_limit(settings),
        ) as form:
            manifest_upload, video_upload, predictions_upload = _collect_uploads(form)
            _require_media_type(manifest_upload, JSON_MEDIA_TYPE)
            _require_media_type(predictions_upload, JSON_MEDIA_TYPE)
            _require_media_type(video_upload, VIDEO_MEDIA_TYPE)

            manifest_bytes = await _read_json_part(
                manifest_upload,
                max_bytes=settings.max_recording_manifest_bytes,
                too_large_code="recording_manifest_too_large",
            )
            predictions_bytes = await _read_json_part(
                predictions_upload,
                max_bytes=settings.max_recording_predictions_bytes,
                too_large_code="recording_predictions_too_large",
            )
            manifest, predictions = validate_recording_documents(manifest_bytes, predictions_bytes)
            if manifest.recording_id != requested_id:
                raise ContractError(
                    "recording_id_mismatch",
                    "The path recording ID does not match the manifest recording ID.",
                )
            _verify_declared_bytes(
                predictions_bytes,
                manifest.predictions.byte_length,
                manifest.predictions.sha256,
                "predictions",
            )
            predictions_sha256 = hashlib.sha256(predictions_bytes).hexdigest()

            repository: TrainingRecordingRepository = request.app.state.training_repository
            existing = repository.get(requested_id)
            if existing is not None:
                video = await _inspect_video(
                    video_upload,
                    max_bytes=settings.max_recording_video_bytes,
                )
                _verify_declared_file(video, manifest.video.byte_length, manifest.video.sha256)
                _validate_total_size(
                    len(manifest_bytes) + len(predictions_bytes) + video.byte_length,
                    settings.max_recording_bytes,
                )
                fingerprint = calculate_recording_fingerprint(
                    manifest_bytes,
                    video.sha256,
                    predictions_sha256,
                )
                if existing.recording_fingerprint == fingerprint:
                    return _recording_upload_response(existing, created=False)
                raise ContractError(
                    "recording_conflict",
                    "The recording ID is already stored with different content.",
                    status_code=409,
                )

            storage: TrainingRecordingStorage = request.app.state.training_storage
            committed = False
            try:
                with storage.start_recording(requested_id) as upload:
                    upload.write_manifest(manifest_bytes)
                    upload.write_predictions(manifest.predictions.name, predictions_bytes)
                    video = upload.write_video(
                        manifest.video.name,
                        video_upload.file,
                        max_bytes=settings.max_recording_video_bytes,
                    )
                    _verify_declared_file(video, manifest.video.byte_length, manifest.video.sha256)
                    _validate_total_size(
                        len(manifest_bytes) + len(predictions_bytes) + video.byte_length,
                        settings.max_recording_bytes,
                    )
                    committed_files = upload.commit()
                    committed = True

                dataset_record = build_dataset_record_yaml(manifest)
                candidate_queue = build_candidate_review_queue(
                    manifest,
                    predictions,
                    predictions_sha256=predictions_sha256,
                )
                dataset_file, queue_file = storage.write_derived(
                    requested_id,
                    dataset_record=dataset_record,
                    candidate_queue=candidate_queue,
                )
                stored = StoredTrainingRecording(
                    recording_id=manifest.recording_id,
                    schema_version=manifest.schema_version,
                    session_id=manifest.session_id,
                    video_id=manifest.video_id,
                    started_at_utc=manifest.started_at_utc,
                    ended_at_utc=manifest.ended_at_utc,
                    duration_s=manifest.duration_s,
                    manifest_json=manifest_bytes.decode("utf-8"),
                    manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                    video=committed_files.video,
                    predictions=committed_files.predictions,
                    recording_fingerprint=calculate_recording_fingerprint(
                        manifest_bytes,
                        committed_files.video.sha256,
                        committed_files.predictions.sha256,
                    ),
                    state="stored",
                    received_at=datetime.now(timezone.utc),
                    derived_state="ready",
                    dataset_record=dataset_file,
                    candidate_queue=queue_file,
                )
                try:
                    inserted = repository.insert(stored)
                except TrainingRecordingConflict as error:
                    existing = repository.get(requested_id)
                    if (
                        existing is not None
                        and existing.recording_fingerprint == stored.recording_fingerprint
                    ):
                        storage.remove_recording(requested_id)
                        return _recording_upload_response(existing, created=False)
                    raise ContractError(
                        "recording_conflict",
                        "The recording ID is already stored with different content.",
                        status_code=409,
                    ) from error
                return _recording_upload_response(inserted, created=True)
            except ContractError:
                if committed:
                    storage.remove_recording(requested_id)
                raise
            except StorageLimitError as error:
                if committed:
                    storage.remove_recording(requested_id)
                raise ContractError(
                    "recording_video_too_large",
                    "The recording video exceeds the configured size limit.",
                    status_code=413,
                ) from error
            except (OSError, TrainingRecordingRepositoryError) as error:
                if committed:
                    storage.remove_recording(requested_id)
                raise ContractError(
                    "internal_error",
                    "The recording could not be stored.",
                    status_code=500,
                ) from error
            except Exception as error:
                if committed:
                    storage.remove_recording(requested_id)
                raise ContractError(
                    "internal_error",
                    "The recording could not be stored.",
                    status_code=500,
                ) from error
    except MultiPartException as error:
        raise ContractError(
            "recording_request_too_large",
            "The recording request exceeds the configured part limit.",
            status_code=413,
        ) from error


@router.get(
    "/v1/training-recordings/{recording_id}",
    response_model=TrainingRecordingMetadataResponse,
)
def get_training_recording(
    recording_id: str, request: Request
) -> TrainingRecordingMetadataResponse:
    """Return immutable recording metadata and derived-artifact state."""

    requested_id = _parse_recording_id(recording_id)
    repository: TrainingRecordingRepository = request.app.state.training_repository
    recording = repository.get(requested_id)
    if recording is None:
        raise ContractError(
            "recording_not_found",
            "The training recording was not found.",
            status_code=404,
        )
    try:
        return _recording_metadata_response(
            recording,
            evidence_package_count=repository.count_evidence_packages(recording.session_id),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ContractError(
            "internal_error",
            "The stored recording metadata is invalid.",
            status_code=500,
        ) from error


def _collect_uploads(form: FormData) -> tuple[UploadFile, UploadFile, UploadFile]:
    uploads: dict[str, UploadFile] = {}
    for name, value in form.multi_items():
        if not isinstance(value, UploadFile):
            raise ContractError(
                "invalid_request",
                "Every multipart part must be a file part.",
                status_code=400,
            )
        if name in uploads or name not in {"manifest", "video", "predictions"}:
            raise ContractError(
                "invalid_request",
                "The request must contain exactly one manifest, video, and predictions part.",
                status_code=400,
            )
        uploads[name] = value
    if set(uploads) != {"manifest", "video", "predictions"}:
        raise ContractError(
            "invalid_request",
            "The request must contain exactly one manifest, video, and predictions part.",
            status_code=400,
        )
    return uploads["manifest"], uploads["video"], uploads["predictions"]


async def _read_json_part(
    upload: UploadFile,
    *,
    max_bytes: int,
    too_large_code: str,
) -> bytes:
    await upload.seek(0)
    value = await upload.read(max_bytes + 1)
    await upload.seek(0)
    if len(value) > max_bytes:
        raise ContractError(
            too_large_code,
            "A recording JSON part exceeds the configured size limit.",
            status_code=413,
        )
    return value


async def _inspect_video(upload: UploadFile, *, max_bytes: int) -> StoredFile:
    await upload.seek(0)
    digest = hashlib.sha256()
    byte_length = 0
    while chunk := await upload.read(COPY_CHUNK_BYTES):
        byte_length += len(chunk)
        if byte_length > max_bytes:
            raise ContractError(
                "recording_video_too_large",
                "The recording video exceeds the configured size limit.",
                status_code=413,
            )
        digest.update(chunk)
    await upload.seek(0)
    return StoredFile(relative_path="", byte_length=byte_length, sha256=digest.hexdigest())


def _verify_declared_file(file: StoredFile, expected_length: int, expected_sha256: str) -> None:
    _verify_declared_bytes(file, expected_length, expected_sha256, "video")


def _verify_declared_bytes(
    value: bytes | StoredFile,
    expected_length: int,
    expected_sha256: str,
    name: str,
) -> None:
    actual_length = len(value) if isinstance(value, bytes) else value.byte_length
    actual_sha256 = hashlib.sha256(value).hexdigest() if isinstance(value, bytes) else value.sha256
    if actual_length != expected_length or actual_sha256 != expected_sha256:
        raise ContractError(
            "recording_hash_mismatch",
            f"The {name} bytes do not match the manifest.",
        )


def _validate_total_size(total_bytes: int, max_bytes: int) -> None:
    if total_bytes > max_bytes:
        raise ContractError(
            "recording_too_large",
            "The recording exceeds the configured total size limit.",
            status_code=413,
        )


def _recording_upload_response(
    recording: StoredTrainingRecording,
    *,
    created: bool,
) -> JSONResponse:
    response = TrainingRecordingUploadResponse(
        recording_id=recording.recording_id,
        state="stored",
        created=created,
        received_at=recording.received_at,
    )
    return JSONResponse(
        status_code=201 if created else 200,
        content=response.model_dump(mode="json"),
    )


def _recording_metadata_response(
    recording: StoredTrainingRecording,
    *,
    evidence_package_count: int,
) -> TrainingRecordingMetadataResponse:
    manifest = json.loads(recording.manifest_json)
    if not isinstance(manifest, dict):
        raise ValueError("The stored manifest must be an object.")
    video_descriptor = manifest["video"]
    prediction_descriptor = manifest["predictions"]
    if not isinstance(video_descriptor, dict) or not isinstance(prediction_descriptor, dict):
        raise ValueError("The stored file descriptors must be objects.")
    return TrainingRecordingMetadataResponse(
        recording_id=recording.recording_id,
        session_id=recording.session_id,
        video_id=recording.video_id,
        state="stored",
        received_at=recording.received_at,
        schema_version=recording.schema_version,
        started_at_utc=recording.started_at_utc,
        ended_at_utc=recording.ended_at_utc,
        duration_s=recording.duration_s,
        manifest_sha256=recording.manifest_sha256,
        manifest=manifest,
        video={
            "name": video_descriptor["name"],
            "type": video_descriptor["type"],
            "byte_length": recording.video.byte_length,
            "sha256": recording.video.sha256,
            "relative_path": recording.video.relative_path,
        },
        predictions={
            "name": prediction_descriptor["name"],
            "type": prediction_descriptor["type"],
            "byte_length": recording.predictions.byte_length,
            "sha256": recording.predictions.sha256,
            "relative_path": recording.predictions.relative_path,
        },
        derived_artifacts={
            "state": recording.derived_state,
            "dataset_record": _derived_response(
                recording.dataset_record,
                name="dataset-record.yaml",
            ),
            "candidate_review_queue": (
                _derived_response(recording.candidate_queue, name="candidate-review-queue.json")
                if recording.candidate_queue is not None
                else None
            ),
        },
        evidence_package_count=evidence_package_count,
    )


def _derived_response(file: StoredFile, *, name: str) -> dict[str, object]:
    return {
        "state": "ready",
        "name": name,
        "byte_length": file.byte_length,
        "sha256": file.sha256,
        "relative_path": file.relative_path,
    }


def _parse_recording_id(value: str) -> str:
    if not RECORDING_ID_PATTERN.fullmatch(value):
        raise ContractError(
            "invalid_recording_id",
            "The recording ID is not a valid identifier.",
        )
    return value


def _require_media_type(upload: UploadFile, expected: str) -> None:
    if _media_type(upload.content_type) != expected:
        raise ContractError(
            "unsupported_media_type",
            f"The multipart part must use {expected}.",
            status_code=415,
        )


def _media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _multipart_part_limit(settings: Settings) -> int:
    return max(
        settings.max_recording_manifest_bytes,
        settings.max_recording_predictions_bytes,
        settings.max_recording_video_bytes,
    )


__all__ = ["get_training_recording", "router", "upload_training_recording"]
