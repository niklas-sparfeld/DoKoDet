"""Compose the backend pipeline stores and services in one place."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from doko_operations.card_plane_calibration_refinement import CalibrationDraftStore

from dokodetector_backend.calibration_refinement_service import CalibrationRefinementService
from dokodetector_backend.event_pipeline_service import EventPipelineService, EventProcessorProvider
from dokodetector_backend.event_set_store import EventSetStore
from dokodetector_backend.observation_pipeline_service import ObservationPipelineService
from dokodetector_backend.pipeline_comparison_service import PipelineComparisonService
from dokodetector_backend.pipeline_lineage import PipelineLineage
from dokodetector_backend.pipeline_lineage_writer import PipelineLineageWriter
from dokodetector_backend.pipeline_node_edits import PipelineNodeEdits
from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
from dokodetector_backend.pipeline_node_selection_store import PipelineNodeSelectionStore
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses
from dokodetector_backend.pipeline_storage import PipelineRuntimeStorage
from dokodetector_backend.pipeline_workspace_service import RecordingPipelineWorkspaceService
from dokodetector_backend.processor_run_store import ProcessorRunStore
from dokodetector_backend.proposed_card_scene_pipeline_service import (
    ProposedCardScenePipelineService,
)
from dokodetector_backend.recording_bundle_store import RecordingBundleStore
from dokodetector_backend.recording_folder_store import RecordingFolderStore
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.round_analysis_store import RoundAnalysisStore
from dokodetector_backend.visible_card_pipeline_service import VisibleCardPipelineService
from dokodetector_backend.visual_identity_pipeline_service import VisualIdentityPipelineService


@dataclass(frozen=True)
class PipelineComposition:
    """All shared pipeline stores and constructed services."""

    run_store: ProcessorRunStore
    selection_store: PipelineNodeSelectionStore
    event_service: EventPipelineService
    comparison_service: PipelineComparisonService
    visible_card_service: VisibleCardPipelineService
    proposed_card_scene_service: ProposedCardScenePipelineService
    calibration_refinement_service: CalibrationRefinementService
    visual_identity_service: VisualIdentityPipelineService
    observation_service: ObservationPipelineService
    workspace_service: RecordingPipelineWorkspaceService
    lineage_service: PipelineLineage
    lineage_writer: PipelineLineageWriter
    node_edits: PipelineNodeEdits
    node_reviews: PipelineNodeReviews

    @property
    def lifecycle_services(self) -> tuple[Any, ...]:
        """Return processor and analysis services managed by the app lifespan."""

        return (
            self.event_service,
            self.visible_card_service,
            self.visual_identity_service,
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
    recording_folder_store: RecordingFolderStore | None = None,
    event_set_store: EventSetStore | None = None,
) -> PipelineComposition:
    """Create shared pipeline stores and services with explicit dependencies."""

    runtime_storage = PipelineRuntimeStorage(settings.evidence_root, settings.operations_root)
    node_store = PipelineNodeStore(settings.operations_root / "pipeline-nodes")
    lineage_service = PipelineLineage(node_store)
    lineage_writer = PipelineLineageWriter(
        node_store,
        lineage_service,
        PipelineNodeUses(node_store),
        event_set_store=event_set_store,
    )
    run_store = ProcessorRunStore(runtime_storage, lineage_writer=lineage_writer)
    selection_store = PipelineNodeSelectionStore(node_store, lineage_writer)
    node_edits = PipelineNodeEdits(node_store)
    node_reviews = PipelineNodeReviews(node_store)
    event_service = EventPipelineService(
        settings,
        recording_store,
        repository_storage,
        event_provider=event_provider,
        run_store=run_store,
        recording_folder_store=recording_folder_store,
        event_set_store=event_set_store,
    )
    comparison_service = PipelineComparisonService(
        selection_store=selection_store,
        run_store=run_store,
        event_set_store=event_set_store,
    )
    visible_card_service = VisibleCardPipelineService(
        settings,
        recording_store,
        repository_storage,
        detector_provider=visible_card_provider,
        detector_providers=visible_card_providers,
        frame_resolver=visible_card_frame_resolver,
        run_store=run_store,
        selection_store=selection_store,
        node_store=node_store,
        event_set_store=event_set_store,
    )
    proposed_card_scene_service = ProposedCardScenePipelineService(
        settings,
        run_store=run_store,
        selection_store=selection_store,
        node_store=node_store,
    )
    calibration_refinement_service = CalibrationRefinementService(
        settings,
        draft_store=CalibrationDraftStore(
            settings.operations_root / "calibration-refinement-drafts"
        ),
        node_store=node_store,
    )
    visual_identity_service = VisualIdentityPipelineService(
        settings,
        recording_store,
        repository_storage,
        identity_classifier=visible_card_identity_classifier,
        identity_classifiers=visible_card_identity_classifiers,
        frame_resolver=visible_card_frame_resolver,
        run_store=run_store,
        selection_store=selection_store,
        node_store=node_store,
        recording_folder_store=recording_folder_store,
    )
    observation_service = ObservationPipelineService(
        run_store=run_store,
        selection_store=selection_store,
        recording_store=recording_store,
        runtime_root=settings.evidence_root,
        operations_root=settings.operations_root,
        node_store=node_store,
        event_set_store=event_set_store,
    )
    workspace_service = RecordingPipelineWorkspaceService(
        recording_source_provider=event_service.get_recording_source,
        run_store=run_store,
        selection_store=selection_store,
        round_analysis_store=round_analysis_store,
        node_store=node_store,
        lineage_service=lineage_service,
        recording_folder_store=recording_folder_store,
        event_set_store=event_set_store,
    )
    return PipelineComposition(
        run_store=run_store,
        selection_store=selection_store,
        event_service=event_service,
        comparison_service=comparison_service,
        visible_card_service=visible_card_service,
        proposed_card_scene_service=proposed_card_scene_service,
        calibration_refinement_service=calibration_refinement_service,
        visual_identity_service=visual_identity_service,
        observation_service=observation_service,
        workspace_service=workspace_service,
        lineage_service=lineage_service,
        lineage_writer=lineage_writer,
        node_edits=node_edits,
        node_reviews=node_reviews,
    )


def install_pipeline_composition(state: Any, composition: PipelineComposition) -> None:
    """Install the composition under the existing application state keys."""

    state.pipeline_run_store = composition.run_store
    state.pipeline_selection_store = composition.selection_store
    state.event_pipeline_service = composition.event_service
    state.pipeline_comparison_service = composition.comparison_service
    state.visible_card_pipeline_service = composition.visible_card_service
    state.proposed_card_scene_pipeline_service = composition.proposed_card_scene_service
    state.calibration_refinement_service = composition.calibration_refinement_service
    state.visual_identity_pipeline_service = composition.visual_identity_service
    state.observation_pipeline_service = composition.observation_service
    state.pipeline_workspace_service = composition.workspace_service
    state.pipeline_lineage_service = composition.lineage_service
    state.pipeline_lineage_writer = composition.lineage_writer
    state.pipeline_node_edits = composition.node_edits
    state.pipeline_node_reviews = composition.node_reviews


__all__ = [
    "PipelineComposition",
    "build_pipeline_composition",
    "install_pipeline_composition",
]
