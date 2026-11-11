"""Deterministic comparisons of retained pipeline runs and revisions."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import Any

from doko_operations.pipeline_comparison_contract import (
    PIPELINE_COMPARISON_ALGORITHM_VERSION,
    PipelineComparison,
    PipelineComparisonContractError,
    PipelineComparisonDelta,
    PipelineComparisonReference,
    PipelineComparisonRequest,
    PipelineComparisonSide,
    build_comparison_scope,
    build_frame_comparison_scope,
    normalize_event_coverage,
)
from doko_operations.pipeline_comparison_execution import (
    compare_event_data,
    compare_visible_card_data,
    compare_visual_identity_data,
)
from doko_operations.pipeline_data import EventData, canonical_json_bytes

from dokodetector_backend.event_set_store import EventSetStore
from dokodetector_backend.pipeline_node_selection_store import PipelineNodeSelectionStore
from dokodetector_backend.pipeline_service_errors import PipelineServiceError
from dokodetector_backend.pipeline_storage import PipelineNotFound
from dokodetector_backend.processor_run_models import StoredProcessorRun
from dokodetector_backend.processor_run_store import ProcessorRunStore


class PipelineComparisonError(PipelineServiceError):
    """A recording-pipeline comparison could not be calculated."""


class PipelineComparisonInputError(PipelineComparisonError, ValueError):
    """A comparison request or retained input is invalid."""


class PipelineComparisonService:
    """Calculate deterministic comparisons from immutable retained event resources."""

    def __init__(
        self,
        *,
        selection_store: PipelineNodeSelectionStore,
        run_store: ProcessorRunStore,
        event_set_store: EventSetStore | None = None,
    ) -> None:
        self.selection_store = selection_store
        self.run_store = run_store
        self.event_set_store = event_set_store

    def compare(
        self, recording_id: str, payload: Mapping[str, Any] | PipelineComparisonRequest
    ) -> PipelineComparison:
        try:
            comparison_request = (
                payload
                if isinstance(payload, PipelineComparisonRequest)
                else PipelineComparisonRequest.from_mapping(payload)
            )
        except (PipelineComparisonContractError, TypeError, ValueError) as error:
            raise PipelineComparisonInputError(str(error)) from error
        if comparison_request.recording_id != recording_id:
            raise PipelineComparisonInputError("comparison recording_id differs from the route")
        if comparison_request.left_run_id == comparison_request.right_run_id:
            raise PipelineComparisonInputError("left_run_id and right_run_id must differ")

        if comparison_request.content_type == "events":
            left_run, left_revision = self._resolve_event_run(
                recording_id, comparison_request.left_run_id
            )
            right_run, right_revision = self._resolve_event_run(
                recording_id, comparison_request.right_run_id
            )
        else:
            left_run, left_revision = self._resolve_run(
                recording_id, comparison_request.left_run_id, comparison_request.content_type
            )
            right_run, right_revision = self._resolve_run(
                recording_id, comparison_request.right_run_id, comparison_request.content_type
            )
        if right_run.request.source != left_run.request.source:
            raise PipelineComparisonInputError(
                "comparison runs do not use the same accepted recording video"
            )
        if comparison_request.content_type == "events":
            reference = self._resolve_event_reference(
                recording_id,
                comparison_request.reference_event_set_ref,
                expected_source=left_run.request.source,
            )
        else:
            reference = self._resolve_reference(
                recording_id,
                comparison_request.reference_revision_id,
                comparison_request.content_type,
                left_run.request.source,
            )
        if comparison_request.content_type == "events":
            duration_us = left_run.request.source.duration_us
            try:
                left_coverage = normalize_event_coverage(
                    left_revision.coverage, duration_us=duration_us
                )
                right_coverage = normalize_event_coverage(
                    right_revision.coverage, duration_us=duration_us
                )
                reviewed = normalize_event_coverage(reference.coverage, duration_us=duration_us)
            except PipelineComparisonContractError as error:
                raise PipelineComparisonInputError(str(error)) from error
            scope = build_comparison_scope(
                reviewed=reviewed,
                left_coverage=left_coverage,
                right_coverage=right_coverage,
            )
            counts, metrics, items = compare_event_data(
                recording_id=recording_id,
                left_run_id=left_run.run_id,
                right_run_id=right_run.run_id,
                reference=reference.content,
                left=left_revision.content,
                right=right_revision.content,
                policy=comparison_request.matching_policy,
                scope=scope,
                left_coverage=left_coverage,
                right_coverage=right_coverage,
            )
        else:
            scope = build_frame_comparison_scope(
                reviewed=_frame_mappings(reference.content.outcomes),
                left=_frame_mappings(left_revision.content.outcomes),
                right=_frame_mappings(right_revision.content.outcomes),
            )
            if comparison_request.content_type == "visible_cards":
                counts, metrics, items = compare_visible_card_data(
                    recording_id=recording_id,
                    reference=reference.content,
                    left=left_revision.content,
                    right=right_revision.content,
                    policy=comparison_request.matching_policy,
                    scope=scope,
                )
            else:
                reference_inputs = reference.manifest.input_revision_ids
                counts, metrics, items = compare_visual_identity_data(
                    recording_id=recording_id,
                    reference=reference.content,
                    left=left_revision.content,
                    right=right_revision.content,
                    policy=comparison_request.matching_policy,
                    scope=scope,
                    left_exact_upstream=(
                        len(reference_inputs) == 1
                        and left_run.request.input_revision_ids == reference_inputs
                    ),
                    right_exact_upstream=(
                        len(reference_inputs) == 1
                        and right_run.request.input_revision_ids == reference_inputs
                    ),
                )
        mode = (
            "paired_processor"
            if self._paired_inputs(left_run, right_run)
            else "upstream_experiment"
        )
        paired_delta = None if mode == "upstream_experiment" else _paired_delta(metrics)
        left_side = self._side(left_run, left_revision)
        right_side = self._side(right_run, right_revision)
        reference_identity = self._reference_identity(reference, comparison_request.content_type)
        identity = {
            "request": comparison_request.to_mapping(),
            "left_content_sha256": left_revision.manifest.content_sha256,
            "right_content_sha256": right_revision.manifest.content_sha256,
            "reference_content_sha256": reference.manifest.content_sha256,
            "algorithm_version": PIPELINE_COMPARISON_ALGORITHM_VERSION,
        }
        comparison_id = (
            "comparison-" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()[:32]
        )
        return PipelineComparison(
            comparison_id=comparison_id,
            recording_id=recording_id,
            content_type=comparison_request.content_type,
            mode=mode,
            algorithm_version=PIPELINE_COMPARISON_ALGORITHM_VERSION,
            left=left_side,
            right=right_side,
            reference=reference_identity,
            scope=scope,
            matching_policy=comparison_request.matching_policy,
            counts=counts,
            metrics=metrics,
            paired_delta=paired_delta,
            items=items,
        )

    def _resolve_event_run(self, recording_id: str, run_id: str) -> tuple[StoredProcessorRun, Any]:
        run = self.run_store.require(run_id)
        if run.request.source.recording_id != recording_id:
            raise PipelineNotFound(f"The processor run was not found for recording: {recording_id}")
        if run.request.processor_type != "event-detection":
            raise PipelineComparisonInputError(f"run {run_id} is not an event-detection run")
        if run.state.status not in {"complete", "partial"}:
            raise PipelineComparisonInputError(
                f"run {run_id} is not comparable because its status is {run.state.status}"
            )
        if self.event_set_store is None:
            raise PipelineComparisonInputError("event-set comparison is unavailable")
        stored = self.event_set_store.get(recording_id, f"run-{run_id}", "1")
        if stored is None:
            raise PipelineComparisonInputError(f"run {run_id} has no saved event set")
        source = stored.get("source")
        if not isinstance(source, Mapping) or (
            source.get("recording_id") != recording_id
            or source.get("video_sha256") != run.request.source.video_sha256
        ):
            raise PipelineComparisonInputError(
                f"run {run_id} event set has a different video source"
            )
        if run.state.output_revision_ids:
            raise PipelineComparisonInputError(
                f"run {run_id} still publishes legacy node revisions"
            )
        value = _event_set_value(stored, self.event_set_store, recording_id)
        return run, value

    def _resolve_event_reference(
        self,
        recording_id: str,
        reference: Mapping[str, str] | None,
        *,
        expected_source: Any,
    ) -> Any:
        if self.event_set_store is None or reference is None:
            raise PipelineComparisonInputError(
                "event comparison needs an exact event-set reference"
            )
        event_set = self.event_set_store.get(
            recording_id, reference["set_id"], reference["version"]
        )
        if event_set is None or event_set.get("content_sha256") != reference["content_sha256"]:
            raise PipelineComparisonInputError(
                "reference event set does not match its exact digest"
            )
        if event_set.get("origin") not in {"manual", "corrected"}:
            raise PipelineComparisonInputError("reference event set is not reviewed content")
        source = event_set.get("source")
        if not isinstance(source, Mapping) or (
            source.get("recording_id") != recording_id
            or source.get("video_sha256") != expected_source.video_sha256
        ):
            raise PipelineComparisonInputError(
                "reference event set does not match the exact recording video"
            )
        return _event_set_value(event_set, self.event_set_store, recording_id)

    @staticmethod
    def _reference_identity(reference: Any, content_type: str) -> PipelineComparisonReference:
        if content_type == "events":
            return PipelineComparisonReference(
                revision_id=None,
                event_set_ref=reference.event_set_ref,
                input_revision_ids=(),
                content_sha256=reference.manifest.content_sha256,
                origin=reference.manifest.origin,
            )
        return PipelineComparisonReference(
            revision_id=reference.manifest.revision_id,
            event_set_ref=None,
            input_revision_ids=reference.manifest.input_revision_ids,
            content_sha256=reference.manifest.content_sha256,
            origin=reference.manifest.origin,
        )

    def _resolve_run(
        self, recording_id: str, run_id: str, content_type: str
    ) -> tuple[StoredProcessorRun, Any]:
        run = self.run_store.require(run_id)
        if run.request.source.recording_id != recording_id:
            raise PipelineNotFound(f"The processor run was not found for recording: {recording_id}")
        if run.state.status not in {"complete", "partial"}:
            raise PipelineComparisonInputError(
                f"run {run_id} is not comparable because its status is {run.state.status}"
            )
        revisions = []
        for revision_id in run.state.output_revision_ids:
            revision = self.selection_store.require_processor_revision(revision_id)
            if (
                revision.manifest.content_type == content_type
                and revision.manifest.recording_id == recording_id
                and revision.manifest.source == run.request.source
            ):
                revisions.append(revision)
        if len(revisions) != 1:
            raise PipelineComparisonInputError(
                f"run {run_id} does not have one valid {content_type} output revision"
            )
        return run, revisions[0]

    def _resolve_reference(
        self,
        recording_id: str,
        revision_id: str,
        content_type: str,
        source: Any,
    ) -> Any:
        revision = self.selection_store.require_revision(revision_id)
        manifest = revision.manifest
        if (
            manifest.recording_id != recording_id
            or manifest.content_type != content_type
            or manifest.source != source
            or manifest.origin not in {"manual", "corrected"}
        ):
            raise PipelineComparisonInputError(
                "reference revision does not match the recording, content type, or video"
            )
        return revision

    @staticmethod
    def _paired_inputs(left: StoredProcessorRun, right: StoredProcessorRun) -> bool:
        return (
            left.request.input_revision_ids == right.request.input_revision_ids
            and left.request.extraction_policy == right.request.extraction_policy
            and left.request.crop_policy == right.request.crop_policy
        )

    @staticmethod
    def _side(run: StoredProcessorRun, revision: Any) -> PipelineComparisonSide:
        event_set_ref = getattr(revision, "event_set_ref", None)
        return PipelineComparisonSide(
            run_id=run.run_id,
            revision_id=None if event_set_ref is not None else revision.manifest.revision_id,
            event_set_ref=event_set_ref,
            status=run.state.status,
            input_revision_ids=run.request.input_revision_ids,
            content_sha256=revision.manifest.content_sha256,
            implementation=run.request.implementation.to_mapping(),
            model=None if run.request.model is None else run.request.model.to_mapping(),
            configuration=run.request.configuration,
            extraction_policy=run.request.extraction_policy,
        )


def _paired_delta(metrics: dict[str, Any]) -> Any:
    left = metrics["left"]
    right = metrics["right"]

    def difference(name: str) -> float | None:
        first = getattr(right, name)
        second = getattr(left, name)
        return None if first is None or second is None else first - second

    max_left = left.max_error_us
    max_right = right.max_error_us
    return PipelineComparisonDelta(
        precision=difference("precision"),
        recall=difference("recall"),
        f1=difference("f1"),
        mean_error_us=difference("mean_error_us"),
        max_error_us=None if max_left is None or max_right is None else max_right - max_left,
    )


def _frame_mappings(outcomes: Sequence[Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        outcome.frame_identity.to_mapping()
        for outcome in outcomes
        if getattr(outcome, "frame_identity", None) is not None
    )


def _event_set_value(event_set: Mapping[str, Any], store: EventSetStore, recording_id: str) -> Any:
    set_id = event_set["set_id"]
    version = event_set["version"]
    reviews = store.list_reviews(recording_id, set_id, version)
    coverage_reviews = [review for review in reviews if review.get("kind") == "coverage"]
    if len(coverage_reviews) > 1:
        raise PipelineComparisonInputError(
            "event set has multiple coverage reviews; comparison scope is ambiguous"
        )
    coverage = coverage_reviews[0]["coverage"] if coverage_reviews else {"kind": "full-recording"}
    reference = {
        "set_id": set_id,
        "version": version,
        "content_sha256": event_set["content_sha256"],
    }
    manifest = SimpleNamespace(
        revision_id=None,
        input_revision_ids=(),
        content_sha256=event_set["content_sha256"],
        origin=event_set["origin"],
        coverage=coverage,
    )
    return SimpleNamespace(
        manifest=manifest,
        content=EventData.from_mapping(event_set["content"]),
        coverage=coverage,
        event_set_ref=reference,
    )


__all__ = [
    "PipelineComparisonError",
    "PipelineComparisonInputError",
    "PipelineComparisonService",
]
