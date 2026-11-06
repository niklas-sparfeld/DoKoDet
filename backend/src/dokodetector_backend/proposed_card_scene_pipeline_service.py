"""Backend execution service for recording-wide proposed card scenes."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid4, uuid5

from doko_operations.card_plane_calibration import CalibrationRevisionStore
from doko_operations.pipeline_data import (
    DataRevision,
    ImplementationIdentity,
    ProcessorProducer,
    ProcessorRunRequest,
    RecordingVideoSource,
    RunFailure,
    RunItemOutcome,
    RunProgress,
    canonical_json_bytes,
    parse_source,
    sha256_bytes,
)
from doko_operations.proposed_card_scene_processor import (
    PROPOSED_CARD_SCENE_PROCESSOR_TYPE,
    build_proposed_card_scenes,
    visible_card_data_to_local_result,
)
from table_evidence_analyzer.pipeline_data import (
    PROPOSED_CARD_SCENE_DATA_SCHEMA_VERSION,
    ProposedCardSceneData,
    VisibleCardData,
    canonical_proposed_card_scene_data_bytes,
    parse_visible_card_data_bytes,
)

from dokodetector_backend.config import Settings
from dokodetector_backend.job_store import Job, JobCancelled, JobManager
from dokodetector_backend.pipeline_node_selection_store import PipelineNodeSelectionStore
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_store import (
    PipelineNotFound,
    PipelineRuntimeStorage,
    ProcessorRunStore,
    StoredPipelineRevision,
    StoredProcessorRun,
)

LOGGER = logging.getLogger(__name__)
_SAFE = re.compile(r"[^A-Za-z0-9._:-]+")


class ProposedCardScenePipelineError(RuntimeError):
    """The proposed-card-scene pipeline could not execute a request."""


class ProposedCardScenePipelineInputError(ProposedCardScenePipelineError, ValueError):
    """The proposed-card-scene request is invalid."""


def _safe(value: str) -> str:
    return _SAFE.sub("-", value).strip("-") or "proposal"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class ProposedCardScenePipelineService:
    """Queue and retain one immutable proposal result for a selected detector revision."""

    def __init__(
        self,
        settings: Settings,
        *,
        run_store: ProcessorRunStore,
        selection_store: PipelineNodeSelectionStore,
        node_store: PipelineNodeStore | None = None,
    ) -> None:
        self.settings = settings
        self.run_store = run_store
        self.selection_store = selection_store
        self.node_store = node_store or getattr(
            getattr(selection_store, "lineage_writer", None), "node_store", None
        )
        self.storage = PipelineRuntimeStorage(settings.evidence_root, settings.operations_root)
        self.job_manager_provider: Any | None = None

    def start_proposal(self, recording_id: str, payload: Mapping[str, Any]) -> StoredProcessorRun:
        """Accept a proposal job through the shared manager and return its domain run."""
        if self.job_manager_provider is None:
            raise ProposedCardScenePipelineError("the shared job manager is not available")
        run_id = payload.get("run_id")
        key = (
            str(uuid5(NAMESPACE_URL, f"proposed-card-scene-run:{run_id}"))
            if isinstance(run_id, str) and run_id
            else str(uuid4())
        )
        job = self.job_manager_provider().accept(
            key,
            {
                "type": "proposed_card_scene_creation",
                "context": {"recording_id": recording_id},
                "request": dict(payload),
            },
        )
        return self.get_run(recording_id, job.id)

    def retry(self, recording_id: str, run_id: str) -> StoredProcessorRun:
        """Create a linked retry through the shared manager."""
        self.get_run(recording_id, run_id)
        if self.job_manager_provider is None:
            raise ProposedCardScenePipelineError("the shared job manager is not available")
        job = self.job_manager_provider().retry(run_id, str(uuid4()))
        return self.get_run(recording_id, job.id)

    def freeze_job_request(self, recording_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = self._build_request(recording_id, payload)
        return {
            "schema": "proposed-card-scene-job-request/v1",
            "processor_request": request.to_mapping(),
        }

    def validate_frozen_job_request(self, recording_id: str, frozen: Mapping[str, Any]) -> None:
        try:
            request = ProcessorRunRequest.from_mapping(frozen["processor_request"])
        except (KeyError, TypeError, ValueError) as error:
            raise ProposedCardScenePipelineInputError(
                "the frozen proposal request is invalid"
            ) from error
        if frozen.get("schema") != "proposed-card-scene-job-request/v1":
            raise ProposedCardScenePipelineInputError("the frozen proposal schema is invalid")
        if request.source.recording_id != recording_id or len(request.input_revision_ids) != 1:
            raise ProposedCardScenePipelineInputError("the frozen proposal inputs are invalid")
        input_revision = self._visible_input(
            recording_id, request.input_revision_ids[0], request.input_node_ref
        )
        producer = input_revision.producer
        if (
            input_revision.recording_id != recording_id
            or input_revision.content_type != "visible_cards"
            or not isinstance(input_revision.content, VisibleCardData)
            or input_revision.origin != "processor"
            or request.processor_type != PROPOSED_CARD_SCENE_PROCESSOR_TYPE
            or not isinstance(producer, ProcessorProducer)
            or producer.processor_type != "visible-card-detection"
            or producer.model_id is None
            or not producer.model_id.startswith("local-rfdetr-")
        ):
            raise ProposedCardScenePipelineInputError("the frozen visible-card revision is invalid")

    def prepare_job(self, job_id: str, envelope: Mapping[str, Any], after_write: Any) -> None:
        recording_id = envelope["context"]["recording_id"]
        frozen = envelope["request"]
        self.validate_frozen_job_request(recording_id, frozen)
        values = dict(frozen["processor_request"])
        values["run_id"] = job_id
        processor_request = ProcessorRunRequest.from_mapping(values)
        run, _ = self.run_store.create(processor_request)
        if run.request.to_mapping() != processor_request.to_mapping():
            raise ProposedCardScenePipelineInputError("the accepted proposal run conflicts")
        del after_write

    def verify_job(self, job_id: str, envelope: Mapping[str, Any]) -> bool:
        try:
            self.validate_frozen_job_request(
                envelope["context"]["recording_id"], envelope["request"]
            )
            expected = dict(envelope["request"]["processor_request"])
            expected["run_id"] = job_id
            return (
                self.run_store.require(job_id).request.to_mapping()
                == ProcessorRunRequest.from_mapping(expected).to_mapping()
            )
        except (OSError, KeyError, TypeError, ValueError, PipelineNotFound):
            return False

    def verify_job_publication(self, job: Job, results: list[dict[str, Any]]) -> bool:
        try:
            if len(results) != 1 or results[0].get("kind") != "pipeline_revision":
                return False
            revision = self.selection_store.require_processor_revision(results[0]["id"])
            run = self.run_store.require(job.id)
            return (
                run.state.status in {"complete", "partial"}
                and run.state.output_revision_ids == (revision.manifest.revision_id,)
                and results[0].get("digest") == revision.manifest.content_sha256
            )
        except (KeyError, TypeError, ValueError, PipelineNotFound):
            return False

    def reconcile_job_states(self, jobs: list[Job]) -> None:
        for job in jobs:
            if job.type != "proposed_card_scene_creation":
                continue
            run = self.run_store.get(job.id)
            if run is None or run.state.status != "running":
                continue
            if job.state == "interrupted":
                failure = RunFailure(
                    "backend_restarted", "Proposal processing was interrupted by a backend restart."
                )
            elif job.state == "cancelled":
                failure = RunFailure("cancelled", "Proposal processing was cancelled.")
            elif job.state == "failed":
                failure = RunFailure("job_failed", "The proposal job failed.")
            else:
                continue
            self.run_store.fail(job.id, failure)

    def execute_job(self, job: Job, token: Any, manager: JobManager) -> None:
        run_id = job.id
        run = self.run_store.start(run_id)
        try:
            token.check()
            source_revision = self._visible_input(
                run.request.source.recording_id,
                run.request.input_revision_ids[0],
                run.request.input_node_ref,
            )
            if not isinstance(source_revision.content, VisibleCardData):
                raise ProposedCardScenePipelineError("the proposal input content is invalid")
            local_result = visible_card_data_to_local_result(
                source_revision.content,
                recording_id=run.request.source.recording_id,
                source_revision=run.request.input_revision_ids[0],
            )

            def report_progress(
                phase: str, completed: int, total: int, message: str, step: int, steps: int
            ) -> None:
                token.check()
                self._report_progress(
                    run_id,
                    phase=phase,
                    completed=completed,
                    total=total,
                    message=message,
                    step=step,
                    steps=steps,
                )
                manager.report_progress(
                    job.id, phase=message, completed=completed, total=total, unit="frames"
                )

            processor_result = build_proposed_card_scenes(
                local_result,
                detector_revision_id=run.request.input_revision_ids[0],
                detector_revision_digest=source_revision.content_sha256,
                calibration_store=CalibrationRevisionStore(self.settings.operations_root),
                progress_callback=report_progress,
            )
            token.check()
            if processor_result.data is None:
                failure = processor_result.failure or {
                    "code": "proposal_failed",
                    "message": "The proposal processor failed.",
                }
                self._fail_safely(run_id, str(failure["code"]), str(failure["message"]))
                raise ProposedCardScenePipelineError(str(failure["message"]))
            revision = self._publish_revision(run, processor_result.data)
            items = tuple(
                RunItemOutcome(
                    item_id=frame.frame_id,
                    status="succeeded",
                    result=frame.to_mapping(),
                    failure=None,
                )
                for frame in processor_result.data.frames
            )
            progress = RunProgress(completed=len(items), total=len(items))
            self._report_progress(
                run_id,
                phase="complete",
                completed=len(items),
                total=len(items),
                message="Proposed card scenes are ready",
                step=3,
                steps=3,
            )
            output = {
                "kind": "pipeline_revision",
                "id": revision.manifest.revision_id,
                "digest": revision.manifest.content_sha256,
                "available": True,
            }

            def commit() -> None:
                if processor_result.status == "partial":
                    self.run_store.partial(
                        run_id,
                        progress=progress,
                        items=items,
                        output_revision_ids=[revision.manifest.revision_id],
                        metrics=self._current_metrics(run_id),
                    )
                else:
                    self.run_store.complete(
                        run_id,
                        [revision.manifest.revision_id],
                        progress=progress,
                        items=items,
                        metrics=self._current_metrics(run_id),
                    )

            if not manager.publish(job.id, [output], commit):
                raise JobCancelled("job cancellation requested before proposal publication")
        except JobCancelled:
            self._fail_safely(run_id, "cancelled", "Proposal processing was cancelled.")
            raise
        except Exception:
            self._fail_safely(
                run_id, "proposal_failed", "The proposed-card-scene processor failed."
            )
            raise

    def list_runs(self, recording_id: str) -> tuple[StoredProcessorRun, ...]:
        return tuple(
            run
            for run in self.run_store.list_for_recording(
                recording_id,
                include_items=False,
                validate_output_revisions=False,
            )
            if run.request.processor_type == PROPOSED_CARD_SCENE_PROCESSOR_TYPE
        )

    def get_run(self, recording_id: str, run_id: str) -> StoredProcessorRun:
        run = self.run_store.require(run_id)
        self._require_recording(run.request.source, recording_id)
        return run

    def get_result(
        self, recording_id: str, run_id: str
    ) -> tuple[StoredProcessorRun, tuple[StoredPipelineRevision, ...]]:
        run = self.get_run(recording_id, run_id)
        if not run.state.output_revision_ids:
            raise ProposedCardScenePipelineError("the proposal result is not available")
        return run, tuple(
            self.selection_store.require_processor_revision(item)
            for item in run.state.output_revision_ids
        )

    def _build_request(self, recording_id: str, payload: Mapping[str, Any]) -> ProcessorRunRequest:
        if not isinstance(payload, Mapping):
            raise ProposedCardScenePipelineInputError("the proposal request must be an object")
        unknown = set(payload) - {
            "run_id",
            "configuration",
            "input_node_ref",
        }
        if unknown:
            raise ProposedCardScenePipelineInputError(
                "the proposal request has unknown fields: " + ", ".join(sorted(unknown))
            )
        node_ref = payload.get("input_node_ref")
        if node_ref is None:
            exact = getattr(self.selection_store, "get_exact", lambda *_: None)(
                recording_id, "visible_cards"
            )
            if exact is not None and exact.selected_generated is not None:
                node_ref = {
                    **exact.selected_generated,
                    "revision_policy": "current_head",
                }
        if node_ref is None:
            raise ProposedCardScenePipelineInputError(
                "an exact visible-card node revision is required"
            )
        if not isinstance(node_ref, Mapping) or set(node_ref) != {
            "node_id",
            "revision_id",
            "revision_policy",
        }:
            raise ProposedCardScenePipelineInputError("input_node_ref is invalid")
        revision_id = node_ref.get("revision_id")
        if not isinstance(revision_id, str) or not revision_id:
            raise ProposedCardScenePipelineInputError("input_node_ref needs a revision ID")
        revision = self._visible_input(recording_id, revision_id, node_ref)
        if revision.recording_id != recording_id:
            raise ProposedCardScenePipelineInputError(
                "the selected visible-card revision belongs to another recording"
            )
        if revision.content_type != "visible_cards" or not isinstance(
            revision.content, VisibleCardData
        ):
            raise ProposedCardScenePipelineInputError(
                "the proposal input must be a visible-card revision"
            )
        producer = revision.producer
        if (
            revision.origin != "processor"
            or not isinstance(producer, ProcessorProducer)
            or producer.processor_type != "visible-card-detection"
            or producer.model_id is None
            or not producer.model_id.startswith("local-rfdetr-")
        ):
            raise ProposedCardScenePipelineInputError(
                "the proposal input must be a generated local RF-DETR revision"
            )
        run_id = payload.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ProposedCardScenePipelineInputError("run_id is required")
        configuration = payload.get("configuration", {})
        if not isinstance(configuration, Mapping):
            raise ProposedCardScenePipelineInputError("configuration must be an object")
        return ProcessorRunRequest(
            run_id=run_id,
            processor_type=PROPOSED_CARD_SCENE_PROCESSOR_TYPE,
            source=revision.source,
            input_revision_ids=(revision_id,),
            implementation=ImplementationIdentity(
                name="proposed-card-scene-processor", version="v2"
            ),
            model=None,
            configuration=dict(configuration),
            extraction_policy={"policy_id": "selected-visible-card-revision/v1"},
            crop_policy=None,
            input_node_ref=revision.node_ref,
        )

    def _visible_input(self, recording_id: str, revision_id: str, node_ref: Any):
        if node_ref is not None:
            if (
                self.node_store is None
                or not isinstance(node_ref, Mapping)
                or set(node_ref)
                != {
                    "node_id",
                    "revision_id",
                    "revision_policy",
                }
            ):
                raise ProposedCardScenePipelineInputError("input_node_ref is invalid")
            if node_ref["revision_id"] != revision_id or node_ref["revision_policy"] not in {
                "current_head",
                "historical",
            }:
                raise ProposedCardScenePipelineInputError("input_node_ref does not match input")
            try:
                node = self.node_store.get(node_ref["node_id"])
                revision = self.node_store.read_revision(node.node_id, revision_id)
                content = parse_visible_card_data_bytes(canonical_json_bytes(revision.content))
                source = parse_source(node.source)
            except (FileNotFoundError, KeyError, TypeError, ValueError) as error:
                raise ProposedCardScenePipelineInputError(
                    "the visible-card node revision is unavailable"
                ) from error
            if (
                node.content_type != "visible_cards"
                or source.recording_id != recording_id
                or (
                    node_ref["revision_policy"] == "current_head"
                    and node.head_revision_id != revision_id
                )
            ):
                raise ProposedCardScenePipelineInputError("the visible-card node input is invalid")
            producer = None
            raw_producer = revision.metadata.get("producer")
            if isinstance(raw_producer, Mapping):
                try:
                    producer = ProcessorProducer.from_mapping(raw_producer)
                except (TypeError, ValueError):
                    producer = None
            return SimpleNamespace(
                recording_id=recording_id,
                content_type=node.content_type,
                content=content,
                origin=revision.metadata.get("origin"),
                producer=producer,
                source=source,
                node_ref=dict(node_ref),
                content_sha256=revision.content_sha256,
            )
        raise ProposedCardScenePipelineInputError("the visible-card node revision is unavailable")

    def _publish_revision(
        self, run: StoredProcessorRun, data: ProposedCardSceneData
    ) -> StoredPipelineRevision:
        revision_id = f"card-scene-proposals-{_safe(run.run_id)}-attempt-{run.state.attempt}"
        manifest = DataRevision(
            revision_id=revision_id,
            content_type="card_scene_proposals",
            content_schema=PROPOSED_CARD_SCENE_DATA_SCHEMA_VERSION,
            recording_id=run.request.source.recording_id,
            source=run.request.source,
            content_sha256=sha256_bytes(canonical_proposed_card_scene_data_bytes(data)),
            input_revision_ids=run.request.input_revision_ids,
            origin="processor",
            producer=ProcessorProducer(
                run_id=run.run_id,
                processor_type=run.request.processor_type,
                implementation_id="proposed-card-scene-processor/v2",
                model_id=None,
            ),
            coverage={
                "kind": "proposed-card-scenes",
                "detector_revision_id": data.detector_revision_id,
                "detector_revision_digest": data.detector_revision_digest,
                "calibration_revision_id": data.calibration_revision_id,
                "calibration_digest": data.calibration_digest,
                "supported_frame_count": sum(frame.status == "supported" for frame in data.frames),
                "no_card_frame_count": sum(
                    frame.status == "no_cards_detected" for frame in data.frames
                ),
                "unsupported_frame_count": sum(
                    frame.status == "unsupported" for frame in data.frames
                ),
            },
            created_at=_now(),
        )
        stored, _ = self.selection_store.publish_processor_revision(manifest, data)
        return stored

    def _fail_safely(self, run_id: str, code: str, message: str) -> None:
        try:
            current = self.run_store.get(run_id)
            if current is not None and current.state.status == "running":
                metrics = self._current_metrics(run_id, current=current)
                logs = metrics.get("logs")
                activity_logs = list(logs) if isinstance(logs, list) else []
                activity_logs.append({"at": _now(), "level": "error", "message": message})
                metrics.update(
                    {
                        "schema_version": "processor-run-activity/v1",
                        "activity": {
                            "phase": "failed",
                            "message": message,
                            "step": None,
                            "steps": None,
                        },
                        "logs": activity_logs,
                    }
                )
                self.run_store.fail(
                    run_id,
                    RunFailure(code=code, message=message),
                    metrics=metrics,
                )
                LOGGER.error(
                    "proposed_card_scene_pipeline_failed run_id=%s code=%s message=%s",
                    run_id,
                    code,
                    message,
                )
        except Exception:
            LOGGER.exception("proposed_card_scene_pipeline_failure_persist_failed")

    def _report_progress(
        self,
        run_id: str,
        *,
        phase: str,
        completed: int,
        total: int,
        message: str,
        step: int,
        steps: int,
    ) -> None:
        current = self.run_store.require(
            run_id,
            include_items=False,
            validate_output_revisions=False,
        )
        metrics = self._current_metrics(run_id, current=current)
        raw_logs = metrics.get("logs")
        logs = list(raw_logs) if isinstance(raw_logs, list) else []
        logs.append({"at": _now(), "level": "info", "message": message})
        activity = {
            "phase": phase,
            "message": message,
            "step": step,
            "steps": steps,
        }
        next_metrics = {
            **metrics,
            "schema_version": "processor-run-activity/v1",
            "activity": activity,
            "logs": logs,
        }
        self.run_store.update_progress(
            run_id,
            progress=RunProgress(completed=completed, total=total),
            metrics=next_metrics,
        )
        LOGGER.info(
            "proposed_card_scene_progress run_id=%s phase=%s step=%s/%s progress=%s/%s message=%s",
            run_id,
            phase,
            step,
            steps,
            completed,
            total,
            message,
        )

    def _current_metrics(
        self,
        run_id: str,
        *,
        current: StoredProcessorRun | None = None,
    ) -> dict[str, Any]:
        run = current or self.run_store.require(
            run_id,
            include_items=False,
            validate_output_revisions=False,
        )
        return dict(run.state.metrics)

    @staticmethod
    def _require_recording(source: RecordingVideoSource, recording_id: str) -> None:
        if source.recording_id != recording_id:
            raise PipelineNotFound(f"The proposal run was not found for recording: {recording_id}")


__all__ = [
    "ProposedCardScenePipelineError",
    "ProposedCardScenePipelineInputError",
    "ProposedCardScenePipelineService",
]
