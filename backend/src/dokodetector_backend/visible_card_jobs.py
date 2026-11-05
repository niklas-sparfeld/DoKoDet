"""Job Manager adapter for visible-card detection."""

from __future__ import annotations

from typing import Any

from dokodetector_backend.job_scheduler import Claims
from dokodetector_backend.job_store import Job, JobManager
from dokodetector_backend.visible_card_pipeline_service import VisibleCardPipelineService


class VisibleCardJobParticipant:
    """Freeze visible-card inputs and execute them under shared job ownership."""

    def __init__(self, service: VisibleCardPipelineService) -> None:
        self.service = service

    def normalize(self, request: dict[str, Any]) -> dict[str, Any]:
        context = request.get("context")
        body = request.get("request")
        if (
            request.get("type") != "visible_card_detection"
            or not isinstance(context, dict)
            or set(context) != {"recording_id"}
            or not isinstance(context["recording_id"], str)
            or not isinstance(body, dict)
        ):
            raise ValueError("invalid visible-card job request")
        if body.get("schema") == "visible-card-job-request/v1":
            self.validate(request)
            return request
        frozen = self.service.freeze_job_request(context["recording_id"], body)
        return {**request, "request": frozen}

    def validate(self, request: dict[str, Any]) -> None:
        context = request.get("context")
        body = request.get("request")
        if (
            request.get("type") != "visible_card_detection"
            or not isinstance(context, dict)
            or set(context) != {"recording_id"}
            or not isinstance(context["recording_id"], str)
            or not isinstance(body, dict)
        ):
            raise ValueError("invalid visible-card job request")
        self.service.validate_frozen_job_request(context["recording_id"], body)

    def prepare(self, job_id: str, request: dict[str, Any], after_write: Any) -> None:
        self.service.prepare_job(job_id, request, after_write)

    def verify(self, job_id: str, request: dict[str, Any]) -> bool:
        return self.service.verify_job(job_id, request)

    def job_fields(self, request: dict[str, Any]) -> dict[str, Any]:
        frozen = request["request"]["processor_request"]
        source = frozen["source"]
        return {
            "label": "Detect visible cards",
            "inputs": [
                {
                    "kind": "recording_video",
                    "id": source["recording_id"],
                    "digest": source["video_sha256"],
                },
                {"kind": "pipeline_revision", "id": frozen["input_revision_ids"][0]},
            ],
            "implementation": {
                "implementation": frozen["implementation"],
                "model": frozen.get("model"),
                "configuration": frozen["configuration"],
                "extraction_policy": frozen["extraction_policy"],
            },
        }

    def verify_publication(self, job: Job, results: list[dict[str, Any]]) -> bool:
        return self.service.verify_job_publication(job, results)

    def reconcile(self, jobs: list[Job]) -> None:
        self.service.reconcile_job_states(jobs)

    def handle(self, job: Job, claims: Claims, token: Any, manager: JobManager) -> None:
        self.service.execute_job(job, claims, token, manager)

    def claims_for(self, job: Job) -> Claims:
        return Claims(
            cpu=self.service.max_concurrent_requests,
            locks=(f"recording:{job.context['recording_id']}:visible_cards",),
        )
