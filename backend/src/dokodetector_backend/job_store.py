"""Durable job acceptance and lifecycle foundations.

This module does not start workers or register real processor types.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dokodetector_backend.filesystem import atomic_replace_json


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


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


State = Literal[
    "queued", "running", "waiting", "cancelling", "succeeded", "failed", "cancelled", "interrupted"
]


class JobRequest(Model):
    type: str = Field(min_length=1)
    context: dict[str, Any]
    request: dict[str, Any]


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
    committed: bool = False


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


class FakeParticipant:
    """A deterministic domain run and input-protection fixture."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def validate(self, request: dict[str, Any]) -> None:
        if (
            request["type"] != "fake"
            or set(request["context"]) != {"recording_id"}
            or not isinstance(request["context"]["recording_id"], str)
            or set(request["request"]) != {"input"}
            or not isinstance(request["request"]["input"], str)
        ):
            raise ValueError("invalid fake participant request")

    def prepare(
        self, job_id: str, request: dict[str, Any], after_write: Callable[[str], None]
    ) -> None:
        records = (
            (self.root / f"{job_id}.json", {"job_id": job_id, "request": request}, "domain_run"),
            (
                self.root / f"{job_id}.use.json",
                {"job_id": job_id, "input": request["request"]["input"]},
                "accepted_use",
            ),
        )
        for path, expected, point in records:
            if path.exists():
                if json.loads(path.read_text()) != expected:
                    raise JobStorageError("participant identity conflict")
            else:
                atomic_replace_json(path, expected)
                after_write(point)

    def verify(self, job_id: str, request: dict[str, Any]) -> bool:
        try:
            return json.loads((self.root / f"{job_id}.json").read_text()) == {
                "job_id": job_id,
                "request": request,
            } and json.loads((self.root / f"{job_id}.use.json").read_text()) == {
                "job_id": job_id,
                "input": request["request"]["input"],
            }
        except (OSError, ValueError):
            return False


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
    raw = json.dumps(request.model_dump(), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as error:
        raise ValueError("expected a UUID") from error


class JobManager:
    """Own one root and serialize durable acceptance and state changes."""

    def __init__(
        self,
        operations_root: Path,
        participant: Participant,
        *,
        after_write: Callable[[str], None] | None = None,
    ) -> None:
        self.root = Path(operations_root).resolve() / "jobs"
        self.participant = participant
        self.after_write = after_write or (lambda _: None)
        self.diagnostics: list[str] = []
        self._lock = RLock()
        self._owner: Any = None

    def __enter__(self) -> JobManager:
        self.root.mkdir(parents=True, exist_ok=True)
        self._owner = (self.root / "owner.lock").open("a+")
        try:
            fcntl.flock(self._owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self._owner.close()
            self._owner = None
            raise JobOwnershipError("another job manager owns this root") from error
        try:
            self._recover()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_args: object) -> None:
        if self._owner is not None:
            fcntl.flock(self._owner.fileno(), fcntl.LOCK_UN)
            self._owner.close()
            self._owner = None

    def _owned(self) -> None:
        if self._owner is None:
            raise JobOwnershipError("job manager does not own the root")

    def _intents(self) -> list[Intent]:
        path = self.root / "intents"
        result = []
        for item in sorted(path.glob("*.json")):
            try:
                intent = Intent.model_validate_json(item.read_bytes())
                if item.stem != _uuid(intent.job.id):
                    raise ValueError("intent ID mismatch")
                _uuid(intent.job.idempotency_key)
                parsed = JobRequest(
                    type=intent.job.type, context=intent.job.context, request=intent.job.request
                )
                if _digest(parsed) != intent.job.request_hash:
                    raise ValueError("intent request hash mismatch")
                result.append(intent)
            except (OSError, ValueError) as error:
                self.diagnostics.append(f"invalid intent {item.name}: {error}")
                raise JobStorageError("invalid intent blocks acceptance and dispatch") from error
        if len({i.sequence for i in result}) != len(result) or len(
            {i.job.idempotency_key for i in result}
        ) != len(result):
            raise JobStorageError("duplicate intent sequence or key")
        return sorted(result, key=lambda i: i.sequence)

    def _write_intent(self, intent: Intent) -> None:
        atomic_replace_json(self.root / "intents" / f"{intent.job.id}.json", intent.model_dump())

    def _write_job(self, job: Job) -> None:
        atomic_replace_json(self.root / job.id / "job.json", job.model_dump())

    def get(self, job_id: str) -> Job:
        self._owned()
        job_id = _uuid(job_id)
        try:
            job = Job.model_validate_json((self.root / job_id / "job.json").read_bytes())
            if job.id != job_id:
                raise ValueError("job ID mismatch")
            return job
        except (OSError, ValueError) as error:
            raise JobStorageError(f"invalid job {job_id}") from error

    def queue(self) -> Queue:
        self._owned()
        path = self.root / "queue.json"
        if not path.exists():
            return Queue()
        try:
            queue = Queue.model_validate_json(path.read_bytes())
            if len(set(queue.job_ids)) != len(queue.job_ids):
                raise ValueError("duplicate queue member")
            for group in queue.groups:
                if group.child_job_ids:
                    raise ValueError("child queues require scheduler support")
            for job_id in queue.job_ids:
                if _uuid(job_id) != job_id:
                    raise ValueError("invalid queue member")
            return queue
        except (OSError, ValueError) as error:
            self.diagnostics.append(f"invalid queue: {error}")
            raise JobStorageError("invalid queue blocks dispatch") from error

    def _set_queue(self, queue: Queue) -> None:
        atomic_replace_json(self.root / "queue.json", queue.model_dump())

    def _finish_intent(self, intent: Intent) -> None:
        job = intent.job
        request = {"type": job.type, "context": job.context, "request": job.request}
        self.participant.validate(request)
        if not intent.committed:
            self.participant.prepare(job.id, request, self.after_write)
        if not self.participant.verify(job.id, request):
            raise JobStorageError("participant verification failed")
        self.after_write("participant")
        path = self.root / job.id / "job.json"
        if path.exists():
            existing = self.get(job.id)
            if (
                existing.request_hash != job.request_hash
                or existing.idempotency_key != job.idempotency_key
            ):
                raise JobStorageError("job identity conflict")
        else:
            if intent.committed:
                raise JobStorageError("committed job record is missing")
            self._write_job(job)
            self.after_write("job")
        queue = self.queue()
        current = self.get(job.id)
        if current.state == "queued" and job.id not in queue.job_ids:
            queue.groups.append(QueueGroup(group_id=job.id))
            queue.revision += 1
            self._set_queue(queue)
            self.after_write("queue")
        if not intent.committed:
            intent.committed = True
            self._write_intent(intent)
            self.after_write("commit")

    def _recover(self) -> None:
        intents = self._intents()
        known = {intent.job.id for intent in intents}
        for path in self.root.iterdir():
            if path.is_dir() and path.name != "intents" and path.name not in known:
                self.diagnostics.append(f"unknown job directory {path.name}")
        for intent in intents:
            try:
                self._finish_intent(intent)
            except (OSError, ValueError, JobStorageError) as error:
                self.diagnostics.append(f"intent {intent.job.id}: {error}")
        self._reconcile(intents)

    def _reconcile(self, intents: list[Intent]) -> None:
        queue = self.queue()
        valid = {i.job.id: i for i in intents if i.committed}
        retained = []
        for job_id in queue.job_ids:
            try:
                if job_id not in valid or self.get(job_id).state != "queued":
                    raise JobStorageError("not a committed queued job")
                retained.append(job_id)
            except JobStorageError as error:
                self.diagnostics.append(f"queue member {job_id}: {error}")
        for intent in intents:
            if intent.committed and intent.job.id not in retained:
                try:
                    if self.get(intent.job.id).state == "queued":
                        retained.append(intent.job.id)
                except JobStorageError as error:
                    self.diagnostics.append(str(error))
        if retained != queue.job_ids:
            self._set_queue(
                Queue(
                    revision=queue.revision + 1, groups=[QueueGroup(group_id=i) for i in retained]
                )
            )

    def accept(self, key: str, raw_request: Mapping[str, Any]) -> Job:
        with self._lock:
            self._owned()
            key = _uuid(key)
            request = JobRequest.model_validate(raw_request)
            self.participant.validate(request.model_dump())
            digest = _digest(request)
            intents = self._intents()
            for intent in intents:
                if intent.job.idempotency_key == key:
                    if intent.job.request_hash != digest:
                        raise JobConflict("idempotency key has a different request")
                    self._finish_intent(intent)
                    return self.get(intent.job.id)
            now = _now()
            job = Job(
                id=str(uuid4()),
                idempotency_key=key,
                request_hash=digest,
                created_at=now,
                updated_at=now,
                label=request.type,
                **request.model_dump(),
            )
            intent = Intent(sequence=max((i.sequence for i in intents), default=0) + 1, job=job)
            self._write_intent(intent)
            self.after_write("intent")
            self._finish_intent(intent)
            return self.get(job.id)

    def dispatchable(self) -> list[str]:
        with self._lock:
            self._owned()
            intents = {i.job.id: i for i in self._intents() if i.committed}
            result = []
            for job_id in self.queue().job_ids:
                intent = intents.get(job_id)
                if intent is None:
                    self.diagnostics.append(f"unknown queue member {job_id}")
                    continue
                try:
                    job = self.get(job_id)
                    request = {"type": job.type, "context": job.context, "request": job.request}
                    if (
                        job.state == "queued"
                        and job.request_hash == intent.job.request_hash
                        and _digest(JobRequest.model_validate(request)) == intent.job.request_hash
                        and job.idempotency_key == intent.job.idempotency_key
                        and self.participant.verify(job_id, request)
                    ):
                        result.append(job_id)
                    else:
                        self.diagnostics.append(f"unverified queued job {job_id}")
                except JobStorageError as error:
                    self.diagnostics.append(str(error))
            return result

    def transition(self, job_id: str, state: State) -> Job:
        with self._lock:
            self._owned()
            job = self.get(job_id)
            if state not in _TRANSITIONS.get(job.state, set()):
                raise JobStateError(f"invalid transition {job.state} -> {state}")
            if state == "waiting" and job.type != "automated_pipeline":
                raise JobStateError("only parent jobs may wait")
            if state == "running" and job.id not in self.dispatchable():
                raise JobStateError("job is not dispatchable")
            now = _now()
            job.state = state
            job.revision += 1
            job.updated_at = now
            if state == "running" and job.started_at is None:
                job.started_at = now
            if state in _TERMINAL:
                job.finished_at = now
            self._write_job(job)
            self._reconcile(self._intents())
            return job
