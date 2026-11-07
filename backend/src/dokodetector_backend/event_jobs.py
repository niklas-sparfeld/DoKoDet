"""Job-manager adapter for event inference and prediction imports."""

from __future__ import annotations

from typing import Any

from dokodetector_backend.event_pipeline_service import EventPipelineService
from dokodetector_backend.job_models import Job
from dokodetector_backend.job_scheduler import Claims
from dokodetector_backend.job_store import JobManager


class EventJobParticipant:
    """Freeze event inputs and adapt event processing to the shared scheduler."""

    def __init__(self, service: EventPipelineService) -> None:
        self.service = service

    def validate(self, request: dict[str, Any]) -> None:
        job_type = request.get("type")
        context = request.get("context")
        body = request.get("request")
        if job_type not in {"event_processing", "event_import"}:
            raise ValueError("unsupported event job type")
        if (
            not isinstance(context, dict)
            or set(context) != {"recording_id"}
            or not isinstance(context["recording_id"], str)
        ):
            raise ValueError("event jobs need one recording context")
        if not isinstance(body, dict) or body.get("schema") != "event-job-request/v1":
            raise ValueError("event job request is not normalized")
        if body.get("mode") != ("import" if job_type == "event_import" else "inference"):
            raise ValueError("event job mode does not match its type")
        self.service.validate_frozen_job_request(context["recording_id"], body)

    def normalize(self, request: dict[str, Any]) -> dict[str, Any]:
        job_type = request.get("type")
        context = request.get("context")
        body = request.get("request")
        if (
            job_type not in {"event_processing", "event_import"}
            or not isinstance(context, dict)
            or not isinstance(context.get("recording_id"), str)
            or not isinstance(body, dict)
        ):
            raise ValueError("invalid event job request")
        if body.get("schema") == "event-job-request/v1":
            self.validate(request)
            return request
        mode = "import" if job_type == "event_import" else "inference"
        frozen = self.service.freeze_job_request(context["recording_id"], mode, body)
        return {**request, "request": frozen}

    def prepare(
        self,
        job_id: str,
        request: dict[str, Any],
        after_write: Any,
    ) -> None:
        self.service.prepare_job(job_id, request, after_write)

    def verify(self, job_id: str, request: dict[str, Any]) -> bool:
        return self.service.verify_job(job_id, request)

    def job_fields(self, request: dict[str, Any]) -> dict[str, Any]:
        frozen = request["request"]
        processor = frozen["processor_request"]
        source = processor["source"]
        inputs = [
            {
                "kind": "recording_video",
                "id": source["recording_id"],
                "digest": source["video_sha256"],
            }
        ]
        artifact = frozen.get("artifact")
        if artifact is not None:
            inputs.append(
                {
                    "kind": "event_prediction_import",
                    "id": artifact["id"],
                    "digest": artifact["sha256"],
                }
            )
        return {
            "label": "Import event predictions"
            if frozen["mode"] == "import"
            else "Detect card events",
            "inputs": inputs,
            "implementation": {
                "implementation": processor["implementation"],
                "model": processor.get("model"),
                "configuration": processor["configuration"],
                "extraction_policy": processor["extraction_policy"],
            },
        }

    def verify_publication(self, job: Job, results: list[dict[str, Any]]) -> bool:
        return self.service.verify_job_publication(job, results)

    def reconcile(self, jobs: list[Job]) -> None:
        self.service.reconcile_job_states(jobs)

    def handle(
        self,
        job: Job,
        _claims: Claims,
        token: Any,
        manager: JobManager,
    ) -> None:
        self.service.execute_job(job, token, manager)

    @staticmethod
    def claims_for(job: Job) -> Claims:
        processor = job.request["processor_request"]
        device = processor.get("configuration", {}).get("device")
        return Claims(
            cpu=1,
            accelerator=1 if device == "mps" else 0,
            external=0,
            locks=(f"recording:{job.context['recording_id']}:events",),
        )
