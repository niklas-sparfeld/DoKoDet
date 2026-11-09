from __future__ import annotations

import threading
import time
from pathlib import Path
from uuid import uuid4

from dokodetector_backend.automated_pipeline_jobs import AutomatedPipelineJobParticipant
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
        return []


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


def _manager(tmp_path: Path, participant: AutomatedPipelineJobParticipant) -> JobManager:
    return JobManager(
        tmp_path,
        _Registry(participant),
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


def test_restart_resumes_an_accepted_child_without_duplicate_creation(tmp_path: Path) -> None:
    run_id = str(uuid4())
    document, _service, participant = _participant(run_id)
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
        parent = manager.get(parent.id)
        assert parent.phase == "event_proposals"
        assert parent.steps[0].child_job_id is not None
        before = [job for job in manager.list_jobs() if job.parent_id == parent.id]
        assert len(before) == 1

    with _manager(tmp_path, participant) as manager:
        parent = manager.get(parent.id)

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
