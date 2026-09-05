"""Execution service for video-derived visual card identity results."""

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
from typing import Any

from doko_operations.derived_view import (
    DerivedViewError,
    FrameResolver,
    resolve_exact_event,
    resolve_visible_region_crop,
)
from doko_operations.pipeline_data import (
    DataRevision,
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
    PipelineGeometry,
    VisibleCardData,
    VisualIdentityCandidate,
    VisualIdentityClassifierIdentity,
    VisualIdentityCropIdentity,
    VisualIdentityData,
    VisualIdentityOutcome,
    canonical_visual_identity_data_bytes,
)
from table_evidence_analyzer.visual_identity import (
    CardIdentityClassifierProvider,
    VisualIdentityClassifierProvider,
    VisualIdentityRequest,
)

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


class VisualIdentityPipelineError(RuntimeError):
    """The visual identity pipeline could not accept or execute a request."""


class VisualIdentityPipelineInputError(VisualIdentityPipelineError, ValueError):
    """The visual identity pipeline request is invalid."""


class VisualIdentityPipelineService:
    """Freeze visible-card inputs, classify their crops, and retain the result."""

    def __init__(
        self,
        settings: Settings,
        recording_store: RecordingBundleStore,
        repository_storage: RepositoryBundleStorage,
        *,
        identity_classifier: Any | None,
        frame_resolver: FrameResolver | None = None,
        revision_store: PipelineRevisionStore,
        run_store: ProcessorRunStore,
        selection_store: PipelineSelectionStore,
    ) -> None:
        self.settings = settings
        self.recording_store = recording_store
        self.repository_storage = repository_storage
        self.frame_resolver = frame_resolver
        self.revision_store = revision_store
        self.run_store = run_store
        self.selection_store = selection_store
        self.storage = PipelineRuntimeStorage(settings.evidence_root)
        self.classifier = self._adapt_classifier(identity_classifier)
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="visual-identity-pipeline"
        )
        self._futures: dict[str, Future[None]] = {}
        self._lock = RLock()

    async def start(self) -> None:
        """Keep the service lifecycle symmetrical with the other pipeline services."""

    async def stop(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
        with self._lock:
            self._futures.clear()

    def start_classification(
        self, recording_id: str, payload: Mapping[str, Any]
    ) -> StoredProcessorRun:
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
        return run

    def list_runs(self, recording_id: str) -> tuple[StoredProcessorRun, ...]:
        return tuple(
            run
            for run in self.run_store.list()
            if run.request.source.recording_id == recording_id
            and run.request.processor_type == "visual-card-identity"
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

    def select_generated(
        self, recording_id: str, payload: Mapping[str, Any]
    ) -> PipelineSelection:
        expected_revision = payload.get("expected_revision")
        selected = payload.get("selected_generated_revision_id")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise VisualIdentityPipelineInputError(
                "expected_revision must be a non-negative integer."
            )
        if selected is not None and not isinstance(selected, str):
            raise VisualIdentityPipelineInputError(
                "selected_generated_revision_id must be a string or null."
            )
        current = self.selection_store.get(recording_id, "visual_identities")
        completed = None if current is None else current.selected_completed_reference_revision_id
        try:
            return self.selection_store.update_pointers(
                recording_id,
                "visual_identities",
                expected_revision=expected_revision,
                selected_generated_revision_id=selected,
                selected_completed_reference_revision_id=completed,
            )
        except PipelineSelectionConflict:
            raise
        except (PipelineNotFound, PipelineStateError) as error:
            raise VisualIdentityPipelineInputError(str(error)) from error

    def _build_request(
        self, recording_id: str, payload: Mapping[str, Any]
    ) -> ProcessorRunRequest:
        if not isinstance(payload, Mapping):
            raise VisualIdentityPipelineInputError("The processor request must be an object.")
        if self.classifier is None:
            raise VisualIdentityPipelineInputError(
                "The visual card identity classifier is unavailable."
            )
        raw = payload.get("request", payload)
        if not isinstance(raw, Mapping):
            raise VisualIdentityPipelineInputError("request must be an object.")
        _, source = self._accepted_source(recording_id)
        visible_revision_id = self._visible_revision_id(recording_id, raw)
        visible_revision = self.revision_store.require(visible_revision_id)
        if (
            visible_revision.manifest.content_type != "visible_cards"
            or visible_revision.manifest.source != source
            or not isinstance(visible_revision.content, VisibleCardData)
        ):
            raise VisualIdentityPipelineInputError(
                "The selected visible-card revision does not match the accepted recording video."
            )
        values = dict(raw)
        values.pop("visible_card_revision_id", None)
        values.setdefault("schema_version", "processor-run-request/v1")
        values.setdefault("run_id", payload.get("run_id"))
        if not values.get("run_id"):
            raise VisualIdentityPipelineInputError("run_id is required.")
        values.setdefault("processor_type", "visual-card-identity")
        values.setdefault("source", source.to_mapping())
        values["input_revision_ids"] = [visible_revision_id]
        values.setdefault(
            "implementation",
            {"name": "visual-identity-classifier-adapter", "version": "v1"},
        )
        values.setdefault(
            "model",
            {"name": self.classifier.model, "version": self.classifier.version},
        )
        configuration = values.get("configuration", {})
        if not isinstance(configuration, Mapping):
            raise VisualIdentityPipelineInputError("configuration must be an object.")
        configuration = dict(configuration)
        configured_provider = configuration.get("provider", self.classifier.name)
        if configured_provider != self.classifier.name:
            raise VisualIdentityPipelineInputError(
                "The requested identity provider is not the configured provider."
            )
        configuration.setdefault("provider", self.classifier.name)
        configuration.setdefault(
            "classifier", {"name": self.classifier.name, "version": self.classifier.version}
        )
        values["configuration"] = configuration
        values.setdefault("extraction_policy", {"policy_id": "exact-event/v1"})
        values.setdefault(
            "crop_policy",
            {"policy_id": "raw_rectangular", "output_encoding": "ppm"},
        )
        try:
            request = ProcessorRunRequest.from_mapping(values)
        except (TypeError, ValueError) as error:
            raise VisualIdentityPipelineInputError(
                "The visual identity processor request failed validation."
            ) from error
        if request.source != source:
            raise VisualIdentityPipelineInputError(
                "The request source does not match the accepted recording video."
            )
        if request.processor_type != "visual-card-identity":
            raise VisualIdentityPipelineInputError(
                "The visual identity endpoint only accepts visual-card-identity runs."
            )
        if request.model is None or request.model.name != self.classifier.model:
            raise VisualIdentityPipelineInputError(
                "The request model does not match the configured classifier."
            )
        if request.configuration.get("classifier") != {
            "name": self.classifier.name,
            "version": self.classifier.version,
        }:
            raise VisualIdentityPipelineInputError(
                "The request classifier identity does not match the configured classifier."
            )
        return request

    def _visible_revision_id(self, recording_id: str, raw: Mapping[str, Any]) -> str:
        explicit = raw.get("visible_card_revision_id")
        input_ids = raw.get("input_revision_ids")
        if explicit is not None:
            if not isinstance(explicit, str):
                raise VisualIdentityPipelineInputError(
                    "visible_card_revision_id must be a string."
                )
            if input_ids is not None and input_ids != [explicit]:
                raise VisualIdentityPipelineInputError(
                    "visible_card_revision_id must match the single input revision ID."
                )
            return explicit
        if input_ids is not None:
            if (
                not isinstance(input_ids, list)
                or len(input_ids) != 1
                or not isinstance(input_ids[0], str)
            ):
                raise VisualIdentityPipelineInputError(
                    "visual identity classification needs one visible-card input revision."
                )
            return input_ids[0]
        selection = self.selection_store.get(recording_id, "visible_cards")
        if selection is None:
            raise VisualIdentityPipelineInputError(
                "No selected visible-card revision is available."
            )
        return (
            selection.selected_completed_reference_revision_id
            or selection.selected_generated_revision_id
            or _raise_input("No selected visible-card revision is available.")
        )

    def _execute(self, run_id: str) -> None:
        try:
            run = self.run_store.require(run_id)
            visible_revision = self.revision_store.require(run.request.input_revision_ids[0])
            if not isinstance(visible_revision.content, VisibleCardData):
                raise VisualIdentityPipelineError("The visible-card input revision is invalid.")
            candidates = [
                (outcome, candidate)
                for outcome in visible_revision.content.outcomes
                if outcome.status == "detected"
                for candidate in outcome.candidates
            ]
            self.run_store.update_progress(
                run_id,
                progress=RunProgress(completed=0, total=len(candidates)),
            )
            outcomes: list[VisualIdentityOutcome] = []
            items: list[RunItemOutcome] = []
            for outcome, candidate in candidates:
                result = self._process_card(run, outcome, candidate)
                outcomes.append(result)
                items.append(
                    RunItemOutcome(
                        item_id=candidate.card_id,
                        status="succeeded",
                        result=result.to_mapping(),
                        failure=None,
                    )
                )
                self.run_store.update_progress(
                    run_id,
                    progress=RunProgress(completed=len(items), total=len(candidates)),
                    items=tuple(items),
                )
            content = VisualIdentityData(outcomes=tuple(outcomes))
            revision = self._publish_revision(run, content)
            self.run_store.complete(
                run_id,
                [revision.manifest.revision_id],
                progress=RunProgress(completed=len(items), total=len(candidates)),
                items=tuple(items),
            )
            self._advance_generated_selection(
                run.request.source.recording_id, revision.manifest.revision_id
            )
        except VisualIdentityPipelineError as error:
            self._fail_safely(run_id, "classifier_failed", str(error))
        except Exception:
            LOGGER.exception("visual_identity_pipeline_worker_failed")
            self._fail_safely(run_id, "classifier_failed", "The visual identity classifier failed.")

    def _process_card(
        self, run: StoredProcessorRun, visible_outcome: Any, card: Any
    ) -> VisualIdentityOutcome:
        assert visible_outcome.frame_identity is not None
        frame_identity = visible_outcome.frame_identity
        geometry: PipelineGeometry = card.geometry
        classifier_identity = self._classifier_identity(run.request)
        frame = None
        try:
            frame = resolve_exact_event(
                self._video_path(run.request.source.recording_id),
                source=run.request.source,
                requested_time_us=frame_identity.requested_time_us,
                cache=self.storage.pipeline_root / "derived-views",
                resolver=self.frame_resolver,
                output_encoding=frame_identity.output_encoding,
            )
            if frame.identity_mapping() != frame_identity.to_mapping():
                raise DerivedViewError("the resolved frame identity changed")
        except (DerivedViewError, OSError, RuntimeError):
            return VisualIdentityOutcome(
                card_id=card.card_id,
                frame_identity=frame_identity,
                geometry=geometry,
                crop_identity=None,
                classifier=classifier_identity,
                status="failed",
                candidates=(),
                error="The exact visible-card frame is unavailable.",
            )

        try:
            crop_policy = run.request.crop_policy or {}
            crop = resolve_visible_region_crop(
                frame,
                geometry.to_mapping(),
                crop_policy=str(crop_policy.get("policy_id", "raw_rectangular")),
                output_encoding=str(crop_policy.get("output_encoding", "ppm")),
                cache=self.storage.pipeline_root / "derived-views",
            )
            crop_identity = VisualIdentityCropIdentity.from_mapping(crop.identity_mapping())
        except (DerivedViewError, OSError, RuntimeError, ValueError):
            return VisualIdentityOutcome(
                card_id=card.card_id,
                frame_identity=frame_identity,
                geometry=geometry,
                crop_identity=None,
                classifier=classifier_identity,
                status="failed",
                candidates=(),
                error="The visible-card identity crop is unavailable.",
            )
        if crop.status == "unusable":
            return VisualIdentityOutcome(
                card_id=card.card_id,
                frame_identity=frame_identity,
                geometry=geometry,
                crop_identity=crop_identity,
                classifier=classifier_identity,
                status="unusable",
                candidates=(),
                unusable_reason=crop.unusable_reason,
            )
        try:
            assert crop.image_bytes is not None
            request = VisualIdentityRequest(
                card_id=card.card_id,
                provider=self.classifier.name if self.classifier is not None else "unknown",
                model=run.request.model.name if run.request.model is not None else "unknown",
                crop_bytes=crop.image_bytes,
            )
            result = self.classifier.classify(request) if self.classifier is not None else None
            if result is None or result.status != "ok":
                raise VisualIdentityPipelineError(
                    "The visual identity classifier returned no result."
                )
            candidates = tuple(
                VisualIdentityCandidate(
                    identity=identity.card,
                    score=identity.probability,
                    score_meaning="probability",
                    producer_id=_model_id(run.request.model)
                    or _implementation_id(run.request.implementation),
                )
                for identity in result.candidates
            )
        except Exception:
            return VisualIdentityOutcome(
                card_id=card.card_id,
                frame_identity=frame_identity,
                geometry=geometry,
                crop_identity=crop_identity,
                classifier=classifier_identity,
                status="failed",
                candidates=(),
                error="The visual identity classifier failed for this card.",
            )
        return VisualIdentityOutcome(
            card_id=card.card_id,
            frame_identity=frame_identity,
            geometry=geometry,
            crop_identity=crop_identity,
            classifier=classifier_identity,
            status="classified",
            candidates=candidates,
        )

    def _classifier_identity(
        self, request: ProcessorRunRequest
    ) -> VisualIdentityClassifierIdentity:
        model = request.model
        if model is None or self.classifier is None:
            raise VisualIdentityPipelineError("The visual identity classifier identity is missing.")
        return VisualIdentityClassifierIdentity(
            provider=self.classifier.name,
            implementation_name=request.implementation.name,
            implementation_version=request.implementation.version,
            model_name=model.name,
            model_version=model.version,
        )

    def _publish_revision(
        self, run: StoredProcessorRun, content: VisualIdentityData
    ) -> StoredPipelineRevision:
        producer = ProcessorProducer(
            run_id=run.run_id,
            processor_type=run.request.processor_type,
            implementation_id=_implementation_id(run.request.implementation),
            model_id=_model_id(run.request.model),
        )
        manifest = DataRevision(
            revision_id=f"visual-identities-{_safe(run.run_id)}-attempt-{run.state.attempt}",
            content_type="visual_identities",
            content_schema="visual-identity-data/v1",
            recording_id=run.request.source.recording_id,
            source=run.request.source,
            content_sha256=sha256_bytes(canonical_visual_identity_data_bytes(content)),
            input_revision_ids=run.request.input_revision_ids,
            origin="processor",
            producer=producer,
            coverage={
                "kind": "requested-visible-cards",
                "visible_card_revision_id": run.request.input_revision_ids[0],
                "card_ids": [outcome.card_id for outcome in content.outcomes],
                "policy_id": run.request.crop_policy["policy_id"]
                if run.request.crop_policy is not None
                else "raw_rectangular",
            },
            created_at=_now(),
        )
        stored, _ = self.revision_store.publish(manifest, content)
        return stored

    def _advance_generated_selection(self, recording_id: str, revision_id: str) -> None:
        current = self.selection_store.get(recording_id, "visual_identities")
        expected = 0 if current is None else current.revision
        completed = None if current is None else current.selected_completed_reference_revision_id
        try:
            self.selection_store.update_pointers(
                recording_id,
                "visual_identities",
                expected_revision=expected,
                selected_generated_revision_id=revision_id,
                selected_completed_reference_revision_id=completed,
            )
        except PipelineSelectionConflict:
            LOGGER.warning(
                "visual_identity_pipeline_selection_advance_conflict",
                extra={"recording_id": recording_id},
            )

    def _fail_safely(self, run_id: str, code: str, message: str) -> None:
        try:
            run = self.run_store.get(run_id)
            if run is not None and run.state.status == "running":
                self.run_store.fail(run_id, RunFailure(code=code, message=message))
        except Exception:
            LOGGER.exception("visual_identity_pipeline_failure_persist_failed")

    def _accepted_source(self, recording_id: str) -> tuple[Any, RecordingVideoSource]:
        bundle = self.recording_store.get(recording_id)
        if bundle is None:
            raise PipelineNotFound(f"The recording was not found: {recording_id}")
        video_path = self._video_path(recording_id)
        if not video_path.is_file():
            raise VisualIdentityPipelineInputError("The accepted recording video is unavailable.")
        actual_length, actual_digest = _file_identity(video_path)
        if actual_length != bundle.video_byte_length or actual_digest != bundle.source_sha256:
            raise VisualIdentityPipelineInputError(
                "The accepted recording video does not match its manifest."
            )
        try:
            from dokodetector_backend.video_probe import probe_video_path_metadata

            probe = probe_video_path_metadata(video_path)
        except Exception as error:
            raise VisualIdentityPipelineInputError(
                "The accepted recording video could not be probed."
            ) from error
        try:
            relative_path = (
                video_path.resolve().relative_to(self.settings.repository_root).as_posix()
            )
        except ValueError as error:
            raise VisualIdentityPipelineInputError(
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
            raise VisualIdentityPipelineInputError(
                "The accepted recording manifest is invalid."
            ) from error
        path = self.repository_storage.bundle_path(recording_id) / str(relative_path)
        try:
            path.resolve().relative_to(self.repository_storage.bundle_path(recording_id).resolve())
        except ValueError as error:
            raise VisualIdentityPipelineInputError(
                "The accepted recording video path is invalid."
            ) from error
        return path

    @staticmethod
    def _require_recording(request: ProcessorRunRequest, recording_id: str) -> None:
        if request.source.recording_id != recording_id:
            raise PipelineNotFound(f"The processor run was not found for recording: {recording_id}")

    @staticmethod
    def _adapt_classifier(classifier: Any | None) -> VisualIdentityClassifierProvider | None:
        if classifier is None:
            return None
        if isinstance(classifier, VisualIdentityClassifierProvider):
            return classifier
        return CardIdentityClassifierProvider(classifier)


def _implementation_id(identity: Any) -> str:
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
    raise VisualIdentityPipelineInputError(message)


__all__ = [
    "VisualIdentityPipelineError",
    "VisualIdentityPipelineInputError",
    "VisualIdentityPipelineService",
]
