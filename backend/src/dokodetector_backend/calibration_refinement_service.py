"""Backend persistence and calculation service for 0073 calibration previews."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from doko_operations.card_plane_calibration_refinement import (
    CalibrationDraftStore,
    CalibrationRefinementError,
    anchor_observations_from_local_result,
    apply_anchor_command_to_draft,
    build_calibration_draft,
    build_calibration_preview,
)
from doko_operations.proposed_card_scene_processor import visible_card_data_to_local_result
from table_evidence_analyzer.card_scene_contract import (
    AnchorCommand,
    CalibrationDraft,
)
from table_evidence_analyzer.pipeline_data import ProposedCardSceneData, VisibleCardData

from dokodetector_backend.pipeline_reference_store import PipelineReferenceNotFound
from dokodetector_backend.pipeline_store import PipelineNotFound, PipelineRevisionStore
from dokodetector_backend.proposed_card_scene_pipeline_service import (
    ProposedCardScenePipelineService,
)


class CalibrationRefinementInputError(CalibrationRefinementError, ValueError):
    """The calibration refinement request is invalid."""


class CalibrationRefinementNotFound(CalibrationRefinementError):
    """The requested calibration refinement draft does not exist."""


class CalibrationRefinementService:
    """Keep one resumable calibration draft and calculate its current preview."""

    def __init__(
        self,
        settings: Any,
        *,
        revision_store: PipelineRevisionStore,
        proposal_service: ProposedCardScenePipelineService,
        reference_service: Any,
    ) -> None:
        self.revision_store = revision_store
        self.proposal_service = proposal_service
        self.reference_service = reference_service
        self.store = CalibrationDraftStore(settings.operations_root)

    def start(self, recording_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise CalibrationRefinementInputError(
                "the calibration refinement request must be an object"
            )
        proposal_revision_id = payload.get("proposal_revision_id")
        if not isinstance(proposal_revision_id, str) or not proposal_revision_id:
            raise CalibrationRefinementInputError("proposal_revision_id is required")
        proposal, source, data = self._proposal(recording_id, proposal_revision_id)
        del proposal
        draft_id = payload.get("draft_id", f"calibration-draft-{proposal_revision_id}")
        if not isinstance(draft_id, str) or not draft_id:
            raise CalibrationRefinementInputError("draft_id must be a non-empty string")
        try:
            draft = self.store.load(recording_id, draft_id)
        except CalibrationRefinementError as error:
            if not isinstance(source.content, VisibleCardData):
                raise CalibrationRefinementInputError(
                    "proposal source is not visible-card data"
                ) from error
            local_result = visible_card_data_to_local_result(
                source.content,
                recording_id=recording_id,
                source_revision=source.manifest.revision_id,
            )
            anchors, frame_digests = anchor_observations_from_local_result(
                local_result,
                detector_revision_id=source.manifest.revision_id,
            )
            draft = build_calibration_draft(
                draft_id=draft_id,
                recording_id=recording_id,
                detector_revision_id=source.manifest.revision_id,
                detector_revision_digest=source.manifest.content_sha256,
                base_calibration=data.calibration,
                anchors=anchors,
                source_frame_digests=frame_digests,
            )
            self.store.publish_initial(draft)
            self.store.publish(draft)
        return self._response(recording_id, proposal_revision_id, draft, data)

    def get(
        self, recording_id: str, proposal_revision_id: str, draft_id: str | None
    ) -> dict[str, Any]:
        _proposal, _source, data = self._proposal(recording_id, proposal_revision_id)
        selected_draft_id = draft_id
        if selected_draft_id is None:
            selected = self.store.list_draft_ids(recording_id)
            selected_draft_id = selected[-1] if selected else None
        if selected_draft_id is None:
            raise CalibrationRefinementNotFound("no calibration refinement draft exists")
        try:
            draft = self.store.load(recording_id, selected_draft_id)
        except CalibrationRefinementError as error:
            raise CalibrationRefinementNotFound(str(error)) from error
        return self._response(recording_id, proposal_revision_id, draft, data)

    def update(
        self,
        recording_id: str,
        proposal_revision_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise CalibrationRefinementInputError(
                "the calibration refinement update must be an object"
            )
        draft_id = payload.get("draft_id")
        if not isinstance(draft_id, str) or not draft_id:
            raise CalibrationRefinementInputError("draft_id is required")
        expected_revision = payload.get("expected_revision")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise CalibrationRefinementInputError("expected_revision must be an integer")
        command_raw = payload.get("command")
        if not isinstance(command_raw, Mapping):
            raise CalibrationRefinementInputError("command is required")
        try:
            command = AnchorCommand.from_mapping(command_raw, "command")
            draft = self.store.load(recording_id, draft_id)
        except (CalibrationRefinementError, TypeError, ValueError) as error:
            raise CalibrationRefinementInputError(str(error)) from error
        if any(existing.command_id == command.command_id for existing in draft.commands):
            _proposal, _source, data = self._proposal(recording_id, proposal_revision_id)
            return self._response(recording_id, proposal_revision_id, draft, data)
        if draft.revision != expected_revision:
            raise CalibrationRefinementInputError(
                "calibration draft changed; "
                f"expected revision {expected_revision}, current {draft.revision}"
            )
        updated = apply_anchor_command_to_draft(draft, command)
        self.store.publish(updated)
        _proposal, _source, data = self._proposal(recording_id, proposal_revision_id)
        return self._response(recording_id, proposal_revision_id, updated, data)

    def discard(
        self,
        recording_id: str,
        proposal_revision_id: str,
        draft_id: str,
    ) -> dict[str, Any]:
        _proposal, _source, data = self._proposal(recording_id, proposal_revision_id)
        try:
            draft = self.store.reset(recording_id, draft_id)
        except CalibrationRefinementError as error:
            raise CalibrationRefinementNotFound(str(error)) from error
        return self._response(recording_id, proposal_revision_id, draft, data)

    def _proposal(
        self, recording_id: str, proposal_revision_id: str
    ) -> tuple[Any, Any, ProposedCardSceneData]:
        try:
            proposal = self.revision_store.require(proposal_revision_id)
        except PipelineNotFound as error:
            raise CalibrationRefinementInputError("proposal revision was not found") from error
        if proposal.manifest.recording_id != recording_id:
            raise CalibrationRefinementInputError("proposal revision belongs to another recording")
        if proposal.manifest.content_type != "card_scene_proposals" or not isinstance(
            proposal.content, ProposedCardSceneData
        ):
            raise CalibrationRefinementInputError("proposal_revision_id must reference card scenes")
        source_ids = proposal.manifest.input_revision_ids
        if len(source_ids) != 1:
            raise CalibrationRefinementInputError("proposal revision must have one detector input")
        try:
            source = self.revision_store.require(source_ids[0])
        except PipelineNotFound as error:
            raise CalibrationRefinementInputError(
                "proposal detector input was not found"
            ) from error
        if not isinstance(source.content, VisibleCardData):
            raise CalibrationRefinementInputError(
                "proposal detector input is not visible-card data"
            )
        return proposal, source, proposal.content

    def _response(
        self,
        recording_id: str,
        proposal_revision_id: str,
        draft: CalibrationDraft,
        data: ProposedCardSceneData,
    ) -> dict[str, Any]:
        frame_scenes = self._frame_scenes(recording_id, data)
        preview = build_calibration_preview(draft, data.calibration, frame_scenes=frame_scenes)
        contributions = []
        from table_evidence_analyzer.card_scene_contract import anchor_fit_contributions

        contributions.extend(item.to_mapping() for item in anchor_fit_contributions(draft.anchors))
        return {
            "schema_version": "table-plane-calibration-refinement/v1",
            "recording_id": recording_id,
            "proposal_revision_id": proposal_revision_id,
            "draft": draft.to_mapping(),
            "preview": preview.to_mapping(),
            "anchor_contributions": contributions,
        }

    def _frame_scenes(
        self, recording_id: str, data: ProposedCardSceneData
    ) -> tuple[dict[str, Any], ...]:
        try:
            reference = self.reference_service.get_reference(recording_id, "visible_cards")
        except PipelineReferenceNotFound:
            reference = None
        if reference is not None and reference.draft.items:
            return tuple(
                {"item_id": item.item_id, **item.item}
                for item in reference.draft.items
            )
        return tuple(
            {
                "frame_id": frame.frame_id,
                "scene": frame.proposal.initialized_scene
                if frame.proposal is not None
                else None,
            }
            for frame in data.frames
            if frame.proposal is not None
        )


__all__ = [
    "CalibrationRefinementInputError",
    "CalibrationRefinementNotFound",
    "CalibrationRefinementService",
]
