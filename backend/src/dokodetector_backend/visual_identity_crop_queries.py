"""Validate visual identity results and resolve their frozen crops."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Mapping
from threading import RLock
from typing import Any

from doko_operations.derived_view import (
    DerivedViewError,
    FrameResolver,
    ResolvedCrop,
    ResolvedCropJpegPreview,
)
from doko_operations.pipeline_data import ProcessorProducer, RecordingVideoSource
from table_evidence_analyzer.pipeline_data import (
    VisibleCardData,
    VisualIdentityCropIdentity,
    VisualIdentityCropInputProvenance,
    VisualIdentityData,
    VisualIdentityOutcome,
)
from table_evidence_analyzer.visual_identity_crop_input import (
    VisualIdentityCropInput,
    VisualIdentityCropInputError,
    VisualIdentityCropInputItem,
)

from dokodetector_backend.pipeline_node_selection_store import PipelineNodeSelectionStore
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_revision_store import StoredPipelineRevision
from dokodetector_backend.pipeline_storage import PipelineNotFound, PipelineRuntimeStorage
from dokodetector_backend.processor_run_store import ProcessorRunStore
from dokodetector_backend.recording_bundle_store import RecordingBundleStore
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.visual_identity_crop_provenance import (
    ValidatedCropContext,
    crop_dependency_fingerprint,
    crop_input_provenance,
    validate_crop_outcome,
    validate_run_crop_provenance,
)
from dokodetector_backend.visual_identity_crop_resolution import (
    crop_identity_mapping,
    resolve_browser_preview,
    resolve_geometry_crop,
    validated_identity_crop_outcome,
)
from dokodetector_backend.visual_identity_crop_resolution import (
    resolve_identity_crop as resolve_frozen_identity_crop,
)
from dokodetector_backend.visual_identity_crop_resolution import (
    resolve_reviewed_annotation_crop as resolve_frozen_reviewed_annotation_crop,
)
from dokodetector_backend.visual_identity_crop_sources import VisualIdentityCropSources
from dokodetector_backend.visual_identity_pipeline_errors import (
    VisualIdentityPipelineInputError,
)
from dokodetector_backend.visual_identity_recording_access import VisualIdentityRecordingAccess
from dokodetector_backend.visual_identity_request import VisualIdentityRequestBuilder

LOGGER = logging.getLogger(__name__)


class VisualIdentityCropQueries:
    """Expose validated crop and result reads over explicit storage owners."""

    def __init__(
        self,
        *,
        recording_access: VisualIdentityRecordingAccess,
        request_builder: VisualIdentityRequestBuilder,
        selection_store: PipelineNodeSelectionStore,
        node_store: PipelineNodeStore | None,
        recording_store: RecordingBundleStore,
        repository_storage: RepositoryBundleStorage,
        run_store: ProcessorRunStore,
        storage: PipelineRuntimeStorage,
        frame_resolver: FrameResolver,
        derived_view_lock: RLock,
        crop_sources: VisualIdentityCropSources,
    ) -> None:
        self.recording_access = recording_access
        self.request_builder = request_builder
        self.selection_store = selection_store
        self.node_store = node_store
        self.recording_store = recording_store
        self.repository_storage = repository_storage
        self.run_store = run_store
        self.storage = storage
        self.frame_resolver = frame_resolver
        self._derived_view_lock = derived_view_lock
        self.crop_sources = crop_sources
        self._crop_context_lock = RLock()
        self._crop_contexts: OrderedDict[str, ValidatedCropContext] = OrderedDict()

    def get_identity_crop_identity(
        self, recording_id: str, revision_id: str, item_id: str
    ) -> VisualIdentityCropIdentity:
        """Validate one stored identity crop without resolving its source image."""

        _, outcome = self._validated_identity_crop_outcome(recording_id, revision_id, item_id)
        return self._usable_crop_identity(outcome)

    def _validated_identity_crop_outcome(
        self, recording_id: str, revision_id: str, item_id: str
    ) -> tuple[StoredPipelineRevision, VisualIdentityOutcome]:
        return validated_identity_crop_outcome(
            recording_id,
            revision_id,
            item_id,
            contexts=self._crop_contexts,
            context_lock=self._crop_context_lock,
            require_revision=self._require_identity_revision,
            require_outcome=self._require_identity_outcome,
            validate_outcome=self._validate_frozen_crop_outcome,
            validate_provenance=self._validate_crop_input_provenance,
            recording_store=self.recording_store,
            node_store=self.node_store,
            run_store=self.run_store,
            repository_storage=self.repository_storage,
        )

    @staticmethod
    def _usable_crop_identity(outcome: VisualIdentityOutcome) -> VisualIdentityCropIdentity:
        crop = outcome.crop_identity
        if crop is None or crop.status != "usable" or crop.image_sha256 is None:
            raise DerivedViewError("The identity crop is unavailable.")
        return crop

    def _validate_frozen_crop_outcome(
        self, frozen_input: VisualIdentityCropInput, outcome: VisualIdentityOutcome
    ) -> None:
        item = self.request_builder._identity_crop_item_for_outcome(frozen_input, outcome)
        validate_crop_outcome(frozen_input, item, outcome)

    def resolve_reviewed_annotation_crops(
        self, recording_id: str, visible_revision_id: str
    ) -> dict[str, dict[str, Any] | str]:
        """Resolve native crops for exact reviewed visible-card geometry, without a classifier."""

        _, source = self.recording_access.accepted_source(recording_id)
        node_ref = self.request_builder._canonical_input_node_ref(
            visible_revision_id, "visible_cards"
        )
        revision = self.selection_store.read_node_revision(
            node_ref["node_id"], node_ref["revision_id"]
        )
        crop_input = self.request_builder._freeze_crop_input(
            recording_id,
            revision,
            source=source,
            requested_kind="reviewed_visible_card",
            require_current_reference=True,
            input_node_ref=node_ref,
        )
        resolved: dict[str, dict[str, Any] | str] = {}
        for item in crop_input.items:
            try:
                crop = resolve_geometry_crop(
                    video_path=self.recording_access.video_path(recording_id),
                    source=source,
                    frame_identity=item.frame_identity.to_mapping(),
                    geometry=item.geometry.to_mapping(),
                    crop_policy="oracle_visible_region",
                    output_encoding="ppm",
                    resolver=self.frame_resolver,
                    cache=self.storage.derived_views_root,
                    lock=self._derived_view_lock,
                )
                resolved[item.card_id] = crop_identity_mapping(crop)
            except (DerivedViewError, OSError, RuntimeError, ValueError) as error:
                resolved[item.card_id] = str(error) or "The reviewed crop is unavailable."
        return resolved

    def resolve_reviewed_annotation_crop(
        self,
        recording_id: str,
        visible_revision_id: str,
        item_id: str,
        outcome: Mapping[str, Any],
    ) -> ResolvedCrop:
        """Resolve one saved annotation crop against its reviewed geometry and digest."""

        revision, crop_input = self._reviewed_crop_input_context(recording_id, visible_revision_id)
        source = revision.manifest.source
        if not isinstance(source, RecordingVideoSource):
            raise DerivedViewError("the reviewed visible-card source is unavailable")
        return resolve_frozen_reviewed_annotation_crop(
            crop_input=crop_input,
            item_id=item_id,
            outcome=outcome,
            source=source,
            video_path=self.recording_access.video_path(recording_id),
            resolver=self.frame_resolver,
            cache=self.storage.derived_views_root,
            lock=self._derived_view_lock,
        )

    def _reviewed_crop_input_context(
        self, recording_id: str, visible_revision_id: str
    ) -> tuple[StoredPipelineRevision, VisualIdentityCropInput]:
        """Reuse reviewed geometry validation while all source files remain unchanged."""

        context_id = f"reviewed:{recording_id}:{visible_revision_id}"
        with self._crop_context_lock:
            context = self._crop_contexts.get(context_id)
            if context is not None:
                try:
                    unchanged = crop_dependency_fingerprint(context.roots) == context.fingerprint
                except OSError:
                    unchanged = False
                if (
                    unchanged
                    and context.revision.manifest.recording_id == recording_id
                    and context.crop_input.input_kind == "reviewed_visible_card"
                ):
                    self._crop_contexts.move_to_end(context_id)
                    return context.revision, context.crop_input
                self._crop_contexts.pop(context_id)

            validation_started_ns = time.time_ns()
            _, source = self.recording_access.accepted_source(recording_id)
            node_ref = self.request_builder._canonical_input_node_ref(
                visible_revision_id, "visible_cards"
            )
            revision_cache: dict[str, StoredPipelineRevision] = {}
            revision = self.selection_store.read_node_revision(
                node_ref["node_id"], node_ref["revision_id"]
            )
            if (
                revision.manifest.recording_id != recording_id
                or revision.manifest.content_type != "visible_cards"
                or not isinstance(revision.content, VisibleCardData)
            ):
                raise DerivedViewError("the reviewed visible-card revision is unavailable")
            crop_input = self.request_builder._freeze_crop_input(
                recording_id,
                revision,
                source=source,
                requested_kind="reviewed_visible_card",
                revision_cache=revision_cache,
                input_node_ref=node_ref,
            )

            roots = {self.repository_storage.bundle_path(recording_id)}
            roots.add(self.node_store.root / node_ref["node_id"])
            if isinstance(revision.manifest.producer, ProcessorProducer):
                roots.add(self.run_store.run_path(revision.manifest.producer.run_id))
            dependency_roots = tuple(sorted(roots))
            try:
                fingerprint = crop_dependency_fingerprint(dependency_roots)
            except OSError:
                fingerprint = ()
            if fingerprint and all(entry[5] < validation_started_ns for entry in fingerprint):
                self._crop_contexts[context_id] = ValidatedCropContext(
                    revision,
                    crop_input,
                    dependency_roots,
                    fingerprint,
                )
                while len(self._crop_contexts) > 8:
                    self._crop_contexts.popitem(last=False)
            return revision, crop_input

    def resolve_identity_crop(
        self, recording_id: str, revision_id: str, item_id: str
    ) -> ResolvedCrop:
        """Resolve one identity crop from an immutable identity revision."""

        revision, outcome = self._validated_identity_crop_outcome(
            recording_id, revision_id, item_id
        )
        return self._resolve_identity_crop_from_validated(recording_id, revision, outcome)

    def _resolve_identity_crop_from_validated(
        self,
        recording_id: str,
        revision: StoredPipelineRevision,
        outcome: VisualIdentityOutcome,
    ) -> ResolvedCrop:
        """Resolve a crop after its revision lineage and source have been checked."""

        return resolve_frozen_identity_crop(
            video_path=self.recording_access.video_path(recording_id),
            source=revision.manifest.source,
            outcome=outcome,
            crop_identity=self._usable_crop_identity(outcome),
            resolver=self.frame_resolver,
            cache=self.storage.derived_views_root,
            lock=self._derived_view_lock,
        )

    def _validate_crop_input_provenance(
        self,
        output_revision: StoredPipelineRevision,
        outcome: VisualIdentityOutcome,
        *,
        source: RecordingVideoSource | None = None,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
    ) -> VisualIdentityCropInput:
        """Reject a stored crop whose run, source item, or manifest lineage has changed."""
        try:
            if source is not None:

                def accepted_source(_recording_id):
                    return None, source
            else:
                accepted_source = self.recording_access.accepted_source
            return validate_run_crop_provenance(
                output_revision,
                outcome,
                run_store=self.run_store,
                selection_store=self.selection_store,
                accepted_source=accepted_source,
                canonical_input_revision=self.request_builder.canonical_input_revision,
                freeze_crop_input=self.request_builder._freeze_crop_input,
                validate_frozen_outcome=self._validate_frozen_crop_outcome,
                revision_cache=revision_cache,
            )
        except VisualIdentityCropInputError as error:
            raise DerivedViewError("the identity crop input is invalid") from error

    @staticmethod
    def _crop_input_provenance(
        crop_input: VisualIdentityCropInput,
        item: VisualIdentityCropInputItem | None,
    ) -> VisualIdentityCropInputProvenance | None:
        return crop_input_provenance(crop_input, item)

    def _canonical_crop_source(self, revision, input_node_ref=None):
        return self.crop_sources._canonical_crop_source(revision, input_node_ref)

    def resolve_identity_crop_browser_preview(
        self,
        recording_id: str,
        revision_id: str,
        item_id: str,
    ) -> ResolvedCropJpegPreview | None:
        """Resolve a browser preview with one lineage validation for the whole request."""

        revision, outcome = self._validated_identity_crop_outcome(
            recording_id, revision_id, item_id
        )
        crop_identity = self._usable_crop_identity(outcome)
        with self._derived_view_lock:
            return resolve_browser_preview(
                crop_identity=crop_identity,
                crop_resolver=lambda: self._resolve_identity_crop_from_validated(
                    recording_id, revision, outcome
                ),
                cache=self.storage.derived_views_root,
            )

    def _require_identity_revision(
        self,
        recording_id: str,
        revision_id: str,
        *,
        source: RecordingVideoSource | None = None,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
    ) -> StoredPipelineRevision:
        revision = self.selection_store.require_processor_revision(revision_id)
        if revision_cache is not None:
            revision_cache[revision_id] = revision
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
