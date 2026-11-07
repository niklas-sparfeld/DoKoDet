"""Freeze exact crop inputs from validated source revisions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from doko_operations.card_plane_geometry import (
    ReviewedCardScene,
    derive_pose_scene_visible_regions,
)
from doko_operations.pipeline_data import (
    HumanProducer,
    ProcessorProducer,
    RecordingVideoSource,
    sha256_bytes,
)
from table_evidence_analyzer.pipeline_data import (
    PredictedVisibleRegionGeometry,
    ProposedCardSceneData,
    ReviewedVisibleRegionGeometry,
    VisibleCardData,
    canonical_proposed_card_scene_data_bytes,
    canonical_visible_card_data_bytes,
)
from table_evidence_analyzer.visual_identity_crop_input import (
    VISUAL_IDENTITY_CROP_INPUT_SCHEMA_VERSION,
    ProposedVirtualCardLineage,
    VisualIdentityCropInput,
    VisualIdentityCropInputError,
    VisualIdentityCropInputItem,
)

from dokodetector_backend.pipeline_revision_store import StoredPipelineRevision
from dokodetector_backend.pipeline_storage import PipelineNotFound
from dokodetector_backend.visual_identity_crop_sources import (
    CropSourceError,
    VisualIdentityCropSources,
)


@dataclass(frozen=True)
class FrozenVisualIdentityCropInput:
    exact_input_revision_id: str
    crop_input: VisualIdentityCropInput
    crop_items: tuple[VisualIdentityCropInputItem, ...]
    provenance: "VisualIdentityCropInputProvenance"

    def to_mapping(self):
        return self.crop_input.to_mapping()

    @property
    def items(self):
        return self.crop_items

    def __getattr__(self, name):
        return getattr(self.crop_input, name)


@dataclass(frozen=True)
class VisualIdentityCropInputProvenance:
    source_revision_id: str
    source_revision_digest: str
    source_node_id: str | None
    source_node_revision_id: str | None
    manifest_digest: str
    virtual_card_lineage: Any
    proposed_virtual_card_lineage: Any


class VisualIdentityCropInputFreezer:
    def __init__(
        self, *, sources: VisualIdentityCropSources, run_store: Any, calibration_store: Any
    ):
        self.sources = sources
        self.run_store = run_store
        self.calibration_store = calibration_store

    def freeze(
        self,
        recording_id: str,
        revision: StoredPipelineRevision,
        *,
        source: RecordingVideoSource,
        requested: Any = None,
        requested_kind: Any = None,
        require_current_reference: bool = False,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        input_node_ref: Mapping[str, str] | None = None,
    ) -> VisualIdentityCropInput:
        """Resolve one exact generated or reviewed revision into its crop-input manifest."""

        try:
            supplied = (
                None if requested is None else VisualIdentityCropInput.from_mapping(requested)
            )
            if supplied is not None:
                if requested_kind is not None and requested_kind != supplied.input_kind:
                    raise VisualIdentityCropInputError(
                        "the selected input kind does not match its crop-input descriptor"
                    )
                requested_kind = supplied.input_kind
            source_node_id, source_node_revision_id, canonical_source_digest = (
                self.sources._canonical_crop_source(revision, input_node_ref)
            )
            canonical_descriptor = (
                supplied is None
                or supplied.schema_version == VISUAL_IDENTITY_CROP_INPUT_SCHEMA_VERSION
            )
            source_revision_digest = (
                canonical_source_digest
                if canonical_descriptor
                else sha256_bytes(
                    json.dumps(
                        revision.manifest.to_mapping(), sort_keys=True, separators=(",", ":")
                    ).encode("utf-8")
                )
            )
            source_node_fields = (
                {
                    "source_node_id": source_node_id,
                    "source_node_revision_id": source_node_revision_id,
                    "schema_version": VISUAL_IDENTITY_CROP_INPUT_SCHEMA_VERSION,
                }
                if canonical_descriptor
                else {}
            )
            source_view_bytes = (
                canonical_proposed_card_scene_data_bytes(revision.content)
                if isinstance(revision.content, ProposedCardSceneData)
                else canonical_visible_card_data_bytes(revision.content)
            )
            source_view_digest = sha256_bytes(source_view_bytes)
            if source_view_digest != revision.manifest.content_sha256:
                raise VisualIdentityCropInputError("the selected source view changed")
            producer = revision.manifest.producer
            if isinstance(revision.content, ProposedCardSceneData):
                source_kind = "proposed_virtual_cards"
            elif isinstance(producer, ProcessorProducer):
                producer_run = self.run_store.require(
                    producer.run_id, revision_cache=revision_cache
                )
                provider = str(producer_run.request.configuration.get("provider", "gemini"))
                source_kind = "rfdetr_segment" if "rfdetr" in provider.lower() else "gemini_polygon"
            elif isinstance(producer, HumanProducer):
                source_kind = requested_kind or (
                    "reviewed_virtual_card"
                    if any(outcome.card_scene is not None for outcome in revision.content.outcomes)
                    else "reviewed_visible_card"
                )
            else:
                raise VisualIdentityCropInputError(
                    "the selected revision is not a generated or maintained crop input"
                )
            if requested_kind is not None and requested_kind != source_kind:
                raise VisualIdentityCropInputError(
                    "the selected input kind does not match its processor source"
                )
            kind = source_kind

            if kind == "proposed_virtual_cards":
                if not isinstance(revision.content, ProposedCardSceneData):
                    raise VisualIdentityCropInputError("the selected proposal revision is invalid")
                data = revision.content
                if (
                    data.calibration is None
                    or data.calibration_revision_id is None
                    or data.calibration_digest is None
                ):
                    raise VisualIdentityCropInputError("the proposal has no frozen calibration")
                try:
                    detector_node, detector_node_revision = self.sources.node_store.find_revision(
                        data.detector_revision_id
                    )
                    detector_revision = self.sources.selection_store.read_node_revision(
                        detector_node.node_id, detector_node_revision.revision_id
                    )
                except (FileNotFoundError, ValueError) as error:
                    raise VisualIdentityCropInputError(
                        "the proposal detector node revision is unavailable"
                    ) from error
                if (
                    detector_revision.manifest.recording_id != recording_id
                    or detector_revision.manifest.content_type != "visible_cards"
                    or detector_revision.manifest.source != source
                    or detector_revision.manifest.content_sha256 != data.detector_revision_digest
                ):
                    raise VisualIdentityCropInputError("the detector lineage is stale")
                detector_card_ids_by_event = {
                    outcome.event_id: {candidate.card_id for candidate in outcome.candidates}
                    for outcome in detector_revision.content.outcomes
                }
                calibration_run = self.calibration_store.load(
                    recording_id, data.calibration_revision_id
                )
                calibration = calibration_run.calibration
                if calibration is None or calibration.calibration_digest != data.calibration_digest:
                    raise VisualIdentityCropInputError("the frozen calibration lineage is stale")
                if data.calibration != calibration.to_mapping():
                    raise VisualIdentityCropInputError("the proposal calibration contents changed")
                projection = {
                    "table_to_image_homography": [list(row) for row in calibration.table_to_image],
                    "card_short_size": calibration.card_short_size,
                    "card_long_size": calibration.card_long_size,
                }
                items = []
                unsupported_frames: list[str] = []
                hidden_cards: list[str] = []
                for frame in data.frames:
                    if frame.status == "unsupported":
                        unsupported_frames.append(frame.frame_id)
                        continue
                    if frame.status == "no_cards_detected":
                        continue
                    if frame.proposal is None or frame.source_identity is None:
                        raise VisualIdentityCropInputError(
                            "a supported proposal has no exact frame identity"
                        )
                    identity = frame.source_identity
                    if identity.source_video_sha256 != source.video_sha256:
                        raise VisualIdentityCropInputError(
                            "a proposal frame uses different video bytes"
                        )
                    scene = ReviewedCardScene.from_mapping(frame.proposal.initialized_scene)
                    if (
                        scene.source_frame_id != frame.frame_id
                        or scene.source_frame_width != identity.width
                        or scene.source_frame_height != identity.height
                        or scene.calibration_revision_id != data.calibration_revision_id
                        or scene.calibration_digest != data.calibration_digest
                    ):
                        raise VisualIdentityCropInputError(
                            "proposal scene and exact frame identity differ"
                        )
                    derivation = derive_pose_scene_visible_regions(scene, projection)
                    source_card_ids = {
                        pose.card_id: pose.source_suggestion_id for pose in scene.poses
                    }
                    hidden_cards.extend(
                        f"{frame.frame_id}:{card_id}" for card_id in derivation.hidden_card_ids
                    )
                    for region in derivation.regions:
                        source_card_id = source_card_ids.get(region["card_id"])
                        if (
                            source_card_id is None
                            or source_card_id
                            not in detector_card_ids_by_event.get(frame.frame_id, set())
                        ):
                            raise VisualIdentityCropInputError(
                                "a visible proposal pose has no source detector card in its frame"
                            )
                        raw_geometry = dict(region["geometry"])
                        raw_geometry["kind"] = "visible-region/v1"
                        geometry = PredictedVisibleRegionGeometry.from_mapping(raw_geometry)
                        items.append(
                            VisualIdentityCropInputItem(
                                card_id=source_card_id,
                                frame_identity=identity,
                                geometry=geometry,
                                side="unknown",
                                identity_usable=True,
                            )
                        )
                items.sort(key=lambda item: (item.frame_identity.frame_index, item.card_id))
                input_value = VisualIdentityCropInput(
                    input_kind=kind,
                    recording_id=recording_id,
                    accepted_video_sha256=source.video_sha256,
                    accepted_video_byte_length=source.byte_length,
                    source_revision_id=source_node_revision_id,
                    source_revision_digest=source_revision_digest,
                    source_view_digest=sha256_bytes(canonical_proposed_card_scene_data_bytes(data)),
                    **source_node_fields,
                    items=tuple(items),
                    proposed_virtual_card_lineage=ProposedVirtualCardLineage(
                        detector_revision_id=data.detector_revision_id,
                        detector_revision_digest=data.detector_revision_digest,
                        detector_data_digest=sha256_bytes(
                            canonical_visible_card_data_bytes(detector_revision.content)
                        ),
                        calibration_revision_id=data.calibration_revision_id,
                        calibration_digest=data.calibration_digest,
                        derivation_policy="pose-scene-stacking-visible-regions.v1",
                        unsupported_frame_ids=tuple(sorted(unsupported_frames)),
                        hidden_cards=tuple(sorted(hidden_cards)),
                    ),
                )
                input_value = VisualIdentityCropInput.from_mapping(input_value.to_mapping())
                if supplied is not None and supplied.to_mapping() != input_value.to_mapping():
                    raise VisualIdentityCropInputError(
                        "the selected crop-input descriptor does not match its proposal revision"
                    )
                return _frozen(revision, input_value)

            if not isinstance(revision.content, VisibleCardData):
                raise VisualIdentityCropInputError("the selected crop input is unavailable")

            if kind == "reviewed_visible_card":
                if not isinstance(producer, HumanProducer):
                    raise VisualIdentityCropInputError(
                        "reviewed visible-card input needs a completed node review"
                    )
                if (
                    require_current_reference
                    and not self.sources._is_selected_completed_node_revision(
                        recording_id, source_node_id, source_node_revision_id
                    )
                ):
                    raise VisualIdentityCropInputError(
                        "the selected revision is not the completed visible-card node"
                    )
                items: list[VisualIdentityCropInputItem] = []
                for outcome in revision.content.outcomes:
                    if outcome.status != "detected" or outcome.frame_identity is None:
                        continue
                    for card in outcome.candidates:
                        if not isinstance(card.geometry, ReviewedVisibleRegionGeometry):
                            continue
                        items.append(
                            VisualIdentityCropInputItem(
                                card_id=card.card_id,
                                frame_identity=outcome.frame_identity,
                                geometry=card.geometry,
                                side=card.side,
                                identity_usable=card.side != "face_down",
                            )
                        )
                items.sort(key=lambda item: (item.frame_identity.frame_index, item.card_id))
                input_value = VisualIdentityCropInput(
                    input_kind=kind,
                    recording_id=recording_id,
                    accepted_video_sha256=source.video_sha256,
                    accepted_video_byte_length=source.byte_length,
                    source_revision_id=source_node_revision_id,
                    source_revision_digest=source_revision_digest,
                    source_view_digest=source_view_digest,
                    **source_node_fields,
                    items=tuple(items),
                )
                input_value = VisualIdentityCropInput.from_mapping(input_value.to_mapping())
                if supplied is not None and supplied.to_mapping() != input_value.to_mapping():
                    raise VisualIdentityCropInputError(
                        "the selected crop-input descriptor does not match its source revision"
                    )
                return _frozen(revision, input_value)

            if kind == "reviewed_virtual_card":
                if not isinstance(producer, HumanProducer):
                    raise VisualIdentityCropInputError(
                        "reviewed virtual-card geometry needs a completed node review"
                    )
                if (
                    require_current_reference
                    and not self.sources._is_selected_completed_node_revision(
                        recording_id, source_node_id, source_node_revision_id
                    )
                ):
                    raise VisualIdentityCropInputError(
                        "the selected revision is not the completed visible-card node"
                    )
                self.sources._validate_scene_derived_views(revision.content)
                items, lineage = self.sources._reviewed_virtual_card_items(
                    revision.content,
                    fallback_scene_revision_id=source_node_revision_id,
                )
                input_value = VisualIdentityCropInput(
                    input_kind=kind,
                    recording_id=recording_id,
                    accepted_video_sha256=source.video_sha256,
                    accepted_video_byte_length=source.byte_length,
                    source_revision_id=source_node_revision_id,
                    source_revision_digest=source_revision_digest,
                    source_view_digest=source_view_digest,
                    **source_node_fields,
                    items=tuple(items),
                    virtual_card_lineage=lineage,
                )
                input_value = VisualIdentityCropInput.from_mapping(input_value.to_mapping())
                if supplied is not None and supplied.to_mapping() != input_value.to_mapping():
                    raise VisualIdentityCropInputError(
                        "the selected crop-input descriptor does not match its source revision"
                    )
                return _frozen(revision, input_value)

            if kind not in {"gemini_polygon", "rfdetr_segment"}:
                raise VisualIdentityCropInputError("the selected crop input kind is unsupported")
            items: list[VisualIdentityCropInputItem] = []
            for outcome in revision.content.outcomes:
                if outcome.status != "detected":
                    continue
                if outcome.frame_identity is None:
                    raise VisualIdentityCropInputError("a selected frame has no exact identity")
                for card in outcome.candidates:
                    items.append(
                        VisualIdentityCropInputItem(
                            card_id=card.card_id,
                            frame_identity=outcome.frame_identity,
                            geometry=card.geometry,
                            side=card.side,
                            identity_usable=card.side != "face_down",
                        )
                    )
            items.sort(key=lambda item: (item.frame_identity.frame_index, item.card_id))
            input_value = VisualIdentityCropInput(
                input_kind=kind,
                recording_id=recording_id,
                accepted_video_sha256=source.video_sha256,
                accepted_video_byte_length=source.byte_length,
                source_revision_id=source_node_revision_id,
                source_revision_digest=source_revision_digest,
                source_view_digest=source_view_digest,
                **source_node_fields,
                items=tuple(items),
            )
            input_value = VisualIdentityCropInput.from_mapping(input_value.to_mapping())
            if supplied is not None and supplied.to_mapping() != input_value.to_mapping():
                raise VisualIdentityCropInputError(
                    "the selected crop-input descriptor does not match its source revision"
                )
            return _frozen(revision, input_value)
        except (VisualIdentityCropInputError, PipelineNotFound, TypeError, ValueError) as error:
            raise CropSourceError(
                f"The selected visual identity crop input is invalid: {error}."
            ) from error


def _frozen(
    revision: StoredPipelineRevision, value: VisualIdentityCropInput
) -> FrozenVisualIdentityCropInput:
    return FrozenVisualIdentityCropInput(
        exact_input_revision_id=revision.manifest.revision_id,
        crop_input=value,
        crop_items=value.items,
        provenance=VisualIdentityCropInputProvenance(
            source_revision_id=value.source_revision_id,
            source_revision_digest=value.source_revision_digest,
            source_node_id=value.source_node_id,
            source_node_revision_id=value.source_node_revision_id,
            manifest_digest=value.computed_manifest_digest,
            virtual_card_lineage=value.virtual_card_lineage,
            proposed_virtual_card_lineage=value.proposed_virtual_card_lineage,
        ),
    )
