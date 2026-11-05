"""Global durable job management HTTP API."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from dokodetector_backend.errors import APIErrorDetail, ContractError
from dokodetector_backend.job_scheduler import Claims, JobScheduler, QueueRevisionConflict
from dokodetector_backend.job_store import (
    FakeParticipant,
    Job,
    JobConflict,
    JobLogEntry,
    JobManager,
    JobNotFound,
    JobOwnershipError,
    JobStateError,
    JobStorageError,
    Queue,
    State,
    Step,
)


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EnqueueBody(APIModel):
    type: str = Field(min_length=1)
    context: dict[str, Any]
    request: dict[str, Any]


class QueueMoveBody(APIModel):
    group_id: str
    before_group_id: str | None
    expected_revision: int = Field(ge=0)


class EmptyBody(APIModel):
    pass


class JobCapabilities(APIModel):
    allowed: bool
    reason: str | None = None


class Capabilities(APIModel):
    cancel: JobCapabilities
    retry: JobCapabilities
    reorder: JobCapabilities


class JobDetail(APIModel):
    schema_version: Literal["backend-job/v1"]
    id: str
    type: str
    label: str
    context: dict[str, Any]
    request: dict[str, Any]
    idempotency_key: str
    request_hash: str
    state: Literal[
        "queued",
        "running",
        "waiting",
        "cancelling",
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
    ]
    revision: int
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    parent_id: str | None
    parent_step_id: str | None
    retry_of: str | None
    steps: list[Step]
    inputs: list[dict[str, Any]]
    results: list[dict[str, Any]]
    failure: dict[str, Any] | None
    implementation: dict[str, Any]
    creator: str | None
    correlation_id: str | None
    worker_owner: str | None
    phase: str | None
    waiting_reason: str | None
    warnings: list[dict[str, Any]]
    coverage: dict[str, Any] | None
    capabilities: Capabilities


class QueueGroupResponse(APIModel):
    group_id: str
    child_job_ids: list[str]


class QueueMoveResponse(APIModel):
    revision: int
    groups: list[QueueGroupResponse]


class JobListResponse(APIModel):
    items: list[JobDetail]
    next_cursor: str | None
    queue_revision: int
    groups: list[QueueGroupResponse]


class JobLogPage(APIModel):
    entries: list[JobLogEntry]
    next_after: int
    truncated_before: int


class JobTypeRegistry:
    """Closed request registry used by job acceptance."""

    def __init__(self, root: Path) -> None:
        self._participant = FakeParticipant(root / "job-domain")
        self._validators: dict[str, Callable[[dict[str, Any]], None]] = {}

    def register_fake(self, name: Literal["fake", "automated_pipeline"] = "fake") -> None:
        """Register one closed fake request type for API fixtures."""
        self._validators[name] = self._validate_fake

    @staticmethod
    def _validate_fake(request: dict[str, Any]) -> None:
        if (
            set(request["context"]) != {"recording_id"}
            or not isinstance(request["context"]["recording_id"], str)
            or set(request["request"]) != {"input"}
            or not isinstance(request["request"]["input"], str)
        ):
            raise ValueError("invalid fake job request")

    def require(self, job_type: str) -> None:
        if job_type not in self._validators:
            raise ContractError("unknown_job_type", "The job type is not registered.")

    def validate(self, request: dict[str, Any]) -> None:
        job_type = request.get("type")
        if not isinstance(job_type, str) or job_type not in self._validators:
            raise ValueError("unknown job type")
        self._validators[job_type](request)
        self._participant.validate(request)

    def prepare(
        self,
        job_id: str,
        request: dict[str, Any],
        after_write: Callable[[str], None],
    ) -> None:
        self._participant.prepare(job_id, request, after_write)

    def verify(self, job_id: str, request: dict[str, Any]) -> bool:
        return self._participant.verify(job_id, request)


class JobManagerService:
    """Keep one manager owner for the application lifetime."""

    def __init__(self, operations_root: Path, registry: JobTypeRegistry) -> None:
        self.operations_root = operations_root
        self.registry = registry
        self.manager: JobManager | None = None

    async def start(self) -> None:
        self.manager = JobManager(self.operations_root, self.registry).__enter__()

    async def stop(self) -> None:
        if self.manager is not None:
            self.manager.__exit__(None, None, None)
            self.manager = None

    def get_manager(self) -> JobManager:
        if self.manager is None:
            raise JobOwnershipError("job manager is not available")
        return self.manager


router = APIRouter(prefix="/api/jobs", tags=["jobs"])
_ACTIVE_STATES = {"queued", "running", "waiting", "cancelling"}
_TERMINAL_STATES = {"succeeded", "failed", "cancelled", "interrupted"}


@router.post("", response_model=JobDetail, status_code=202)
def enqueue_job(
    body: EnqueueBody,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> JSONResponse:
    manager = _manager(request)
    registry: JobTypeRegistry = request.app.state.job_type_registry
    registry.require(body.type)
    try:
        job = manager.accept(
            idempotency_key,
            {"type": body.type, "context": body.context, "request": body.request},
        )
    except Exception as error:
        _raise_job_error(error)
    return JSONResponse(
        status_code=202,
        headers={"Location": f"/api/jobs/{job.id}"},
        content=_detail(job, manager.queue()).model_dump(mode="json"),
    )


@router.get("", response_model=JobListResponse)
def list_jobs(
    request: Request,
    state: State | None = None,
    type: str | None = None,
    recording_id: str | None = None,
    parent_id: str | None = None,
    scope: Literal["active", "history", "all"] = "active",
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> JobListResponse:
    manager = _manager(request)
    filters = {
        "state": state,
        "type": type,
        "recording_id": recording_id,
        "parent_id": parent_id,
        "scope": scope,
    }
    boundary = _decode_cursor(cursor, filters) if cursor else None
    jobs = [job for job in manager.list_jobs() if _matches(job, filters)]
    jobs.sort(key=lambda job: (job.created_at, job.id), reverse=True)
    if boundary is not None:
        jobs = [job for job in jobs if (job.created_at, job.id) < boundary]
    page = jobs[:limit]
    next_cursor = None
    if len(jobs) > limit and page:
        next_cursor = _encode_cursor(filters, page[-1])
    queue = manager.queue()
    return JobListResponse(
        items=[_detail(job, queue) for job in page],
        next_cursor=next_cursor,
        queue_revision=queue.revision,
        groups=[QueueGroupResponse.model_validate(group.model_dump()) for group in queue.groups],
    )


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: str, request: Request) -> JobDetail:
    manager = _manager(request)
    try:
        return _detail(manager.get(job_id), manager.queue())
    except Exception as error:
        _raise_job_error(error)


@router.post("/{job_id}/cancel", response_model=JobDetail)
def cancel_job(job_id: str, request: Request, body: EmptyBody) -> JobDetail:
    del body
    manager = _manager(request)
    try:
        job = manager.cancel(job_id)
        return _detail(job, manager.queue())
    except Exception as error:
        _raise_job_error(error)


@router.post("/{job_id}/retry", response_model=JobDetail, status_code=202)
def retry_job(
    job_id: str,
    request: Request,
    body: EmptyBody,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> JSONResponse:
    del body
    manager = _manager(request)
    try:
        job = manager.retry(job_id, idempotency_key)
        return JSONResponse(
            status_code=202,
            headers={"Location": f"/api/jobs/{job.id}"},
            content=_detail(job, manager.queue()).model_dump(mode="json"),
        )
    except JobStateError as error:
        raise ContractError("retry_not_supported", str(error), status_code=409) from error
    except Exception as error:
        _raise_job_error(error)


@router.post("/queue/move", response_model=QueueMoveResponse)
def move_job(body: QueueMoveBody, request: Request) -> QueueMoveResponse:
    manager = _manager(request)
    scheduler = JobScheduler(manager, lambda _job, _claims, _token: None, lambda _job: Claims())
    try:
        queue = scheduler.move(body.group_id, body.before_group_id, body.expected_revision)
        return QueueMoveResponse(
            revision=queue.revision,
            groups=[QueueGroupResponse.model_validate(item.model_dump()) for item in queue.groups],
        )
    except QueueRevisionConflict as error:
        raise ContractError(
            "queue_revision_conflict",
            "The queue changed before the move was applied.",
            status_code=409,
            details=[
                APIErrorDetail(field="revision", message=str(error.queue.revision)),
                APIErrorDetail(
                    field="groups",
                    message=json.dumps(
                        [group.model_dump() for group in error.queue.groups],
                        separators=(",", ":"),
                    ),
                ),
            ],
        ) from error
    except Exception as error:
        _raise_job_error(error)


@router.get("/{job_id}/logs", response_model=JobLogPage)
def get_job_logs(
    job_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> JobLogPage:
    try:
        return JobLogPage.model_validate(_manager(request).logs(job_id, after=after, limit=limit))
    except Exception as error:
        _raise_job_error(error)


def _manager(request: Request) -> JobManager:
    return request.app.state.job_manager_service.get_manager()


def _detail(job: Job, queue: Queue | None = None) -> JobDetail:
    del queue
    retryable = job.state in {"failed", "cancelled", "interrupted"} and job.parent_id is None
    reorderable = job.state == "queued" or (
        job.type == "automated_pipeline" and job.state == "waiting"
    )
    result = job.model_dump(mode="json")
    result["results"] = [
        {**item, "available": bool(item.get("available", False))} for item in job.results
    ]
    result["capabilities"] = {
        "cancel": JobCapabilities(
            allowed=job.state in {"queued", "running", "waiting"},
            reason=None if job.state in {"queued", "running", "waiting"} else "job is not active",
        ).model_dump(),
        "retry": JobCapabilities(
            allowed=retryable,
            reason=None if retryable else "job type or state does not support retry",
        ).model_dump(),
        "reorder": JobCapabilities(
            allowed=reorderable,
            reason=None if reorderable else "only queued work or a waiting parent can move",
        ).model_dump(),
    }
    return JobDetail.model_validate(result)


def _matches(job: Job, filters: Mapping[str, Any]) -> bool:
    if filters["state"] is not None and job.state != filters["state"]:
        return False
    if filters["type"] is not None and job.type != filters["type"]:
        return False
    if (
        filters["recording_id"] is not None
        and job.context.get("recording_id") != filters["recording_id"]
    ):
        return False
    if filters["parent_id"] is not None and job.parent_id != filters["parent_id"]:
        return False
    if filters["scope"] == "active" and job.state not in _ACTIVE_STATES:
        return False
    return not (filters["scope"] == "history" and job.state not in _TERMINAL_STATES)


def _filter_digest(filters: Mapping[str, Any]) -> str:
    raw = json.dumps(filters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _encode_cursor(filters: Mapping[str, Any], job: Job) -> str:
    payload = json.dumps(
        {"filters": _filter_digest(filters), "created_at": job.created_at, "id": job.id},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str, filters: Mapping[str, Any]) -> tuple[str, str]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if payload["filters"] != _filter_digest(filters):
            raise ValueError("cursor filters changed")
        if not isinstance(payload["created_at"], str) or not isinstance(payload["id"], str):
            raise ValueError("cursor boundary is invalid")
        return payload["created_at"], payload["id"]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ContractError("invalid_request", "The job cursor is invalid.") from error


def _raise_job_error(error: Exception) -> None:
    if isinstance(error, JobNotFound):
        raise ContractError("job_not_found", str(error), status_code=404) from error
    if isinstance(error, JobConflict):
        raise ContractError("idempotency_conflict", str(error), status_code=409) from error
    if isinstance(error, JobOwnershipError | JobStorageError):
        raise ContractError(
            "job_manager_unavailable",
            "The job manager cannot safely serve this request.",
            status_code=503,
        ) from error
    if isinstance(error, JobStateError):
        raise ContractError("invalid_transition", str(error), status_code=409) from error
    if isinstance(error, ValueError):
        raise ContractError("invalid_request", str(error)) from error
    raise error
