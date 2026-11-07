"""Execution service for recording-pipeline observation assembly."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from doko_operations.pipeline_data import (
    DataRevision,
    EventData,
    ProcessorProducer,
    ProcessorRunRequest,
    RecordingVideoSource,
    RunFailure,
    RunItemOutcome,
    RunProgress,
    canonical_json_bytes,
    parse_event_data_bytes,
    sha256_bytes,
)
from table_evidence_analyzer import (
    ObservationAssemblyError,
    TableObservationData,
    VisibleCardData,
    VisualIdentityData,
    assemble_table_observations,
    canonical_table_observation_data_bytes,
    parse_visible_card_data_bytes,
    parse_visual_identity_data_bytes,
)

from dokodetector_backend.job_models import Job, JobCancelled
from dokodetector_backend.job_store import JobManager
from dokodetector_backend.pipeline_node_selection_store import (
    ExactNodeSelection,
    PipelineNodeSelectionStore,
)
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_revision_store import StoredPipelineRevision
from dokodetector_backend.pipeline_storage import (
    PipelineNotFound,
    PipelineRuntimeStorage,
    PipelineSelectionConflict,
    PipelineStateError,
)
from dokodetector_backend.processor_run_models import StoredProcessorRun
from dokodetector_backend.processor_run_store import ProcessorRunStore

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
        run_store: ProcessorRunStore,
        selection_store: PipelineNodeSelectionStore,
        recording_store: Any,
        runtime_root: Any,
        operations_root: Any,
        node_store: PipelineNodeStore | None = None,
    ) -> None:
        self.run_store = run_store
        self.selection_store = selection_store
        self.node_store = node_store
        self.recording_store = recording_store
        self.storage = PipelineRuntimeStorage(runtime_root, operations_root)
        self.job_manager_provider: Any | None = None

    def start_assembly(self, recording_id: str, payload: Mapping[str, Any]) -> StoredProcessorRun:
        if self.job_manager_provider is None:
            raise ObservationPipelineError("the shared job manager is not available")
        request_payload = payload.get("request", payload)
        request_id = request_payload.get("run_id") if isinstance(request_payload, Mapping) else None
        key = (
            str(uuid5(NAMESPACE_URL, f"table-observation-run:{request_id}"))
            if isinstance(request_id, str) and request_id
            else str(uuid4())
        )
        job = self.job_manager_provider().accept(
            key,
            {
                "type": "table_observation_assembly",
                "context": {"recording_id": recording_id},
                "request": dict(payload),
            },
        )
        return self.get_run(recording_id, job.id)

    def get_run(self, recording_id: str, run_id: str) -> StoredProcessorRun:
        run = self.run_store.require(run_id)
        self._require_recording(run.request, recording_id)
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
            self.selection_store.require_processor_revision(item)
            for item in run.state.output_revision_ids
        )
        return run, revisions

    def retry(self, recording_id: str, run_id: str) -> StoredProcessorRun:
        self.get_run(recording_id, run_id)
        if self.job_manager_provider is None:
            raise ObservationPipelineError("the shared job manager is not available")
        job = self.job_manager_provider().retry(run_id, str(uuid4()))
        return self.get_run(recording_id, job.id)

    def freeze_job_request(self, recording_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = self._build_request(recording_id, payload)
        return {
            "schema": "table-observation-job-request/v1",
            "processor_request": request.to_mapping(),
        }

    def validate_frozen_job_request(self, recording_id: str, frozen: Mapping[str, Any]) -> None:
        try:
            request = ProcessorRunRequest.from_mapping(frozen["processor_request"])
        except (KeyError, TypeError, ValueError) as error:
            raise ObservationPipelineInputError(
                "the frozen observation request is invalid"
            ) from error
        if (
            frozen.get("schema") != "table-observation-job-request/v1"
            or request.source.recording_id != recording_id
            or request.processor_type != "observation-assembly"
            or len(request.input_revision_ids) != 3
        ):
            raise ObservationPipelineInputError("the frozen observation inputs are invalid")
        self._validate_frozen_inputs(recording_id, request)

    def _validate_frozen_inputs(self, recording_id: str, request: ProcessorRunRequest) -> None:
        if request.input_node_refs is None or self.node_store is None:
            raise ObservationPipelineInputError("frozen canonical input references are required")
        for revision_id, content_type, node_ref in zip(
            request.input_revision_ids,
            ("events", "visible_cards", "visual_identities"),
            request.input_node_refs,
            strict=True,
        ):
            try:
                node = self.node_store.get(node_ref["node_id"])
                revision = self.node_store.read_revision(node.node_id, node_ref["revision_id"])
                source = RecordingVideoSource.from_mapping(node.source)
                raw_manifest = revision.metadata.get("data_revision")
                manifest_id = (
                    raw_manifest.get("revision_id")
                    if isinstance(raw_manifest, Mapping)
                    else revision.revision_id
                )
            except (FileNotFoundError, KeyError, TypeError, ValueError) as error:
                raise ObservationPipelineInputError("a frozen node input is unavailable") from error
            if (
                node.content_type != content_type
                or source.recording_id != recording_id
                or source != request.source
                or manifest_id != revision_id
                or (
                    node_ref["revision_policy"] == "current_head"
                    and node.head_revision_id != node_ref["revision_id"]
                )
            ):
                raise ObservationPipelineInputError("the frozen inputs do not match the recording")

    def prepare_job(self, job_id: str, envelope: Mapping[str, Any], after_write: Any) -> None:
        recording_id = envelope["context"]["recording_id"]
        self.validate_frozen_job_request(recording_id, envelope["request"])
        values = dict(envelope["request"]["processor_request"])
        values["run_id"] = job_id
        request = ProcessorRunRequest.from_mapping(values)
        run, _ = self.run_store.create(request)
        if run.request.to_mapping() != request.to_mapping():
            raise ObservationPipelineInputError("the accepted observation run conflicts")
        del after_write

    def verify_job(self, job_id: str, envelope: Mapping[str, Any]) -> bool:
        try:
            self.validate_frozen_job_request(
                envelope["context"]["recording_id"], envelope["request"]
            )
            values = dict(envelope["request"]["processor_request"])
            values["run_id"] = job_id
            return self.run_store.require(job_id).request.to_mapping() == (
                ProcessorRunRequest.from_mapping(values).to_mapping()
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
                run.state.status == "complete"
                and run.state.output_revision_ids == (revision.manifest.revision_id,)
                and results[0].get("digest") == revision.manifest.content_sha256
            )
        except (KeyError, TypeError, ValueError, PipelineNotFound):
            return False

    def reconcile_job_states(self, jobs: list[Job]) -> None:
        for job in jobs:
            if job.type != "table_observation_assembly":
                continue
            run = self.run_store.get(job.id)
            if run is None or run.state.status not in {"queued", "running"}:
                continue
            failures = {
                "interrupted": RunFailure(
                    "backend_restarted",
                    "Observation assembly was interrupted by a backend restart.",
                ),
                "cancelled": RunFailure("cancelled", "Observation assembly was cancelled."),
                "failed": RunFailure("job_failed", "Observation assembly failed."),
            }
            failure = failures.get(job.state)
            if failure is not None:
                if run.state.status == "queued":
                    self.run_store.start(job.id)
                self.run_store.fail(job.id, failure)

    def execute_job(self, job: Job, token: Any, manager: JobManager) -> None:
        run_id = job.id
        run = self.run_store.start(run_id)
        try:
            token.check()
            event_data, visible_data, identity_data = self._canonical_input_content(run.request)
            total = len(event_data.events)
            self.run_store.update_progress(run_id, progress=RunProgress(completed=0, total=total))
            manager.report_progress(
                job.id,
                phase="Assembling table observations",
                completed=0,
                total=total,
                unit="events",
            )
            configuration = run.request.configuration
            content = assemble_table_observations(
                event_data,
                visible_data,
                identity_data,
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
            token.check()
            items = tuple(
                RunItemOutcome(
                    item_id=observation.observation_id,
                    status="succeeded",
                    result=observation.model_dump(mode="json", exclude_none=True),
                    failure=None,
                )
                for observation in content.observations
            )
            progress = RunProgress(completed=total, total=total)
            revision_id = f"table-observations-{_safe(run.run_id)}-attempt-{run.state.attempt}"
            digest = sha256_bytes(canonical_table_observation_data_bytes(content))
            output = {
                "kind": "pipeline_revision",
                "id": revision_id,
                "digest": digest,
                "available": True,
            }

            def commit() -> None:
                revision = self._publish_revision(run, content)
                if (
                    revision.manifest.revision_id != revision_id
                    or revision.manifest.content_sha256 != digest
                ):
                    raise ObservationPipelineError("the published observation revision changed")
                self.run_store.complete(run_id, [revision_id], progress=progress, items=items)
                self._advance_generated_selection(run.request.source.recording_id, revision_id)

            if not manager.publish(job.id, [output], commit):
                raise JobCancelled("job cancellation requested before observation publication")
        except JobCancelled:
            self._fail_safely(run_id, "cancelled", "Observation assembly was cancelled.")
            raise
        except Exception:
            LOGGER.exception("observation_pipeline_worker_failed")
            self._fail_safely(run_id, "assembly_failed", "The observation assembler failed.")
            raise

    def select_generated(self, recording_id: str, payload: Mapping[str, Any]) -> ExactNodeSelection:
        expected_revision = payload.get("expected_revision")
        selected = payload.get("selected_generated")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ObservationPipelineInputError("expected_revision must be a non-negative integer.")
        if selected is not None and not isinstance(selected, Mapping):
            raise ObservationPipelineInputError(
                "selected_generated must be a node revision pointer or null."
            )
        current = self.selection_store.get_exact(recording_id, "table_observations")
        completed = None if current is None else current.selected_completed_reference
        try:
            return self.selection_store.update_exact(
                recording_id,
                "table_observations",
                expected_revision=expected_revision,
                selected_generated=selected,
                selected_completed_reference=completed,
            )
        except PipelineSelectionConflict:
            raise
        except (PipelineNotFound, PipelineStateError, ValueError, FileNotFoundError) as error:
            raise ObservationPipelineInputError(str(error)) from error

    def _build_request(self, recording_id: str, payload: Mapping[str, Any]) -> ProcessorRunRequest:
        if not isinstance(payload, Mapping):
            raise ObservationPipelineInputError("The processor request must be an object.")
        raw = payload.get("request", payload)
        if not isinstance(raw, Mapping):
            raise ObservationPipelineInputError("request must be an object.")
        input_refs = self._input_node_refs(recording_id, raw)
        input_ids = tuple(ref["revision_id"] for ref in input_refs)
        event_revision, visible_revision, identity_revision = tuple(
            self.selection_store.read_node_revision(ref["node_id"], ref["revision_id"])
            for ref in input_refs
        )
        if event_revision.manifest.content_type != "events" or not isinstance(
            event_revision.content, EventData
        ):
            raise ObservationPipelineInputError("the first input is not event node content")
        if not isinstance(event_revision.manifest.source, RecordingVideoSource):
            raise ObservationPipelineInputError(
                "observation assembly needs a recording video source"
            )
        source = event_revision.manifest.source
        if event_revision.manifest.source.recording_id != recording_id:
            raise ObservationPipelineInputError("the input revisions belong to another recording")
        if visible_revision.manifest.content_type != "visible_cards" or not isinstance(
            visible_revision.content, VisibleCardData
        ):
            raise ObservationPipelineInputError("the second input is not visible-card node content")
        if identity_revision.manifest.content_type != "visual_identities" or not isinstance(
            identity_revision.content, VisualIdentityData
        ):
            raise ObservationPipelineInputError("the third input is not identity node content")
        if (
            visible_revision.manifest.source != source
            or identity_revision.manifest.source != source
        ):
            raise ObservationPipelineInputError(
                "all input revisions must use the same recording video source"
            )
        source = event_revision.manifest.source
        values = dict(raw)
        recording = self.recording_store.get_metadata(recording_id)
        if recording is None or not recording.session_id:
            raise ObservationPipelineInputError("the recording has no valid canonical session ID")
        configuration = values.get("configuration", {})
        if not isinstance(configuration, Mapping):
            raise ObservationPipelineInputError("configuration must be an object")
        requested_session_id = configuration.get("session_id")
        if requested_session_id is not None and requested_session_id != recording.session_id:
            raise ObservationPipelineInputError(
                "the observation session ID must match the recording session ID"
            )
        values["configuration"] = {
            **configuration,
            "session_id": recording.session_id,
        }
        for field in (
            "event_revision_id",
            "visible_card_revision_id",
            "visual_identity_revision_id",
        ):
            values.pop(field, None)
        values["input_revision_ids"] = list(input_ids)
        values["input_node_refs"] = list(input_refs)
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

    def _input_node_refs(
        self, recording_id: str, raw: Mapping[str, Any]
    ) -> tuple[dict[str, str], ...]:
        expected_types = ("events", "visible_cards", "visual_identities")
        provided = raw.get("input_node_refs")
        if any(
            raw.get(field) is not None
            for field in (
                "input_revision_ids",
                "event_revision_id",
                "visible_card_revision_id",
                "visual_identity_revision_id",
            )
        ):
            raise ObservationPipelineInputError(
                "use exact input_node_refs instead of revision-ID input fields"
            )
        if not isinstance(provided, list) or len(provided) != 3:
            raise ObservationPipelineInputError(
                "assembly needs ordered event, visible-card, and identity node references"
            )
        refs = []
        for ref, content_type in zip(provided, expected_types, strict=True):
            if not isinstance(ref, Mapping) or set(ref) != {
                "node_id",
                "revision_id",
                "revision_policy",
            }:
                raise ObservationPipelineInputError(
                    "an observation input node reference is invalid"
                )
            node_id, revision_id, policy = (
                ref.get("node_id"),
                ref.get("revision_id"),
                ref.get("revision_policy"),
            )
            if not all(isinstance(value, str) and value for value in (node_id, revision_id)):
                raise ObservationPipelineInputError(
                    "an observation input node reference is invalid"
                )
            if policy not in {"current_head", "historical"}:
                raise ObservationPipelineInputError("an observation input policy is invalid")
            try:
                node = self.node_store.get(node_id)
                self.node_store.read_revision(node_id, revision_id)
            except (FileNotFoundError, KeyError, ValueError) as error:
                raise ObservationPipelineInputError(
                    "an observation input node is unavailable"
                ) from error
            if (
                node.content_type != content_type
                or node.source.get("recording_id") != recording_id
                or (policy == "current_head" and node.head_revision_id != revision_id)
            ):
                raise ObservationPipelineInputError("an observation input node does not match")
            refs.append({"node_id": node_id, "revision_id": revision_id, "revision_policy": policy})
        if len({(ref["node_id"], ref["revision_id"]) for ref in refs}) != len(refs):
            raise ObservationPipelineInputError("assembly node references must be unique")
        return tuple(refs)

    def _canonical_input_content(
        self, request: ProcessorRunRequest
    ) -> tuple[EventData, VisibleCardData, VisualIdentityData]:
        if self.node_store is None or request.input_node_refs is None:
            raise ObservationPipelineInputError("canonical node inputs are required")
        revisions = [
            self.node_store.read_revision(ref["node_id"], ref["revision_id"])
            for ref in request.input_node_refs
        ]
        event_content = parse_event_data_bytes(
            canonical_json_bytes(revisions[0].content), duration_us=request.source.duration_us
        )
        visible_content = parse_visible_card_data_bytes(canonical_json_bytes(revisions[1].content))
        identity_content = parse_visual_identity_data_bytes(
            canonical_json_bytes(revisions[2].content)
        )
        return event_content, visible_content, identity_content

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
        stored, _ = self.selection_store.publish_processor_revision(manifest, content)
        return stored

    def _advance_generated_selection(self, recording_id: str, revision_id: str) -> None:
        current = self.selection_store.get_exact(recording_id, "table_observations")
        expected = 0 if current is None else current.revision
        completed = None if current is None else current.selected_completed_reference
        generated = self.selection_store.reference_for_processor_output(
            revision_id, recording_id, "table_observations"
        )
        try:
            self.selection_store.update_exact(
                recording_id,
                "table_observations",
                expected_revision=expected,
                selected_generated=generated,
                selected_completed_reference=completed,
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
