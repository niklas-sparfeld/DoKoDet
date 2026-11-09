"""Durable job lifecycle management and persistence."""

from __future__ import annotations

import fcntl
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from dokodetector_backend.job_models import (
    _TERMINAL,
    _TRANSITIONS,
    Intent,
    Job,
    JobConflict,
    JobLogEntry,
    JobOwnershipError,
    JobRequest,
    JobStateError,
    JobStorageError,
    Participant,
    Publication,
    Queue,
    State,
    Step,
    _digest,
    _mapping_digest,
    _now,
    _uuid,
)
from dokodetector_backend.job_persistence import JobPersistence
from dokodetector_backend.job_recovery import JobRecovery


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
        self._owner: Any = None
        self._lock = RLock()
        self.persistence = JobPersistence(
            self.root,
            participant,
            self.after_write,
            self.verify_publication,
            self.diagnostics,
            self._lock,
            self._owned,
        )
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
        self._owned()
        return self.persistence._intents()

    def _write_intent(self, intent: Intent) -> None:
        self._owned()
        self.persistence._write_intent(intent)

    def _write_job(self, job: Job) -> None:
        self._owned()
        self.persistence._write_job(job)

    def get(self, job_id: str) -> Job:
        self._owned()
        return self.persistence.get(job_id)

    def list_jobs(self) -> list[Job]:
        self._owned()
        return self.persistence.list_jobs()

    def projection_authority(self):
        """Return the durable generation used to validate compact job projections."""
        self._owned()
        return self.persistence.read_projection_authority()

    def has_active_children(self, parent_id: str) -> bool:
        self._owned()
        return self.persistence.has_active_children(parent_id)

    def append_log(self, *args: Any, **kwargs: Any) -> JobLogEntry:
        self._owned()
        return self.persistence.append_log(*args, **kwargs)

    def logs(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._owned()
        return self.persistence.logs(*args, **kwargs)

    def queue(self) -> Queue:
        with self._lock:
            self._owned()
            if not self.persistence.projection_authority.index.queue_ready():
                raise JobStorageError("job queue authority is not ready")
            return self.persistence.queue()

    def _set_queue(self, queue: Queue) -> None:
        self._owned()
        self.persistence._set_queue(queue)

    def _finish_intent(self, intent: Intent) -> None:
        self._owned()
        self.persistence._finish_intent(intent)

    def _read_publication(self, job_id: str) -> Publication | None:
        self._owned()
        return self.persistence._read_publication(job_id)

    def _write_publication(self, publication: Publication) -> None:
        self._owned()
        self.persistence._write_publication(publication)

    def _unknown_job_directories(self, known_ids: set[str]) -> list[str]:
        self._owned()
        return self.persistence._unknown_job_directories(known_ids)

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

    def _recover(self) -> None:
        self._owned()
        self.persistence.initialize_projection_authority()
        JobRecovery(self.persistence.recovery_operations()).recover()

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
                child_ids = {
                    step.child_job_id
                    for step in self.get(job.id).steps
                    if step.child_job_id is not None
                }
                child_ids.update(
                    self.persistence.projection_authority.index.parent_children(job.id)
                )
                for child_id in child_ids:
                    child = self.get(child_id)
                    if child.state not in _TERMINAL and child.state != "cancelling":
                        self.cancel(child_id)
                if (
                    job.state == "waiting"
                    and self.get(job.id).state == "cancelling"
                    and not self.has_active_children(job.id)
                ):
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
            self.persistence._write_publication(publication)
            self.after_write("publication_prepared")
            commit()
            self.after_write("publication_domain_commit")
            publication.state = "committed"
            self.persistence._write_publication(publication)
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
        try:
            intent = self.persistence.get_intent(job.id)
            indexed = self.persistence.projection_authority.index.parent_child_sequence(job.id)
            if not intent.committed or indexed != (job.parent_id, intent.sequence, job.state):
                return False
            return not self.persistence.projection_authority.index.preceding_child_not_succeeded(
                job.parent_id, intent.sequence
            )
        except JobStorageError:
            return False

    def _is_dispatchable(self, job: Job) -> bool:
        """Check one job against durable queue and acceptance authority."""
        try:
            intent = self.persistence.get_intent(job.id)
            if not intent.committed:
                return False
            if job.parent_id is None:
                candidate = self.persistence.projection_authority.index.queue_group_exists(job.id)
            else:
                parent = self.get(job.parent_id)
                candidate = (
                    parent.type == "automated_pipeline"
                    and parent.state == "waiting"
                    and self.persistence.projection_authority.index.queue_first_child(parent.id)
                    == job.id
                )
            request = {"type": job.type, "context": job.context, "request": job.request}
            request_hash = _digest(
                JobRequest.model_validate(
                    {
                        **request,
                        "parent_id": job.parent_id,
                        "parent_step_id": job.parent_step_id,
                    }
                )
            )
            return (
                candidate
                and job.state == "queued"
                and job.request_hash == intent.job.request_hash
                and request_hash == intent.job.request_hash
                and job.idempotency_key == intent.job.idempotency_key
                and self.participant.verify(job.id, request)
            )
        except JobStorageError as error:
            self.diagnostics.append(str(error))
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
                not self._is_dispatchable(job) or not self.dependencies_ready(job)
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
            self.append_log(job.id, f"job_{state}", f"Job state changed to {state}.")
            if job.parent_id is not None and state in _TERMINAL:
                parent = self.get(job.parent_id)
                if parent.state == "waiting":
                    self.transition(parent.id, "cancelled" if state == "cancelled" else "queued")
                elif parent.state == "cancelling" and not self.has_active_children(parent.id):
                    self.transition(parent.id, "cancelled")
            return job
