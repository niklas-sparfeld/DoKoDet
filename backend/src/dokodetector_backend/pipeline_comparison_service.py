"""Deterministic comparisons of retained pipeline runs and revisions."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from doko_operations.pipeline_comparison import (
    PIPELINE_COMPARISON_ALGORITHM_VERSION,
    PipelineComparison,
    PipelineComparisonContractError,
    PipelineComparisonDelta,
    PipelineComparisonReference,
    PipelineComparisonRequest,
    PipelineComparisonSide,
    build_comparison_scope,
    build_frame_comparison_scope,
    compare_event_data,
    compare_visible_card_data,
    compare_visual_identity_data,
    normalize_event_coverage,
)
from doko_operations.pipeline_data import canonical_json_bytes

from dokodetector_backend.pipeline_service_errors import PipelineServiceError
from dokodetector_backend.pipeline_store import (
    PipelineNotFound,
    PipelineRevisionStore,
    ProcessorRunStore,
    StoredProcessorRun,
)


class PipelineComparisonError(PipelineServiceError):
    """A recording-pipeline comparison could not be calculated."""


class PipelineComparisonInputError(PipelineComparisonError, ValueError):
    """A comparison request or retained input is invalid."""


class PipelineComparisonService:
    """Calculate deterministic comparisons from immutable retained event resources."""

    def __init__(
        self,
        *,
        revision_store: PipelineRevisionStore,
        run_store: ProcessorRunStore,
    ) -> None:
        self.revision_store = revision_store
        self.run_store = run_store

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
                    left_revision.manifest.coverage, duration_us=duration_us
                )
                right_coverage = normalize_event_coverage(
                    right_revision.manifest.coverage, duration_us=duration_us
                )
                reviewed = normalize_event_coverage(
                    reference.manifest.coverage, duration_us=duration_us
                )
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
        reference_identity = PipelineComparisonReference(
            revision_id=reference.manifest.revision_id,
            input_revision_ids=reference.manifest.input_revision_ids,
            content_sha256=reference.manifest.content_sha256,
            origin=reference.manifest.origin,
        )
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
            revision = self.revision_store.require(revision_id)
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
        revision = self.revision_store.require(revision_id)
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
        return PipelineComparisonSide(
            run_id=run.run_id,
            revision_id=revision.manifest.revision_id,
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


__all__ = [
    "PipelineComparisonError",
    "PipelineComparisonInputError",
    "PipelineComparisonService",
]
