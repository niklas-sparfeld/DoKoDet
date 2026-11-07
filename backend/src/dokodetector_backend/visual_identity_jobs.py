"""Job Manager adapter for visual identity processing."""

from __future__ import annotations

from typing import Any

from doko_operations.pipeline_data import ProcessorRunRequest, RunFailure

from dokodetector_backend.job_models import Job
from dokodetector_backend.job_scheduler import Claims
from dokodetector_backend.job_store import JobManager
from dokodetector_backend.pipeline_storage import PipelineNotFound
from dokodetector_backend.visual_identity_pipeline_service import (
    VisualIdentityPipelineService,
)


class VisualIdentityJobParticipant:
    """Freeze exact crop inputs and run identity work under shared job ownership."""

    def __init__(self, service: VisualIdentityPipelineService) -> None:
        self.service = service

    def normalize(self, request: dict[str, Any]) -> dict[str, Any]:
        context = request.get("context")
        body = request.get("request")
        if (
            request.get("type") != "visual_identity_classification"
            or not isinstance(context, dict)
            or set(context) != {"recording_id"}
            or not isinstance(context["recording_id"], str)
            or not isinstance(body, dict)
        ):
            raise ValueError("invalid visual-identity job request")
        if body.get("schema") == "visual-identity-job-request/v1":
            self.validate(request)
            return request
        run = self.service._build_request(context["recording_id"], body)
        return {
            **request,
            "request": {
                "schema": "visual-identity-job-request/v1",
                "processor_request": run.to_mapping(),
            },
        }

    def validate(self, request: dict[str, Any]) -> None:
        context = request.get("context")
        body = request.get("request")
        if (
            request.get("type") != "visual_identity_classification"
            or not isinstance(context, dict)
            or set(context) != {"recording_id"}
            or not isinstance(context["recording_id"], str)
            or not isinstance(body, dict)
            or body.get("schema") != "visual-identity-job-request/v1"
        ):
            raise ValueError("invalid visual-identity job request")
        try:
            run = ProcessorRunRequest.from_mapping(body["processor_request"])
            self._validate_exact_inputs(context["recording_id"], run)
        except (KeyError, TypeError, ValueError, PipelineNotFound) as error:
            raise ValueError("the frozen visual-identity request is invalid") from error

    def _validate_exact_inputs(self, recording_id: str, run: ProcessorRunRequest) -> None:
        if (
            run.source.recording_id != recording_id
            or run.processor_type != "visual-card-identity"
            or len(run.input_revision_ids) != 1
            or run.input_node_refs is None
            or len(run.input_node_refs) != 1
            or run.crop_input is None
        ):
            raise ValueError("the frozen visual-identity inputs are invalid")
        revision = self.service.canonical_input_revision(run)
        _, source = self.service._accepted_source(recording_id)
        if revision.manifest.source != source:
            raise ValueError("the identity input does not match the accepted recording")
        frozen = self.service._freeze_crop_input(
            recording_id,
            revision,
            source=source,
            requested=run.crop_input,
        )
        if frozen.to_mapping() != run.crop_input:
            raise ValueError("the frozen identity crop input changed")

    def prepare(self, job_id: str, request: dict[str, Any], after_write: Any) -> None:
        self.validate(request)
        values = dict(request["request"]["processor_request"])
        values["run_id"] = job_id
        run, _ = self.service.run_store.create(ProcessorRunRequest.from_mapping(values))
        if run.request.to_mapping() != ProcessorRunRequest.from_mapping(values).to_mapping():
            raise ValueError("the accepted visual-identity run conflicts")
        del after_write

    def verify(self, job_id: str, request: dict[str, Any]) -> bool:
        try:
            self.validate(request)
            values = dict(request["request"]["processor_request"])
            values["run_id"] = job_id
            return self.service.run_store.require(job_id).request.to_mapping() == (
                ProcessorRunRequest.from_mapping(values).to_mapping()
            )
        except (OSError, KeyError, TypeError, ValueError, PipelineNotFound):
            return False

    def job_fields(self, request: dict[str, Any]) -> dict[str, Any]:
        run = ProcessorRunRequest.from_mapping(request["request"]["processor_request"])
        input_id = run.input_revision_ids[0]
        input_revision = self.service.canonical_input_revision(run)
        device = run.configuration.get("device")
        return {
            "label": "Classify visual identities",
            "inputs": [
                {
                    "kind": "pipeline_revision",
                    "id": input_id,
                    "digest": input_revision.manifest.content_sha256,
                },
                {
                    "kind": "visual_identity_crop_input",
                    "id": run.crop_input["source_revision_id"],
                    "digest": run.crop_input["manifest_digest"],
                },
            ],
            "implementation": {
                "implementation": run.implementation.to_mapping(),
                "model": None if run.model is None else run.model.to_mapping(),
                "configuration": dict(run.configuration),
                "extraction_policy": dict(run.extraction_policy),
                "crop_policy": None if run.crop_policy is None else dict(run.crop_policy),
                "device": device,
            },
        }

    def verify_publication(self, job: Job, results: list[dict[str, Any]]) -> bool:
        try:
            if len(results) != 1 or results[0].get("kind") != "pipeline_revision":
                return False
            revision = self.service.selection_store.require_processor_revision(results[0]["id"])
            run = self.service.run_store.require(job.id)
            return (
                run.state.status in {"complete", "partial"}
                and run.state.output_revision_ids == (revision.manifest.revision_id,)
                and results[0].get("digest") == revision.manifest.content_sha256
            )
        except (KeyError, TypeError, ValueError, PipelineNotFound):
            return False

    def reconcile(self, jobs: list[Job]) -> None:
        for job in jobs:
            if job.type != "visual_identity_classification":
                continue
            run = self.service.run_store.get(job.id)
            if run is None or run.state.status not in {"queued", "running"}:
                continue
            if job.state == "interrupted":
                failure = RunFailure(
                    "backend_restarted", "Identity processing was interrupted by a backend restart."
                )
            elif job.state == "cancelled":
                failure = RunFailure("cancelled", "Identity processing was cancelled.")
            elif job.state == "failed":
                failure = RunFailure("job_failed", "Identity processing failed.")
            else:
                continue
            if run.state.status == "queued":
                self.service.run_store.start(job.id)
            self.service.run_store.fail(job.id, failure)

    def execute(self, job: Job, claims: Claims, token: Any, manager: JobManager) -> None:
        self.service.execute_job(job, token, manager, cpu_budget=claims.cpu)

    def claims_for(self, job: Job) -> Claims:
        request = ProcessorRunRequest.from_mapping(job.request["processor_request"])
        device = request.configuration.get("device")
        return Claims(
            cpu=1,
            accelerator=1 if device == "mps" else 0,
            locks=(f"recording:{job.context['recording_id']}:visual_identities",),
        )
