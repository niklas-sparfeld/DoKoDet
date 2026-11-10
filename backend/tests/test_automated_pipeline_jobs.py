from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from dokodetector_backend.automated_pipeline_contracts import StageDefinition
from dokodetector_backend.automated_pipeline_jobs import AutomatedPipelineJobParticipant
from dokodetector_backend.automated_pipeline_run import AutomatedPipelineRunStore
from dokodetector_backend.job_models import Job
from dokodetector_backend.job_scheduler import Claims, JobScheduler
from dokodetector_backend.job_store import JobManager


class _RunStore:
    def __init__(self, document: dict) -> None:
        self.document = document

    def update(self, _run_id: str, mutate) -> dict:
        mutate(self.document)
        return self.document

    def finish(self, _run_id: str, *, status: str) -> dict:
        self.document["status"] = status
        return self.document

    def resumable(self) -> list[dict]:
        return [self.document] if self.document["status"] in {"accepted", "running"} else []


class _RunService:
    def __init__(self, document: dict) -> None:
        self.store = _RunStore(document)
        self.document = document

    def read(self, _run_id: str) -> dict:
        return self.document


class _Registry:
    def __init__(self, parent: AutomatedPipelineJobParticipant) -> None:
        self.parent = parent

    def normalize(self, request: dict) -> dict:
        return request

    def validate(self, request: dict) -> None:
        if request["type"] == "automated_pipeline":
            self.parent.validate(request)
        elif request["type"] == "fake":
            if set(request["request"]) != {"input"}:
                raise ValueError("invalid fixture child request")
        else:
            raise ValueError("unknown fixture job type")

    def prepare(self, _job_id: str, _request: dict, _after_write) -> None:
        return None

    def verify(self, _job_id: str, request: dict) -> bool:
        self.validate(request)
        return True

    @staticmethod
    def verify_publication(_job: Job, results: list[dict]) -> bool:
        return bool(results)

    def reconcile(self, manager: JobManager) -> None:
        self.parent.reconcile(manager.list_jobs())

    def job_transitioned(self, job: Job, manager: JobManager) -> None:
        self.parent.job_transitioned(job, manager)


def _document(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "recording_id": "recording-1",
        "status": "accepted",
        "source": {"video_sha256": "a" * 64},
        "request": {
            "stage_requests": {
                name: {"configuration": {"stage": name}}
                for name in (
                    "event_proposals",
                    "visible_card_and_pile_proposals",
                    "card_scene_and_calibration",
                    "visual_identity_proposals",
                    "table_observations",
                )
            },
            "session_id": "session-1",
            "round_id": "round-1",
            "round_context": {"round_id": "round-1"},
            "rules_version": "v1",
            "search": {
                "max_missing_plays": 1,
                "max_hypotheses": 16,
                "max_search_nodes": 1000,
            },
        },
        "stages": [
            {
                "name": name,
                "status": "pending",
                "run_id": None,
                "child_job_id": None,
                "input_revision_ids": [],
                "output_revision_ids": [],
                "failure": None,
            }
            for name in (
                "event_proposals",
                "visible_card_and_pile_proposals",
                "card_scene_and_calibration",
                "visual_identity_proposals",
                "table_observations",
                "reconstruction",
            )
        ],
    }


def _participant(run_id: str):
    document = _document(run_id)
    service = _RunService(document)
    participant = AutomatedPipelineJobParticipant(service, object())
    participant._child_request = lambda _parent, definition, _inputs: {
        "type": "fake",
        "context": {"recording_id": "recording-1"},
        "request": {"input": f"stage:{definition.name}"},
    }
    return document, service, participant


def _manager(
    tmp_path: Path, participant: AutomatedPipelineJobParticipant, *, after_write=None
) -> JobManager:
    return JobManager(
        tmp_path,
        _Registry(participant),
        after_write=after_write,
        verify_publication=_Registry.verify_publication,
    )


def _wait_for(predicate, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def test_mixed_recording_pipeline_yields_to_an_independent_leaf_job(tmp_path: Path) -> None:
    run_id = str(uuid4())
    document, _service, participant = _participant(run_id)
    started: list[str] = []
    active = 0
    maximum_active = 0
    guard = threading.Lock()

    with _manager(tmp_path, participant) as manager:
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "recording-1"},
                "request": {"run_id": run_id},
            },
        )
        independent = manager.accept(
            str(uuid4()),
            {
                "type": "fake",
                "context": {"recording_id": "recording-2"},
                "request": {"input": "independent"},
            },
        )

        def handle(job: Job, _claims: Claims, token) -> None:
            nonlocal active, maximum_active
            with guard:
                active += 1
                maximum_active = max(maximum_active, active)
                started.append(job.request.get("input", "parent"))
            try:
                if job.type == "automated_pipeline":
                    participant.handle(job, Claims(), token, manager)
                    return
                token.check()
                current = manager.get(job.id)
                current.results = [
                    {
                        "kind": "pipeline_revision",
                        "id": f"revision-{job.id}",
                        "digest": "b" * 64,
                        "available": True,
                    }
                ]
                manager._write_job(current)
            finally:
                with guard:
                    active -= 1

        with JobScheduler(manager, handle, lambda _job: Claims(), budget=None):
            _wait_for(
                lambda: manager.get(parent.id).state in {"succeeded", "failed"},
            )
            assert manager.get(parent.id).state == "succeeded", str(manager.get(parent.id).failure)

        children = [job for job in manager.list_jobs() if job.parent_id == parent.id]
        assert len(children) == 6
        assert all(child.state == "succeeded" for child in children)
        assert maximum_active == 1
        assert started.index("independent") < started.index("stage:visible_card_and_pile_proposals")
        assert manager.get(independent.id).state == "succeeded"
        assert manager.get(parent.id).context["recording_id"] == "recording-1"
        assert manager.get(independent.id).context["recording_id"] == "recording-2"
        revisions_by_stage = {
            child.parent_step_id: str(child.results[0]["id"])
            for child in children
            if child.parent_step_id is not None and child.results
        }
        stages_by_name = {row["name"]: row for row in document["stages"]}
        assert stages_by_name["visible_card_and_pile_proposals"]["input_revision_ids"] == [
            revisions_by_stage["event_proposals"]
        ]
        assert stages_by_name["table_observations"]["input_revision_ids"] == [
            revisions_by_stage["event_proposals"],
            revisions_by_stage["visible_card_and_pile_proposals"],
            revisions_by_stage["visual_identity_proposals"],
        ]
        assert stages_by_name["reconstruction"]["input_revision_ids"] == [
            revisions_by_stage["table_observations"]
        ]
        assert all(stages_by_name[name]["child_job_id"] for name in stages_by_name)
        assert document["status"] == "complete"


def test_restart_recovers_unlinked_child_and_completes_pipeline(tmp_path: Path) -> None:
    run_id = str(uuid4())
    document, _service, participant = _participant(run_id)
    armed = False

    def crash_after_child_acceptance(point: str) -> None:
        if armed and point == "commit":
            raise RuntimeError("crash after child acceptance commit")

    with _manager(tmp_path, participant, after_write=crash_after_child_acceptance) as manager:
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "recording-1"},
                "request": {"run_id": run_id},
            },
        )
        manager.transition(parent.id, "running")
        armed = True
        with pytest.raises(RuntimeError, match="crash after child acceptance commit"):
            participant.handle(
                manager.get(parent.id),
                Claims(),
                type("Token", (), {"check": lambda _self: None})(),
                manager,
            )
        parent = manager.get(parent.id)
        assert parent.phase == "event_proposals"
        assert parent.steps[0].child_job_id is None
        before = [job for job in manager.list_jobs() if job.parent_id == parent.id]
        assert len(before) == 1
        child_id = before[0].id
        assert before[0].state == "queued"

    with _manager(tmp_path, participant) as manager:
        parent = manager.get(parent.id)
        assert parent.steps[0].child_job_id == child_id

        def handle(job: Job, _claims: Claims, token) -> None:
            if job.type == "automated_pipeline":
                participant.handle(job, Claims(), token, manager)
            else:
                current = manager.get(job.id)
                current.results = [{"id": f"revision-{job.id}"}]
                manager._write_job(current)

        with JobScheduler(manager, handle, lambda _job: Claims()):
            _wait_for(
                lambda: manager.get(parent.id).state in {"succeeded", "failed"},
            )
            assert manager.get(parent.id).state == "succeeded", (
                manager.get(parent.id).model_dump(),
                manager.diagnostics,
            )
        assert len([job for job in manager.list_jobs() if job.parent_id == parent.id]) == 6
        assert document["status"] == "complete"


def test_later_stage_recovery_restores_lineage_status_and_reuse(tmp_path: Path) -> None:
    run_id = str(uuid4())
    document, _service, participant = _participant(run_id)
    armed = False
    manager_ref: JobManager | None = None

    def crash_after_later_acceptance(point: str) -> None:
        if not armed or point != "commit" or manager_ref is None:
            return
        accepted = next(
            item
            for item in manager_ref._intents()
            if item.job.parent_step_id == "visible_card_and_pile_proposals"
        )
        if accepted.committed:
            raise RuntimeError("crash after later-stage acceptance commit")

    with _manager(tmp_path, participant, after_write=crash_after_later_acceptance) as manager:
        manager_ref = manager
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "recording-1"},
                "request": {"run_id": run_id},
            },
        )
        manager.transition(parent.id, "running")
        token = type("Token", (), {"check": lambda _self: None})()
        participant.handle(manager.get(parent.id), Claims(), token, manager)
        first_child = next(
            job for job in manager.list_jobs() if job.parent_step_id == "event_proposals"
        )
        manager.transition(first_child.id, "running")
        first_child = manager.get(first_child.id)
        first_child.results = [{"id": "event-revision"}]
        manager._write_job(first_child)
        manager.transition(first_child.id, "succeeded")
        manager.transition(parent.id, "running")
        armed = True
        with pytest.raises(RuntimeError, match="crash after later-stage acceptance commit"):
            participant.handle(manager.get(parent.id), Claims(), token, manager)
        second_child = next(
            job
            for job in manager.list_jobs()
            if job.parent_step_id == "visible_card_and_pile_proposals"
        )
        assert document["stages"][1]["input_revision_ids"] == []

    with _manager(tmp_path, participant) as manager:
        manager.participant.reconcile(manager)
        parent = manager.get(parent.id)
        second_child_id = next(
            step.child_job_id
            for step in parent.steps
            if step.id == "visible_card_and_pile_proposals"
        )
        assert second_child_id == second_child.id
        stage = document["stages"][1]
        assert stage["input_revision_ids"] == ["event-revision"]
        assert stage["child_job_id"] == second_child.id
        assert stage["status"] == "queued"

        manager.transition(second_child.id, "running")
        assert document["status"] == "running"
        assert stage["status"] == "running"
        assert stage["input_revision_ids"] == ["event-revision"]
        child = manager.get(second_child.id)
        child.results = [{"id": "visible-revision"}]
        manager._write_job(child)
        manager.transition(child.id, "succeeded")

        manager.transition(parent.id, "running")
        parent = manager.get(parent.id)
        plan = participant._stage_plan(document)
        definition = next(item for item in plan if item.name == "visible_card_and_pile_proposals")
        inputs = participant._resolve_inputs(manager, parent, definition)
        candidate = participant._child_request(parent, definition, inputs)
        reused = participant._reuse_completed_stage(
            run_id, manager, parent, definition, inputs, candidate
        )
        assert reused is not None
        assert reused.id == second_child.id

        participant.handle(parent, Claims(), token, manager)
        assert document["stages"][1]["input_revision_ids"] == ["event-revision"]
        assert any(
            job.parent_step_id == "card_scene_and_calibration" for job in manager.list_jobs()
        )


def test_parent_cancel_waits_for_owned_child_to_stop(tmp_path: Path) -> None:
    run_id = str(uuid4())
    _document_value, _service, participant = _participant(run_id)
    with _manager(tmp_path, participant) as manager:
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "recording-1"},
                "request": {"run_id": run_id},
            },
        )
        manager.transition(parent.id, "running")
        participant.handle(
            parent, Claims(), type("Token", (), {"check": lambda _self: None})(), manager
        )
        child = next(job for job in manager.list_jobs() if job.parent_id == parent.id)
        manager.transition(child.id, "running")
        manager.cancel(parent.id)
        assert manager.get(parent.id).state == "cancelling"
        assert manager.get(child.id).state == "cancelling"
        manager.transition(child.id, "cancelled")
        assert manager.get(parent.id).state == "cancelled"


def test_succeeded_child_without_complete_result_does_not_complete_stage(tmp_path: Path) -> None:
    run_id = str(uuid4())
    document, _service, participant = _participant(run_id)
    participant._child_is_complete = lambda _child: False
    with _manager(tmp_path, participant) as manager:
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "recording-1"},
                "request": {"run_id": run_id},
            },
        )
        manager.transition(parent.id, "running")
        participant.handle(
            manager.get(parent.id),
            Claims(),
            type("Token", (), {"check": lambda _self: None})(),
            manager,
        )
        child = next(job for job in manager.list_jobs() if job.parent_id == parent.id)
        manager.transition(child.id, "running")
        manager.transition(child.id, "succeeded")
        assert document["stages"][0]["status"] == "failed"
        assert document["stages"][0]["child_job_id"] == child.id


def test_interrupted_child_stage_of_cancelled_parent_recovers_status_and_lineage(
    tmp_path: Path,
) -> None:
    run_id = str(uuid4())
    run_store = AutomatedPipelineRunStore(tmp_path / "pipeline-runs")
    run_store.create(_document(run_id))

    class _PersistedService:
        store = run_store

        def read(self, requested_run_id: str) -> dict:
            return self.store.get(requested_run_id)

    service = _PersistedService()
    participant = AutomatedPipelineJobParticipant(service, object())
    participant._child_request = lambda _parent, definition, _inputs: {
        "type": "fake",
        "context": {"recording_id": "recording-1"},
        "request": {"input": f"stage:{definition.name}"},
    }
    participant._stage_plan = lambda _document: (
        StageDefinition("event_proposals", {}, ("input-revision",)),
    )
    with _manager(tmp_path, participant) as manager:
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "recording-1"},
                "request": {"run_id": run_id},
            },
        )
        manager.transition(parent.id, "running")
        participant.handle(
            manager.get(parent.id),
            Claims(),
            type("Token", (), {"check": lambda _self: None})(),
            manager,
        )
        child = next(job for job in manager.list_jobs() if job.parent_id == parent.id)
        run_store.update(
            run_id,
            lambda current: current["stages"][0].update(
                {
                    "status": "running",
                    "child_job_id": child.id,
                    "input_revision_ids": ["input-revision"],
                }
            ),
        )
        manager.transition(child.id, "running")
        manager.cancel(parent.id)
        assert manager.get(parent.id).state == "cancelling"
        assert manager.get(child.id).state == "cancelling"

    with _manager(tmp_path, participant) as manager:
        child = manager.get(child.id)
        assert child.state == "interrupted"
        manager.participant.reconcile(manager)
        recovered = run_store.get(run_id)
        assert manager.get(parent.id).state == "cancelled"
        assert recovered["status"] == "cancelled"
        assert recovered["stages"][0]["status"] == "interrupted"
        assert recovered["stages"][0]["child_job_id"] == child.id
        assert recovered["stages"][0]["input_revision_ids"] == ["input-revision"]


def test_unlinked_interrupted_child_recovers_exact_stage_and_inputs_after_restart(
    tmp_path: Path,
) -> None:
    run_id = str(uuid4())
    run_store = AutomatedPipelineRunStore(tmp_path / "pipeline-runs")
    run_store.create(_document(run_id))

    class _PersistedService:
        store = run_store

        def read(self, requested_run_id: str) -> dict:
            return self.store.get(requested_run_id)

    participant = AutomatedPipelineJobParticipant(_PersistedService(), object())
    participant._child_request = lambda _parent, definition, _inputs: {
        "type": "fake",
        "context": {"recording_id": "recording-1"},
        "request": {"input": f"stage:{definition.name}"},
    }
    participant._stage_plan = lambda _document: (
        StageDefinition("event_proposals", {}, ("input-revision",)),
    )
    with _manager(tmp_path, participant) as manager:
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "recording-1"},
                "request": {"run_id": run_id},
            },
        )
        manager.transition(parent.id, "running")
        participant.handle(
            manager.get(parent.id),
            Claims(),
            type("Token", (), {"check": lambda _self: None})(),
            manager,
        )
        child = next(job for job in manager.list_jobs() if job.parent_id == parent.id)
        manager.transition(child.id, "running")
        manager.cancel(parent.id)
        cancelling_parent = manager.get(parent.id)
        assert cancelling_parent.phase == "event_proposals"
        cancelling_parent.steps[0].child_job_id = None
        manager._write_job(cancelling_parent)

    with _manager(tmp_path, participant) as manager:
        child = manager.get(child.id)
        assert child.state == "interrupted"
        manager.participant.reconcile(manager)
        recovered = run_store.get(run_id)
        assert manager.get(parent.id).state == "cancelled"
        assert recovered["status"] == "cancelled"
        assert recovered["stages"][0]["status"] == "interrupted"
        assert recovered["stages"][0]["child_job_id"] == child.id
        assert recovered["stages"][0]["input_revision_ids"] == ["input-revision"]
        manager.participant.reconcile(manager)
        assert run_store.get(run_id)["stages"][0]["child_job_id"] == child.id


def test_cancelled_child_persisted_before_observer_recovers_after_restart(
    tmp_path: Path,
) -> None:
    run_id = str(uuid4())
    run_store = AutomatedPipelineRunStore(tmp_path / "pipeline-runs")
    run_store.create(_document(run_id))

    class _PersistedService:
        store = run_store

        def read(self, requested_run_id: str) -> dict:
            return self.store.get(requested_run_id)

    participant = AutomatedPipelineJobParticipant(_PersistedService(), object())
    participant._child_request = lambda _parent, definition, _inputs: {
        "type": "fake",
        "context": {"recording_id": "recording-1"},
        "request": {"input": f"stage:{definition.name}"},
    }
    participant._stage_plan = lambda _document: (
        StageDefinition("event_proposals", {}, ("input-revision",)),
    )
    with _manager(tmp_path, participant) as manager:
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "recording-1"},
                "request": {"run_id": run_id},
            },
        )
        manager.transition(parent.id, "running")
        participant.handle(
            manager.get(parent.id),
            Claims(),
            type("Token", (), {"check": lambda _self: None})(),
            manager,
        )
        child = next(job for job in manager.list_jobs() if job.parent_id == parent.id)
        manager.transition(child.id, "running")
        run_store.update(
            run_id,
            lambda current: current["stages"][0].update(
                {
                    "status": "running",
                    "child_job_id": child.id,
                    "input_revision_ids": ["input-revision"],
                }
            ),
        )
        manager.cancel(parent.id)
        participant.job_transitioned = lambda _job, _manager: (_ for _ in ()).throw(
            RuntimeError("crash after cancelled child persistence")
        )
        with pytest.raises(RuntimeError, match="crash after cancelled child persistence"):
            manager.transition(child.id, "cancelled")

    with _manager(tmp_path, participant) as manager:
        manager.participant.reconcile(manager)
        recovered = run_store.get(run_id)
        assert manager.get(parent.id).state == "cancelled"
        assert recovered["status"] == "cancelled"
        assert recovered["stages"][0]["status"] == "cancelled"
        assert recovered["stages"][0]["child_job_id"] == child.id
        assert recovered["stages"][0]["input_revision_ids"] == ["input-revision"]


def test_cancelled_stage_reconciliation_rejects_earlier_or_ambiguous_children(
    tmp_path: Path,
) -> None:
    run_id = str(uuid4())
    document, _service, participant = _participant(run_id)
    participant._stage_plan = lambda _document: (
        StageDefinition("event_proposals", {}, ("input-revision",)),
    )
    parent = SimpleNamespace(
        id="parent",
        phase="event_proposals",
        steps=[SimpleNamespace(id="event_proposals", child_job_id=None)],
        request={"run_id": run_id},
    )
    earlier = SimpleNamespace(
        id="earlier",
        parent_id=parent.id,
        parent_step_id="previous_stage",
        state="cancelled",
    )
    before = document["stages"][0].copy()
    participant._reconcile_cancelled_stage(document, parent, {earlier.id: earlier})
    assert document["stages"][0] == before

    first = SimpleNamespace(
        id="first",
        parent_id=parent.id,
        parent_step_id="event_proposals",
        state="cancelled",
    )
    second = SimpleNamespace(
        id="second",
        parent_id=parent.id,
        parent_step_id="event_proposals",
        state="interrupted",
    )
    participant._reconcile_cancelled_stage(document, parent, {first.id: first, second.id: second})
    assert document["stages"][0] == before


def test_parent_retry_reuses_verified_completed_stage_and_keeps_failed_history(
    tmp_path: Path,
) -> None:
    run_id = str(uuid4())
    document, _service, participant = _participant(run_id)
    fail_visible_once = True
    with _manager(tmp_path, participant) as manager:
        parent = manager.accept(
            str(uuid4()),
            {
                "type": "automated_pipeline",
                "context": {"recording_id": "recording-1"},
                "request": {"run_id": run_id},
            },
        )

        def handle(job: Job, _claims: Claims, token) -> None:
            nonlocal fail_visible_once
            if job.type == "automated_pipeline":
                participant.handle(job, Claims(), token, manager)
                return
            stage = job.request["input"].removeprefix("stage:")
            if stage == "visible_card_and_pile_proposals" and fail_visible_once:
                fail_visible_once = False
                raise RuntimeError("fixture stage failure")
            current = manager.get(job.id)
            current.results = [
                {
                    "kind": "pipeline_revision",
                    "id": f"revision-{job.id}",
                    "digest": "c" * 64,
                    "available": True,
                }
            ]
            manager._write_job(current)

        with JobScheduler(manager, handle, lambda _job: Claims()):
            _wait_for(lambda: manager.get(parent.id).state == "failed")
            retry = manager.retry(parent.id, str(uuid4()))
            _wait_for(lambda: manager.get(retry.id).state in {"succeeded", "failed"})
            assert manager.get(retry.id).state == "succeeded"

        event_children = [
            child
            for child in manager.list_jobs()
            if child.type == "fake" and child.request["input"] == "stage:event_proposals"
        ]
        failed_visible = [
            child
            for child in manager.list_jobs()
            if child.type == "fake"
            and child.request["input"] == "stage:visible_card_and_pile_proposals"
            and child.state == "failed"
        ]
        assert len(event_children) == 1
        assert len(failed_visible) == 1
        assert len([job for job in manager.list_jobs() if job.type == "automated_pipeline"]) == 2
        assert document["status"] == "complete"
