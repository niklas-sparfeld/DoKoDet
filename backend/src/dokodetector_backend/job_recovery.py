from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from dokodetector_backend.job_models import (
    _TERMINAL,
    Intent,
    Job,
    JobStorageError,
    Publication,
    Queue,
    QueueGroup,
    Step,
    _now,
)


@dataclass(frozen=True)
class JobRecoveryOperations:
    """Explicit durable operations used by restart recovery and queue repair."""

    intents: Callable[[], list[Intent]]
    finish_intent: Callable[[Intent], None]
    get: Callable[[str], Job]
    write_job: Callable[[Job], None]
    queue: Callable[[], Queue]
    set_queue: Callable[[Queue], None]
    mark_queue_ready: Callable[[], None]
    rebuild_parent_children: Callable[[list[Intent]], None]
    read_publication: Callable[[str], Publication | None]
    write_publication: Callable[[Publication], None]
    verify_publication: Callable[[Job, list[dict]], bool]
    unknown_job_directories: Callable[[set[str]], list[str]]
    diagnostic: Callable[[str], None]
    ensure_owned: Callable[[], None]


class JobRecovery:
    """Reconcile accepted job records through the manager's locked operations."""

    def __init__(self, operations: JobRecoveryOperations) -> None:
        self.operations = operations

    def recover(self) -> None:
        self.operations.ensure_owned()
        intents = self.operations.intents()
        known = {intent.job.id for intent in intents}
        for directory in self.operations.unknown_job_directories(known):
            self.operations.diagnostic(f"unknown job directory {directory}")
        self.rebuild_queue(intents)
        for intent in intents:
            try:
                self.operations.finish_intent(intent)
            except (OSError, ValueError, JobStorageError) as error:
                self.operations.diagnostic(f"intent {intent.job.id}: {error}")
        # Intent completion can turn an interrupted child acceptance into the
        # current durable wait target. Re-read before reconciling parent waits.
        intents = self.operations.intents()
        for intent in intents:
            if not intent.committed:
                continue
            try:
                job = self.operations.get(intent.job.id)
            except JobStorageError as error:
                self.operations.diagnostic(str(error))
                continue
            if job.state in {"running", "cancelling"}:
                publication: Publication | None = None
                try:
                    publication = self.operations.read_publication(job.id)
                except (OSError, ValueError, JobStorageError) as error:
                    self.operations.diagnostic(f"invalid publication for {job.id}: {error}")
                if publication is not None and self.operations.verify_publication(
                    job, publication.results
                ):
                    job.results = publication.results
                    job.state = "succeeded"
                    job.finished_at = _now()
                    job.updated_at = job.finished_at
                    job.revision += 1
                    job.worker_owner = None
                    self.operations.write_job(job)
                    if publication.state != "committed":
                        publication.state = "committed"
                        self.operations.write_publication(publication)
                    continue
                if job.type == "automated_pipeline":
                    if job.state == "running":
                        job.state = "queued"
                        job.finished_at = None
                    job.updated_at = _now()
                    job.revision += 1
                    job.worker_owner = None
                    job.waiting_reason = None
                    self.operations.write_job(job)
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
                self.operations.write_job(job)
        for intent in intents:
            if not intent.committed:
                continue
            try:
                parent = self.operations.get(intent.job.id)
            except JobStorageError:
                continue
            if parent.type != "automated_pipeline" or parent.state != "cancelling":
                continue
            children = [item.job for item in intents if item.job.parent_id == parent.id]
            for child_intent in children:
                child = self.operations.get(child_intent.id)
                if child.state == "queued":
                    child.state = "cancelled"
                    child.finished_at = _now()
                    child.updated_at = child.finished_at
                    child.revision += 1
                    self.operations.write_job(child)
            if all(self.operations.get(child.id).state in _TERMINAL for child in children):
                parent.state = "cancelled"
                parent.finished_at = _now()
                parent.updated_at = parent.finished_at
                parent.revision += 1
                self.operations.write_job(parent)
        self.rebuild_queue(intents)
        for intent in intents:
            if not intent.committed:
                continue
            try:
                parent = self.operations.get(intent.job.id)
            except JobStorageError:
                continue
            if parent.type != "automated_pipeline" or parent.state != "waiting":
                continue
            # `phase` is written before the parent enters waiting. Resolve only that
            # stage's child. An earlier terminal child must not complete a later wait.
            waiting_step = next((step for step in parent.steps if step.id == parent.phase), None)
            current_children = [
                item
                for item in intents
                if item.job.parent_id == parent.id and item.job.parent_step_id == parent.phase
            ]
            if len(current_children) > 1:
                self.operations.diagnostic(
                    f"pipeline {parent.id} has multiple children for waiting stage {parent.phase}"
                )
                continue
            child_intent = current_children[0] if current_children else None
            if (
                child_intent is not None
                and waiting_step is not None
                and waiting_step.child_job_id not in {None, child_intent.job.id}
            ):
                self.operations.diagnostic(
                    f"pipeline {parent.id} waiting child conflicts with stage {parent.phase}"
                )
                continue
            if child_intent is None:
                # The parent may have committed its wait before accepting the first
                # child. Requeue it so the stage can be accepted on the next dispatch.
                parent.state = "queued"
                parent.finished_at = None
                parent.updated_at = _now()
                parent.revision += 1
                self.operations.write_job(parent)
                continue
            if waiting_step is None:
                if parent.phase is None:
                    self.operations.diagnostic(
                        f"pipeline {parent.id} has a child without a waiting phase"
                    )
                    continue
                waiting_step = Step(id=parent.phase, label=parent.phase)
                parent.steps.append(waiting_step)
            if waiting_step.child_job_id is None:
                # Acceptance commits before the pipeline writes this link. Restore
                # the exact child before interpreting its state or dispatching work.
                waiting_step.child_job_id = child_intent.job.id
                parent.updated_at = _now()
                parent.revision += 1
                self.operations.write_job(parent)
            if not child_intent.committed:
                # Keep the exact wait while acceptance recovery completes this child.
                continue
            terminal_child = self.operations.get(child_intent.job.id)
            if terminal_child.state not in _TERMINAL:
                continue

            now = _now()
            parent.state = "cancelled" if terminal_child.state == "cancelled" else "queued"
            parent.finished_at = now if parent.state == "cancelled" else None
            parent.updated_at = now
            parent.revision += 1
            if parent.state == "cancelled":
                for step in parent.steps:
                    if step.state in {"pending", "running"}:
                        step.state = "cancelled"
                        step.finished_at = now
            self.operations.write_job(parent)
        self.rebuild_queue(intents)
        self.operations.rebuild_parent_children(intents)
        self.operations.mark_queue_ready()

    def rebuild_queue(self, intents: list[Intent]) -> None:
        """Repair the full queue from durable jobs during explicit manager startup recovery."""
        self.operations.ensure_owned()
        queue = self.operations.queue()
        valid = {i.job.id: i for i in intents if i.committed}
        jobs: dict[str, Job] = {}
        for job_id in valid:
            try:
                jobs[job_id] = self.operations.get(job_id)
            except JobStorageError as error:
                self.operations.diagnostic(str(error))
        groups: list[QueueGroup] = []
        seen: set[str] = set()
        for group in queue.groups:
            job = jobs.get(group.group_id)
            if job is None or job.parent_id is not None:
                self.operations.diagnostic(f"invalid queue group {group.group_id}")
                continue
            if (job.type == "automated_pipeline" and job.state in _TERMINAL) or (
                job.type != "automated_pipeline" and job.state != "queued"
            ):
                continue
            children = []
            for child_id in group.child_job_ids:
                child = jobs.get(child_id)
                if child is None or child.parent_id != job.id:
                    self.operations.diagnostic(f"invalid queue child {child_id}")
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
                self.operations.diagnostic(f"missing parent queue group for {job.id}")
            else:
                group.child_job_ids.append(job.id)
                seen.add(job.id)
        sequence = {intent.job.id: intent.sequence for intent in intents}
        for group in groups:
            group.child_job_ids.sort(key=lambda child_id: sequence[child_id])
        if groups != queue.groups:
            self.operations.set_queue(Queue(revision=queue.revision + 1, groups=groups))
