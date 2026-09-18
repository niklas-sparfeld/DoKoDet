"""Execution service for video-derived visual card identity results."""

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
from threading import RLock
from typing import Any

from doko_operations.derived_view import (
    DerivedViewError,
    FFmpegFrameResolver,
    FrameResolver,
    ResolvedCrop,
    ResolvedCropJpegPreview,
    parse_geometry,
    resolve_crop_jpeg_preview,
    resolve_crop_jpeg_preview_from_cache,
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
    DetectorBoxGeometry,
    PipelineGeometry,
    PredictedVisibleRegionGeometry,
    ReviewedVisibleRegionGeometry,
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
from dokodetector_backend.derived_view_cache import DERIVED_VIEW_CACHE_LOCK
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


def _result_latency_ms(result: Any) -> float | None:
    value = getattr(result, "latency_ms", None)
    return float(value) if isinstance(value, (int, float)) else None


def _default_crop_policy_for_geometry(geometry: PipelineGeometry) -> dict[str, str]:
    """Return the polygon crop policy that matches one visible-region geometry."""

    if isinstance(geometry, DetectorBoxGeometry):
        return {"policy_id": "raw_rectangular", "output_encoding": "ppm"}
    if isinstance(geometry, PredictedVisibleRegionGeometry):
        return {"policy_id": "predicted_visible_region", "output_encoding": "ppm"}
    if isinstance(geometry, ReviewedVisibleRegionGeometry):
        return {"policy_id": "oracle_visible_region", "output_encoding": "ppm"}
    raise VisualIdentityPipelineInputError(
        "the default visual identity crop policy requires polygon visible-region geometry"
    )


def _default_crop_policy(content: VisibleCardData) -> dict[str, str]:
    """Return the default crop policy for one visible-card revision."""

    geometries = [
        candidate.geometry for outcome in content.outcomes for candidate in outcome.candidates
    ]
    if not geometries:
        return {"policy_id": "predicted_visible_region", "output_encoding": "ppm"}
    policies = {_default_crop_policy_for_geometry(geometry)["policy_id"] for geometry in geometries}
    if len(policies) == 1:
        return {"policy_id": policies.pop(), "output_encoding": "ppm"}
    # A maintained visible-card reference can contain generated geometry for accepted
    # suggestions and reviewed geometry for corrected cards.  The item-level resolver below
    # selects the matching policy for each geometry in that mixed revision.
    return {"policy_id": "predicted_visible_region", "output_encoding": "ppm"}


def _crop_policy_for_geometry(policy_id: str, geometry: PipelineGeometry) -> str:
    """Resolve an origin-level polygon policy against one card's actual geometry."""

    if policy_id in {"predicted_visible_region", "oracle_visible_region"}:
        return _default_crop_policy_for_geometry(geometry)["policy_id"]
    return policy_id


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
        identity_classifiers: Mapping[str, Any] | None = None,
        frame_resolver: FrameResolver | None = None,
        revision_store: PipelineRevisionStore,
        run_store: ProcessorRunStore,
        selection_store: PipelineSelectionStore,
    ) -> None:
        self.settings = settings
        self.recording_store = recording_store
        self.repository_storage = repository_storage
        self.frame_resolver = (
            frame_resolver if frame_resolver is not None else FFmpegFrameResolver()
        )
        self.revision_store = revision_store
        self.run_store = run_store
        self.selection_store = selection_store
        self.identity_classifiers = identity_classifiers
        self.storage = PipelineRuntimeStorage(settings.evidence_root, settings.operations_root)
        self.cloud_max_concurrent_requests = getattr(settings, "gemini_max_concurrent_requests", 4)
        self.local_max_concurrent_requests = getattr(
            settings, "visible_card_identity_max_concurrent_requests", 1
        )
        if (
            isinstance(self.cloud_max_concurrent_requests, bool)
            or self.cloud_max_concurrent_requests < 1
            or isinstance(self.local_max_concurrent_requests, bool)
            or self.local_max_concurrent_requests < 1
        ):
            raise ValueError("identity processor concurrency settings must be positive integers")
        self._derived_view_lock = DERIVED_VIEW_CACHE_LOCK
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
            and run.request.processor_type == "visual-card-identity"
        )

    def plan_auto_approval(
        self,
        recording_id: str,
        source_revision_id: str,
        draft_items: tuple[Mapping[str, Any], ...],
    ) -> dict[str, Any]:
        """Compare retained Cloud and local outcomes for one identity draft.

        This method deliberately only plans work.  A later revision-guarded review command
        applies the accepted decisions, so a plan can never overwrite an operator decision.
        """

        source = self.revision_store.require(source_revision_id)
        if (
            source.manifest.content_type != "visual_identities"
            or source.manifest.source.recording_id != recording_id
            or not isinstance(source.content, VisualIdentityData)
        ):
            raise VisualIdentityPipelineInputError("The identity draft source is unavailable.")
        cloud_run = self._run_for_output(source_revision_id)
        if cloud_run is None or cloud_run.request.input_revision_ids == ():
            raise VisualIdentityPipelineInputError(
                "The identity draft has no retained processor lineage."
            )
        visible_revision_id = cloud_run.request.input_revision_ids[0]
        cloud_outcomes = {
            outcome.card_id: outcome
            for outcome in source.content.outcomes
            if outcome.classifier.provider == "gemini"
        }
        local_results = self._retained_local_results(recording_id, visible_revision_id)
        items: list[dict[str, Any]] = []
        needs_local = False
        for draft_item in draft_items:
            item_id = draft_item.get("item_id")
            item = draft_item.get("item")
            state = draft_item.get("review_state")
            if not isinstance(item_id, str) or not isinstance(item, Mapping):
                continue
            cloud = cloud_outcomes.get(item_id)
            local = None if cloud is None else local_results.get(self._outcome_key(cloud))
            reason = self._auto_approval_reason(state, cloud, local)
            if cloud is not None and local is None:
                needs_local = True
            items.append(
                {
                    "item_id": item_id,
                    "reason": reason,
                    "eligible": reason == "eligible",
                    "gemini_result": self._result_provenance(source_revision_id, cloud),
                    "local_result": None if local is None else self._result_provenance(*local),
                }
            )
        local_run = None
        if needs_local:
            local_run = self._start_or_reuse_auto_approval_local_run(
                recording_id, visible_revision_id, cloud_run.request
            )
        return {
            "source_revision_id": source_revision_id,
            "local_run": (
                None
                if local_run is None
                else {
                    "run_id": local_run.run_id,
                    "status": local_run.state.status,
                    "attempt": local_run.state.attempt,
                }
            ),
            "items": items,
        }

    def _run_for_output(self, revision_id: str) -> StoredProcessorRun | None:
        matches = [
            run for run in self.run_store.list() if revision_id in run.state.output_revision_ids
        ]
        return max(
            matches, key=lambda run: (run.state.completed_at or "", run.run_id), default=None
        )

    def _retained_local_results(
        self, recording_id: str, visible_revision_id: str
    ) -> dict[tuple[Any, ...], tuple[str, VisualIdentityOutcome]]:
        selected: dict[tuple[Any, ...], tuple[str, VisualIdentityOutcome, str]] = {}
        for run in self.list_runs(recording_id):
            if (
                run.state.status != "complete"
                or run.request.input_revision_ids != (visible_revision_id,)
                or not str(run.request.configuration.get("provider", "")).startswith("local")
            ):
                continue
            for revision_id in run.state.output_revision_ids:
                revision = self.revision_store.require(revision_id)
                if not isinstance(revision.content, VisualIdentityData):
                    continue
                for outcome in revision.content.outcomes:
                    key = self._outcome_key(outcome)
                    candidate = (revision_id, outcome, run.state.completed_at or "")
                    current = selected.get(key)
                    if current is None or (candidate[2], revision_id) > (current[2], current[0]):
                        selected[key] = candidate
        return {key: (value[0], value[1]) for key, value in selected.items()}

    @staticmethod
    def _outcome_key(outcome: VisualIdentityOutcome) -> tuple[Any, ...]:
        return (
            outcome.card_id,
            json.dumps(outcome.frame_identity.to_mapping(), sort_keys=True),
            json.dumps(outcome.geometry.to_mapping(), sort_keys=True),
            None
            if outcome.crop_identity is None
            else json.dumps(outcome.crop_identity.to_mapping(), sort_keys=True),
        )

    @staticmethod
    def _result_provenance(
        revision_id: str, outcome: VisualIdentityOutcome | None
    ) -> dict[str, Any] | None:
        if outcome is None:
            return None
        return {"result_id": revision_id, "classifier": outcome.classifier.to_mapping()}

    @staticmethod
    def _auto_approval_reason(
        state: Any,
        cloud: VisualIdentityOutcome | None,
        local: tuple[str, VisualIdentityOutcome] | None,
    ) -> str:
        if state != "pending":
            return "already_reviewed"
        if cloud is None:
            return "gemini_unavailable"
        if cloud.status == "face_down":
            return "gemini_face_down"
        if cloud.status == "unusable":
            return "gemini_unusable"
        if cloud.status == "failed":
            return "gemini_failed"
        if cloud.status != "classified" or not cloud.candidates:
            return "gemini_unavailable"
        if local is None:
            return "local_unavailable"
        local_outcome = local[1]
        if local_outcome.status == "face_down":
            return "local_face_down"
        if local_outcome.status == "unusable":
            return "local_unusable"
        if local_outcome.status == "failed":
            return "local_failed"
        if local_outcome.status != "classified" or not local_outcome.candidates:
            return "local_unavailable"
        if cloud.candidates[0].identity != local_outcome.candidates[0].identity:
            return "identity_mismatch"
        return "eligible"

    def _start_or_reuse_auto_approval_local_run(
        self, recording_id: str, visible_revision_id: str, cloud_request: ProcessorRunRequest
    ) -> StoredProcessorRun:
        token = sha256_bytes(
            json.dumps(
                {
                    "recording_id": recording_id,
                    "visible_revision_id": visible_revision_id,
                    "crop_policy": cloud_request.crop_policy,
                },
                sort_keys=True,
            ).encode("utf-8")
        )[:20]
        return self.start_classification(
            recording_id,
            {
                "run_id": f"auto-approve-local-{token}",
                "visible_card_revision_id": visible_revision_id,
                "configuration": {"provider": "local"},
                "crop_policy": cloud_request.crop_policy,
                "extraction_policy": cloud_request.extraction_policy,
            },
        )

    def get_result(
        self, recording_id: str, run_id: str
    ) -> tuple[StoredProcessorRun, tuple[StoredPipelineRevision, ...]]:
        run = self.get_run(recording_id, run_id)
        revisions = tuple(
            self.revision_store.require(item) for item in run.state.output_revision_ids
        )
        return run, revisions

    def get_identity_crop_identity(
        self, recording_id: str, revision_id: str, item_id: str
    ) -> VisualIdentityCropIdentity:
        """Validate one stored identity crop without resolving its source image."""

        bundle = self.recording_store.get_metadata(recording_id)
        if bundle is None:
            raise PipelineNotFound(f"The recording was not found: {recording_id}")
        revision = self._require_identity_revision(recording_id, revision_id)
        source = revision.manifest.source
        if (
            source.recording_id != recording_id
            or source.video_sha256 != bundle.source_sha256
            or source.byte_length != bundle.video_byte_length
        ):
            raise VisualIdentityPipelineInputError(
                "The selected visual identity revision does not match the accepted recording video."
            )
        outcome = self._require_identity_outcome(revision, item_id)
        crop = outcome.crop_identity
        if crop is None or crop.status != "usable" or crop.image_sha256 is None:
            raise DerivedViewError("The identity crop is unavailable.")
        return crop

    def resolve_identity_crop(
        self, recording_id: str, revision_id: str, item_id: str
    ) -> ResolvedCrop:
        """Resolve one identity crop from an immutable identity revision."""

        _, source = self._accepted_source(recording_id)
        revision = self._require_identity_revision(recording_id, revision_id, source=source)
        outcome = self._require_identity_outcome(revision, item_id)
        if outcome.crop_identity is None or outcome.crop_identity.status != "usable":
            raise DerivedViewError("The identity crop is unavailable.")
        with self._derived_view_lock:
            frame = resolve_exact_event(
                self._video_path(recording_id),
                source=source,
                requested_time_us=outcome.frame_identity.requested_time_us,
                cache=self.storage.derived_views_root,
                resolver=self.frame_resolver,
                output_encoding=outcome.frame_identity.output_encoding,
            )
        if frame.identity_mapping() != outcome.frame_identity.to_mapping():
            raise DerivedViewError("the resolved identity frame changed")
        with self._derived_view_lock:
            crop = resolve_visible_region_crop(
                frame,
                parse_geometry(outcome.geometry.to_mapping()),
                crop_policy=outcome.crop_identity.crop_policy,
                output_encoding=outcome.crop_identity.output_encoding,
                cache=self.storage.derived_views_root,
            )
        if _pipeline_crop_identity_mapping(crop) != outcome.crop_identity.to_mapping():
            raise DerivedViewError("the resolved identity crop changed")
        return crop

    def resolve_identity_crop_browser_preview(
        self,
        recording_id: str,
        revision_id: str,
        item_id: str,
        source_crop_sha256: str,
    ) -> ResolvedCropJpegPreview:
        """Resolve and cache one browser preview after a digest-only cache miss."""

        with self._derived_view_lock:
            cached = resolve_crop_jpeg_preview_from_cache(
                source_crop_sha256,
                cache=self.storage.derived_views_root,
            )
            if cached is not None:
                return cached
            crop = self.resolve_identity_crop(recording_id, revision_id, item_id)
            if crop.image_sha256 != source_crop_sha256:
                raise DerivedViewError("the resolved identity crop changed")
            return resolve_crop_jpeg_preview(
                crop,
                cache=self.storage.derived_views_root,
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

    def _build_request(self, recording_id: str, payload: Mapping[str, Any]) -> ProcessorRunRequest:
        if not isinstance(payload, Mapping):
            raise VisualIdentityPipelineInputError("The processor request must be an object.")
        if self.classifier is None and not self.identity_classifiers:
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
        configuration = values.get("configuration", {})
        if not isinstance(configuration, Mapping):
            raise VisualIdentityPipelineInputError("configuration must be an object.")
        configuration = dict(configuration)
        requested_provider = configuration_provider(configuration)
        classifier = self._classifier_for_selection(requested_provider)
        if classifier is None:
            raise VisualIdentityPipelineInputError(
                "The requested visual identity processor is unavailable."
            )
        configuration["provider"] = classifier.name
        configuration["classifier"] = {"name": classifier.name, "version": classifier.version}
        values["configuration"] = configuration
        if values.get("model") is None or requested_provider is not None:
            values["model"] = {"name": classifier.model, "version": classifier.version}
        values.setdefault("extraction_policy", {"policy_id": "exact-event/v1"})
        if values.get("crop_policy") is None:
            values["crop_policy"] = _default_crop_policy(visible_revision.content)
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
        if request.model is None or request.model.name != classifier.model:
            raise VisualIdentityPipelineInputError(
                "The request model does not match the configured classifier."
            )
        if request.configuration.get("classifier") != {
            "name": classifier.name,
            "version": classifier.version,
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
                raise VisualIdentityPipelineInputError("visible_card_revision_id must be a string.")
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
            outcomes_by_index: list[VisualIdentityOutcome | None] = [None] * len(candidates)
            prior_items = {item.item_id: item for item in run.state.items}
            candidate_ids = {candidate.card_id for _, candidate in candidates}
            if not set(prior_items).issubset(candidate_ids):
                raise VisualIdentityPipelineError(
                    "The retry contains an item that is not in the frozen card input."
                )
            items_by_index: list[RunItemOutcome | None] = [
                prior_items.get(candidate.card_id) for _, candidate in candidates
            ]
            pending_candidates: list[tuple[int, Any, Any]] = []
            completed = 0
            for index, (visible_outcome, candidate) in enumerate(candidates):
                item = items_by_index[index]
                if item is None or item.status != "succeeded":
                    pending_candidates.append((index, visible_outcome, candidate))
                    continue
                if item.result is None:
                    raise VisualIdentityPipelineError(
                        f"The retained outcome for card {candidate.card_id} is invalid."
                    )
                try:
                    result = VisualIdentityOutcome.from_mapping(item.result)
                except ValueError as error:
                    raise VisualIdentityPipelineError(
                        f"The retained outcome for card {candidate.card_id} is invalid."
                    ) from error
                if result.card_id != candidate.card_id:
                    raise VisualIdentityPipelineError(
                        f"The retained outcome for card {candidate.card_id} has the wrong ID."
                    )
                outcomes_by_index[index] = result
                completed += 1
            self.run_store.update_progress(
                run_id,
                progress=RunProgress(completed=completed, total=len(candidates)),
            )
            with ThreadPoolExecutor(
                max_workers=self._max_concurrent_requests(run.request),
                thread_name_prefix="visual-identity-card",
            ) as executor:
                futures: dict[Future[VisualIdentityOutcome], int] = {
                    executor.submit(self._process_card_timed, run, outcome, candidate): index
                    for index, outcome, candidate in pending_candidates
                }
                for future in as_completed(futures):
                    index = futures[future]
                    outcome, candidate = candidates[index]
                    try:
                        result = future.result()
                    except Exception:
                        LOGGER.exception(
                            "visual_identity_card_failed",
                            extra={"run_id": run.run_id, "card_id": candidate.card_id},
                        )
                        result = VisualIdentityOutcome(
                            card_id=candidate.card_id,
                            frame_identity=outcome.frame_identity,
                            geometry=candidate.geometry,
                            crop_identity=None,
                            classifier=self._classifier_identity(run.request),
                            status="failed",
                            candidates=(),
                            error="The visual identity classifier failed for this card.",
                    )
                    outcomes_by_index[index] = result
                    item = RunItemOutcome(
                        item_id=candidate.card_id,
                        status="succeeded",
                        result=result.to_mapping(),
                        failure=None,
                    )
                    items_by_index[index] = item
                    completed += 1
                    self.run_store.record_item_progress(
                        run_id,
                        progress=RunProgress(completed=completed, total=len(candidates)),
                        item=item,
                    )

            outcomes = [outcome for outcome in outcomes_by_index if outcome is not None]
            items = tuple(item for item in items_by_index if item is not None)
            if len(outcomes) != len(candidates) or len(items) != len(candidates):
                raise VisualIdentityPipelineError(
                    "The visual identity classifier did not process all cards."
                )
            content = VisualIdentityData(outcomes=tuple(outcomes))
            revision = self._publish_revision(run, content)
            self.run_store.complete(
                run_id,
                [revision.manifest.revision_id],
                progress=RunProgress(completed=len(items), total=len(candidates)),
                items=items,
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
        self,
        run: StoredProcessorRun,
        visible_outcome: Any,
        card: Any,
        *,
        timings: dict[str, float | None] | None = None,
    ) -> VisualIdentityOutcome:
        assert visible_outcome.frame_identity is not None
        frame_identity = visible_outcome.frame_identity
        geometry: PipelineGeometry = card.geometry
        classifier_identity = self._classifier_identity(run.request)
        frame = None
        try:
            started = time.monotonic()
            with self._derived_view_lock:
                frame = resolve_exact_event(
                    self._video_path(run.request.source.recording_id),
                    source=run.request.source,
                    requested_time_us=frame_identity.requested_time_us,
                    cache=self.storage.derived_views_root,
                    resolver=self.frame_resolver,
                    output_encoding=frame_identity.output_encoding,
                    # The accepted source was hashed when the run request was built. Avoid
                    # hashing the complete video again for every card.
                    validate_source=False,
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
        finally:
            if timings is not None:
                timings["frame_resolve_ms"] = round(
                    max(0.0, time.monotonic() - started) * 1000.0, 3
                )

        try:
            started = time.monotonic()
            crop_policy = run.request.crop_policy or {}
            crop_policy_id = crop_policy.get("policy_id")
            if crop_policy_id is None:
                crop_policy_id = _default_crop_policy_for_geometry(geometry)["policy_id"]
            crop_policy_id = _crop_policy_for_geometry(str(crop_policy_id), geometry)
            with self._derived_view_lock:
                crop = resolve_visible_region_crop(
                    frame,
                    geometry.to_mapping(),
                    crop_policy=str(crop_policy_id),
                    output_encoding=str(crop_policy.get("output_encoding", "ppm")),
                    cache=self.storage.derived_views_root,
                )
            crop_identity = VisualIdentityCropIdentity.from_mapping(
                _pipeline_crop_identity_mapping(crop)
            )
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
        finally:
            if timings is not None:
                timings["crop_ms"] = round(max(0.0, time.monotonic() - started) * 1000.0, 3)
        if card.side == "face_down":
            return VisualIdentityOutcome(
                card_id=card.card_id,
                frame_identity=frame_identity,
                geometry=geometry,
                crop_identity=crop_identity,
                classifier=classifier_identity,
                status="face_down",
                candidates=(),
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
        classifier_started: float | None = None
        try:
            assert crop.image_bytes is not None
            classifier = self._classifier_for_request(run.request)
            if classifier is None:
                raise VisualIdentityPipelineError("The visual identity classifier is unavailable.")
            request = VisualIdentityRequest(
                card_id=card.card_id,
                provider=classifier.name,
                model=run.request.model.name if run.request.model is not None else "unknown",
                crop_bytes=crop.image_bytes,
            )
            classifier_started = time.monotonic()
            result = classifier.classify(request)
            if timings is not None:
                timings["classifier_latency_ms"] = _result_latency_ms(result)
            if result.status == "unavailable":
                return VisualIdentityOutcome(
                    card_id=card.card_id,
                    frame_identity=frame_identity,
                    geometry=geometry,
                    crop_identity=crop_identity,
                    classifier=classifier_identity,
                    status="failed",
                    candidates=(),
                    error=result.error or "The visual identity classifier failed for this card.",
                )
            if result.classification == "face_down":
                return VisualIdentityOutcome(
                    card_id=card.card_id,
                    frame_identity=frame_identity,
                    geometry=geometry,
                    crop_identity=crop_identity,
                    classifier=classifier_identity,
                    status="face_down",
                    candidates=(),
                )
            if result.classification == "unknown" or not result.candidates:
                return VisualIdentityOutcome(
                    card_id=card.card_id,
                    frame_identity=frame_identity,
                    geometry=geometry,
                    crop_identity=crop_identity,
                    classifier=classifier_identity,
                    status="unusable",
                    candidates=(),
                    unusable_reason="The classifier returned no identity candidates.",
                )
            if result.classification != "identity":
                raise VisualIdentityPipelineError(
                    "The visual identity classifier returned an unsupported classification."
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
        finally:
            if timings is not None and classifier_started is not None:
                timings["classifier_wall_time_ms"] = round(
                    max(0.0, time.monotonic() - classifier_started) * 1000.0, 3
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

    def _process_card_timed(
        self, run: StoredProcessorRun, visible_outcome: Any, card: Any
    ) -> VisualIdentityOutcome:
        started = time.monotonic()
        timings: dict[str, float | None] = {}
        try:
            return self._process_card(run, visible_outcome, card, timings=timings)
        finally:
            LOGGER.info(
                "visual_identity_card_timing",
                extra={
                    "event_name": "visual_identity_card_timing",
                    "run_id": run.run_id,
                    "card_id": card.card_id,
                    "item_wall_time_ms": round(max(0.0, time.monotonic() - started) * 1000.0, 3),
                    **timings,
                    "timing_scope": (
                        "wall-clock item timing with derived-view and classifier stages"
                    ),
                },
            )

    def _max_concurrent_requests(self, request: ProcessorRunRequest) -> int:
        classifier = self._classifier_for_request(request)
        if classifier is not None and getattr(classifier, "name", None) == "local-dinov3":
            return self.local_max_concurrent_requests
        return self.cloud_max_concurrent_requests

    def _classifier_identity(
        self, request: ProcessorRunRequest
    ) -> VisualIdentityClassifierIdentity:
        model = request.model
        classifier = self._classifier_for_request(request)
        if model is None or classifier is None:
            raise VisualIdentityPipelineError("The visual identity classifier identity is missing.")
        return VisualIdentityClassifierIdentity(
            provider=classifier.name,
            implementation_name=request.implementation.name,
            implementation_version=request.implementation.version,
            model_name=model.name,
            model_version=model.version,
        )

    def _classifier_for_selection(self, requested_provider: str | None) -> Any | None:
        if requested_provider is None:
            return self.classifier
        if requested_provider == "cloud":
            candidates = ("gemini", "cloud")
        elif requested_provider == "local":
            candidates = ("local",)
        elif requested_provider.startswith("local-"):
            # Durable requests store the concrete classifier name, while the lazy registry
            # exposes the configured local implementation under its logical provider name.
            candidates = (requested_provider, "local")
        else:
            candidates = (requested_provider,)
        if self.identity_classifiers is not None:
            for candidate in candidates:
                try:
                    classifier = self.identity_classifiers.get(candidate)
                except (KeyError, ValueError, RuntimeError) as error:
                    raise VisualIdentityPipelineInputError(str(error)) from error
                if classifier is not None:
                    return self._adapt_classifier(classifier)
        current = self.classifier
        if current is not None and requested_provider in {
            current.name,
            "cloud" if current.name == "gemini" else None,
            "local" if current.name.startswith("local") else None,
        }:
            return current
        return None

    def _classifier_for_request(self, request: ProcessorRunRequest) -> Any | None:
        return self._classifier_for_selection(configuration_provider(request.configuration))

    def _publish_revision(
        self, run: StoredProcessorRun, content: VisualIdentityData
    ) -> StoredPipelineRevision:
        producer = ProcessorProducer(
            run_id=run.run_id,
            processor_type=run.request.processor_type,
            implementation_id=_implementation_id(run.request.implementation),
            model_id=_model_id(run.request.model),
        )
        crop_policy = run.request.crop_policy or _default_crop_policy(
            self.revision_store.require(run.request.input_revision_ids[0]).content
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
                "policy_id": crop_policy["policy_id"],
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

    def _require_identity_revision(
        self,
        recording_id: str,
        revision_id: str,
        *,
        source: RecordingVideoSource | None = None,
    ) -> StoredPipelineRevision:
        revision = self.revision_store.require(revision_id)
        if (
            revision.manifest.recording_id != recording_id
            or revision.manifest.content_type != "visual_identities"
            or (source is not None and revision.manifest.source != source)
            or not isinstance(revision.content, VisualIdentityData)
        ):
            raise VisualIdentityPipelineInputError(
                "The selected visual identity revision does not match the accepted recording video."
            )
        return revision

    @staticmethod
    def _require_identity_outcome(
        revision: StoredPipelineRevision, item_id: str
    ) -> VisualIdentityOutcome:
        assert isinstance(revision.content, VisualIdentityData)
        outcome = next(
            (candidate for candidate in revision.content.outcomes if candidate.card_id == item_id),
            None,
        )
        if outcome is None:
            raise PipelineNotFound(f"The identity item was not found: {item_id}")
        return outcome

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


def configuration_provider(value: Any) -> str | None:
    """Read the optional provider selection from a processor configuration."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise VisualIdentityPipelineInputError("configuration must be an object.")
    provider = value.get("provider")
    if provider is None:
        return None
    if not isinstance(provider, str) or not provider:
        raise VisualIdentityPipelineInputError("configuration.provider must be a non-empty string.")
    return provider


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


def _pipeline_crop_identity_mapping(crop: ResolvedCrop) -> dict[str, Any]:
    """Adapt the derived-view crop identity to the stored pipeline contract."""

    mapping = crop.identity_mapping()
    for field in ("exclusion_inputs", "exclusion_decisions", "exclusion_policy"):
        mapping.pop(field, None)
    return mapping


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _raise_input(message: str) -> str:
    raise VisualIdentityPipelineInputError(message)


__all__ = [
    "VisualIdentityPipelineError",
    "VisualIdentityPipelineInputError",
    "VisualIdentityPipelineService",
]
