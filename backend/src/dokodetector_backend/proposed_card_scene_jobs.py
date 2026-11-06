"""Job Manager adapter for proposed card scene processing."""

from __future__ import annotations

from typing import Any

from dokodetector_backend.job_scheduler import Claims
from dokodetector_backend.job_store import Job, JobManager
from dokodetector_backend.proposed_card_scene_pipeline_service import (
    ProposedCardScenePipelineService,
)


class ProposedCardSceneJobParticipant:
    """Freeze the exact visible-card revision and execute under manager ownership."""

    def __init__(self, service: ProposedCardScenePipelineService) -> None:
        self.service = service

    def normalize(self, request: dict[str, Any]) -> dict[str, Any]:
        context = request.get("context")
        body = request.get("request")
        if (
            request.get("type") != "proposed_card_scene_creation"
            or not isinstance(context, dict)
            or set(context) != {"recording_id"}
            or not isinstance(context["recording_id"], str)
            or not isinstance(body, dict)
        ):
            raise ValueError("invalid proposed-card-scene job request")
        if body.get("schema") == "proposed-card-scene-job-request/v1":
            self.validate(request)
            return request
        payload = {**body, "run_id": body.get("run_id") or "pending-proposal-run"}
        return {
            **request,
            "request": self.service.freeze_job_request(context["recording_id"], payload),
        }

    def validate(self, request: dict[str, Any]) -> None:
        context = request.get("context")
        body = request.get("request")
        if (
            request.get("type") != "proposed_card_scene_creation"
            or not isinstance(context, dict)
            or set(context) != {"recording_id"}
            or not isinstance(context["recording_id"], str)
            or not isinstance(body, dict)
        ):
            raise ValueError("invalid proposed-card-scene job request")
        self.service.validate_frozen_job_request(context["recording_id"], body)

    def prepare(self, job_id: str, request: dict[str, Any], after_write: Any) -> None:
        self.service.prepare_job(job_id, request, after_write)

    def verify(self, job_id: str, request: dict[str, Any]) -> bool:
        return self.service.verify_job(job_id, request)

    def job_fields(self, request: dict[str, Any]) -> dict[str, Any]:
        frozen = request["request"]["processor_request"]
        input_ref = frozen.get("input_node_ref")
        input_digest = self.service._visible_input(
            request["context"]["recording_id"],
            frozen["input_revision_ids"][0],
            input_ref,
        ).content_sha256
        return {
            "label": "Create proposed card scenes",
            "inputs": [
                {
                    "kind": "pipeline_node_revision",
                    "id": frozen["input_revision_ids"][0],
                    "digest": input_digest,
                }
            ],
            "implementation": {
                "implementation": frozen["implementation"],
                "configuration": frozen["configuration"],
                "extraction_policy": frozen["extraction_policy"],
            },
        }

    def verify_publication(self, job: Job, results: list[dict[str, Any]]) -> bool:
        return self.service.verify_job_publication(job, results)

    def reconcile(self, jobs: list[Job]) -> None:
        self.service.reconcile_job_states(jobs)

    def handle(self, job: Job, claims: Claims, token: Any, manager: JobManager) -> None:
        del claims
        self.service.execute_job(job, token, manager)

    @staticmethod
    def claims_for(job: Job) -> Claims:
        return Claims(
            cpu=1, locks=(f"recording:{job.context['recording_id']}:card_scene_proposals",)
        )
