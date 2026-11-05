from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from dokodetector_backend.job_store import (
    FakeParticipant,
    JobConflict,
    JobManager,
    JobOwnershipError,
    JobStateError,
)


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


def test_owner_and_terminal_transition(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        with pytest.raises(JobOwnershipError), JobManager(tmp_path, participant):
            pass
        job = manager.accept(str(uuid4()), request())
        manager.transition(job.id, "running")
        manager.transition(job.id, "succeeded")
        with pytest.raises(JobStateError):
            manager.transition(job.id, "running")
        assert manager.queue().job_ids == []


def test_damaged_participant_never_dispatches(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), request())
        (tmp_path / "domain" / f"{job.id}.json").write_text("{}")
        assert manager.dispatchable() == []
        assert manager.diagnostics


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


def test_invalid_request_creates_no_intent(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        with pytest.raises(ValueError):
            manager.accept(str(uuid4()), {"type": "", "context": {}, "request": {}})
        assert not list((tmp_path / "jobs" / "intents").glob("*.json"))


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
    from dokodetector_backend.job_store import JobStorageError

    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        manager.accept(str(uuid4()), request())
        (tmp_path / "jobs" / "intents" / f"{uuid4()}.json").write_text("{}")
        with pytest.raises(JobStorageError):
            manager.dispatchable()
        with pytest.raises(JobStorageError):
            manager.accept(str(uuid4()), request())
        assert manager.diagnostics


def test_invalid_transition_does_not_change_job(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), request())
        with pytest.raises(JobStateError):
            manager.transition(job.id, "succeeded")
        assert manager.get(job.id) == job
        assert manager.dispatchable() == [job.id]


def test_owner_lock_applies_across_processes(tmp_path: Path) -> None:
    import subprocess
    import sys

    participant = FakeParticipant(tmp_path / "domain")
    code = (
        "from pathlib import Path\n"
        "from dokodetector_backend.job_store import JobManager, FakeParticipant\n"
        "from dokodetector_backend.job_store import JobOwnershipError\n"
        "import sys\n"
        "root = Path(sys.argv[1])\n"
        "try:\n"
        "    with JobManager(root, FakeParticipant(root / 'domain')): pass\n"
        "except JobOwnershipError:\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n"
    )
    with JobManager(tmp_path, participant):
        result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=False)
    assert result.returncode == 0
