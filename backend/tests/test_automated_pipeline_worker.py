from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from dokodetector_backend.automated_pipeline_run import (
    AutomatedPipelineRunService,
    AutomatedPipelineRunStore,
)
from dokodetector_backend.automated_pipeline_worker import AutomatedPipelineWorker
from dokodetector_backend.pipeline_coordinator import StageExecution


def _service(tmp_path: Path) -> AutomatedPipelineRunService:
    return AutomatedPipelineRunService(
        store=AutomatedPipelineRunStore(tmp_path),
        recording_source_provider=lambda recording_id: SimpleNamespace(
            to_mapping=lambda: {
                "schema_version": "recording-video/v1",
                "recording_id": recording_id,
                "video_sha256": "a" * 64,
            }
        ),
        recording_provider_validator=lambda _recording_id, stage_requests: {
            "stage_requests": stage_requests,
            "providers": {"event_proposals": {"name": "fixture"}},
        },
        round_session_provider=lambda _recording_id: "session-1",
    )


def _request() -> dict[str, object]:
    return {
        "idempotency_key": str(uuid4()),
        "session_id": "session-1",
        "round_id": "round-1",
        "round_context": {
            "game_id": "game-1",
            "round_id": "round-1",
            "active_players": ["p1", "p2", "p3", "p4"],
            "dealer": "p1",
            "first_trick_leader": "p2",
        },
        "rules_version": "v1",
        "search": {
            "max_missing_plays": 1,
            "max_hypotheses": 16,
            "max_search_nodes": 1000,
        },
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
    }


class _FixtureExecutor:
    def __init__(
        self,
        *,
        fail_stage: str | None = None,
        empty_stages: tuple[str, ...] = (),
        interrupt_stage: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.fail_stage = fail_stage
        self.empty_stages = set(empty_stages)
        self.interrupt_stage = interrupt_stage

    def __call__(
        self,
        *,
        recording_id: str,
        stage: str,
        run_id: str,
        request: object,
        input_revision_ids: tuple[str, ...],
    ) -> StageExecution:
        del recording_id, run_id, request
        self.calls.append((stage, input_revision_ids))
        if stage == self.interrupt_stage:
            raise _SimulatedProcessInterruption
        if stage == self.fail_stage:
            return StageExecution(
                status="failed",
                input_revision_ids=input_revision_ids,
                failure={"code": "fixture_failure"},
            )
        revision_id = f"revision-{stage}"
        if stage in self.empty_stages:
            revision_id = f"empty-{revision_id}"
        return StageExecution(
            status="complete",
            input_revision_ids=input_revision_ids,
            output_revision_ids=(revision_id,),
        )


class _SimulatedProcessInterruption(BaseException):
    pass


def test_worker_executes_all_stages_and_persists_exact_lineage(tmp_path: Path) -> None:
    service = _service(tmp_path)
    run, _ = service.start("recording-1", _request())
    executor = _FixtureExecutor(empty_stages=("event_proposals",))
    worker = AutomatedPipelineWorker(service, None, stage_executor=executor)

    worker._execute(run["run_id"])

    completed = service.read(run["run_id"])
    stages = {row["name"]: row for row in completed["stages"]}
    assert completed["status"] == "complete"
    assert all(row["status"] == "complete" for row in stages.values())
    assert stages["visible_card_and_pile_proposals"]["input_revision_ids"] == [
        "empty-revision-event_proposals"
    ]
    assert stages["card_scene_and_calibration"]["input_revision_ids"] == [
        "revision-visible_card_and_pile_proposals"
    ]
    assert stages["visual_identity_proposals"]["input_revision_ids"] == [
        "revision-card_scene_and_calibration"
    ]
    assert stages["table_observations"]["input_revision_ids"] == [
        "empty-revision-event_proposals",
        "revision-visible_card_and_pile_proposals",
        "revision-visual_identity_proposals",
    ]
    assert stages["reconstruction"]["input_revision_ids"] == ["revision-table_observations"]
    assert len(executor.calls) == 6


def test_worker_stops_after_a_blocking_stage_and_retains_partial_lineage(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    run, _ = service.start("recording-1", _request())
    executor = _FixtureExecutor(fail_stage="card_scene_and_calibration")
    worker = AutomatedPipelineWorker(service, None, stage_executor=executor)

    worker._execute(run["run_id"])

    failed = service.read(run["run_id"])
    stages = {row["name"]: row for row in failed["stages"]}
    assert failed["status"] == "failed"
    assert failed["failure"]["stage"] == "card_scene_and_calibration"
    assert stages["event_proposals"]["status"] == "complete"
    assert stages["visible_card_and_pile_proposals"]["status"] == "complete"
    assert stages["card_scene_and_calibration"]["status"] == "failed"
    assert stages["visual_identity_proposals"]["status"] == "pending"
    assert stages["reconstruction"]["status"] == "pending"
    assert [stage for stage, _ in executor.calls] == [
        "event_proposals",
        "visible_card_and_pile_proposals",
        "card_scene_and_calibration",
    ]


def test_worker_startup_resumes_an_accepted_run(tmp_path: Path) -> None:
    service = _service(tmp_path)
    run, _ = service.start("recording-1", _request())
    executor = _FixtureExecutor()
    worker = AutomatedPipelineWorker(service, None, stage_executor=executor)

    async def run_worker() -> None:
        await worker.start()
        await worker._queue.join()
        await worker.stop()

    asyncio.run(run_worker())

    assert service.read(run["run_id"])["status"] == "complete"
    assert len(executor.calls) == 6


def test_worker_restart_reuses_completed_stages_and_retries_interrupted_stage(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    run, _ = service.start("recording-1", _request())
    interrupted_executor = _FixtureExecutor(interrupt_stage="visible_card_and_pile_proposals")
    first_worker = AutomatedPipelineWorker(
        service,
        None,
        stage_executor=interrupted_executor,
    )

    try:
        first_worker._execute(run["run_id"])
    except _SimulatedProcessInterruption:
        pass
    else:
        raise AssertionError("The fixture must interrupt the worker.")

    resumed_executor = _FixtureExecutor()
    resumed_worker = AutomatedPipelineWorker(service, None, stage_executor=resumed_executor)

    async def resume_worker() -> None:
        await resumed_worker.start()
        await resumed_worker._queue.join()
        await resumed_worker.stop()

    asyncio.run(resume_worker())

    completed = service.read(run["run_id"])
    assert completed["status"] == "complete"
    assert [stage for stage, _ in resumed_executor.calls] == [
        "visible_card_and_pile_proposals",
        "card_scene_and_calibration",
        "visual_identity_proposals",
        "table_observations",
        "reconstruction",
    ]
    assert completed["stages"][0]["status"] == "complete"
