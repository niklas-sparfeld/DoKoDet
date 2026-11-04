"""Run durable automated pipeline records outside the request lifecycle."""

from __future__ import annotations

import asyncio
import logging
from threading import Lock
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from dokodetector_backend.automated_pipeline_run import AutomatedPipelineRunService
from dokodetector_backend.pipeline_coordinator import (
    PipelineCoordinator,
    RetainedPipelineStageExecutor,
    StageExecution,
    frozen_pilot_stage_plan,
)
from dokodetector_backend.round_analysis_contract import RoundAnalysisCreateRequest

LOGGER = logging.getLogger(__name__)


class AutomatedPipelineWorker:
    """Queue accepted runs and resume durable records when the backend starts."""

    def __init__(
        self,
        service: AutomatedPipelineRunService,
        state: Any,
        *,
        stage_executor: Any | None = None,
    ) -> None:
        self.service = service
        self.state = state
        self.stage_executor = stage_executor
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._queued: set[str] = set()
        self._guard = Lock()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._worker_loop(), name="automated-pipeline-worker")
        for document in self.service.store.resumable():
            self.enqueue(str(document["run_id"]))

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        await self._queue.put(None)
        await task
        self._task = None

    def enqueue(self, run_id: str) -> None:
        with self._guard:
            if run_id in self._queued:
                return
            self._queued.add(run_id)
        self._queue.put_nowait(run_id)

    async def _worker_loop(self) -> None:
        while True:
            run_id = await self._queue.get()
            try:
                if run_id is None:
                    return
                await asyncio.to_thread(self._execute, run_id)
            finally:
                if run_id is not None:
                    with self._guard:
                        self._queued.discard(run_id)
                self._queue.task_done()

    def _execute(self, run_id: str) -> None:
        document = self.service.read(run_id)
        recording_id = str(document["recording_id"])
        request = document["request"]
        stage_requests = dict(request["stage_requests"])
        stage_requests["reconstruction"] = {
            "session_id": request["session_id"],
            "round_id": request["round_id"],
            "round_context": request["round_context"],
            "rules_version": request["rules_version"],
            "search": request["search"],
        }
        plan = frozen_pilot_stage_plan(stage_requests)
        coordinator = PipelineCoordinator(
            self.service.store.root / "coordinator-runs",
            self.stage_executor or _AutomatedStageExecutor(self.state),
        )
        coordinator.on_update = lambda manifest: self._copy_status(run_id, manifest)
        try:
            self.service.store.update(
                run_id,
                lambda current: current.update({"status": "running", "failure": None}),
            )
            result = coordinator.run(recording_id, plan, coordinator_id=run_id)
            status = "complete" if result["status"] == "complete" else "failed"
            self.service.store.finish(run_id, status=status)
        except Exception as error:
            LOGGER.exception("Automated pipeline run failed", extra={"run_id": run_id})
            failure_message = str(error)
            self.service.store.update(
                run_id,
                lambda current: current.update(
                    {
                        "status": "failed",
                        "failure": current.get("failure")
                        or {"code": "pipeline_worker_failed", "message": failure_message},
                    }
                ),
            )
            self._release_active(run_id)

    def _copy_status(self, run_id: str, manifest: Mapping[str, Any]) -> None:
        def update(current: dict[str, Any]) -> None:
            current["status"] = manifest["status"] if manifest["status"] != "pending" else "queued"
            current["failure"] = manifest.get("failure")
            by_name = {row["name"]: row for row in manifest["stages"]}
            for stage in current["stages"]:
                source = by_name[stage["name"]]
                stage.update(
                    {
                        "status": source["status"],
                        "run_id": source.get("processor_run_id") or source.get("run_id"),
                        "input_revision_ids": list(source.get("input_revision_ids", [])),
                        "output_revision_ids": list(source.get("output_revision_ids", [])),
                        "failure": source.get("failure"),
                    }
                )

        self.service.store.update(run_id, update)

    def _release_active(self, run_id: str) -> None:
        try:
            self.service.store.finish(run_id, status="failed")
        except Exception:
            LOGGER.exception("Could not release failed automated pipeline run")


class _AutomatedStageExecutor:
    """Bridge five retained processor services and the saved round-analysis service."""

    def __init__(self, state: Any) -> None:
        self.state = state
        composition = type("PipelineServices", (), {})()
        composition.event_service = state.event_pipeline_service
        composition.visible_card_service = state.visible_card_pipeline_service
        composition.proposed_card_scene_service = state.proposed_card_scene_pipeline_service
        composition.visual_identity_service = state.visual_identity_pipeline_service
        composition.observation_service = state.observation_pipeline_service
        composition.run_store = state.pipeline_run_store
        self.pipeline = RetainedPipelineStageExecutor(composition)

    def __call__(self, **kwargs: Any) -> StageExecution:
        if kwargs["stage"] != "reconstruction":
            return self.pipeline(**kwargs)
        return self._reconstruct(**kwargs)

    def _reconstruct(
        self,
        *,
        recording_id: str,
        run_id: str,
        request: Mapping[str, Any],
        input_revision_ids: tuple[str, ...],
        **_: Any,
    ) -> StageExecution:
        if len(input_revision_ids) != 1:
            raise ValueError("Round analysis needs one table-observation revision.")
        attempt = 1
        analysis_id = uuid5(NAMESPACE_URL, f"{run_id}:attempt:{attempt}")
        analysis_request = RoundAnalysisCreateRequest(
            analysis_id=analysis_id,
            recording_id=recording_id,
            round_id=request["round_id"],
            session_id=request["session_id"],
            table_observation_revision_id=input_revision_ids[0],
            round_context=request["round_context"],
            rules_version=request["rules_version"],
            search=request["search"],
        )
        service = self.state.round_analysis_service
        existing = service.store.get(analysis_id)
        while existing is not None and existing.state == "failed":
            attempt += 1
            analysis_id = uuid5(NAMESPACE_URL, f"{run_id}:attempt:{attempt}")
            analysis_request = analysis_request.model_copy(update={"analysis_id": analysis_id})
            existing = service.store.get(analysis_id)
        if existing is None:
            service.validate_request(analysis_request)
            created = service.store.create(analysis_request)
            if created.created:
                service.prepare_inputs(analysis_request)
                service.enqueue(analysis_id, f"automated-pipeline:{run_id}")
        while True:
            status = service.status(analysis_id)
            if status.state in {"complete", "failed"}:
                break
            import time

            time.sleep(0.25)
        return StageExecution(
            status=status.state,
            input_revision_ids=input_revision_ids,
            output_revision_ids=(str(analysis_id),) if status.state == "complete" else (),
            failure={"message": status.error} if status.error else None,
            processor_run_id=str(analysis_id),
        )


__all__ = ["AutomatedPipelineWorker"]
