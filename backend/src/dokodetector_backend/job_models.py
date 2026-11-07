from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from threading import Event
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobError(RuntimeError):
    """Base error for job storage."""


class JobConflict(JobError):
    """An idempotency key has a different request."""


class JobStateError(JobError):
    """A lifecycle transition is not valid."""


class JobOwnershipError(JobError):
    """Another manager owns this operations root."""


class JobStorageError(JobError):
    """A durable record cannot be safely used."""


class JobNotFound(JobStorageError):
    """A job identity is valid but does not exist."""


class CancellationToken:
    """Cooperative stop signal for one running handler."""

    def __init__(self) -> None:
        self._event = Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def request(self) -> None:
        self._event.set()

    def check(self) -> None:
        if self.cancelled:
            raise JobCancelled("job cancellation requested")


class JobCancelled(JobError):
    """A cooperative handler stopped after a cancellation request."""


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


State = Literal[
    "queued", "running", "waiting", "cancelling", "succeeded", "failed", "cancelled", "interrupted"
]


class JobRequest(Model):
    type: str = Field(min_length=1)
    context: dict[str, Any]
    request: dict[str, Any]
    parent_id: str | None = None
    parent_step_id: str | None = None

    @model_validator(mode="after")
    def validate_parent(self) -> JobRequest:
        if (self.parent_id is None) != (self.parent_step_id is None):
            raise ValueError("parent ID and step ID must be supplied together")
        if self.parent_id is not None:
            _uuid(self.parent_id)
            if not self.parent_step_id:
                raise ValueError("parent step ID cannot be empty")
        return self


class Step(Model):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    state: Literal["pending", "running", "succeeded", "failed", "cancelled", "skipped"] = "pending"
    started_at: str | None = None
    finished_at: str | None = None
    completed: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    unit: str | None = None
    message: str | None = None
    failure: dict[str, Any] | None = None
    child_job_id: str | None = None

    @model_validator(mode="after")
    def validate_progress(self) -> Step:
        if (self.completed is None) != (self.total is None):
            raise ValueError("progress needs both completed and total")
        if self.completed is not None and self.total is not None and self.completed > self.total:
            raise ValueError("completed progress exceeds total")
        return self


class Job(Model):
    schema_version: Literal["backend-job/v1"] = "backend-job/v1"
    id: str
    type: str
    label: str
    context: dict[str, Any]
    request: dict[str, Any]
    idempotency_key: str
    request_hash: str
    state: State = "queued"
    revision: int = Field(default=1, ge=1)
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    parent_id: str | None = None
    parent_step_id: str | None = None
    retry_of: str | None = None
    steps: list[Step] = Field(default_factory=list)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)
    failure: dict[str, Any] | None = None
    implementation: dict[str, Any] = Field(default_factory=dict)
    creator: str | None = None
    correlation_id: str | None = None
    worker_owner: str | None = None
    phase: str | None = None
    waiting_reason: str | None = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    coverage: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_job(self) -> Job:
        if len({step.id for step in self.steps}) != len(self.steps):
            raise ValueError("step IDs must be unique")
        if (self.state in {"succeeded", "failed", "cancelled", "interrupted"}) != (
            self.finished_at is not None
        ):
            raise ValueError("terminal state and finish time must agree")
        return self


class Intent(Model):
    schema_version: Literal["backend-job-intent/v1"] = "backend-job-intent/v1"
    sequence: int = Field(ge=1)
    job: Job
    submitted_request: dict[str, Any]
    submitted_hash: str
    committed: bool = False


class Publication(Model):
    schema_version: Literal["backend-job-publication/v1"] = "backend-job-publication/v1"
    job_id: str
    results: list[dict[str, Any]]
    state: Literal["prepared", "committed"]


class JobLogEntry(Model):
    sequence: int = Field(ge=1)
    timestamp: str
    level: Literal["debug", "info", "warning", "error"]
    code: str
    message: str


class QueueGroup(Model):
    group_id: str
    child_job_ids: list[str] = Field(default_factory=list)


class Queue(Model):
    schema_version: Literal["backend-job-queue/v1"] = "backend-job-queue/v1"
    revision: int = Field(default=0, ge=0)
    groups: list[QueueGroup] = Field(default_factory=list)

    @property
    def job_ids(self) -> list[str]:
        return [group.group_id for group in self.groups]


class Participant(Protocol):
    def validate(self, request: dict[str, Any]) -> None: ...

    def prepare(
        self, job_id: str, request: dict[str, Any], after_write: Callable[[str], None]
    ) -> None: ...

    def verify(self, job_id: str, request: dict[str, Any]) -> bool: ...


_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "cancelled"},
    "running": {"waiting", "cancelling", "succeeded", "failed", "interrupted"},
    "waiting": {"queued", "cancelling", "failed", "interrupted"},
    "cancelling": {"cancelled", "succeeded", "failed", "interrupted"},
}
_TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(request: JobRequest) -> str:
    raw = json.dumps(
        request.model_dump(exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _mapping_digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as error:
        raise ValueError("expected a UUID") from error
