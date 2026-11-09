"""Durable compact active-job pages tied to the Job Manager authority."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.job_models import Job
from dokodetector_backend.recording_state_contract import (
    CompactJobMetadata,
    HistoryPageCursor,
    JobProjectionAuthority,
    RecordingJobProjection,
)

_ACTIVE = {"queued", "running", "cancelling"}
_PAGE_SIZE = 20
_FILTER_SHA256 = hashlib.sha256(b"{}").hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class JobProjectionCursorInvalid(ValueError):
    """The cursor is malformed or bound to another request."""


class JobProjectionCursorExpired(ValueError):
    """The job authority changed after the cursor was issued."""


class RecordingJobProjectionStore:
    """Store a compact active index and serve bounded, authority-pinned pages."""

    def __init__(self, jobs_root: Path) -> None:
        self.root = Path(jobs_root) / "recording-projections"
        self.projections = self.root / "recordings"
        self.key_path = self.root / "cursor-key.json"

    def page(
        self,
        recording_id: str,
        authority: JobProjectionAuthority,
        list_jobs: Callable[[], list[Job]],
        token: str | None,
    ) -> RecordingJobProjection:
        self.root.mkdir(parents=True, exist_ok=True)
        cursor = self._decode(token) if token else None
        if cursor is not None:
            if (
                cursor.recording_id != recording_id
                or cursor.collection != "jobs"
                or cursor.filter_sha256 != _FILTER_SHA256
                or cursor.page_size != _PAGE_SIZE
            ):
                raise JobProjectionCursorInvalid("cursor request binding mismatch")
            if (
                cursor.authority_epoch != authority.epoch
                or cursor.authority_sequence != authority.sequence
            ):
                raise JobProjectionCursorExpired("Job Manager authority advanced")

        path = self._projection_path(recording_id)
        document = self._read_projection(path, recording_id)
        if (
            document is None
            or document["epoch"] != authority.epoch
            or document["sequence"] != authority.sequence
        ):
            compact = [
                self._compact(job)
                for job in list_jobs()
                if job.context.get("recording_id") == recording_id and job.state in _ACTIVE
            ]
            compact.sort(key=lambda item: (item.updated_at, item.job_id), reverse=True)
            document = {
                "schema_version": "recording-active-job-index/v1",
                "recording_id": recording_id,
                "epoch": authority.epoch,
                "sequence": authority.sequence,
                "jobs": [item.model_dump(mode="json") for item in compact],
            }
            atomic_replace_json(path, document)

        jobs = [CompactJobMetadata.model_validate(item) for item in document["jobs"]]
        boundary = None
        if cursor is not None and cursor.last_key is not None:
            try:
                value = json.loads(cursor.last_key)
                if (
                    not isinstance(value, list)
                    or len(value) != 2
                    or not all(isinstance(part, str) for part in value)
                    or _canonical(value).decode() != cursor.last_key
                ):
                    raise ValueError("invalid job cursor key")
                boundary = tuple(value)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                raise JobProjectionCursorInvalid("invalid job cursor key") from error
        if boundary is not None:
            jobs = [item for item in jobs if (item.updated_at, item.job_id) < boundary]
        page = jobs[:_PAGE_SIZE]
        has_more = len(jobs) > _PAGE_SIZE
        next_cursor = None
        if has_more and page:
            next_cursor = self._encode(
                HistoryPageCursor(
                    recording_id=recording_id,
                    collection="jobs",
                    filter_sha256=_FILTER_SHA256,
                    upper_bound_sequence=authority.sequence,
                    last_key=_canonical([page[-1].updated_at, page[-1].job_id]).decode(),
                    page_size=_PAGE_SIZE,
                    authority_epoch=authority.epoch,
                    authority_sequence=authority.sequence,
                )
            )
        projection = RecordingJobProjection(
            recording_id=recording_id,
            authority_epoch=authority.epoch,
            authority_sequence=authority.sequence,
            # The contract count is the number remaining from this cursor boundary.
            active_job_count=len(jobs),
            jobs=page,
            next_cursor=next_cursor,
            has_more=has_more,
        )
        projection.validate_authority(authority)
        return projection

    def _projection_path(self, recording_id: str) -> Path:
        digest = hashlib.sha256(recording_id.encode("utf-8")).hexdigest()
        return self.projections / f"{digest}.json"

    def _read_projection(self, path: Path, recording_id: str) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError) as error:
            raise ValueError("recording job projection is corrupt") from error
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "recording_id", "epoch", "sequence", "jobs"}
            or value["schema_version"] != "recording-active-job-index/v1"
            or value["recording_id"] != recording_id
            or not isinstance(value["epoch"], str)
            or not isinstance(value["sequence"], int)
            or not isinstance(value["jobs"], list)
        ):
            raise ValueError("recording job projection is corrupt")
        jobs = [CompactJobMetadata.model_validate(item) for item in value["jobs"]]
        if any(job.status not in _ACTIVE for job in jobs):
            raise ValueError("recording job projection contains a terminal job")
        if [job.job_id for job in jobs] != list(dict.fromkeys(job.job_id for job in jobs)):
            raise ValueError("recording job projection contains duplicate jobs")
        return value

    @staticmethod
    def _compact(job: Job) -> CompactJobMetadata:
        return CompactJobMetadata(
            job_id=job.id,
            schema_version="backend-job/v1",
            status=job.state,
            updated_at=job.updated_at,
            request_id=job.correlation_id,
        )

    def _key(self) -> bytes:
        if self.key_path.exists():
            try:
                value = json.loads(self.key_path.read_bytes())
                raw = bytes.fromhex(value["key"])
                if value.get("schema_version") != "recording-job-cursor-key/v1" or len(raw) != 32:
                    raise ValueError("invalid key")
                return raw
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise ValueError("recording job cursor key is corrupt") from error
        raw = secrets.token_bytes(32)
        atomic_replace_json(
            self.key_path,
            {"schema_version": "recording-job-cursor-key/v1", "key": raw.hex()},
        )
        return raw

    def _encode(self, cursor: HistoryPageCursor) -> str:
        payload = _canonical(cursor.model_dump(mode="json"))
        signature = hmac.new(self._key(), payload, hashlib.sha256).digest()
        return f"{_b64(payload)}.{_b64(signature)}"

    def _decode(self, token: str) -> HistoryPageCursor:
        try:
            payload_text, signature_text = token.split(".", 1)
            payload = base64.urlsafe_b64decode(payload_text + "=" * (-len(payload_text) % 4))
            signature = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
            if not hmac.compare_digest(
                signature, hmac.new(self._key(), payload, hashlib.sha256).digest()
            ):
                raise ValueError("signature mismatch")
            value = json.loads(payload)
            if not isinstance(value, dict) or _canonical(value) != payload:
                raise ValueError("cursor is not canonical")
            return HistoryPageCursor.model_validate(value)
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as error:
            raise JobProjectionCursorInvalid("invalid job cursor") from error
