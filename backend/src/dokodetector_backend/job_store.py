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
from threading import Event, RLock
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


class FakeParticipant:
    """A deterministic domain run and input-protection fixture."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def validate(self, request: dict[str, Any]) -> None:
        if (
            request["type"] not in {"fake", "automated_pipeline"}
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


class JobManager:
    """Own one root and serialize durable acceptance and state changes."""

    def __init__(
        self,
        operations_root: Path,
        participant: Participant,
        *,
        after_write: Callable[[str], None] | None = None,
        verify_publication: Callable[[Job, list[dict[str, Any]]], bool] | None = None,
    ) -> None:
        self.root = Path(operations_root).resolve() / "jobs"
        self.participant = participant
        self.after_write = after_write or (lambda _: None)
        self.verify_publication = verify_publication or (lambda _job, _results: False)
        self.diagnostics: list[str] = []
        self._lock = RLock()
        self._owner: Any = None
        self._scheduler: object | None = None

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
                    type=intent.job.type,
                    context=intent.job.context,
                    request=intent.job.request,
                    parent_id=intent.job.parent_id,
                    parent_step_id=intent.job.parent_step_id,
                )
                if _digest(parsed) != intent.job.request_hash:
                    raise ValueError("intent request hash mismatch")
                if _mapping_digest(intent.submitted_request) != intent.submitted_hash:
                    raise ValueError("submitted request hash mismatch")
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
        except FileNotFoundError as error:
            raise JobNotFound(f"job {job_id} was not found") from error
        except (OSError, ValueError) as error:
            raise JobStorageError(f"invalid job {job_id}") from error

    def list_jobs(self) -> list[Job]:
        """Return readable jobs in durable acceptance order."""
        self._owned()
        jobs = []
        for intent in self._intents():
            if not intent.committed:
                continue
            try:
                jobs.append(self.get(intent.job.id))
            except JobStorageError as error:
                self.diagnostics.append(str(error))
        return jobs

    def has_active_children(self, parent_id: str) -> bool:
        """Return whether an automated parent still owns non-terminal child work."""
        return any(
            job.parent_id == parent_id and job.state not in _TERMINAL for job in self.list_jobs()
        )

    def append_log(
        self,
        job_id: str,
        code: str,
        message: str,
        *,
        level: Literal["debug", "info", "warning", "error"] = "info",
    ) -> JobLogEntry:
        """Append one bounded durable diagnostic entry for a job."""
        with self._lock:
            self._owned()
            self.get(job_id)
            path = self.root / _uuid(job_id) / "logs.json"
            entries = self.logs(job_id, after=0, limit=1000)["entries"]
            sequence = entries[-1].sequence + 1 if entries else 1
            entry = JobLogEntry(
                sequence=sequence,
                timestamp=_now(),
                level=level,
                code=code,
                message=message,
            )
            entries.append(entry)
            atomic_replace_json(path, [item.model_dump() for item in entries[-1000:]])
            return entry

    def logs(self, job_id: str, *, after: int = 0, limit: int = 100) -> dict[str, Any]:
        """Read a bounded sequence page and report whether older entries were trimmed."""
        self._owned()
        self.get(job_id)
        path = self.root / _uuid(job_id) / "logs.json"
        if not path.exists():
            return {"entries": [], "next_after": after, "truncated_before": 0}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            entries = [JobLogEntry.model_validate(item) for item in raw]
        except (OSError, ValueError, TypeError) as error:
            raise JobStorageError(f"invalid job log for {job_id}") from error
        truncated_before = max(0, entries[0].sequence - 1) if entries else 0
        selected = [item for item in entries if item.sequence > after][:limit]
        next_after = selected[-1].sequence if selected else max(after, truncated_before)
        return {
            "entries": selected,
            "next_after": next_after,
            "truncated_before": truncated_before,
        }

    def report_progress(
        self,
        job_id: str,
        *,
        phase: str,
        completed: int | None,
        total: int | None,
        unit: str | None = None,
        step_id: str | None = None,
    ) -> Job:
        """Persist bounded handler progress on a stable step."""
        with self._lock:
            self._owned()
            job = self.get(job_id)
            if job.state != "running":
                return job
            now = _now()
            job.phase = phase
            if step_id is None:
                if not job.steps:
                    job.steps.append(Step(id="process", label=phase))
                step = job.steps[0]
            else:
                step = next((item for item in job.steps if item.id == step_id), None)
                if step is None:
                    now = _now()
                    for previous in job.steps:
                        if previous.state == "running":
                            previous.state = "succeeded"
                            previous.finished_at = now
                    step = Step(id=step_id, label=phase)
                    job.steps.append(step)
            if step.state == "pending":
                step.state = "running"
                step.started_at = now
            step.label = phase
            step.completed = completed
            step.total = total
            step.unit = unit
            job.revision += 1
            job.updated_at = now
            self._write_job(job)
            return job

    def queue(self) -> Queue:
        self._owned()
        path = self.root / "queue.json"
        if not path.exists():
            return Queue()
        try:
            queue = Queue.model_validate_json(path.read_bytes())
            if len(set(queue.job_ids)) != len(queue.job_ids):
                raise ValueError("duplicate queue member")
            members = [member for group in queue.groups for member in group.child_job_ids]
            if len(set(members + queue.job_ids)) != len(members) + len(queue.job_ids):
                raise ValueError("duplicate queue member")
            for member in members:
                if _uuid(member) != member:
                    raise ValueError("invalid child queue member")
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
            self.append_log(job.id, "job_accepted", "Job accepted and queued.")
        queue = self.queue()
        current = self.get(job.id)
        if current.state == "queued":
            if job.parent_id is None and job.id not in queue.job_ids:
                queue.groups.append(QueueGroup(group_id=job.id))
                queue.revision += 1
                self._set_queue(queue)
                self.after_write("queue")
            elif job.parent_id is not None:
                group = next((g for g in queue.groups if g.group_id == job.parent_id), None)
                if group is None:
                    raise JobStorageError("parent queue group is missing")
                if job.id not in group.child_job_ids:
                    group.child_job_ids.append(job.id)
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
        self._reconcile(intents)
        for intent in intents:
            try:
                self._finish_intent(intent)
            except (OSError, ValueError, JobStorageError) as error:
                self.diagnostics.append(f"intent {intent.job.id}: {error}")
        for intent in intents:
            if not intent.committed:
                continue
            try:
                job = self.get(intent.job.id)
            except JobStorageError as error:
                self.diagnostics.append(str(error))
                continue
            if job.state in {"running", "cancelling"}:
                publication_path = self.root / job.id / "publication.json"
                publication: Publication | None = None
                if publication_path.exists():
                    try:
                        publication = Publication.model_validate_json(publication_path.read_bytes())
                        if publication.job_id != job.id:
                            raise ValueError("publication job ID mismatch")
                    except (OSError, ValueError) as error:
                        self.diagnostics.append(f"invalid publication for {job.id}: {error}")
                if publication is not None and self.verify_publication(job, publication.results):
                    job.results = publication.results
                    job.state = "succeeded"
                    job.finished_at = _now()
                    job.updated_at = job.finished_at
                    job.revision += 1
                    job.worker_owner = None
                    self._write_job(job)
                    if publication.state != "committed":
                        publication.state = "committed"
                        atomic_replace_json(publication_path, publication.model_dump())
                    continue
                if job.type == "automated_pipeline":
                    if job.state == "running":
                        job.state = "queued"
                        job.finished_at = None
                    job.updated_at = _now()
                    job.revision += 1
                    job.worker_owner = None
                    job.waiting_reason = None
                    self._write_job(job)
                    continue
                job.state = "interrupted"
                job.finished_at = _now()
                job.updated_at = job.finished_at
                job.revision += 1
                job.worker_owner = None
                job.waiting_reason = "worker stopped before completion was recorded"
                for step in job.steps:
                    if step.state == "running":
                        step.state = "cancelled"
                        step.finished_at = job.finished_at
                        step.message = "interrupted during restart; recorded progress is retained"
                self._write_job(job)
        for intent in intents:
            if not intent.committed:
                continue
            try:
                parent = self.get(intent.job.id)
            except JobStorageError:
                continue
            if parent.type != "automated_pipeline" or parent.state != "cancelling":
                continue
            children = [item.job for item in intents if item.job.parent_id == parent.id]
            for child_intent in children:
                child = self.get(child_intent.id)
                if child.state == "queued":
                    child.state = "cancelled"
                    child.finished_at = _now()
                    child.updated_at = child.finished_at
                    child.revision += 1
                    self._write_job(child)
            if all(self.get(child.id).state in _TERMINAL for child in children):
                parent.state = "cancelled"
                parent.finished_at = _now()
                parent.updated_at = parent.finished_at
                parent.revision += 1
                self._write_job(parent)
        self._reconcile(intents)
        for intent in intents:
            if not intent.committed:
                continue
            try:
                parent = self.get(intent.job.id)
            except JobStorageError:
                continue
            if (
                parent.type != "automated_pipeline"
                or not isinstance(parent.request.get("run_id"), str)
                or parent.state != "waiting"
            ):
                continue
            children = [item.job for item in intents if item.job.parent_id == parent.id]
            if not any(self.get(child.id).state not in _TERMINAL for child in children):
                parent.state = "queued"
                parent.finished_at = None
                parent.updated_at = _now()
                parent.revision += 1
                self._write_job(parent)
        self._reconcile(intents)

    def _reconcile(self, intents: list[Intent]) -> None:
        queue = self.queue()
        valid = {i.job.id: i for i in intents if i.committed}
        jobs: dict[str, Job] = {}
        for job_id in valid:
            try:
                jobs[job_id] = self.get(job_id)
            except JobStorageError as error:
                self.diagnostics.append(str(error))
        groups: list[QueueGroup] = []
        seen: set[str] = set()
        for group in queue.groups:
            job = jobs.get(group.group_id)
            if job is None or job.parent_id is not None:
                self.diagnostics.append(f"invalid queue group {group.group_id}")
                continue
            if (job.type == "automated_pipeline" and job.state in _TERMINAL) or (
                job.type != "automated_pipeline" and job.state != "queued"
            ):
                continue
            children = []
            for child_id in group.child_job_ids:
                child = jobs.get(child_id)
                if child is None or child.parent_id != job.id:
                    self.diagnostics.append(f"invalid queue child {child_id}")
                elif child.state == "queued":
                    children.append(child_id)
                    seen.add(child_id)
            groups.append(QueueGroup(group_id=job.id, child_job_ids=children))
            seen.add(job.id)
        for intent in intents:
            job = jobs.get(intent.job.id)
            if job is None or job.id in seen or job.parent_id is not None:
                continue
            if job.state == "queued" or (
                job.type == "automated_pipeline" and job.state not in _TERMINAL
            ):
                groups.append(QueueGroup(group_id=job.id))
                seen.add(job.id)
        for intent in intents:
            job = jobs.get(intent.job.id)
            if job is None or job.id in seen or job.parent_id is None or job.state != "queued":
                continue
            group = next((g for g in groups if g.group_id == job.parent_id), None)
            if group is None:
                self.diagnostics.append(f"missing parent queue group for {job.id}")
            else:
                group.child_job_ids.append(job.id)
                seen.add(job.id)
        sequence = {intent.job.id: intent.sequence for intent in intents}
        for group in groups:
            group.child_job_ids.sort(key=lambda child_id: sequence[child_id])
        if groups != queue.groups:
            self._set_queue(Queue(revision=queue.revision + 1, groups=groups))

    def accept(
        self,
        key: str,
        raw_request: Mapping[str, Any],
        *,
        retry_of: str | None = None,
        correlation_id: str | None = None,
    ) -> Job:
        with self._lock:
            self._owned()
            key = _uuid(key)
            submitted_request = dict(raw_request)
            submitted_hash = _mapping_digest(submitted_request)
            for intent in self._intents():
                if intent.job.idempotency_key == key:
                    if intent.submitted_hash != submitted_hash or intent.job.retry_of != retry_of:
                        raise JobConflict("idempotency key has a different request")
                    self._finish_intent(intent)
                    return self.get(intent.job.id)
            normalizer = getattr(self.participant, "normalize", None)
            normalized_request = (
                normalizer(submitted_request) if normalizer is not None else submitted_request
            )
            request = JobRequest.model_validate(normalized_request)
            participant_request = {
                "type": request.type,
                "context": request.context,
                "request": request.request,
            }
            self.participant.validate(participant_request)
            digest = _digest(request)
            intents = self._intents()
            if request.parent_id is not None:
                parent = self.get(request.parent_id)
                if parent.type != "automated_pipeline" or parent.state in _TERMINAL:
                    raise JobStateError("parent must be an active pipeline")
                if any(
                    i.job.parent_id == request.parent_id
                    and i.job.parent_step_id == request.parent_step_id
                    for i in intents
                ):
                    raise JobConflict("parent step already has a child")
            now = _now()
            participant_fields = self._participant_job_fields(
                {
                    "type": request.type,
                    "context": request.context,
                    "request": request.request,
                }
            )
            label = participant_fields.pop("label", request.type)
            job = Job(
                id=str(uuid4()),
                idempotency_key=key,
                request_hash=digest,
                created_at=now,
                updated_at=now,
                label=label,
                retry_of=retry_of,
                correlation_id=correlation_id,
                **participant_fields,
                **request.model_dump(),
            )
            intent = Intent(
                sequence=max((i.sequence for i in intents), default=0) + 1,
                job=job,
                submitted_request=submitted_request,
                submitted_hash=submitted_hash,
            )
            self._write_intent(intent)
            self.after_write("intent")
            self._finish_intent(intent)
            return self.get(job.id)

    def _participant_job_fields(self, request: dict[str, Any]) -> dict[str, Any]:
        describe = getattr(self.participant, "job_fields", None)
        if describe is None:
            return {}
        fields = describe(request)
        allowed = {"inputs", "implementation", "label"}
        if not isinstance(fields, Mapping) or set(fields) - allowed:
            raise JobStorageError("participant returned invalid job metadata")
        return dict(fields)

    def cancel(self, job_id: str) -> Job:
        """Request cancellation; an active handler keeps its claims until it stops."""
        with self._lock:
            self._owned()
            job = self.get(job_id)
            if job.state in _TERMINAL or job.state == "cancelling":
                return job
            target = "cancelled" if job.state == "queued" else "cancelling"
            updated = self.transition(job.id, target)
            if job.type == "automated_pipeline" and target == "cancelling":
                group = next(
                    (item for item in self.queue().groups if item.group_id == job.id), None
                )
                child_ids = {
                    step.child_job_id
                    for step in self.get(job.id).steps
                    if step.child_job_id is not None
                }
                child_ids.update(
                    child.id for child in self.list_jobs() if child.parent_id == job.id
                )
                if group is not None:
                    child_ids.update(group.child_job_ids)
                for child_id in child_ids:
                    child = self.get(child_id)
                    if child.state not in _TERMINAL and child.state != "cancelling":
                        self.cancel(child_id)
                if job.state == "waiting" and self.get(job.id).state == "cancelling":
                    children = [child for child in self.list_jobs() if child.parent_id == job.id]
                    if all(child.state in _TERMINAL for child in children):
                        updated = self.transition(job.id, "cancelled")
            if target == "cancelling" and self._scheduler is not None:
                request_cancel = getattr(self._scheduler, "request_cancel", None)
                if request_cancel is not None:
                    request_cancel(job.id)
            return updated

    def retry(self, job_id: str, key: str) -> Job:
        """Create a new attempt with the source job's immutable request."""
        with self._lock:
            self._owned()
            source = self.get(job_id)
            if source.state not in {"failed", "cancelled", "interrupted"}:
                raise JobStateError("only failed, cancelled, or interrupted jobs can be retried")
            if source.parent_id is not None:
                raise JobStateError("retry the parent attempt to create a new child attempt")
            raw_retry_request = {
                "type": source.type,
                "context": source.context,
                "request": source.request,
                "parent_id": source.parent_id,
                "parent_step_id": source.parent_step_id,
            }
            prepare_retry = getattr(self.participant, "retry_request", None)
            retry_request = (
                raw_retry_request if prepare_retry is None else prepare_retry(raw_retry_request)
            )
            return self.accept(
                key,
                retry_request,
                retry_of=source.id,
                correlation_id=source.correlation_id,
            )

    def publish(
        self,
        job_id: str,
        results: list[dict[str, Any]],
        commit: Callable[[], None],
    ) -> bool:
        """Arbitrate cancellation and record a verifiable domain publication."""
        with self._lock:
            self._owned()
            job = self.get(job_id)
            if job.state == "cancelling":
                return False
            if job.state != "running":
                raise JobStateError("only a running job can publish results")
            publication = Publication(job_id=job.id, results=results, state="prepared")
            path = self.root / job.id / "publication.json"
            atomic_replace_json(path, publication.model_dump())
            self.after_write("publication_prepared")
            commit()
            self.after_write("publication_domain_commit")
            publication.state = "committed"
            atomic_replace_json(path, publication.model_dump())
            self.after_write("publication_committed")
            job.results = results
            self._write_job(job)
            self.after_write("publication_job")
            self.transition(job.id, "succeeded")
            return True

    def dispatchable(self) -> list[str]:
        with self._lock:
            self._owned()
            intents = {i.job.id: i for i in self._intents() if i.committed}
            result = []
            candidates: list[str] = []
            for group in self.queue().groups:
                try:
                    parent = self.get(group.group_id)
                except JobStorageError as error:
                    self.diagnostics.append(str(error))
                    continue
                if parent.state == "queued":
                    candidates.append(parent.id)
                if (
                    parent.type == "automated_pipeline"
                    and parent.state == "waiting"
                    and group.child_job_ids
                ):
                    candidates.append(group.child_job_ids[0])
            for job_id in candidates:
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
                        and _digest(
                            JobRequest.model_validate(
                                {
                                    **request,
                                    "parent_id": job.parent_id,
                                    "parent_step_id": job.parent_step_id,
                                }
                            )
                        )
                        == intent.job.request_hash
                        and job.idempotency_key == intent.job.idempotency_key
                        and self.participant.verify(job_id, request)
                    ):
                        result.append(job_id)
                    else:
                        self.diagnostics.append(f"unverified queued job {job_id}")
                except JobStorageError as error:
                    self.diagnostics.append(str(error))
            return result

    def dependencies_ready(self, job: Job) -> bool:
        """Require earlier children of a parent to have succeeded."""
        if job.parent_id is None:
            return True
        intents = self._intents()
        for intent in intents:
            if intent.job.id == job.id:
                return True
            if intent.job.parent_id == job.parent_id:
                if not intent.committed:
                    return False
                try:
                    if self.get(intent.job.id).state != "succeeded":
                        return False
                except JobStorageError:
                    return False
        return False

    def transition(self, job_id: str, state: State) -> Job:
        with self._lock:
            self._owned()
            job = self.get(job_id)
            if state not in _TRANSITIONS.get(job.state, set()):
                raise JobStateError(f"invalid transition {job.state} -> {state}")
            if state == "waiting" and job.type != "automated_pipeline":
                raise JobStateError("only parent jobs may wait")
            if state == "running" and (
                job.id not in self.dispatchable() or not self.dependencies_ready(job)
            ):
                raise JobStateError("job is not dispatchable")
            now = _now()
            job.state = state
            job.revision += 1
            job.updated_at = now
            if state == "running" and job.started_at is None:
                job.started_at = now
            if state in _TERMINAL:
                job.finished_at = now
                for step in job.steps:
                    if step.state in {"pending", "running"}:
                        step.state = {
                            "succeeded": "succeeded",
                            "failed": "failed",
                            "cancelled": "cancelled",
                            "interrupted": "cancelled",
                        }[state]
                        step.finished_at = now
                        if state == "interrupted":
                            step.message = "interrupted during restart"
            self._write_job(job)
            self._reconcile(self._intents())
            self.append_log(job.id, f"job_{state}", f"Job state changed to {state}.")
            if job.parent_id is not None and state in _TERMINAL:
                parent = self.get(job.parent_id)
                if parent.state == "waiting":
                    parent = self.transition(
                        parent.id, "cancelled" if state == "cancelled" else "queued"
                    )
                    if parent.state == "queued" and isinstance(parent.request.get("run_id"), str):
                        queue = self.queue()
                        group = next(
                            (item for item in queue.groups if item.group_id == parent.id), None
                        )
                        if group is not None and queue.groups[-1] is not group:
                            queue.groups.remove(group)
                            queue.groups.append(group)
                            queue.revision += 1
                            self._set_queue(queue)
                elif parent.state == "cancelling":
                    siblings = [child for child in self.list_jobs() if child.parent_id == parent.id]
                    if all(child.state in _TERMINAL for child in siblings):
                        self.transition(parent.id, "cancelled")
            return job
