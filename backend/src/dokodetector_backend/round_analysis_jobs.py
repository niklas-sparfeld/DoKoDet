"""Job Manager adapter for round analysis."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from dokodetector_backend.job_models import Job
from dokodetector_backend.job_scheduler import Claims
from dokodetector_backend.job_store import JobManager
from dokodetector_backend.round_analysis_service import RoundAnalysisService


class RoundAnalysisJobParticipant:
    """Validate immutable round inputs and execute analysis as a managed job."""

    def __init__(self, service: RoundAnalysisService) -> None:
        self.service = service

    def validate(self, request: dict[str, Any]) -> None:
        if (
            request.get("type") != "round_analysis"
            or not isinstance(request.get("context"), dict)
            or not isinstance(request["context"].get("recording_id"), str)
            or not isinstance(request.get("request"), dict)
        ):
            raise ValueError("invalid round-analysis job request")
        import json

        from dokodetector_backend.round_analysis_contract import (
            parse_round_analysis_create_request_bytes,
        )

        parsed = parse_round_analysis_create_request_bytes(
            json.dumps(
                request["request"],
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        if request["context"]["recording_id"] != parsed.recording_id:
            raise ValueError("round-analysis recording context does not match its request")
        self.service.validate_request(parsed)

    def prepare(self, job_id: str, request: dict[str, Any], after_write: Any) -> None:
        self.service.prepare_job(job_id, request["request"], after_write)

    @staticmethod
    def retry_request(request: dict[str, Any]) -> dict[str, Any]:
        return {
            **request,
            "request": {**request["request"], "analysis_id": str(uuid4())},
        }

    def verify(self, job_id: str, request: dict[str, Any]) -> bool:
        return self.service.verify_job(job_id, request["request"])

    def job_fields(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.service.job_fields(request)

    def verify_publication(self, job: Job, results: list[dict[str, Any]]) -> bool:
        return self.service.verify_job_publication(job, results)

    def reconcile(self, jobs: list[Job]) -> None:
        self.service.reconcile_jobs(jobs)

    def handle(self, job: Job, _claims: Claims, token: Any, manager: JobManager) -> None:
        self.service.execute_job(job, token, manager)

    @staticmethod
    def claims_for(job: Job) -> Claims:
        return Claims(cpu=1, locks=(f"recording:{job.context['recording_id']}:round_analysis",))
