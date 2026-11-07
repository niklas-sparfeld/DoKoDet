"""Durable job record encoding and persistence operations."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.job_models import (
    _TERMINAL,
    Intent,
    Job,
    JobLogEntry,
    JobNotFound,
    JobRequest,
    JobStorageError,
    Participant,
    Publication,
    Queue,
    QueueGroup,
    _digest,
    _mapping_digest,
    _now,
    _uuid,
)
from dokodetector_backend.job_recovery import JobRecoveryOperations


class JobPersistence:
    """Persist job records through explicit operations for the manager and recovery."""

    def __init__(
        self,
        root: Path,
        participant: Participant,
        after_write: Callable[[str], None],
        verify_publication: Callable[[Job, list[dict[str, Any]]], bool],
        diagnostics: list[str],
        lock: Any,
        ensure_owned: Callable[[], None],
    ) -> None:
        self.root = root
        self.participant = participant
        self.after_write = after_write
        self.verify_publication = verify_publication
        self.diagnostics = diagnostics
        self._lock = lock
        self.ensure_owned = ensure_owned

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

    def queue(self) -> Queue:
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

    def _read_publication(self, job_id: str) -> Publication | None:
        path = self.root / _uuid(job_id) / "publication.json"
        if not path.exists():
            return None
        publication = Publication.model_validate_json(path.read_bytes())
        if publication.job_id != job_id:
            raise ValueError("publication job ID mismatch")
        return publication

    def _write_publication(self, publication: Publication) -> None:
        atomic_replace_json(
            self.root / _uuid(publication.job_id) / "publication.json", publication.model_dump()
        )

    def _unknown_job_directories(self, known_ids: set[str]) -> list[str]:
        return [
            path.name
            for path in self.root.iterdir()
            if path.is_dir() and path.name != "intents" and path.name not in known_ids
        ]

    def recovery_operations(self) -> JobRecoveryOperations:
        return JobRecoveryOperations(
            intents=self._intents,
            finish_intent=self._finish_intent,
            get=self.get,
            write_job=self._write_job,
            queue=self.queue,
            set_queue=self._set_queue,
            read_publication=self._read_publication,
            write_publication=self._write_publication,
            verify_publication=self.verify_publication,
            unknown_job_directories=self._unknown_job_directories,
            diagnostic=self.diagnostics.append,
            ensure_owned=self.ensure_owned,
        )
