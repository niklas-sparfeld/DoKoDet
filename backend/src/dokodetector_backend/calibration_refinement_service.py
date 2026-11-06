"""Backend persistence and calculation service for 0073 calibration previews."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

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
    exclude_anchors_in_reviewed_ignore_regions,
    reflow_reference_items,
)
from doko_operations.card_plane_geometry import TablePlaneCalibration
from doko_operations.pipeline_data import (
    ProcessorProducer,
    canonical_json_bytes,
    parse_source,
    sha256_bytes,
)
from doko_operations.pipeline_reference import (
    PipelineReferenceDraft,
    PipelineReferenceState,
    ReferenceDraftItem,
)
from doko_operations.proposed_card_scene_processor import (
    build_proposed_card_scene_data,
    visible_card_data_to_local_result,
)
from table_evidence_analyzer.card_scene_contract import (
    AnchorCommand,
    CalibrationDraft,
    CalibrationFailure,
    CalibrationPreview,
    CalibrationReflowReceipt,
)
from table_evidence_analyzer.pipeline_data import (
    PROPOSED_CARD_SCENE_DATA_SCHEMA_VERSION,
    ProposedCardSceneData,
    VisibleCardData,
    canonical_proposed_card_scene_data_bytes,
)

from dokodetector_backend.calibration_reflow_context import build_calibration_reflow_context
from dokodetector_backend.pipeline_item_provenance import _items
from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
from dokodetector_backend.pipeline_node_store import NodeConflict, PipelineNodeStore
from dokodetector_backend.pipeline_node_transactions import PipelineNodeTransactions
from dokodetector_backend.pipeline_proposal_seed import seed_proposal_items
from dokodetector_backend.pipeline_reference_errors import (
    PipelineReferenceConflict,
    PipelineReferenceInputError,
)
from dokodetector_backend.pipeline_reference_handlers import build_reference_handlers


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
        draft_store: CalibrationDraftStore | None = None,
        node_store: PipelineNodeStore | None = None,
    ) -> None:
        self.node_store = node_store
        self.node_transactions = (
            None if node_store is None else PipelineNodeTransactions(node_store)
        )
        self.store = draft_store or CalibrationDraftStore(settings.operations_root)
        self.calibration_store = CalibrationRevisionStore(settings.operations_root)
        self.receipt_store = CalibrationReflowReceiptStore(settings.operations_root)

    def _publish_node_reflow(
        self,
        recording_id: str,
        current: Any,
        items: tuple[Any, ...],
        target_proposal_revision_id: str,
        receipt_id: str,
        impact: tuple[dict[str, Any], ...] | None = None,
    ) -> None:
        """Publish migrated visible-card and scene drafts as one recoverable update."""
        if self.node_store is None or self.node_transactions is None:
            raise CalibrationRefinementInputError(
                "calibration reflow requires the active pipeline node store"
            )
        from dokodetector_backend.lineage_draft_projection import project_draft, project_scene_frame
        from dokodetector_backend.virtual_scene_data import validate_virtual_scenes

        key = f"maintained_draft/{recording_id}/visible_cards"
        visible_node_id = str(uuid5(NAMESPACE_URL, f"lineage-draft:{key}"))
        scene_node_id = str(uuid5(NAMESPACE_URL, f"lineage-draft-scenes:{key}"))
        visible_node = self.node_store.get(visible_node_id)
        visible_revision = self.node_store.read_revision_record(
            visible_node_id, visible_node.head_revision_id
        )
        if visible_revision.metadata.get("calibration_reflow", {}).get("receipt_id") == receipt_id:
            try:
                scene_node = self.node_store.get(scene_node_id)
            except FileNotFoundError:
                scene_node = None
            if scene_node is not None:
                scene_revision = self.node_store.read_revision_record(
                    scene_node_id, scene_node.head_revision_id
                )
                if (
                    scene_revision.metadata.get("calibration_reflow", {}).get("receipt_id")
                    != receipt_id
                ):
                    raise CalibrationRefinementConflict(
                        "the visible-card and virtual-scene reflow heads do not match"
                    )
            return
        source_projection = project_draft(current.draft)
        source_context = visible_revision.metadata.get("calibration_reflow_context")
        if (
            visible_revision.metadata.get("migration", {}).get("legacy_key") != key
            or not isinstance(source_context, dict)
            or source_context.get("schema_version") != "calibration-reflow-context/v1"
            or source_context.get("proposal_revision_id") != current.draft.proposal_revision_id
            or source_context.get("source_revision_id") != current.draft.source_revision_id
            or source_projection["content"] != visible_revision.content
        ):
            raise CalibrationRefinementConflict(
                "the migrated visible-card draft differs from the maintained reference"
            )

        target_draft = replace(
            current.draft,
            revision=current.draft.revision + 1,
            items=items,
            proposal_revision_id=target_proposal_revision_id,
            coverage=None,
            impact=current.draft.impact if impact is None else impact,
            updated_at=_now(),
        )
        projection = project_draft(target_draft)
        digest = sha256_bytes(canonical_json_bytes(target_draft.to_mapping()))
        visible_metadata = dict(visible_revision.metadata)
        visible_metadata["migration"] = {
            **visible_metadata.get("migration", {}),
            "draft_sha256": digest,
            "updated_at": target_draft.updated_at,
        }
        visible_metadata["calibration_reflow_context"] = build_calibration_reflow_context(
            target_draft
        )
        visible_metadata["scene_only_frame_ids"] = projection["scene_only_items"]
        visible_metadata["calibration_reflow"] = {
            "receipt_id": receipt_id,
            "proposal_revision_id": target_proposal_revision_id,
        }
        visible_metadata["item_provenance"] = {
            "version": 1,
            "items": _items(projection["content"], projection["pointers"]),
            "changes": [],
        }
        node_updates = [
            {
                "node_id": visible_node_id,
                "expected_revision_id": visible_revision.revision_id,
                "revision_id": str(
                    uuid5(NAMESPACE_URL, f"calibration-reflow:{receipt_id}:visible")
                ),
                "content": projection["content"],
                "metadata": visible_metadata,
            }
        ]

        scene_frames = []
        for item in target_draft.items:
            if item.review_state == "rejected" or item.item.get("card_scene") is None:
                continue
            projected = project_scene_frame(dict(item.item))
            frame = projected["content"]["frames"][0]
            scene_frames.append(frame)
        scene_content = validate_virtual_scenes(
            {"schema_version": "virtual-scene-data/v1", "frames": scene_frames}
        )
        try:
            scene_node = self.node_store.get(scene_node_id)
        except FileNotFoundError:
            if scene_frames:
                raise CalibrationRefinementInputError(
                    "the migrated virtual-scene draft is missing"
                ) from None
        else:
            scene_revision = self.node_store.read_revision_record(
                scene_node_id, scene_node.head_revision_id
            )
            if scene_revision.metadata.get("migration", {}).get("legacy_key") != key:
                raise CalibrationRefinementConflict(
                    "the migrated virtual-scene draft has a different source"
                )
            scene_metadata = dict(scene_revision.metadata)
            scene_metadata["migration"] = {
                **scene_metadata.get("migration", {}),
                "draft_sha256": digest,
                "updated_at": target_draft.updated_at,
            }
            scene_metadata["calibration_reflow"] = {
                "receipt_id": receipt_id,
                "proposal_revision_id": target_proposal_revision_id,
            }
            pointers = {
                frame["frame_id"]: f"/frames/{index}"
                for index, frame in enumerate(scene_content["frames"])
            }
            scene_metadata["item_provenance"] = {
                "version": 1,
                "items": _items(scene_content, pointers),
                "changes": [],
            }
            node_updates.append(
                {
                    "node_id": scene_node_id,
                    "expected_revision_id": scene_revision.revision_id,
                    "revision_id": str(
                        uuid5(NAMESPACE_URL, f"calibration-reflow:{receipt_id}:scenes")
                    ),
                    "content": scene_content,
                    "metadata": scene_metadata,
                }
            )
        self.node_transactions.commit(
            receipt_id,
            node_updates=node_updates,
            selection_updates=[],
        )

    def _node_reflow_reference(
        self, recording_id: str, target_proposal_revision_id: str
    ) -> dict[str, Any] | None:
        """Return the published draft view when a previous apply already committed."""
        if self.node_store is None:
            return None
        key = f"maintained_draft/{recording_id}/visible_cards"
        node_id = str(uuid5(NAMESPACE_URL, f"lineage-draft:{key}"))
        try:
            node = self.node_store.get(node_id)
            revision = self.node_store.read_revision_record(node_id, node.head_revision_id)
        except FileNotFoundError:
            return None
        if (
            revision.metadata.get("migration", {}).get("legacy_key") != key
            or revision.metadata.get("calibration_reflow", {}).get("proposal_revision_id")
            != target_proposal_revision_id
        ):
            return None
        current_node = self._current_node_reference(recording_id, target_proposal_revision_id)
        return {
            "state": current_node.state.to_mapping(),
            "draft": current_node.draft.to_mapping(),
        }

    def _current_node_reference(
        self,
        recording_id: str,
        proposal_revision_id: str,
        *,
        allow_missing: bool = False,
    ):
        if self.node_store is None:
            raise CalibrationRefinementInputError("the active pipeline node store is unavailable")
        key = f"maintained_draft/{recording_id}/visible_cards"
        node_id = str(uuid5(NAMESPACE_URL, f"lineage-draft:{key}"))
        try:
            node = self.node_store.get(node_id)
            revision = self.node_store.read_revision_record(node_id, node.head_revision_id)
        except FileNotFoundError as error:
            if allow_missing:
                return None
            raise CalibrationRefinementInputError(
                "the canonical visible-card draft is missing; reload the pipeline"
            ) from error
        if node.content_type != "visible_cards" or node.source.get("recording_id") != recording_id:
            raise CalibrationRefinementConflict(
                "the canonical visible-card draft has changed source"
            )
        context = revision.metadata.get("calibration_reflow_context")
        if not isinstance(context, dict) or context.get("schema_version") != (
            "calibration-reflow-context/v1"
        ):
            raise CalibrationRefinementInputError(
                "the canonical calibration reflow context is missing"
            )
        try:
            actual_proposal_id = context.get("proposal_revision_id") or proposal_revision_id
            if actual_proposal_id != proposal_revision_id:
                raise CalibrationRefinementConflict(
                    "the canonical visible-card draft uses a different proposal revision"
                )
            _proposal, source, _data = self._proposal(recording_id, actual_proposal_id)
            review_records = PipelineNodeReviews(self.node_store).applicable_for_revision(
                node_id, revision.revision_id
            )
            item_decisions = {}
            for review in review_records:
                if review["kind"] == "item":
                    item_decisions.setdefault(review["item_id"], review["decision"])
            base_item_ids = context.get("base_item_ids", {})
            affected_item_ids = set(context.get("affected_item_ids", []))
            items_by_id = {}
            for outcome in VisibleCardData.from_mapping(revision.content).outcomes:
                decision = item_decisions.get(outcome.event_id, "pending")
                if decision not in {
                    "accepted",
                    "corrected",
                    "rejected",
                    "added",
                    "empty",
                    "unusable",
                    "identity_unusable",
                    "source_problem",
                    "face_down",
                    "pending",
                }:
                    decision = "pending"
                if outcome.event_id in affected_item_ids and decision in {"pending", "accepted"}:
                    decision = "affected"
                base_item_id = base_item_ids.get(outcome.event_id)
                if decision not in {
                    "accepted",
                    "corrected",
                    "rejected",
                    "empty",
                    "unusable",
                    "identity_unusable",
                    "source_problem",
                }:
                    base_item_id = None
                item = ReferenceDraftItem.from_mapping(
                    {
                        "item_id": outcome.event_id,
                        "base_item_id": base_item_id,
                        "review_state": decision,
                        "item": outcome.to_mapping(),
                    }
                )
                items_by_id[item.item_id] = item
            for raw_item in context.get("excluded_items", []):
                item = ReferenceDraftItem.from_mapping(raw_item)
                items_by_id.setdefault(item.item_id, item)
            items = tuple(items_by_id.values())
            current_reviews = PipelineNodeReviews(self.node_store).list_for_revision(
                node_id, revision.revision_id
            )
            coverage_review = next(
                (review for review in current_reviews if review["kind"] == "coverage"), None
            )
            overall_review = next(
                (review for review in current_reviews if review["kind"] == "overall"), None
            )
            updated_at = context.get("updated_at")
            source_revision_id = context.get("source_revision_id")
            draft_revision = context.get("draft_revision")
            if (
                not isinstance(updated_at, str)
                or source_revision_id != source.manifest.revision_id
                or isinstance(draft_revision, bool)
                or not isinstance(draft_revision, int)
            ):
                raise CalibrationRefinementInputError(
                    "the canonical calibration reflow context is invalid"
                )
            state = PipelineReferenceState(
                recording_id=recording_id,
                content_type="visible_cards",
                draft_revision=draft_revision,
                draft_state=(
                    "completed"
                    if overall_review is not None and overall_review["decision"] == "complete"
                    else "draft"
                ),
                source_revision_id=source_revision_id,
                selected_completed_revision_id=None,
                updated_at=updated_at,
            )
            draft = PipelineReferenceDraft.from_mapping(
                {
                    "schema_version": "pipeline-reference-draft/v2",
                    "recording_id": recording_id,
                    "content_type": "visible_cards",
                    "revision": draft_revision,
                    "source_revision_id": source.manifest.revision_id,
                    "items": [item.to_mapping() for item in items],
                    "coverage": None if coverage_review is None else coverage_review["coverage"],
                    "impact": context.get("impact", []),
                    "updated_at": updated_at,
                    "proposal_revision_id": actual_proposal_id,
                }
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, CalibrationRefinementError):
                raise
            raise CalibrationRefinementInputError(
                f"the canonical visible-card draft is invalid: {error}"
            ) from error
        if state.recording_id != recording_id or state.content_type != "visible_cards":
            raise CalibrationRefinementConflict(
                "the canonical visible-card state has changed source"
            )
        return SimpleNamespace(state=state, draft=draft)

    def _publish_target_proposal_node(
        self,
        recording_id: str,
        revision_id: str,
        source: Any,
        data: ProposedCardSceneData,
        calibration: TablePlaneCalibration,
        source_proposal_revision_id: str,
    ) -> None:
        if self.node_store is None:
            raise CalibrationRefinementInputError("the active pipeline node store is unavailable")
        node_id = "data-" + hashlib.sha256(revision_id.encode("utf-8")).hexdigest()[:32]
        digest = sha256_bytes(canonical_proposed_card_scene_data_bytes(data))
        producer = ProcessorProducer(
            run_id=revision_id.removeprefix("card-scene-reflow-"),
            processor_type="visible-card-scene-proposal-reflow",
            implementation_id="calibration-reflow/v1",
            model_id=None,
        )
        metadata = {
            "origin": "processor",
            "legacy_revision_id": revision_id,
            "legacy_content_schema": PROPOSED_CARD_SCENE_DATA_SCHEMA_VERSION,
            "legacy_content_sha256": digest,
            "input_revision_ids": [source.manifest.revision_id],
            "producer": producer.to_mapping(),
            "coverage": {
                "kind": "calibration-reflow-proposed-card-scenes",
                "source_proposal_revision_id": source_proposal_revision_id,
                "calibration_revision_id": calibration.calibration_revision_id,
                "calibration_digest": calibration.calibration_digest,
            },
            "calibration_reflow": {"source_proposal_revision_id": source_proposal_revision_id},
        }
        existing = self._find_node_revision(revision_id, "card_scene_proposals")
        if existing is not None:
            node, revision = existing
            if (
                node.node_id != node_id
                or revision.content != data.to_mapping()
                or revision.content_sha256 != digest
                or revision.metadata.get("input_revision_ids") != [source.manifest.revision_id]
            ):
                raise CalibrationRefinementConflict(
                    "the target proposal node conflicts with this calibration reflow"
                )
            return
        try:
            self.node_store.create(
                node_id,
                f"Calibration reflow {recording_id}",
                "card_scene_proposals",
                source.manifest.source.to_mapping(),
                data.to_mapping(),
                metadata,
                revision_id=revision_id,
            )
        except NodeConflict as error:
            raise CalibrationRefinementConflict(
                "the target proposal node already exists with different content"
            ) from error

    def _reflow_impact(self, recording_id: str, current: Any, items: tuple[Any, ...]):
        """Keep the same correction-impact calculation as maintained-reference apply."""
        handler = build_reference_handlers(
            source_for=lambda *_: None,
            selected_revision=lambda *_: None,
        )["visible_cards"]
        handler.validate_draft_items(
            recording_id,
            current.draft.source_revision_id,
            list(items),
        )
        impact = list(current.draft.impact)
        previous_by_id = {item.item_id: item for item in current.draft.items}
        for item in items:
            previous = previous_by_id.get(item.item_id)
            if previous is not None:
                impact.extend(handler.correction_impact(recording_id, previous, item))
        return tuple(impact)

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
        self._require_supported_calibration_geometry(data)
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
            try:
                draft = build_calibration_draft(
                    draft_id=draft_id,
                    recording_id=recording_id,
                    detector_revision_id=source.manifest.revision_id,
                    detector_revision_digest=source.manifest.content_sha256,
                    base_calibration=data.calibration,
                    anchors=anchors,
                    source_frame_digests=frame_digests,
                )
            except CalibrationRefinementError as build_error:
                raise CalibrationRefinementInputError(
                    "the proposal uses an unsupported calibration geometry; "
                    "rerun the card-scene proposal with the current geometry before "
                    "preparing calibration refinement"
                ) from build_error
            self.store.publish_initial(draft)
            self.store.publish(draft)
        self._require_current_source(draft, source)
        return self._response(
            recording_id, proposal_revision_id, draft, data, include_frame_scenes=False
        )

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
        return self._response(
            recording_id,
            proposal_revision_id,
            draft,
            data,
            include_frame_scenes=False,
        )

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
            return self._response(
                recording_id,
                proposal_revision_id,
                draft,
                data,
                include_frame_scenes=False,
            )
        if draft.revision != expected_revision:
            raise CalibrationRefinementInputError(
                "calibration draft changed; "
                f"expected revision {expected_revision}, current {draft.revision}"
            )
        updated = apply_anchor_command_to_draft(draft, command)
        self.store.publish(updated)
        # Anchor edits need a quick acknowledgement. The full recording-wide impact
        # preview is refreshed by the client after the operator pauses editing.
        return self._response(
            recording_id,
            proposal_revision_id,
            updated,
            data,
            include_frame_scenes=False,
        )

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
        return self._response(
            recording_id,
            proposal_revision_id,
            draft,
            data,
            include_frame_scenes=False,
        )

    @staticmethod
    def _require_current_source(draft: CalibrationDraft, source: Any) -> None:
        if (
            draft.detector_revision_id != source.manifest.revision_id
            or draft.detector_revision_digest != source.manifest.content_sha256
        ):
            raise CalibrationRefinementInputError(
                "calibration draft uses a different detector revision; start a new mapping preview"
            )

    @staticmethod
    def _require_supported_calibration_geometry(data: ProposedCardSceneData) -> None:
        calibration = data.calibration
        calibration_mapping = (
            calibration.to_mapping()
            if isinstance(calibration, TablePlaneCalibration)
            else calibration
        )
        try:
            TablePlaneCalibration.from_mapping(calibration_mapping)
        except (TypeError, ValueError) as error:
            raise CalibrationRefinementInputError(
                "the proposal uses an unsupported calibration geometry; "
                "rerun the card-scene proposal with the current geometry before "
                "preparing calibration refinement"
            ) from error

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
        frame_scenes = self._frame_scenes(recording_id, proposal_revision_id, data)
        effective_draft = exclude_anchors_in_reviewed_ignore_regions(draft, frame_scenes)
        receipt_id = (
            "reflow-"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "draft_id": effective_draft.draft_id,
                        "draft_digest": effective_draft.draft_digest,
                        "preview_digest": preview_digest,
                    }
                )
            ).hexdigest()[:24]
        )
        try:
            previous_receipt = self.receipt_store.load(recording_id, receipt_id)
        except CalibrationRefinementError:
            previous_receipt = None
        if previous_receipt is not None:
            reference = self._current_node_reference(recording_id, proposal_revision_id)
            if reference.draft.proposal_revision_id == previous_receipt.proposal_revision_id:
                return {
                    "schema_version": "table-plane-calibration-refinement/v1",
                    "action": "applied",
                    "recording_id": recording_id,
                    "source_proposal_revision_id": proposal_revision_id,
                    "proposal_revision_id": previous_receipt.proposal_revision_id,
                    "calibration_revision_id": previous_receipt.target_calibration_revision_id,
                    "receipt": previous_receipt.to_mapping(),
                    "reference": {
                        "state": reference.state.to_mapping(),
                        "draft": reference.draft.to_mapping(),
                    },
                }
            node_reference = self._node_reflow_reference(
                recording_id, previous_receipt.proposal_revision_id
            )
            if node_reference is not None:
                return {
                    "schema_version": "table-plane-calibration-refinement/v1",
                    "action": "applied",
                    "recording_id": recording_id,
                    "source_proposal_revision_id": proposal_revision_id,
                    "proposal_revision_id": previous_receipt.proposal_revision_id,
                    "calibration_revision_id": previous_receipt.target_calibration_revision_id,
                    "receipt": previous_receipt.to_mapping(),
                    "reference": node_reference,
                }
        preview = build_calibration_preview(
            effective_draft,
            data.calibration,
            frame_scenes=frame_scenes,
        )
        if preview.preview_digest != preview_digest:
            raise CalibrationRefinementInputError(
                "the calibration preview changed; reload the current preview"
            )
        if preview.candidate_calibration is None or (
            preview.failure is not None
            and (preview.failure.code != "reviewed_displacement_exceeded" or not confirm_affected)
        ):
            action = "inspect and correct the blocked calibration gate"
            if preview.failure is not None:
                action = preview.failure.action
            raise CalibrationRefinementInputError(action)
        current_reference = self._current_node_reference(recording_id, proposal_revision_id)
        if current_reference.draft.proposal_revision_id != proposal_revision_id:
            raise CalibrationRefinementConflict(
                "the canonical visible-card draft uses a different proposal revision"
            )
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
            effective_draft,
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
                "anchor_command_digests": [command.command_digest for command in draft.commands],
            },
        )
        target_proposal_revision_id = f"card-scene-reflow-{receipt_id}"
        self.calibration_store.publish(
            build_published_calibration_run(
                target,
                diagnostics=target_data.calibration_diagnostics,
            )
        )
        self._publish_target_proposal_node(
            recording_id,
            target_proposal_revision_id,
            source,
            target_data,
            target,
            proposal_revision_id,
        )
        try:
            _target_proposal, target_source, target_data = self._proposal(
                recording_id, target_proposal_revision_id
            )
            target_items = seed_proposal_items(
                recording_id,
                target_source,
                target_data,
                target_proposal_revision_id,
                current_reference.draft.items,
            )
            planned = reflow_reference_items(
                current_reference.draft.items,
                target_items,
                data.calibration,
                target.to_mapping(),
                target_proposal_revision_id=target_proposal_revision_id,
                target_proposal_data_digest=target_data.data_digest,
                force_affected_frame_ids=forced_affected_frame_ids,
            )
        except PipelineReferenceConflict as error:
            raise CalibrationRefinementConflict(str(error)) from error
        except PipelineReferenceInputError as error:
            raise CalibrationRefinementInputError(str(error)) from error
        current = current_reference
        reinitialized, rebased, affected_frames = planned[1], planned[2], planned[3]
        reflow_impact = self._reflow_impact(recording_id, current, planned[0])
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
            self._publish_node_reflow(
                recording_id,
                current,
                planned[0],
                target_proposal_revision_id,
                receipt_id,
                reflow_impact,
            )
        except NodeConflict as error:
            raise CalibrationRefinementConflict(str(error)) from error
        except FileNotFoundError as error:
            raise CalibrationRefinementInputError(
                "the migrated visible-card draft is missing"
            ) from error
        except ValueError as error:
            if isinstance(error, CalibrationRefinementError):
                raise
            raise CalibrationRefinementInputError(str(error)) from error
        timestamp = _now()
        reference_draft = replace(
            current.draft,
            revision=current.draft.revision + 1,
            items=planned[0],
            proposal_revision_id=target_proposal_revision_id,
            coverage=None,
            impact=reflow_impact,
            updated_at=timestamp,
        )
        reference_state = replace(
            current.state,
            draft_revision=reference_draft.revision,
            draft_state="draft",
            updated_at=timestamp,
        )
        return {
            "schema_version": "table-plane-calibration-refinement/v1",
            "action": "applied",
            "recording_id": recording_id,
            "source_proposal_revision_id": proposal_revision_id,
            "proposal_revision_id": target_proposal_revision_id,
            "calibration_revision_id": target.calibration_revision_id,
            "receipt": receipt.to_mapping(),
            "reference": {
                "state": reference_state.to_mapping(),
                "draft": reference_draft.to_mapping(),
            },
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
        target_id = (
            "calibration-refined-"
            + hashlib.sha256(
                canonical_json_bytes({"draft": draft.draft_digest, "preview": preview_digest})
            ).hexdigest()[:24]
        )
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
        proposal = self._find_node_revision(proposal_revision_id, "card_scene_proposals")
        if proposal is None:
            raise CalibrationRefinementInputError("proposal node revision was not found")
        proposal_node, proposal_revision = proposal
        try:
            proposal_content = ProposedCardSceneData.from_mapping(proposal_revision.content)
        except (TypeError, ValueError) as error:
            raise CalibrationRefinementInputError("proposal node content is invalid") from error
        if (
            sha256_bytes(canonical_proposed_card_scene_data_bytes(proposal_content))
            != proposal_revision.content_sha256
        ):
            raise CalibrationRefinementInputError("proposal node content digest is invalid")
        proposal_metadata = proposal_revision.metadata
        source_ids = proposal_metadata.get("input_revision_ids")
        producer = proposal_metadata.get("producer")
        if (
            proposal_node.source.get("recording_id") != recording_id
            or proposal_metadata.get("origin") != "processor"
            or not isinstance(producer, dict)
            or producer.get("processor_type")
            not in {"visible-card-scene-proposal", "visible-card-scene-proposal-reflow"}
            or not isinstance(source_ids, list)
        ):
            raise CalibrationRefinementInputError("proposal node lineage is invalid")
        if len(source_ids) != 1:
            raise CalibrationRefinementInputError("proposal revision must have one detector input")
        proposal_manifest = SimpleNamespace(
            recording_id=recording_id,
            content_type=proposal_node.content_type,
            revision_id=proposal_revision.revision_id,
            input_revision_ids=tuple(source_ids),
            source=parse_source(proposal_node.source),
        )
        if proposal_manifest.content_type != "card_scene_proposals":
            raise CalibrationRefinementInputError("proposal_revision_id must reference card scenes")
        if len(source_ids) != 1:
            raise CalibrationRefinementInputError("proposal revision must have one detector input")
        source_node_revision = self._find_node_revision(source_ids[0], "visible_cards")
        if source_node_revision is None:
            raise CalibrationRefinementInputError("proposal detector node revision was not found")
        source_node, source_revision = source_node_revision
        try:
            source_content = VisibleCardData.from_mapping(source_revision.content)
        except (TypeError, ValueError) as error:
            raise CalibrationRefinementInputError(
                "proposal detector input is not visible-card data"
            ) from error
        source_id = source_ids[0]
        digest = source_revision.content_sha256
        source_producer = source_revision.metadata.get("producer")
        if (
            source_id != proposal_content.detector_revision_id
            or digest != proposal_content.detector_revision_digest
            or parse_source(source_node.source).recording_id != recording_id
            or source_revision.metadata.get("origin") != "processor"
            or not isinstance(source_producer, dict)
            or source_producer.get("processor_type") != "visible-card-detection"
            or not isinstance(source_producer.get("model_id"), str)
            or not source_producer["model_id"].startswith("local-rfdetr-")
        ):
            raise CalibrationRefinementInputError(
                "proposal detector digest or node lineage is invalid"
            )
        source = SimpleNamespace(
            manifest=SimpleNamespace(
                recording_id=recording_id,
                content_type="visible_cards",
                revision_id=source_id,
                content_sha256=digest,
                source=parse_source(source_node.source),
            ),
            content=source_content,
        )
        return (proposal_node, proposal_revision), source, proposal_content

    def _find_node_revision(self, revision_id: str, content_type: str):
        if self.node_store is None:
            return None
        for node in self.node_store.list_nodes():
            if node.content_type != content_type:
                continue
            try:
                revision = self.node_store.read_revision_record(node.node_id, revision_id)
            except FileNotFoundError:
                continue
            return node, revision
        return None

    def _response(
        self,
        recording_id: str,
        proposal_revision_id: str,
        draft: CalibrationDraft,
        data: ProposedCardSceneData,
        *,
        include_frame_scenes: bool = True,
    ) -> dict[str, Any]:
        if not include_frame_scenes:
            return self._pending_response(recording_id, proposal_revision_id, draft)
        frame_scenes = self._frame_scenes(recording_id, proposal_revision_id, data)
        effective_draft = exclude_anchors_in_reviewed_ignore_regions(draft, frame_scenes)
        preview = build_calibration_preview(
            effective_draft,
            data.calibration,
            frame_scenes=frame_scenes if include_frame_scenes else (),
        )
        contributions = []
        from table_evidence_analyzer.card_scene_contract import anchor_fit_contributions

        contributions.extend(
            item.to_mapping() for item in anchor_fit_contributions(effective_draft.anchors)
        )
        return {
            "schema_version": "table-plane-calibration-refinement/v1",
            "recording_id": recording_id,
            "proposal_revision_id": proposal_revision_id,
            "draft": effective_draft.to_mapping(),
            "preview": preview.to_mapping(),
            "preview_complete": include_frame_scenes,
            "anchor_contributions": contributions,
        }

    @staticmethod
    def _pending_response(
        recording_id: str,
        proposal_revision_id: str,
        draft: CalibrationDraft,
    ) -> dict[str, Any]:
        """Return draft state without fitting a calibration candidate."""

        pending = CalibrationPreview.create(
            preview_id="preview-pending-" + draft.draft_digest[:24],
            draft_id=draft.draft_id,
            base_calibration_revision_id=draft.base_calibration_revision_id,
            base_calibration_digest=draft.base_calibration_digest,
            candidate_calibration=None,
            gates=(),
            status="blocked",
            failure=CalibrationFailure.create(
                code="preview_not_run",
                message="The recording-wide calibration preview has not been run.",
                action=(
                    "Update the recording-wide preview when you are ready to "
                    "calculate recalibration impact."
                ),
            ),
            fit_residual=0.0,
            accepted_anchor_count=sum(
                1 for anchor in draft.anchors if anchor.state in {"accepted", "adjusted", "pinned"}
            ),
            rejected_candidate_count=0,
            held_out_alignment_change_px=0.0,
            changed_frame_ids=(),
            changed_card_ids=(),
            max_source_pixel_displacement=0.0,
            most_affected_frame_ids=(),
        )
        return {
            "schema_version": "table-plane-calibration-refinement/v1",
            "recording_id": recording_id,
            "proposal_revision_id": proposal_revision_id,
            "draft": draft.to_mapping(),
            "preview": pending.to_mapping(),
            "preview_complete": False,
            "anchor_contributions": [],
        }

    def _frame_scenes(
        self, recording_id: str, proposal_revision_id: str, data: ProposedCardSceneData
    ) -> tuple[dict[str, Any], ...]:
        reference = self._current_node_reference(
            recording_id, proposal_revision_id, allow_missing=True
        )
        if reference is not None and reference.draft.items:
            return tuple({"item_id": item.item_id, **item.item} for item in reference.draft.items)
        return tuple(
            {
                "frame_id": frame.frame_id,
                "scene": frame.proposal.initialized_scene if frame.proposal is not None else None,
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
