from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from support.job_participants import FakeParticipant

import dokodetector_backend.job_persistence as job_persistence_module
from dokodetector_backend.job_models import JobConflict, JobOwnershipError, JobStorageError
from dokodetector_backend.job_recovery import JobRecovery
from dokodetector_backend.job_store import JobManager


def request() -> dict:
    return {"type": "fake", "context": {"recording_id": "r1"}, "request": {"input": "a"}}


@pytest.mark.parametrize(
    "point",
    [
        "intent",
        "domain_run",
        "accepted_use",
        "participant",
        "job_transition_index",
        "job",
        "commit",
    ],
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
        manager.persistence.projection_authority.index.replace_queue(
            manager.queue().model_copy(update={"groups": []}), ready=False
        )
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


@pytest.mark.parametrize(
    ("child_terminal_state", "expected_parent_state"),
    [
        ("succeeded", "queued"),
        ("failed", "queued"),
        ("interrupted", "queued"),
        ("cancelled", "cancelled"),
    ],
)
def test_waiting_parent_recovery_matches_child_terminal_transition(
    tmp_path: Path, child_terminal_state: str, expected_parent_state: str
) -> None:
    class RunParticipant(FakeParticipant):
        def validate(self, request_data: dict) -> None:
            normalized = {**request_data, "request": dict(request_data["request"])}
            normalized["request"].pop("run_id", None)
            super().validate(normalized)

    participant = RunParticipant(tmp_path / "domain")
    child_id = None
    armed = False

    def crash(point: str) -> None:
        if armed and point == "job_transition_committed":
            child = json.loads((tmp_path / "jobs" / child_id / "job.json").read_text())
            if child["state"] == child_terminal_state:
                raise RuntimeError("crash after child terminal commit")

    with JobManager(tmp_path, participant, after_write=crash) as manager:
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "r1"},
                "request": {"input": "parent", "run_id": str(uuid4())},
            },
        )
        other = manager.accept(str(uuid4()), request())
        manager.transition(parent.id, "running")
        manager.transition(parent.id, "waiting")
        child = manager.accept(
            str(uuid4()),
            {
                "type": "fake",
                "context": {"recording_id": "r1"},
                "request": {"input": "first child"},
                "parent_id": parent.id,
                "parent_step_id": "first",
            },
        )
        manager.accept(
            str(uuid4()),
            {
                "type": "fake",
                "context": {"recording_id": "r1"},
                "request": {"input": "next child"},
                "parent_id": parent.id,
                "parent_step_id": "next",
            },
        )
        child_id = child.id
        manager.transition(child.id, "running")
        if child_terminal_state == "cancelled":
            manager.transition(child.id, "cancelling")
        armed = True
        with pytest.raises(RuntimeError, match="crash after child terminal commit"):
            manager.transition(child.id, child_terminal_state)

    with JobManager(tmp_path, participant) as manager:
        assert manager.get(parent.id).state == expected_parent_state
        assert manager.get(child.id).state == child_terminal_state
        if expected_parent_state == "cancelled":
            assert manager.queue().job_ids == [other.id]
        else:
            assert manager.queue().job_ids == [other.id, parent.id]


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


def test_job_logs_survive_active_terminal_concurrent_read_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), request())
        manager.transition(job.id, "running")
        manager.append_log(job.id, "active_marker", "active work")
        assert manager.get(job.id).state == "running"
        assert manager.logs(job.id)["entries"][-1].code == "active_marker"

        replace_started = Event()
        allow_replace = Event()
        read_completed = Event()
        atomic_replace_json = job_persistence_module.atomic_replace_json

        def pause_log_replace(path: Path, payload: object) -> None:
            is_inflight_log = (
                isinstance(payload, list)
                and bool(payload)
                and payload[-1]["code"] == "inflight_marker"
            )
            if Path(path).name == "logs.json" and is_inflight_log:
                replace_started.set()
                if not allow_replace.wait(timeout=5):
                    raise TimeoutError("test did not release the log replacement")
            atomic_replace_json(path, payload)

        monkeypatch.setattr(job_persistence_module, "atomic_replace_json", pause_log_replace)

        def append_batch() -> None:
            manager.append_log(job.id, "inflight_marker", "replacement pending")

        def read_snapshot():
            page = manager.logs(job.id, after=0, limit=500)
            read_completed.set()
            return page

        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(append_batch)
            try:
                assert replace_started.wait(timeout=5)
                reader = pool.submit(read_snapshot)
                assert read_completed.wait(timeout=5)
                visible_during_append = reader.result()
                assert visible_during_append["entries"][-1].code == "active_marker"
            finally:
                allow_replace.set()
            writer.result()
            visible_after_append = manager.logs(job.id, after=0, limit=500)
            assert visible_after_append["entries"][-1].code == "inflight_marker"

        manager.transition(job.id, "succeeded")
        terminal_logs = manager.logs(job.id, after=0, limit=500)
        assert manager.get(job.id).state == "succeeded"
        assert terminal_logs["entries"][-1].code == "job_succeeded"

    with JobManager(tmp_path, participant) as restarted:
        assert restarted.get(job.id).state == "succeeded"
        entries = restarted.logs(job.id, after=0, limit=500)["entries"]
        assert entries[-1].code == "job_succeeded"
        assert sum(entry.code == "inflight_marker" for entry in entries) == 1
