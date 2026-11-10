"""Job Manager adapter for table-observation assembly."""

from __future__ import annotations

from typing import Any

from dokodetector_backend.job_models import Job
from dokodetector_backend.job_scheduler import Claims
from dokodetector_backend.job_store import JobManager
from dokodetector_backend.observation_pipeline_service import ObservationPipelineService


class ObservationJobParticipant:
    """Freeze the three exact source revisions and run assembly as a managed job."""

    def __init__(self, service: ObservationPipelineService) -> None:
        self.service = service

    def normalize(self, request: dict[str, Any]) -> dict[str, Any]:
        context = request.get("context")
        body = request.get("request")
        if (
            request.get("type") != "table_observation_assembly"
            or not isinstance(context, dict)
            or set(context) != {"recording_id"}
            or not isinstance(context["recording_id"], str)
            or not isinstance(body, dict)
        ):
            raise ValueError("invalid table-observation job request")
        if body.get("schema") == "table-observation-job-request/v1":
            self.validate(request)
            return request
        return {
            **request,
            "request": self.service.freeze_job_request(context["recording_id"], body),
        }

    def validate(self, request: dict[str, Any]) -> None:
        context = request.get("context")
        body = request.get("request")
        if (
            request.get("type") != "table_observation_assembly"
            or not isinstance(context, dict)
            or set(context) != {"recording_id"}
            or not isinstance(context["recording_id"], str)
            or not isinstance(body, dict)
        ):
            raise ValueError("invalid table-observation job request")
        self.service.validate_frozen_job_request(context["recording_id"], body)

    def prepare(self, job_id: str, request: dict[str, Any], after_write: Any) -> None:
        self.service.prepare_job(job_id, request, after_write)

    def verify(self, job_id: str, request: dict[str, Any]) -> bool:
        return self.service.verify_job(job_id, request)

    def job_fields(self, request: dict[str, Any]) -> dict[str, Any]:
        processor = request["request"]["processor_request"]
        inputs = []
        for revision_id in processor["input_revision_ids"]:
            revision = self.service.selection_store.require_processor_revision(revision_id)
            inputs.append(
                {
                    "kind": "pipeline_revision",
                    "id": revision_id,
                    "digest": revision.manifest.content_sha256,
                }
            )
        event_ref = processor.get("input_event_set_ref")
        if event_ref is not None:
            inputs.append(
                {
                    "kind": "artifact",
                    "id": f"event-set/{event_ref['set_id']}/versions/{event_ref['version']}",
                    "digest": event_ref["content_sha256"],
                }
            )
        return {
            "label": "Assemble table observations",
            "inputs": inputs,
            "implementation": {
                "implementation": processor["implementation"],
                "configuration": processor["configuration"],
                "extraction_policy": processor["extraction_policy"],
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
            cpu=1,
            locks=(f"recording:{job.context['recording_id']}:table_observations",),
        )
