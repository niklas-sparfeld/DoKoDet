"""HTTP routes for the evidence upload contract."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException

from dokodetector_backend.config import Settings
from dokodetector_backend.contract import (
    EvidenceManifest,
    UploadResponse,
    calculate_package_fingerprint,
    parse_manifest_bytes,
    validate_package_id,
)
from dokodetector_backend.errors import ContractError
from dokodetector_backend.repository import (
    EvidenceRepository,
    LogicalEventConflict,
    PackageConflict,
    RepositoryError,
    StoredFrame,
    StoredPackage,
)
from dokodetector_backend.storage import StorageLimitError

FRAME_COPY_CHUNK_BYTES = 1024 * 1024
MANIFEST_MEDIA_TYPE = "application/json"
MULTIPART_MEDIA_TYPE = "multipart/form-data"
SUPPORTED_FRAME_MEDIA_TYPE = "image/jpeg"

router = APIRouter()


@router.put(
    "/v1/evidence-packages/{package_id}",
    response_model=UploadResponse,
    status_code=201,
)
async def upload_evidence_package(package_id: str, request: Request) -> JSONResponse:
    """Validate and persist one immutable multipart evidence package."""

    requested_package_id = _parse_package_id(package_id)
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
            max_fields=1000,
            max_part_size=settings.max_manifest_bytes,
        ) as form:
            manifest_upload, frame_uploads = _collect_uploads(form)
            _require_media_type(manifest_upload, MANIFEST_MEDIA_TYPE)
            manifest_bytes = await manifest_upload.read(settings.max_manifest_bytes + 1)
            manifest = parse_manifest_bytes(
                manifest_bytes,
                max_bytes=settings.max_manifest_bytes,
            )
            validate_package_id(requested_package_id, manifest)
            _validate_frame_parts(manifest, frame_uploads)

            package_bytes = len(manifest_bytes)
            if package_bytes > settings.max_package_bytes:
                raise ContractError(
                    "package_too_large",
                    "The package exceeds the configured size limit.",
                    status_code=413,
                )
            for frame in manifest.frames:
                upload = frame_uploads[frame.part_name]
                _require_media_type(upload, SUPPORTED_FRAME_MEDIA_TYPE)
                byte_length, digest = await _inspect_frame(
                    upload,
                    max_frame_bytes=settings.max_frame_bytes,
                )
                package_bytes += byte_length
                if package_bytes > settings.max_package_bytes:
                    raise ContractError(
                        "package_too_large",
                        "The package exceeds the configured size limit.",
                        status_code=413,
                    )
                if byte_length != frame.byte_length or digest != frame.sha256:
                    raise ContractError(
                        "hash_mismatch",
                        "The frame bytes do not match the manifest.",
                        details=[],
                    )

            fingerprint = calculate_package_fingerprint(manifest_bytes, manifest.frames)
            repository: EvidenceRepository = request.app.state.repository
            existing = repository.get_package(manifest.package_id)
            if existing is not None:
                if existing.package_fingerprint == fingerprint:
                    return _upload_response(existing, created=False)
                raise ContractError(
                    "package_conflict",
                    "The package ID is already stored with different content.",
                    status_code=409,
                )

            existing_event = repository.get_by_logical_event(
                manifest.session.session_id,
                manifest.session.event_sequence,
            )
            if existing_event is not None:
                raise ContractError(
                    "logical_event_conflict",
                    "The session and event sequence are already stored for another package.",
                    status_code=409,
                )

            package = StoredPackage.from_manifest(
                manifest,
                manifest_bytes,
                package_fingerprint=fingerprint,
                frames=tuple(
                    StoredFrame.from_manifest(
                        frame,
                        relative_path=(
                            f"evidence/{manifest.package_id}/frames/{frame.part_name}.jpg"
                        ),
                    )
                    for frame in manifest.frames
                ),
                received_at=datetime.now(timezone.utc),
            )
            try:
                stored = request.app.state.persister.persist(
                    package,
                    manifest_bytes,
                    {part_name: upload.file for part_name, upload in frame_uploads.items()},
                    max_manifest_bytes=settings.max_manifest_bytes,
                    max_frame_bytes=settings.max_frame_bytes,
                )
            except PackageConflict:
                return _resolve_package_conflict(repository, manifest.package_id, fingerprint)
            except LogicalEventConflict as error:
                raise ContractError(
                    "logical_event_conflict",
                    "The session and event sequence are already stored for another package.",
                    status_code=409,
                ) from error
            except (RepositoryError, OSError, StorageLimitError) as error:
                raise ContractError(
                    "internal_error",
                    "The package could not be stored.",
                    status_code=500,
                ) from error

            return _upload_response(stored, created=True)
    except MultiPartException as error:
        raise ContractError(
            "invalid_request",
            "The multipart request is malformed.",
            status_code=400,
        ) from error


def _parse_package_id(value: str) -> UUID:
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ContractError(
            "invalid_package_id",
            "The package ID is not a valid UUID.",
        ) from error


def _collect_uploads(form: FormData) -> tuple[UploadFile, dict[str, UploadFile]]:
    manifest_parts: list[UploadFile] = []
    frame_parts: dict[str, UploadFile] = {}
    for name, value in form.multi_items():
        if not isinstance(value, UploadFile):
            raise ContractError(
                "invalid_request",
                "Every multipart part must be a file part.",
                status_code=400,
            )
        if name == "manifest":
            manifest_parts.append(value)
            continue
        if name in frame_parts:
            raise ContractError(
                "invalid_request",
                "Multipart part names must be unique.",
                status_code=400,
            )
        frame_parts[name] = value

    if len(manifest_parts) != 1:
        raise ContractError(
            "invalid_request",
            "The request must contain exactly one manifest part.",
            status_code=400,
        )
    return manifest_parts[0], frame_parts


def _validate_frame_parts(manifest: EvidenceManifest, frame_uploads: dict[str, UploadFile]) -> None:
    declared_names = {frame.part_name for frame in manifest.frames}
    received_names = set(frame_uploads)
    if declared_names - received_names:
        raise ContractError(
            "invalid_request",
            "A declared frame part is missing.",
            status_code=400,
        )
    if received_names - declared_names:
        raise ContractError(
            "invalid_request",
            "The request contains an undeclared frame part.",
            status_code=400,
        )


def _require_media_type(upload: UploadFile, expected: str) -> None:
    if _media_type(upload.content_type) != expected:
        raise ContractError(
            "unsupported_media_type",
            f"The multipart part must use {expected}.",
            status_code=415,
        )


def _media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


async def _inspect_frame(upload: UploadFile, *, max_frame_bytes: int) -> tuple[int, str]:
    await upload.seek(0)
    digest = hashlib.sha256()
    byte_length = 0
    while chunk := await upload.read(FRAME_COPY_CHUNK_BYTES):
        byte_length += len(chunk)
        if byte_length > max_frame_bytes:
            raise ContractError(
                "frame_too_large",
                "A frame exceeds the configured size limit.",
                status_code=413,
            )
        digest.update(chunk)
    await upload.seek(0)
    return byte_length, digest.hexdigest()


def _upload_response(package: StoredPackage, *, created: bool) -> JSONResponse:
    response = UploadResponse(
        package_id=package.package_id,
        state="stored",
        created=created,
        received_at=package.received_at,
    )
    return JSONResponse(
        status_code=201 if created else 200,
        content=response.model_dump(mode="json"),
    )


def _resolve_package_conflict(
    repository: EvidenceRepository,
    package_id: UUID,
    fingerprint: str,
) -> JSONResponse:
    existing = repository.get_package(package_id)
    if existing is not None and existing.package_fingerprint == fingerprint:
        return _upload_response(existing, created=False)
    raise ContractError(
        "package_conflict",
        "The package ID is already stored with different content.",
        status_code=409,
    )


__all__ = ["router", "upload_evidence_package"]
