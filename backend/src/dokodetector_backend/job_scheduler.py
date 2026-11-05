"""Local ordered scheduler for registered, bounded job handlers."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from time import monotonic
from typing import Callable

from dokodetector_backend.job_store import (
    CancellationToken,
    Job,
    JobCancelled,
    JobManager,
    JobStateError,
    Queue,
    _now,
)


@dataclass(frozen=True)
class Budget:
    slots: int = 1
    cpu: int = 1
    accelerator: int = 1
    external: int = 1

    def __post_init__(self) -> None:
        if min(self.slots, self.cpu) < 1 or min(self.accelerator, self.external) < 0:
            raise ValueError("invalid scheduler budget")


@dataclass(frozen=True)
class Claims:
    cpu: int = 1
    accelerator: int = 0
    external: int = 0
    locks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.cpu < 1 or self.accelerator < 0 or self.external < 0:
            raise ValueError("invalid resource claims")
        if len(set(self.locks)) != len(self.locks) or any(not lock for lock in self.locks):
            raise ValueError("invalid domain locks")


class QueueRevisionConflict(JobStateError):
    def __init__(self, queue: Queue) -> None:
        super().__init__("queue revision changed")
        self.queue = queue


class JobScheduler:
    """Run fake or registered handlers under one shared resource budget.

    The handler receives its admitted CPU and resource allocation. It must respect that budget.
    Active job recovery and cancellation are handled in M3; a scheduler refuses stale active jobs.
    """

    def __init__(
        self,
        manager: JobManager,
        handler: Callable[[Job, Claims, CancellationToken], None],
        claims_for: Callable[[Job], Claims],
        *,
        budget: Budget | None = None,
        ready: Callable[[Job], str | None] = lambda _: None,
        shutdown_timeout: float = 5.0,
    ) -> None:
        self.manager = manager
        self.handler = handler
        self.claims_for = claims_for
        self.budget = budget or Budget()
        self.ready = ready
        if shutdown_timeout <= 0:
            raise ValueError("shutdown timeout must be positive")
        self.shutdown_timeout = shutdown_timeout
        self._active: dict[str, tuple[Future[None], Claims, CancellationToken]] = {}
        self._event = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool: ThreadPoolExecutor | None = None
        self.error: Exception | None = None

    def __enter__(self) -> JobScheduler:
        with self.manager._lock:
            self.manager._owned()
            if self.manager._scheduler is not None:
                raise JobStateError("a scheduler already owns this manager")
            for intent in self.manager._intents():
                if intent.committed and self.manager.get(intent.job.id).state in {
                    "running",
                    "cancelling",
                }:
                    raise JobStateError("active job needs restart reconciliation")
            self.manager._scheduler = self
            self._pool = ThreadPoolExecutor(
                max_workers=self.budget.slots, thread_name_prefix="jobs"
            )
            self._thread = threading.Thread(target=self._loop, name="job-scheduler", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._event.set()
        if self._thread is not None:
            self._thread.join()
        with self.manager._lock:
            for job_id, (_, _, token) in self._active.items():
                token.request()
                job = self.manager.get(job_id)
                if job.state == "running":
                    self.manager.transition(job_id, "cancelling")
        deadline = monotonic() + self.shutdown_timeout
        while self._active and monotonic() < deadline:
            with self.manager._lock:
                self._reap()
            if self._active:
                threading.Event().wait(min(0.02, max(0.0, deadline - monotonic())))
        if self._pool is not None:
            self._pool.shutdown(wait=not self._active, cancel_futures=False)
        with self.manager._lock:
            self._reap()
            if not self._active:
                self.manager._scheduler = None
        if self._active:
            raise JobStateError("graceful shutdown timed out; active handler claims remain held")

    def request_cancel(self, job_id: str) -> None:
        """Signal an active handler after its durable state enters cancelling."""
        active = self._active.get(job_id)
        if active is not None:
            active[2].request()
            self._event.set()

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                with self.manager._lock:
                    self._reap()
                    self._admit()
                self._event.wait(0.05)
                self._event.clear()
        except Exception as error:
            self.error = error
            self.manager.diagnostics.append(f"scheduler stopped: {error}")
            self._stop.set()

    def _reap(self) -> None:
        for job_id, (future, _, _) in list(self._active.items()):
            if not future.done():
                continue
            del self._active[job_id]
            try:
                future.result()
            except JobCancelled:
                job = self.manager.get(job_id)
                if job.state in {"cancelling", "running"} and (
                    job.type != "automated_pipeline" or not self.manager.has_active_children(job.id)
                ):
                    self.manager.transition(job_id, "cancelled")
            except Exception as error:
                job = self.manager.get(job_id)
                if job.state in {"cancelling", "cancelled", "succeeded"}:
                    continue
                job.failure = {"code": "handler_failed", "message": str(error)}
                self.manager._write_job(job)
                self.manager.transition(job_id, "failed")
            else:
                job = self.manager.get(job_id)
                if job.state == "running":
                    self.manager.transition(job_id, "succeeded")
                elif job.state == "cancelling" and (
                    job.type != "automated_pipeline" or not self.manager.has_active_children(job.id)
                ):
                    self.manager.transition(job_id, "cancelled")

    def _waiting(self, job: Job, reason: str | None) -> None:
        if job.waiting_reason != reason:
            job.waiting_reason = reason
            job.revision += 1
            job.updated_at = _now()
            self.manager._write_job(job)

    def _admit(self) -> None:
        if self._pool is None:
            return
        active = [claims for _, claims, _ in self._active.values()]
        available = {
            "slots": self.budget.slots - len(active),
            "cpu": self.budget.cpu - sum(c.cpu for c in active),
            "accelerator": self.budget.accelerator - sum(c.accelerator for c in active),
            "external": self.budget.external - sum(c.external for c in active),
        }
        held_locks = {lock for claim in active for lock in claim.locks}
        reserved: set[str] = set()
        for group in self.manager.queue().groups:
            for child_id in group.child_job_ids[1:]:
                self._waiting(self.manager.get(child_id), "waiting for previous child")
        for job_id in self.manager.dispatchable():
            job = self.manager.get(job_id)
            if not self.manager.dependencies_ready(job):
                self._waiting(job, "waiting for previous child")
                continue
            dependency = self.ready(job)
            if dependency:
                self._waiting(job, dependency)
                continue
            claim = self.claims_for(job)
            required = {
                "slots": 1,
                "cpu": claim.cpu,
                "accelerator": claim.accelerator,
                "external": claim.external,
            }
            impossible = [
                name for name, amount in required.items() if amount > getattr(self.budget, name)
            ]
            if impossible:
                self._waiting(job, "exceeds configured " + ", ".join(impossible))
                continue
            needed = {name for name, amount in required.items() if amount > 0}
            needed.update("lock:" + name for name in claim.locks)
            shortage = {name for name, amount in required.items() if amount > available[name]}
            shortage.update("lock:" + name for name in claim.locks if name in held_locks)
            if shortage or needed & reserved:
                reserved.update(shortage)
                self._waiting(
                    job, "waiting for " + ", ".join(sorted(shortage or needed & reserved))
                )
                continue
            self._waiting(job, None)
            job = self.manager.transition(job_id, "running")
            for name, amount in required.items():
                available[name] -= amount
            held_locks.update(claim.locks)
            token = CancellationToken()
            future = self._pool.submit(self.handler, job, claim, token)
            self._active[job_id] = (future, claim, token)
            future.add_done_callback(lambda _: self._event.set())

    def move(self, group_id: str, before_group_id: str | None, expected_revision: int) -> Queue:
        with self.manager._lock:
            self.manager._owned()
            queue = self.manager.queue()
            if queue.revision != expected_revision:
                raise QueueRevisionConflict(queue)
            if group_id not in queue.job_ids or group_id == before_group_id:
                raise JobStateError("invalid queue group")
            if before_group_id is not None and before_group_id not in queue.job_ids:
                raise JobStateError("invalid target queue group")
            selected = self.manager.get(group_id)
            if selected.state != "queued" and not (
                selected.type == "automated_pipeline" and selected.state == "waiting"
            ):
                raise JobStateError("only queued jobs or waiting parent groups can move")
            group = next(group for group in queue.groups if group.group_id == group_id)
            queue.groups.remove(group)
            position = (
                len(queue.groups)
                if before_group_id is None
                else queue.job_ids.index(before_group_id)
            )
            queue.groups.insert(position, group)
            queue.revision += 1
            self.manager._set_queue(queue)
            self._event.set()
            return queue
