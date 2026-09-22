"""Backend execution service for recording-wide proposed card scenes."""

from __future__ import annotations

import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Mapping

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
    sha256_bytes,
)
from doko_operations.proposed_card_scene_processor import (
    PROPOSED_CARD_SCENE_PROCESSOR_TYPE,
    ProposedCardSceneProcessorError,
    build_proposed_card_scenes,
    visible_card_data_to_local_result,
)
from table_evidence_analyzer.pipeline_data import (
    ProposedCardSceneData,
    VisibleCardData,
    canonical_proposed_card_scene_data_bytes,
)

from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_store import (
    PipelineConflict,
    PipelineNotFound,
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    PipelineSelectionStore,
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
        revision_store: PipelineRevisionStore,
        run_store: ProcessorRunStore,
        selection_store: PipelineSelectionStore,
    ) -> None:
        self.settings = settings
        self.revision_store = revision_store
        self.run_store = run_store
        self.selection_store = selection_store
        self.storage = PipelineRuntimeStorage(settings.evidence_root, settings.operations_root)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="card-scene-proposal")
        self._futures: dict[str, Future[None]] = {}
        self._lock = RLock()

    async def start(self) -> None:
        """Keep the service lifecycle compatible with the other pipeline services."""

    async def stop(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
        with self._lock:
            self._futures.clear()

    def start_proposal(self, recording_id: str, payload: Mapping[str, Any]) -> StoredProcessorRun:
        request = self._build_request(recording_id, payload)
        run, created = self.run_store.create(request)
        if not created:
            return run
        running = self.run_store.start(run.run_id)
        with self._lock:
            self._futures[run.run_id] = self._executor.submit(self._execute, run.run_id)
        return running

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
        with self._lock:
            future = self._futures.get(run_id)
        if run.state.status in {"complete", "partial", "failed"}:
            return run
        if future is not None:
            future.result()
            return self.run_store.require(run_id)
        return run

    def get_result(
        self, recording_id: str, run_id: str
    ) -> tuple[StoredProcessorRun, tuple[StoredPipelineRevision, ...]]:
        run = self.get_run(recording_id, run_id)
        if not run.state.output_revision_ids:
            raise ProposedCardScenePipelineError("the proposal result is not available")
        return run, tuple(
            self.revision_store.require(item) for item in run.state.output_revision_ids
        )

    def retry(self, recording_id: str, run_id: str) -> StoredProcessorRun:
        self.get_run(recording_id, run_id)
        retried = self.run_store.retry(run_id)
        with self._lock:
            self._futures[run_id] = self._executor.submit(self._execute, run_id)
        return retried

    def _build_request(
        self, recording_id: str, payload: Mapping[str, Any]
    ) -> ProcessorRunRequest:
        if not isinstance(payload, Mapping):
            raise ProposedCardScenePipelineInputError("the proposal request must be an object")
        unknown = set(payload) - {
            "run_id",
            "visible_card_revision_id",
            "input_revision_ids",
            "configuration",
        }
        if unknown:
            raise ProposedCardScenePipelineInputError(
                "the proposal request has unknown fields: " + ", ".join(sorted(unknown))
            )
        revision_id = payload.get("visible_card_revision_id")
        input_ids = payload.get("input_revision_ids")
        if input_ids is not None:
            if not isinstance(input_ids, list) or len(input_ids) != 1:
                raise ProposedCardScenePipelineInputError(
                    "a proposal needs one visible-card input revision"
                )
            input_revision_id = input_ids[0]
            if revision_id is not None and revision_id != input_revision_id:
                raise ProposedCardScenePipelineInputError(
                    "visible_card_revision_id conflicts with input_revision_ids"
                )
            revision_id = input_revision_id
        if revision_id is None:
            selection = self.selection_store.get(recording_id, "visible_cards")
            revision_id = None if selection is None else selection.selected_generated_revision_id
        if not isinstance(revision_id, str) or not revision_id:
            raise ProposedCardScenePipelineInputError(
                "no generated visible-card revision is selected"
            )
        revision = self.revision_store.require(revision_id)
        if revision.manifest.recording_id != recording_id:
            raise ProposedCardScenePipelineInputError(
                "the selected visible-card revision belongs to another recording"
            )
        if revision.manifest.content_type != "visible_cards" or not isinstance(
            revision.content, VisibleCardData
        ):
            raise ProposedCardScenePipelineInputError(
                "the proposal input must be a visible-card revision"
            )
        producer = revision.manifest.producer
        if (
            revision.manifest.origin != "processor"
            or not isinstance(producer, ProcessorProducer)
            or producer.processor_type != "visible-card-detection"
            or producer.model_id is None
            or not producer.model_id.startswith("local-rfdetr-cascade")
        ):
            raise ProposedCardScenePipelineInputError(
                "the proposal input must be a generated local cascade revision"
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
            source=revision.manifest.source,
            input_revision_ids=(revision_id,),
            implementation=ImplementationIdentity(
                name="proposed-card-scene-processor", version="v1"
            ),
            model=None,
            configuration=dict(configuration),
            extraction_policy={"policy_id": "selected-visible-card-revision/v1"},
            crop_policy=None,
        )

    def _execute(self, run_id: str) -> None:
        try:
            run = self.run_store.require(run_id)
            source_revision = self.revision_store.require(run.request.input_revision_ids[0])
            if not isinstance(source_revision.content, VisibleCardData):
                raise ProposedCardScenePipelineError("the proposal input content is invalid")
            local_result = visible_card_data_to_local_result(
                source_revision.content,
                recording_id=run.request.source.recording_id,
                source_revision=source_revision.manifest.revision_id,
            )
            processor_result = build_proposed_card_scenes(
                local_result,
                detector_revision_id=source_revision.manifest.revision_id,
                detector_revision_digest=source_revision.manifest.content_sha256,
                calibration_store=CalibrationRevisionStore(self.settings.operations_root),
            )
            if processor_result.data is None:
                failure = processor_result.failure or {
                    "code": "proposal_failed",
                    "message": "the proposed-card-scene processor failed",
                    "action": "inspect the selected generated result and retry",
                }
                self.run_store.fail(
                    run_id,
                    RunFailure(code=str(failure["code"]), message=str(failure["message"])),
                )
                return
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
            if processor_result.status == "partial":
                self.run_store.partial(
                    run_id,
                    progress=progress,
                    items=items,
                    output_revision_ids=[revision.manifest.revision_id],
                )
            else:
                self.run_store.complete(
                    run_id,
                    [revision.manifest.revision_id],
                    progress=progress,
                    items=items,
                )
        except (ProposedCardSceneProcessorError, PipelineNotFound, PipelineConflict) as error:
            self._fail_safely(run_id, "proposal_failed", str(error))
        except Exception:
            LOGGER.exception("proposed_card_scene_pipeline_worker_failed")
            self._fail_safely(
                run_id, "proposal_failed", "The proposed-card-scene processor failed."
            )

    def _publish_revision(
        self, run: StoredProcessorRun, data: ProposedCardSceneData
    ) -> StoredPipelineRevision:
        revision_id = (
            f"card-scene-proposals-{_safe(run.run_id)}-attempt-{run.state.attempt}"
        )
        manifest = DataRevision(
            revision_id=revision_id,
            content_type="card_scene_proposals",
            content_schema="proposed-card-scene-data/v1",
            recording_id=run.request.source.recording_id,
            source=run.request.source,
            content_sha256=sha256_bytes(canonical_proposed_card_scene_data_bytes(data)),
            input_revision_ids=run.request.input_revision_ids,
            origin="processor",
            producer=ProcessorProducer(
                run_id=run.run_id,
                processor_type=run.request.processor_type,
                implementation_id="proposed-card-scene-processor/v1",
                model_id=None,
            ),
            coverage={
                "kind": "proposed-card-scenes",
                "detector_revision_id": data.detector_revision_id,
                "detector_revision_digest": data.detector_revision_digest,
                "calibration_revision_id": data.calibration_revision_id,
                "calibration_digest": data.calibration_digest,
                "supported_frame_count": sum(frame.status == "supported" for frame in data.frames),
                "unsupported_frame_count": sum(
                    frame.status == "unsupported" for frame in data.frames
                ),
            },
            created_at=_now(),
        )
        stored, _ = self.revision_store.publish(manifest, data)
        return stored

    def _fail_safely(self, run_id: str, code: str, message: str) -> None:
        try:
            current = self.run_store.get(run_id)
            if current is not None and current.state.status == "running":
                self.run_store.fail(run_id, RunFailure(code=code, message=message))
        except Exception:
            LOGGER.exception("proposed_card_scene_pipeline_failure_persist_failed")

    @staticmethod
    def _require_recording(source: RecordingVideoSource, recording_id: str) -> None:
        if source.recording_id != recording_id:
            raise PipelineNotFound(f"The proposal run was not found for recording: {recording_id}")


__all__ = [
    "ProposedCardScenePipelineError",
    "ProposedCardScenePipelineInputError",
    "ProposedCardScenePipelineService",
]
