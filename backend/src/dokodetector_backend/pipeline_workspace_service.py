"""Read-only recording workspace composition for pipeline state."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from doko_operations.pipeline_data import (
    DATA_REVISION_SCHEMA_VERSION,
    DataRevision,
    EventData,
    RecordingVideoSource,
    canonical_json_bytes,
    parse_event_data_bytes,
    parse_source,
)
from table_evidence_analyzer import ObservationAssemblyError, assemble_table_observations
from table_evidence_analyzer.pipeline_data import (
    VisibleCardData,
    VisualIdentityData,
    parse_table_observation_data_bytes,
    parse_visible_card_data_bytes,
    parse_visual_identity_data_bytes,
)

from dokodetector_backend.filesystem import enumerate_resource_directories
from dokodetector_backend.pipeline_node_selection_store import PipelineNodeSelectionStore
from dokodetector_backend.pipeline_node_store import PipelineNodeStore, _read_json
from dokodetector_backend.processor_run_models import ProcessorRunStatus, StoredProcessorRun
from dokodetector_backend.processor_run_store import ProcessorRunStore
from dokodetector_backend.round_analysis_contract import parse_round_analysis_create_request_bytes

LOGGER = logging.getLogger(__name__)
_UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class _WorkspaceStageDefinition:
    key: str
    processor_key: str
    processor_type: str
    content_type: str


_WORKSPACE_STAGES = (
    _WorkspaceStageDefinition(
        key="events",
        processor_key="event_detection",
        processor_type="event-detection",
        content_type="events",
    ),
    _WorkspaceStageDefinition(
        key="visible_cards",
        processor_key="visible_card_detection",
        processor_type="visible-card-detection",
        content_type="visible_cards",
    ),
    _WorkspaceStageDefinition(
        key="visual_identities",
        processor_key="visual_identity_classification",
        processor_type="visual-card-identity",
        content_type="visual_identities",
    ),
    _WorkspaceStageDefinition(
        key="table_observations",
        processor_key="observation_assembly",
        processor_type="observation-assembly",
        content_type="table_observations",
    ),
    _WorkspaceStageDefinition(
        key="round_analyses",
        processor_key="round_analysis",
        processor_type="round-analysis",
        content_type="round_analyses",
    ),
)


@dataclass(frozen=True, slots=True)
class _WorkspaceNodeRevision:
    """Node revision fields used by the established workspace projection."""

    manifest: DataRevision
    content: Any | None
    node_id: str
    node_revision_id: str
    migrated_draft: bool = False


class RecordingPipelineWorkspaceService:
    """Aggregate persisted recording-pipeline state for the recording workspace."""

    def __init__(
        self,
        *,
        recording_source_provider: Callable[[str], RecordingVideoSource],
        run_store: ProcessorRunStore,
        selection_store: PipelineNodeSelectionStore,
        round_analysis_store: Any,
        node_store: PipelineNodeStore,
        lineage_service: Any,
    ) -> None:
        self.recording_source_provider = recording_source_provider
        self.run_store = run_store
        self.selection_store = selection_store
        self.round_analysis_store = round_analysis_store
        self.node_store = node_store
        self.lineage_service = lineage_service

    def get_workspace(
        self,
        recording_id: str,
        *,
        stage_key: str | None = None,
    ) -> dict[str, Any]:
        """Read one complete workspace snapshot without changing pipeline state."""

        source = self.recording_source_provider(recording_id)
        revision_cache: dict[str, Any] = {}
        include_revision_content = stage_key in {None, "table_observations"}
        revisions = self._node_revisions_for_recording(
            recording_id, include_content=include_revision_content
        )
        runs = self.run_store.list_for_recording(
            recording_id,
            revision_cache=revision_cache,
            include_items=stage_key == "table_observations",
            validate_output_revisions=False,
            include_items_for_processor_types={"observation-assembly"},
        )
        lineage_runs_by_output = self._lineage_runs_by_output(revisions)
        diagnostics: list[dict[str, Any]] = []
        revision_by_id = {self._manifest(revision).revision_id: revision for revision in revisions}
        revision_targets = {
            self._manifest(revision).revision_id: (revision.node_id, revision.node_revision_id)
            for revision in revisions
        }
        selections = {
            content_type: self._selection(
                recording_id,
                content_type,
                diagnostics,
            )
            for content_type in (
                "events",
                "visible_cards",
                "visual_identities",
                "table_observations",
            )
        }
        full_revisions = revisions if include_revision_content else ()
        stages = [
            self._stage(
                recording_id,
                source,
                definition,
                revisions=revisions,
                runs=runs,
                selection=selections.get(definition.content_type),
                selections=selections,
                revision_by_id=revision_by_id,
                full_revisions=full_revisions,
                lineage_runs_by_output=lineage_runs_by_output,
                revision_targets=revision_targets,
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
        for revision in self._node_revisions_for_recordings(requested_ids):
            manifest = self._manifest(revision)
            if manifest.recording_id in requested_ids:
                revisions_by_recording.setdefault(manifest.recording_id, set()).add(
                    manifest.content_type
                )

        runs_by_recording: dict[str, list[tuple[str, str]]] = {}
        for run in self._list_statuses_for_recordings(requested_ids):
            runs_by_recording.setdefault(run.recording_id, []).append(
                (run.processor_type, run.status)
            )

        if analyses_by_recording is None:
            analyses = self.round_analysis_store.list()
            analyses_by_recording = {}
            for analysis in analyses:
                analyses_by_recording.setdefault(analysis.recording_id, []).append(analysis)

        statuses: dict[str, dict[str, Any]] = {}
        for recording_id in requested_ids:
            recording_revisions = revisions_by_recording.get(recording_id, set())
            recording_runs = runs_by_recording.get(recording_id, ())
            recording_analyses = analyses_by_recording.get(recording_id, ())
            stages = [
                {
                    "key": definition.key,
                    "state": self._compact_stage_state(
                        definition,
                        has_revision=definition.content_type in recording_revisions,
                        runs=recording_runs,
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

    def _node_revisions_for_recordings(
        self, recording_ids: Collection[str], *, include_content: bool = False
    ) -> tuple[Any, ...]:
        """Build workspace revision records from immutable node revisions."""
        requested = set(recording_ids)
        revisions = []
        parsers = {
            "events": parse_event_data_bytes,
            "visible_cards": parse_visible_card_data_bytes,
            "visual_identities": parse_visual_identity_data_bytes,
            "table_observations": parse_table_observation_data_bytes,
        }
        nodes = [
            node
            for node in self.node_store.list_nodes()
            if node.source.get("recording_id") in requested
        ]
        target_node_ids = {node.node_id for node in nodes}
        graph_inputs: dict[tuple[str, str], list[str]] = {}
        role_order = {"events": 0, "visible_cards": 1, "visual_identities": 2}
        lineage_root = self.lineage_service.root
        run_paths = sorted(lineage_root.glob("*.json")) if lineage_root.is_dir() else []
        for path in run_paths:
            run = _read_json(path)
            inputs = [ref for ref in run.get("inputs", []) if ref.get("kind") == "revision"]
            inputs.sort(key=lambda ref: (role_order.get(ref["role"], 10), ref["role"]))
            input_ids = [ref["revision_id"] for ref in inputs]
            for output in run.get("outputs", []):
                if output.get("kind") == "revision" and output.get("node_id") in target_node_ids:
                    graph_inputs[(output["node_id"], output["revision_id"])] = input_ids
        for node in nodes:
            source = parse_source(node.source)
            recording_id = getattr(source, "recording_id", None)
            if recording_id not in requested:
                continue
            parser = parsers.get(node.content_type)
            if parser is None:
                continue
            history = self.node_store.history(node.node_id)
            inherited: dict[str, Any] = {}
            for revision in reversed(history):
                inherited.update(revision.metadata)
            for node_revision in history:
                metadata = {**inherited, **node_revision.metadata}
                revision_id = node_revision.revision_id
                raw_manifest = node_revision.metadata.get("data_revision")
                if isinstance(raw_manifest, Mapping):
                    manifest = DataRevision.from_mapping(raw_manifest)
                else:
                    content_schema = node_revision.content.get("schema_version")
                    if not isinstance(content_schema, str):
                        content_schema = {
                            "events": "event-data/v1",
                            "visible_cards": "visible-card-data/v2",
                            "visual_identities": "visual-identity-data/v2",
                            "table_observations": "table-observation-data/v1",
                        }[node.content_type]
                    manifest = DataRevision.from_mapping(
                        {
                            "schema_version": DATA_REVISION_SCHEMA_VERSION,
                            "revision_id": revision_id,
                            "content_type": node.content_type,
                            "content_schema": content_schema,
                            "recording_id": recording_id,
                            "source": node.source,
                            "content_sha256": node_revision.content_sha256,
                            "input_revision_ids": metadata.get(
                                "input_revision_ids",
                                graph_inputs.get((node.node_id, node_revision.revision_id), []),
                            ),
                            "origin": metadata.get("origin", "processor"),
                            "producer": metadata.get(
                                "producer",
                                {
                                    "kind": "processor",
                                    "run_id": revision_id,
                                    "processor_type": metadata.get(
                                        "processor_type", "pipeline-import"
                                    ),
                                    "implementation_id": metadata.get(
                                        "implementation_id", "doko_detector.node_store"
                                    ),
                                },
                            ),
                            "coverage": metadata.get("coverage", {"kind": "unknown"}),
                            "created_at": metadata.get("created_at", node_revision.created_at),
                        }
                    )
                content = (
                    parser(canonical_json_bytes(node_revision.content)) if include_content else None
                )
                revisions.append(
                    _WorkspaceNodeRevision(
                        manifest=manifest,
                        content=content,
                        node_id=node.node_id,
                        node_revision_id=node_revision.revision_id,
                        migrated_draft=(
                            isinstance(metadata.get("migration"), dict)
                            and isinstance(metadata["migration"].get("legacy_key"), str)
                        ),
                    )
                )
        return tuple(revisions)

    def _node_revisions_for_recording(
        self, recording_id: str, *, include_content: bool = False
    ) -> tuple[Any, ...]:
        return self._node_revisions_for_recordings((recording_id,), include_content=include_content)

    def _lineage_runs_by_output(
        self, revisions: tuple[_WorkspaceNodeRevision, ...]
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Index terminal lineage records by their exact node output."""
        node_ids = {revision.node_id for revision in revisions}
        if not node_ids:
            return {}
        result = {}
        root = self.lineage_service.root
        paths = sorted(root.glob("*.json")) if root.is_dir() else []
        for path in paths:
            record = _read_json(path)
            for output in record.get("outputs", []):
                if output.get("kind") != "revision" or output.get("node_id") not in node_ids:
                    continue
                key = (output["node_id"], output["revision_id"])
                previous = result.setdefault(key, record)
                if previous["run_id"] != record["run_id"]:
                    raise ValueError("a graph revision has multiple producer runs")
        return result

    def _list_statuses_for_recordings(self, recording_ids: Collection[str]) -> tuple[Any, ...]:
        """Read run status only for the requested recordings."""

        if not recording_ids:
            return ()

        enumeration = enumerate_resource_directories(self.run_store.root)
        for diagnostic in enumeration.diagnostics:
            self.run_store._log_invalid(diagnostic.path, ValueError(diagnostic.reason))

        requested = set(recording_ids)
        statuses = []
        for path in enumeration.paths:
            try:
                # Run requests can contain large image and crop payloads. JSON
                # decoding validates the document syntax without running the
                # full nested contract validators used by workspace detail APIs.
                request = json.loads((path / "request.json").read_bytes())
                if not isinstance(request, dict):
                    raise ValueError("processor run request must be an object")
                run_id = request.get("run_id")
                processor_type = request.get("processor_type")
                source = request.get("source")
                if (
                    not isinstance(run_id, str)
                    or run_id != path.name
                    or not isinstance(processor_type, str)
                    or not isinstance(source, dict)
                ):
                    raise ValueError("processor run request has invalid status fields")
                recording_id = source.get("recording_id")
                if not isinstance(recording_id, str) or recording_id not in requested:
                    continue
                state = json.loads((path / "state.json").read_bytes())
                if (
                    not isinstance(state, dict)
                    or state.get("run_id") != run_id
                    or not isinstance(state.get("status"), str)
                ):
                    raise ValueError("processor run state has invalid status fields")
                statuses.append(
                    ProcessorRunStatus(
                        run_id=run_id,
                        recording_id=recording_id,
                        processor_type=processor_type,
                        status=state["status"],
                    )
                )
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                self.run_store._log_invalid(path, error)
        return tuple(sorted(statuses, key=lambda item: item.run_id))

    @staticmethod
    def _compact_stage_state(
        definition: _WorkspaceStageDefinition,
        *,
        has_revision: bool,
        runs: Collection[tuple[str, str]],
        analyses: Collection[Any],
    ) -> str:
        stage_runs = [
            status for processor_type, status in runs if processor_type == definition.processor_type
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
        if has_revision:
            return "data-available"
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
        selections: Mapping[str, Any],
        revision_by_id: Mapping[str, Any],
        full_revisions: tuple[Any, ...],
        lineage_runs_by_output: Mapping[tuple[str, str], dict[str, Any]],
        revision_targets: Mapping[str, tuple[str, str]],
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
        options = []
        for revision in stage_revisions:
            option = self._revision_option(revision, definition.key)
            option["node_id"] = revision.node_id
            option["node_revision_id"] = revision.node_revision_id
            option["is_current_head"] = (
                self.node_store.get(revision.node_id).head_revision_id == revision.node_revision_id
            )
            options.append(option)
        options.sort(
            key=lambda option: (option["created_at"], option["node_revision_id"]),
            reverse=True,
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
        selected_generated = None if selection is None else selection.selected_generated
        selected_completed = None if selection is None else selection.selected_completed_reference
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
        return {
            "key": definition.key,
            "processor_key": definition.processor_key,
            "processor_type": definition.processor_type,
            "output_content_type": definition.content_type,
            "state": self._stage_state(
                definition,
                source,
                options,
                stage_runs,
                analyses,
            ),
            "input_options": options,
            "compatible_input_sets": compatible_input_sets,
            "selection_revision": selection_revision,
            "selected_generated": selected_generated,
            "selected_completed_reference": selected_completed,
            "runs": [
                self._run_summary(
                    run,
                    next(
                        (
                            lineage_runs_by_output[target]
                            for revision_id in run.state.output_revision_ids
                            if (target := revision_targets.get(revision_id))
                            in lineage_runs_by_output
                        ),
                        None,
                    ),
                )
                for run in self._ordered_runs(stage_runs)
            ],
            "analyses": analyses,
            "can_run": not run_blockers,
            "run_blockers": run_blockers,
            "comparable_run_ids": comparable_run_ids,
        }

    def _selection(
        self,
        recording_id: str,
        content_type: str,
        diagnostics: list[dict[str, Any]],
    ) -> Any:
        try:
            selection = self.selection_store.get_exact(recording_id, content_type)
        except (OSError, TypeError, ValueError):
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

    @staticmethod
    def _revision_option(revision: Any, stage_key: str) -> dict[str, Any]:
        manifest = RecordingPipelineWorkspaceService._manifest(revision)
        generated = manifest.origin == "processor"
        label = "Processor output" if generated else "Edited"
        if getattr(revision, "migrated_draft", False):
            label = "Imported draft"
        return {
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
    def _run_summary(
        run: StoredProcessorRun,
        lineage_run: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = run.state
        request = run.request.to_mapping()
        crop_input = request.get("crop_input")
        if isinstance(crop_input, dict):
            crop_input = dict(crop_input)
            items = crop_input.pop("items", None)
            if isinstance(items, list):
                crop_input["item_count"] = len(items)
            request["crop_input"] = crop_input
        input_revision_ids = list(run.request.input_revision_ids)
        output_revision_ids = list(state.output_revision_ids)
        if lineage_run is not None:
            role_order = {"events": 0, "visible_cards": 1, "visual_identities": 2}
            inputs = [ref for ref in lineage_run.get("inputs", []) if ref.get("kind") == "revision"]
            inputs.sort(key=lambda ref: (role_order.get(ref["role"], 10), ref["role"]))
            input_revision_ids = [ref["revision_id"] for ref in inputs]
            output_revision_ids = [
                ref["revision_id"]
                for ref in lineage_run.get("outputs", [])
                if ref.get("kind") == "revision"
            ]
            request["input_revision_ids"] = input_revision_ids
        return {
            "run_id": run.run_id,
            "status": state.status,
            "attempt": state.attempt,
            # Crop input items can make an immutable request hundreds of kilobytes.
            # Workspace history only needs their count; the run detail endpoint keeps
            # the complete request available when a caller needs its full lineage.
            "request": request,
            "state": state.to_mapping(),
            "input_revision_ids": input_revision_ids,
            "implementation": run.request.implementation.to_mapping(),
            "model": None if run.request.model is None else run.request.model.to_mapping(),
            "configuration": run.request.configuration,
            "extraction_policy": run.request.extraction_policy,
            "crop_policy": run.request.crop_policy,
            "output_revision_ids": output_revision_ids,
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
        if options:
            return "data-available"
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
                selection.selected_completed_reference or selection.selected_generated
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
                    selections[content_type].selected_completed_reference
                    or selections[content_type].selected_generated
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
                    input_node_refs = [
                        {
                            "node_id": revision.node_id,
                            "revision_id": revision.node_revision_id,
                            "revision_policy": "historical",
                        }
                        for revision in (
                            event_revision,
                            visible_revision,
                            identity_revision,
                        )
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
                            "input_node_refs": input_node_refs,
                            "display_label": " + ".join(
                                labels[revision_id] for revision_id in input_revision_ids
                            ),
                        }
                    )
        compatible.sort(
            key=lambda item: tuple(
                (ref["node_id"], ref["revision_id"]) for ref in item["input_node_refs"]
            )
        )
        return compatible

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
                if request.table_observation_node_ref is None
                else [request.table_observation_node_ref["revision_id"]]
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
