"""Composition root for visual identity pipeline operations."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from doko_operations.card_plane_calibration import CalibrationRevisionStore
from doko_operations.derived_view import FFmpegFrameResolver, FrameResolver
from doko_operations.pipeline_data import ProcessorRunRequest, RecordingVideoSource
from table_evidence_analyzer.pipeline_data import VisualIdentityCropIdentity, VisualIdentityOutcome
from table_evidence_analyzer.visual_identity_crop_input import (
    VisualIdentityCropInput,
    VisualIdentityCropInputItem,
)

from dokodetector_backend.config import Settings
from dokodetector_backend.derived_view_cache import DERIVED_VIEW_CACHE_LOCK
from dokodetector_backend.job_store import Job, JobManager
from dokodetector_backend.pipeline_node_selection_store import (
    ExactNodeSelection,
    PipelineNodeSelectionStore,
)
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_store import (
    PipelineNotFound,
    PipelineRuntimeStorage,
    PipelineSelectionConflict,
    PipelineStateError,
    ProcessorRunStore,
    StoredPipelineRevision,
    StoredProcessorRun,
)
from dokodetector_backend.recording_bundle_store import RecordingBundleStore
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.visual_identity_approval import VisualIdentityApprovalPlanner
from dokodetector_backend.visual_identity_classification import VisualIdentityClassification
from dokodetector_backend.visual_identity_crop_inputs import VisualIdentityCropInputFreezer
from dokodetector_backend.visual_identity_crop_queries import VisualIdentityCropQueries
from dokodetector_backend.visual_identity_crop_sources import (
    VisualIdentityCropSources,
)
from dokodetector_backend.visual_identity_job import VisualIdentityJobExecutor
from dokodetector_backend.visual_identity_pipeline_errors import (
    VisualIdentityPipelineError,
    VisualIdentityPipelineInputError,
)
from dokodetector_backend.visual_identity_recording_access import VisualIdentityRecordingAccess
from dokodetector_backend.visual_identity_request import VisualIdentityRequestBuilder


class VisualIdentityPipelineService:
    """Compose request, crop, classification, job, and approval owners."""

    def __init__(
        self,
        settings: Settings,
        recording_store: RecordingBundleStore,
        repository_storage: RepositoryBundleStorage,
        *,
        identity_classifier: Any | None,
        identity_classifiers: Mapping[str, Any] | None = None,
        frame_resolver: FrameResolver | None = None,
        run_store: ProcessorRunStore,
        selection_store: PipelineNodeSelectionStore,
        node_store: PipelineNodeStore | None = None,
    ) -> None:
        self.settings = settings
        self.recording_store = recording_store
        self.repository_storage = repository_storage
        self.frame_resolver = (
            frame_resolver if frame_resolver is not None else FFmpegFrameResolver()
        )
        self.run_store = run_store
        self.selection_store = selection_store
        self.node_store = node_store
        self.calibration_store = CalibrationRevisionStore(settings.operations_root)
        self.crop_sources = VisualIdentityCropSources(
            node_store=node_store,
            selection_store=selection_store,
            recording_store=recording_store,
            run_store=run_store,
            calibration_store=self.calibration_store,
        )
        self.crop_input_freezer = VisualIdentityCropInputFreezer(
            sources=self.crop_sources,
            run_store=run_store,
            calibration_store=self.calibration_store,
        )
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
        self._lock = RLock()
        self.recording_access = VisualIdentityRecordingAccess(
            settings, recording_store, repository_storage
        )
        self.classification = VisualIdentityClassification(
            settings,
            classifier=identity_classifier,
            identity_classifiers=identity_classifiers,
            storage=self.storage,
            frame_resolver=self.frame_resolver,
            derived_view_lock=self._derived_view_lock,
            video_path_for_recording=self.recording_access.video_path,
            cloud_max_concurrent_requests=self.cloud_max_concurrent_requests,
            local_max_concurrent_requests=self.local_max_concurrent_requests,
        )
        self.request_builder = VisualIdentityRequestBuilder(
            selection_store=selection_store,
            node_store=node_store,
            crop_sources=self.crop_sources,
            crop_input_freezer=self.crop_input_freezer,
            recording_access=self.recording_access,
            classification=self.classification,
            calibration_store=self.calibration_store,
        )
        self.crop_queries = VisualIdentityCropQueries(
            recording_access=self.recording_access,
            request_builder=self.request_builder,
            selection_store=selection_store,
            node_store=node_store,
            recording_store=recording_store,
            repository_storage=repository_storage,
            run_store=run_store,
            storage=self.storage,
            frame_resolver=self.frame_resolver,
            derived_view_lock=self._derived_view_lock,
            crop_sources=self.crop_sources,
        )
        self.job_executor = VisualIdentityJobExecutor(
            run_store=run_store,
            selection_store=selection_store,
            storage=self.storage,
            crop_sources=self.crop_sources,
            request_builder=self.request_builder,
            recording_access=self.recording_access,
            classification=self.classification,
        )
        self.job_manager_provider: Any | None = None
        self.approval_planner = VisualIdentityApprovalPlanner(selection_store, run_store)

    async def start(self) -> None:
        """Keep the service lifecycle symmetrical with the other pipeline services."""

    async def stop(self) -> None:
        """The shared Job Manager owns execution shutdown."""

    def start_classification(
        self, recording_id: str, payload: Mapping[str, Any]
    ) -> StoredProcessorRun:
        if self.job_manager_provider is None:
            raise VisualIdentityPipelineError("the shared job manager is not available")
        values = dict(payload)
        run_id = values.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            run_id = str(uuid4())
            values["run_id"] = run_id
        key = str(uuid5(NAMESPACE_URL, f"visual-identity-run:{run_id}"))
        job = self.job_manager_provider().accept(
            key,
            {
                "type": "visual_identity_classification",
                "context": {"recording_id": recording_id},
                "request": values,
            },
        )
        return self.get_run(recording_id, job.id)

    def get_run(
        self,
        recording_id: str,
        run_id: str,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        include_items: bool = True,
        validate_output_lineage: bool = True,
    ) -> StoredProcessorRun:
        run = self.run_store.require(
            run_id,
            revision_cache=revision_cache,
            include_items=include_items,
            validate_output_lineage=validate_output_lineage,
        )
        self._require_recording(run.request, recording_id)
        return run

    def list_runs(self, recording_id: str) -> tuple[StoredProcessorRun, ...]:
        return tuple(
            run
            for run in self.run_store.list_for_recording(recording_id)
            if run.request.source.recording_id == recording_id
            and run.request.processor_type == "visual-card-identity"
        )

    def get_result(
        self, recording_id: str, run_id: str
    ) -> tuple[StoredProcessorRun, tuple[StoredPipelineRevision, ...]]:
        # The revision is the canonical result payload. Do not load the run's duplicate
        # per-item outcomes or revalidate immutable ancestor payloads on every result read.
        # The run store still checks the output manifest against this request, and the
        # revision store validates the output content and its digest.
        revision_cache: dict[str, StoredPipelineRevision] = {}
        run = self.get_run(
            recording_id,
            run_id,
            revision_cache=revision_cache,
            include_items=False,
            validate_output_lineage=False,
        )
        revisions = tuple(
            self.selection_store.require_processor_revision(item)
            for item in run.state.output_revision_ids
        )
        return run, revisions

    def retry(self, recording_id: str, run_id: str) -> StoredProcessorRun:
        self.get_run(recording_id, run_id)
        if self.job_manager_provider is None:
            raise VisualIdentityPipelineError("the shared job manager is not available")
        job = self.job_manager_provider().retry(run_id, str(uuid4()))
        return self.get_run(recording_id, job.id)

    def select_generated(self, recording_id: str, payload: Mapping[str, Any]) -> ExactNodeSelection:
        expected_revision = payload.get("expected_revision")
        selected = payload.get("selected_generated")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise VisualIdentityPipelineInputError(
                "expected_revision must be a non-negative integer."
            )
        if selected is not None and not isinstance(selected, Mapping):
            raise VisualIdentityPipelineInputError(
                "selected_generated must be a node revision pointer or null."
            )
        current = self.selection_store.get_exact(recording_id, "visual_identities")
        completed = None if current is None else current.selected_completed_reference
        try:
            return self.selection_store.update_exact(
                recording_id,
                "visual_identities",
                expected_revision=expected_revision,
                selected_generated=selected,
                selected_completed_reference=completed,
            )
        except PipelineSelectionConflict:
            raise
        except (PipelineNotFound, PipelineStateError, ValueError, FileNotFoundError) as error:
            raise VisualIdentityPipelineInputError(str(error)) from error

    def list_proposed_crop_inputs(self, recording_id: str) -> tuple[dict[str, Any], ...]:
        return self.request_builder.list_proposed_crop_inputs(recording_id)

    def plan_auto_approval(
        self, recording_id: str, source_revision_id: str, draft_items: tuple[Mapping[str, Any], ...]
    ) -> dict[str, Any]:
        plan = self.approval_planner.plan_auto_approval(
            recording_id, source_revision_id, draft_items
        )
        local_run = (
            None
            if plan.local_run_request is None
            else self.start_classification(recording_id, plan.local_run_request)
        )
        return {
            "source_revision_id": plan.source_revision_id,
            "local_run": (
                None
                if local_run is None
                else {
                    "run_id": local_run.run_id,
                    "status": local_run.state.status,
                    "attempt": local_run.state.attempt,
                }
            ),
            "items": list(plan.items),
        }

    def get_identity_crop_identity(
        self, recording_id: str, revision_id: str, item_id: str
    ) -> VisualIdentityCropIdentity:
        return self.crop_queries.get_identity_crop_identity(recording_id, revision_id, item_id)

    def resolve_reviewed_annotation_crops(
        self,
        recording_id: str,
        visible_revision_id: str,
        annotation_revision_id: str,
        item_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        return self.crop_queries.resolve_reviewed_annotation_crops(
            recording_id, visible_revision_id, annotation_revision_id, item_ids
        )

    def resolve_reviewed_annotation_crop(
        self, recording_id: str, visible_revision_id: str, annotation_revision_id: str, item_id: str
    ) -> Any:
        return self.crop_queries.resolve_reviewed_annotation_crop(
            recording_id, visible_revision_id, annotation_revision_id, item_id
        )

    def resolve_identity_crop(self, recording_id: str, revision_id: str, item_id: str) -> Any:
        return self.crop_queries.resolve_identity_crop(recording_id, revision_id, item_id)

    def resolve_identity_crop_browser_preview(
        self, recording_id: str, revision_id: str, item_id: str
    ) -> Any:
        return self.crop_queries.resolve_identity_crop_browser_preview(
            recording_id, revision_id, item_id
        )

    def _build_request(self, recording_id: str, payload: Mapping[str, Any]) -> ProcessorRunRequest:
        return self.request_builder.build(recording_id, payload)

    def _canonical_input_node_ref(self, revision_id: str, content_type: str) -> dict[str, Any]:
        return self.request_builder._canonical_input_node_ref(revision_id, content_type)

    def canonical_input_revision(self, request: ProcessorRunRequest) -> StoredPipelineRevision:
        return self.request_builder.canonical_input_revision(request)

    def _freeze_crop_input(
        self, recording_id: str, revision: StoredPipelineRevision, **kwargs: Any
    ) -> VisualIdentityCropInput:
        return self.request_builder._freeze_crop_input(recording_id, revision, **kwargs)

    def _is_selected_completed_node_revision(
        self, recording_id: str, node_id: str, revision_id: str
    ) -> bool:
        return self.request_builder._is_selected_completed_node_revision(
            recording_id, node_id, revision_id
        )

    @staticmethod
    def _reviewed_virtual_card_items(
        content: Any, *, fallback_scene_revision_id: str
    ) -> tuple[VisualIdentityCropInputItem, ...]:
        return VisualIdentityRequestBuilder._reviewed_virtual_card_items(
            content, fallback_scene_revision_id=fallback_scene_revision_id
        )

    @staticmethod
    def _validate_scene_derived_views(content: Any) -> None:
        return VisualIdentityRequestBuilder._validate_scene_derived_views(content)

    @staticmethod
    def _validate_outcome_scene_derived_view(outcome: VisualIdentityOutcome) -> None:
        return VisualIdentityRequestBuilder._validate_outcome_scene_derived_view(outcome)

    @staticmethod
    def _identity_item_ids(items: tuple[VisualIdentityCropInputItem, ...]) -> tuple[str, ...]:
        return VisualIdentityRequestBuilder._identity_item_ids(items)

    @staticmethod
    def _identity_crop_item_for_outcome(
        crop_input: VisualIdentityCropInput, outcome: VisualIdentityOutcome
    ) -> VisualIdentityCropInputItem | None:
        return VisualIdentityRequestBuilder._identity_crop_item_for_outcome(crop_input, outcome)

    def execute_job(
        self, job: Job, token: Any, manager: JobManager, *, cpu_budget: int = 1
    ) -> None:
        return self.job_executor.execute_job(job, token, manager, cpu_budget=cpu_budget)

    def _classifier_for_selection(self, requested_provider: str | None) -> Any | None:
        return self.classification.classifier_for_selection(requested_provider)

    def _classifier_for_request(self, request: ProcessorRunRequest) -> Any | None:
        return self.classification.classifier_for_request(request)

    def _classifier_identity(self, request: ProcessorRunRequest) -> Any:
        return self.classification.classifier_identity(request)

    def _max_concurrent_requests(self, request: ProcessorRunRequest) -> int:
        return self.classification.max_concurrent_requests(request)

    def _publish_revision(self, run: StoredProcessorRun, content: Any) -> StoredPipelineRevision:
        return self.job_executor._publish_revision(run, content)

    def _accepted_source(self, recording_id: str) -> tuple[Any, RecordingVideoSource]:
        return self.recording_access.accepted_source(recording_id)

    def _video_path(self, recording_id: str) -> Path:
        return self.recording_access.video_path(recording_id)

    @staticmethod
    def _require_recording(request: ProcessorRunRequest, recording_id: str) -> None:
        if request.source.recording_id != recording_id:
            raise PipelineNotFound(f"The processor run was not found for recording: {recording_id}")

    @staticmethod
    def _adapt_classifier(classifier: Any | None) -> Any | None:
        return VisualIdentityClassification._adapt_classifier(classifier)


__all__ = [
    "VisualIdentityPipelineError",
    "VisualIdentityPipelineInputError",
    "VisualIdentityPipelineService",
]
