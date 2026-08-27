"""HTTP routes for the evidence upload contract."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException
from vision_detector import VisionContractError, VisionDetectionResult, parse_result_bytes

from dokodetector_backend.config import Settings
from dokodetector_backend.contract import (
    SUPPORTED_VIDEO_CONTENT_TYPE,
    EvidenceManifest,
    PackageMetadataResponse,
    StoredFrameResponse,
    UploadResponse,
    VideoSnippetManifest,
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
from dokodetector_backend.video_probe import (
    UnsupportedVideoError,
    VideoProbeError,
    VideoProbeUnavailable,
    probe_video_bytes,
)

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
            video_upload = None
            if manifest.video_snippet is not None and manifest.video_snippet.capture_complete:
                video_part_name = manifest.video_snippet.part_name
                assert video_part_name is not None
                video_upload = frame_uploads.pop(video_part_name, None)
                if video_upload is None:
                    raise ContractError(
                        "invalid_request",
                        "The declared video snippet part is missing.",
                        status_code=400,
                    )
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

            if manifest.video_snippet is not None and manifest.video_snippet.capture_complete:
                assert video_upload is not None
                _require_media_type(video_upload, SUPPORTED_VIDEO_CONTENT_TYPE)
                video_length, video_digest = await _inspect_video(
                    video_upload,
                    manifest.video_snippet,
                    max_video_bytes=settings.max_video_bytes,
                )
                package_bytes += video_length
                if package_bytes > settings.max_package_bytes:
                    raise ContractError(
                        "package_too_large",
                        "The package exceeds the configured size limit.",
                        status_code=413,
                    )
                if (
                    video_length != manifest.video_snippet.byte_length
                    or video_digest != manifest.video_snippet.sha256
                ):
                    raise ContractError(
                        "hash_mismatch",
                        "The video snippet bytes do not match the manifest.",
                        details=[],
                    )

            fingerprint = calculate_package_fingerprint(
                manifest_bytes,
                manifest.frames,
                video_snippet=manifest.video_snippet,
            )
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
                    video_source=video_upload.file if video_upload is not None else None,
                    video_part_name=(
                        manifest.video_snippet.part_name
                        if manifest.video_snippet is not None
                        and manifest.video_snippet.capture_complete
                        else None
                    ),
                    max_manifest_bytes=settings.max_manifest_bytes,
                    max_frame_bytes=settings.max_frame_bytes,
                    max_video_bytes=settings.max_video_bytes,
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


@router.get(
    "/v1/evidence-packages/{package_id}",
    response_model=PackageMetadataResponse,
)
def get_evidence_package(package_id: str, request: Request) -> PackageMetadataResponse:
    """Return metadata for one stored evidence package."""

    requested_package_id = _parse_package_id(package_id)
    repository: EvidenceRepository = request.app.state.repository
    package = repository.get_package(requested_package_id)
    if package is None:
        raise ContractError(
            "package_not_found",
            "The package was not found.",
            status_code=404,
        )

    manifest, manifest_payload = _read_stored_manifest(package.manifest_json)
    return PackageMetadataResponse(
        package_id=package.package_id,
        state=package.state,
        received_at=package.received_at,
        schema_version=package.schema_version,
        session=manifest.session,
        event=manifest.event,
        manifest_sha256=package.manifest_sha256,
        manifest=manifest_payload,
        frames=[
            StoredFrameResponse(
                part_name=frame.part_name,
                target_offset_ms=frame.target_offset_ms,
                actual_offset_ms=frame.actual_offset_ms,
                session_elapsed_ms=frame.session_elapsed_ms,
                captured_at_utc=frame.captured_at_utc,
                content_type=frame.content_type,
                byte_length=frame.byte_length,
                sha256=frame.sha256,
                relative_path=frame.relative_path,
            )
            for frame in package.frames
        ],
        video_snippet=manifest.video_snippet,
        video_relative_path=(
            f"evidence/{package.package_id}/video/{manifest.video_snippet.part_name}.mp4"
            if manifest.video_snippet is not None and manifest.video_snippet.capture_complete
            else None
        ),
        missing_frame_targets_ms=manifest.missing_frame_targets_ms,
    )


@router.get(
    "/v1/evidence-packages/{package_id}/video-snippet",
    response_model=None,
)
def get_evidence_video_snippet(package_id: str, request: Request) -> FileResponse:
    """Return the original bytes for one stored complete video snippet."""

    requested_package_id = _parse_package_id(package_id)
    repository: EvidenceRepository = request.app.state.repository
    package = repository.get_package(requested_package_id)
    if package is None:
        raise ContractError(
            "package_not_found",
            "The package was not found.",
            status_code=404,
        )

    manifest, _ = _read_stored_manifest(package.manifest_json)
    snippet = manifest.video_snippet
    if snippet is None or not snippet.capture_complete or snippet.part_name is None:
        raise ContractError(
            "video_snippet_not_found",
            "The package has no complete video snippet.",
            status_code=404,
        )

    video_path = request.app.state.storage.video_path(package.package_id, snippet.part_name)
    if not video_path.is_file():
        raise ContractError(
            "internal_error",
            "The stored video snippet is unavailable.",
            status_code=500,
        )
    return FileResponse(
        video_path,
        media_type=SUPPORTED_VIDEO_CONTENT_TYPE,
        headers={"ETag": f'"{snippet.sha256}"'},
    )


@router.get(
    "/v1/evidence-packages/{package_id}/vision-results",
    response_model=list[VisionDetectionResult],
)
def get_package_vision_results(package_id: str, request: Request) -> list[VisionDetectionResult]:
    """Return immutable detector results for one stored package."""

    requested_package_id = _parse_package_id(package_id)
    repository: EvidenceRepository = request.app.state.repository
    if repository.get_package(requested_package_id) is None:
        raise ContractError(
            "package_not_found",
            "The package was not found.",
            status_code=404,
        )
    return [
        _parse_stored_result(row.result_json)
        for row in repository.list_vision_results(requested_package_id)
    ]


@router.get(
    "/v1/vision-results/{result_id}",
    response_model=VisionDetectionResult,
)
def get_vision_result(result_id: str, request: Request) -> VisionDetectionResult:
    """Return one immutable detector result."""

    requested_result_id = _parse_result_id(result_id)
    repository: EvidenceRepository = request.app.state.repository
    stored_result = repository.get_vision_result(requested_result_id)
    if stored_result is None:
        raise ContractError(
            "vision_result_not_found",
            "The vision result was not found.",
            status_code=404,
        )
    return _parse_stored_result(stored_result.result_json)


def _parse_package_id(value: str) -> UUID:
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ContractError(
            "invalid_package_id",
            "The package ID is not a valid UUID.",
        ) from error


def _parse_result_id(value: str) -> UUID:
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ContractError(
            "invalid_result_id",
            "The result ID is not a valid UUID.",
        ) from error


def _parse_stored_result(result_json: str) -> VisionDetectionResult:
    try:
        return parse_result_bytes(result_json.encode("utf-8"))
    except (UnicodeEncodeError, VisionContractError) as error:
        raise ContractError(
            "internal_error",
            "The stored vision result is invalid.",
            status_code=500,
        ) from error


def _read_stored_manifest(
    manifest_json: str,
) -> tuple[EvidenceManifest, dict[str, object]]:
    try:
        manifest_bytes = manifest_json.encode("utf-8")
        manifest = parse_manifest_bytes(manifest_bytes)
        payload = json.loads(manifest_json)
    except (ContractError, UnicodeEncodeError, json.JSONDecodeError) as error:
        raise ContractError(
            "internal_error",
            "The stored package metadata is invalid.",
            status_code=500,
        ) from error
    if not isinstance(payload, dict):
        raise ContractError(
            "internal_error",
            "The stored package metadata is invalid.",
            status_code=500,
        )
    return manifest, payload


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


async def _inspect_video(
    upload: UploadFile,
    snippet: VideoSnippetManifest,
    *,
    max_video_bytes: int,
) -> tuple[int, str]:
    await upload.seek(0)
    digest = hashlib.sha256()
    byte_length = 0
    video_bytes = bytearray()
    while chunk := await upload.read(FRAME_COPY_CHUNK_BYTES):
        byte_length += len(chunk)
        if byte_length > max_video_bytes:
            raise ContractError(
                "video_too_large",
                "A video snippet exceeds the configured size limit.",
                status_code=413,
            )
        digest.update(chunk)
        video_bytes.extend(chunk)
    await upload.seek(0)

    digest_hex = digest.hexdigest()
    if byte_length != snippet.byte_length or digest_hex != snippet.sha256:
        raise ContractError(
            "hash_mismatch",
            "The video snippet bytes do not match the manifest.",
            details=[],
        )

    try:
        probe = probe_video_bytes(bytes(video_bytes))
    except UnsupportedVideoError as error:
        raise ContractError(
            "unsupported_media_type",
            "The video snippet uses unsupported media.",
            status_code=415,
        ) from error
    except VideoProbeError as error:
        raise ContractError(
            "invalid_video",
            "The video snippet could not be decoded.",
            status_code=422,
        ) from error
    except VideoProbeUnavailable as error:
        raise ContractError(
            "internal_error",
            "The video probe is not available.",
            status_code=500,
        ) from error

    if (
        probe.container != snippet.container
        or probe.video_codec != snippet.video_codec
        or probe.width != snippet.width
        or probe.height != snippet.height
        or snippet.nominal_frame_rate is None
        or not math.isclose(probe.nominal_frame_rate, snippet.nominal_frame_rate, abs_tol=0.05)
        or abs(probe.duration_ms - snippet.duration_ms) > 50
    ):
        raise ContractError(
            "invalid_video",
            "The video stream metadata does not match the manifest.",
            status_code=422,
        )
    return byte_length, digest_hex


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


__all__ = ["get_evidence_package", "router", "upload_evidence_package"]
