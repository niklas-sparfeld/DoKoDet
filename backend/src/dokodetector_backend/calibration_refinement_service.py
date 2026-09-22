"""Backend persistence and calculation service for 0073 calibration previews."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from doko_operations.card_plane_calibration import CalibrationRevisionStore
from doko_operations.card_plane_calibration_refinement import (
    CalibrationDraftStore,
    CalibrationRefinementError,
    CalibrationReflowReceiptStore,
    anchor_observations_from_local_result,
    apply_anchor_command_to_draft,
    build_calibration_draft,
    build_calibration_preview,
    build_published_calibration_run,
)
from doko_operations.card_plane_geometry import TablePlaneCalibration
from doko_operations.pipeline_data import (
    DataRevision,
    ProcessorProducer,
    canonical_json_bytes,
    sha256_bytes,
)
from doko_operations.proposed_card_scene_processor import (
    build_proposed_card_scene_data,
    visible_card_data_to_local_result,
)
from table_evidence_analyzer.card_scene_contract import (
    AnchorCommand,
    CalibrationDraft,
    CalibrationReflowReceipt,
)
from table_evidence_analyzer.pipeline_data import (
    ProposedCardSceneData,
    VisibleCardData,
    canonical_proposed_card_scene_data_bytes,
)

from dokodetector_backend.pipeline_reference_errors import (
    PipelineReferenceConflict,
    PipelineReferenceInputError,
)
from dokodetector_backend.pipeline_reference_store import PipelineReferenceNotFound
from dokodetector_backend.pipeline_store import PipelineNotFound, PipelineRevisionStore
from dokodetector_backend.proposed_card_scene_pipeline_service import (
    ProposedCardScenePipelineService,
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class CalibrationRefinementInputError(CalibrationRefinementError, ValueError):
    """The calibration refinement request is invalid."""


class CalibrationRefinementConflict(CalibrationRefinementError):
    """The maintained reference changed while calibration apply was pending."""


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
        self.calibration_store = CalibrationRevisionStore(settings.operations_root)
        self.receipt_store = CalibrationReflowReceiptStore(settings.operations_root)

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
        self._require_current_source(draft, source)
        return self._response(recording_id, proposal_revision_id, draft, data)

    def get(
        self, recording_id: str, proposal_revision_id: str, draft_id: str | None
    ) -> dict[str, Any]:
        selected_draft_id = draft_id or f"calibration-draft-{proposal_revision_id}"
        try:
            draft = self.store.load(recording_id, selected_draft_id)
        except CalibrationRefinementError as error:
            raise CalibrationRefinementNotFound(str(error)) from error
        _proposal, source, data = self._proposal(recording_id, proposal_revision_id)
        self._require_current_source(draft, source)
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
        _proposal, source, data = self._proposal(recording_id, proposal_revision_id)
        self._require_current_source(draft, source)
        if any(existing.command_id == command.command_id for existing in draft.commands):
            return self._response(recording_id, proposal_revision_id, draft, data)
        if draft.revision != expected_revision:
            raise CalibrationRefinementInputError(
                "calibration draft changed; "
                f"expected revision {expected_revision}, current {draft.revision}"
            )
        updated = apply_anchor_command_to_draft(draft, command)
        self.store.publish(updated)
        return self._response(recording_id, proposal_revision_id, updated, data)

    def discard(
        self,
        recording_id: str,
        proposal_revision_id: str,
        draft_id: str,
    ) -> dict[str, Any]:
        _proposal, source, data = self._proposal(recording_id, proposal_revision_id)
        try:
            draft = self.store.load(recording_id, draft_id)
        except CalibrationRefinementError as error:
            raise CalibrationRefinementNotFound(str(error)) from error
        self._require_current_source(draft, source)
        try:
            draft = self.store.reset(recording_id, draft_id)
        except CalibrationRefinementError as error:
            raise CalibrationRefinementNotFound(str(error)) from error
        return self._response(recording_id, proposal_revision_id, draft, data)

    @staticmethod
    def _require_current_source(draft: CalibrationDraft, source: DataRevision) -> None:
        if (
            draft.detector_revision_id != source.manifest.revision_id
            or draft.detector_revision_digest != source.manifest.content_sha256
        ):
            raise CalibrationRefinementInputError(
                "calibration draft uses a different detector revision; start a new mapping preview"
            )

    def apply(
        self,
        recording_id: str,
        proposal_revision_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Apply one passing calibration preview and atomically reflow the draft."""

        if not isinstance(payload, Mapping):
            raise CalibrationRefinementInputError(
                "the calibration refinement apply request must be an object"
            )
        draft_id = payload.get("draft_id")
        expected_revision = payload.get("expected_revision")
        preview_digest = payload.get("preview_digest")
        operator_id = payload.get("operator_id", "operator")
        confirm_affected = payload.get("confirm_affected", False)
        if not isinstance(draft_id, str) or not draft_id:
            raise CalibrationRefinementInputError("draft_id is required")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise CalibrationRefinementInputError("expected_revision must be an integer")
        if not isinstance(preview_digest, str) or not preview_digest:
            raise CalibrationRefinementInputError("preview_digest is required")
        if not isinstance(operator_id, str) or not operator_id.strip():
            raise CalibrationRefinementInputError("operator_id must be a non-empty string")
        if not isinstance(confirm_affected, bool):
            raise CalibrationRefinementInputError("confirm_affected must be a boolean")

        _proposal, source, data = self._proposal(recording_id, proposal_revision_id)
        try:
            draft = self.store.load(recording_id, draft_id)
        except CalibrationRefinementError as error:
            raise CalibrationRefinementInputError(str(error)) from error
        if draft.revision != expected_revision:
            raise CalibrationRefinementInputError(
                "calibration draft changed; "
                f"expected revision {expected_revision}, current {draft.revision}"
            )
        if (
            draft.detector_revision_id != source.manifest.revision_id
            or draft.detector_revision_digest != source.manifest.content_sha256
        ):
            raise CalibrationRefinementInputError(
                "the calibration draft uses a stale detector revision; reload the refinement"
            )
        receipt_id = "reflow-" + hashlib.sha256(
            canonical_json_bytes(
                {
                    "draft_id": draft.draft_id,
                    "draft_digest": draft.draft_digest,
                    "preview_digest": preview_digest,
                }
            )
        ).hexdigest()[:24]
        try:
            previous_receipt = self.receipt_store.load(recording_id, receipt_id)
        except CalibrationRefinementError:
            previous_receipt = None
        if previous_receipt is not None:
            try:
                reference = self.reference_service.get_reference(recording_id, "visible_cards")
            except PipelineReferenceNotFound as error:
                raise CalibrationRefinementInputError(
                    "the maintained visible-card draft is missing; reload the pipeline"
                ) from error
            if reference.draft.proposal_revision_id == previous_receipt.proposal_revision_id:
                return {
                    "schema_version": "table-plane-calibration-refinement/v1",
                    "action": "applied",
                    "recording_id": recording_id,
                    "source_proposal_revision_id": proposal_revision_id,
                    "proposal_revision_id": previous_receipt.proposal_revision_id,
                    "calibration_revision_id": previous_receipt.target_calibration_revision_id,
                    "receipt": previous_receipt.to_mapping(),
                    "reference": reference.to_mapping(),
                }
        preview = build_calibration_preview(
            draft,
            data.calibration,
            frame_scenes=self._frame_scenes(recording_id, data),
        )
        if preview.preview_digest != preview_digest:
            raise CalibrationRefinementInputError(
                "the calibration preview changed; reload the current preview"
            )
        if preview.candidate_calibration is None or (
            preview.failure is not None
            and (
                preview.failure.code != "reviewed_displacement_exceeded"
                or not confirm_affected
            )
        ):
            action = "inspect and correct the blocked calibration gate"
            if preview.failure is not None:
                action = preview.failure.action
            raise CalibrationRefinementInputError(action)
        try:
            current_reference = self.reference_service.get_reference(
                recording_id, "visible_cards"
            )
        except PipelineReferenceNotFound as error:
            raise CalibrationRefinementInputError(
                "the maintained visible-card draft is missing; reload the pipeline"
            ) from error
        forced_affected_frame_ids = tuple(
            sorted(
                item.item_id
                for item in current_reference.draft.items
                if item.item_id in preview.changed_frame_ids
                and item.review_state in {"accepted", "corrected"}
            )
        )

        target = self._target_calibration(
            data.calibration,
            draft,
            preview_digest,
        )
        target_data = build_proposed_card_scene_data(
            visible_card_data_to_local_result(
                source.content,
                recording_id=recording_id,
                source_revision=source.manifest.revision_id,
            ),
            detector_revision_id=source.manifest.revision_id,
            detector_revision_digest=source.manifest.content_sha256,
            calibration=target,
            calibration_diagnostics={
                "source_proposal_revision_id": proposal_revision_id,
                "source_calibration_revision_id": data.calibration_revision_id,
                "source_calibration_digest": data.calibration_digest,
                "refinement_preview_digest": preview_digest,
                "anchor_command_digests": [
                    command.command_digest for command in draft.commands
                ],
            },
        )
        target_proposal_revision_id = f"card-scene-reflow-{receipt_id}"
        target_manifest = DataRevision(
            revision_id=target_proposal_revision_id,
            content_type="card_scene_proposals",
            content_schema="proposed-card-scene-data/v1",
            recording_id=recording_id,
            source=source.manifest.source,
            content_sha256=sha256_bytes(canonical_proposed_card_scene_data_bytes(target_data)),
            input_revision_ids=(source.manifest.revision_id,),
            origin="processor",
            producer=ProcessorProducer(
                run_id=receipt_id,
                processor_type="visible-card-scene-proposal-reflow",
                implementation_id="calibration-reflow/v1",
                model_id=None,
            ),
            coverage={
                "kind": "calibration-reflow-proposed-card-scenes",
                "source_proposal_revision_id": proposal_revision_id,
                "calibration_revision_id": target.calibration_revision_id,
                "calibration_digest": target.calibration_digest,
            },
            created_at=_now(),
        )
        self.calibration_store.publish(
            build_published_calibration_run(
                target,
                diagnostics=target_data.calibration_diagnostics,
            )
        )
        self.revision_store.publish(target_manifest, target_data)
        try:
            current, _target_items, planned = self.reference_service.plan_visible_card_reflow(
                recording_id,
                proposal_revision_id,
                target_proposal_revision_id,
                data.calibration,
                target.to_mapping(),
                force_affected_frame_ids=forced_affected_frame_ids,
            )
        except PipelineReferenceConflict as error:
            raise CalibrationRefinementConflict(str(error)) from error
        except PipelineReferenceInputError as error:
            raise CalibrationRefinementInputError(str(error)) from error
        reinitialized, rebased, affected_frames = planned[1], planned[2], planned[3]
        affected_cards = tuple(sorted(set(preview.changed_card_ids)))
        receipt = CalibrationReflowReceipt.create(
            receipt_id=receipt_id,
            draft_id=draft.draft_id,
            preview_digest=preview_digest,
            source_calibration_revision_id=data.calibration_revision_id,
            source_calibration_digest=data.calibration_digest,
            target_calibration_revision_id=target.calibration_revision_id,
            target_calibration_digest=target.calibration_digest,
            proposal_revision_id=target_proposal_revision_id,
            anchor_command_digests=[command.command_digest for command in draft.commands],
            reinitialized_card_ids=reinitialized,
            rebased_card_ids=rebased,
            affected_frame_ids=affected_frames,
            affected_card_ids=affected_cards,
            preserved_anchor_ids=[
                anchor.anchor_id
                for anchor in draft.anchors
                if anchor.state in {"accepted", "adjusted", "pinned"}
            ],
        )
        self.receipt_store.publish(recording_id, receipt)
        try:
            reference = self.reference_service.apply_visible_card_reflow(
                recording_id,
                source_proposal_revision_id=proposal_revision_id,
                target_proposal_revision_id=target_proposal_revision_id,
                source_calibration=data.calibration,
                target_calibration=target.to_mapping(),
                expected_revision=current.state.draft_revision,
                command_id=receipt_id,
                operator_id=operator_id,
                force_affected_frame_ids=forced_affected_frame_ids,
            )
        except PipelineReferenceConflict as error:
            raise CalibrationRefinementConflict(str(error)) from error
        except PipelineReferenceInputError as error:
            raise CalibrationRefinementInputError(str(error)) from error
        return {
            "schema_version": "table-plane-calibration-refinement/v1",
            "action": "applied",
            "recording_id": recording_id,
            "source_proposal_revision_id": proposal_revision_id,
            "proposal_revision_id": target_proposal_revision_id,
            "calibration_revision_id": target.calibration_revision_id,
            "receipt": receipt.to_mapping(),
            "reference": reference.to_mapping(),
        }

    def _target_calibration(
        self,
        base: Mapping[str, Any],
        draft: CalibrationDraft,
        preview_digest: str,
    ) -> TablePlaneCalibration:
        preview = build_calibration_preview(draft, base)
        candidate = preview.candidate_calibration
        if candidate is None:
            raise CalibrationRefinementInputError("the calibration preview has no candidate")
        target_id = "calibration-refined-" + hashlib.sha256(
            canonical_json_bytes({"draft": draft.draft_digest, "preview": preview_digest})
        ).hexdigest()[:24]
        return TablePlaneCalibration.create(
            calibration_revision_id=target_id,
            recording_id=draft.recording_id,
            source_revision=candidate["source_revision"],
            frame_width=candidate["frame_width"],
            frame_height=candidate["frame_height"],
            image_to_table=candidate["image_to_table"],
            table_to_image=candidate["table_to_image"],
            card_short_size=candidate["card_short_size"],
            card_long_size=candidate["card_long_size"],
            candidate_receipt_digests=candidate["candidate_receipt_digests"],
            diagnostics={
                **candidate["diagnostics"],
                "refinement_preview_digest": preview_digest,
                "source_calibration_revision_id": draft.base_calibration_revision_id,
            },
        )

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
    "CalibrationRefinementConflict",
    "CalibrationRefinementInputError",
    "CalibrationRefinementNotFound",
    "CalibrationRefinementService",
]
