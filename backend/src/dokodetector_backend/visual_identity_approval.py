"""Plan authority-guarded visual identity auto-approval comparisons."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from doko_operations.pipeline_data import ProcessorRunRequest, sha256_bytes
from table_evidence_analyzer.pipeline_data import VisualIdentityData, VisualIdentityOutcome

from dokodetector_backend.pipeline_node_selection_store import PipelineNodeSelectionStore
from dokodetector_backend.pipeline_store import (
    ProcessorRunStore,
    StoredProcessorRun,
)
from dokodetector_backend.visual_identity_pipeline_errors import VisualIdentityPipelineInputError

_AUTO_APPROVAL_LOCAL_PURPOSE = "auto_approval_comparison"


@dataclass(frozen=True)
class VisualIdentityApprovalPlan:
    source_revision_id: str
    items: tuple[dict[str, Any], ...]
    local_run_request: dict[str, Any] | None


class VisualIdentityApprovalPlanner:
    """Compare retained outcomes and describe missing local work for the service."""

    def __init__(
        self,
        selection_store: PipelineNodeSelectionStore,
        run_store: ProcessorRunStore,
    ) -> None:
        self.selection_store = selection_store
        self.run_store = run_store

    def plan_auto_approval(
        self,
        recording_id: str,
        source_revision_id: str,
        draft_items: tuple[Mapping[str, Any], ...],
    ) -> VisualIdentityApprovalPlan:
        """Compare retained Cloud and local outcomes for one identity draft.

        This method deliberately only plans work.  A later revision-guarded review command
        applies the accepted decisions, so a plan can never overwrite an operator decision.
        """

        source = self.selection_store.require_processor_revision(source_revision_id)
        if (
            source.manifest.content_type != "visual_identities"
            or source.manifest.source.recording_id != recording_id
            or not isinstance(source.content, VisualIdentityData)
        ):
            raise VisualIdentityPipelineInputError("The identity draft source is unavailable.")
        cloud_run = self._run_for_output(recording_id, source_revision_id)
        if cloud_run is None or cloud_run.request.input_revision_ids == ():
            raise VisualIdentityPipelineInputError(
                "The identity draft has no retained processor lineage."
            )
        visible_revision_id = cloud_run.request.input_revision_ids[0]
        cloud_outcomes = {
            outcome.card_id: outcome
            for outcome in source.content.outcomes
            if outcome.classifier.provider == "gemini"
        }
        local_results = self._retained_local_results(recording_id, visible_revision_id)
        items: list[dict[str, Any]] = []
        needs_local = False
        for draft_item in draft_items:
            item_id = draft_item.get("item_id")
            item = draft_item.get("item")
            state = draft_item.get("review_state")
            if not isinstance(item_id, str) or not isinstance(item, Mapping):
                continue
            cloud = cloud_outcomes.get(item_id)
            local = None if cloud is None else local_results.get(self._outcome_key(cloud))
            reason = self.auto_approval_reason(state, cloud, local)
            if cloud is not None and local is None:
                needs_local = True
            items.append(
                {
                    "item_id": item_id,
                    "reason": reason,
                    "eligible": reason == "eligible",
                    "gemini_result": self._result_provenance(source_revision_id, cloud),
                    "local_result": None if local is None else self._result_provenance(*local),
                }
            )
        local_run_request = (
            self._auto_approval_local_request(recording_id, visible_revision_id, cloud_run.request)
            if needs_local
            else None
        )
        return VisualIdentityApprovalPlan(
            source_revision_id=source_revision_id,
            items=tuple(items),
            local_run_request=local_run_request,
        )

    def _run_for_output(self, recording_id: str, revision_id: str) -> StoredProcessorRun | None:
        matches = [
            run
            for run in self.list_runs(recording_id)
            if revision_id in run.state.output_revision_ids
        ]
        return max(
            matches, key=lambda run: (run.state.completed_at or "", run.run_id), default=None
        )

    def list_runs(self, recording_id: str) -> tuple[StoredProcessorRun, ...]:
        return tuple(
            run
            for run in self.run_store.list_for_recording(recording_id)
            if run.request.source.recording_id == recording_id
            and run.request.processor_type == "visual-card-identity"
        )

    def _retained_local_results(
        self, recording_id: str, visible_revision_id: str
    ) -> dict[tuple[Any, ...], tuple[str, VisualIdentityOutcome]]:
        selected: dict[tuple[Any, ...], tuple[str, VisualIdentityOutcome, str]] = {}
        for run in self.list_runs(recording_id):
            if (
                run.state.status != "complete"
                or run.request.input_revision_ids != (visible_revision_id,)
                or not str(run.request.configuration.get("provider", "")).startswith("local")
            ):
                continue
            for revision_id in run.state.output_revision_ids:
                revision = self.selection_store.require_processor_revision(revision_id)
                if not isinstance(revision.content, VisualIdentityData):
                    continue
                for outcome in revision.content.outcomes:
                    key = self._outcome_key(outcome)
                    candidate = (revision_id, outcome, run.state.completed_at or "")
                    current = selected.get(key)
                    if current is None or (candidate[2], revision_id) > (current[2], current[0]):
                        selected[key] = candidate
        return {key: (value[0], value[1]) for key, value in selected.items()}

    @staticmethod
    def _outcome_key(outcome: VisualIdentityOutcome) -> tuple[Any, ...]:
        return (
            outcome.card_id,
            json.dumps(outcome.frame_identity.to_mapping(), sort_keys=True),
            json.dumps(outcome.geometry.to_mapping(), sort_keys=True),
            None
            if outcome.crop_identity is None
            else json.dumps(outcome.crop_identity.to_mapping(), sort_keys=True),
        )

    @staticmethod
    def _result_provenance(
        revision_id: str, outcome: VisualIdentityOutcome | None
    ) -> dict[str, Any] | None:
        if outcome is None:
            return None
        return {"result_id": revision_id, "classifier": outcome.classifier.to_mapping()}

    @staticmethod
    def auto_approval_reason(
        state: Any,
        cloud: VisualIdentityOutcome | None,
        local: tuple[str, VisualIdentityOutcome] | None,
    ) -> str:
        if state != "pending":
            return "already_reviewed"
        if cloud is None:
            return "gemini_unavailable"
        if cloud.status == "face_down":
            return "gemini_face_down"
        if cloud.status == "unusable":
            return "gemini_unusable"
        if cloud.status == "failed":
            return "gemini_failed"
        if cloud.status != "classified" or not cloud.candidates:
            return "gemini_unavailable"
        if local is None:
            return "local_unavailable"
        local_outcome = local[1]
        if local_outcome.status == "face_down":
            return "local_face_down"
        if local_outcome.status == "unusable":
            return "local_unusable"
        if local_outcome.status == "failed":
            return "local_failed"
        if local_outcome.status != "classified" or not local_outcome.candidates:
            return "local_unavailable"
        if cloud.candidates[0].identity != local_outcome.candidates[0].identity:
            return "identity_mismatch"
        return "eligible"

    def _auto_approval_local_request(
        self, recording_id: str, visible_revision_id: str, cloud_request: ProcessorRunRequest
    ) -> dict[str, Any]:
        token = sha256_bytes(
            json.dumps(
                {
                    "recording_id": recording_id,
                    "visible_revision_id": visible_revision_id,
                    "crop_policy": cloud_request.crop_policy,
                },
                sort_keys=True,
            ).encode("utf-8")
        )[:20]
        return {
            "run_id": f"auto-approve-local-{token}",
            "visible_card_revision_id": visible_revision_id,
            "configuration": {
                "provider": "local",
                "purpose": _AUTO_APPROVAL_LOCAL_PURPOSE,
            },
            "crop_policy": cloud_request.crop_policy,
            "extraction_policy": cloud_request.extraction_policy,
        }
