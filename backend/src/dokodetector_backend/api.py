"""HTTP routes for the evidence upload contract."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException
from table_evidence_analyzer import ContractError as TableObservationContractError
from table_evidence_analyzer import TableObservation, parse_observation_bytes

from dokodetector_backend.config import Settings
from dokodetector_backend.contract import (
    SUPPORTED_VIDEO_CONTENT_TYPE,
    EvidenceManifest,
    PackageMetadataResponse,
    StoredFrameResponse,
    UploadResponse,
    VideoSnippetManifest,
    parse_manifest_bytes,
    validate_package_id,
)
from dokodetector_backend.errors import APIErrorDetail, ContractError
from dokodetector_backend.evidence_package_storage import (
    calculate_bundle_fingerprint,
)
from dokodetector_backend.intake_contract import (
    IntakeContractError,
    parse_evidence_package_lineage,
    parse_evidence_package_record,
    parse_task_enrollment,
    validate_evidence_package_bundle,
)
from dokodetector_backend.logging_config import get_or_create_request_id, log_event
from dokodetector_backend.repository import (
    EvidenceRepository,
    LogicalEventConflict,
    PackageConflict,
    RepositoryError,
    StoredFrame,
    StoredPackage,
)
from dokodetector_backend.repository_bundle_storage import StoredRepositoryFile
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
VIDEO_FRAME_RATE_WARNING_TOLERANCE_FPS = 0.05
VIDEO_DURATION_TOLERANCE_MS = 50
LOGGER = logging.getLogger(__name__)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
            max_part_size=max(
                settings.max_manifest_bytes,
                settings.max_frame_bytes,
                settings.max_video_bytes,
            ),
        ) as form:
            (
                manifest_upload,
                package_record_upload,
                task_enrollment_upload,
                lineage_upload,
                frame_uploads,
            ) = _collect_uploads(form)
            _require_media_type(manifest_upload, MANIFEST_MEDIA_TYPE, field="manifest")
            for field, upload in (
                ("package_record", package_record_upload),
                ("task_enrollment", task_enrollment_upload),
                ("lineage", lineage_upload),
            ):
                _require_media_type(upload, MANIFEST_MEDIA_TYPE, field=field)

            manifest_bytes = await _read_upload(manifest_upload, settings.max_manifest_bytes)
            package_record_bytes = await _read_upload(
                package_record_upload, settings.max_manifest_bytes
            )
            task_enrollment_bytes = await _read_upload(
                task_enrollment_upload, settings.max_manifest_bytes
            )
            lineage_bytes = await _read_upload(lineage_upload, settings.max_manifest_bytes)
            manifest = parse_manifest_bytes(
                manifest_bytes,
                max_bytes=settings.max_manifest_bytes,
            )
            validate_package_id(requested_package_id, manifest)
            try:
                package_record = parse_evidence_package_record(package_record_bytes)
                parse_task_enrollment(task_enrollment_bytes)
                parse_evidence_package_lineage(lineage_bytes)
            except IntakeContractError as error:
                raise ContractError(
                    "invalid_request",
                    "The evidence package intake documents failed validation.",
                    status_code=422,
                ) from error
            if package_record.package_id != str(manifest.package_id):
                raise ContractError(
                    "invalid_request",
                    "The package record does not match the evidence manifest package ID.",
                    status_code=422,
                )
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
                        details=[
                            APIErrorDetail(
                                field="video_snippet.part_name",
                                message=f"missing multipart part {video_part_name!r}.",
                            )
                        ],
                    )
            _validate_frame_parts(manifest, frame_uploads)

            frame_sources: dict[str, bytes] = {}
            member_files: dict[str, bytes] = {
                "evidence-manifest.json": manifest_bytes,
                "package-record.json": package_record_bytes,
                "initial-task-enrollment.json": task_enrollment_bytes,
                "lineage.json": lineage_bytes,
            }
            package_bytes = sum(len(value) for value in member_files.values())
            for frame in manifest.frames:
                upload = frame_uploads[frame.part_name]
                _require_media_type(
                    upload,
                    SUPPORTED_FRAME_MEDIA_TYPE,
                    field=f"frames.{frame.part_name}",
                )
                frame_bytes, byte_length, digest = await _inspect_frame(
                    upload,
                    max_frame_bytes=settings.max_frame_bytes,
                )
                frame_sources[frame.part_name] = frame_bytes
                member_files[f"frames/{frame.part_name}.jpg"] = frame_bytes
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
                        details=[
                            APIErrorDetail(
                                field=f"frames.{frame.part_name}",
                                message=(
                                    f"manifest byte_length={frame.byte_length}, received "
                                    f"byte_length={byte_length}; manifest sha256={frame.sha256}, "
                                    f"received sha256={digest}."
                                ),
                            )
                        ],
                    )

            if manifest.video_snippet is not None and manifest.video_snippet.capture_complete:
                assert video_upload is not None
                _require_media_type(
                    video_upload,
                    SUPPORTED_VIDEO_CONTENT_TYPE,
                    field="video_snippet",
                )
                video_bytes, video_length, video_digest = await _inspect_video(
                    video_upload,
                    manifest.video_snippet,
                    max_video_bytes=settings.max_video_bytes,
                    package_id=str(manifest.package_id),
                    request_id=get_or_create_request_id(request),
                    upload_id=request.headers.get("x-dokodetector-upload-id") or "-",
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
                        details=[
                            APIErrorDetail(
                                field="video_snippet",
                                message=(
                                    f"manifest byte_length={manifest.video_snippet.byte_length}, "
                                    f"received byte_length={video_length}; "
                                    f"manifest sha256={manifest.video_snippet.sha256}, "
                                    f"received sha256={video_digest}."
                                ),
                            )
                        ],
                    )

                assert manifest.video_snippet.part_name is not None
                member_files[f"video/{manifest.video_snippet.part_name}.mp4"] = video_bytes

            bundle_manifest_bytes = _build_evidence_package_bundle(
                package_id=manifest.package_id,
                source_asset_id=package_record.source_asset_id,
                manifest_bytes=manifest_bytes,
                package_record_bytes=package_record_bytes,
                task_enrollment_bytes=task_enrollment_bytes,
                lineage_bytes=lineage_bytes,
                manifest=manifest,
                frame_sources=frame_sources,
                video_bytes=(
                    video_bytes
                    if manifest.video_snippet is not None
                    and manifest.video_snippet.capture_complete
                    else None
                ),
            )
            member_files_with_bundle = {"manifest.json": bundle_manifest_bytes, **member_files}
            try:
                validate_evidence_package_bundle(
                    bundle_manifest_bytes,
                    manifest_bytes,
                    package_record_bytes,
                    task_enrollment_bytes,
                    lineage_bytes,
                    member_files,
                )
            except IntakeContractError as error:
                raise ContractError(
                    "invalid_request",
                    "The evidence package intake documents are inconsistent.",
                    status_code=422,
                ) from error
            package_bytes = sum(len(value) for value in member_files_with_bundle.values())
            if package_bytes > settings.max_package_bytes:
                raise ContractError(
                    "package_too_large",
                    "The package exceeds the configured size limit.",
                    status_code=413,
                )

            log_event(
                LOGGER,
                logging.DEBUG,
                "evidence_package_validation_completed",
                request_id=get_or_create_request_id(request),
                upload_id=request.headers.get("x-dokodetector-upload-id") or "-",
                package_id=str(manifest.package_id),
                frame_count=len(manifest.frames),
                package_bytes=package_bytes,
            )

            fingerprint = calculate_bundle_fingerprint(
                {
                    path: StoredRepositoryFile(path, len(value), _sha256(value))
                    for path, value in member_files_with_bundle.items()
                }
            )
            repository: EvidenceRepository = request.app.state.repository
            existing = repository.get_package(manifest.package_id)
            if existing is not None:
                if existing.package_fingerprint == fingerprint:
                    _log_evidence_package_stored(
                        request,
                        existing,
                        manifest=manifest,
                        created=False,
                    )
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
                        relative_path=f"frames/{frame.part_name}.jpg",
                    )
                    for frame in manifest.frames
                ),
                received_at=datetime.now(timezone.utc),
            )
            try:
                stored = request.app.state.persister.persist(
                    package,
                    evidence_manifest_source=manifest_bytes,
                    package_record_source=package_record_bytes,
                    task_enrollment_source=task_enrollment_bytes,
                    lineage_source=lineage_bytes,
                    bundle_manifest_source=bundle_manifest_bytes,
                    frame_sources=frame_sources,
                    video_source=(
                        video_bytes
                        if manifest.video_snippet is not None
                        and manifest.video_snippet.capture_complete
                        else None
                    ),
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
                resolved = _resolve_package_conflict(repository, manifest.package_id, fingerprint)
                existing = repository.get_package(manifest.package_id)
                if existing is not None:
                    _log_evidence_package_stored(
                        request,
                        existing,
                        manifest=manifest,
                        created=False,
                    )
                return resolved
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

            _log_evidence_package_stored(
                request,
                stored,
                manifest=manifest,
                created=True,
            )
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
            f"video/{manifest.video_snippet.part_name}.mp4"
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

    video_path = (
        request.app.state.evidence_package_storage.package_path(package.package_id)
        / f"video/{snippet.part_name}.mp4"
    )
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
    "/v1/evidence-packages/{package_id}/table-observations",
    response_model=list[TableObservation],
)
def get_package_table_observations(package_id: str, request: Request) -> list[TableObservation]:
    """Return immutable table observations for one stored package."""

    requested_package_id = _parse_package_id(package_id)
    repository: EvidenceRepository = request.app.state.repository
    if repository.get_package(requested_package_id) is None:
        raise ContractError(
            "package_not_found",
            "The package was not found.",
            status_code=404,
        )
    return [
        _parse_stored_observation(row.observation_json)
        for row in repository.list_table_observations(requested_package_id)
    ]


@router.get(
    "/v1/table-observations/{observation_id}",
    response_model=TableObservation,
)
def get_table_observation(observation_id: str, request: Request) -> TableObservation:
    """Return one immutable table observation."""

    repository: EvidenceRepository = request.app.state.repository
    stored_observation = repository.get_table_observation(observation_id)
    if stored_observation is None:
        raise ContractError(
            "table_observation_not_found",
            "The table observation was not found.",
            status_code=404,
        )
    return _parse_stored_observation(stored_observation.observation_json)


def _parse_package_id(value: str) -> UUID:
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ContractError(
            "invalid_package_id",
            "The package ID is not a valid UUID.",
        ) from error


def _parse_stored_observation(observation_json: str) -> TableObservation:
    try:
        return parse_observation_bytes(observation_json.encode("utf-8"))
    except (UnicodeEncodeError, TableObservationContractError) as error:
        raise ContractError(
            "internal_error",
            "The stored table observation is invalid.",
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


def _collect_uploads(
    form: FormData,
) -> tuple[UploadFile, UploadFile, UploadFile, UploadFile, dict[str, UploadFile]]:
    required_names = {"manifest", "package_record", "task_enrollment", "lineage"}
    fixed_parts: dict[str, UploadFile] = {}
    frame_parts: dict[str, UploadFile] = {}
    for name, value in form.multi_items():
        if not isinstance(value, UploadFile):
            raise ContractError(
                "invalid_request",
                "Every multipart part must be a file part.",
                status_code=400,
            )
        if name in required_names:
            if name in fixed_parts:
                raise ContractError(
                    "invalid_request",
                    "Multipart part names must be unique.",
                    status_code=400,
                )
            fixed_parts[name] = value
            continue
        if name in frame_parts:
            raise ContractError(
                "invalid_request",
                "Multipart part names must be unique.",
                status_code=400,
            )
        frame_parts[name] = value

    missing_names = sorted(required_names - set(fixed_parts))
    if missing_names:
        raise ContractError(
            "invalid_request",
            "The request is missing one or more intake documents.",
            status_code=400,
            details=[
                APIErrorDetail(
                    field="multipart",
                    message=f"missing multipart parts: {', '.join(missing_names)}.",
                )
            ],
        )
    return (
        fixed_parts["manifest"],
        fixed_parts["package_record"],
        fixed_parts["task_enrollment"],
        fixed_parts["lineage"],
        frame_parts,
    )


def _validate_frame_parts(manifest: EvidenceManifest, frame_uploads: dict[str, UploadFile]) -> None:
    declared_names = {frame.part_name for frame in manifest.frames}
    received_names = set(frame_uploads)
    missing_names = sorted(declared_names - received_names)
    extra_names = sorted(received_names - declared_names)
    if missing_names:
        raise ContractError(
            "invalid_request",
            "A declared frame part is missing.",
            status_code=400,
            details=[
                APIErrorDetail(
                    field="frames",
                    message=f"missing multipart parts: {', '.join(missing_names)}.",
                )
            ],
        )
    if extra_names:
        raise ContractError(
            "invalid_request",
            "The request contains an undeclared frame part.",
            status_code=400,
            details=[
                APIErrorDetail(
                    field="frames",
                    message=f"undeclared multipart parts: {', '.join(extra_names)}.",
                )
            ],
        )


def _require_media_type(upload: UploadFile, expected: str, *, field: str) -> None:
    actual = _media_type(upload.content_type)
    if actual != expected:
        raise ContractError(
            "unsupported_media_type",
            f"The multipart part must use {expected}.",
            status_code=415,
            details=[
                APIErrorDetail(
                    field=field,
                    message=f"received {actual or '<missing>'}; expected {expected}.",
                )
            ],
        )


def _media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


async def _inspect_frame(upload: UploadFile, *, max_frame_bytes: int) -> tuple[bytes, int, str]:
    await upload.seek(0)
    digest = hashlib.sha256()
    content = bytearray()
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
        content.extend(chunk)
    await upload.seek(0)
    return bytes(content), byte_length, digest.hexdigest()


async def _inspect_video(
    upload: UploadFile,
    snippet: VideoSnippetManifest,
    *,
    max_video_bytes: int,
    package_id: str,
    request_id: str,
    upload_id: str,
) -> tuple[bytes, int, str]:
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
            details=[
                APIErrorDetail(
                    field="video_snippet",
                    message=(
                        f"manifest byte_length={snippet.byte_length}, received "
                        f"byte_length={byte_length}; manifest sha256={snippet.sha256}, "
                        f"received sha256={digest_hex}."
                    ),
                )
            ],
        )

    try:
        probe = probe_video_bytes(bytes(video_bytes))
    except UnsupportedVideoError as error:
        raise ContractError(
            "unsupported_media_type",
            "The video snippet uses unsupported media.",
            status_code=415,
            details=[APIErrorDetail(field="video_snippet", message=str(error))],
        ) from error
    except VideoProbeError as error:
        raise ContractError(
            "invalid_video",
            "The video snippet could not be decoded.",
            status_code=422,
            details=[APIErrorDetail(field="video_snippet", message=str(error))],
        ) from error
    except VideoProbeUnavailable as error:
        raise ContractError(
            "internal_error",
            "The video probe is not available.",
            status_code=500,
            details=[APIErrorDetail(field="video_snippet", message=str(error))],
        ) from error

    mismatches: list[APIErrorDetail] = []
    for field, expected, actual in (
        ("container", snippet.container, probe.container),
        ("video_codec", snippet.video_codec, probe.video_codec),
        ("width", snippet.width, probe.width),
        ("height", snippet.height, probe.height),
    ):
        if expected != actual:
            mismatches.append(
                APIErrorDetail(
                    field=f"video_snippet.{field}",
                    message=f"manifest={expected!r}; actual={actual!r}.",
                )
            )

    if snippet.nominal_frame_rate is not None and not math.isclose(
        probe.nominal_frame_rate,
        snippet.nominal_frame_rate,
        abs_tol=VIDEO_FRAME_RATE_WARNING_TOLERANCE_FPS,
    ):
        log_event(
            LOGGER,
            logging.WARNING,
            "video_frame_rate_mismatch",
            request_id=request_id,
            upload_id=upload_id,
            package_id=package_id,
            manifest_frame_rate=snippet.nominal_frame_rate,
            actual_frame_rate=probe.nominal_frame_rate,
            difference_fps=abs(probe.nominal_frame_rate - snippet.nominal_frame_rate),
            tolerance_fps=VIDEO_FRAME_RATE_WARNING_TOLERANCE_FPS,
        )

    if abs(probe.duration_ms - snippet.duration_ms) > VIDEO_DURATION_TOLERANCE_MS:
        mismatches.append(
            APIErrorDetail(
                field="video_snippet.duration_ms",
                message=(
                    f"manifest={snippet.duration_ms!r}; actual={probe.duration_ms!r}; "
                    f"tolerance={VIDEO_DURATION_TOLERANCE_MS!r} ms."
                ),
            )
        )

    if mismatches:
        raise ContractError(
            "invalid_video",
            "The video stream metadata does not match the manifest.",
            status_code=422,
            details=mismatches,
        )
    return bytes(video_bytes), byte_length, digest_hex


async def _read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """Read one bounded JSON multipart part."""

    content = await upload.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ContractError(
            "manifest_too_large",
            "An intake document exceeds the configured size limit.",
            status_code=413,
        )
    return content


def _build_evidence_package_bundle(
    *,
    package_id: UUID,
    source_asset_id: str,
    manifest_bytes: bytes,
    package_record_bytes: bytes,
    task_enrollment_bytes: bytes,
    lineage_bytes: bytes,
    manifest: EvidenceManifest,
    frame_sources: dict[str, bytes],
    video_bytes: bytes | None,
) -> bytes:
    """Build the canonical repository manifest from the accepted upload members."""

    def descriptor(relative_path: str, media_type: str, value: bytes) -> dict[str, object]:
        return {
            "relative_path": relative_path,
            "type": media_type,
            "byte_length": len(value),
            "sha256": _sha256(value),
        }

    payload: dict[str, object] = {
        "schema_version": "evidence-package-bundle/v1",
        "package_id": str(package_id),
        "source_asset_id": source_asset_id,
        "state": "complete",
        "files": {
            "evidence_manifest": descriptor(
                "evidence-manifest.json", MANIFEST_MEDIA_TYPE, manifest_bytes
            ),
            "package_record": descriptor(
                "package-record.json", MANIFEST_MEDIA_TYPE, package_record_bytes
            ),
            "task_enrollment": descriptor(
                "initial-task-enrollment.json", MANIFEST_MEDIA_TYPE, task_enrollment_bytes
            ),
            "lineage": descriptor("lineage.json", MANIFEST_MEDIA_TYPE, lineage_bytes),
            "frames": [
                descriptor(
                    f"frames/{frame.part_name}.jpg",
                    SUPPORTED_FRAME_MEDIA_TYPE,
                    frame_sources[frame.part_name],
                )
                for frame in manifest.frames
            ],
            "video_snippet": (
                descriptor(
                    f"video/{manifest.video_snippet.part_name}.mp4",
                    SUPPORTED_VIDEO_CONTENT_TYPE,
                    video_bytes,
                )
                if video_bytes is not None
                and manifest.video_snippet is not None
                and manifest.video_snippet.part_name is not None
                else None
            ),
        },
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


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


def _log_evidence_package_stored(
    request: Request,
    package: StoredPackage,
    *,
    manifest: EvidenceManifest,
    created: bool,
) -> None:
    """Log one accepted evidence-package request without logging its content."""

    log_event(
        LOGGER,
        logging.INFO,
        "evidence_package_stored",
        request_id=get_or_create_request_id(request),
        upload_id=request.headers.get("x-dokodetector-upload-id") or "-",
        package_id=str(package.package_id),
        created=created,
        frame_count=len(package.frames),
        video_snippet_complete=(
            manifest.video_snippet is not None and manifest.video_snippet.capture_complete
        ),
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
