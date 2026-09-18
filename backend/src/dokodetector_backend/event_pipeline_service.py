"""Event processor orchestration for accepted recording videos."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from doko_operations.pipeline_data import (
    CARD_STATE_CHANGED_EVENT_TYPE,
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
    RunItemOutcome,
    RunProgress,
    canonical_event_data_bytes,
    sha256_bytes,
)

from dokodetector_backend.intake_contract import parse_proposal_generator_run
from dokodetector_backend.pipeline_service_errors import (
    PipelineInputError,
    PipelineProviderError,
    PipelineServiceError,
)
from dokodetector_backend.pipeline_store import (
    PipelineNotFound,
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    PipelineSelectionConflict,
    PipelineSelectionStore,
    PipelineStateError,
    ProcessorRunStore,
    StoredProcessorRun,
)
from dokodetector_backend.recording_bundle_store import (
    RecordingBundleStore,
    StoredRecordingBundle,
)
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.video_probe import VideoProbeError, probe_video_path_metadata

LOGGER = logging.getLogger(__name__)
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._:-]+")
_UTC = timezone.utc
_CARD_EVENT_INTEGRATION_CONTRACT = Path(
    "data/model-campaigns/cardeventnet-0063-m14-development-integration/integration-contract.json"
)
_CARD_EVENT_INTEGRATION_SCHEMA = "cardeventnet-m15-integration-contract/v1"
_DEFAULT_CARD_EVENT_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class _CheckpointDefaults:
    path: Path
    threshold: float = _DEFAULT_CARD_EVENT_THRESHOLD
    merge_window_s: float | None = None


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

    def resolve_checkpoint_path(self, configuration: Mapping[str, Any]) -> Path | None:
        """Resolve the checkpoint explicitly supplied in a processor request."""

        return _configured_path(
            configuration,
            "checkpoint_path",
            "checkpoint",
            repository_root=self.repository_root,
        )

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
        checkpoint = self.resolve_checkpoint_path(configuration)
        if checkpoint is None:
            raise PipelineProviderError(
                "The CardEventNet checkpoint is not configured. Set CARD_EVENT_CHECKPOINT_PATH "
                "or add a trained best.pt under card_event_net/data/outputs."
            )
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


def _discover_checkpoint(repository_root: Path) -> Path | None:
    """Find the default CardEventNet checkpoint for local pipeline runs."""

    defaults = _discover_checkpoint_defaults(repository_root)
    return None if defaults is None else defaults.path


def _discover_checkpoint_defaults(repository_root: Path) -> _CheckpointDefaults | None:
    """Find the default CardEventNet checkpoint and its local decoding defaults."""

    output_root = repository_root / "card_event_net" / "data" / "outputs"
    try:
        candidates = [path for path in output_root.rglob("best.pt") if path.is_file()]
    except OSError:
        return None
    if candidates:

        def sort_key(path: Path) -> tuple[int, str]:
            try:
                modified_ns = path.stat().st_mtime_ns
            except OSError:
                modified_ns = -1
            return modified_ns, path.as_posix()

        return _CheckpointDefaults(path=max(candidates, key=sort_key))

    return _discover_integration_checkpoint_defaults(repository_root)


def _discover_integration_checkpoint_defaults(repository_root: Path) -> _CheckpointDefaults | None:
    """Resolve the immutable 0063 checkpoint and decoder defaults, when present."""

    contract_path = repository_root / _CARD_EVENT_INTEGRATION_CONTRACT
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(contract, Mapping):
        return None
    if (
        contract.get("schema_version") != _CARD_EVENT_INTEGRATION_SCHEMA
        or contract.get("role") != "development_integration_model"
        or contract.get("production_promotion_eligible") is not False
    ):
        return None

    checkpoint = contract.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        return None
    relative_path = checkpoint.get("path")
    expected_digest = checkpoint.get("sha256")
    if (
        not isinstance(relative_path, str)
        or not relative_path.strip()
        or Path(relative_path).is_absolute()
        or not isinstance(expected_digest, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_digest)
    ):
        return None

    path = (repository_root / relative_path).resolve()
    try:
        path.relative_to(repository_root.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    if _sha256_file(path) != expected_digest.lower():
        return None

    threshold = contract.get("threshold")
    decoder = contract.get("decoder")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not isfinite(float(threshold))
        or not 0.0 <= float(threshold) <= 1.0
        or not isinstance(decoder, Mapping)
    ):
        return None
    merge_window = decoder.get("min_event_gap_s")
    if (
        isinstance(merge_window, bool)
        or not isinstance(merge_window, (int, float))
        or not isfinite(float(merge_window))
        or float(merge_window) < 0.0
    ):
        return None
    return _CheckpointDefaults(
        path=path,
        threshold=float(threshold),
        merge_window_s=float(merge_window),
    )


def _sha256_file(path: Path) -> str:
    """Return a file SHA-256 digest without loading the file into memory."""

    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()


def _request_path(path: Path, repository_root: Path) -> str:
    """Use a repository-relative path when the checkpoint is inside the checkout."""

    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return str(path)


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
        self.storage = PipelineRuntimeStorage(settings.evidence_root, settings.operations_root)
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
        self.event_provider = event_provider or CardEventFileProvider(
            settings.repository_root,
        )
        self.card_event_checkpoint_path = getattr(settings, "card_event_checkpoint_path", None)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="event-pipeline")
        self._futures: dict[str, Future[None]] = {}
        self._workspace_sources: dict[
            str, tuple[tuple[int, int, str], RecordingVideoSource]
        ] = {}
        self._lock = RLock()

    def get_recording_source(self, recording_id: str) -> RecordingVideoSource:
        """Return the accepted source identity for a read-only workspace snapshot."""

        bundle = self.recording_store.get_metadata(recording_id)
        if bundle is None:
            raise PipelineNotFound(f"The recording was not found: {recording_id}")
        video_path = self.repository_storage.bundle_path(recording_id) / self._video_relative_path(
            recording_id
        )
        try:
            video_stat = video_path.stat()
        except OSError as error:
            raise PipelineInputError("The accepted recording video is unavailable.") from error
        cache_key = (video_stat.st_mtime_ns, video_stat.st_size, bundle.source_sha256)
        with self._lock:
            cached = self._workspace_sources.get(recording_id)
            if cached is not None and cached[0] == cache_key:
                return cached[1]

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
        source = RecordingVideoSource(
            recording_id=recording_id,
            relative_path=relative_path,
            video_sha256=bundle.source_sha256,
            byte_length=video_stat.st_size,
            duration_us=probe.duration_ms * 1000,
        )
        with self._lock:
            self._workspace_sources[recording_id] = (cache_key, source)
        return source

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
        request = self._freeze_provider_defaults(request)
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

    def _freeze_provider_defaults(self, request: ProcessorRunRequest) -> ProcessorRunRequest:
        """Persist defaults used by the file provider in the immutable run request."""

        provider = self.event_provider
        if not isinstance(provider, CardEventFileProvider):
            return request
        configuration = dict(request.configuration)
        checkpoint = (
            provider.resolve_checkpoint_path(configuration) or self.card_event_checkpoint_path
        )
        defaults = None
        if checkpoint is None:
            defaults = _discover_checkpoint_defaults(self.settings.repository_root)
            checkpoint = None if defaults is None else defaults.path
        if checkpoint is None:
            raise PipelineInputError(
                "The CardEventNet checkpoint is not configured. Set CARD_EVENT_CHECKPOINT_PATH "
                "or add a trained best.pt under card_event_net/data/outputs."
            )

        if not any(key in configuration for key in ("checkpoint_path", "checkpoint")):
            configuration["checkpoint_path"] = _request_path(
                checkpoint, self.settings.repository_root
            )
        configuration.setdefault(
            "threshold",
            _DEFAULT_CARD_EVENT_THRESHOLD if defaults is None else defaults.threshold,
        )
        if defaults is not None and defaults.merge_window_s is not None:
            configuration.setdefault("merge_window_s", defaults.merge_window_s)
        return replace(request, configuration=configuration)

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
            metrics = _card_event_metrics_from_provider(result, run.request)
            content = _event_data_from_provider(result, run.request)
            items = _event_run_items(content)
            progress = RunProgress(completed=len(items), total=len(items))
            self.run_store.update_progress(run_id, progress=progress, items=items)
            revision = self._publish_processor_revision(run, content)
            self.run_store.complete(
                run_id,
                [revision.manifest.revision_id],
                metrics=metrics,
                progress=progress,
                items=items,
            )
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
            {
                "events": artifact,
                "event_type": CARD_STATE_CHANGED_EVENT_TYPE,
                "producer_id": model_id,
            },
            run.request,
        )
        items = _event_run_items(content)
        progress = RunProgress(completed=len(items), total=len(items))
        self.run_store.update_progress(run_id, progress=progress, items=items)
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
        self.run_store.complete(
            run_id,
            [stored.manifest.revision_id],
            progress=progress,
            items=items,
        )
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
        value = value.to_mapping()
    if isinstance(value, Mapping):
        raw_events = value.get("events")
        producer_id = value.get(
            "producer_id",
            _model_id(request.model) or _implementation_id(request.implementation),
        )
    else:
        raw_events = value
        producer_id = _model_id(request.model) or _implementation_id(request.implementation)
    event_type = CARD_STATE_CHANGED_EVENT_TYPE
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
                "event_type": event_type,
                "start_us": start_us,
                "end_us": round(float(raw.get("end_time_s", time_s)) * 1_000_000),
                "model_scores": [{"producer_id": str(producer_id), "score": float(probability)}],
            }
        item.setdefault("event_id", f"event-{index:06d}")
        item["event_type"] = event_type
        events.append(item)
    try:
        return EventData.from_mapping(
            {"schema_version": "event-data/v1", "events": events},
            duration_us=request.source.duration_us,
        )
    except (TypeError, ValueError) as error:
        raise PipelineProviderError("The event provider returned invalid event content.") from error


def _card_event_metrics_from_provider(
    value: EventData | Mapping[str, Any] | Sequence[Mapping[str, Any]],
    request: ProcessorRunRequest,
) -> dict[str, Any]:
    """Retain the raw CardEventNet probability stream for debugging views."""

    if not isinstance(value, Mapping) or "probabilities" not in value:
        return {}
    raw_probabilities = value.get("probabilities")
    if not isinstance(raw_probabilities, list):
        raise PipelineProviderError("The event provider returned invalid probability metrics.")

    probabilities: list[dict[str, float]] = []
    for index, raw in enumerate(raw_probabilities):
        if not isinstance(raw, Mapping):
            raise PipelineProviderError(
                f"The event provider returned invalid probability metrics at index {index}."
            )
        sample = {
            "time_s": _metric_number(raw.get("time_s"), f"probabilities[{index}].time_s"),
            "probability": _metric_number(
                raw.get("probability"), f"probabilities[{index}].probability"
            ),
        }
        if "logit" in raw and raw["logit"] is not None:
            sample["logit"] = _metric_number(raw["logit"], f"probabilities[{index}].logit")
        probabilities.append(sample)

    metrics: dict[str, Any] = {
        "schema_version": "cardeventnet-metrics/v1",
        "probabilities": probabilities,
    }
    for field in ("threshold", "merge_window_s", "min_event_gap_s"):
        raw = value.get(field, request.configuration.get(field))
        if raw is not None:
            metrics[field] = _metric_number(raw, field)
    for field in ("source_video", "checkpoint", "device", "preprocessing", "event_type"):
        raw = value.get(field)
        if raw is not None:
            if not isinstance(raw, str) or not raw:
                raise PipelineProviderError(
                    f"The event provider returned invalid {field} metadata."
                )
            metrics[field] = raw

    raw_events = value.get("events")
    if raw_events is not None:
        if not isinstance(raw_events, list):
            raise PipelineProviderError("The event provider returned invalid decoded events.")
        events: list[dict[str, float]] = []
        for index, raw in enumerate(raw_events):
            if not isinstance(raw, Mapping):
                raise PipelineProviderError(
                    f"The event provider returned invalid decoded event at index {index}."
                )
            event = {
                "time_s": _metric_number(raw.get("time_s"), f"events[{index}].time_s"),
            }
            if "probability" in raw and raw["probability"] is not None:
                event["probability"] = _metric_number(
                    raw["probability"], f"events[{index}].probability"
                )
            if "emitted_at_s" in raw and raw["emitted_at_s"] is not None:
                event["emitted_at_s"] = _metric_number(
                    raw["emitted_at_s"], f"events[{index}].emitted_at_s"
                )
            events.append(event)
        metrics["events"] = events

    return metrics


def _metric_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
        raise PipelineProviderError(f"The event provider returned invalid metric {field}.")
    return float(value)


def _event_run_items(content: EventData) -> tuple[RunItemOutcome, ...]:
    """Represent every generated event in the durable processor run state."""

    return tuple(
        RunItemOutcome(
            item_id=event.event_id,
            status="succeeded",
            result=event.to_mapping(),
            failure=None,
        )
        for event in content.events
    )


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
]
