"""HTTP routes for bounded pending-video intake."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePath

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from dokodetector_backend.config import Settings
from dokodetector_backend.errors import ContractError
from dokodetector_backend.intake_contract import IntakeContractError, PendingVideo
from dokodetector_backend.logging_config import get_or_create_request_id, log_event
from dokodetector_backend.pending_video_storage import (
    PendingVideoStorage,
    StoredPendingVideo,
)
from dokodetector_backend.storage import StorageLimitError
from dokodetector_backend.video_probe import (
    UnsupportedVideoError,
    VideoProbeError,
    VideoProbeUnavailable,
    probe_video_path,
)

JSON_MEDIA_TYPE = "application/json"
MULTIPART_MEDIA_TYPE = "multipart/form-data"
SUPPORTED_VIDEO_MEDIA_TYPES = {"video/quicktime", "video/mp4"}
LOGGER = logging.getLogger(__name__)

router = APIRouter()


class PendingVideoUploadResponse(BaseModel):
    """Response returned after a pending video receipt is published."""

    model_config = ConfigDict(extra="forbid")

    upload_id: str
    state: str
    created: bool
    received_at_utc: str
    original_filename: str
    byte_length: int = Field(gt=0)
    sha256: str
    media_facts: dict[str, int | float | str]


@router.put(
    "/v1/pending-videos/{upload_id}",
    response_model=PendingVideoUploadResponse,
    status_code=201,
)
async def upload_pending_video(
    upload_id: str, request: Request, response: Response
) -> PendingVideoUploadResponse:
    """Stream, probe, and atomically publish one pending raw video."""

    settings: Settings = request.app.state.settings
    storage: PendingVideoStorage = request.app.state.pending_video_storage
    try:
        async with _collect_upload(request, settings) as upload:
            filename = _filename(upload)
            media_type = _media_type(upload.content_type)
            _validate_video_name(filename, media_type)

            with storage.start_upload(upload_id) as staged:
                await upload.seek(0)
                try:
                    stored = staged.write_video(
                        filename,
                        upload.file,
                        max_bytes=settings.max_pending_video_bytes,
                    )
                finally:
                    await upload.seek(0)
                facts = probe_video_path(staged.temporary_path / filename)
                log_event(
                    LOGGER,
                    logging.DEBUG,
                    "pending_video_validation_completed",
                    request_id=get_or_create_request_id(request),
                    upload_id=upload_id,
                    media_type=media_type,
                    byte_length=stored.byte_length,
                )
                receipt = _build_receipt(
                    upload_id=upload_id,
                    stored=stored,
                    media_type=media_type,
                    facts=facts,
                )
                receipt_bytes = _receipt_bytes(receipt)
                staged.write_receipt(receipt_bytes)
                try:
                    staged.commit()
                except FileExistsError:
                    retry_response = _retry_response(
                        storage,
                        upload_id=upload_id,
                        incoming=receipt,
                        response=response,
                    )
                    _log_pending_video_stored(request, receipt, created=False)
                    _log_pending_video_publication_completed(request, receipt, created=False)
                    return retry_response
                _log_pending_video_publication_completed(request, receipt, created=True)
                stored_response = _response(receipt)
                _log_pending_video_stored(request, receipt, created=True)
                return stored_response
    except MultiPartException as error:
        raise ContractError(
            "pending_video_request_too_large",
            "The pending video request exceeds the configured size limit.",
            status_code=413,
        ) from error
    except StorageLimitError as error:
        raise ContractError(
            "pending_video_too_large",
            "The pending video exceeds the configured size limit.",
            status_code=413,
        ) from error
    except (UnsupportedVideoError, VideoProbeError, VideoProbeUnavailable) as error:
        raise ContractError("pending_video_invalid", str(error), status_code=422) from error
    except ContractError:
        raise
    except (IntakeContractError, OSError, ValueError) as error:
        raise ContractError("pending_video_invalid", str(error), status_code=422) from error


@router.get(
    "/v1/pending-videos/{upload_id}",
    response_model=PendingVideoUploadResponse,
)
def get_pending_video(upload_id: str, request: Request) -> PendingVideoUploadResponse:
    """Return the durable receipt for one pending video."""

    storage: PendingVideoStorage = request.app.state.pending_video_storage
    try:
        receipt = _read_receipt(storage, upload_id)
    except (IntakeContractError, OSError, ValueError) as error:
        raise ContractError(
            "pending_video_not_found", "The pending video was not found.", status_code=404
        ) from error
    return _response(receipt)


@asynccontextmanager
async def _collect_upload(request: Request, settings: Settings):
    if _media_type(request.headers.get("content-type")) != MULTIPART_MEDIA_TYPE:
        raise ContractError(
            "invalid_request",
            "The request must use multipart/form-data.",
            status_code=400,
        )
    async with request.form(
        max_files=1,
        max_fields=0,
        max_part_size=settings.max_pending_video_bytes,
    ) as form:
        uploads: list[UploadFile] = []
        for name, value in form.multi_items():
            if name != "video" or not isinstance(value, UploadFile):
                raise ContractError(
                    "invalid_request",
                    "The request must contain one video file part.",
                    status_code=400,
                )
            uploads.append(value)
        if len(uploads) != 1:
            raise ContractError(
                "invalid_request",
                "The request must contain one video file part.",
                status_code=400,
            )
        _require_media_type(uploads[0])
        yield uploads[0]


def _build_receipt(
    *, upload_id: str, stored: StoredPendingVideo, media_type: str, facts
) -> PendingVideo:
    received_at = (
        datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )
    return PendingVideo.model_validate(
        {
            "schema_version": "pending-video/v1",
            "upload_id": upload_id,
            "state": "pending",
            "original_filename": stored.filename,
            "byte_length": stored.byte_length,
            "sha256": stored.sha256,
            "media_type": media_type,
            "received_at_utc": received_at,
            "media_facts": {
                "container": facts.container,
                "video_codec": facts.video_codec,
                "width": facts.width,
                "height": facts.height,
                "nominal_frame_rate": facts.nominal_frame_rate,
                "duration_ms": facts.duration_ms,
                "frame_count": facts.frame_count,
            },
        }
    )


def _read_receipt(storage: PendingVideoStorage, upload_id: str) -> PendingVideo:
    receipt = PendingVideo.model_validate_json(storage.read_receipt(upload_id))
    video_path = storage.upload_path(upload_id) / receipt.original_filename
    if not video_path.is_file():
        raise IntakeContractError("pending video bytes are missing")
    if (
        video_path.stat().st_size != receipt.byte_length
        or _sha256_file(video_path) != receipt.sha256
    ):
        raise IntakeContractError("pending video bytes do not match the receipt")
    return receipt


def _retry_response(
    storage: PendingVideoStorage,
    *,
    upload_id: str,
    incoming: PendingVideo,
    response: Response,
) -> PendingVideoUploadResponse:
    receipt = _read_receipt(storage, upload_id)
    if (
        receipt.original_filename != incoming.original_filename
        or receipt.media_type != incoming.media_type
        or receipt.byte_length != incoming.byte_length
        or receipt.sha256 != incoming.sha256
    ):
        raise ContractError(
            "pending_video_conflict",
            "The upload ID is already stored with different content.",
            status_code=409,
        )
    response.status_code = 200
    return PendingVideoUploadResponse(**_response_payload(receipt), created=False)


def _response(receipt: PendingVideo) -> PendingVideoUploadResponse:
    return PendingVideoUploadResponse(**_response_payload(receipt), created=True)


def _response_payload(receipt: PendingVideo) -> dict[str, object]:
    return {
        "upload_id": receipt.upload_id,
        "state": receipt.state,
        "received_at_utc": receipt.received_at_utc,
        "original_filename": receipt.original_filename,
        "byte_length": receipt.byte_length,
        "sha256": receipt.sha256,
        "media_facts": receipt.media_facts.model_dump(),
    }


def _log_pending_video_stored(
    request: Request,
    receipt: PendingVideo,
    *,
    created: bool,
) -> None:
    """Log one accepted pending-video receipt without logging video content."""

    log_event(
        LOGGER,
        logging.INFO,
        "pending_video_stored",
        request_id=get_or_create_request_id(request),
        upload_id=receipt.upload_id,
        state=receipt.state,
        created=created,
        media_type=receipt.media_type,
        byte_length=receipt.byte_length,
        sha256=receipt.sha256,
    )


def _log_pending_video_publication_completed(
    request: Request,
    receipt: PendingVideo,
    *,
    created: bool,
) -> None:
    """Log the completion of pending-video directory publication at DEBUG."""

    log_event(
        LOGGER,
        logging.DEBUG,
        "pending_video_publication_completed",
        request_id=get_or_create_request_id(request),
        upload_id=receipt.upload_id,
        created=created,
    )


def _receipt_bytes(receipt: PendingVideo) -> bytes:
    return (json.dumps(receipt.model_dump(), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _filename(upload: UploadFile) -> str:
    return upload.filename or ""


def _validate_video_name(filename: str, media_type: str) -> None:
    if not filename or PurePath(filename).name != filename or PurePath(filename).is_absolute():
        raise ContractError("invalid_request", "The video filename is invalid.", status_code=400)
    if media_type == "video/quicktime" and not filename.endswith(".mov"):
        raise ContractError(
            "invalid_request", "QuickTime videos must use a .mov filename.", status_code=400
        )
    if media_type == "video/mp4" and not filename.endswith(".mp4"):
        raise ContractError(
            "invalid_request", "MP4 videos must use a .mp4 filename.", status_code=400
        )


def _require_media_type(upload: UploadFile) -> None:
    if _media_type(upload.content_type) not in SUPPORTED_VIDEO_MEDIA_TYPES:
        raise ContractError(
            "invalid_request",
            "The video part must use video/quicktime or video/mp4.",
            status_code=400,
        )


def _media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["router"]
