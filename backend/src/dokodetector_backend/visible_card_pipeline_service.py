"""Execution service for video-derived visible-card detector results."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from doko_operations.derived_view import (
    DerivedViewError,
    FrameResolver,
    ResolvedFrame,
    resolve_exact_event,
)
from doko_operations.pipeline_data import (
    DataRevision,
    EventData,
    ImplementationIdentity,
    ModelIdentity,
    PipelineSelection,
    ProcessorProducer,
    ProcessorRunRequest,
    RecordingVideoSource,
    RunFailure,
    RunItemOutcome,
    RunProgress,
    sha256_bytes,
)
from table_evidence_analyzer.pipeline_data import (
    DetectorBoxGeometry,
    VisibleCardCandidate,
    VisibleCardData,
    VisibleCardFrameIdentity,
    VisibleCardModelScore,
    VisibleCardOutcome,
    canonical_visible_card_data_bytes,
)
from table_evidence_analyzer.visible_cards import ProviderResult, VisibleCardRequest

from dokodetector_backend.config import Settings
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
        frame_resolver: FrameResolver | None = None,
        revision_store: PipelineRevisionStore,
        run_store: ProcessorRunStore,
        selection_store: PipelineSelectionStore,
    ) -> None:
        self.settings = settings
        self.recording_store = recording_store
        self.repository_storage = repository_storage
        self.detector_provider = detector_provider
        self.frame_resolver = frame_resolver
        self.revision_store = revision_store
        self.run_store = run_store
        self.selection_store = selection_store
        self.storage = PipelineRuntimeStorage(settings.evidence_root)
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="visible-card-pipeline"
        )
        self._futures: dict[str, Future[None]] = {}
        self._lock = RLock()

    async def start(self) -> None:
        """Keep the service lifecycle symmetrical with the event service."""

    async def stop(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
        with self._lock:
            self._futures.clear()

    def start_detection(self, recording_id: str, payload: Mapping[str, Any]) -> StoredProcessorRun:
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
            if run.request.source.recording_id == recording_id
            and run.request.processor_type == "visible-card-detection"
        )

    def get_result(
        self, recording_id: str, run_id: str
    ) -> tuple[StoredProcessorRun, tuple[StoredPipelineRevision, ...]]:
        run = self.get_run(recording_id, run_id)
        revisions = tuple(
            self.revision_store.require(item) for item in run.state.output_revision_ids
        )
        return run, revisions

    def resolve_source_frame(self, recording_id: str, requested_time_us: int) -> ResolvedFrame:
        """Resolve one recording-owned exact-event frame for a derived-view URL."""

        _, source = self._accepted_source(recording_id)
        return resolve_exact_event(
            self._video_path(recording_id),
            source=source,
            requested_time_us=requested_time_us,
            cache=self.storage.pipeline_root / "derived-views",
            resolver=self.frame_resolver,
            output_encoding="jpeg",
        )

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
            raise VisibleCardPipelineInputError("expected_revision must be a non-negative integer.")
        if selected is not None and not isinstance(selected, str):
            raise VisibleCardPipelineInputError(
                "selected_generated_revision_id must be a string or null."
            )
        current = self.selection_store.get(recording_id, "visible_cards")
        completed = None if current is None else current.selected_completed_reference_revision_id
        try:
            return self.selection_store.update_pointers(
                recording_id,
                "visible_cards",
                expected_revision=expected_revision,
                selected_generated_revision_id=selected,
                selected_completed_reference_revision_id=completed,
            )
        except PipelineSelectionConflict:
            raise
        except (PipelineNotFound, PipelineStateError) as error:
            raise VisibleCardPipelineInputError(str(error)) from error

    def _build_request(self, recording_id: str, payload: Mapping[str, Any]) -> ProcessorRunRequest:
        if not isinstance(payload, Mapping):
            raise VisibleCardPipelineInputError("The processor request must be an object.")
        if self.detector_provider is None:
            raise VisibleCardPipelineInputError("The visible-card detector is unavailable.")
        raw = payload.get("request", payload)
        if not isinstance(raw, Mapping):
            raise VisibleCardPipelineInputError("request must be an object.")
        _, source = self._accepted_source(recording_id)
        event_revision_id = self._event_revision_id(recording_id, raw)
        event_revision = self.revision_store.require(event_revision_id)
        if (
            event_revision.manifest.content_type != "events"
            or event_revision.manifest.source != source
            or not isinstance(event_revision.content, EventData)
        ):
            raise VisibleCardPipelineInputError(
                "The selected event revision does not match the accepted recording video."
            )
        provider = _base_provider(self.detector_provider)
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
        values.setdefault(
            "implementation",
            {"name": "visible-card-detector-adapter", "version": "v1"},
        )
        values.setdefault(
            "model",
            {"name": provider_name, "version": provider_version},
        )
        configuration = values.get("configuration", {})
        if not isinstance(configuration, Mapping):
            raise VisibleCardPipelineInputError("configuration must be an object.")
        configuration = dict(configuration)
        configured_provider = configuration.get("provider", provider_name)
        if configured_provider != provider_name:
            raise VisibleCardPipelineInputError(
                "The requested detector provider is not the configured provider."
            )
        configuration.setdefault("provider", provider_name)
        configuration.setdefault(
            "detector",
            {"name": provider_name, "version": provider_version},
        )
        values["configuration"] = configuration
        values.setdefault(
            "extraction_policy", {"policy_id": "exact-event/v1", "output_encoding": "jpeg"}
        )
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

    def _event_revision_id(self, recording_id: str, raw: Mapping[str, Any]) -> str:
        explicit = raw.get("event_revision_id")
        input_ids = raw.get("input_revision_ids")
        if explicit is not None:
            if not isinstance(explicit, str):
                raise VisibleCardPipelineInputError("event_revision_id must be a string.")
            if input_ids is not None and input_ids != [explicit]:
                raise VisibleCardPipelineInputError(
                    "event_revision_id must match the single input revision ID."
                )
            return explicit
        if input_ids is not None:
            if (
                not isinstance(input_ids, list)
                or len(input_ids) != 1
                or not isinstance(input_ids[0], str)
            ):
                raise VisibleCardPipelineInputError(
                    "visible-card detection needs one event input revision."
                )
            return input_ids[0]
        selection = self.selection_store.get(recording_id, "events")
        if selection is None:
            raise VisibleCardPipelineInputError("No selected event revision is available.")
        return (
            selection.selected_completed_reference_revision_id
            or selection.selected_generated_revision_id
            or _raise_input("No selected event revision is available.")
        )

    def _execute(self, run_id: str) -> None:
        try:
            run = self.run_store.require(run_id)
            event_revision = self.revision_store.require(run.request.input_revision_ids[0])
            if not isinstance(event_revision.content, EventData):
                raise VisibleCardPipelineError("The event input revision is invalid.")
            events = event_revision.content.events
            self.run_store.update_progress(
                run_id,
                progress=RunProgress(completed=0, total=len(events)),
            )
            outcomes: list[VisibleCardOutcome] = []
            items: list[RunItemOutcome] = []
            for event in events:
                outcome = self._process_event(run, event)
                outcomes.append(outcome)
                items.append(
                    RunItemOutcome(
                        item_id=event.event_id,
                        status="succeeded",
                        result=outcome.to_mapping(),
                        failure=None,
                    )
                )
                self.run_store.update_progress(
                    run_id,
                    progress=RunProgress(completed=len(items), total=len(events)),
                    items=tuple(items),
                )
            content = VisibleCardData(outcomes=tuple(outcomes))
            revision = self._publish_revision(run, content)
            self.run_store.complete(
                run_id,
                [revision.manifest.revision_id],
                progress=RunProgress(completed=len(items), total=len(events)),
                items=tuple(items),
            )
            self._advance_generated_selection(
                run.request.source.recording_id, revision.manifest.revision_id
            )
        except VisibleCardPipelineError as error:
            self._fail_safely(run_id, "provider_failed", str(error))
        except Exception:
            LOGGER.exception("visible_card_pipeline_worker_failed")
            self._fail_safely(run_id, "provider_failed", "The visible-card detector failed.")

    def _process_event(self, run: StoredProcessorRun, event: Any) -> VisibleCardOutcome:
        try:
            frame = resolve_exact_event(
                self._video_path(run.request.source.recording_id),
                source=run.request.source,
                requested_time_us=event.start_us,
                cache=self.storage.pipeline_root / "derived-views",
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
                error="The visible-card detector returned no result for this event.",
            )
        candidates = tuple(
            self._candidate(run, event.event_id, frame, index, proposal, result)
            for index, proposal in enumerate(result.proposals)
        )
        return VisibleCardOutcome(
            event_id=event.event_id,
            frame_identity=frame_identity,
            status="detected" if candidates else "empty",
            candidates=candidates,
            error=None,
        )

    def _propose(
        self, run: StoredProcessorRun, event_id: str, frame: ResolvedFrame
    ) -> ProviderResult:
        provider = self.detector_provider
        if provider is None:
            raise VisibleCardPipelineError("The visible-card detector is unavailable.")
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
            geometry=DetectorBoxGeometry.from_mapping(
                {
                    "kind": "detector-box/v1",
                    "box_2d": proposal.box_2d.to_mapping(),
                }
            ),
            normalization={
                "width": frame.width,
                "height": frame.height,
                "policy_id": "full-frame-0-1000/v1",
            },
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
            content_schema="visible-card-data/v1",
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
        stored, _ = self.revision_store.publish(manifest, content)
        return stored

    def _advance_generated_selection(self, recording_id: str, revision_id: str) -> None:
        current = self.selection_store.get(recording_id, "visible_cards")
        expected = 0 if current is None else current.revision
        completed = None if current is None else current.selected_completed_reference_revision_id
        try:
            self.selection_store.update_pointers(
                recording_id,
                "visible_cards",
                expected_revision=expected,
                selected_generated_revision_id=revision_id,
                selected_completed_reference_revision_id=completed,
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
        bundle = self.recording_store.get(recording_id)
        if bundle is None:
            raise PipelineNotFound(f"The recording was not found: {recording_id}")
        video_path = self._video_path(recording_id)
        if not video_path.is_file():
            raise VisibleCardPipelineInputError("The accepted recording video is unavailable.")
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
        return bundle, RecordingVideoSource(
            recording_id=recording_id,
            relative_path=relative_path,
            video_sha256=bundle.source_sha256,
            byte_length=actual_length,
            duration_us=probe.duration_ms * 1000,
        )

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


def _raise_input(message: str) -> str:
    raise VisibleCardPipelineInputError(message)


__all__ = [
    "VisibleCardPipelineError",
    "VisibleCardPipelineInputError",
    "VisibleCardPipelineProvider",
    "VisibleCardPipelineService",
]
