from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from support.job_participants import FakeParticipant

from dokodetector_backend.job_models import JobOwnershipError, JobStateError
from dokodetector_backend.job_store import JobManager


def request() -> dict:
    return {"type": "fake", "context": {"recording_id": "r1"}, "request": {"input": "a"}}


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


def test_invalid_request_creates_no_intent(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        with pytest.raises(ValueError):
            manager.accept(str(uuid4()), {"type": "", "context": {}, "request": {}})
        assert not list((tmp_path / "jobs" / "intents").glob("*.json"))


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
        "import sys\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "from dokodetector_backend.job_store import JobManager\n"
        "from support.job_participants import FakeParticipant\n"
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
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path), str(Path(__file__).parent)], check=False
        )
    assert result.returncode == 0
