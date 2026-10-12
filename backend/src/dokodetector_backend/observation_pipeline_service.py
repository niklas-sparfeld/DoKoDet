"""Execution service for recording-pipeline observation assembly."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from doko_operations.pipeline_data import (
    DataRevision,
    EventData,
    PipelineSelection,
    ProcessorProducer,
    ProcessorRunRequest,
    RecordingVideoSource,
    RunFailure,
    RunItemOutcome,
    RunProgress,
    sha256_bytes,
)
from table_evidence_analyzer import (
    ObservationAssemblyError,
    TableObservationData,
    VisibleCardData,
    VisualIdentityData,
    assemble_table_observations,
    canonical_table_observation_data_bytes,
)

from dokodetector_backend.pipeline_store import (
    PipelineNotFound,
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    PipelineSelectionConflict,
    PipelineSelectionStore,
    PipelineStateError,
    ProcessorRunStore,
    StoredPipelineRevision,
    StoredProcessorRun,
)

LOGGER = logging.getLogger(__name__)
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._:-]+")


class ObservationPipelineError(RuntimeError):
    """The observation assembly pipeline could not accept or execute a request."""


class ObservationPipelineInputError(ObservationPipelineError, ValueError):
    """The observation assembly request is invalid."""


class ObservationPipelineService:
    """Freeze exact upstream results and assemble reusable table observations."""

    def __init__(
        self,
        *,
        revision_store: PipelineRevisionStore,
        run_store: ProcessorRunStore,
        selection_store: PipelineSelectionStore,
        runtime_root: Any,
        operations_root: Any,
    ) -> None:
        self.revision_store = revision_store
        self.run_store = run_store
        self.selection_store = selection_store
        self.storage = PipelineRuntimeStorage(runtime_root, operations_root)
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="observation-pipeline"
        )
        self._futures: dict[str, Future[None]] = {}
        self._lock = RLock()

    async def start(self) -> None:
        """Keep the lifecycle symmetrical with the other pipeline services."""

    async def stop(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
        with self._lock:
            self._futures.clear()

    def start_assembly(self, recording_id: str, payload: Mapping[str, Any]) -> StoredProcessorRun:
        request = self._build_request(recording_id, payload)
        run, created = self.run_store.create(request)
        if not created:
            return run
        running = self.run_store.start(run.run_id)
        with self._lock:
            self._futures[run.run_id] = self._executor.submit(self._execute, run.run_id)
        return running

    def get_run(self, recording_id: str, run_id: str) -> StoredProcessorRun:
        run = self.run_store.require(run_id)
        self._require_recording(run.request, recording_id)
        with self._lock:
            future = self._futures.get(run_id)
        if run.state.status == "complete" and future is not None and not future.done():
            future.result()
            run = self.run_store.require(run_id)
        return run

    def list_runs(self, recording_id: str) -> tuple[StoredProcessorRun, ...]:
        return tuple(
            run
            for run in self.run_store.list()
            if run.request.processor_type == "observation-assembly"
            and run.request.source.recording_id == recording_id
        )

    def get_result(
        self, recording_id: str, run_id: str
    ) -> tuple[StoredProcessorRun, tuple[StoredPipelineRevision, ...]]:
        run = self.get_run(recording_id, run_id)
        revisions = tuple(
            self.revision_store.require(item) for item in run.state.output_revision_ids
        )
        return run, revisions

    def retry(self, recording_id: str, run_id: str) -> StoredProcessorRun:
        self.get_run(recording_id, run_id)
        retried = self.run_store.retry(run_id)
        with self._lock:
            self._futures[run_id] = self._executor.submit(self._execute, run_id)
        return retried

    def select_generated(self, recording_id: str, payload: Mapping[str, Any]) -> PipelineSelection:
        expected_revision = payload.get("expected_revision")
        selected = payload.get("selected_generated_revision_id")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ObservationPipelineInputError("expected_revision must be a non-negative integer.")
        if selected is not None and not isinstance(selected, str):
            raise ObservationPipelineInputError(
                "selected_generated_revision_id must be a string or null."
            )
        current = self.selection_store.get(recording_id, "table_observations")
        completed = None if current is None else current.selected_completed_reference_revision_id
        try:
            return self.selection_store.update_pointers(
                recording_id,
                "table_observations",
                expected_revision=expected_revision,
                selected_generated_revision_id=selected,
                selected_completed_reference_revision_id=completed,
            )
        except PipelineSelectionConflict:
            raise
        except (PipelineNotFound, PipelineStateError) as error:
            raise ObservationPipelineInputError(str(error)) from error

    def _build_request(self, recording_id: str, payload: Mapping[str, Any]) -> ProcessorRunRequest:
        if not isinstance(payload, Mapping):
            raise ObservationPipelineInputError("The processor request must be an object.")
        raw = payload.get("request", payload)
        if not isinstance(raw, Mapping):
            raise ObservationPipelineInputError("request must be an object.")
        input_ids = self._input_revision_ids(recording_id, raw)
        event_revision = self._require_revision(input_ids[0], "events", EventData)
        if not isinstance(event_revision.manifest.source, RecordingVideoSource):
            raise ObservationPipelineInputError(
                "observation assembly needs a recording video source"
            )
        source = event_revision.manifest.source
        if event_revision.manifest.source.recording_id != recording_id:
            raise ObservationPipelineInputError("the input revisions belong to another recording")
        visible_revision = self._require_revision(input_ids[1], "visible_cards", VisibleCardData)
        identity_revision = self._require_revision(
            input_ids[2], "visual_identities", VisualIdentityData
        )
        if (
            visible_revision.manifest.source != source
            or identity_revision.manifest.source != source
        ):
            raise ObservationPipelineInputError(
                "all input revisions must use the same recording video source"
            )
        source = event_revision.manifest.source
        values = dict(raw)
        for field in (
            "event_revision_id",
            "visible_card_revision_id",
            "visual_identity_revision_id",
        ):
            values.pop(field, None)
        values["input_revision_ids"] = list(input_ids)
        values.setdefault("schema_version", "processor-run-request/v1")
        run_id = raw.get("run_id") or payload.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ObservationPipelineInputError("run_id is required.")
        assert isinstance(event_revision.content, EventData)
        assert isinstance(visible_revision.content, VisibleCardData)
        assert isinstance(identity_revision.content, VisualIdentityData)
        try:
            assemble_table_observations(
                event_revision.content,
                visible_revision.content,
                identity_revision.content,
                recording_id=recording_id,
                video_sha256=source.video_sha256,
                assembly_run_id=run_id,
                input_revision_ids=input_ids,
            )
        except (ObservationAssemblyError, TypeError, ValueError) as error:
            raise ObservationPipelineInputError(
                f"the selected revisions are not compatible: {error}"
            ) from error
        values.setdefault("run_id", run_id)
        values.setdefault("processor_type", "observation-assembly")
        values.setdefault("source", source.to_mapping())
        values.setdefault("implementation", {"name": "observation-assembler", "version": "v1"})
        values.setdefault("model", None)
        values.setdefault("configuration", {})
        values.setdefault("extraction_policy", {"policy_id": "exact-event/v1"})
        values.setdefault("crop_policy", None)
        try:
            request = ProcessorRunRequest.from_mapping(values)
        except (TypeError, ValueError) as error:
            raise ObservationPipelineInputError(
                "The observation assembly request failed validation."
            ) from error
        if request.source != source:
            raise ObservationPipelineInputError(
                "The request source does not match the input event revision."
            )
        if request.processor_type != "observation-assembly":
            raise ObservationPipelineInputError(
                "The observation endpoint only accepts observation-assembly runs."
            )
        return request

    def _input_revision_ids(
        self, recording_id: str, raw: Mapping[str, Any]
    ) -> tuple[str, str, str]:
        named = tuple(
            raw.get(field)
            for field in (
                "event_revision_id",
                "visible_card_revision_id",
                "visual_identity_revision_id",
            )
        )
        provided = raw.get("input_revision_ids")
        if provided is not None and any(value is not None for value in named):
            raise ObservationPipelineInputError(
                "use input_revision_ids or named revision IDs, not both"
            )
        if provided is not None:
            values = tuple(provided) if isinstance(provided, list) else ()
        elif any(value is not None for value in named):
            values = named
        else:
            values = tuple(
                self._selected_revision_id(recording_id, content_type)
                for content_type in ("events", "visible_cards", "visual_identities")
            )
        if len(values) != 3 or any(not isinstance(value, str) or not value for value in values):
            raise ObservationPipelineInputError(
                "assembly needs ordered event, visible-card, and identity revision IDs"
            )
        if len(set(values)) != 3:
            raise ObservationPipelineInputError("assembly input revision IDs must be unique")
        return values  # type: ignore[return-value]

    def _selected_revision_id(self, recording_id: str, content_type: str) -> str:
        selection = self.selection_store.get(recording_id, content_type)
        if selection is None:
            raise ObservationPipelineInputError(f"no selected {content_type} revision is available")
        selected = (
            selection.selected_completed_reference_revision_id
            or selection.selected_generated_revision_id
        )
        if selected is None:
            raise ObservationPipelineInputError(f"no selected {content_type} revision is available")
        return selected

    def _require_revision(
        self, revision_id: str, content_type: str, content_class: type[Any]
    ) -> StoredPipelineRevision:
        revision = self.revision_store.require(revision_id)
        if revision.manifest.content_type != content_type or not isinstance(
            revision.content, content_class
        ):
            raise ObservationPipelineInputError(
                f"revision {revision_id} is not valid {content_type} content"
            )
        return revision

    def _execute(self, run_id: str) -> None:
        try:
            run = self.run_store.require(run_id)
            event_revision = self._require_revision(
                run.request.input_revision_ids[0], "events", EventData
            )
            visible_revision = self._require_revision(
                run.request.input_revision_ids[1], "visible_cards", VisibleCardData
            )
            identity_revision = self._require_revision(
                run.request.input_revision_ids[2], "visual_identities", VisualIdentityData
            )
            assert isinstance(event_revision.content, EventData)
            assert isinstance(visible_revision.content, VisibleCardData)
            assert isinstance(identity_revision.content, VisualIdentityData)
            total = len(event_revision.content.events)
            self.run_store.update_progress(run_id, progress=RunProgress(completed=0, total=total))
            configuration = run.request.configuration
            content = assemble_table_observations(
                event_revision.content,
                visible_revision.content,
                identity_revision.content,
                recording_id=run.request.source.recording_id,
                video_sha256=run.request.source.video_sha256,
                assembly_run_id=run_id,
                input_revision_ids=run.request.input_revision_ids,
                session_id=_optional_text(configuration.get("session_id")),
                calibration=_calibration(configuration.get("calibration")),
                analyzer_name=_optional_text(configuration.get("analyzer_name"))
                or "observation-assembler",
                analyzer_version=_optional_text(configuration.get("analyzer_version")) or "v1",
            )
            items = tuple(
                RunItemOutcome(
                    item_id=observation.observation_id,
                    status="succeeded",
                    result=observation.model_dump(mode="json", exclude_none=True),
                    failure=None,
                )
                for observation in content.observations
            )
            self.run_store.update_progress(
                run_id,
                progress=RunProgress(completed=total, total=total),
                items=items,
            )
            revision = self._publish_revision(run, content)
            self.run_store.complete(
                run_id,
                [revision.manifest.revision_id],
                progress=RunProgress(completed=total, total=total),
                items=items,
            )
            self._advance_generated_selection(
                run.request.source.recording_id, revision.manifest.revision_id
            )
        except (ObservationPipelineError, ObservationAssemblyError) as error:
            self._fail_safely(run_id, "assembly_failed", str(error))
        except Exception:
            LOGGER.exception("observation_pipeline_worker_failed")
            self._fail_safely(run_id, "assembly_failed", "The observation assembler failed.")

    def _publish_revision(
        self, run: StoredProcessorRun, content: TableObservationData
    ) -> StoredPipelineRevision:
        revision_id = f"table-observations-{_safe(run.run_id)}-attempt-{run.state.attempt}"
        manifest = DataRevision(
            revision_id=revision_id,
            content_type="table_observations",
            content_schema="table-observation-data/v1",
            recording_id=run.request.source.recording_id,
            source=run.request.source,
            content_sha256=sha256_bytes(canonical_table_observation_data_bytes(content)),
            input_revision_ids=run.request.input_revision_ids,
            origin="processor",
            producer=ProcessorProducer(
                run_id=run.run_id,
                processor_type=run.request.processor_type,
                implementation_id=_implementation_id(run.request.implementation),
                model_id=None,
            ),
            coverage={
                "kind": "assembled-events",
                "event_revision_id": run.request.input_revision_ids[0],
                "visible_card_revision_id": run.request.input_revision_ids[1],
                "visual_identity_revision_id": run.request.input_revision_ids[2],
                "observation_ids": [
                    observation.observation_id for observation in content.observations
                ],
            },
            created_at=_now(),
        )
        stored, _ = self.revision_store.publish(manifest, content)
        return stored

    def _advance_generated_selection(self, recording_id: str, revision_id: str) -> None:
        current = self.selection_store.get(recording_id, "table_observations")
        expected = 0 if current is None else current.revision
        completed = None if current is None else current.selected_completed_reference_revision_id
        try:
            self.selection_store.update_pointers(
                recording_id,
                "table_observations",
                expected_revision=expected,
                selected_generated_revision_id=revision_id,
                selected_completed_reference_revision_id=completed,
            )
        except PipelineSelectionConflict:
            LOGGER.warning(
                "observation_pipeline_selection_advance_conflict",
                extra={"recording_id": recording_id},
            )

    def _fail_safely(self, run_id: str, code: str, message: str) -> None:
        try:
            run = self.run_store.get(run_id)
            if run is not None and run.state.status == "running":
                self.run_store.fail(run_id, RunFailure(code=code, message=message))
        except Exception:
            LOGGER.exception("observation_pipeline_failure_persist_failed")

    @staticmethod
    def _require_recording(request: ProcessorRunRequest, recording_id: str) -> None:
        if request.source.recording_id != recording_id:
            raise PipelineNotFound(f"The processor run was not found for recording: {recording_id}")


def _implementation_id(identity: Any) -> str:
    return _safe(identity.name) + "." + _safe(identity.version)


def _safe(value: str) -> str:
    return _SAFE_COMPONENT.sub("-", value).strip("-") or "unknown"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _calibration(value: Any) -> str:
    return value if value in {"fixture", "uncalibrated", "calibrated"} else "uncalibrated"


__all__ = [
    "ObservationPipelineError",
    "ObservationPipelineInputError",
    "ObservationPipelineService",
]
