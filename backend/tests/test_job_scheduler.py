from __future__ import annotations

import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from dokodetector_backend.job_scheduler import (
    Budget,
    Claims,
    JobScheduler,
    QueueRevisionConflict,
)
from dokodetector_backend.job_store import FakeParticipant, JobManager


def enqueue(manager: JobManager, name: str) -> str:
    return manager.accept(
        str(uuid4()),
        {"type": "fake", "context": {"recording_id": "r"}, "request": {"input": name}},
    ).id


def until(predicate: object) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return
        time.sleep(0.01)
    pytest.fail("scheduler did not reach the expected state")


def test_single_slot_and_actual_claim(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    entered = threading.Event()
    release = threading.Event()
    with JobManager(tmp_path, participant) as manager:
        first, second = enqueue(manager, "first"), enqueue(manager, "second")

        def handler(job: object, budget: Claims) -> None:
            assert budget.cpu == 1
            entered.set()
            assert release.wait(3)

        with JobScheduler(manager, handler, lambda job: Claims()):
            assert entered.wait(2)
            assert manager.get(first).state == "running"
            assert manager.get(second).state == "queued"
            until(lambda: manager.get(second).waiting_reason is not None)
            release.set()
            until(lambda: manager.get(second).state == "succeeded")
            assert manager.get(first).state == "succeeded"


def test_blocked_head_and_resource_reservation(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    release = threading.Event()
    starts: list[str] = []
    with JobManager(tmp_path, participant) as manager:
        first = enqueue(manager, "gpu-active")
        blocked = enqueue(manager, "input-blocked")
        reserved = enqueue(manager, "gpu-waiting")
        bypass = enqueue(manager, "cpu")
        later = enqueue(manager, "gpu-later")

        def handler(job: object, budget: Claims) -> None:
            starts.append(job.id)  # type: ignore[attr-defined]
            assert release.wait(3)

        def claims(job: object) -> Claims:
            return Claims(accelerator=1 if "gpu" in job.request["input"] else 0)  # type: ignore[attr-defined]

        with JobScheduler(
            manager,
            handler,
            claims,
            budget=Budget(slots=3, cpu=3, accelerator=1),
            ready=lambda job: "needs input" if job.id == blocked else None,
        ):
            until(lambda: len(starts) == 2)
            assert set(starts) == {first, bypass}
            assert manager.get(blocked).waiting_reason == "needs input"
            assert manager.get(reserved).state == "queued"
            assert manager.get(later).state == "queued"
            release.set()
            until(lambda: manager.get(later).state == "succeeded")
            assert starts.index(reserved) < starts.index(later)


def test_queue_moves_revision_and_restart(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        first, second, third = [enqueue(manager, str(i)) for i in range(3)]
        scheduler = JobScheduler(manager, lambda job, budget: None, lambda job: Claims())
        initial = manager.queue()
        moved = scheduler.move(third, first, initial.revision)
        assert moved.job_ids == [third, first, second]
        with pytest.raises(QueueRevisionConflict) as conflict:
            scheduler.move(first, None, initial.revision)
        assert conflict.value.queue.job_ids == moved.job_ids
    with JobManager(tmp_path, participant) as manager:
        assert manager.queue().job_ids == [third, first, second]


def test_second_scheduler_cannot_claim_same_manager(tmp_path: Path) -> None:
    from dokodetector_backend.job_store import JobStateError

    with JobManager(tmp_path, FakeParticipant(tmp_path / "domain")) as manager:
        first = JobScheduler(manager, lambda job, budget: None, lambda job: Claims())
        second = JobScheduler(manager, lambda job, budget: None, lambda job: Claims())
        with first, pytest.raises(JobStateError), second:
            pass


def test_waiting_parent_group_keeps_children_and_order_after_restart(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        first = enqueue(manager, "first")
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "r"},
                "request": {"input": "parent"},
            },
        ).id
        manager.transition(parent, "running")
        manager.transition(parent, "waiting")
        children = []
        for step in ("one", "two"):
            child = manager.accept(
                str(uuid4()),
                {
                    "type": "fake",
                    "context": {"recording_id": "r"},
                    "request": {"input": step},
                    "parent_id": parent,
                    "parent_step_id": step,
                },
            )
            children.append(child.id)
        scheduler = JobScheduler(manager, lambda job, budget: None, lambda job: Claims())
        queue = scheduler.move(parent, first, manager.queue().revision)
        assert queue.job_ids == [parent, first]
        assert queue.groups[0].child_job_ids == children
        assert manager.dispatchable() == [children[0], first]
    with JobManager(tmp_path, participant) as manager:
        assert manager.queue().job_ids == [parent, first]
        assert manager.queue().groups[0].child_job_ids == children
        assert manager.dispatchable() == [children[0], first]


def test_failed_child_blocks_later_child(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "r"},
                "request": {"input": "parent"},
            },
        ).id
        manager.transition(parent, "running")
        manager.transition(parent, "waiting")
        children = [
            manager.accept(
                str(uuid4()),
                {
                    "type": "fake",
                    "context": {"recording_id": "r"},
                    "request": {"input": name},
                    "parent_id": parent,
                    "parent_step_id": name,
                },
            ).id
            for name in ("one", "two")
        ]

        def handler(job: object, budget: Claims) -> None:
            raise RuntimeError("failed")

        with JobScheduler(manager, handler, lambda job: Claims()):
            until(lambda: manager.get(children[0]).state == "failed")
            until(lambda: manager.get(children[1]).waiting_reason is not None)
            assert manager.get(children[1]).state == "queued"


def test_domain_locks_and_cpu_budget(tmp_path: Path) -> None:
    release = threading.Event()
    started: list[str] = []
    with JobManager(tmp_path, FakeParticipant(tmp_path / "domain")) as manager:
        first, same_lock, independent = [enqueue(manager, name) for name in ("a", "b", "c")]

        def handler(job: object, allocation: Claims) -> None:
            started.append(job.id)  # type: ignore[attr-defined]
            assert allocation.cpu == 2
            assert release.wait(3)

        def claims(job: object) -> Claims:
            lock = "recording:r:events" if job.id in {first, same_lock} else "other"  # type: ignore[attr-defined]
            return Claims(cpu=2, locks=(lock,))

        with JobScheduler(manager, handler, claims, budget=Budget(slots=3, cpu=4)):
            until(lambda: len(started) == 2)
            assert set(started) == {first, independent}
            assert manager.get(same_lock).state == "queued"
            until(lambda: manager.get(same_lock).waiting_reason is not None)
            release.set()
            until(lambda: manager.get(same_lock).state == "succeeded")


def test_unattainable_claim_does_not_block_independent_work(tmp_path: Path) -> None:
    with JobManager(tmp_path, FakeParticipant(tmp_path / "domain")) as manager:
        too_large, fits = enqueue(manager, "large"), enqueue(manager, "fits")
        with JobScheduler(
            manager,
            lambda job, budget: None,
            lambda job: Claims(cpu=2 if job.id == too_large else 1),
        ):
            until(lambda: manager.get(fits).state == "succeeded")
            assert manager.get(too_large).state == "queued"
            assert "exceeds" in (manager.get(too_large).waiting_reason or "")


def test_late_child_joins_moved_group(tmp_path: Path) -> None:
    with JobManager(tmp_path, FakeParticipant(tmp_path / "domain")) as manager:
        first = enqueue(manager, "first")
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "r"},
                "request": {"input": "parent"},
            },
        ).id
        manager.transition(parent, "running")
        manager.transition(parent, "waiting")
        scheduler = JobScheduler(manager, lambda job, budget: None, lambda job: Claims())
        scheduler.move(parent, first, manager.queue().revision)
        child = manager.accept(
            str(uuid4()),
            {
                "type": "fake",
                "context": {"recording_id": "r"},
                "request": {"input": "child"},
                "parent_id": parent,
                "parent_step_id": "step",
            },
        ).id
        assert manager.queue().job_ids == [parent, first]
        assert manager.queue().groups[0].child_job_ids == [child]


@pytest.mark.parametrize(
    "point", ["intent", "domain_run", "accepted_use", "job", "queue", "commit"]
)
def test_child_acceptance_recovers_in_parent_group(tmp_path: Path, point: str) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "r"},
                "request": {"input": "parent"},
            },
        ).id
        manager.transition(parent, "running")
        manager.transition(parent, "waiting")
    key = str(uuid4())
    child_request = {
        "type": "fake",
        "context": {"recording_id": "r"},
        "request": {"input": "child"},
        "parent_id": parent,
        "parent_step_id": "s",
    }

    def crash(name: str) -> None:
        if name == point:
            raise RuntimeError("crash")

    with (
        JobManager(tmp_path, participant, after_write=crash) as manager,
        pytest.raises(RuntimeError, match="crash"),
    ):
        manager.accept(key, child_request)
    with JobManager(tmp_path, participant) as manager:
        child = manager.accept(key, child_request)
        assert manager.queue().job_ids == [parent]
        assert manager.queue().groups[0].child_job_ids == [child.id]
        assert manager.dispatchable() == [child.id]
