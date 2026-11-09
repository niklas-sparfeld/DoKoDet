from __future__ import annotations

import sqlite3
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
        "job_transition_index",
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
        assert manager.queue().job_ids == []
        assert authority.sequence == initial_sequence + 2
        index_state = manager.persistence.projection_authority.index.state(authority, "r1")
        assert index_state["global_sequence"] == authority.sequence
        assert index_state["recording_sequence"] == 3
        assert index_state["active_count"] == 0
        with sqlite3.connect(
            tmp_path / "jobs" / "recording-projections" / "active-jobs.sqlite3"
        ) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM active_jobs WHERE recording_id = 'r1'"
            ).fetchone() == (0,)
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
            queue_reading = pool.submit(manager.queue)
            assert not reading.done()
            assert not queue_reading.done()
            release.set()
            assert writing.result(timeout=5).state == "running"
            assert reading.result(timeout=5).state == "running"
            assert queue_reading.result(timeout=5).job_ids == []
        authority = manager.projection_authority()
        assert authority.sequence == 3
        index_state = manager.persistence.projection_authority.index.state(authority, "r1")
        assert index_state == {
            "ready": True,
            "global_sequence": 3,
            "recording_sequence": 2,
            "active_count": 1,
        }
        with sqlite3.connect(
            tmp_path / "jobs" / "recording-projections" / "active-jobs.sqlite3"
        ) as connection:
            query_plan = connection.execute(
                "EXPLAIN QUERY PLAN SELECT job_id FROM active_jobs WHERE recording_id = ? "
                "ORDER BY updated_at DESC, job_id DESC LIMIT 20",
                ("r1",),
            ).fetchall()
            assert any("active_jobs_page_order" in str(row) for row in query_plan)
            assert connection.execute(
                "SELECT status FROM active_jobs WHERE recording_id = 'r1' AND job_id = ?",
                (job.id,),
            ).fetchone() == ("running",)


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


def test_identical_job_write_recovers_after_authority_publication(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")

    def crash(name: str) -> None:
        if name == "job_transition_authority":
            raise RuntimeError("simulated crash")

    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), _request())
        sequence_before = manager.projection_authority().sequence

    with (
        JobManager(tmp_path, participant, after_write=crash) as manager,
        pytest.raises(RuntimeError, match="simulated crash"),
    ):
        manager._write_job(job)

    with JobManager(tmp_path, participant) as manager:
        assert manager.get(job.id) == job
        assert manager.projection_authority().sequence == sequence_before + 1
        assert not (tmp_path / "jobs" / "recording-projections" / "job-transition.json").exists()


@pytest.mark.parametrize(
    "point",
    ["job_transition_prepared", "job_transition_record", "job_transition_index"],
)
def test_unicode_job_digest_survives_transition_recovery(tmp_path: Path, point: str) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), _request())
        job.label = "Döko 🂡"
        manager._write_job(job)

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
        assert recovered.label == "Döko 🂡"
        assert recovered.state == "interrupted"
        authority = manager.projection_authority()
        assert (
            manager.persistence.projection_authority.index.state(authority, "r1")["active_count"]
            == 0
        )


def test_ordinary_job_transitions_do_not_scan_committed_jobs(tmp_path: Path, monkeypatch) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        first = manager.accept(str(uuid4()), _request())
        first_authority = manager.projection_authority()
        first_index = manager.persistence.projection_authority.index.state(first_authority, "r1")

        def fail_scan():
            raise AssertionError("ordinary job transition scanned committed jobs")

        monkeypatch.setattr(manager.persistence, "list_jobs", fail_scan)
        manager.transition(first.id, "running")
        second = manager.accept(
            str(uuid4()),
            {"type": "fake", "context": {"recording_id": "r2"}, "request": {"input": "b"}},
        )
        authority = manager.projection_authority()
        r1 = manager.persistence.projection_authority.index.state(authority, "r1")
        r2 = manager.persistence.projection_authority.index.state(authority, "r2")
        assert r1["recording_sequence"] == first_index["recording_sequence"] + 1
        assert r2["recording_sequence"] == 1
        assert r1["active_count"] == 1
        assert r2["active_count"] == 1
        assert manager.get(second.id).state == "queued"


def test_child_transition_uses_bounded_queue_and_dependency_lookups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "r1"},
                "request": {"input": "parent"},
            },
        )
        manager.transition(parent.id, "running")
        manager.transition(parent.id, "waiting")
        children = [
            manager.accept(
                str(uuid4()),
                {
                    "type": "fake",
                    "context": {"recording_id": "r1"},
                    "request": {"input": str(i)},
                    "parent_id": parent.id,
                    "parent_step_id": str(i),
                },
            )
            for i in range(20)
        ]

        def fail_history_scan():
            raise AssertionError("child transition scanned intent history")

        monkeypatch.setattr(manager.persistence, "_intents", fail_history_scan)
        intent_reads = []
        read_intent = manager.persistence._read_intent

        def count_intent_reads(job_id: str):
            intent_reads.append(job_id)
            return read_intent(job_id)

        monkeypatch.setattr(manager.persistence, "_read_intent", count_intent_reads)
        manager.transition(children[0].id, "running")
        assert intent_reads == [children[0].id, children[0].id]
        next_sequence = manager.persistence.projection_authority.index.parent_child_sequence(
            children[1].id
        )[1]
        assert manager.persistence.projection_authority.index.preceding_child_not_succeeded(
            parent.id, next_sequence
        )
        manager.transition(children[0].id, "succeeded")
        assert not manager.persistence.projection_authority.index.preceding_child_not_succeeded(
            parent.id, next_sequence
        )
        with sqlite3.connect(
            tmp_path / "jobs" / "recording-projections" / "active-jobs.sqlite3"
        ) as connection:
            query_plan = connection.execute(
                "EXPLAIN QUERY PLAN SELECT 1 FROM parent_children WHERE parent_id = ? "
                "AND sequence < ? AND state != 'succeeded' ORDER BY sequence LIMIT 1",
                (parent.id, next_sequence),
            ).fetchall()
            assert any("parent_children_dependency" in str(row) for row in query_plan)
            queue_plan = connection.execute(
                "EXPLAIN QUERY PLAN SELECT child_id FROM queue_children WHERE parent_id = ? "
                "ORDER BY sequence LIMIT 1",
                (parent.id,),
            ).fetchall()
            assert any("queue_child_order" in str(row) for row in queue_plan)


def test_missing_queue_authority_table_fails_closed(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        manager.accept(str(uuid4()), _request())
    with sqlite3.connect(
        tmp_path / "jobs" / "recording-projections" / "active-jobs.sqlite3"
    ) as connection:
        connection.execute("DROP TABLE queue_children")
    with pytest.raises(JobStorageError, match="queue authority schema is incomplete"):
        JobManager(tmp_path, participant).__enter__()


def test_corrupt_active_index_row_blocks_write_before_job_mutation(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job = manager.accept(str(uuid4()), _request())
        job_path = tmp_path / "jobs" / job.id / "job.json"
        before = job_path.read_bytes()
        index_path = tmp_path / "jobs" / "recording-projections" / "active-jobs.sqlite3"

    with sqlite3.connect(index_path) as connection:
        connection.execute(
            "UPDATE active_jobs SET status = 'running' WHERE recording_id = 'r1' AND job_id = ?",
            (job.id,),
        )

    with (
        JobManager(tmp_path, participant) as manager,
        pytest.raises(JobStorageError, match="active job index row conflicts"),
    ):
        manager.transition(job.id, "running")
    assert job_path.read_bytes() == before
    assert not (index_path.parent / "job-transition.json").exists()


def test_corrupt_active_index_database_fails_closed(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        manager.accept(str(uuid4()), _request())
    index_path = tmp_path / "jobs" / "recording-projections" / "active-jobs.sqlite3"
    index_path.write_bytes(b"not sqlite")
    with pytest.raises(JobStorageError, match="job recording index"):
        JobManager(tmp_path, participant).__enter__()


def test_missing_active_index_order_does_not_reinitialize_as_valid(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        manager.accept(str(uuid4()), _request())
    index_path = tmp_path / "jobs" / "recording-projections" / "active-jobs.sqlite3"
    with sqlite3.connect(index_path) as connection:
        connection.execute("DROP INDEX active_jobs_page_order")
    with pytest.raises(JobStorageError, match="schema is incomplete"):
        JobManager(tmp_path, participant).__enter__()


def test_legacy_job_root_stays_not_ready_without_scanning_on_write(
    tmp_path: Path, monkeypatch
) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    intents = tmp_path / "jobs" / "intents"
    intents.mkdir(parents=True)
    with JobManager(tmp_path, participant) as manager:
        initial = manager.projection_authority()
        index = manager.persistence.projection_authority.index
        assert index.state(initial)["ready"] is False

        def fail_scan():
            raise AssertionError("legacy job write scanned history")

        monkeypatch.setattr(manager.persistence, "list_jobs", fail_scan)
        job = manager.accept(str(uuid4()), _request())
        authority = manager.projection_authority()
        state = index.state(authority, "r1")
        assert state["ready"] is False
        assert state["recording_sequence"] == 1
        assert state["active_count"] is None
        with sqlite3.connect(
            tmp_path / "jobs" / "recording-projections" / "active-jobs.sqlite3"
        ) as connection:
            assert connection.execute(
                "SELECT status FROM active_jobs WHERE recording_id = 'r1' AND job_id = ?",
                (job.id,),
            ).fetchone() == ("queued",)
