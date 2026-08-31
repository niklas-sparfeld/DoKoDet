"""HTTP routes for atomic shared repository-bundle intake."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException

from dokodetector_backend.config import Settings
from dokodetector_backend.errors import ContractError
from dokodetector_backend.intake_contract import (
    IntakeContractError,
    RepositoryBundle,
    SourceRecord,
    TaskEnrollmentDocument,
    parse_repository_bundle,
    validate_repository_bundle,
)
from dokodetector_backend.logging_config import get_or_create_request_id, log_event
from dokodetector_backend.repository_bundle_repository import (
    RepositoryBundleConflict,
    RepositoryBundleRepositoryError,
    StoredRepositoryBundle,
)
from dokodetector_backend.repository_bundle_storage import (
    RepositoryBundleStorage,
    StoredRepositoryFile,
    TemporaryRepositoryBundle,
    bundle_fingerprint,
)
from dokodetector_backend.storage import StorageLimitError

MULTIPART_MEDIA_TYPE = "multipart/form-data"
JSON_MEDIA_TYPE = "application/json"
VIDEO_MEDIA_TYPE = "video/quicktime"
RECORDING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
VIDEO_PATH_PATTERN = re.compile(r"^videos/[A-Za-z0-9][A-Za-z0-9._-]*\.mov$")
PROPOSAL_PATH_PATTERN = re.compile(r"^predictions/[A-Za-z0-9][A-Za-z0-9._-]*\.json$")
LOGGER = logging.getLogger(__name__)

router = APIRouter()


class RepositoryBundleUploadResponse(BaseModel):
    """Response returned after a bundle is accepted or found to be identical."""

    model_config = ConfigDict(extra="forbid")

    recording_id: str
    state: str
    created: bool
    received_at: datetime


class RepositoryBundleFileResponse(BaseModel):
    """Stored digest metadata for one canonical bundle member."""

    model_config = ConfigDict(extra="forbid")

    byte_length: int = Field(gt=0)
    sha256: str


class RepositoryBundleMetadataResponse(BaseModel):
    """Canonical bundle metadata and member hashes."""

    model_config = ConfigDict(extra="forbid")

    recording_id: str
    source_asset_id: str
    video_id: str
    session_id: str
    state: str
    source_sha256: str
    received_at: datetime
    files: dict[str, RepositoryBundleFileResponse]


@router.put(
    "/v1/repository-bundles/{recording_id}",
    response_model=RepositoryBundleUploadResponse,
    status_code=201,
)
async def upload_repository_bundle(
    recording_id: str, request: Request, response: Response
) -> RepositoryBundleUploadResponse:
    """Validate and atomically publish one repository bundle."""

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
            max_files=1000,
            max_fields=0,
            max_part_size=_multipart_part_limit(settings),
        ) as form:
            uploads = _collect_uploads(form)
            for name, upload in uploads.items():
                if isinstance(upload, list):
                    for proposal in upload:
                        _require_media_type(proposal, JSON_MEDIA_TYPE)
                elif name in {"manifest", "source_record", "task_enrollment"}:
                    _require_media_type(upload, JSON_MEDIA_TYPE)
                else:
                    _require_media_type(upload, VIDEO_MEDIA_TYPE)

            storage: RepositoryBundleStorage = request.app.state.repository_bundle_storage
            with storage.start_bundle(requested_id) as staged:
                bundle, source, enrollments, proposal_runs, staged_files = await _stage_bundle(
                    staged,
                    uploads,
                    requested_id=requested_id,
                    settings=settings,
                )
                log_event(
                    LOGGER,
                    logging.DEBUG,
                    "repository_bundle_validation_completed",
                    request_id=get_or_create_request_id(request),
                    upload_id=request.headers.get("x-dokodetector-upload-id") or "-",
                    recording_id=bundle.recording_id,
                    proposal_count=len(proposal_runs),
                    file_count=len(staged_files),
                )
                incoming_fingerprint = bundle_fingerprint(staged_files)
                try:
                    committed_files = staged.commit()
                    created = True
                except FileExistsError as error:
                    committed_files = storage.file_digests(requested_id)
                    if bundle_fingerprint(committed_files) != incoming_fingerprint:
                        raise ContractError(
                            "recording_conflict",
                            "The recording ID is already stored with different content.",
                            status_code=409,
                        ) from error
                    created = False

                log_event(
                    LOGGER,
                    logging.DEBUG,
                    "repository_bundle_publication_completed",
                    request_id=get_or_create_request_id(request),
                    upload_id=request.headers.get("x-dokodetector-upload-id") or "-",
                    recording_id=bundle.recording_id,
                    created=created,
                    file_count=len(committed_files),
                )

                received_at = datetime.now(timezone.utc)
                indexed = StoredRepositoryBundle(
                    recording_id=bundle.recording_id,
                    source_asset_id=bundle.source_asset_id,
                    video_id=bundle.video_id,
                    session_id=bundle.session_id,
                    source_sha256=bundle.source_sha256,
                    manifest_sha256=committed_files["manifest.json"].sha256,
                    source_record_sha256=committed_files["source-record.json"].sha256,
                    task_enrollment_sha256=committed_files["initial-task-enrollment.json"].sha256,
                    proposal_run_ids=tuple(run.proposal_generator_run_id for run in proposal_runs),
                    bundle_fingerprint=incoming_fingerprint,
                    state=bundle.state,
                    received_at=received_at,
                )
                try:
                    stored, index_created = request.app.state.repository_bundle_repository.insert(
                        indexed
                    )
                except RepositoryBundleConflict as error:
                    raise ContractError(
                        "recording_conflict",
                        "The recording ID is already stored with different content.",
                        status_code=409,
                    ) from error
                except RepositoryBundleRepositoryError as error:
                    raise ContractError(
                        "internal_error",
                        "The repository bundle index could not be stored.",
                        status_code=500,
                    ) from error
                if not (created and index_created):
                    response.status_code = 200
                log_event(
                    LOGGER,
                    logging.INFO,
                    "repository_bundle_stored",
                    request_id=get_or_create_request_id(request),
                    upload_id=request.headers.get("x-dokodetector-upload-id") or "-",
                    recording_id=stored.recording_id,
                    created=created and index_created,
                    proposal_count=len(stored.proposal_run_ids),
                )
                return RepositoryBundleUploadResponse(
                    recording_id=stored.recording_id,
                    state=stored.state,
                    created=created and index_created,
                    received_at=stored.received_at,
                )
    except MultiPartException as error:
        raise ContractError(
            "repository_bundle_request_too_large",
            "The repository bundle request exceeds the configured part limit.",
            status_code=413,
        ) from error
    except StorageLimitError as error:
        raise ContractError(
            "repository_bundle_too_large",
            "The repository bundle exceeds the configured size limit.",
            status_code=413,
        ) from error
    except ContractError:
        raise
    except IntakeContractError as error:
        raise ContractError(
            "repository_bundle_invalid",
            str(error),
            status_code=422,
        ) from error
    except (OSError, ValueError) as error:
        raise ContractError(
            "repository_bundle_invalid",
            str(error),
            status_code=422,
        ) from error
    except Exception as error:
        raise ContractError(
            "internal_error",
            "The repository bundle could not be stored.",
            status_code=500,
        ) from error


@router.get(
    "/v1/repository-bundles/{recording_id}",
    response_model=RepositoryBundleMetadataResponse,
)
def get_repository_bundle(recording_id: str, request: Request) -> RepositoryBundleMetadataResponse:
    """Return indexed metadata and current canonical member hashes."""

    requested_id = _parse_recording_id(recording_id)
    stored = request.app.state.repository_bundle_repository.get(requested_id)
    if stored is None:
        raise ContractError(
            "repository_bundle_not_found",
            "The repository bundle was not found.",
            status_code=404,
        )
    try:
        files = request.app.state.repository_bundle_storage.file_digests(requested_id)
    except OSError as error:
        raise ContractError(
            "internal_error",
            "The canonical repository bundle could not be read.",
            status_code=500,
        ) from error
    return RepositoryBundleMetadataResponse(
        recording_id=stored.recording_id,
        source_asset_id=stored.source_asset_id,
        video_id=stored.video_id,
        session_id=stored.session_id,
        state=stored.state,
        source_sha256=stored.source_sha256,
        received_at=stored.received_at,
        files={
            relative_path: RepositoryBundleFileResponse(
                byte_length=file.byte_length,
                sha256=file.sha256,
            )
            for relative_path, file in files.items()
        },
    )


@router.get(
    "/v1/repository-bundles/{recording_id}/video",
    response_model=None,
)
def get_repository_bundle_video(recording_id: str, request: Request) -> FileResponse:
    """Stream the complete source recording from one accepted bundle."""

    requested_id = _parse_recording_id(recording_id)
    stored = request.app.state.repository_bundle_repository.get(requested_id)
    if stored is None:
        raise ContractError(
            "repository_bundle_not_found",
            "The repository bundle was not found.",
            status_code=404,
        )
    bundle_path = request.app.state.repository_bundle_storage.bundle_path(requested_id)
    try:
        manifest = parse_repository_bundle((bundle_path / "manifest.json").read_bytes())
    except (OSError, TypeError, ValueError) as error:
        raise ContractError(
            "internal_error",
            "The recording manifest could not be read.",
            status_code=500,
        ) from error
    if manifest.recording_id != requested_id or manifest.source_sha256 != stored.source_sha256:
        raise ContractError(
            "internal_error",
            "The stored recording metadata is inconsistent.",
            status_code=500,
        )
    video_path = bundle_path / PurePosixPath(manifest.files.video.relative_path)
    if not video_path.is_file():
        raise ContractError(
            "internal_error",
            "The stored recording video is unavailable.",
            status_code=500,
        )
    return FileResponse(
        video_path,
        media_type=VIDEO_MEDIA_TYPE,
        headers={"ETag": f'"{manifest.files.video.sha256}"'},
    )


async def _stage_bundle(
    staged: TemporaryRepositoryBundle,
    uploads: dict[str, UploadFile | list[UploadFile]],
    *,
    requested_id: str,
    settings: Settings,
) -> tuple[
    RepositoryBundle,
    SourceRecord,
    TaskEnrollmentDocument,
    tuple,
    dict[str, StoredRepositoryFile],
]:
    manifest_upload = _one_upload(uploads, "manifest")
    source_upload = _one_upload(uploads, "source_record")
    enrollment_upload = _one_upload(uploads, "task_enrollment")
    video_upload = _one_upload(uploads, "video")

    manifest_bytes = await _stream_part(
        staged,
        "manifest.json",
        manifest_upload,
        settings.max_recording_manifest_bytes,
    )
    try:
        manifest = RepositoryBundle.model_validate(json.loads(manifest_bytes))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise IntakeContractError("repository bundle failed validation") from error
    if manifest.recording_id != requested_id:
        raise ContractError(
            "recording_id_mismatch",
            "The path recording ID does not match the bundle recording ID.",
        )
    _validate_manifest_paths(manifest)

    source_bytes = await _stream_part(
        staged,
        manifest.files.source_record.relative_path,
        source_upload,
        settings.max_recording_predictions_bytes,
    )
    enrollment_bytes = await _stream_part(
        staged,
        manifest.files.task_enrollment.relative_path,
        enrollment_upload,
        settings.max_recording_predictions_bytes,
    )
    await _stream_part(
        staged,
        manifest.files.video.relative_path,
        video_upload,
        settings.max_recording_video_bytes,
        read_back=False,
    )
    proposal_uploads = _many_uploads(uploads, "proposal")
    proposal_bytes: dict[str, bytes] = {}
    expected_proposals = {
        PurePosixPath(item.relative_path).name: item
        for item in manifest.files.proposal_generator_runs
    }
    if len(proposal_uploads) != len(expected_proposals):
        raise IntakeContractError("proposal files and supplied runs differ")
    for proposal_upload in proposal_uploads:
        filename = proposal_upload.filename or ""
        descriptor = expected_proposals.get(PurePosixPath(filename).name)
        if descriptor is None or filename != PurePosixPath(filename).name:
            raise ContractError(
                "invalid_request",
                "Each proposal filename must match its manifest member path.",
                status_code=400,
            )
        proposal_bytes[descriptor.proposal_generator_run_id] = await _stream_part(
            staged,
            descriptor.relative_path,
            proposal_upload,
            settings.max_recording_predictions_bytes,
        )

    bundle, source, enrollments, runs = validate_repository_bundle(
        manifest_bytes,
        source_bytes,
        enrollment_bytes,
        proposal_bytes,
    )
    _validate_source_metadata(source, bundle, video_upload.filename)
    staged_files = staged.file_digests()
    expected_files = {
        "manifest.json",
        bundle.files.video.relative_path,
        bundle.files.source_record.relative_path,
        bundle.files.task_enrollment.relative_path,
        *(item.relative_path for item in bundle.files.proposal_generator_runs),
    }
    if set(staged_files) != expected_files:
        raise IntakeContractError("bundle contains unexpected or missing files")
    _verify_descriptor(staged_files["manifest.json"], len(manifest_bytes), _sha256(manifest_bytes))
    _verify_descriptor(
        staged_files[bundle.files.video.relative_path],
        bundle.files.video.byte_length,
        bundle.files.video.sha256,
    )
    _verify_descriptor(
        staged_files[bundle.files.source_record.relative_path],
        bundle.files.source_record.byte_length,
        bundle.files.source_record.sha256,
    )
    _verify_descriptor(
        staged_files[bundle.files.task_enrollment.relative_path],
        bundle.files.task_enrollment.byte_length,
        bundle.files.task_enrollment.sha256,
    )
    for descriptor in bundle.files.proposal_generator_runs:
        _verify_descriptor(
            staged_files[descriptor.relative_path],
            descriptor.byte_length,
            descriptor.sha256,
        )
    _validate_total_size(staged_files, settings.max_recording_bytes)
    return bundle, source, enrollments, runs, staged_files


def _collect_uploads(form: FormData) -> dict[str, UploadFile | list[UploadFile]]:
    uploads: dict[str, UploadFile | list[UploadFile]] = {}
    allowed = {"manifest", "source_record", "task_enrollment", "video", "proposal"}
    for name, value in form.multi_items():
        if not isinstance(value, UploadFile) or name not in allowed:
            raise ContractError(
                "invalid_request",
                "The request must contain only repository bundle file parts.",
                status_code=400,
            )
        if name == "proposal":
            current = uploads.setdefault(name, [])
            assert isinstance(current, list)
            current.append(value)
        elif name in uploads:
            raise ContractError(
                "invalid_request",
                "The request must contain exactly one file for each bundle part.",
                status_code=400,
            )
        else:
            uploads[name] = value
    if set(uploads) != {"manifest", "source_record", "task_enrollment", "video", "proposal"}:
        raise ContractError(
            "invalid_request",
            "The request must contain manifest, source record, task enrollment, video, "
            "and proposal parts.",
            status_code=400,
        )
    if not _many_uploads(uploads, "proposal"):
        raise ContractError(
            "invalid_request",
            "The request must contain at least one proposal part.",
            status_code=400,
        )
    return uploads


def _one_upload(uploads: dict[str, UploadFile | list[UploadFile]], name: str) -> UploadFile:
    value = uploads[name]
    if isinstance(value, list):
        raise ContractError("invalid_request", f"The {name} part is invalid.")
    return value


def _many_uploads(uploads: dict[str, UploadFile | list[UploadFile]], name: str) -> list[UploadFile]:
    value = uploads[name]
    if not isinstance(value, list):
        raise ContractError("invalid_request", f"The {name} part is invalid.")
    return value


async def _stream_part(
    staged: TemporaryRepositoryBundle,
    relative_path: str,
    upload: UploadFile,
    max_bytes: int,
    *,
    read_back: bool = True,
) -> bytes:
    await upload.seek(0)
    try:
        staged.write_part(relative_path, upload.file, max_bytes=max_bytes)
    finally:
        await upload.seek(0)
    return staged.read_part(relative_path) if read_back else b""


def _validate_manifest_paths(bundle: RepositoryBundle) -> None:
    if bundle.files.source_record.relative_path != "source-record.json":
        raise IntakeContractError("source record path must be source-record.json")
    if bundle.files.task_enrollment.relative_path != "initial-task-enrollment.json":
        raise IntakeContractError("task enrollment path must be initial-task-enrollment.json")
    if not VIDEO_PATH_PATTERN.fullmatch(bundle.files.video.relative_path):
        raise IntakeContractError("video path must be a safe videos/*.mov path")
    if any(
        not PROPOSAL_PATH_PATTERN.fullmatch(item.relative_path)
        for item in bundle.files.proposal_generator_runs
    ):
        raise IntakeContractError("proposal paths must be safe predictions/*.json paths")


def _validate_source_metadata(
    source: SourceRecord, bundle: RepositoryBundle, filename: str | None
) -> None:
    if source.media_type != VIDEO_MEDIA_TYPE:
        raise IntakeContractError("source record media_type must be video/quicktime")
    if filename != PurePosixPath(bundle.files.video.relative_path).name:
        raise IntakeContractError("video filename differs from the manifest path")
    if (
        source.byte_length != bundle.files.video.byte_length
        or source.sha256 != bundle.source_sha256
    ):
        raise IntakeContractError("source record media metadata differs from the video")
    if source.content_type == "real_game" and not source.game_id:
        raise IntakeContractError("real_game source records need collection game metadata")
    if not source.table_setup:
        raise IntakeContractError("source records need collection table metadata")


def _verify_descriptor(
    file: StoredRepositoryFile, expected_length: int, expected_sha256: str
) -> None:
    if file.byte_length != expected_length or file.sha256 != expected_sha256:
        raise IntakeContractError(f"file hash or length mismatch for {file.relative_path}")


def _validate_total_size(files: dict[str, StoredRepositoryFile], max_bytes: int) -> None:
    if sum(file.byte_length for file in files.values()) > max_bytes:
        raise StorageLimitError("the repository bundle exceeds its total size limit")


def _parse_recording_id(value: str) -> str:
    if not RECORDING_ID_PATTERN.fullmatch(value):
        raise ContractError("invalid_recording_id", "The recording ID is invalid.")
    return value


def _media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _require_media_type(upload: UploadFile, expected: str) -> None:
    if _media_type(upload.content_type) != expected:
        raise ContractError(
            "invalid_request",
            f"The {upload.filename or 'uploaded'} part must use {expected}.",
            status_code=400,
        )


def _multipart_part_limit(settings: Settings) -> int:
    return max(
        settings.max_recording_manifest_bytes,
        settings.max_recording_predictions_bytes,
        settings.max_recording_video_bytes,
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = ["router"]
