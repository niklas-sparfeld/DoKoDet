"""Build and freeze exact visual identity processor requests."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Protocol

from doko_operations.card_plane_calibration import (
    CalibrationRevisionStore,
    CardPlaneCalibrationError,
)
from doko_operations.pipeline_data import ProcessorRunRequest
from table_evidence_analyzer.pipeline_data import (
    DetectorBoxGeometry,
    PipelineGeometry,
    PredictedVisibleRegionGeometry,
    ProposedCardSceneData,
    ReviewedVisibleRegionGeometry,
    VisibleCardData,
    VisualIdentityOutcome,
)
from table_evidence_analyzer.visual_identity import VisualIdentityClassifierProvider
from table_evidence_analyzer.visual_identity_crop_input import (
    VisualIdentityCropInput,
    VisualIdentityCropInputError,
    VisualIdentityCropInputItem,
    validate_crop_policy_compatibility,
)

from dokodetector_backend.pipeline_node_selection_store import PipelineNodeSelectionStore
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_storage import PipelineNotFound
from dokodetector_backend.visual_identity_crop_inputs import VisualIdentityCropInputFreezer
from dokodetector_backend.visual_identity_crop_sources import (
    CropSourceError,
    VisualIdentityCropSources,
)
from dokodetector_backend.visual_identity_pipeline_errors import (
    VisualIdentityPipelineError,
    VisualIdentityPipelineInputError,
)
from dokodetector_backend.visual_identity_recording_access import VisualIdentityRecordingAccess

_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._:-]+")


class ClassifierSelection(Protocol):
    classifier: VisualIdentityClassifierProvider | None
    identity_classifiers: Mapping[str, Any] | None

    def classifier_for_selection(self, requested_provider: str | None) -> Any | None: ...


def _safe(value: str) -> str:
    return _SAFE_COMPONENT.sub("-", value).strip("-") or "unknown"


def _default_crop_policy_for_geometry(geometry: PipelineGeometry) -> dict[str, str]:
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
    geometries = [
        candidate.geometry for outcome in content.outcomes for candidate in outcome.candidates
    ]
    if not geometries:
        return {"policy_id": "predicted_visible_region", "output_encoding": "ppm"}
    policies = {_default_crop_policy_for_geometry(geometry)["policy_id"] for geometry in geometries}
    if len(policies) == 1:
        return {"policy_id": policies.pop(), "output_encoding": "ppm"}
    return {"policy_id": "predicted_visible_region", "output_encoding": "ppm"}


def _crop_policy_for_geometry(policy_id: str, geometry: PipelineGeometry) -> str:
    if policy_id in {"predicted_visible_region", "oracle_visible_region"}:
        return _default_crop_policy_for_geometry(geometry)["policy_id"]
    return policy_id


def configuration_provider(value: Any) -> str | None:
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


class VisualIdentityRequestBuilder:
    """Validate request choices and freeze their exact crop source."""

    def __init__(
        self,
        *,
        selection_store: PipelineNodeSelectionStore,
        node_store: PipelineNodeStore | None,
        crop_sources: VisualIdentityCropSources,
        crop_input_freezer: VisualIdentityCropInputFreezer,
        recording_access: VisualIdentityRecordingAccess,
        classification: ClassifierSelection,
        calibration_store: CalibrationRevisionStore,
    ) -> None:
        self.selection_store = selection_store
        self.node_store = node_store
        self.crop_sources = crop_sources
        self.crop_input_freezer = crop_input_freezer
        self.recording_access = recording_access
        self.classification = classification
        self.calibration_store = calibration_store

    def list_proposed_crop_inputs(self, recording_id: str) -> tuple[dict[str, Any], ...]:
        """List exact proposal revisions that can supply identity crop geometry."""

        _, source = self.recording_access.accepted_source(recording_id)
        values = []
        for node in self.node_store.list_nodes():
            if (
                node.content_type != "card_scene_proposals"
                or node.source.get("recording_id") != recording_id
            ):
                continue
            for node_revision in self.node_store.history(node.node_id):
                revision = self.selection_store.read_node_revision(
                    node.node_id, node_revision.revision_id
                )
                manifest = revision.manifest
                if (
                    revision.manifest.source != source
                    or not isinstance(revision.content, ProposedCardSceneData)
                    or revision.content.calibration_revision_id is None
                    or not any(frame.status == "supported" for frame in revision.content.frames)
                    or any(
                        frame.status == "supported" and frame.source_identity is None
                        for frame in revision.content.frames
                    )
                ):
                    continue
                data = revision.content
                try:
                    detector = self.selection_store.require_processor_revision(
                        data.detector_revision_id
                    )
                except PipelineNotFound:
                    continue
                if (
                    detector.manifest.content_type != "visible_cards"
                    or detector.manifest.source != source
                    or detector.manifest.content_sha256 != data.detector_revision_digest
                ):
                    continue
                try:
                    calibration_run = self.calibration_store.load(
                        recording_id, data.calibration_revision_id
                    )
                except CardPlaneCalibrationError:
                    continue
                calibration = calibration_run.calibration
                if (
                    calibration is None
                    or calibration.calibration_digest != data.calibration_digest
                    or calibration.to_mapping() != data.calibration
                ):
                    continue
                values.append(
                    {
                        "node_id": node.node_id,
                        "revision_id": manifest.revision_id,
                        "created_at": manifest.created_at,
                        "proposal_data_digest": data.data_digest,
                        "detector_revision_id": data.detector_revision_id,
                        "calibration_revision_id": data.calibration_revision_id,
                        "supported_frame_count": sum(
                            frame.status == "supported" for frame in data.frames
                        ),
                        "unsupported_frame_count": sum(
                            frame.status == "unsupported" for frame in data.frames
                        ),
                    }
                )
        return tuple(
            sorted(values, key=lambda item: (item["created_at"], item["revision_id"]), reverse=True)
        )

    def build(self, recording_id: str, payload: Mapping[str, Any]) -> ProcessorRunRequest:
        if not isinstance(payload, Mapping):
            raise VisualIdentityPipelineInputError("The processor request must be an object.")
        if self.classification.classifier is None and not self.classification.identity_classifiers:
            raise VisualIdentityPipelineInputError(
                "The visual card identity classifier is unavailable."
            )
        raw = payload.get("request", payload)
        if not isinstance(raw, Mapping):
            raise VisualIdentityPipelineInputError("request must be an object.")
        _, source = self.recording_access.accepted_source(recording_id)
        requested_crop_input = raw.get("crop_input")
        requested_kind = raw.get("crop_input_kind")
        content_type = (
            "card_scene_proposals"
            if requested_kind == "proposed_virtual_cards"
            else "visible_cards"
        )
        input_node_refs = raw.get("input_node_refs")
        input_node_ref = raw.get("input_node_ref")
        if input_node_refs is not None:
            if not isinstance(input_node_refs, list) or len(input_node_refs) != 1:
                raise VisualIdentityPipelineInputError("one exact input_node_ref is required")
            input_node_ref = input_node_refs[0]
        if input_node_ref is None:
            raise VisualIdentityPipelineInputError("one exact input_node_ref is required")
        if not isinstance(input_node_ref, Mapping) or set(input_node_ref) != {
            "node_id",
            "revision_id",
            "revision_policy",
        }:
            raise VisualIdentityPipelineInputError("input_node_ref is invalid")
        visible_revision_id = input_node_ref.get("revision_id")
        if not isinstance(visible_revision_id, str) or not visible_revision_id:
            raise VisualIdentityPipelineInputError("input_node_ref needs a revision ID")
        if input_node_ref["revision_policy"] not in {"current_head", "historical"}:
            raise VisualIdentityPipelineInputError("input_node_ref needs a revision policy")
        if any(
            raw.get(field) is not None
            for field in (
                "input_revision_ids",
                "visible_card_revision_id",
                "card_scene_proposal_revision_id",
            )
        ):
            raise VisualIdentityPipelineInputError(
                "use input_node_ref instead of revision-ID input fields"
            )
        try:
            revision = self.selection_store.read_node_revision(
                input_node_ref["node_id"], visible_revision_id
            )
        except (FileNotFoundError, KeyError, ValueError) as error:
            raise VisualIdentityPipelineInputError(
                "The selected node revision is unavailable"
            ) from error
        if (
            revision.manifest.content_type != content_type
            or revision.manifest.source != source
            or (
                input_node_ref["revision_policy"] == "current_head"
                and self.node_store.get(input_node_ref["node_id"]).head_revision_id
                != visible_revision_id
            )
        ):
            raise VisualIdentityPipelineInputError(
                "The selected node revision does not match the accepted recording video."
            )
        if content_type == "visible_cards" and not isinstance(revision.content, VisibleCardData):
            raise VisualIdentityPipelineInputError(
                "The selected node has invalid visible-card data"
            )
        values = dict(raw)
        values.pop("card_scene_proposal_revision_id", None)
        values.pop("visible_card_revision_id", None)
        values.pop("input_node_ref", None)
        crop_input = self._freeze_crop_input(
            recording_id,
            revision,
            source=source,
            requested=requested_crop_input,
            requested_kind=requested_kind,
            require_current_reference=True,
            input_node_ref=input_node_ref,
        )
        values.pop("visible_card_revision_id", None)
        values.pop("crop_input_kind", None)
        values.setdefault("schema_version", "processor-run-request/v1")
        values.setdefault("run_id", payload.get("run_id"))
        if not values.get("run_id"):
            raise VisualIdentityPipelineInputError("run_id is required.")
        values.setdefault("processor_type", "visual-card-identity")
        values.setdefault("source", source.to_mapping())
        values["input_revision_ids"] = [visible_revision_id]
        values["input_node_refs"] = [dict(input_node_ref)]
        values.setdefault(
            "implementation",
            {"name": "visual-identity-classifier-adapter", "version": "v1"},
        )
        configuration = values.get("configuration", {})
        if not isinstance(configuration, Mapping):
            raise VisualIdentityPipelineInputError("configuration must be an object.")
        configuration = dict(configuration)
        requested_provider = configuration_provider(configuration)
        classifier = self.classification.classifier_for_selection(requested_provider)
        if classifier is None:
            raise VisualIdentityPipelineInputError(
                "The requested visual identity processor is unavailable."
            )
        configuration["provider"] = classifier.name
        configuration["classifier"] = {"name": classifier.name, "version": classifier.version}
        underlying = getattr(classifier, "classifier", classifier)
        bundle_identity = getattr(underlying, "bundle_identity", None)
        if isinstance(bundle_identity, Mapping):
            configuration["bundle_identity"] = dict(bundle_identity)
        device = getattr(underlying, "device", None)
        if isinstance(device, str):
            configuration["device"] = device
        values["configuration"] = configuration
        if values.get("model") is None or requested_provider is not None:
            values["model"] = {"name": classifier.model, "version": classifier.version}
        values.setdefault("extraction_policy", {"policy_id": "exact-event/v1"})
        if values.get("crop_policy") is None:
            values["crop_policy"] = (
                {"policy_id": "predicted_visible_region", "output_encoding": "ppm"}
                if requested_kind == "proposed_virtual_cards"
                else _default_crop_policy(revision.content)
            )
        try:
            validate_crop_policy_compatibility(crop_input, str(values["crop_policy"]["policy_id"]))
        except (KeyError, TypeError, VisualIdentityCropInputError) as error:
            raise VisualIdentityPipelineInputError(
                "The crop policy is incompatible with the selected crop input."
            ) from error
        values["crop_input"] = crop_input.to_mapping()
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

    def _canonical_input_node_ref(self, revision_id, content_type):
        return self.crop_sources._canonical_input_node_ref(revision_id, content_type)

    def canonical_input_revision(self, request):
        try:
            return self.crop_sources.canonical_input_revision(request)
        except CropSourceError as error:
            raise VisualIdentityPipelineInputError(str(error)) from error

    def _freeze_crop_input(
        self,
        recording_id,
        revision,
        *,
        source,
        requested=None,
        requested_kind=None,
        require_current_reference=False,
        revision_cache=None,
        input_node_ref=None,
    ):
        try:
            frozen = self.crop_input_freezer.freeze(
                recording_id,
                revision,
                source=source,
                requested=requested,
                requested_kind=requested_kind,
                require_current_reference=require_current_reference,
                revision_cache=revision_cache,
                input_node_ref=input_node_ref,
            )
            return frozen.crop_input
        except (CropSourceError, PipelineNotFound, TypeError, ValueError) as error:
            raise VisualIdentityPipelineInputError(
                f"The selected visual identity crop input is invalid: {error}."
            ) from error

    def _is_selected_completed_node_revision(self, recording_id, node_id, revision_id):
        return self.crop_sources._is_selected_completed_node_revision(
            recording_id, node_id, revision_id
        )

    @staticmethod
    def _reviewed_virtual_card_items(content, *, fallback_scene_revision_id):
        return VisualIdentityCropSources._reviewed_virtual_card_items(
            content, fallback_scene_revision_id=fallback_scene_revision_id
        )

    @classmethod
    def _validate_scene_derived_views(cls, content):
        try:
            VisualIdentityCropSources._validate_scene_derived_views(content)
        except CropSourceError as error:
            raise VisualIdentityPipelineError(str(error)) from error

    @classmethod
    def _validate_outcome_scene_derived_view(cls, outcome):
        try:
            VisualIdentityCropSources._validate_outcome_scene_derived_view(outcome)
        except CropSourceError as error:
            raise VisualIdentityPipelineError(str(error)) from error

    @staticmethod
    def _identity_item_ids(items: tuple[VisualIdentityCropInputItem, ...]) -> tuple[str, ...]:
        """Keep output IDs unique when source card IDs are only unique within a frame."""

        counts: dict[str, int] = {}
        for item in items:
            counts[item.card_id] = counts.get(item.card_id, 0) + 1
        reserved = set(counts)
        assigned: set[str] = set()
        result: list[str] = []
        for item in items:
            if counts[item.card_id] == 1:
                item_id = item.card_id
            else:
                digest = hashlib.sha256(
                    f"{item.frame_identity.frame_index}:{item.card_id}".encode("utf-8")
                ).hexdigest()
                item_id = ""
                for length in range(12, len(digest) + 1, 4):
                    suffix = f"-frame-{item.frame_identity.frame_index}-{digest[:length]}"
                    item_id = f"{item.card_id[: 128 - len(suffix)]}{suffix}"
                    if item_id not in reserved and item_id not in assigned:
                        break
                else:
                    raise VisualIdentityPipelineError(
                        "The visual identity input cannot produce unique item IDs."
                    )
            if item_id in assigned:
                raise VisualIdentityPipelineError(
                    "The visual identity input cannot produce unique item IDs."
                )
            assigned.add(item_id)
            result.append(item_id)
        return tuple(result)

    @classmethod
    def _identity_crop_item_for_outcome(
        cls,
        crop_input: VisualIdentityCropInput,
        outcome: VisualIdentityOutcome,
    ) -> VisualIdentityCropInputItem | None:
        for item, item_id in zip(
            crop_input.items, cls._identity_item_ids(crop_input.items), strict=True
        ):
            if (
                item_id == outcome.card_id
                and item.frame_identity.to_mapping() == outcome.frame_identity.to_mapping()
            ):
                return item
        return None
