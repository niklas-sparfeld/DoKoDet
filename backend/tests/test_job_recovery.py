from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from support.job_participants import FakeParticipant

from dokodetector_backend.job_models import JobConflict, JobOwnershipError, JobStorageError
from dokodetector_backend.job_recovery import JobRecovery
from dokodetector_backend.job_store import JobManager


def request() -> dict:
    return {"type": "fake", "context": {"recording_id": "r1"}, "request": {"input": "a"}}


@pytest.mark.parametrize(
    "point", ["intent", "domain_run", "accepted_use", "participant", "job", "queue", "commit"]
)
def test_acceptance_recovers_each_write(tmp_path: Path, point: str) -> None:
    key = str(uuid4())
    participant = FakeParticipant(tmp_path / "domain")

    def crash(name: str) -> None:
        if name == point:
            raise RuntimeError("simulated crash")

    with (
        JobManager(tmp_path, participant, after_write=crash) as manager,
        pytest.raises(RuntimeError, match="simulated crash"),
    ):
        manager.accept(key, request())
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(key, request())
        assert manager.accept(key, request()).id == job.id
        assert manager.queue().job_ids == [job.id]
        assert participant.verify(job.id, request())
        assert manager.dispatchable() == [job.id]
        with pytest.raises(JobConflict):
            manager.accept(key, {**request(), "request": {"input": "different"}})


def test_recover_lost_queue_and_report_unknown(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), request())
    (tmp_path / "jobs" / "queue.json").unlink()
    with JobManager(tmp_path, participant) as manager:
        assert manager.queue().job_ids == [job.id]


def test_missing_committed_job_is_not_recreated(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), request())
        manager.transition(job.id, "running")
        manager.transition(job.id, "succeeded")
    (tmp_path / "jobs" / job.id / "job.json").unlink()
    with JobManager(tmp_path, participant) as manager:
        assert manager.dispatchable() == []
        assert manager.diagnostics
        assert not (tmp_path / "jobs" / job.id / "job.json").exists()


def test_missing_committed_protection_is_not_recreated(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), request())
    path = tmp_path / "domain" / f"{job.id}.use.json"
    path.unlink()
    with JobManager(tmp_path, participant) as manager:
        assert manager.dispatchable() == []
        assert manager.diagnostics
        assert not path.exists()


def test_invalid_intent_blocks_dispatch_and_acceptance(tmp_path: Path) -> None:

    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        manager.accept(str(uuid4()), request())
        (tmp_path / "jobs" / "intents" / f"{uuid4()}.json").write_text("{}")
        with pytest.raises(JobStorageError):
            manager.dispatchable()
        with pytest.raises(JobStorageError):
            manager.accept(str(uuid4()), request())
        assert manager.diagnostics


def test_recovery_requires_manager_ownership(tmp_path: Path) -> None:
    manager = JobManager(tmp_path, FakeParticipant(tmp_path / "domain"))
    with pytest.raises(JobOwnershipError, match="does not own the root"):
        JobRecovery(manager.persistence.recovery_operations()).recover()
    with pytest.raises(JobOwnershipError, match="does not own the root"):
        manager._recover()
    assert not (tmp_path / "jobs" / "queue.json").exists()


def test_job_logs_survive_active_terminal_concurrent_read_and_restart(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), request())
        manager.transition(job.id, "running")
        manager.append_log(job.id, "active_marker", "active work")
        assert manager.get(job.id).state == "running"
        assert manager.logs(job.id)["entries"][-1].code == "active_marker"

        barrier = Barrier(2)

        def append_batch() -> None:
            barrier.wait()
            for index in range(128):
                manager.append_log(job.id, "concurrent", str(index))

        def read_pages() -> None:
            barrier.wait()
            for _ in range(256):
                page = manager.logs(job.id, after=0, limit=500)
                sequences = [entry.sequence for entry in page["entries"]]
                assert sequences == sorted(set(sequences))

        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(append_batch)
            reader = pool.submit(read_pages)
            writer.result()
            reader.result()

        manager.transition(job.id, "succeeded")
        terminal_logs = manager.logs(job.id, after=0, limit=500)
        assert manager.get(job.id).state == "succeeded"
        assert terminal_logs["entries"][-1].code == "job_succeeded"

    with JobManager(tmp_path, participant) as restarted:
        assert restarted.get(job.id).state == "succeeded"
        entries = restarted.logs(job.id, after=0, limit=500)["entries"]
        assert entries[-1].code == "job_succeeded"
        assert sum(entry.code == "concurrent" for entry in entries) == 128
