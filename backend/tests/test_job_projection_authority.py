from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from support.job_participants import FakeParticipant

from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.job_models import Job, JobOwnershipError, JobStorageError
from dokodetector_backend.job_store import JobManager
from dokodetector_backend.recording_state_contract import JobProjectionAuthority


def _request() -> dict:
    return {"type": "fake", "context": {"recording_id": "r1"}, "request": {"input": "a"}}


@pytest.mark.parametrize(
    "point",
    [
        "job_transition_prepared",
        "job_transition_record",
        "job_transition_authority",
        "job_transition_committed",
    ],
)
def test_job_authority_transition_recovers_after_each_boundary(tmp_path: Path, point: str) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), _request())
        initial_sequence = manager.projection_authority().sequence

    def crash(name: str) -> None:
        if name == point:
            raise RuntimeError("simulated crash")

    with (
        JobManager(tmp_path, participant, after_write=crash) as manager,
        pytest.raises(RuntimeError, match="simulated crash"),
    ):
        manager.transition(job.id, "running")

    with JobManager(tmp_path, participant) as manager:
        recovered = manager.get(job.id)
        authority = manager.projection_authority()
        assert recovered.state == "interrupted"
        assert authority.sequence == initial_sequence + 2
        assert not (tmp_path / "jobs" / "recording-projections" / "job-transition.json").exists()


def test_job_transition_reader_waits_for_authority_commit(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    prepared = Event()
    release = Event()
    pause_transition = False

    def pause(name: str) -> None:
        if pause_transition and name == "job_transition_prepared":
            prepared.set()
            assert release.wait(5)

    with JobManager(tmp_path, participant, after_write=pause) as manager:
        job = manager.accept(str(uuid4()), _request())
        pause_transition = True
        with ThreadPoolExecutor(max_workers=2) as pool:
            writing = pool.submit(manager.transition, job.id, "running")
            assert prepared.wait(5)
            reading = pool.submit(manager.get, job.id)
            assert not reading.done()
            release.set()
            assert writing.result(timeout=5).state == "running"
            assert reading.result(timeout=5).state == "running"
        assert manager.projection_authority().sequence == 3


def test_job_authority_persists_across_restart_and_manager_lock(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        first = manager.projection_authority()
        with pytest.raises(JobOwnershipError), JobManager(tmp_path, participant):
            pass
        manager.accept(str(uuid4()), _request())
        after_write = manager.projection_authority()
        assert after_write.sequence == first.sequence + 1

    with JobManager(tmp_path, participant) as manager:
        restarted = manager.projection_authority()
        assert restarted.manager_id == first.manager_id
        assert restarted.epoch == first.epoch
        assert restarted.sequence == after_write.sequence


def test_job_transition_rejects_unrelated_record_change(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), _request())

    def crash(name: str) -> None:
        if name == "job_transition_prepared":
            raise RuntimeError("simulated crash")

    with (
        JobManager(tmp_path, participant, after_write=crash) as manager,
        pytest.raises(RuntimeError, match="simulated crash"),
    ):
        manager.transition(job.id, "running")

    job_path = tmp_path / "jobs" / job.id / "job.json"
    changed = Job.model_validate_json(job_path.read_bytes())
    changed.label = "changed outside the transition"
    atomic_replace_json(job_path, changed.model_dump(mode="json"))
    with pytest.raises(JobStorageError, match="job record conflicts"):
        JobManager(tmp_path, participant).__enter__()


def test_job_authority_conflict_does_not_mutate_job_record(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), _request())
        original_job = (tmp_path / "jobs" / job.id / "job.json").read_bytes()

    def crash(name: str) -> None:
        if name == "job_transition_prepared":
            raise RuntimeError("simulated crash")

    with (
        JobManager(tmp_path, participant, after_write=crash) as manager,
        pytest.raises(RuntimeError, match="simulated crash"),
    ):
        manager.transition(job.id, "running")

    authority_path = tmp_path / "jobs" / "recording-projections" / "authority.json"
    authority = JobProjectionAuthority.model_validate_json(authority_path.read_bytes())
    conflict = authority.model_copy(update={"sequence": authority.sequence + 2})
    atomic_replace_json(authority_path, conflict.model_dump(mode="json"))

    with pytest.raises(JobStorageError, match="job authority conflicts"):
        JobManager(tmp_path, participant).__enter__()
    assert (tmp_path / "jobs" / job.id / "job.json").read_bytes() == original_job
