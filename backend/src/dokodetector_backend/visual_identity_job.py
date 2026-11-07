"""Run a frozen visual identity job and arbitrate durable publication."""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from doko_operations.pipeline_data import (
    DataRevision,
    ProcessorProducer,
    RunFailure,
    RunItemOutcome,
    RunProgress,
    sha256_bytes,
)
from table_evidence_analyzer.pipeline_data import (
    ProposedCardSceneData,
    VisibleCardCandidate,
    VisibleCardData,
    VisibleCardOutcome,
    VisualIdentityData,
    VisualIdentityOutcome,
    canonical_visual_identity_data_bytes,
)
from table_evidence_analyzer.visual_identity_crop_input import VisualIdentityCropInputItem

from dokodetector_backend.job_store import Job, JobCancelled, JobManager
from dokodetector_backend.pipeline_node_selection_store import PipelineNodeSelectionStore
from dokodetector_backend.pipeline_store import (
    PipelineRuntimeStorage,
    PipelineSelectionConflict,
    ProcessorRunStore,
    StoredPipelineRevision,
    StoredProcessorRun,
)
from dokodetector_backend.visual_identity_approval import _AUTO_APPROVAL_LOCAL_PURPOSE
from dokodetector_backend.visual_identity_classification import (
    VisualIdentityClassification,
    _implementation_id,
    _model_id,
)
from dokodetector_backend.visual_identity_crop_provenance import crop_input_provenance
from dokodetector_backend.visual_identity_crop_sources import VisualIdentityCropSources
from dokodetector_backend.visual_identity_pipeline_errors import VisualIdentityPipelineError
from dokodetector_backend.visual_identity_recording_access import VisualIdentityRecordingAccess
from dokodetector_backend.visual_identity_request import (
    VisualIdentityRequestBuilder,
    _default_crop_policy,
)

LOGGER = logging.getLogger(__name__)
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._:-]+")


def _safe(value: str) -> str:
    return _SAFE_COMPONENT.sub("-", value).strip("-") or "unknown"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class VisualIdentityJobExecutor:
    """Execute persisted identity work through the shared JobManager owner."""

    def __init__(
        self,
        *,
        run_store: ProcessorRunStore,
        selection_store: PipelineNodeSelectionStore,
        storage: PipelineRuntimeStorage,
        crop_sources: VisualIdentityCropSources,
        request_builder: VisualIdentityRequestBuilder,
        recording_access: VisualIdentityRecordingAccess,
        classification: VisualIdentityClassification,
    ) -> None:
        self.run_store = run_store
        self.selection_store = selection_store
        self.storage = storage
        self.crop_sources = crop_sources
        self.request_builder = request_builder
        self.recording_access = recording_access
        self.classification = classification

    def execute_job(
        self, job: Job, token: Any, manager: JobManager, *, cpu_budget: int = 1
    ) -> None:
        if cpu_budget < 1:
            raise ValueError("The visual identity CPU budget must be positive.")
        run = self.run_store.start(job.id)
        try:
            token.check()
            run_id = job.id
            if len(run.request.input_revision_ids) != 1 or run.request.crop_input is None:
                raise VisualIdentityPipelineError("The frozen crop input is unavailable.")
            visible_revision = self.request_builder.canonical_input_revision(run.request)
            _, source = self.recording_access.accepted_source(run.request.source.recording_id)
            frozen_input = self.request_builder._freeze_crop_input(
                run.request.source.recording_id,
                visible_revision,
                source=source,
                requested=run.request.crop_input,
                input_node_ref=(run.request.input_node_refs or [None])[0],
            )
            if frozen_input.to_mapping() != run.request.crop_input:
                raise VisualIdentityPipelineError("The frozen crop input changed.")
            if isinstance(visible_revision.content, VisibleCardData):
                candidate_lookup = {
                    (outcome.frame_identity.frame_index, candidate.card_id): (outcome, candidate)
                    for outcome in visible_revision.content.outcomes
                    if outcome.status == "detected" and outcome.frame_identity is not None
                    for candidate in outcome.candidates
                }
                self.request_builder._validate_scene_derived_views(visible_revision.content)
            elif isinstance(visible_revision.content, ProposedCardSceneData):
                grouped: dict[int, list[VisualIdentityCropInputItem]] = {}
                for crop_item in frozen_input.items:
                    grouped.setdefault(crop_item.frame_identity.frame_index, []).append(crop_item)
                candidate_lookup = {}
                for frame_index, frame_items in grouped.items():
                    frame_identity = frame_items[0].frame_identity
                    candidates_for_frame = tuple(
                        VisibleCardCandidate(
                            card_id=item.card_id,
                            geometry=item.geometry,
                            normalization={
                                "width": frame_identity.width,
                                "height": frame_identity.height,
                                "policy_id": "full-frame-0-1000/v1",
                            },
                            side=item.side,
                        )
                        for item in frame_items
                    )
                    synthetic = VisibleCardOutcome(
                        event_id=f"proposal-frame-{frame_index}",
                        frame_identity=frame_identity,
                        status="detected",
                        candidates=candidates_for_frame,
                    )
                    for candidate in candidates_for_frame:
                        candidate_lookup[(frame_index, candidate.card_id)] = (synthetic, candidate)
            else:
                raise VisualIdentityPipelineError("The visual identity input revision is invalid.")
            item_ids = self.request_builder._identity_item_ids(frozen_input.items)
            candidates: list[tuple[Any, Any, VisualIdentityCropInputItem, str]] = []
            for crop_item, item_id in zip(frozen_input.items, item_ids, strict=True):
                key = (crop_item.frame_identity.frame_index, crop_item.card_id)
                pair = candidate_lookup.get(key)
                if (
                    pair is None
                    or pair[0].frame_identity.to_mapping() != crop_item.frame_identity.to_mapping()
                    or pair[1].geometry.to_mapping() != crop_item.geometry.to_mapping()
                    or pair[1].side != crop_item.side
                ):
                    raise VisualIdentityPipelineError(
                        "The frozen crop input no longer matches its source."
                    )
                candidates.append((pair[0], pair[1], crop_item, item_id))
            outcomes_by_index: list[VisualIdentityOutcome | None] = [None] * len(candidates)
            prior_items = {item.item_id: item for item in run.state.items}
            candidate_ids = {item_id for _, _, _, item_id in candidates}
            if not set(prior_items).issubset(candidate_ids):
                raise VisualIdentityPipelineError(
                    "The retry contains an item that is not in the frozen card input."
                )
            items_by_index: list[RunItemOutcome | None] = [
                prior_items.get(item_id) for _, _, _, item_id in candidates
            ]
            pending_candidates: list[tuple[int, Any, Any, VisualIdentityCropInputItem, str]] = []
            completed = 0
            for index, (visible_outcome, candidate, crop_item, item_id) in enumerate(candidates):
                token.check()
                item = items_by_index[index]
                if item is None or item.status != "succeeded":
                    pending_candidates.append(
                        (index, visible_outcome, candidate, crop_item, item_id)
                    )
                    continue
                if item.result is None:
                    raise VisualIdentityPipelineError(
                        f"The retained outcome for card {candidate.card_id} is invalid."
                    )
                try:
                    result = VisualIdentityOutcome.from_mapping(item.result)
                except ValueError as error:
                    raise VisualIdentityPipelineError(
                        f"The retained outcome for card {candidate.card_id} is invalid."
                    ) from error
                if result.card_id != item_id:
                    raise VisualIdentityPipelineError(
                        f"The retained outcome for card {item_id} has the wrong ID."
                    )
                outcomes_by_index[index] = result
                completed += 1
            self.run_store.update_progress(
                run_id,
                progress=RunProgress(completed=completed, total=len(candidates)),
            )
            provenance = (
                crop_input_provenance(frozen_input, frozen_input.items[0]) if candidates else None
            )
            frame_cache: OrderedDict[tuple[int, str], Any] = OrderedDict()
            with ThreadPoolExecutor(
                max_workers=min(
                    cpu_budget,
                    self.classification.max_concurrent_requests(run.request),
                    max(1, len(pending_candidates)),
                ),
                thread_name_prefix="visual-identity-card",
            ) as executor:
                futures: dict[Future[VisualIdentityOutcome], int] = {
                    executor.submit(
                        self.classification.process_card_timed,
                        run,
                        outcome,
                        candidate,
                        crop_item,
                        item_id,
                        provenance,
                        frame_cache,
                    ): index
                    for index, outcome, candidate, crop_item, item_id in pending_candidates
                }
                for future in as_completed(futures):
                    token.check()
                    index = futures[future]
                    outcome, candidate, crop_item, item_id = candidates[index]
                    try:
                        result = future.result()
                    except Exception:
                        LOGGER.exception(
                            "visual_identity_card_failed",
                            extra={"run_id": run.run_id, "card_id": item_id},
                        )
                        result = VisualIdentityOutcome(
                            card_id=item_id,
                            frame_identity=outcome.frame_identity,
                            geometry=candidate.geometry,
                            crop_identity=None,
                            classifier=self.classification.classifier_identity(run.request),
                            status="failed",
                            candidates=(),
                            error="The visual identity classifier failed for this card.",
                            crop_input_provenance=provenance,
                        )
                    outcomes_by_index[index] = result
                    item = RunItemOutcome(
                        item_id=item_id,
                        status="succeeded",
                        result=result.to_mapping(),
                        failure=None,
                    )
                    items_by_index[index] = item
                    completed += 1
                    self.run_store.record_item_progress(
                        run_id,
                        progress=RunProgress(completed=completed, total=len(candidates)),
                        item=item,
                    )
                    manager.report_progress(
                        job.id,
                        phase="Classify visible cards",
                        completed=completed,
                        total=len(candidates),
                        unit="cards",
                    )

            outcomes = [outcome for outcome in outcomes_by_index if outcome is not None]
            items = tuple(item for item in items_by_index if item is not None)
            if len(outcomes) != len(candidates) or len(items) != len(candidates):
                raise VisualIdentityPipelineError(
                    "The visual identity classifier did not process all cards."
                )
            content = VisualIdentityData(outcomes=tuple(outcomes))
            token.check()
            expected_digest = sha256_bytes(canonical_visual_identity_data_bytes(content))
            expected_revision_id = (
                f"visual-identities-{_safe(run.run_id)}-attempt-{run.state.attempt}"
            )
            output = {
                "kind": "pipeline_revision",
                "id": expected_revision_id,
                "digest": expected_digest,
                "available": True,
            }

            def commit() -> None:
                revision = self._publish_revision(run, content)
                if (
                    revision.manifest.revision_id != expected_revision_id
                    or revision.manifest.content_sha256 != expected_digest
                ):
                    raise VisualIdentityPipelineError(
                        "The identity result changed during publication."
                    )
                self.run_store.complete(
                    run_id,
                    [revision.manifest.revision_id],
                    progress=RunProgress(completed=len(items), total=len(candidates)),
                    items=items,
                )
                if run.request.configuration.get("purpose") != _AUTO_APPROVAL_LOCAL_PURPOSE:
                    self._advance_generated_selection(
                        run.request.source.recording_id, revision.manifest.revision_id
                    )

            if not manager.publish(job.id, [output], commit):
                raise JobCancelled("job cancellation requested before identity publication")
        except JobCancelled:
            self._fail_safely(run.run_id, "cancelled", "Identity processing was cancelled.")
            raise
        except Exception as error:
            self._fail_safely(
                run.run_id, "classifier_failed", str(error) or "Identity processing failed."
            )
            raise

    def _publish_revision(
        self, run: StoredProcessorRun, content: VisualIdentityData
    ) -> StoredPipelineRevision:
        producer = ProcessorProducer(
            run_id=run.run_id,
            processor_type=run.request.processor_type,
            implementation_id=_implementation_id(run.request.implementation),
            model_id=_model_id(run.request.model),
        )
        crop_policy = run.request.crop_policy or _default_crop_policy(
            self.request_builder.canonical_input_revision(run.request).content
        )
        manifest = DataRevision(
            revision_id=f"visual-identities-{_safe(run.run_id)}-attempt-{run.state.attempt}",
            content_type="visual_identities",
            content_schema="visual-identity-data/v2",
            recording_id=run.request.source.recording_id,
            source=run.request.source,
            content_sha256=sha256_bytes(canonical_visual_identity_data_bytes(content)),
            input_revision_ids=run.request.input_revision_ids,
            origin="processor",
            producer=producer,
            coverage={
                "kind": "requested-visible-cards",
                "visible_card_revision_id": run.request.input_revision_ids[0],
                "card_ids": [outcome.card_id for outcome in content.outcomes],
                "policy_id": crop_policy["policy_id"],
            },
            created_at=_now(),
        )
        stored, _ = self.selection_store.publish_processor_revision(manifest, content)
        return stored

    def _advance_generated_selection(self, recording_id: str, revision_id: str) -> None:
        current = self.selection_store.get_exact(recording_id, "visual_identities")
        expected = 0 if current is None else current.revision
        completed = None if current is None else current.selected_completed_reference
        generated = self.selection_store.reference_for_processor_output(
            revision_id, recording_id, "visual_identities"
        )
        try:
            self.selection_store.update_exact(
                recording_id,
                "visual_identities",
                expected_revision=expected,
                selected_generated=generated,
                selected_completed_reference=completed,
            )
        except PipelineSelectionConflict:
            LOGGER.warning(
                "visual_identity_pipeline_selection_advance_conflict",
                extra={"recording_id": recording_id},
            )

    def _fail_safely(self, run_id: str, code: str, message: str) -> None:
        try:
            run = self.run_store.get(run_id)
            if run is not None and run.state.status == "running":
                self.run_store.fail(run_id, RunFailure(code=code, message=message))
        except Exception:
            LOGGER.exception("visual_identity_pipeline_failure_persist_failed")
