"""Event processor orchestration for accepted recording videos."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import tempfile
from collections.abc import Callable, Mapping, Sequence
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
    ProcessorProducer,
    ProcessorRunRequest,
    RecordingVideoSource,
    RunFailure,
    RunItemOutcome,
    RunProgress,
    canonical_event_data_bytes,
    canonical_processor_run_request_bytes,
    sha256_bytes,
)

from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.intake_contract import parse_proposal_generator_run
from dokodetector_backend.job_models import Job, JobCancelled
from dokodetector_backend.job_store import JobManager
from dokodetector_backend.pipeline_node_selection_store import (
    ExactNodeSelection,
    PipelineNodeSelectionStore,
)
from dokodetector_backend.pipeline_revision_store import StoredPipelineRevision
from dokodetector_backend.pipeline_service_errors import (
    PipelineInputError,
    PipelineProviderError,
    PipelineServiceError,
)
from dokodetector_backend.pipeline_storage import (
    PipelineNotFound,
    PipelineRuntimeStorage,
    PipelineSelectionConflict,
    PipelineStateError,
)
from dokodetector_backend.processor_run_models import StoredProcessorRun
from dokodetector_backend.processor_run_store import ProcessorRunStore
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
_CARD_EVENT_RUNTIME_CACHE = Path(".runtime/cardevent/inference-cache")
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
        progress_callback: Callable[[int, int], None] | None = None,
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
        progress_callback: Callable[[int, int], None] | None = None,
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
                "or publish a validated model-campaign integration contract."
            )
        expected_digest = configuration.get("checkpoint_sha256")
        if expected_digest is not None and (
            not checkpoint.is_file() or _sha256_file(checkpoint) != expected_digest
        ):
            raise PipelineProviderError(
                "The CardEventNet checkpoint changed or is missing. Restore the frozen checkpoint."
            )
        cache_dir = (
            _configured_path(
                configuration,
                "cache_dir",
                repository_root=self.repository_root,
            )
            or self.repository_root / _CARD_EVENT_RUNTIME_CACHE
        )
        batch_size = configuration.get("batch_size")
        threshold = configuration.get("threshold")
        merge_window = configuration.get("merge_window_s")
        device = configuration.get("device")
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
            if device is not None:
                kwargs["device_override"] = device
            if progress_callback is not None:
                kwargs["progress_callback"] = progress_callback
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
        run_store: ProcessorRunStore,
        selection_store: PipelineNodeSelectionStore,
    ) -> None:
        self.settings = settings
        self.recording_store = recording_store
        self.repository_storage = repository_storage
        self.storage = PipelineRuntimeStorage(settings.evidence_root, settings.operations_root)
        self.run_store = run_store
        if run_store.lineage_writer is None:
            raise ValueError("event pipeline requires a lineage-backed run store")
        if selection_store.lineage_writer is not run_store.lineage_writer:
            raise ValueError("event pipeline selection store must share the run lineage writer")
        self.selection_store = selection_store
        self.event_provider = event_provider or CardEventFileProvider(
            settings.repository_root,
        )
        self.card_event_checkpoint_path = getattr(settings, "card_event_checkpoint_path", None)
        self._workspace_sources: dict[str, tuple[tuple[int, int, str], RecordingVideoSource]] = {}
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
        """Event work is owned and stopped by the shared job scheduler."""

    def recover_interrupted_runs(self) -> int:
        """Convert work interrupted by a backend restart into terminal failures."""

        failure = RunFailure(
            code="backend_restarted",
            message="The event processor did not finish before the backend restarted.",
        )
        count = 0
        for run in self.run_store.list_statuses():
            if run.status not in {"queued", "running"}:
                continue
            # New runs are linked to a durable job input-use record. Only settle old
            # execution-only runs here; the manager reconciles linked work itself.
            if self._event_use_path(run.run_id).exists():
                continue
            if run.status == "queued":
                self.run_store.start(run.run_id)
            self.run_store.fail(run.run_id, failure)
            count += 1
        if count:
            LOGGER.warning("event_pipeline_recovery_failed", extra={"run_count": count})
        return count

    def get_run(self, recording_id: str, run_id: str) -> StoredProcessorRun:
        run = self.run_store.require(run_id)
        self._require_recording(run.request, recording_id)
        return run

    def list_runs(self, recording_id: str) -> tuple[StoredProcessorRun, ...]:
        return tuple(
            run for run in self.run_store.list() if run.request.source.recording_id == recording_id
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

    def select_generated(
        self,
        recording_id: str,
        payload: Mapping[str, Any],
    ) -> ExactNodeSelection:
        expected_revision = payload.get("expected_revision")
        selected = payload.get("selected_generated")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise PipelineInputError("expected_revision must be a non-negative integer.")
        if selected is not None and not isinstance(selected, Mapping):
            raise PipelineInputError("selected_generated must be a node revision pointer or null.")
        current = self.selection_store.get_exact(recording_id, "events")
        completed = None if current is None else current.selected_completed_reference
        try:
            return self.selection_store.update_exact(
                recording_id,
                "events",
                expected_revision=expected_revision,
                selected_generated=selected,
                selected_completed_reference=completed,
            )
        except PipelineSelectionConflict:
            raise
        except (PipelineNotFound, PipelineStateError, ValueError, FileNotFoundError) as error:
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
        device = configuration.get("device", getattr(self.settings, "card_event_device", None))
        if device is not None:
            if not isinstance(device, str) or device not in {"cpu", "mps"}:
                raise PipelineInputError("CardEventNet device must be cpu or mps.")
            configuration["device"] = device
        checkpoint = (
            provider.resolve_checkpoint_path(configuration) or self.card_event_checkpoint_path
        )
        defaults = _discover_checkpoint_defaults(self.settings.repository_root)
        if checkpoint is None:
            checkpoint = None if defaults is None else defaults.path
        elif defaults is not None and checkpoint != defaults.path:
            defaults = None
        if checkpoint is None:
            raise PipelineInputError(
                "The CardEventNet checkpoint is not configured. Set CARD_EVENT_CHECKPOINT_PATH "
                "or publish a validated model-campaign integration contract."
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
            configuration["checkpoint_sha256"] = _sha256_file(checkpoint)
        return replace(request, configuration=configuration)

    def freeze_job_request(
        self,
        recording_id: str,
        mode: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Resolve and freeze all inputs before durable job acceptance."""
        if mode not in {"inference", "import"}:
            raise PipelineInputError("The event job mode is invalid.")
        values = dict(payload)
        raw_request = values.pop("request", values)
        if not isinstance(raw_request, Mapping):
            raise PipelineInputError("request must be an object.")
        values = {**dict(raw_request), **values}
        values["run_id"] = values.get("run_id") or "pending-event-run"
        processor_request = self._build_request(recording_id, values)
        if mode == "inference":
            processor_request = self._freeze_provider_defaults(processor_request)
        frozen: dict[str, Any] = {
            "schema": "event-job-request/v1",
            "mode": mode,
            "processor_request": processor_request.to_mapping(),
        }
        if mode == "import":
            _, artifact_id, artifact_digest, model_id, raw = self._load_import_artifact(
                recording_id,
                values,
            )
            frozen["artifact"] = {
                "id": artifact_id,
                "sha256": artifact_digest,
                "model_id": model_id,
                "bytes_base64": base64.b64encode(raw).decode("ascii"),
            }
        return frozen

    def validate_frozen_job_request(self, recording_id: str, frozen: Mapping[str, Any]) -> None:
        """Validate the frozen request and exact source identity without changing it."""
        try:
            processor_request = ProcessorRunRequest.from_mapping(frozen["processor_request"])
        except (KeyError, TypeError, ValueError) as error:
            raise PipelineInputError("The frozen event request is invalid.") from error
        if processor_request.source.recording_id != recording_id:
            raise PipelineInputError("The frozen event request has a different recording.")
        video_path = self._video_path(recording_id)
        try:
            video_path.resolve().relative_to(self.settings.repository_root.resolve())
            relative_path = (
                video_path.resolve().relative_to(self.settings.repository_root.resolve()).as_posix()
            )
            byte_length, digest = _file_identity(video_path)
        except (OSError, ValueError) as error:
            raise PipelineInputError("The frozen recording video is unavailable.") from error
        if (
            processor_request.source.relative_path != relative_path
            or processor_request.source.byte_length != byte_length
            or processor_request.source.video_sha256 != digest
        ):
            raise PipelineInputError("The frozen recording video changed after acceptance.")
        if frozen.get("mode") == "import":
            artifact = frozen.get("artifact")
            if not isinstance(artifact, Mapping):
                raise PipelineInputError("The frozen import artifact is missing.")
            try:
                raw = base64.b64decode(artifact["bytes_base64"], validate=True)
            except (KeyError, TypeError, ValueError) as error:
                raise PipelineInputError("The frozen import artifact is invalid.") from error
            if sha256_bytes(raw) != artifact.get("sha256"):
                raise PipelineInputError("The frozen import artifact digest does not match.")
            try:
                parse_proposal_generator_run(raw)
            except (TypeError, ValueError) as error:
                raise PipelineInputError("The frozen import artifact failed validation.") from error
        elif frozen.get("mode") != "inference" or "artifact" in frozen:
            raise PipelineInputError("The frozen event request mode is invalid.")

    def prepare_job(
        self,
        job_id: str,
        envelope: Mapping[str, Any],
        after_write: Any,
    ) -> None:
        recording_id = envelope["context"]["recording_id"]
        frozen = envelope["request"]
        self.validate_frozen_job_request(recording_id, frozen)
        request_values = dict(frozen["processor_request"])
        request_values["run_id"] = job_id
        domain_run_id = job_id
        processor_request = ProcessorRunRequest.from_mapping(request_values)
        stored, _ = self.run_store.create(processor_request)
        if canonical_processor_run_request_bytes(
            stored.request
        ) != canonical_processor_run_request_bytes(processor_request):
            raise PipelineInputError("The accepted event run does not match its frozen request.")
        use_path = self._event_use_path(job_id)
        use_record = {
            "schema_version": "event-job-accepted-use/v1",
            "job_id": job_id,
            "run_id": domain_run_id,
            "recording_id": recording_id,
            "video_sha256": processor_request.source.video_sha256,
            "import_sha256": frozen.get("artifact", {}).get("sha256"),
        }
        if use_path.exists():
            if json.loads(use_path.read_text(encoding="utf-8")) != use_record:
                raise PipelineInputError("The event job input protection identity conflicts.")
        else:
            atomic_replace_json(use_path, use_record)
            after_write("event_accepted_use")

    def verify_job(self, job_id: str, envelope: Mapping[str, Any]) -> bool:
        try:
            recording_id = envelope["context"]["recording_id"]
            frozen = envelope["request"]
            self.validate_frozen_job_request(recording_id, frozen)
            use = json.loads(self._event_use_path(job_id).read_text(encoding="utf-8"))
            expected = dict(frozen["processor_request"])
            expected["run_id"] = use["run_id"]
            run = self.run_store.require(use["run_id"])
            return (
                run.request.to_mapping() == ProcessorRunRequest.from_mapping(expected).to_mapping()
                and use.get("job_id") == job_id
                and use.get("run_id") == run.run_id
                and use.get("video_sha256") == run.request.source.video_sha256
                and use.get("import_sha256") == frozen.get("artifact", {}).get("sha256")
            )
        except (OSError, KeyError, TypeError, ValueError, PipelineServiceError):
            return False

    def verify_job_publication(self, job: Job, results: list[dict[str, Any]]) -> bool:
        try:
            if len(results) != 1 or results[0].get("kind") != "pipeline_revision":
                return False
            revision = self.selection_store.require_processor_revision(results[0]["id"])
            use = json.loads(self._event_use_path(job.id).read_text(encoding="utf-8"))
            run = self.run_store.require(use["run_id"])
            return (
                run.state.status == "complete"
                and run.state.output_revision_ids == (revision.manifest.revision_id,)
                and results[0].get("digest") == revision.manifest.content_sha256
            )
        except (KeyError, TypeError, ValueError, PipelineServiceError):
            return False

    def reconcile_job_states(self, jobs: Sequence[Job]) -> int:
        """Settle linked domain run records after job restart recovery."""
        count = 0
        for job in jobs:
            if job.type not in {"event_processing", "event_import"}:
                continue
            try:
                use = json.loads(self._event_use_path(job.id).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            run = self.run_store.get(use.get("run_id", job.id))
            if run is None or run.state.status != "running":
                continue
            if job.state == "interrupted":
                failure = RunFailure(
                    code="backend_restarted",
                    message="The event processor did not finish before the backend restarted.",
                )
            elif job.state == "cancelled":
                failure = RunFailure(code="cancelled", message="Event processing was cancelled.")
            elif job.state == "failed":
                failure = RunFailure(
                    code="job_failed",
                    message="The event processor job failed before it recorded a result.",
                )
            else:
                continue
            self.run_store.fail(run.run_id, failure)
            count += 1
        return count

    def execute_job(self, job: Job, token: Any, manager: JobManager) -> None:
        """Run inference or import under Job Manager ownership."""
        job_id = job.id
        accepted_use = json.loads(self._event_use_path(job_id).read_text(encoding="utf-8"))
        run_id = accepted_use["run_id"]
        run = self.run_store.start(run_id)
        try:
            token.check()
            frozen = job.request
            if frozen["mode"] == "inference":
                result, metrics = self._run_job_inference(run, token, manager, job_id)
            else:
                result, metrics = self._run_job_import(
                    run, frozen["artifact"], token, manager, job_id
                )
            token.check()
            content = _event_data_from_provider(result, run.request)
            items = _event_run_items(content)
            progress = RunProgress(completed=len(items), total=len(items))
            self.run_store.update_progress(run_id, progress=progress, items=items)
            manager.report_progress(
                job_id,
                phase="Publish event revision",
                completed=0,
                total=1,
                unit="revisions",
            )

            def publish_domain_result() -> None:
                if job.request["mode"] == "inference":
                    revision = self._publish_processor_revision(run, content)
                else:
                    artifact = job.request["artifact"]
                    producer = ImportProducer(
                        run_id=run_id,
                        artifact_id=artifact["id"],
                        artifact_sha256=artifact["sha256"],
                        source_schema="proposal-generator-run/v1",
                        model_id=artifact["model_id"],
                    )
                    revision = _build_revision(
                        run.request,
                        content,
                        _revision_id(run, suffix="import"),
                        producer,
                    )
                    revision, _ = self.selection_store.publish_processor_revision(
                        revision.manifest, revision.content
                    )
                self.run_store.complete(
                    run_id,
                    [revision.manifest.revision_id],
                    metrics=metrics,
                    progress=progress,
                    items=items,
                )
                self._advance_generated_selection(
                    run.request.source.recording_id,
                    revision.manifest.revision_id,
                )

            expected_revision = _revision_id(
                run, suffix="import" if job.request["mode"] == "import" else None
            )
            output = {
                "kind": "pipeline_revision",
                "id": expected_revision,
                "digest": self._expected_event_content_digest(result, run.request),
                "available": True,
            }
            if not manager.publish(job_id, [output], publish_domain_result):
                raise JobCancelled("job cancellation requested before event publication")
            manager.report_progress(
                job_id,
                phase="Publish event revision",
                completed=1,
                total=1,
                unit="revisions",
            )
        except JobCancelled:
            self._fail_safely(run_id, "cancelled", "Event processing was cancelled.")
            raise
        except PipelineServiceError as error:
            self._fail_safely(run_id, "provider_failed", str(error))
            raise
        except Exception:
            LOGGER.exception("event_job_handler_failed")
            self._fail_safely(run_id, "provider_failed", "The event processor failed.")
            raise RuntimeError("The event processor failed.") from None

    def _run_job_inference(
        self,
        run: StoredProcessorRun,
        token: Any,
        manager: JobManager,
        job_id: str,
    ):
        last_reported = [-1, -1]

        def on_progress(completed: int, total: int) -> None:
            token.check()
            completed = max(0, int(completed))
            total = max(completed, int(total))
            if completed == last_reported[0] and total == last_reported[1]:
                return
            step = max(1, total // 100) if total > 0 else 1
            if completed not in {0, total} and completed - last_reported[0] < step:
                return
            last_reported[:] = [completed, total]
            progress = RunProgress(completed=completed, total=total)
            self.run_store.update_progress(run.run_id, progress=progress)
            manager.report_progress(
                job_id,
                phase="Detect card events",
                completed=completed,
                total=total,
                unit="frames",
            )

        result = self.event_provider.infer(
            self._video_path(run.request.source.recording_id),
            request=run.request,
            progress_callback=on_progress,
        )
        token.check()
        return result, _card_event_metrics_from_provider(result, run.request)

    def _run_job_import(
        self,
        run: StoredProcessorRun,
        artifact: Mapping[str, Any],
        token: Any,
        manager: JobManager,
        job_id: str,
    ):
        token.check()
        raw = base64.b64decode(artifact["bytes_base64"], validate=True)
        parsed = parse_proposal_generator_run(raw)
        events = [
            {
                "event_id": f"import-{parsed.proposal_generator_run_id}-{index}",
                "time_s": event.time_s,
                "probability": event.probability,
            }
            for index, event in enumerate(parsed.event_proposals)
        ]
        result = {
            "events": events,
            "event_type": CARD_STATE_CHANGED_EVENT_TYPE,
            "producer_id": parsed.model_bundle_id,
        }
        manager.report_progress(
            job_id,
            phase="Import event predictions",
            completed=len(events),
            total=len(events),
            unit="events",
        )
        return result, {}

    def _expected_event_content_digest(
        self,
        result: Any,
        request: ProcessorRunRequest,
    ) -> str:
        content = _event_data_from_provider(result, request)
        return sha256_bytes(canonical_event_data_bytes(content))

    def _event_use_path(self, job_id: str) -> Path:
        return (
            Path(self.settings.operations_root).resolve()
            / "jobs"
            / "event-accepted-uses"
            / f"{job_id}.json"
        )

    def event_run_id_for_job(self, job_id: str) -> str:
        return json.loads(self._event_use_path(job_id).read_text(encoding="utf-8"))["run_id"]

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

    def _load_import_artifact(
        self,
        recording_id: str,
        payload: Mapping[str, Any],
    ) -> tuple[list[Mapping[str, Any]], str, str, str, bytes]:
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
            raw,
        )

    def _publish_processor_revision(
        self,
        run: StoredProcessorRun,
        content: EventData,
    ) -> StoredPipelineRevision:
        producer = ProcessorProducer(
            run_id=run.run_id,
            processor_type=run.request.processor_type,
            implementation_id=_implementation_id(run.request.implementation),
            model_id=_model_id(run.request.model),
        )
        revision = _build_revision(run.request, content, _revision_id(run), producer)
        stored, _ = self.selection_store.publish_processor_revision(
            revision.manifest, revision.content
        )
        return stored

    def _advance_generated_selection(self, recording_id: str, revision_id: str) -> None:
        current = self.selection_store.get_exact(recording_id, "events")
        expected = 0 if current is None else current.revision
        completed = None if current is None else current.selected_completed_reference
        generated = self.selection_store.reference_for_processor_output(
            revision_id, recording_id, "events"
        )
        try:
            self.selection_store.update_exact(
                recording_id,
                "events",
                expected_revision=expected,
                selected_generated=generated,
                selected_completed_reference=completed,
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
