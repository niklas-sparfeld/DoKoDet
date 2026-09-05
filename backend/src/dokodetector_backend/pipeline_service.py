"""Event processor orchestration for accepted recording videos."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from doko_operations import (
    DataRevision,
    EventData,
    EventDataRevision,
    ImplementationIdentity,
    ImportProducer,
    ModelIdentity,
    PipelineSelection,
    ProcessorProducer,
    ProcessorRunRequest,
    RecordingVideoSource,
    RunFailure,
    canonical_event_data_bytes,
    sha256_bytes,
)

from dokodetector_backend.intake_contract import parse_proposal_generator_run
from dokodetector_backend.pipeline_store import (
    PipelineNotFound,
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    PipelineSelectionConflict,
    PipelineSelectionStore,
    PipelineStateError,
    PipelineStoreError,
    ProcessorRunStore,
    StoredProcessorRun,
)
from dokodetector_backend.recording_bundle_store import (
    RecordingBundleStore,
    StoredRecordingBundle,
)
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.round_analysis_contract import parse_round_analysis_create_request_bytes
from dokodetector_backend.video_probe import VideoProbeError, probe_video_path_metadata

LOGGER = logging.getLogger(__name__)
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._:-]+")
_UTC = timezone.utc


class PipelineServiceError(RuntimeError):
    """A pipeline operation could not be completed."""


class PipelineInputError(PipelineServiceError, ValueError):
    """A pipeline request or source artifact is invalid."""


class PipelineProviderError(PipelineServiceError):
    """An event provider failed without exposing provider internals to the API."""


class EventProcessorProvider(Protocol):
    """The one provider boundary used by generated event processing."""

    def infer(
        self,
        video_path: Path,
        *,
        request: ProcessorRunRequest,
    ) -> EventData | Mapping[str, Any] | Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class CardEventFileProvider:
    """Adapt CardEventNet's existing file inference operation."""

    repository_root: Path

    def infer(
        self,
        video_path: Path,
        *,
        request: ProcessorRunRequest,
    ) -> EventData | Mapping[str, Any] | Sequence[Mapping[str, Any]]:
        try:
            from cardevent import infer_from_files
        except ImportError as error:  # pragma: no cover - depends on optional model runtime.
            raise PipelineProviderError("The CardEventNet provider is not installed.") from error

        configuration = request.configuration
        checkpoint = _configured_path(
            configuration,
            "checkpoint_path",
            "checkpoint",
            repository_root=self.repository_root,
        )
        if checkpoint is None:
            raise PipelineProviderError("The CardEventNet run has no checkpoint path.")
        cache_dir = (
            _configured_path(
                configuration,
                "cache_dir",
                repository_root=self.repository_root,
            )
            or self.repository_root / "card_event_net" / "data" / "cache"
        )
        batch_size = configuration.get("batch_size")
        threshold = configuration.get("threshold")
        merge_window = configuration.get("merge_window_s")
        with tempfile.NamedTemporaryFile(suffix=".json") as output:
            kwargs: dict[str, Any] = {
                "out_path": output.name,
                "cache_dir": cache_dir,
            }
            if batch_size is not None:
                kwargs["batch_size"] = int(batch_size)
            if threshold is not None:
                kwargs["threshold"] = float(threshold)
            if merge_window is not None:
                kwargs["merge_window_s"] = float(merge_window)
            try:
                payload = infer_from_files(checkpoint, video_path, **kwargs)
            except Exception as error:  # provider details stay out of the HTTP response.
                LOGGER.exception("cardevent_file_provider_failed")
                raise PipelineProviderError("The CardEventNet provider failed.") from error
        if not isinstance(payload, Mapping):
            raise PipelineProviderError("The CardEventNet provider returned invalid data.")
        return payload


def _configured_path(
    configuration: Mapping[str, Any],
    *keys: str,
    repository_root: Path,
) -> Path | None:
    for key in keys:
        value = configuration.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise PipelineInputError(f"configuration.{key} must be a non-empty path.")
        path = Path(value).expanduser()
        return path if path.is_absolute() else (repository_root / path).resolve()
    return None


class EventPipelineService:
    """Create, execute, import, and select event processor results."""

    def __init__(
        self,
        settings: Any,
        recording_store: RecordingBundleStore,
        repository_storage: RepositoryBundleStorage,
        *,
        event_provider: EventProcessorProvider | None = None,
        revision_store: PipelineRevisionStore | None = None,
        run_store: ProcessorRunStore | None = None,
        selection_store: PipelineSelectionStore | None = None,
    ) -> None:
        self.settings = settings
        self.recording_store = recording_store
        self.repository_storage = repository_storage
        self.storage = PipelineRuntimeStorage(settings.evidence_root)
        self.revision_store = revision_store or PipelineRevisionStore(self.storage)
        self.run_store = run_store or ProcessorRunStore(
            self.storage,
            revision_store=self.revision_store,
        )
        self.selection_store = selection_store or PipelineSelectionStore(
            self.storage,
            revision_store=self.revision_store,
            run_store=self.run_store,
        )
        self.event_provider = event_provider or CardEventFileProvider(settings.repository_root)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="event-pipeline")
        self._futures: dict[str, Future[None]] = {}
        self._lock = RLock()

    async def start(self) -> None:
        """Keep the lifecycle symmetrical with the other backend services."""

    async def stop(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
        with self._lock:
            self._futures.clear()

    def recover_interrupted_runs(self) -> int:
        """Convert work interrupted by a backend restart into terminal failures."""

        failure = RunFailure(
            code="backend_restarted",
            message="The event processor did not finish before the backend restarted.",
        )
        count = self.run_store.fail_non_terminal(failure=failure)
        if count:
            LOGGER.warning("event_pipeline_recovery_failed", extra={"run_count": count})
        return count

    def start_inference(self, recording_id: str, payload: Mapping[str, Any]) -> StoredProcessorRun:
        request = self._build_request(recording_id, payload)
        run, created = self.run_store.create(request)
        if not created:
            return run
        try:
            running = self.run_store.start(run.run_id)
        except Exception:
            raise
        with self._lock:
            self._futures[run.run_id] = self._executor.submit(self._execute, running.run_id)
        return running

    def import_predictions(
        self,
        recording_id: str,
        payload: Mapping[str, Any],
    ) -> StoredProcessorRun:
        request = self._build_request(recording_id, payload)
        run, created = self.run_store.create(request)
        if not created:
            return run
        try:
            self.run_store.start(run.run_id)
            self._execute_import(run.run_id, payload)
        except PipelineServiceError as error:
            self._fail_safely(run.run_id, "import_failed", str(error))
        except Exception:
            LOGGER.exception("event_pipeline_import_failed")
            self._fail_safely(
                run.run_id,
                "import_failed",
                "The recording-bundle event prediction import failed.",
            )
        return self.run_store.require(run.run_id)

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
            run for run in self.run_store.list() if run.request.source.recording_id == recording_id
        )

    def get_result(
        self, recording_id: str, run_id: str
    ) -> tuple[StoredProcessorRun, tuple[EventDataRevision, ...]]:
        run = self.get_run(recording_id, run_id)
        revisions = tuple(
            self.revision_store.require(item) for item in run.state.output_revision_ids
        )
        return run, revisions

    def retry(self, recording_id: str, run_id: str) -> StoredProcessorRun:
        self.get_run(recording_id, run_id)
        retried = self.run_store.retry(run_id)
        with self._lock:
            self._futures[run_id] = self._executor.submit(self._execute, retried.run_id)
        return retried

    def select_generated(
        self,
        recording_id: str,
        payload: Mapping[str, Any],
    ) -> PipelineSelection:
        expected_revision = payload.get("expected_revision")
        selected = payload.get("selected_generated_revision_id")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise PipelineInputError("expected_revision must be a non-negative integer.")
        if selected is not None and not isinstance(selected, str):
            raise PipelineInputError("selected_generated_revision_id must be a string or null.")
        current = self.selection_store.get(recording_id, "events")
        completed = None if current is None else current.selected_completed_reference_revision_id
        try:
            return self.selection_store.update_pointers(
                recording_id,
                "events",
                expected_revision=expected_revision,
                selected_generated_revision_id=selected,
                selected_completed_reference_revision_id=completed,
            )
        except PipelineSelectionConflict:
            raise
        except (PipelineNotFound, PipelineStateError) as error:
            raise PipelineInputError(str(error)) from error

    def _build_request(
        self,
        recording_id: str,
        payload: Mapping[str, Any],
    ) -> ProcessorRunRequest:
        if not isinstance(payload, Mapping):
            raise PipelineInputError("The processor request must be an object.")
        raw = payload.get("request", payload)
        if not isinstance(raw, Mapping):
            raise PipelineInputError("request must be an object.")
        _, source = self._accepted_source(recording_id)
        values = dict(raw)
        values.setdefault("schema_version", "processor-run-request/v1")
        values.setdefault("run_id", payload.get("run_id"))
        if not values.get("run_id"):
            raise PipelineInputError("run_id is required.")
        values.setdefault("processor_type", "event-detection")
        values.setdefault("source", source.to_mapping())
        values.setdefault("input_revision_ids", [])
        values.setdefault("implementation", {"name": "cardeventnet", "version": "file-v1"})
        values.setdefault("model", None)
        values.setdefault("configuration", {})
        values.setdefault("extraction_policy", {"policy_id": "exact-event/v1"})
        values.setdefault("crop_policy", None)
        try:
            request = ProcessorRunRequest.from_mapping(values)
        except (TypeError, ValueError) as error:
            raise PipelineInputError("The processor request failed validation.") from error
        if request.source != source:
            raise PipelineInputError(
                "The request source does not match the accepted recording video."
            )
        if request.processor_type != "event-detection":
            raise PipelineInputError("The event endpoint only accepts event-detection runs.")
        return request

    def _accepted_source(
        self, recording_id: str
    ) -> tuple[StoredRecordingBundle, RecordingVideoSource]:
        bundle = self.recording_store.get(recording_id)
        if bundle is None:
            raise PipelineNotFound(f"The recording was not found: {recording_id}")
        video_path = self.repository_storage.bundle_path(recording_id) / self._video_relative_path(
            recording_id
        )
        if not video_path.is_file():
            raise PipelineInputError("The accepted recording video is unavailable.")
        actual_length, actual_digest = _file_identity(video_path)
        if actual_length != bundle.video_byte_length or actual_digest != bundle.source_sha256:
            raise PipelineInputError("The accepted recording video does not match its manifest.")
        try:
            probe = probe_video_path_metadata(video_path)
        except VideoProbeError as error:
            raise PipelineInputError("The accepted recording video could not be probed.") from error
        try:
            relative_path = (
                video_path.resolve().relative_to(self.settings.repository_root).as_posix()
            )
        except ValueError as error:
            raise PipelineInputError(
                "The accepted recording video is outside the repository root."
            ) from error
        return bundle, RecordingVideoSource(
            recording_id=recording_id,
            relative_path=relative_path,
            video_sha256=bundle.source_sha256,
            byte_length=actual_length,
            duration_us=probe.duration_ms * 1000,
        )

    def _video_relative_path(self, recording_id: str) -> str:
        manifest = self.repository_storage.bundle_path(recording_id) / "manifest.json"
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
            return str(value["files"]["video"]["relative_path"])
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise PipelineInputError("The accepted recording manifest is invalid.") from error

    def _execute(self, run_id: str) -> None:
        try:
            run = self.run_store.require(run_id)
            result = self.event_provider.infer(
                self._video_path(run.request.source.recording_id),
                request=run.request,
            )
            content = _event_data_from_provider(result, run.request)
            revision = self._publish_processor_revision(run, content)
            self.run_store.complete(run_id, [revision.manifest.revision_id])
            self._advance_generated_selection(
                run.request.source.recording_id, revision.manifest.revision_id
            )
        except PipelineServiceError as error:
            self._fail_safely(run_id, "provider_failed", str(error))
        except Exception:
            LOGGER.exception("event_pipeline_worker_failed")
            self._fail_safely(run_id, "provider_failed", "The event processor failed.")

    def _execute_import(self, run_id: str, payload: Mapping[str, Any]) -> None:
        run = self.run_store.require(run_id)
        artifact, artifact_id, artifact_digest, model_id = self._load_import_artifact(
            run.request.source.recording_id,
            payload,
        )
        content = _event_data_from_provider(
            {"events": artifact, "event_type": "card_played", "producer_id": model_id},
            run.request,
        )
        revision_id = _revision_id(run, suffix="import")
        producer = ImportProducer(
            run_id=run_id,
            artifact_id=artifact_id,
            artifact_sha256=artifact_digest,
            source_schema="proposal-generator-run/v1",
            model_id=model_id,
        )
        revision = _build_revision(run.request, content, revision_id, producer)
        stored, _ = self.revision_store.publish(revision)
        self.run_store.complete(run_id, [stored.manifest.revision_id])
        self._advance_generated_selection(
            run.request.source.recording_id, stored.manifest.revision_id
        )

    def _load_import_artifact(
        self,
        recording_id: str,
        payload: Mapping[str, Any],
    ) -> tuple[list[Mapping[str, Any]], str, str, str]:
        bundle_path = self.repository_storage.bundle_path(recording_id)
        try:
            manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
            descriptors = manifest["files"]["proposal_generator_runs"]
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise PipelineInputError(
                "The recording-bundle prediction manifest is invalid."
            ) from error
        requested_path = payload.get("artifact_path") or payload.get("prediction_path")
        requested_run = payload.get("proposal_generator_run_id")
        descriptor = next(
            (
                item
                for item in descriptors
                if (requested_path is None or item.get("relative_path") == requested_path)
                and (
                    requested_run is None or item.get("proposal_generator_run_id") == requested_run
                )
            ),
            None,
        )
        if (
            descriptor is None
            and requested_path is None
            and requested_run is None
            and len(descriptors) == 1
        ):
            descriptor = descriptors[0]
        if not isinstance(descriptor, Mapping):
            raise PipelineInputError(
                "The requested recording-bundle event prediction was not found."
            )
        relative_path = descriptor.get("relative_path")
        if not isinstance(relative_path, str):
            raise PipelineInputError("The recording-bundle prediction path is invalid.")
        prediction_path = bundle_path / relative_path
        try:
            raw = prediction_path.read_bytes()
        except OSError as error:
            raise PipelineInputError(
                "The recording-bundle event prediction is unavailable."
            ) from error
        if len(raw) != descriptor.get("byte_length") or sha256_bytes(raw) != descriptor.get(
            "sha256"
        ):
            raise PipelineInputError(
                "The recording-bundle event prediction failed integrity validation."
            )
        try:
            parsed = parse_proposal_generator_run(raw)
        except (TypeError, ValueError) as error:
            raise PipelineInputError(
                "The recording-bundle event prediction failed validation."
            ) from error
        return (
            [
                {
                    "event_id": f"import-{parsed.proposal_generator_run_id}-{index}",
                    "time_s": event.time_s,
                    "probability": event.probability,
                }
                for index, event in enumerate(parsed.event_proposals)
            ],
            parsed.proposal_generator_run_id,
            str(descriptor["sha256"]),
            parsed.model_bundle_id,
        )

    def _publish_processor_revision(
        self,
        run: StoredProcessorRun,
        content: EventData,
    ) -> EventDataRevision:
        producer = ProcessorProducer(
            run_id=run.run_id,
            processor_type=run.request.processor_type,
            implementation_id=_implementation_id(run.request.implementation),
            model_id=_model_id(run.request.model),
        )
        revision = _build_revision(run.request, content, _revision_id(run), producer)
        stored, _ = self.revision_store.publish(revision)
        return stored

    def _advance_generated_selection(self, recording_id: str, revision_id: str) -> None:
        current = self.selection_store.get(recording_id, "events")
        expected = 0 if current is None else current.revision
        completed = None if current is None else current.selected_completed_reference_revision_id
        try:
            self.selection_store.update_pointers(
                recording_id,
                "events",
                expected_revision=expected,
                selected_generated_revision_id=revision_id,
                selected_completed_reference_revision_id=completed,
            )
        except PipelineSelectionConflict:
            LOGGER.warning(
                "event_pipeline_selection_advance_conflict",
                extra={"recording_id": recording_id},
            )

    def _fail_safely(self, run_id: str, code: str, message: str) -> None:
        try:
            run = self.run_store.get(run_id)
            if run is not None and run.state.status == "running":
                self.run_store.fail(run_id, RunFailure(code=code, message=message))
        except Exception:
            LOGGER.exception("event_pipeline_failure_persist_failed")

    def _video_path(self, recording_id: str) -> Path:
        return self.repository_storage.bundle_path(recording_id) / self._video_relative_path(
            recording_id
        )

    def _require_recording(self, request: ProcessorRunRequest, recording_id: str) -> None:
        if request.source.recording_id != recording_id:
            raise PipelineNotFound(f"The processor run was not found for recording: {recording_id}")


@dataclass(frozen=True, slots=True)
class _WorkspaceStageDefinition:
    key: str
    processor_key: str
    processor_type: str
    content_type: str
    reviewable: bool


_WORKSPACE_STAGES = (
    _WorkspaceStageDefinition(
        key="events",
        processor_key="event_detection",
        processor_type="event-detection",
        content_type="events",
        reviewable=True,
    ),
    _WorkspaceStageDefinition(
        key="visible_cards",
        processor_key="visible_card_detection",
        processor_type="visible-card-detection",
        content_type="visible_cards",
        reviewable=True,
    ),
    _WorkspaceStageDefinition(
        key="visual_identities",
        processor_key="visual_identity_classification",
        processor_type="visual-card-identity",
        content_type="visual_identities",
        reviewable=True,
    ),
    _WorkspaceStageDefinition(
        key="table_observations",
        processor_key="observation_assembly",
        processor_type="observation-assembly",
        content_type="table_observations",
        reviewable=False,
    ),
    _WorkspaceStageDefinition(
        key="round_analyses",
        processor_key="round_analysis",
        processor_type="round-analysis",
        content_type="round_analyses",
        reviewable=False,
    ),
)


class RecordingPipelineWorkspaceService:
    """Aggregate persisted recording-pipeline state for the recording workspace."""

    def __init__(
        self,
        *,
        event_pipeline_service: EventPipelineService,
        revision_store: PipelineRevisionStore,
        run_store: ProcessorRunStore,
        selection_store: PipelineSelectionStore,
        reference_store: Any,
        round_analysis_store: Any,
    ) -> None:
        self.event_pipeline_service = event_pipeline_service
        self.revision_store = revision_store
        self.run_store = run_store
        self.selection_store = selection_store
        self.reference_store = reference_store
        self.round_analysis_store = round_analysis_store

    def get_workspace(self, recording_id: str) -> dict[str, Any]:
        """Read one complete workspace snapshot without changing pipeline state."""

        _, source = self.event_pipeline_service._accepted_source(recording_id)  # noqa: SLF001
        revisions = tuple(
            revision
            for revision in self.revision_store.list()
            if revision.manifest.recording_id == recording_id
        )
        runs = tuple(
            run
            for run in self.run_store.list()
            if run.request.source.recording_id == recording_id
        )
        diagnostics: list[dict[str, Any]] = []
        selections = {
            content_type: self._selection(recording_id, content_type, diagnostics)
            for content_type in (
                "events",
                "visible_cards",
                "visual_identities",
                "table_observations",
            )
        }
        references = {
            content_type: self._reference(recording_id, content_type, diagnostics)
            for content_type in ("events", "visible_cards", "visual_identities")
        }
        stages = [
            self._stage(
                recording_id,
                source,
                definition,
                revisions=revisions,
                runs=runs,
                selection=selections.get(definition.content_type),
                reference=references.get(definition.content_type),
                diagnostics=diagnostics,
            )
            for definition in _WORKSPACE_STAGES
        ]
        return {
            "schema_version": "pipeline-workspace/v1",
            "recording_id": recording_id,
            "video": source.to_mapping(),
            "stages": stages,
            "diagnostics": diagnostics,
        }

    def _stage(
        self,
        recording_id: str,
        source: RecordingVideoSource,
        definition: _WorkspaceStageDefinition,
        *,
        revisions: tuple[Any, ...],
        runs: tuple[StoredProcessorRun, ...],
        selection: Any,
        reference: Any,
        diagnostics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        stage_revisions = tuple(
            revision
            for revision in revisions
            if revision.manifest.content_type == definition.content_type
        )
        stage_runs = tuple(
            run for run in runs if run.request.processor_type == definition.processor_type
        )
        options = [self._revision_option(revision, definition.key) for revision in stage_revisions]
        options.sort(key=lambda option: (option["created_at"], option["revision_id"]), reverse=True)
        reference_summary = (
            self._reference_summary(reference, definition.content_type, diagnostics)
            if definition.reviewable
            else None
        )
        analyses = (
            self._analysis_summaries(recording_id, diagnostics)
            if definition.key == "round_analyses"
            else []
        )
        selection_revision = None if selection is None else selection.revision
        selected_generated = (
            None if selection is None else selection.selected_generated_revision_id
        )
        selected_completed = (
            None
            if selection is None
            else selection.selected_completed_reference_revision_id
        )
        comparable_run_ids = [
            run.run_id
            for run in stage_runs
            if run.state.status in {"complete", "partial"}
            and any(
                self.revision_store.get(revision_id) is not None
                and self.revision_store.require(revision_id).manifest.content_type
                == definition.content_type
                for revision_id in run.state.output_revision_ids
            )
        ]
        comparable_run_ids.sort()
        run_blockers = self._run_blockers(
            definition,
            source,
            stage_revisions,
            selections={
                "events": self._selection_value(recording_id, "events"),
                "visible_cards": self._selection_value(recording_id, "visible_cards"),
                "visual_identities": self._selection_value(
                    recording_id, "visual_identities"
                ),
            },
        )
        review_blockers = self._review_blockers(definition, options, reference_summary)
        return {
            "key": definition.key,
            "processor_key": definition.processor_key,
            "processor_type": definition.processor_type,
            "output_content_type": definition.content_type,
            "has_maintained_reference": definition.reviewable,
            "state": self._stage_state(
                definition,
                source,
                options,
                stage_runs,
                reference_summary,
                analyses,
            ),
            "input_options": options,
            "selection_revision": selection_revision,
            "selected_generated_revision_id": selected_generated,
            "selected_completed_reference_revision_id": selected_completed,
            "runs": [self._run_summary(run) for run in self._ordered_runs(stage_runs)],
            "analyses": analyses,
            "reference": reference_summary,
            "can_run": not run_blockers,
            "run_blockers": run_blockers,
            "can_review": not review_blockers,
            "review_blockers": review_blockers,
            "comparable_run_ids": comparable_run_ids,
        }

    def _selection(
        self,
        recording_id: str,
        content_type: str,
        diagnostics: list[dict[str, Any]],
    ) -> Any:
        try:
            selection = self.selection_store.get(recording_id, content_type)
        except PipelineStoreError:
            selection = None
        path = self.selection_store.selection_path(recording_id, content_type)
        if selection is None and (path.exists() or path.is_symlink()):
            diagnostics.append(
                {
                    "code": "invalid_selection",
                    "message": f"The {content_type} selection document is invalid.",
                    "content_type": content_type,
                    "revision_id": None,
                }
            )
        return selection

    def _selection_value(self, recording_id: str, content_type: str) -> Any:
        try:
            return self.selection_store.get(recording_id, content_type)
        except PipelineStoreError:
            return None

    def _reference(
        self,
        recording_id: str,
        content_type: str,
        diagnostics: list[dict[str, Any]],
    ) -> Any:
        root = self.reference_store.reference_root(recording_id, content_type)
        if not (root / "state.json").exists() and not (root / "draft.json").exists():
            return None
        reference = self.reference_store.get(recording_id, content_type)
        if reference is None:
            diagnostics.append(
                {
                    "code": "invalid_reference",
                    "message": f"The {content_type} maintained reference is invalid.",
                    "content_type": content_type,
                    "revision_id": None,
                }
            )
        return reference

    def _reference_summary(
        self, reference: Any, content_type: str, diagnostics: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if reference is None:
            return {
                "state": "empty",
                "draft_revision": None,
                "selected_completion": None,
                "source_revision_id": None,
                "coverage": None,
                "coverage_state": "none",
                "affected_count": 0,
                "updated_at": None,
            }
        selected_completion = reference.state.selected_completed_revision_id
        selected_revision = (
            None if selected_completion is None else self.revision_store.get(selected_completion)
        )
        if selected_revision is not None and (
            selected_revision.manifest.recording_id != reference.state.recording_id
            or selected_revision.manifest.content_type != content_type
        ):
            selected_revision = None
        if selected_completion is not None and selected_revision is None:
            diagnostics.append(
                {
                    "code": "missing_reference_revision",
                    "message": "The maintained reference completion is unavailable.",
                    "content_type": content_type,
                    "revision_id": selected_completion,
                }
            )
        affected_count = sum(
            item.review_state == "affected" for item in reference.draft.items
        )
        coverage = reference.draft.coverage
        state = "complete" if reference.state.draft_state == "completed" else "draft"
        return {
            "state": state,
            "draft_revision": reference.state.draft_revision,
            "selected_completion": selected_completion,
            "source_revision_id": reference.state.source_revision_id,
            "coverage": coverage,
            "coverage_state": "complete"
            if state == "complete"
            else "incomplete"
            if coverage is not None
            else "none",
            "affected_count": affected_count,
            "updated_at": reference.state.updated_at,
        }

    @staticmethod
    def _revision_option(revision: Any, stage_key: str) -> dict[str, Any]:
        manifest = revision.manifest
        generated = manifest.origin == "processor"
        label = "Generated" if generated else "Reviewed"
        return {
            "revision_id": manifest.revision_id,
            "content_type": manifest.content_type,
            "origin": manifest.origin,
            "completion_state": "complete",
            "coverage_state": str(manifest.coverage.get("kind", "unknown")),
            "display_label": f"{label} {stage_key.replace('_', ' ')}",
            "content_sha256": manifest.content_sha256,
            "input_revision_ids": list(manifest.input_revision_ids),
            "producer": manifest.producer.to_mapping(),
            "coverage": manifest.coverage,
            "created_at": manifest.created_at,
        }

    @staticmethod
    def _ordered_runs(runs: tuple[StoredProcessorRun, ...]) -> tuple[StoredProcessorRun, ...]:
        return tuple(
            sorted(
                runs,
                key=lambda run: (run.state.created_at, run.run_id),
                reverse=True,
            )
        )

    @staticmethod
    def _run_summary(run: StoredProcessorRun) -> dict[str, Any]:
        state = run.state
        return {
            "run_id": run.run_id,
            "status": state.status,
            "attempt": state.attempt,
            "request": run.request.to_mapping(),
            "state": state.to_mapping(),
            "input_revision_ids": list(run.request.input_revision_ids),
            "implementation": run.request.implementation.to_mapping(),
            "model": None if run.request.model is None else run.request.model.to_mapping(),
            "configuration": run.request.configuration,
            "extraction_policy": run.request.extraction_policy,
            "crop_policy": run.request.crop_policy,
            "output_revision_ids": list(state.output_revision_ids),
            "created_at": state.created_at,
            "started_at": state.started_at,
            "completed_at": state.completed_at,
            "updated_at": state.updated_at,
            "progress": state.progress.to_mapping(),
            "failure": None
            if state.terminal_failure is None
            else state.terminal_failure.to_mapping(),
            "failed_item_count": sum(item.status == "failed" for item in state.items),
        }

    @staticmethod
    def _stage_state(
        definition: _WorkspaceStageDefinition,
        source: RecordingVideoSource,
        options: list[dict[str, Any]],
        runs: tuple[StoredProcessorRun, ...],
        reference: dict[str, Any] | None,
        analyses: list[dict[str, Any]],
    ) -> str:
        if any(run.state.status in {"queued", "running"} for run in runs):
            return "active-run"
        if any(
            analysis["state"] in {"queued", "analyzing_evidence", "reconstructing"}
            for analysis in analyses
        ):
            return "active-run"
        if any(analysis["state"] == "complete" for analysis in analyses):
            return "complete"
        if any(analysis["state"] == "failed" for analysis in analyses):
            return "failed"
        if reference is not None and reference["state"] == "complete":
            return "complete"
        if reference is not None and reference["affected_count"]:
            return "affected"
        if reference is not None and reference["coverage_state"] == "incomplete":
            return "incomplete-coverage"
        if reference is not None and reference["state"] == "draft":
            return "draft"
        if options:
            return "generated-only"
        if any(run.state.status == "partial" for run in runs):
            return "partial"
        if any(run.state.status == "failed" for run in runs):
            return "failed"
        if definition.key == "events":
            return "video-only"
        return "empty"

    @staticmethod
    def _run_blockers(
        definition: _WorkspaceStageDefinition,
        source: RecordingVideoSource,
        stage_revisions: tuple[Any, ...],
        *,
        selections: dict[str, Any],
    ) -> list[str]:
        if definition.key == "events":
            return []
        if definition.key in {"visible_cards", "visual_identities"}:
            upstream = "events" if definition.key == "visible_cards" else "visible_cards"
            selection = selections[upstream]
            if selection is None or not (
                selection.selected_completed_reference_revision_id
                or selection.selected_generated_revision_id
            ):
                return [f"Select a complete {upstream.replace('_', ' ')} revision first."]
            return []
        if definition.key == "table_observations":
            missing = [
                content_type.replace("_", " ")
                for content_type in ("events", "visible_cards", "visual_identities")
                if selections[content_type] is None
                or not (
                    selections[content_type].selected_completed_reference_revision_id
                    or selections[content_type].selected_generated_revision_id
                )
            ]
            return [
                "Select complete event, visible-card, and visual-identity revisions first."
            ] if missing else []
        if definition.key == "round_analyses":
            if not stage_revisions:
                return ["Create a complete table-observation revision first."]
            return ["Round context is required before starting analysis."]
        del source
        return ["The pipeline stage is not available."]

    @staticmethod
    def _review_blockers(
        definition: _WorkspaceStageDefinition,
        options: list[dict[str, Any]],
        reference: dict[str, Any] | None,
    ) -> list[str]:
        if not definition.reviewable:
            return ["This stage does not have a maintained human reference."]
        if reference is not None and reference["state"] == "draft":
            return []
        if not options:
            return ["Create a complete generated result first."]
        if reference is not None and reference["state"] == "complete":
            return ["Start a new review from the selected generated result to review again."]
        return []

    def _analysis_summaries(
        self, recording_id: str, diagnostics: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        analyses = self.round_analysis_store.list_by_recording(recording_id)
        for analysis in analyses:
            try:
                request = parse_round_analysis_create_request_bytes(
                    analysis.request_json.encode("utf-8")
                )
            except (TypeError, ValueError):
                diagnostics.append(
                    {
                        "code": "invalid_round_analysis_request",
                        "message": "A stored round-analysis request is invalid.",
                        "content_type": "round_analyses",
                        "revision_id": str(analysis.analysis_id),
                    }
                )
                LOGGER.warning("pipeline_workspace_analysis_invalid", exc_info=True)
                continue
            input_revision_ids = (
                []
                if request.table_observation_revision_id is None
                else [request.table_observation_revision_id]
            )
            summaries.append(
                {
                    "analysis_id": str(analysis.analysis_id),
                    "recording_id": analysis.recording_id,
                    "round_id": analysis.round_id,
                    "session_id": str(analysis.session_id),
                    "state": analysis.state,
                    "input_revision_ids": input_revision_ids,
                    "request": request.to_mapping(),
                    "progress": {
                        "completed": analysis.completed_evidence_packages,
                        "total": analysis.total_evidence_packages,
                    },
                    "failure": analysis.error,
                    "created_at": _datetime_string(analysis.created_at),
                    "started_at": _datetime_string(analysis.started_at),
                    "completed_at": _datetime_string(analysis.completed_at),
                }
            )
        return summaries


def _file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            length += len(chunk)
            digest.update(chunk)
    return length, digest.hexdigest()


def _implementation_id(identity: ImplementationIdentity) -> str:
    return _safe(identity.name) + "." + _safe(identity.version)


def _model_id(model: ModelIdentity | None) -> str | None:
    return None if model is None else _safe(model.name) + "." + _safe(model.version)


def _safe(value: str) -> str:
    return _SAFE_COMPONENT.sub("-", value).strip("-") or "unknown"


def _revision_id(run: StoredProcessorRun, *, suffix: str | None = None) -> str:
    tail = suffix or f"attempt-{run.state.attempt}"
    return f"events-{_safe(run.run_id)}-{tail}"


def _build_revision(
    request: ProcessorRunRequest,
    content: EventData,
    revision_id: str,
    producer: ProcessorProducer | ImportProducer,
) -> EventDataRevision:
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="events",
        content_schema="event-data/v1",
        recording_id=request.source.recording_id,
        source=request.source,
        content_sha256=sha256_bytes(canonical_event_data_bytes(content)),
        input_revision_ids=request.input_revision_ids,
        origin="processor",
        producer=producer,
        coverage={"kind": "full-recording", "policy_id": request.extraction_policy["policy_id"]},
        created_at=_now(),
    )
    return EventDataRevision(manifest=manifest, content=content)


def _event_data_from_provider(
    value: EventData | Mapping[str, Any] | Sequence[Mapping[str, Any]],
    request: ProcessorRunRequest,
) -> EventData:
    if isinstance(value, EventData):
        return EventData.from_mapping(value.to_mapping(), duration_us=request.source.duration_us)
    if isinstance(value, Mapping):
        raw_events = value.get("events")
        event_type = value.get("event_type", request.configuration.get("event_type", "card_played"))
        producer_id = value.get(
            "producer_id",
            _model_id(request.model) or _implementation_id(request.implementation),
        )
    else:
        raw_events = value
        event_type = request.configuration.get("event_type", "card_played")
        producer_id = _model_id(request.model) or _implementation_id(request.implementation)
    if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes, bytearray)):
        raise PipelineProviderError("The event provider returned no valid event list.")
    events: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_events):
        if not isinstance(raw, Mapping):
            raise PipelineProviderError("The event provider returned an invalid event.")
        if "start_us" in raw:
            item = dict(raw)
        else:
            time_s = raw.get("time_s")
            probability = raw.get("probability")
            if isinstance(time_s, bool) or not isinstance(time_s, (int, float)):
                raise PipelineProviderError("The event provider returned an invalid event time.")
            if isinstance(probability, bool) or not isinstance(probability, (int, float)):
                raise PipelineProviderError("The event provider returned an invalid event score.")
            start_us = round(float(time_s) * 1_000_000)
            item = {
                "event_id": raw.get("event_id", f"event-{index:06d}"),
                "event_type": raw.get("event_type", event_type),
                "start_us": start_us,
                "end_us": round(float(raw.get("end_time_s", time_s)) * 1_000_000),
                "model_scores": [{"producer_id": str(producer_id), "score": float(probability)}],
            }
        item.setdefault("event_id", f"event-{index:06d}")
        item.setdefault("event_type", event_type)
        events.append(item)
    try:
        return EventData.from_mapping(
            {"schema_version": "event-data/v1", "events": events},
            duration_us=request.source.duration_us,
        )
    except (TypeError, ValueError) as error:
        raise PipelineProviderError("The event provider returned invalid event content.") from error


def _now() -> str:
    return datetime.now(_UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _datetime_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(_UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = [
    "CardEventFileProvider",
    "EventPipelineService",
    "EventProcessorProvider",
    "PipelineInputError",
    "PipelineProviderError",
    "PipelineServiceError",
    "RecordingPipelineWorkspaceService",
]
