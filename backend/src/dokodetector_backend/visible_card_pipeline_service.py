"""Execution service for video-derived visible-card detector results."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from threading import BoundedSemaphore, RLock
from typing import Any, Protocol

from doko_operations.derived_view import (
    SAMPLED_FRAME_INTERVAL_US,
    DerivedViewError,
    FFmpegFrameResolver,
    FrameResolver,
    ResolvedFrame,
    SampledFrameResolver,
    resolve_exact_event,
)
from doko_operations.pipeline_data import (
    DataRevision,
    EventData,
    ImplementationIdentity,
    ModelIdentity,
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
from table_evidence_analyzer.pipeline_data import (
    PredictedVisibleRegionGeometry,
    VisibleCardCandidate,
    VisibleCardData,
    VisibleCardFrameIdentity,
    VisibleCardModelScore,
    VisibleCardOutcome,
    VisibleCardPileRegion,
    canonical_visible_card_data_bytes,
)
from table_evidence_analyzer.visible_cards import ProviderResult, VisibleCardRequest

from dokodetector_backend.config import Settings
from dokodetector_backend.derived_view_cache import (
    DERIVED_VIEW_CACHE_LOCK,
    runtime_derived_view_cache,
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
from dokodetector_backend.recording_bundle_store import RecordingBundleStore
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage

LOGGER = logging.getLogger(__name__)
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._:-]+")


class VisibleCardPipelineError(RuntimeError):
    """The visible-card pipeline could not accept or execute a request."""


class VisibleCardPipelineInputError(VisibleCardPipelineError, ValueError):
    """The visible-card pipeline request is invalid."""


class VisibleCardPipelineProvider(Protocol):
    """Provider boundary for one exact resolved event frame."""

    name: str
    version: str

    def propose(self, request: VisibleCardRequest) -> ProviderResult:
        """Return visible-card candidates or an explicit unavailable result."""


class VisibleCardPipelineService:
    """Freeze visible-card inputs, execute one detector, and retain its result."""

    def __init__(
        self,
        settings: Settings,
        recording_store: RecordingBundleStore,
        repository_storage: RepositoryBundleStorage,
        *,
        detector_provider: VisibleCardPipelineProvider | None,
        detector_providers: Mapping[str, VisibleCardPipelineProvider] | None = None,
        frame_resolver: FrameResolver | None = None,
        run_store: ProcessorRunStore,
        selection_store: PipelineNodeSelectionStore,
        node_store: PipelineNodeStore,
    ) -> None:
        self.settings = settings
        self.recording_store = recording_store
        self.repository_storage = repository_storage
        self.detector_provider = detector_provider
        self.detector_providers = detector_providers
        self.frame_resolver = (
            frame_resolver if frame_resolver is not None else FFmpegFrameResolver()
        )
        self.run_store = run_store
        self.selection_store = selection_store
        self.node_store = node_store
        self.storage = PipelineRuntimeStorage(settings.evidence_root, settings.operations_root)
        self.max_concurrent_requests = getattr(settings, "gemini_max_concurrent_requests", 4)
        if isinstance(self.max_concurrent_requests, bool) or self.max_concurrent_requests < 1:
            raise ValueError("gemini_max_concurrent_requests must be a positive integer")
        self._request_slots = BoundedSemaphore(self.max_concurrent_requests)
        self._derived_view_lock = DERIVED_VIEW_CACHE_LOCK
        self._source_contexts: dict[
            str, tuple[tuple[int, int, int, int, str], RecordingVideoSource]
        ] = {}
        self._lock = RLock()

    async def start(self) -> None:
        """Keep the service lifecycle symmetrical with the event service."""

    async def stop(self) -> None:
        """The shared Job Manager owns worker lifecycle."""

    def get_run(
        self, recording_id: str, run_id: str, *, include_items: bool = True
    ) -> StoredProcessorRun:
        run = self.run_store.require(run_id, include_items=include_items)
        self._require_recording(run.request, recording_id)
        return run

    def list_runs(self, recording_id: str) -> tuple[StoredProcessorRun, ...]:
        return tuple(
            run
            for run in self.run_store.list_for_recording(
                recording_id,
                include_items=False,
                processor_types={"visible-card-detection"},
            )
            if run.request.source.recording_id == recording_id
            and run.request.processor_type == "visible-card-detection"
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

    def resolve_source_frame(self, recording_id: str, requested_time_us: int) -> ResolvedFrame:
        """Resolve one recording-owned exact-event frame for a derived-view URL."""

        _, source = self._accepted_source(recording_id)
        with self._derived_view_lock:
            return resolve_exact_event(
                self._video_path(recording_id),
                source=source,
                requested_time_us=requested_time_us,
                cache=runtime_derived_view_cache(self.storage.derived_views_root),
                resolver=self.frame_resolver,
                output_encoding="jpeg",
                validate_source=False,
            )

    def resolve_source_frame_index(self, recording_id: str, frame_index: int) -> ResolvedFrame:
        """Resolve one exact recording frame by its presentation index."""

        if isinstance(frame_index, bool) or frame_index < 0:
            raise VisibleCardPipelineInputError("frame_index must be non-negative")
        _, source = self._accepted_source(recording_id)
        resolver = getattr(self.frame_resolver, "resolve_frame_index", None)
        if not callable(resolver):
            raise VisibleCardPipelineInputError(
                "The configured frame resolver does not support frame stepping."
            )
        with self._derived_view_lock:
            return resolver(
                self._video_path(recording_id), source, frame_index, output_encoding="jpeg"
            )

    def resolve_sampled_source_frame(
        self, recording_id: str, requested_time_us: int
    ) -> ResolvedFrame:
        """Resolve a fast 250 ms review frame from the accepted recording video."""

        _, source = self._accepted_source(recording_id)
        with self._derived_view_lock:
            return resolve_exact_event(
                self._video_path(recording_id),
                source=source,
                requested_time_us=requested_time_us,
                cache=runtime_derived_view_cache(self.storage.derived_views_root),
                resolver=SampledFrameResolver(
                    self.storage.derived_views_root / "sampled-frames",
                    interval_us=SAMPLED_FRAME_INTERVAL_US,
                ),
                output_encoding="jpeg",
                validate_source=False,
            )

    def select_generated(self, recording_id: str, payload: Mapping[str, Any]) -> ExactNodeSelection:
        expected_revision = payload.get("expected_revision")
        selected = payload.get("selected_generated")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise VisibleCardPipelineInputError("expected_revision must be a non-negative integer.")
        if selected is not None and not isinstance(selected, Mapping):
            raise VisibleCardPipelineInputError(
                "selected_generated must be a node revision pointer or null."
            )
        current = self.selection_store.get_exact(recording_id, "visible_cards")
        completed = None if current is None else current.selected_completed_reference
        try:
            return self.selection_store.update_exact(
                recording_id,
                "visible_cards",
                expected_revision=expected_revision,
                selected_generated=selected,
                selected_completed_reference=completed,
            )
        except PipelineSelectionConflict:
            raise
        except (PipelineNotFound, PipelineStateError, ValueError, FileNotFoundError) as error:
            raise VisibleCardPipelineInputError(str(error)) from error

    def _build_request(self, recording_id: str, payload: Mapping[str, Any]) -> ProcessorRunRequest:
        if not isinstance(payload, Mapping):
            raise VisibleCardPipelineInputError("The processor request must be an object.")
        if self.detector_provider is None and not self.detector_providers:
            raise VisibleCardPipelineInputError("The visible-card detector is unavailable.")
        raw = payload.get("request", payload)
        if not isinstance(raw, Mapping):
            raise VisibleCardPipelineInputError("request must be an object.")
        _, source = self._accepted_source(recording_id)
        node_ref = raw.get("input_node_ref")
        if raw.get("input_revision_ids") is not None or raw.get("event_revision_id") is not None:
            raise VisibleCardPipelineInputError(
                "use input_node_ref instead of revision-ID input fields"
            )
        if not isinstance(node_ref, Mapping) or set(node_ref) != {
            "node_id",
            "revision_id",
            "revision_policy",
        }:
            raise VisibleCardPipelineInputError("input_node_ref is required and must be exact.")
        if node_ref is not None:
            node_id, node_revision_id, revision_policy = (
                node_ref.get("node_id"),
                node_ref.get("revision_id"),
                node_ref.get("revision_policy"),
            )
            if not all(isinstance(value, str) and value for value in (node_id, node_revision_id)):
                raise VisibleCardPipelineInputError(
                    "input_node_ref needs exact node and revision IDs."
                )
            if not isinstance(revision_policy, str) or revision_policy not in {
                "current_head",
                "historical",
            }:
                raise VisibleCardPipelineInputError(
                    "input_node_ref needs an explicit revision policy."
                )
            try:
                node = self.node_store.get(node_id)
                node_revision = self.node_store.read_revision(node_id, node_revision_id)
            except (FileNotFoundError, KeyError, ValueError) as error:
                raise VisibleCardPipelineInputError(
                    "The selected event node revision is unavailable."
                ) from error
            if node.content_type != "events" or node.source != source.to_mapping():
                raise VisibleCardPipelineInputError(
                    "The selected node must contain events from the accepted recording video."
                )
            if revision_policy == "current_head" and node.head_revision_id != node_revision_id:
                raise VisibleCardPipelineInputError(
                    "The selected event node is not its current head."
                )
            try:
                events = parse_event_data_bytes(canonical_json_bytes(node_revision.content))
            except (TypeError, ValueError) as error:
                raise VisibleCardPipelineInputError(
                    "The selected node revision has invalid event data."
                ) from error
            if not isinstance(events, EventData):
                raise VisibleCardPipelineInputError(
                    "The selected node revision has invalid event data."
                )
            event_revision_id = node_revision_id
        else:
            raise VisibleCardPipelineInputError("input_node_ref is required.")
        requested_provider = configuration_provider(raw.get("configuration"))
        provider = self._provider_for_selection(requested_provider)
        if provider is None:
            raise VisibleCardPipelineInputError(
                "The requested visible-card processor is unavailable."
            )
        provider = _base_provider(provider)
        provider_name = _provider_text(provider, "name")
        provider_version = _provider_text(provider, "version")
        values = dict(raw)
        values.pop("event_revision_id", None)
        values.setdefault("schema_version", "processor-run-request/v1")
        values.setdefault("run_id", payload.get("run_id"))
        if not values.get("run_id"):
            raise VisibleCardPipelineInputError("run_id is required.")
        values.setdefault("processor_type", "visible-card-detection")
        values.setdefault("source", source.to_mapping())
        values["input_revision_ids"] = [event_revision_id]
        values["input_node_ref"] = dict(node_ref)
        values.setdefault(
            "implementation",
            {"name": "visible-card-detector-adapter", "version": "v1"},
        )
        model_placeholder = {"name": provider_name, "version": provider_version}
        if (
            values.get("model") is None
            or values.get("model") == model_placeholder
            or requested_provider is not None
        ):
            values["model"] = {
                "name": self.settings.gemini_model if provider_name == "gemini" else provider_name,
                "version": provider_version,
            }
        configuration = values.get("configuration", {})
        if not isinstance(configuration, Mapping):
            raise VisibleCardPipelineInputError("configuration must be an object.")
        configuration = dict(configuration)
        configuration["provider"] = provider_name
        configuration["detector"] = {"name": provider_name, "version": provider_version}
        bundle_identity = getattr(provider, "bundle_identity", None)
        if isinstance(bundle_identity, Mapping):
            configuration["bundle_identity"] = dict(bundle_identity)
        device = getattr(provider, "device", None)
        if isinstance(device, str):
            configuration["device"] = device
        values["configuration"] = configuration
        values.setdefault(
            "extraction_policy", {"policy_id": "exact-event/v1", "output_encoding": "jpeg"}
        )
        raw_extraction_policy = values["extraction_policy"]
        if not isinstance(raw_extraction_policy, Mapping):
            raise VisibleCardPipelineInputError("extraction_policy must be an object.")
        extraction_policy = dict(raw_extraction_policy)
        event_time_anchor = extraction_policy.setdefault("event_time_anchor", "start_us")
        if event_time_anchor not in {"start_us", "end_us"}:
            raise VisibleCardPipelineInputError(
                "extraction_policy.event_time_anchor must be start_us or end_us."
            )
        values["extraction_policy"] = extraction_policy
        values.setdefault("crop_policy", None)
        try:
            request = ProcessorRunRequest.from_mapping(values)
        except (TypeError, ValueError) as error:
            raise VisibleCardPipelineInputError(
                "The visible-card processor request failed validation."
            ) from error
        if request.source != source:
            raise VisibleCardPipelineInputError(
                "The request source does not match the accepted recording video."
            )
        if request.processor_type != "visible-card-detection":
            raise VisibleCardPipelineInputError(
                "The visible-card endpoint only accepts visible-card-detection runs."
            )
        return request

    def freeze_job_request(self, recording_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Resolve and freeze the event revision and detector request before acceptance."""
        request = self._build_request(recording_id, payload)
        return {"schema": "visible-card-job-request/v1", "processor_request": request.to_mapping()}

    def validate_frozen_job_request(self, recording_id: str, frozen: Mapping[str, Any]) -> None:
        try:
            request = ProcessorRunRequest.from_mapping(frozen["processor_request"])
        except (KeyError, TypeError, ValueError) as error:
            raise VisibleCardPipelineInputError(
                "The frozen visible-card request is invalid."
            ) from error
        if frozen.get("schema") != "visible-card-job-request/v1":
            raise VisibleCardPipelineInputError(
                "The frozen visible-card request schema is invalid."
            )
        _, source = self._accepted_source(recording_id)
        if request.source != source or request.source.recording_id != recording_id:
            raise VisibleCardPipelineInputError("The frozen visible-card source changed.")
        if (
            request.processor_type != "visible-card-detection"
            or len(request.input_revision_ids) != 1
        ):
            raise VisibleCardPipelineInputError("The frozen visible-card inputs are invalid.")
        if request.input_node_ref is not None:
            ref = request.input_node_ref
            try:
                node = self.node_store.get(ref["node_id"])
                node_revision = self.node_store.read_revision(ref["node_id"], ref["revision_id"])
                content = parse_event_data_bytes(canonical_json_bytes(node_revision.content))
            except (FileNotFoundError, KeyError, TypeError, ValueError) as error:
                raise VisibleCardPipelineInputError(
                    "The frozen event node revision is unavailable."
                ) from error
            if (
                node.content_type != "events"
                or node.source != source.to_mapping()
                or not isinstance(content, EventData)
                or (
                    ref["revision_policy"] == "current_head"
                    and node.head_revision_id != ref["revision_id"]
                )
            ):
                raise VisibleCardPipelineInputError(
                    "The frozen event node revision is unavailable."
                )
        else:
            raise VisibleCardPipelineInputError(
                "The frozen visible-card request has no exact event node reference."
            )

    def prepare_job(self, job_id: str, envelope: Mapping[str, Any], after_write: Any) -> None:
        recording_id = envelope["context"]["recording_id"]
        frozen = envelope["request"]
        self.validate_frozen_job_request(recording_id, frozen)
        values = dict(frozen["processor_request"])
        values["run_id"] = job_id
        processor_request = ProcessorRunRequest.from_mapping(values)
        stored, _ = self.run_store.create(processor_request)
        if stored.request.to_mapping() != processor_request.to_mapping():
            raise VisibleCardPipelineInputError("The accepted visible-card run conflicts.")
        use = {
            "schema_version": "visible-card-job-accepted-use/v1",
            "job_id": job_id,
            "recording_id": recording_id,
            "event_revision_id": processor_request.input_revision_ids[0],
            "event_node_ref": processor_request.input_node_ref,
            "video_sha256": processor_request.source.video_sha256,
        }
        path = self._job_use_path(job_id)
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != use:
                raise VisibleCardPipelineInputError(
                    "The visible-card accepted-use identity conflicts."
                )
        else:
            from dokodetector_backend.filesystem import atomic_replace_json

            atomic_replace_json(path, use)
            after_write("visible_card_accepted_use")

    def verify_job(self, job_id: str, envelope: Mapping[str, Any]) -> bool:
        try:
            recording_id = envelope["context"]["recording_id"]
            frozen = envelope["request"]
            self.validate_frozen_job_request(recording_id, frozen)
            use = json.loads(self._job_use_path(job_id).read_text(encoding="utf-8"))
            expected = dict(frozen["processor_request"])
            expected["run_id"] = job_id
            run = self.run_store.require(job_id)
            return (
                run.request.to_mapping() == ProcessorRunRequest.from_mapping(expected).to_mapping()
                and use.get("job_id") == job_id
                and use.get("event_revision_id") == run.request.input_revision_ids[0]
                and use.get("event_node_ref") == run.request.input_node_ref
                and use.get("video_sha256") == run.request.source.video_sha256
            )
        except (OSError, KeyError, TypeError, ValueError, PipelineStateError, PipelineNotFound):
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
        except (KeyError, TypeError, ValueError, PipelineStateError, PipelineNotFound):
            return False

    def reconcile_job_states(self, jobs: list[Job]) -> None:
        for job in jobs:
            if job.type != "visible_card_detection":
                continue
            run = self.run_store.get(job.id)
            if run is None or run.state.status != "running":
                continue
            if job.state == "interrupted":
                failure = RunFailure(
                    code="backend_restarted",
                    message=(
                        "The visible-card detector did not finish before the backend restarted."
                    ),
                )
            elif job.state == "cancelled":
                failure = RunFailure(
                    code="cancelled", message="Visible-card processing was cancelled."
                )
            elif job.state == "failed":
                failure = RunFailure(code="job_failed", message="The visible-card job failed.")
            else:
                continue
            self.run_store.fail(job.id, failure)

    def _job_use_path(self, job_id: str) -> Path:
        return self.storage.operations_root / "visible-card-job-uses" / f"{job_id}.json"

    def execute_job(self, job: Job, claims: Any, token: Any, manager: JobManager) -> None:
        """Run bounded frame work under Job Manager ownership and publish one exact revision."""
        run_id = job.id
        run = self.run_store.start(run_id)
        try:
            if run.request.input_node_ref is not None:
                ref = run.request.input_node_ref
                node_revision = self.node_store.read_revision(ref["node_id"], ref["revision_id"])
                event_content = parse_event_data_bytes(canonical_json_bytes(node_revision.content))
            else:
                raise VisibleCardPipelineInputError(
                    "The accepted visible-card run has no exact event node reference."
                )
            if not isinstance(event_content, EventData):
                raise VisibleCardPipelineError("The event input revision is invalid.")
            events = event_content.events
            outcomes: list[VisibleCardOutcome | None] = [None] * len(events)
            prior_items = {item.item_id: item for item in run.state.items}
            if not set(prior_items).issubset({event.event_id for event in events}):
                raise VisibleCardPipelineError(
                    "The retry has an item outside its frozen event input."
                )
            items: list[RunItemOutcome | None] = [
                prior_items.get(event.event_id) for event in events
            ]
            completed = 0
            pending: list[tuple[int, Any]] = []
            for index, event in enumerate(events):
                token.check()
                item = items[index]
                if item is None or item.status != "succeeded":
                    pending.append((index, event))
                    continue
                if item.result is None:
                    raise VisibleCardPipelineError("A retained event outcome is invalid.")
                outcome = VisibleCardOutcome.from_mapping(item.result)
                if outcome.event_id != event.event_id:
                    raise VisibleCardPipelineError("A retained event outcome has the wrong ID.")
                outcomes[index] = outcome
                completed += 1
            manager.report_progress(
                job.id,
                phase="Detect visible cards",
                completed=completed,
                total=len(events),
                unit="event frames",
            )
            self.run_store.update_progress(
                run_id, progress=RunProgress(completed=completed, total=len(events))
            )

            def process(item: tuple[int, Any]) -> tuple[int, VisibleCardOutcome]:
                token.check()
                index, event = item
                try:
                    return index, self._process_event_timed(run, event)
                except Exception:
                    LOGGER.exception(
                        "visible_card_event_failed",
                        extra={"run_id": run.run_id, "event_id": event.event_id},
                    )
                    return index, VisibleCardOutcome(
                        event_id=event.event_id,
                        frame_identity=None,
                        status="failed",
                        candidates=(),
                        error="The visible-card detector failed for this event.",
                    )

            worker_count = min(
                max(1, int(claims.cpu)),
                self._event_concurrency_limit(run),
                max(1, len(pending)),
            )
            with ThreadPoolExecutor(
                max_workers=worker_count, thread_name_prefix="visible-card-event"
            ) as executor:
                futures: dict[Future[tuple[int, VisibleCardOutcome]], int] = {
                    executor.submit(process, item): item[0] for item in pending
                }
                for future in as_completed(futures):
                    token.check()
                    index, outcome = future.result()
                    event = events[index]
                    outcomes[index] = outcome
                    item = RunItemOutcome(
                        item_id=event.event_id,
                        status="succeeded",
                        result=outcome.to_mapping(),
                        failure=None,
                    )
                    items[index] = item
                    completed += 1
                    progress = RunProgress(completed=completed, total=len(events))
                    self.run_store.record_item_progress(run_id, progress=progress, item=item)
                    manager.report_progress(
                        job.id,
                        phase="Detect visible cards",
                        completed=completed,
                        total=len(events),
                        unit="event frames",
                    )

            token.check()
            final_outcomes = tuple(item for item in outcomes if item is not None)
            final_items = tuple(item for item in items if item is not None)
            if len(final_outcomes) != len(events) or len(final_items) != len(events):
                raise VisibleCardPipelineError("The detector did not process every event frame.")
            content = VisibleCardData(outcomes=final_outcomes)
            revision_id = f"visible-cards-{_safe(run.run_id)}-attempt-{run.state.attempt}"
            output = {
                "kind": "pipeline_revision",
                "id": revision_id,
                "digest": sha256_bytes(canonical_visible_card_data_bytes(content)),
                "available": True,
            }
            manager.report_progress(
                job.id,
                phase="Publish visible-card revision",
                completed=0,
                total=1,
                unit="revisions",
            )

            def commit() -> None:
                revision = self._publish_revision(run, content)
                self.run_store.complete(
                    run_id,
                    [revision.manifest.revision_id],
                    progress=RunProgress(completed=len(final_items), total=len(events)),
                    items=final_items,
                )
                self._advance_generated_selection(
                    run.request.source.recording_id, revision.manifest.revision_id
                )

            if not manager.publish(job.id, [output], commit):
                raise JobCancelled("job cancellation requested before visible-card publication")
            manager.report_progress(
                job.id,
                phase="Publish visible-card revision",
                completed=1,
                total=1,
                unit="revisions",
            )
        except JobCancelled:
            self._fail_safely(run_id, "cancelled", "Visible-card processing was cancelled.")
            raise
        except VisibleCardPipelineError as error:
            self._fail_safely(run_id, "provider_failed", str(error))
            raise
        except Exception:
            LOGGER.exception("visible_card_job_handler_failed")
            self._fail_safely(run_id, "provider_failed", "The visible-card detector failed.")
            raise RuntimeError("The visible-card detector failed.") from None

    def _process_event(self, run: StoredProcessorRun, event: Any) -> VisibleCardOutcome:
        try:
            with self._derived_view_lock:
                frame = resolve_exact_event(
                    self._video_path(run.request.source.recording_id),
                    source=run.request.source,
                    requested_time_us=getattr(
                        event,
                        run.request.extraction_policy.get("event_time_anchor", "start_us"),
                    ),
                    cache=runtime_derived_view_cache(self.storage.derived_views_root),
                    resolver=self.frame_resolver,
                    output_encoding=run.request.extraction_policy.get("output_encoding", "jpeg"),
                )
        except (DerivedViewError, OSError, RuntimeError):
            return VisibleCardOutcome(
                event_id=event.event_id,
                frame_identity=None,
                status="failed",
                candidates=(),
                error="The exact event frame is unavailable.",
            )
        try:
            with self._request_slots:
                result = self._propose(run, event.event_id, frame)
        except Exception:
            return VisibleCardOutcome(
                event_id=event.event_id,
                frame_identity=VisibleCardFrameIdentity.from_mapping(frame.identity_mapping()),
                status="failed",
                candidates=(),
                error="The visible-card detector failed for this event.",
            )
        frame_identity = VisibleCardFrameIdentity.from_mapping(frame.identity_mapping())
        if result.status != "ok":
            return VisibleCardOutcome(
                event_id=event.event_id,
                frame_identity=frame_identity,
                status="failed",
                candidates=(),
                error=result.error
                or "The visible-card detector returned no result for this event.",
            )
        candidates = tuple(
            self._candidate(run, event.event_id, frame, index, proposal, result)
            for index, proposal in enumerate(result.proposals)
        )
        pile_regions = tuple(
            VisibleCardPileRegion(
                pile_id=f"{_safe(run.run_id)}-{_safe(event.event_id)}-pile-{index:04d}",
                polygons=(tuple((point.x, point.y) for point in proposal.polygon),),
                normalization={
                    "width": frame.width,
                    "height": frame.height,
                    "policy_id": "full-frame-0-1000/v1",
                },
                origin="model_prediction",
                confidence=proposal.confidence,
                model_lineage=proposal.model_lineage,
            )
            for index, proposal in enumerate(result.pile_proposals)
        )
        return VisibleCardOutcome(
            event_id=event.event_id,
            frame_identity=frame_identity,
            status="detected" if candidates or pile_regions else "empty",
            candidates=candidates,
            pile_regions=pile_regions,
            pile_detection_status=(
                "supported"
                if isinstance(result.raw_response, Mapping)
                and result.raw_response.get("pile_detection_supported") is True
                else "unsupported"
            ),
            error=None,
        )

    def _process_event_timed(self, run: StoredProcessorRun, event: Any) -> VisibleCardOutcome:
        started = time.monotonic()
        try:
            return self._process_event(run, event)
        finally:
            LOGGER.info(
                "visible_card_event_timing",
                extra={
                    "event_name": "visible_card_event_timing",
                    "run_id": run.run_id,
                    "event_id": event.event_id,
                    "item_wall_time_ms": round(max(0.0, time.monotonic() - started) * 1000.0, 3),
                    "timing_scope": (
                        "wall-clock item timing; inference and network transfer are not separated"
                    ),
                },
            )

    def _propose(
        self, run: StoredProcessorRun, event_id: str, frame: ResolvedFrame
    ) -> ProviderResult:
        provider = self._provider_for_selection(configuration_provider(run.request.configuration))
        if provider is None:
            raise VisibleCardPipelineError("The visible-card detector is unavailable.")
        actual_provider = _base_provider(provider)
        for field, actual in (
            ("bundle_identity", getattr(actual_provider, "bundle_identity", None)),
            ("device", getattr(actual_provider, "device", None)),
        ):
            if field in run.request.configuration and run.request.configuration[field] != actual:
                raise VisibleCardPipelineError(
                    f"The visible-card {field} changed since this run was created. Start a new run."
                )
        model = run.request.model
        request = VisibleCardRequest(
            package_id=f"{run.run_id}-{event_id}",
            frame_part_name=f"frame-{frame.frame_index:08d}",
            target_offset_ms=0,
            image_bytes=frame.image_bytes,
            width=frame.width,
            height=frame.height,
            provider=run.request.configuration["provider"],
            model=model.name if model is not None else "visible-card-detector",
        )
        return provider.propose(request)

    def _event_concurrency_limit(self, run: StoredProcessorRun) -> int:
        """Limit per-run workers when a provider shares serialized native state."""

        provider = self._provider_for_selection(configuration_provider(run.request.configuration))
        if provider is None:
            return self.max_concurrent_requests
        limit = getattr(_base_provider(provider), "event_concurrency_limit", None)
        if limit is None:
            return self.max_concurrent_requests
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise VisibleCardPipelineError(
                "The detector provider has an invalid concurrency limit."
            )
        return min(self.max_concurrent_requests, limit)

    def _provider_for_selection(
        self, requested_provider: str | None
    ) -> VisibleCardPipelineProvider | None:
        if requested_provider is None:
            if self.detector_provider is not None:
                return self.detector_provider
            requested_provider = getattr(self.settings, "visible_card_provider", None)
            if requested_provider is None:
                return None
        candidates = (
            ("gemini", "cloud")
            if requested_provider == "cloud"
            else ("local", "local-rfdetr-segmentation")
            if requested_provider == "local"
            else (requested_provider,)
        )
        if self.detector_providers is not None:
            for candidate in candidates:
                try:
                    provider = self.detector_providers.get(candidate)
                except (KeyError, ValueError, RuntimeError) as error:
                    raise VisibleCardPipelineInputError(str(error)) from error
                if provider is not None:
                    return provider
        current = self.detector_provider
        if current is not None:
            current_name = _provider_text(_base_provider(current), "name")
            if requested_provider in {
                current_name,
                "cloud" if current_name == "gemini" else None,
                "local" if current_name.startswith("local") else None,
            }:
                return current
        return None

    def _candidate(
        self,
        run: StoredProcessorRun,
        event_id: str,
        frame: ResolvedFrame,
        index: int,
        proposal: Any,
        result: ProviderResult,
    ) -> VisibleCardCandidate:
        score = _proposal_score(result, index)
        model_scores = None
        if score is not None:
            model_id = _model_id(run.request.model) or _implementation_id(
                run.request.implementation
            )
            model_scores = (VisibleCardModelScore(producer_id=model_id, score=score),)
        return VisibleCardCandidate(
            card_id=f"{_safe(run.run_id)}-{_safe(event_id)}-card-{index:04d}",
            geometry=PredictedVisibleRegionGeometry(
                polygons=tuple(
                    tuple((point.x, point.y) for point in component)
                    for component in (proposal.polygons or (proposal.polygon,))
                ),
            ),
            normalization={
                "width": frame.width,
                "height": frame.height,
                "policy_id": "full-frame-0-1000/v1",
            },
            side=proposal.side,
            model_scores=model_scores,
        )

    def _publish_revision(
        self, run: StoredProcessorRun, content: VisibleCardData
    ) -> StoredPipelineRevision:
        producer = ProcessorProducer(
            run_id=run.run_id,
            processor_type=run.request.processor_type,
            implementation_id=_implementation_id(run.request.implementation),
            model_id=_model_id(run.request.model),
        )
        manifest = DataRevision(
            revision_id=f"visible-cards-{_safe(run.run_id)}-attempt-{run.state.attempt}",
            content_type="visible_cards",
            content_schema="visible-card-data/v2",
            recording_id=run.request.source.recording_id,
            source=run.request.source,
            content_sha256=sha256_bytes(canonical_visible_card_data_bytes(content)),
            input_revision_ids=run.request.input_revision_ids,
            origin="processor",
            producer=producer,
            coverage={
                "kind": "requested-event-frames",
                "event_revision_id": run.request.input_revision_ids[0],
                "event_ids": [outcome.event_id for outcome in content.outcomes],
                "policy_id": run.request.extraction_policy["policy_id"],
            },
            created_at=_now(),
        )
        stored, _ = self.selection_store.publish_processor_revision(manifest, content)
        return stored

    def _advance_generated_selection(self, recording_id: str, revision_id: str) -> None:
        current = self.selection_store.get_exact(recording_id, "visible_cards")
        expected = 0 if current is None else current.revision
        completed = None if current is None else current.selected_completed_reference
        generated = self.selection_store.reference_for_processor_output(
            revision_id, recording_id, "visible_cards"
        )
        try:
            self.selection_store.update_exact(
                recording_id,
                "visible_cards",
                expected_revision=expected,
                selected_generated=generated,
                selected_completed_reference=completed,
            )
        except PipelineSelectionConflict:
            LOGGER.warning(
                "visible_card_pipeline_selection_advance_conflict",
                extra={"recording_id": recording_id},
            )

    def _fail_safely(self, run_id: str, code: str, message: str) -> None:
        try:
            run = self.run_store.get(run_id)
            if run is not None and run.state.status == "running":
                self.run_store.fail(run_id, RunFailure(code=code, message=message))
        except Exception:
            LOGGER.exception("visible_card_pipeline_failure_persist_failed")

    def _accepted_source(self, recording_id: str) -> tuple[Any, RecordingVideoSource]:
        bundle = self.recording_store.get_metadata(recording_id)
        if bundle is None:
            raise PipelineNotFound(f"The recording was not found: {recording_id}")
        video_path = self._video_path(recording_id)
        if not video_path.is_file():
            raise VisibleCardPipelineInputError("The accepted recording video is unavailable.")
        try:
            video_stat = video_path.stat()
        except OSError as error:
            raise VisibleCardPipelineInputError(
                "The accepted recording video is unavailable."
            ) from error
        cache_key = (
            video_stat.st_mtime_ns,
            video_stat.st_ctime_ns,
            video_stat.st_size,
            bundle.video_byte_length,
            bundle.source_sha256,
        )
        with self._lock:
            cached = self._source_contexts.get(recording_id)
            if cached is not None and cached[0] == cache_key:
                return bundle, cached[1]

        actual_length, actual_digest = _file_identity(video_path)
        if actual_length != bundle.video_byte_length or actual_digest != bundle.source_sha256:
            raise VisibleCardPipelineInputError(
                "The accepted recording video does not match its manifest."
            )
        try:
            from dokodetector_backend.video_probe import probe_video_path_metadata

            probe = probe_video_path_metadata(video_path)
        except Exception as error:
            raise VisibleCardPipelineInputError(
                "The accepted recording video could not be probed."
            ) from error
        try:
            relative_path = (
                video_path.resolve().relative_to(self.settings.repository_root).as_posix()
            )
        except ValueError as error:
            raise VisibleCardPipelineInputError(
                "The accepted recording video is outside the repository root."
            ) from error
        source = RecordingVideoSource(
            recording_id=recording_id,
            relative_path=relative_path,
            video_sha256=bundle.source_sha256,
            byte_length=actual_length,
            duration_us=probe.duration_ms * 1000,
        )
        with self._lock:
            self._source_contexts[recording_id] = (cache_key, source)
        return bundle, source

    def _video_path(self, recording_id: str) -> Path:
        manifest = self.repository_storage.bundle_path(recording_id) / "manifest.json"
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
            relative_path = value["files"]["video"]["relative_path"]
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise VisibleCardPipelineInputError(
                "The accepted recording manifest is invalid."
            ) from error
        path = self.repository_storage.bundle_path(recording_id) / str(relative_path)
        try:
            path.resolve().relative_to(self.repository_storage.bundle_path(recording_id).resolve())
        except ValueError as error:
            raise VisibleCardPipelineInputError(
                "The accepted recording video path is invalid."
            ) from error
        return path

    @staticmethod
    def _require_recording(request: ProcessorRunRequest, recording_id: str) -> None:
        if request.source.recording_id != recording_id:
            raise PipelineNotFound(f"The processor run was not found for recording: {recording_id}")


def _base_provider(provider: VisibleCardPipelineProvider) -> VisibleCardPipelineProvider:
    current = provider
    while getattr(current, "name", None) == "cached" and hasattr(current, "provider"):
        current = current.provider
    return current


def configuration_provider(value: Any) -> str | None:
    """Read the optional provider selection from a processor configuration."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise VisibleCardPipelineInputError("configuration must be an object.")
    provider = value.get("provider")
    if provider is None:
        return None
    if not isinstance(provider, str) or not provider:
        raise VisibleCardPipelineInputError("configuration.provider must be a non-empty string.")
    return provider


def _provider_text(provider: Any, field: str) -> str:
    value = getattr(provider, field, None)
    if not isinstance(value, str) or not value:
        raise VisibleCardPipelineInputError(f"The detector provider has no valid {field}.")
    return value


def _proposal_score(result: ProviderResult, index: int) -> float | None:
    raw = result.raw_response
    if not isinstance(raw, Mapping):
        return None
    scores = raw.get("detector_scores")
    if isinstance(scores, list) and index < len(scores):
        value = scores[index]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    detections = raw.get("detections")
    if isinstance(detections, list) and index < len(detections):
        value = detections[index]
        if isinstance(value, Mapping) and isinstance(value.get("score"), (int, float)):
            return float(value["score"])
    return None


def _implementation_id(identity: ImplementationIdentity) -> str:
    return _safe(identity.name) + "." + _safe(identity.version)


def _model_id(model: ModelIdentity | None) -> str | None:
    return None if model is None else _safe(model.name) + "." + _safe(model.version)


def _safe(value: str) -> str:
    return _SAFE_COMPONENT.sub("-", value).strip("-") or "unknown"


def _file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            length += len(chunk)
            digest.update(chunk)
    return length, digest.hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = [
    "VisibleCardPipelineError",
    "VisibleCardPipelineInputError",
    "VisibleCardPipelineProvider",
    "VisibleCardPipelineService",
]
