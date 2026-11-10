"""Job Manager parent adapter for automated recording pipelines."""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from dokodetector_backend.automated_pipeline_contracts import (
    PipelineStageRequestBuilder,
    StageDefinition,
    frozen_pilot_stage_plan,
)
from dokodetector_backend.job_models import Job, Step
from dokodetector_backend.job_scheduler import Claims
from dokodetector_backend.job_store import JobManager
from dokodetector_backend.round_analysis_contract import RoundAnalysisCreateRequest


class AutomatedPipelineJobParticipant:
    """Advance one pipeline stage per scheduler admission."""

    def __init__(self, service: Any, state: Any) -> None:
        self.service = service
        self.state = state

    def validate(self, request: dict[str, Any]) -> None:
        if (
            request.get("type") != "automated_pipeline"
            or not isinstance(request.get("context"), dict)
            or set(request["context"]) != {"recording_id"}
            or not isinstance(request["context"].get("recording_id"), str)
            or not isinstance(request.get("request"), dict)
            or not isinstance(request["request"].get("run_id"), str)
        ):
            raise ValueError("invalid automated pipeline parent request")
        self.service.read(request["request"]["run_id"])

    def prepare(self, job_id: str, request: dict[str, Any], after_write: Any) -> None:
        del job_id, request, after_write

    def verify(self, job_id: str, request: dict[str, Any]) -> bool:
        try:
            document = self.service.read(request["request"]["run_id"])
        except (LookupError, OSError, ValueError):
            return False
        return document.get("recording_id") == request["context"]["recording_id"]

    def job_fields(self, request: dict[str, Any]) -> dict[str, Any]:
        document = self.service.read(request["request"]["run_id"])
        return {
            "label": "Automated recording pipeline",
            "inputs": [
                {
                    "kind": "recording_video",
                    "id": document["recording_id"],
                    "digest": document["source"]["video_sha256"],
                }
            ],
        }

    def reconcile(self, jobs: list[Job]) -> None:
        by_id = {job.id: job for job in jobs}
        by_run = {
            job.request["run_id"]: job
            for job in jobs
            if job.type == "automated_pipeline" and "run_id" in job.request
        }
        for document in self.service.store.resumable():
            job = by_run.get(str(document["run_id"]))
            if job is not None and job.state == "cancelled":
                self._reconcile_cancelled_stage(document, job, by_id)
                self.service.store.finish(str(document["run_id"]), status="cancelled")
                continue
            if job is not None and job.state in {"failed", "cancelled", "interrupted"}:
                self.service.store.update(
                    str(document["run_id"]),
                    lambda current: current.update(
                        {
                            "status": "failed",
                            "failure": {
                                "code": "parent_interrupted",
                                "message": "The pipeline parent stopped before completion.",
                            },
                        }
                    ),
                )
                continue
            if job is None or job.state != "waiting" or job.phase is None:
                continue
            step = next((item for item in job.steps if item.id == job.phase), None)
            if step is None or step.child_job_id is None:
                continue
            child = by_id.get(step.child_job_id)
            if child is None or child.state not in {"queued", "running"}:
                continue
            definition = next(
                (item for item in self._stage_plan(document) if item.name == job.phase), None
            )
            if definition is None:
                continue
            inputs = self._resolve_inputs_from_jobs(job, definition, by_id)
            self._set_stage(str(document["run_id"]), definition.name, child.state, child.id, inputs)

    def _reconcile_cancelled_stage(
        self, document: dict[str, Any], parent: Job, jobs_by_id: dict[str, Job]
    ) -> None:
        if parent.phase is None:
            return
        definition = next(
            (item for item in self._stage_plan(document) if item.name == parent.phase), None
        )
        if definition is None:
            return
        step = next((item for item in parent.steps if item.id == parent.phase), None)
        child = jobs_by_id.get(step.child_job_id) if step and step.child_job_id else None
        if child is None:
            matches = [
                item
                for item in jobs_by_id.values()
                if item.parent_id == parent.id
                and item.parent_step_id == parent.phase
                and item.state == "cancelled"
            ]
            child = matches[0] if len(matches) == 1 else None
        if child is None or child.state != "cancelled":
            return
        inputs = self._resolve_inputs_from_jobs(parent, definition, jobs_by_id)
        self._cancel_stage(str(parent.request["run_id"]), definition.name, child.id, inputs)

    def job_transitioned(self, child: Job, manager: JobManager) -> None:
        if child.parent_id is None or child.parent_step_id is None:
            return
        parent = manager.get(child.parent_id)
        if (
            parent.type != "automated_pipeline"
            or parent.phase != child.parent_step_id
            or parent.state not in {"waiting", "queued", "running", "cancelling"}
        ):
            return
        run_id = str(parent.request["run_id"])
        document = self.service.read(run_id)
        definition = next(
            (item for item in self._stage_plan(document) if item.name == child.parent_step_id),
            None,
        )
        if definition is None:
            return
        inputs = self._resolve_inputs(manager, parent, definition)
        if child.state in {"queued", "running"}:
            self._set_stage(run_id, definition.name, child.state, child.id, inputs)
        elif child.state == "succeeded":
            if self._child_is_complete(child):
                self._copy_child_status(run_id, definition.name, child, inputs)
            else:
                self._fail_run(run_id, definition.name, child, inputs)
        elif child.state in {"failed", "interrupted"}:
            self._fail_run(run_id, definition.name, child, inputs)
        elif child.state == "cancelled":
            self._cancel_stage(run_id, definition.name, child.id, inputs)

    def handle(self, job: Job, _claims: Claims, token: Any, manager: JobManager) -> None:
        token.check()
        run_id = str(job.request["run_id"])
        document = self.service.read(run_id)
        plan = self._stage_plan(document)
        if job.state == "running" and job.started_at is not None:
            self.service.store.update(
                run_id, lambda current: current.update({"status": "running", "failure": None})
            )

        for definition in plan:
            token.check()
            current = manager.get(job.id)
            step = next((item for item in current.steps if item.id == definition.name), None)
            if step is not None and step.child_job_id is not None:
                child = manager.get(step.child_job_id)
                inputs = self._resolve_inputs(manager, current, definition)
                if child.state == "succeeded":
                    if not self._child_is_complete(child):
                        self._fail_run(run_id, definition.name, child, inputs)
                        raise RuntimeError(
                            f"Pipeline stage {definition.name} did not complete fully."
                        )
                    step.state = "succeeded"
                    step.finished_at = child.finished_at
                    manager._write_job(current)
                    self._copy_child_status(run_id, definition.name, child, inputs)
                    continue
                if child.state in {"failed", "cancelled", "interrupted"}:
                    self._fail_run(run_id, definition.name, child, inputs)
                    raise RuntimeError(f"Pipeline stage {definition.name} {child.state}.")
                self._set_stage(run_id, definition.name, child.state, child.id, inputs)
                manager.transition(job.id, "waiting")
                return

            inputs = self._resolve_inputs(manager, current, definition)
            child_request = self._child_request(job, definition, inputs)
            reused = self._reuse_completed_stage(
                run_id, manager, job, definition, inputs, child_request
            )
            if reused is not None:
                current.steps.append(
                    Step(
                        id=definition.name,
                        label=definition.name,
                        state="succeeded",
                        started_at=reused.started_at,
                        finished_at=reused.finished_at,
                        child_job_id=reused.id,
                    )
                )
                manager._write_job(current)
                self._copy_child_status(run_id, definition.name, reused, inputs)
                continue
            if definition.name == "reconstruction":
                previous_child_id = next(
                    (
                        row.get("child_job_id")
                        for row in self.service.read(run_id)["stages"]
                        if row["name"] == definition.name
                    ),
                    None,
                )
                if isinstance(previous_child_id, str):
                    previous_child = manager.get(previous_child_id)
                    if previous_child.state in {"failed", "cancelled", "interrupted"}:
                        child_request["request"]["analysis_id"] = str(
                            uuid5(NAMESPACE_URL, f"{job.id}:{definition.name}:retry")
                        )
            child_key = str(uuid5(NAMESPACE_URL, f"{job.id}:{definition.name}:1"))
            child_request.update({"parent_id": job.id, "parent_step_id": definition.name})
            # Persist which stage this wait belongs to before the waiting transition.
            # Recovery can then distinguish a wait with no accepted child from a later
            # wait whose earlier child already reached a terminal state.
            current = manager.get(job.id)
            if not any(item.id == definition.name for item in current.steps):
                current.steps.append(Step(id=definition.name, label=definition.name))
            current.phase = definition.name
            manager._write_job(current)
            manager.transition(job.id, "waiting")
            child = manager.accept(child_key, child_request)
            current = manager.get(job.id)
            if not any(item.id == definition.name for item in current.steps):
                current.steps.append(Step(id=definition.name, label=definition.name))
            parent_step = next(item for item in current.steps if item.id == definition.name)
            parent_step.child_job_id = child.id
            current.phase = definition.name
            manager._write_job(current)
            self._set_stage(run_id, definition.name, "queued", child.id, inputs)
            return

        self.service.store.finish(run_id, status="complete")

    def _resolve_inputs(
        self, manager: JobManager, parent: Job, definition: StageDefinition
    ) -> tuple[str, ...]:
        jobs_by_id = {
            step.child_job_id: manager.get(step.child_job_id)
            for step in parent.steps
            if step.child_job_id is not None
        }
        return self._resolve_inputs_from_jobs(parent, definition, jobs_by_id)

    def _resolve_inputs_from_jobs(
        self, parent: Job, definition: StageDefinition, jobs_by_id: dict[str, Job]
    ) -> tuple[str, ...]:
        by_stage = {step.id: step.child_job_id for step in parent.steps}
        resolved: list[str] = []
        for reference in definition.input_revision_ids:
            if not reference.startswith("@stage:"):
                resolved.append(reference)
                continue
            stage_name = reference.removeprefix("@stage:")
            child_id = by_stage.get(stage_name)
            if child_id is None:
                raise ValueError(f"Pipeline input stage is missing: {stage_name}.")
            child = jobs_by_id.get(child_id)
            if child is None:
                raise ValueError(f"Pipeline input stage is missing: {stage_name}.")
            if child.state != "succeeded" or not child.results:
                raise ValueError(f"Pipeline input stage has no verified output: {stage_name}.")
            resolved.append(str(child.results[0]["id"]))
        return tuple(resolved)

    @staticmethod
    def _stage_plan(document: dict[str, Any]) -> tuple[StageDefinition, ...]:
        request = document["request"]
        stage_requests = dict(request["stage_requests"])
        stage_requests["reconstruction"] = {
            "session_id": request["session_id"],
            "round_id": request["round_id"],
            "round_context": request["round_context"],
            "rules_version": request["rules_version"],
            "search": request["search"],
        }
        return frozen_pilot_stage_plan(stage_requests)

    def _child_request(
        self, parent: Job, definition: StageDefinition, inputs: tuple[str, ...]
    ) -> dict[str, Any]:
        run_id = str(uuid5(NAMESPACE_URL, f"{parent.request['run_id']}:{definition.name}"))
        recording_id = parent.context["recording_id"]
        if definition.name == "reconstruction":
            if definition.request.get("skip") is True:
                raise ValueError("Automated pipeline reconstruction cannot be skipped.")
            if len(inputs) != 1:
                raise ValueError("Round analysis needs one table-observation revision.")
            selection = self.state.pipeline_selection_store.get_exact(
                recording_id, "table_observations"
            )
            node_ref = (
                None
                if selection is None
                else selection.selected_completed_reference or selection.selected_generated
            )
            if node_ref is None:
                raise ValueError("Round analysis needs a selected table-observation node revision.")
            analysis = RoundAnalysisCreateRequest(
                analysis_id=uuid5(NAMESPACE_URL, run_id),
                recording_id=recording_id,
                round_id=definition.request["round_id"],
                session_id=definition.request["session_id"],
                table_observation_node_ref=node_ref,
                round_context=definition.request["round_context"],
                rules_version=definition.request["rules_version"],
                search=definition.request["search"],
            )
            return {
                "type": "round_analysis",
                "context": {"recording_id": recording_id},
                "request": analysis.model_dump(mode="json"),
            }
        payload = PipelineStageRequestBuilder._request_payload(
            definition.name, run_id, definition.request, inputs
        )
        stage_types = {
            "event_proposals": "event_processing",
            "visible_card_and_pile_proposals": "visible_card_detection",
            "card_scene_and_calibration": "proposed_card_scene_creation",
            "visual_identity_proposals": "visual_identity_classification",
            "table_observations": "table_observation_assembly",
        }
        return {
            "type": stage_types[definition.name],
            "context": {"recording_id": recording_id},
            "request": payload,
        }

    def _reuse_completed_stage(
        self,
        run_id: str,
        manager: JobManager,
        parent: Job,
        definition: StageDefinition,
        inputs: tuple[str, ...],
        candidate: dict[str, Any],
    ) -> Job | None:
        document = self.service.read(run_id)
        row = next(item for item in document["stages"] if item["name"] == definition.name)
        child_id = row.get("child_job_id")
        if (
            row.get("status") != "complete"
            or not isinstance(child_id, str)
            or tuple(row.get("input_revision_ids", ())) != inputs
        ):
            return None
        try:
            child = manager.get(child_id)
            normalized = manager.participant.normalize(
                {**candidate, "parent_id": parent.id, "parent_step_id": definition.name}
            )
            manager.participant.validate(normalized)
        except (LookupError, OSError, RuntimeError, TypeError, ValueError):
            return None
        if (
            child.state != "succeeded"
            or not self._child_is_complete(child)
            or child.type != normalized.get("type")
            or child.context != normalized.get("context")
            or child.request != normalized.get("request")
            or [str(result.get("id")) for result in child.results if isinstance(result, dict)]
            != row.get("output_revision_ids", [])
            or not manager.verify_publication(child, child.results)
        ):
            return None
        return child

    def _child_is_complete(self, child: Job) -> bool:
        if not hasattr(self.state, "pipeline_run_store"):
            return True
        if child.type == "round_analysis":
            analysis_id = child.request.get("analysis_id")
            if not isinstance(analysis_id, str):
                return False
            status = self.state.round_analysis_service.status(analysis_id).state
            return status == "complete"
        run = self.state.pipeline_run_store.get(child.id)
        return run is not None and run.state.status == "complete"

    def _copy_child_status(
        self, run_id: str, stage: str, child: Job, inputs: tuple[str, ...]
    ) -> None:
        outputs = [str(result["id"]) for result in child.results if isinstance(result, dict)]

        def update(current: dict[str, Any]) -> None:
            current["status"] = "running"
            row = next(item for item in current["stages"] if item["name"] == stage)
            row.update(
                {
                    "status": "complete",
                    "run_id": str(child.request.get("analysis_id", child.id)),
                    "child_job_id": child.id,
                    "input_revision_ids": list(inputs),
                    "output_revision_ids": outputs,
                }
            )

        self.service.store.update(run_id, update)

    def _set_stage(
        self, run_id: str, stage: str, status: str, child_id: str, inputs: tuple[str, ...]
    ) -> None:
        self.service.store.update(
            run_id,
            lambda current: _update_stage(current, stage, status, child_id, [], list(inputs)),
        )

    def _fail_run(self, run_id: str, stage: str, child: Job, inputs: tuple[str, ...]) -> None:
        def update(current: dict[str, Any]) -> None:
            current["status"] = "failed"
            current["failure"] = {"stage": stage, "details": child.failure}
            row = next(item for item in current["stages"] if item["name"] == stage)
            row.update(
                {
                    "status": "failed",
                    "child_job_id": child.id,
                    "run_id": child.id,
                    "input_revision_ids": list(inputs),
                }
            )

        self.service.store.update(run_id, update)

    def _cancel_stage(
        self, run_id: str, stage: str, child_id: str, inputs: tuple[str, ...]
    ) -> None:
        def update(current: dict[str, Any]) -> None:
            current["status"] = "cancelled"
            row = next(item for item in current["stages"] if item["name"] == stage)
            row.update(
                {
                    "status": "cancelled",
                    "run_id": child_id,
                    "child_job_id": child_id,
                    "input_revision_ids": list(inputs),
                }
            )

        self.service.store.update(run_id, update)


def _update_stage(
    document: dict[str, Any],
    stage_name: str,
    status: str,
    child_id: str,
    outputs: list[str],
    inputs: list[str],
) -> None:
    document["status"] = "running"
    row = next(item for item in document["stages"] if item["name"] == stage_name)
    row.update(
        {
            "status": status,
            "run_id": child_id,
            "child_job_id": child_id,
            "input_revision_ids": inputs,
            "output_revision_ids": outputs,
        }
    )


__all__ = ["AutomatedPipelineJobParticipant"]
