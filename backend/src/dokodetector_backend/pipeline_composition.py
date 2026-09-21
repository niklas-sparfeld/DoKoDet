"""Compose the backend pipeline stores and services in one place."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dokodetector_backend.calibration_refinement_service import CalibrationRefinementService
from dokodetector_backend.event_pipeline_service import EventPipelineService, EventProcessorProvider
from dokodetector_backend.observation_pipeline_service import ObservationPipelineService
from dokodetector_backend.pipeline_comparison_service import PipelineComparisonService
from dokodetector_backend.pipeline_reference_service import PipelineReferenceService
from dokodetector_backend.pipeline_reference_store import PipelineReferenceStore
from dokodetector_backend.pipeline_store import (
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    PipelineSelectionStore,
    ProcessorRunStore,
)
from dokodetector_backend.pipeline_workspace_service import RecordingPipelineWorkspaceService
from dokodetector_backend.proposed_card_scene_pipeline_service import (
    ProposedCardScenePipelineService,
)
from dokodetector_backend.recording_bundle_store import RecordingBundleStore
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.round_analysis_store import RoundAnalysisStore
from dokodetector_backend.visible_card_pipeline_service import VisibleCardPipelineService
from dokodetector_backend.visual_identity_pipeline_service import VisualIdentityPipelineService


@dataclass(frozen=True)
class PipelineComposition:
    """All shared pipeline stores and constructed services."""

    revision_store: PipelineRevisionStore
    run_store: ProcessorRunStore
    selection_store: PipelineSelectionStore
    reference_store: PipelineReferenceStore
    reference_service: PipelineReferenceService
    event_service: EventPipelineService
    comparison_service: PipelineComparisonService
    visible_card_service: VisibleCardPipelineService
    proposed_card_scene_service: ProposedCardScenePipelineService
    calibration_refinement_service: CalibrationRefinementService
    visual_identity_service: VisualIdentityPipelineService
    observation_service: ObservationPipelineService
    workspace_service: RecordingPipelineWorkspaceService

    @property
    def lifecycle_services(self) -> tuple[Any, ...]:
        """Return processor and analysis services managed by the app lifespan."""

        return (
            self.event_service,
            self.visible_card_service,
            self.proposed_card_scene_service,
            self.visual_identity_service,
            self.observation_service,
        )


def build_pipeline_composition(
    settings: Any,
    recording_store: RecordingBundleStore,
    repository_storage: RepositoryBundleStorage,
    round_analysis_store: RoundAnalysisStore,
    *,
    visible_card_provider: Any | None,
    visible_card_frame_resolver: Any | None,
    visible_card_identity_classifier: Any | None,
    event_provider: EventProcessorProvider | None,
    visible_card_providers: Any | None = None,
    visible_card_identity_classifiers: Any | None = None,
) -> PipelineComposition:
    """Create shared pipeline stores and services with explicit dependencies."""

    runtime_storage = PipelineRuntimeStorage(settings.evidence_root, settings.operations_root)
    revision_store = PipelineRevisionStore(runtime_storage)
    run_store = ProcessorRunStore(runtime_storage, revision_store=revision_store)
    selection_store = PipelineSelectionStore(
        runtime_storage,
        revision_store=revision_store,
        run_store=run_store,
    )
    reference_store = PipelineReferenceStore(settings.operations_root / "pipeline-references")
    reference_service = PipelineReferenceService(
        settings,
        recording_store,
        repository_storage,
        reference_store=reference_store,
        revision_store=revision_store,
        selection_store=selection_store,
    )
    event_service = EventPipelineService(
        settings,
        recording_store,
        repository_storage,
        event_provider=event_provider,
        revision_store=revision_store,
        run_store=run_store,
        selection_store=selection_store,
    )
    comparison_service = PipelineComparisonService(
        revision_store=revision_store,
        run_store=run_store,
    )
    visible_card_service = VisibleCardPipelineService(
        settings,
        recording_store,
        repository_storage,
        detector_provider=visible_card_provider,
        detector_providers=visible_card_providers,
        frame_resolver=visible_card_frame_resolver,
        revision_store=revision_store,
        run_store=run_store,
        selection_store=selection_store,
    )
    proposed_card_scene_service = ProposedCardScenePipelineService(
        settings,
        revision_store=revision_store,
        run_store=run_store,
        selection_store=selection_store,
    )
    calibration_refinement_service = CalibrationRefinementService(
        settings,
        revision_store=revision_store,
        proposal_service=proposed_card_scene_service,
        reference_service=reference_service,
    )
    visual_identity_service = VisualIdentityPipelineService(
        settings,
        recording_store,
        repository_storage,
        identity_classifier=visible_card_identity_classifier,
        identity_classifiers=visible_card_identity_classifiers,
        frame_resolver=visible_card_frame_resolver,
        revision_store=revision_store,
        run_store=run_store,
        selection_store=selection_store,
    )
    observation_service = ObservationPipelineService(
        revision_store=revision_store,
        run_store=run_store,
        selection_store=selection_store,
        runtime_root=settings.evidence_root,
        operations_root=settings.operations_root,
    )
    workspace_service = RecordingPipelineWorkspaceService(
        recording_source_provider=event_service.get_recording_source,
        revision_store=revision_store,
        run_store=run_store,
        selection_store=selection_store,
        reference_store=reference_store,
        round_analysis_store=round_analysis_store,
    )
    return PipelineComposition(
        revision_store=revision_store,
        run_store=run_store,
        selection_store=selection_store,
        reference_store=reference_store,
        reference_service=reference_service,
        event_service=event_service,
        comparison_service=comparison_service,
        visible_card_service=visible_card_service,
        proposed_card_scene_service=proposed_card_scene_service,
        calibration_refinement_service=calibration_refinement_service,
        visual_identity_service=visual_identity_service,
        observation_service=observation_service,
        workspace_service=workspace_service,
    )


def install_pipeline_composition(state: Any, composition: PipelineComposition) -> None:
    """Install the composition under the existing application state keys."""

    state.pipeline_revision_store = composition.revision_store
    state.pipeline_run_store = composition.run_store
    state.pipeline_selection_store = composition.selection_store
    state.pipeline_reference_store = composition.reference_store
    state.pipeline_reference_service = composition.reference_service
    state.event_pipeline_service = composition.event_service
    state.pipeline_comparison_service = composition.comparison_service
    state.visible_card_pipeline_service = composition.visible_card_service
    state.proposed_card_scene_pipeline_service = composition.proposed_card_scene_service
    state.calibration_refinement_service = composition.calibration_refinement_service
    state.visual_identity_pipeline_service = composition.visual_identity_service
    state.observation_pipeline_service = composition.observation_service
    state.pipeline_workspace_service = composition.workspace_service


__all__ = [
    "PipelineComposition",
    "build_pipeline_composition",
    "install_pipeline_composition",
]
