"""Write processor and analysis records to the shared pipeline lineage graph."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from doko_operations.pipeline_data import ProcessorRunRequest

from dokodetector_backend.pipeline_lineage import PipelineLineage
from dokodetector_backend.pipeline_node_store import NodeConflict, PipelineNodeStore, _read_json
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses
from dokodetector_backend.pipeline_store import ProcessorRunState, StoredPipelineRevision

_ROLES = {
    "event-detection": "events",
    "visible-card-detection": "events",
    "visible-card-scene-proposal": "visible_cards",
    "visual-card-identity": "virtual_scenes",
    "observation-assembly": "events",
}


def _input_role(request: ProcessorRunRequest, index: int, revision: StoredPipelineRevision) -> str:
    if request.processor_type == "observation-assembly":
        return ("events", "visible_cards", "visual_identities")[index]
    if request.processor_type == "visual-card-identity":
        return (
            "virtual_scenes"
            if revision.manifest.content_type == "card_scene_proposals"
            else revision.manifest.content_type
        )
    return _ROLES.get(request.processor_type, revision.manifest.content_type)


class PipelineLineageWriter:
    """Adapt retained processor revisions and analysis artifacts to lineage nodes."""

    def __init__(
        self,
        node_store: PipelineNodeStore,
        lineage: PipelineLineage,
        uses: PipelineNodeUses,
        revision_store: Any,
    ) -> None:
        self.node_store = node_store
        self.lineage = lineage
        self.uses = uses
        self.revision_store = revision_store
        migration_map_path = node_store.root / ".legacy-revision-map.json"
        migration_map = _read_json(migration_map_path) if migration_map_path.exists() else None
        if migration_map is not None and (
            migration_map.get("schema_version") != "legacy-revision-map/v1"
            or not isinstance(migration_map.get("revisions"), dict)
        ):
            raise ValueError("invalid legacy revision map")
        self.migrated_revisions = {} if migration_map is None else migration_map["revisions"]

    @staticmethod
    def _run_id(run_id: str, attempt: int) -> str:
        return run_id if attempt == 1 else f"{run_id}-attempt-{attempt}"

    @staticmethod
    def _node_id(revision_id: str) -> str:
        return "data-" + hashlib.sha256(revision_id.encode("utf-8")).hexdigest()[:32]

    def _ensure_revision_node(self, revision: StoredPipelineRevision) -> tuple[str, str]:
        manifest = revision.manifest
        migrated = self.migrated_revisions.get(manifest.revision_id)
        if migrated is not None:
            if not isinstance(migrated, dict) or set(migrated) != {"node_id", "revision_id"}:
                raise ValueError("invalid migrated revision entry")
            self.node_store.get(migrated["node_id"])
            return migrated["node_id"], migrated["revision_id"]
        node_id = self._node_id(manifest.revision_id)
        try:
            node = self.node_store.get(node_id)
        except FileNotFoundError:
            node = None
        if node is None:
            try:
                self.node_store.create(
                    node_id,
                    f"{manifest.content_type.replace('_', ' ').title()} {manifest.revision_id[:8]}",
                    manifest.content_type,
                    manifest.source.to_mapping(),
                    revision.content.to_mapping(),
                    {
                        "origin": manifest.origin,
                        "legacy_revision_id": manifest.revision_id,
                    },
                    revision_id=manifest.revision_id,
                )
            except NodeConflict:
                node = self.node_store.get(node_id)
            else:
                return node_id, manifest.revision_id
        stored = self.node_store.read_revision(node_id, manifest.revision_id)
        if (
            node.content_type != manifest.content_type
            or node.source != manifest.source.to_mapping()
            or stored.content != revision.content.to_mapping()
        ):
            raise NodeConflict("lineage node differs from the retained processor revision")
        return node_id, manifest.revision_id

    def accept_processor(self, request: ProcessorRunRequest, state: ProcessorRunState) -> None:
        """Freeze exact inputs before the processor worker starts."""
        run_id = self._run_id(request.run_id, state.attempt)
        inputs: list[dict[str, str]] = []
        revision_pairs = []
        for index, revision_id in enumerate(request.input_revision_ids):
            revision = self.revision_store.require(revision_id)
            node_id, node_revision_id = self._ensure_revision_node(revision)
            revision_pairs.append((node_id, node_revision_id))
            inputs.append(
                {
                    "kind": "revision",
                    "node_id": node_id,
                    "revision_id": node_revision_id,
                    "role": _input_role(request, index, revision),
                }
            )
        if not inputs:
            source = request.source
            inputs.append(
                {
                    "kind": "artifact",
                    "artifact_id": f"recording-video/{source.recording_id}",
                    "sha256": source.video_sha256,
                    "role": "recording_video",
                }
            )
        self.uses.accept(run_id, revision_pairs)
        self.lineage.start(
            run_id,
            inputs=inputs,
            run_kind="processor",
            processor={
                "implementation": {"name": request.processor_type, "version": "1"},
                "model": None,
                "configuration": request.configuration,
                "policies": {},
            },
            context={
                "recording_id": request.source.recording_id,
                "request": request.to_mapping(),
                "attempt": state.attempt,
            },
        )

    def update_processor(self, request: ProcessorRunRequest, state: ProcessorRunState) -> None:
        """Publish exact output nodes and the immutable terminal run record."""
        if state.status not in {"complete", "partial", "failed"}:
            return
        run_id = self._run_id(request.run_id, state.attempt)
        inputs = self._input_refs(request)
        outputs = []
        for revision_id in state.output_revision_ids:
            revision = self.revision_store.require(revision_id)
            node_id, node_revision_id = self._ensure_revision_node(revision)
            outputs.append(
                {
                    "kind": "revision",
                    "node_id": node_id,
                    "revision_id": node_revision_id,
                    "role": revision.manifest.content_type,
                }
            )
        status = "succeeded" if state.status == "complete" else state.status
        result = None
        failure = None
        if status in {"succeeded", "partial"}:
            if state.output_revision_ids:
                result = (
                    "empty"
                    if all(
                        self._is_empty(self.revision_store.require(x))
                        for x in state.output_revision_ids
                    )
                    else "nonempty"
                )
        else:
            failure = (
                {"code": "processor_failed"}
                if state.terminal_failure is None
                else state.terminal_failure.to_mapping()
            )
        self.lineage.finish(
            run_id,
            inputs=inputs,
            outputs=outputs,
            status=status,
            run_kind="processor",
            result=result,
            processor={
                "implementation": {"name": request.processor_type, "version": "1"},
                "model": None,
                "configuration": request.configuration,
                "policies": {},
            },
            context={
                "recording_id": request.source.recording_id,
                "request": request.to_mapping(),
                "attempt": state.attempt,
            },
            failure=failure,
        )

    def _input_refs(self, request: ProcessorRunRequest) -> list[dict[str, str]]:
        refs = []
        for index, revision_id in enumerate(request.input_revision_ids):
            revision = self.revision_store.require(revision_id)
            node_id, node_revision_id = self._ensure_revision_node(revision)
            refs.append(
                {
                    "kind": "revision",
                    "node_id": node_id,
                    "revision_id": node_revision_id,
                    "role": _input_role(request, index, revision),
                }
            )
        if not refs:
            source = request.source
            refs.append(
                {
                    "kind": "artifact",
                    "artifact_id": f"recording-video/{source.recording_id}",
                    "sha256": source.video_sha256,
                    "role": "recording_video",
                }
            )
        return refs

    @staticmethod
    def _is_empty(revision: StoredPipelineRevision) -> bool:
        value = revision.content.to_mapping()
        for key in ("events", "outcomes", "frames", "observations", "identities"):
            if key in value:
                return not value[key]
        return False

    def accept_analysis(
        self,
        analysis_id: str,
        *,
        recording_id: str,
        revision_id: str | None,
        package_inputs: Sequence[tuple[str, str]],
        round_context: Mapping[str, Any],
        rules: Mapping[str, Any],
        search_settings: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        """Register exact observation and package inputs before analysis execution."""
        inputs: list[dict[str, str]] = []
        pairs = []
        if revision_id is not None:
            revision = self.revision_store.require(revision_id)
            node_id, node_revision_id = self._ensure_revision_node(revision)
            pairs.append((node_id, node_revision_id))
            inputs.append(
                {
                    "kind": "revision",
                    "node_id": node_id,
                    "revision_id": node_revision_id,
                    "role": "table_observations",
                }
            )
        inputs.extend(
            {
                "kind": "artifact",
                "artifact_id": f"evidence-package/{package_id}",
                "sha256": digest,
                "role": "evidence_package",
            }
            for package_id, digest in package_inputs
        )
        run_id = f"analysis-{analysis_id}"
        self.uses.accept(run_id, pairs)
        self.lineage.start(
            run_id,
            inputs=inputs,
            run_kind="analysis",
            processor={
                "implementation": {"name": "round-analysis", "version": "1"},
                "model": None,
                "configuration": {},
                "policies": {},
            },
            context={
                "round_context": dict(round_context),
                "rules": dict(rules),
                "search_settings": dict(search_settings),
                "recording_id": recording_id,
            },
        )
        return inputs

    def finish_analysis(
        self,
        analysis_id: str,
        *,
        status: str,
        inputs: Sequence[Mapping[str, str]],
        recording_id: str,
        round_context: Mapping[str, Any],
        rules: Mapping[str, Any],
        search_settings: Mapping[str, Any],
        outputs: Sequence[Mapping[str, str]] = (),
        failure: Mapping[str, Any] | None = None,
    ) -> None:
        """Publish an analysis attempt with its retained input and result artifacts."""
        run_id = f"analysis-{analysis_id}"
        context = {
            "round_context": dict(round_context),
            "rules": dict(rules),
            "search_settings": dict(search_settings),
            "recording_id": recording_id,
        }
        self.lineage.finish(
            run_id,
            inputs=inputs,
            outputs=outputs,
            status="succeeded" if status == "complete" else status,
            run_kind="analysis",
            result="nonempty" if status == "complete" else None,
            processor={
                "implementation": {"name": "round-analysis", "version": "1"},
                "model": None,
                "configuration": {},
                "policies": {},
            },
            context=context,
            failure=failure,
        )
