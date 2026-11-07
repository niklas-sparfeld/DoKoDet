"""Exact source revision validation for visual identity crop inputs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from doko_operations.card_plane_geometry import (
    CardPlaneGeometryError,
    ReviewedCardScene,
    validate_pose_scene_candidate_view,
)
from doko_operations.pipeline_data import ProcessorRunRequest, canonical_json_bytes, sha256_bytes
from table_evidence_analyzer.card_scene_contract import CardSceneDraft
from table_evidence_analyzer.pipeline_data import (
    ReviewedVisibleRegionGeometry,
    VisibleCardData,
    VisibleCardOutcome,
)
from table_evidence_analyzer.visual_identity_crop_input import (
    ReviewedVirtualCardLineage,
    VisualIdentityCropInputError,
    VisualIdentityCropInputItem,
)

from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
from dokodetector_backend.pipeline_revision_store import StoredPipelineRevision
from dokodetector_backend.pipeline_storage import PipelineNotFound


class CropSourceError(ValueError):
    """Selected crop source failed exact revision validation."""


class VisualIdentityCropSources:
    def __init__(
        self,
        *,
        node_store: Any,
        selection_store: Any,
        recording_store: Any,
        run_store: Any,
        calibration_store: Any,
    ):
        self.node_store = node_store
        self.selection_store = selection_store
        self.recording_store = recording_store
        self.run_store = run_store
        self.calibration_store = calibration_store

    def _canonical_crop_source(
        self,
        revision: StoredPipelineRevision,
        input_node_ref: Mapping[str, str] | None = None,
    ) -> tuple[str, str, str]:
        """Return canonical node identity and digest for one crop source revision."""
        if self.node_store is None:
            raise CropSourceError("Canonical node storage is unavailable.")
        ref = (
            dict(input_node_ref)
            if input_node_ref is not None
            else self._canonical_input_node_ref(
                revision.manifest.revision_id, revision.manifest.content_type
            )
        )
        node = self.node_store.get(ref["node_id"])
        node_revision = self.node_store.read_revision(ref["node_id"], ref["revision_id"])
        if (
            node.content_type != revision.manifest.content_type
            or node.source != revision.manifest.source.to_mapping()
            or node_revision.revision_id != revision.manifest.revision_id
            or sha256_bytes(canonical_json_bytes(node_revision.content))
            != node_revision.content_sha256
        ):
            raise CropSourceError(
                "The canonical crop source does not match its execution revision."
            )
        payload = {
            "schema_version": "pipeline-node-revision/v1",
            "node_id": node_revision.node_id,
            "revision_id": node_revision.revision_id,
            "parent_revision_id": node_revision.parent_revision_id,
            "content": node_revision.content,
            "content_sha256": node_revision.content_sha256,
            "metadata": node_revision.metadata,
            "created_at": node_revision.created_at,
        }
        return ref["node_id"], ref["revision_id"], sha256_bytes(canonical_json_bytes(payload))

    def _canonical_input_node_ref(self, revision_id: str, content_type: str) -> dict[str, str]:
        if self.node_store is None:
            raise CropSourceError("Canonical node storage is unavailable.")
        try:
            node, revision = self.node_store.find_revision(revision_id)
        except FileNotFoundError as error:
            raise CropSourceError(
                "The selected input has no exact canonical node revision."
            ) from error
        if node.content_type != content_type:
            raise CropSourceError("The selected node has the wrong content type.")
        return {
            "node_id": node.node_id,
            "revision_id": revision.revision_id,
            "revision_policy": "historical",
        }

    def canonical_input_revision(self, request: ProcessorRunRequest) -> StoredPipelineRevision:
        """Load identity input content from its exact node revision."""
        refs = request.input_node_refs
        if self.node_store is None or refs is None or len(refs) != 1:
            raise CropSourceError("An exact canonical input is required.")
        ref = refs[0]
        try:
            stored = self.selection_store.read_node_revision(ref["node_id"], ref["revision_id"])
            node = self.node_store.get(ref["node_id"])
        except (FileNotFoundError, KeyError, PipelineNotFound, ValueError) as error:
            raise CropSourceError("The canonical input is unavailable.") from error
        if (
            stored.manifest.revision_id != request.input_revision_ids[0]
            or node.source != request.source.to_mapping()
            or (
                ref["revision_policy"] == "current_head"
                and node.head_revision_id != ref["revision_id"]
            )
        ):
            raise CropSourceError("The canonical input no longer matches the run.")
        return stored

    def _is_selected_completed_node_revision(
        self, recording_id: str, node_id: str, revision_id: str
    ) -> bool:
        """Check the execution pointer and completion decision for one exact node revision."""
        if self.node_store is None:
            return False
        try:
            selection = self.selection_store.get_exact(recording_id, "visible_cards")
            node = self.node_store.get(node_id)
            self.node_store.read_revision(node_id, revision_id)
            reviews = PipelineNodeReviews(self.node_store).list_for_revision(node_id, revision_id)
        except (FileNotFoundError, KeyError, OSError, TypeError, ValueError):
            return False
        if (
            selection is None
            or selection.selected_completed_reference
            != {"node_id": node_id, "revision_id": revision_id}
            or node.content_type != "visible_cards"
            or node.source.get("recording_id") != recording_id
        ):
            return False
        return any(
            review["kind"] == "overall" and review["decision"] == "complete" for review in reviews
        )

    @staticmethod
    def _reviewed_virtual_card_items(
        content: VisibleCardData,
        *,
        fallback_scene_revision_id: str,
    ) -> tuple[list[VisualIdentityCropInputItem], ReviewedVirtualCardLineage]:
        """Use only validated, materialized reviewed scene regions and retain their lineage."""

        items: list[VisualIdentityCropInputItem] = []
        scenes: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []
        scene_revision_ids: set[str] = set()
        calibration_revision_ids: set[str] = set()
        calibration_digests: set[str] = set()
        for outcome in content.outcomes:
            if outcome.status != "detected":
                continue
            if outcome.card_scene is None:
                continue
            if outcome.frame_identity is None:
                raise VisualIdentityCropInputError(
                    "a reviewed virtual-card frame has no exact source identity"
                )
            envelope = outcome.card_scene
            if not isinstance(envelope, CardSceneDraft):
                raise VisualIdentityCropInputError(
                    "reviewed virtual-card input needs a versioned reviewed scene"
                )
            if (
                envelope.reviewed is None
                or envelope.projection is None
                or envelope.derived_region_receipt is None
            ):
                raise VisualIdentityCropInputError(
                    "the reviewed card scene has incomplete derivation lineage"
                )
            scene = ReviewedCardScene.from_mapping(envelope.reviewed.scene)
            if envelope.proposal_revision_id is not None:
                scene_revision_ids.add(envelope.proposal_revision_id)
            scenes.append(
                {
                    "frame_identity": outcome.frame_identity.to_mapping(),
                    "scene": scene.to_mapping(),
                    "proposal_data_digest": envelope.proposal_data_digest,
                }
            )
            calibration_revision_ids.add(scene.calibration_revision_id)
            calibration_digests.add(scene.calibration_digest)
            receipts.append(
                {
                    "frame_identity": outcome.frame_identity.to_mapping(),
                    "receipt": envelope.derived_region_receipt,
                }
            )
            for candidate in outcome.candidates:
                if not isinstance(candidate.geometry, ReviewedVisibleRegionGeometry):
                    raise VisualIdentityCropInputError(
                        "reviewed card scene contains non-reviewed visible geometry"
                    )
                items.append(
                    VisualIdentityCropInputItem(
                        card_id=candidate.card_id,
                        frame_identity=outcome.frame_identity,
                        geometry=candidate.geometry,
                        side=candidate.side,
                        identity_usable=candidate.side != "face_down",
                        failure_tags=("face_down",) if candidate.side == "face_down" else (),
                    )
                )
        items.sort(key=lambda item: (item.frame_identity.frame_index, item.card_id))
        if not items or len(scene_revision_ids) > 1:
            raise VisualIdentityCropInputError(
                "the completed reference has no single reviewed virtual-card scene source"
            )
        if len(calibration_revision_ids) != 1 or len(calibration_digests) != 1:
            raise VisualIdentityCropInputError(
                "reviewed virtual-card scenes do not share one calibration revision"
            )
        scene_revision_id = next(iter(scene_revision_ids), fallback_scene_revision_id)
        calibration_revision_id = next(iter(calibration_revision_ids))
        calibration_digest = next(iter(calibration_digests))
        regions = [
            {
                "card_id": item.card_id,
                "frame_identity": item.frame_identity.to_mapping(),
                "geometry": item.geometry.to_mapping(),
                "side": item.side,
                "identity_usable": item.identity_usable,
                "failure_tags": list(item.failure_tags),
            }
            for item in items
        ]
        return items, ReviewedVirtualCardLineage(
            card_scene_revision_id=scene_revision_id,
            card_scene_digest=sha256_bytes(
                json.dumps(scenes, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ),
            calibration_revision_id=calibration_revision_id,
            calibration_digest=calibration_digest,
            scene_derivation_receipt_digest=sha256_bytes(
                json.dumps(receipts, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ),
            derived_visible_region_digest=sha256_bytes(
                json.dumps(regions, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ),
        )

    @staticmethod
    def _validate_scene_derived_views(content: VisibleCardData) -> None:
        """Reject candidate geometry that is not the current scene derivation."""

        for outcome in content.outcomes:
            if outcome.status != "detected":
                continue
            VisualIdentityCropSources._validate_outcome_scene_derived_view(outcome)

    @staticmethod
    def _validate_outcome_scene_derived_view(outcome: VisibleCardOutcome) -> None:
        envelope = outcome.card_scene
        if envelope is None:
            return
        candidate_mappings = [candidate.to_mapping() for candidate in outcome.candidates]
        if isinstance(envelope, CardSceneDraft):
            if envelope.reviewed is None:
                if candidate_mappings:
                    raise CropSourceError("The visible-card scene-derived view is incomplete.")
                return
            if envelope.projection is None:
                raise CropSourceError("The visible-card scene-derived view is incomplete.")
            try:
                validate_pose_scene_candidate_view(
                    ReviewedCardScene.from_mapping(envelope.reviewed.scene),
                    envelope.projection,
                    candidate_mappings,
                    receipt=envelope.derived_region_receipt,
                )
            except (CardPlaneGeometryError, TypeError, ValueError) as error:
                raise CropSourceError(
                    "The visible-card scene-derived view is stale or invalid."
                ) from error
            return
        if not isinstance(envelope, Mapping):
            raise CropSourceError("The visible-card scene-derived view is invalid.")
        raw_scene = envelope.get("scene")
        projection = envelope.get("projection")
        if not isinstance(raw_scene, Mapping) or not isinstance(projection, Mapping):
            raise CropSourceError("The visible-card scene-derived view is incomplete.")
        try:
            validate_pose_scene_candidate_view(
                raw_scene,
                projection,
                candidate_mappings,
                receipt=envelope.get("derived_region_receipt"),
            )
        except (CardPlaneGeometryError, TypeError, ValueError) as error:
            raise CropSourceError(
                "The visible-card scene-derived view is stale or invalid."
            ) from error
