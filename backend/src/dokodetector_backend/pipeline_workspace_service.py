"""Read-only recording workspace composition for pipeline state."""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from doko_operations.pipeline_data import EventData, RecordingVideoSource
from table_evidence_analyzer import ObservationAssemblyError, assemble_table_observations
from table_evidence_analyzer.pipeline_data import VisibleCardData, VisualIdentityData

from dokodetector_backend.pipeline_store import (
    PipelineRevisionStore,
    PipelineSelectionStore,
    PipelineStoreError,
    ProcessorRunStore,
    StoredProcessorRun,
)
from dokodetector_backend.round_analysis_contract import parse_round_analysis_create_request_bytes

LOGGER = logging.getLogger(__name__)
_UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class _WorkspaceStageDefinition:
    key: str
    processor_key: str
    processor_type: str
    content_type: str
    reviewable: bool


_WORKSPACE_STAGES = (
    _WorkspaceStageDefinition(
        key="events",
        processor_key="event_detection",
        processor_type="event-detection",
        content_type="events",
        reviewable=True,
    ),
    _WorkspaceStageDefinition(
        key="visible_cards",
        processor_key="visible_card_detection",
        processor_type="visible-card-detection",
        content_type="visible_cards",
        reviewable=True,
    ),
    _WorkspaceStageDefinition(
        key="visual_identities",
        processor_key="visual_identity_classification",
        processor_type="visual-card-identity",
        content_type="visual_identities",
        reviewable=True,
    ),
    _WorkspaceStageDefinition(
        key="table_observations",
        processor_key="observation_assembly",
        processor_type="observation-assembly",
        content_type="table_observations",
        reviewable=False,
    ),
    _WorkspaceStageDefinition(
        key="round_analyses",
        processor_key="round_analysis",
        processor_type="round-analysis",
        content_type="round_analyses",
        reviewable=False,
    ),
)


@dataclass(frozen=True, slots=True)
class _WorkspaceReference:
    """Reference state for workspace summaries, with an optional loaded draft."""

    state: Any
    draft: Any | None


class RecordingPipelineWorkspaceService:
    """Aggregate persisted recording-pipeline state for the recording workspace."""

    def __init__(
        self,
        *,
        recording_source_provider: Callable[[str], RecordingVideoSource],
        revision_store: PipelineRevisionStore,
        run_store: ProcessorRunStore,
        selection_store: PipelineSelectionStore,
        reference_store: Any,
        round_analysis_store: Any,
    ) -> None:
        self.recording_source_provider = recording_source_provider
        self.revision_store = revision_store
        self.run_store = run_store
        self.selection_store = selection_store
        self.reference_store = reference_store
        self.round_analysis_store = round_analysis_store

    def get_workspace(
        self,
        recording_id: str,
        *,
        stage_key: str | None = None,
    ) -> dict[str, Any]:
        """Read one complete workspace snapshot without changing pipeline state."""

        source = self.recording_source_provider(recording_id)
        revision_cache: dict[str, Any] = {}
        revisions = tuple(
            manifest
            for manifest in self.revision_store.list_manifests()
            if manifest.recording_id == recording_id
        )
        runs = self.run_store.list_for_recording(
            recording_id,
            revision_cache=revision_cache,
            include_items=stage_key == "table_observations",
            validate_output_revisions=False,
            include_items_for_processor_types={"observation-assembly"},
        )
        diagnostics: list[dict[str, Any]] = []
        revision_by_id = {revision.revision_id: revision for revision in revisions}
        selections = {
            content_type: self._selection(
                recording_id,
                content_type,
                diagnostics,
                revision_cache=revision_cache,
                revision_manifests=revision_by_id,
            )
            for content_type in (
                "events",
                "visible_cards",
                "visual_identities",
                "table_observations",
            )
        }
        active_content_type = next(
            (
                definition.content_type
                for definition in _WORKSPACE_STAGES
                if definition.key == stage_key and definition.reviewable
            ),
            None,
        )
        references = {
            content_type: self._reference(
                recording_id,
                content_type,
                diagnostics,
                include_draft=self._should_load_reference_draft(
                    content_type,
                    stage_key=stage_key,
                    active_content_type=active_content_type,
                ),
            )
            for content_type in ("events", "visible_cards", "visual_identities")
        }
        full_revisions = (
            self.revision_store.list_for_recording(
                recording_id,
                revision_cache=revision_cache,
            )
            if stage_key in {None, "table_observations"}
            else ()
        )
        stages = [
            self._stage(
                recording_id,
                source,
                definition,
                revisions=revisions,
                runs=runs,
                selection=selections.get(definition.content_type),
                reference=references.get(definition.content_type),
                selections=selections,
                revision_by_id=revision_by_id,
                full_revisions=full_revisions,
                diagnostics=diagnostics,
            )
            for definition in _WORKSPACE_STAGES
        ]
        return {
            "schema_version": "pipeline-workspace/v1",
            "recording_id": recording_id,
            "video": source.to_mapping(),
            "stages": stages,
            "diagnostics": diagnostics,
        }

    def get_statuses(
        self,
        recording_ids: Collection[str],
        *,
        analyses_by_recording: Mapping[str, Collection[Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Return compact stage states without reading revision content or review drafts."""

        requested_ids = set(recording_ids)
        if not requested_ids:
            return {}

        revisions_by_recording: dict[str, set[str]] = {}
        for manifest in self.revision_store.list_manifests():
            if manifest.recording_id in requested_ids:
                revisions_by_recording.setdefault(manifest.recording_id, set()).add(
                    manifest.content_type
                )

        runs_by_recording: dict[str, list[tuple[str, str]]] = {}
        for run in self.run_store.list_statuses():
            if run.recording_id in requested_ids:
                runs_by_recording.setdefault(run.recording_id, []).append(
                    (run.processor_type, run.status)
                )

        references_by_recording: dict[str, dict[str, Any]] = {}
        for reference in self.reference_store.list_states():
            if reference.recording_id in requested_ids:
                references_by_recording.setdefault(reference.recording_id, {})[
                    reference.content_type
                ] = reference

        if analyses_by_recording is None:
            analyses = self.round_analysis_store.list()
            analyses_by_recording = {}
            for analysis in analyses:
                analyses_by_recording.setdefault(analysis.recording_id, []).append(analysis)

        statuses: dict[str, dict[str, Any]] = {}
        for recording_id in requested_ids:
            recording_revisions = revisions_by_recording.get(recording_id, set())
            recording_runs = runs_by_recording.get(recording_id, ())
            recording_references = references_by_recording.get(recording_id, {})
            recording_analyses = analyses_by_recording.get(recording_id, ())
            stages = [
                {
                    "key": definition.key,
                    "state": self._compact_stage_state(
                        definition,
                        has_revision=definition.content_type in recording_revisions,
                        runs=recording_runs,
                        reference=recording_references.get(definition.content_type),
                        analyses=recording_analyses,
                    ),
                }
                for definition in _WORKSPACE_STAGES
            ]
            statuses[recording_id] = {
                "schema_version": "recording-pipeline-status/v1",
                "stages": stages,
            }
        return statuses

    @staticmethod
    def _compact_stage_state(
        definition: _WorkspaceStageDefinition,
        *,
        has_revision: bool,
        runs: Collection[tuple[str, str]],
        reference: Any,
        analyses: Collection[Any],
    ) -> str:
        stage_runs = [
            status
            for processor_type, status in runs
            if processor_type == definition.processor_type
        ]
        if any(status in {"queued", "running"} for status in stage_runs):
            return "active-run"
        if definition.key == "round_analyses":
            if any(
                analysis.state in {"queued", "analyzing_evidence", "reconstructing"}
                for analysis in analyses
            ):
                return "active-run"
            if any(analysis.state == "complete" for analysis in analyses):
                return "complete"
            if any(analysis.state == "failed" for analysis in analyses):
                return "failed"
        if reference is not None:
            if reference.draft_state == "completed":
                return "complete"
            return "draft"
        if has_revision:
            return "generated-only"
        if any(status == "partial" for status in stage_runs):
            return "partial"
        if any(status == "failed" for status in stage_runs):
            return "failed"
        return "video-only" if definition.key == "events" else "empty"

    def _stage(
        self,
        recording_id: str,
        source: RecordingVideoSource,
        definition: _WorkspaceStageDefinition,
        *,
        revisions: tuple[Any, ...],
        runs: tuple[StoredProcessorRun, ...],
        selection: Any,
        reference: Any,
        selections: Mapping[str, Any],
        revision_by_id: Mapping[str, Any],
        full_revisions: tuple[Any, ...],
        diagnostics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        stage_revisions = tuple(
            revision
            for revision in revisions
            if self._manifest(revision).content_type == definition.content_type
        )
        stage_runs = tuple(
            run for run in runs if run.request.processor_type == definition.processor_type
        )
        options = [self._revision_option(revision, definition.key) for revision in stage_revisions]
        options.sort(key=lambda option: (option["created_at"], option["revision_id"]), reverse=True)
        reference_summary = (
            self._reference_summary(
                reference,
                definition.content_type,
                revision_by_id,
                diagnostics,
            )
            if definition.reviewable
            else None
        )
        analyses = (
            self._analysis_summaries(recording_id, diagnostics)
            if definition.key == "round_analyses"
            else []
        )
        compatible_input_sets = (
            self._compatible_input_sets(recording_id, source, full_revisions)
            if definition.key == "table_observations"
            else []
        )
        selection_revision = None if selection is None else selection.revision
        selected_generated = None if selection is None else selection.selected_generated_revision_id
        selected_completed = (
            None if selection is None else selection.selected_completed_reference_revision_id
        )
        comparable_run_ids = [
            run.run_id
            for run in stage_runs
            if run.state.status in {"complete", "partial"}
            and any(
                (revision := revision_by_id.get(revision_id)) is not None
                and self._manifest(revision).content_type == definition.content_type
                for revision_id in run.state.output_revision_ids
            )
        ]
        comparable_run_ids.sort()
        run_blockers = self._run_blockers(
            definition,
            source,
            stage_revisions,
            selections=selections,
            compatible_input_sets=compatible_input_sets,
        )
        review_blockers = self._review_blockers(definition, options, reference_summary)
        return {
            "key": definition.key,
            "processor_key": definition.processor_key,
            "processor_type": definition.processor_type,
            "output_content_type": definition.content_type,
            "has_maintained_reference": definition.reviewable,
            "state": self._stage_state(
                definition,
                source,
                options,
                stage_runs,
                reference_summary,
                analyses,
            ),
            "input_options": options,
            "compatible_input_sets": compatible_input_sets,
            "selection_revision": selection_revision,
            "selected_generated_revision_id": selected_generated,
            "selected_completed_reference_revision_id": selected_completed,
            "runs": [self._run_summary(run) for run in self._ordered_runs(stage_runs)],
            "analyses": analyses,
            "reference": reference_summary,
            "can_run": not run_blockers,
            "run_blockers": run_blockers,
            "can_review": not review_blockers,
            "review_blockers": review_blockers,
            "comparable_run_ids": comparable_run_ids,
        }

    def _selection(
        self,
        recording_id: str,
        content_type: str,
        diagnostics: list[dict[str, Any]],
        *,
        revision_cache: dict[str, Any] | None = None,
        revision_manifests: Mapping[str, Any] | None = None,
    ) -> Any:
        try:
            selection = self.selection_store.get(
                recording_id,
                content_type,
                revision_cache=revision_cache,
                revision_manifests=revision_manifests,
            )
        except PipelineStoreError:
            selection = None
        path = self.selection_store.selection_path(recording_id, content_type)
        if selection is None and (path.exists() or path.is_symlink()):
            diagnostics.append(
                {
                    "code": "invalid_selection",
                    "message": f"The {content_type} selection document is invalid.",
                    "content_type": content_type,
                    "revision_id": None,
                }
            )
        return selection

    def _reference(
        self,
        recording_id: str,
        content_type: str,
        diagnostics: list[dict[str, Any]],
        *,
        include_draft: bool,
    ) -> _WorkspaceReference | None:
        root = self.reference_store.reference_root(recording_id, content_type)
        if not (root / "state.json").exists() and not (root / "draft.json").exists():
            return None

        state = self.reference_store.get_state(recording_id, content_type)
        # Completed references only need state.json for workspace badges. Active drafts for
        # the requested stage still load draft.json for affected_count and coverage.
        if state is not None and (
            not include_draft or getattr(state, "draft_state", None) == "completed"
        ):
            return _WorkspaceReference(state=state, draft=None)

        reference = self.reference_store.get(recording_id, content_type)
        if reference is None:
            diagnostics.append(
                {
                    "code": "invalid_reference",
                    "message": f"The {content_type} maintained reference is invalid.",
                    "content_type": content_type,
                    "revision_id": None,
                }
            )
            return None
        return _WorkspaceReference(state=reference.state, draft=reference.draft)

    @staticmethod
    def _should_load_reference_draft(
        content_type: str,
        *,
        stage_key: str | None,
        active_content_type: str | None,
    ) -> bool:
        """Load large drafts only when the workspace needs item-level summary fields."""

        if stage_key is None:
            return True
        return active_content_type is not None and content_type == active_content_type

    def _reference_summary(
        self,
        reference: _WorkspaceReference | None,
        content_type: str,
        revision_by_id: Mapping[str, Any],
        diagnostics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if reference is None:
            return {
                "state": "empty",
                "draft_revision": None,
                "selected_completion": None,
                "source_revision_id": None,
                "coverage": None,
                "coverage_state": "none",
                "affected_count": 0,
                "updated_at": None,
            }
        selected_completion = reference.state.selected_completed_revision_id
        selected_revision = (
            None
            if selected_completion is None
            else revision_by_id.get(selected_completion)
        )
        selected_manifest = (
            None if selected_revision is None else self._manifest(selected_revision)
        )
        if selected_manifest is not None and (
            selected_manifest.recording_id != reference.state.recording_id
            or selected_manifest.content_type != content_type
        ):
            selected_manifest = None
        if selected_completion is not None and selected_manifest is None:
            diagnostics.append(
                {
                    "code": "missing_reference_revision",
                    "message": "The maintained reference completion is unavailable.",
                    "content_type": content_type,
                    "revision_id": selected_completion,
                }
            )
        state = "complete" if reference.state.draft_state == "completed" else "draft"
        if reference.draft is None:
            coverage = None if selected_manifest is None else selected_manifest.coverage
            return {
                "state": state,
                "draft_revision": reference.state.draft_revision,
                "selected_completion": selected_completion,
                "source_revision_id": reference.state.source_revision_id,
                "coverage": coverage,
                "coverage_state": "complete"
                if state == "complete"
                else "incomplete"
                if coverage is not None
                else "none",
                "affected_count": 0,
                "updated_at": reference.state.updated_at,
            }
        affected_count = sum(item.review_state == "affected" for item in reference.draft.items)
        coverage = reference.draft.coverage
        return {
            "state": state,
            "draft_revision": reference.state.draft_revision,
            "selected_completion": selected_completion,
            "source_revision_id": reference.state.source_revision_id,
            "coverage": coverage,
            "coverage_state": "complete"
            if state == "complete"
            else "incomplete"
            if coverage is not None
            else "none",
            "affected_count": affected_count,
            "updated_at": reference.state.updated_at,
        }

    @staticmethod
    def _revision_option(revision: Any, stage_key: str) -> dict[str, Any]:
        manifest = RecordingPipelineWorkspaceService._manifest(revision)
        generated = manifest.origin == "processor"
        label = "Generated" if generated else "Reviewed"
        return {
            "revision_id": manifest.revision_id,
            "content_type": manifest.content_type,
            "origin": manifest.origin,
            "completion_state": "complete",
            "coverage_state": str(manifest.coverage.get("kind", "unknown")),
            "display_label": f"{label} {stage_key.replace('_', ' ')}",
            "content_sha256": manifest.content_sha256,
            "input_revision_ids": list(manifest.input_revision_ids),
            "producer": manifest.producer.to_mapping(),
            "coverage": manifest.coverage,
            "created_at": manifest.created_at,
        }

    @staticmethod
    def _manifest(revision: Any) -> Any:
        return revision.manifest if hasattr(revision, "manifest") else revision

    @staticmethod
    def _ordered_runs(runs: tuple[StoredProcessorRun, ...]) -> tuple[StoredProcessorRun, ...]:
        return tuple(
            sorted(
                runs,
                key=lambda run: (run.state.created_at, run.run_id),
                reverse=True,
            )
        )

    @staticmethod
    def _run_summary(run: StoredProcessorRun) -> dict[str, Any]:
        state = run.state
        return {
            "run_id": run.run_id,
            "status": state.status,
            "attempt": state.attempt,
            "request": run.request.to_mapping(),
            "state": state.to_mapping(),
            "input_revision_ids": list(run.request.input_revision_ids),
            "implementation": run.request.implementation.to_mapping(),
            "model": None if run.request.model is None else run.request.model.to_mapping(),
            "configuration": run.request.configuration,
            "extraction_policy": run.request.extraction_policy,
            "crop_policy": run.request.crop_policy,
            "output_revision_ids": list(state.output_revision_ids),
            "created_at": state.created_at,
            "started_at": state.started_at,
            "completed_at": state.completed_at,
            "updated_at": state.updated_at,
            "progress": state.progress.to_mapping(),
            "failure": None
            if state.terminal_failure is None
            else state.terminal_failure.to_mapping(),
            "failed_item_count": sum(item.status == "failed" for item in state.items),
        }

    @staticmethod
    def _stage_state(
        definition: _WorkspaceStageDefinition,
        source: RecordingVideoSource,
        options: list[dict[str, Any]],
        runs: tuple[StoredProcessorRun, ...],
        reference: dict[str, Any] | None,
        analyses: list[dict[str, Any]],
    ) -> str:
        if any(run.state.status in {"queued", "running"} for run in runs):
            return "active-run"
        if any(
            analysis["state"] in {"queued", "analyzing_evidence", "reconstructing"}
            for analysis in analyses
        ):
            return "active-run"
        if any(analysis["state"] == "complete" for analysis in analyses):
            return "complete"
        if any(analysis["state"] == "failed" for analysis in analyses):
            return "failed"
        if reference is not None and reference["state"] == "complete":
            return "complete"
        if reference is not None and reference["affected_count"]:
            return "affected"
        if reference is not None and reference["coverage_state"] == "incomplete":
            return "incomplete-coverage"
        if reference is not None and reference["state"] == "draft":
            return "draft"
        if options:
            return "generated-only"
        if any(run.state.status == "partial" for run in runs):
            return "partial"
        if any(run.state.status == "failed" for run in runs):
            return "failed"
        if definition.key == "events":
            return "video-only"
        return "empty"

    @staticmethod
    def _run_blockers(
        definition: _WorkspaceStageDefinition,
        source: RecordingVideoSource,
        stage_revisions: tuple[Any, ...],
        *,
        selections: dict[str, Any],
        compatible_input_sets: list[dict[str, Any]],
    ) -> list[str]:
        if definition.key == "events":
            return []
        if definition.key in {"visible_cards", "visual_identities"}:
            upstream = "events" if definition.key == "visible_cards" else "visible_cards"
            selection = selections[upstream]
            if selection is None or not (
                selection.selected_completed_reference_revision_id
                or selection.selected_generated_revision_id
            ):
                return [f"Select a complete {upstream.replace('_', ' ')} revision first."]
            return []
        if definition.key == "table_observations":
            if not compatible_input_sets:
                return [
                    "No compatible event, visible-card, and visual-identity revision set "
                    "is available."
                ]
            missing = [
                content_type.replace("_", " ")
                for content_type in ("events", "visible_cards", "visual_identities")
                if selections[content_type] is None
                or not (
                    selections[content_type].selected_completed_reference_revision_id
                    or selections[content_type].selected_generated_revision_id
                )
            ]
            return (
                ["Select complete event, visible-card, and visual-identity revisions first."]
                if missing
                else []
            )
        if definition.key == "round_analyses":
            if not stage_revisions:
                return ["Create a complete table-observation revision first."]
            return ["Round context is required before starting analysis."]
        del source
        return ["The pipeline stage is not available."]

    def _compatible_input_sets(
        self,
        recording_id: str,
        source: RecordingVideoSource,
        revisions: tuple[Any, ...],
    ) -> list[dict[str, Any]]:
        """Return exact revision triples that pass the shared assembly checks."""

        event_revisions = tuple(
            revision
            for revision in revisions
            if revision.manifest.content_type == "events"
            and revision.manifest.recording_id == recording_id
            and revision.manifest.source == source
            and isinstance(revision.content, EventData)
        )
        visible_revisions = tuple(
            revision
            for revision in revisions
            if revision.manifest.content_type == "visible_cards"
            and revision.manifest.recording_id == recording_id
            and revision.manifest.source == source
            and isinstance(revision.content, VisibleCardData)
        )
        identity_revisions = tuple(
            revision
            for revision in revisions
            if revision.manifest.content_type == "visual_identities"
            and revision.manifest.recording_id == recording_id
            and revision.manifest.source == source
            and isinstance(revision.content, VisualIdentityData)
        )
        labels = {
            revision.manifest.revision_id: self._revision_option(
                revision, revision.manifest.content_type
            )["display_label"]
            for revision in (*event_revisions, *visible_revisions, *identity_revisions)
        }
        compatible: list[dict[str, Any]] = []
        for event_revision in event_revisions:
            for visible_revision in visible_revisions:
                for identity_revision in identity_revisions:
                    input_revision_ids = [
                        event_revision.manifest.revision_id,
                        visible_revision.manifest.revision_id,
                        identity_revision.manifest.revision_id,
                    ]
                    try:
                        assemble_table_observations(
                            event_revision.content,
                            visible_revision.content,
                            identity_revision.content,
                            recording_id=recording_id,
                            video_sha256=source.video_sha256,
                            assembly_run_id="compatibility-check",
                            input_revision_ids=input_revision_ids,
                        )
                    except (ObservationAssemblyError, TypeError, ValueError):
                        continue
                    compatible.append(
                        {
                            "input_revision_ids": input_revision_ids,
                            "display_label": " + ".join(
                                labels[revision_id] for revision_id in input_revision_ids
                            ),
                        }
                    )
        compatible.sort(key=lambda item: tuple(item["input_revision_ids"]))
        return compatible

    @staticmethod
    def _review_blockers(
        definition: _WorkspaceStageDefinition,
        options: list[dict[str, Any]],
        reference: dict[str, Any] | None,
    ) -> list[str]:
        if not definition.reviewable:
            return ["This stage does not have a maintained human reference."]
        if reference is not None and reference["state"] == "draft":
            return []
        if not options:
            return ["Create a complete generated result first."]
        if reference is not None and reference["state"] == "complete":
            return ["Start a new review from the selected generated result to review again."]
        return []

    def _analysis_summaries(
        self, recording_id: str, diagnostics: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        analyses = self.round_analysis_store.list_by_recording(recording_id)
        for analysis in analyses:
            try:
                request = parse_round_analysis_create_request_bytes(
                    analysis.request_json.encode("utf-8")
                )
            except (TypeError, ValueError):
                diagnostics.append(
                    {
                        "code": "invalid_round_analysis_request",
                        "message": "A stored round-analysis request is invalid.",
                        "content_type": "round_analyses",
                        "revision_id": str(analysis.analysis_id),
                    }
                )
                LOGGER.warning("pipeline_workspace_analysis_invalid", exc_info=True)
                continue
            input_revision_ids = (
                []
                if request.table_observation_revision_id is None
                else [request.table_observation_revision_id]
            )
            summaries.append(
                {
                    "analysis_id": str(analysis.analysis_id),
                    "recording_id": analysis.recording_id,
                    "round_id": analysis.round_id,
                    "session_id": str(analysis.session_id),
                    "state": analysis.state,
                    "input_revision_ids": input_revision_ids,
                    "request": request.to_mapping(),
                    "progress": {
                        "completed": analysis.completed_evidence_packages,
                        "total": analysis.total_evidence_packages,
                    },
                    "failure": analysis.error,
                    "created_at": _datetime_string(analysis.created_at),
                    "started_at": _datetime_string(analysis.started_at),
                    "completed_at": _datetime_string(analysis.completed_at),
                }
            )
        return summaries


def _datetime_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(_UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = ["RecordingPipelineWorkspaceService"]
