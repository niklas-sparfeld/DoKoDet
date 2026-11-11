"""Write processor and analysis records to the shared pipeline lineage graph."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from doko_operations.pipeline_data import (
    DataRevision,
    ProcessorRunRequest,
    ProcessorRunState,
    canonical_json_bytes,
)

from dokodetector_backend.event_set_store import EventSetStore
from dokodetector_backend.pipeline_lineage import PipelineLineage
from dokodetector_backend.pipeline_node_store import NodeConflict, PipelineNodeStore
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses
from dokodetector_backend.pipeline_revision_store import (
    PipelineRevisionStore,
    StoredPipelineRevision,
)
from dokodetector_backend.pipeline_storage import PipelineNotFound


class PipelineLineageWriter:
    """Publish processor data revisions as canonical node revisions."""

    def __init__(
        self,
        node_store: PipelineNodeStore,
        lineage: PipelineLineage,
        uses: PipelineNodeUses,
        event_set_store: EventSetStore | None = None,
    ) -> None:
        self.node_store = node_store
        self.lineage = lineage
        self.uses = uses
        self.event_set_store = event_set_store

    @staticmethod
    def _run_id(run_id: str, attempt: int) -> str:
        return run_id if attempt == 1 else f"{run_id}-attempt-{attempt}"

    @staticmethod
    def _node_id(revision_id: str) -> str:
        return "data-" + hashlib.sha256(revision_id.encode("utf-8")).hexdigest()[:32]

    def publish_processor_revision(
        self, manifest: DataRevision, content: Any
    ) -> tuple[StoredPipelineRevision, bool]:
        """Validate and publish one processor output directly to its canonical node."""
        PipelineRevisionStore._validate_content(manifest, content)
        node_id = self._node_id(manifest.revision_id)
        metadata = {
            "origin": manifest.origin,
            "input_revision_ids": list(manifest.input_revision_ids),
            "producer": manifest.producer.to_mapping(),
            "coverage": manifest.coverage,
            "data_revision": manifest.to_mapping(),
        }
        try:
            self.node_store.create(
                node_id,
                f"{manifest.content_type.replace('_', ' ').title()} {manifest.revision_id[:8]}",
                manifest.content_type,
                manifest.source.to_mapping(),
                content.to_mapping(),
                metadata,
                revision_id=manifest.revision_id,
            )
            return StoredPipelineRevision(manifest, content), True
        except NodeConflict:
            node = self.node_store.get(node_id)
            revision = self.node_store.read_revision(node_id, manifest.revision_id)
            existing = self._stored_node_revision(node, revision)
            if (
                existing.manifest.to_mapping() != manifest.to_mapping()
                or existing.content.to_mapping() != content.to_mapping()
            ):
                raise NodeConflict(
                    "processor output revision ID has different node content"
                ) from None
            return existing, False

    def require_revision(self, revision_id: str) -> StoredPipelineRevision:
        """Read one canonical output revision by its globally unique revision ID."""
        node_id = self._node_id(revision_id)
        return self.read_node_revision(node_id, revision_id)

    def read_node_revision(self, node_id: str, revision_id: str) -> StoredPipelineRevision:
        """Read one exact node revision as the processor data contract value."""
        try:
            node = self.node_store.get(node_id)
            revision = self.node_store.read_revision(node_id, revision_id)
        except (FileNotFoundError, KeyError, ValueError) as error:
            raise PipelineNotFound(f"The pipeline revision was not found: {revision_id}") from error
        return self._stored_node_revision(node, revision)

    def node_ref_for_processor_output(
        self, revision_id: str, recording_id: str, content_type: str
    ) -> dict[str, str]:
        stored = self.require_revision(revision_id)
        if (
            stored.manifest.recording_id != recording_id
            or stored.manifest.content_type != content_type
        ):
            raise ValueError("processor output does not match its recording or content type")
        return {"node_id": self._node_id(revision_id), "revision_id": revision_id}

    @staticmethod
    def _stored_node_revision(node: Any, revision: Any) -> StoredPipelineRevision:
        raw_manifest = revision.metadata.get("data_revision")
        if not isinstance(raw_manifest, Mapping):
            revision_id = revision.revision_id
            content_schema = revision.content.get("schema_version")
            if not isinstance(content_schema, str):
                content_schema = {
                    "events": "event-data/v1",
                    "visible_cards": "visible-card-data/v2",
                    "visual_identities": "visual-identity-data/v2",
                    "table_observations": "table-observation-data/v1",
                    "card_scene_proposals": "proposed-card-scene-data/v2",
                }[node.content_type]
            raw_manifest = {
                "schema_version": "data-revision/v1",
                "revision_id": revision_id,
                "content_type": node.content_type,
                "content_schema": content_schema,
                "recording_id": node.source.get("recording_id"),
                "source": node.source,
                "content_sha256": revision.content_sha256,
                "input_revision_ids": revision.metadata.get("input_revision_ids", []),
                "origin": revision.metadata.get("origin", "processor"),
                "producer": revision.metadata.get(
                    "producer",
                    {
                        "kind": "processor",
                        "run_id": revision_id,
                        "processor_type": "pipeline-import",
                        "implementation_id": "doko_detector.node_store",
                    },
                ),
                "coverage": revision.metadata.get("coverage", {"kind": "unknown"}),
                "created_at": revision.metadata.get("created_at", revision.created_at),
            }
        manifest = DataRevision.from_mapping(raw_manifest)
        content = PipelineRevisionStore._parse_content_bytes_for_manifest(
            manifest, canonical_json_bytes(revision.content)
        )
        PipelineRevisionStore._validate_content(manifest, content)
        return StoredPipelineRevision(manifest, content)

    def accept_processor(self, request: ProcessorRunRequest, state: ProcessorRunState) -> None:
        """Freeze exact inputs before the processor worker starts."""
        run_id = self._run_id(request.run_id, state.attempt)
        inputs: list[dict[str, str]] = []
        revision_pairs = []
        node_refs = request.input_node_refs or (
            (request.input_node_ref,) if request.input_node_ref is not None else ()
        )
        if request.input_event_set_ref is not None:
            inputs.append(
                {
                    "kind": "artifact",
                    "artifact_id": (
                        f"event-set/{request.input_event_set_ref['set_id']}"
                        f"/versions/{request.input_event_set_ref['version']}"
                    ),
                    "sha256": request.input_event_set_ref["content_sha256"],
                    "role": "events",
                }
            )
        if request.input_detection_set_ref is not None:
            inputs.append(
                {
                    "kind": "artifact",
                    "artifact_id": (
                        f"detection-set/{request.input_detection_set_ref['set_id']}"
                        f"/versions/{request.input_detection_set_ref['version']}"
                    ),
                    "sha256": request.input_detection_set_ref["content_sha256"],
                    "role": "detections",
                }
            )
        if node_refs:
            roles = {
                "observation-assembly": (
                    ("visual_identities",)
                    if request.input_detection_set_ref is not None
                    else ("visible_cards", "visual_identities")
                    if request.input_event_set_ref is not None
                    else ("events", "visible_cards", "visual_identities")
                ),
                "visual-card-identity": ("visible_cards",),
                "visible-card-scene-proposal": ("visible_cards",),
                "visible-card-detection": ("events",),
            }.get(request.processor_type, ())
            for index, ref in enumerate(node_refs):
                node = self.node_store.get(ref["node_id"])
                self.node_store.read_revision(ref["node_id"], ref["revision_id"])
                revision_pairs.append((ref["node_id"], ref["revision_id"]))
                role = roles[index] if index < len(roles) else "input"
                if request.processor_type == "visual-card-identity":
                    role = (
                        "virtual_scenes"
                        if node.content_type == "card_scene_proposals"
                        else "visible_cards"
                    )
                inputs.append(
                    {
                        "kind": "revision",
                        "node_id": ref["node_id"],
                        "revision_id": ref["revision_id"],
                        "role": role,
                    }
                )
        elif request.input_event_set_ref is None and request.input_detection_set_ref is None:
            for index, revision_id in enumerate(request.input_revision_ids):
                raise ValueError(
                    "processor execution requires exact node input references; "
                    f"received revision ID at position {index}: {revision_id}"
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
        revision_policy = (
            "historical"
            if any(ref["revision_policy"] == "historical" for ref in node_refs)
            else "current_head"
            if node_refs
            else "current_head"
        )
        self.uses.accept(run_id, revision_pairs, revision_policy=revision_policy)
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
        artifact_is_empty = False
        for revision_id in state.output_revision_ids:
            revision = self.require_revision(revision_id)
            node_id = self._node_id(revision_id)
            node_revision_id = revision_id
            outputs.append(
                {
                    "kind": "revision",
                    "node_id": node_id,
                    "revision_id": node_revision_id,
                    "role": revision.manifest.content_type,
                }
            )
        if (
            request.processor_type == "event-detection"
            and state.status == "complete"
            and not state.output_revision_ids
        ):
            if self.event_set_store is None:
                raise PipelineNotFound("the event-set authority is unavailable")
            event_set = self.event_set_store.get(
                request.source.recording_id,
                f"run-{request.run_id}",
                "1",
            )
            if event_set is None:
                raise PipelineNotFound("the event processor output event set is unavailable")
            artifact_is_empty = not event_set["content"].get("events")
            outputs.append(
                {
                    "kind": "artifact",
                    "role": "events",
                    "artifact_id": (
                        f"event-set/{event_set['set_id']}/versions/{event_set['version']}"
                    ),
                    "sha256": event_set["content_sha256"],
                }
            )
        status = "succeeded" if state.status == "complete" else state.status
        result = None
        failure = None
        if status in {"succeeded", "partial"}:
            if outputs:
                result = (
                    "empty"
                    if (
                        artifact_is_empty
                        if any(ref["kind"] == "artifact" for ref in outputs)
                        else all(
                            self._is_empty(self.require_revision(x))
                            for x in state.output_revision_ids
                        )
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
        node_refs = request.input_node_refs or (
            (request.input_node_ref,) if request.input_node_ref is not None else ()
        )
        if request.input_event_set_ref is not None:
            refs = [
                {
                    "kind": "artifact",
                    "artifact_id": (
                        f"event-set/{request.input_event_set_ref['set_id']}"
                        f"/versions/{request.input_event_set_ref['version']}"
                    ),
                    "sha256": request.input_event_set_ref["content_sha256"],
                    "role": "events",
                }
            ]
        else:
            refs = []
        if request.input_detection_set_ref is not None:
            refs.append(
                {
                    "kind": "artifact",
                    "artifact_id": (
                        f"detection-set/{request.input_detection_set_ref['set_id']}"
                        f"/versions/{request.input_detection_set_ref['version']}"
                    ),
                    "sha256": request.input_detection_set_ref["content_sha256"],
                    "role": "detections",
                }
            )
        if node_refs:
            roles = {
                "observation-assembly": (
                    ("visual_identities",)
                    if request.input_detection_set_ref is not None
                    else ("visible_cards", "visual_identities")
                    if request.input_event_set_ref is not None
                    else ("events", "visible_cards", "visual_identities")
                ),
                "visual-card-identity": ("visible_cards",),
                "visible-card-scene-proposal": ("visible_cards",),
                "visible-card-detection": ("events",),
            }.get(request.processor_type, ())
            for index, ref in enumerate(node_refs):
                role = roles[index] if index < len(roles) else "input"
                if request.processor_type == "visual-card-identity":
                    node = self.node_store.get(ref["node_id"])
                    role = (
                        "virtual_scenes"
                        if node.content_type == "card_scene_proposals"
                        else "visible_cards"
                    )
                refs.append(
                    {
                        "kind": "revision",
                        "node_id": ref["node_id"],
                        "revision_id": ref["revision_id"],
                        "role": role,
                    }
                )
            return refs
        if request.input_event_set_ref is not None or request.input_detection_set_ref is not None:
            return refs
        if request.input_revision_ids:
            raise ValueError("processor execution requires exact node input references")
        refs = []
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
        node_ref: Mapping[str, str] | None,
        package_inputs: Sequence[tuple[str, str]],
        round_context: Mapping[str, Any],
        rules: Mapping[str, Any],
        search_settings: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        """Register exact observation and package inputs before analysis execution."""
        inputs: list[dict[str, str]] = []
        pairs = []
        if node_ref is not None:
            node_id = node_ref["node_id"]
            node_revision_id = node_ref["revision_id"]
            node = self.node_store.get(node_id)
            self.node_store.read_revision_record(node_id, node_revision_id)
            if (
                node.content_type != "table_observations"
                or node.source.get("recording_id") != recording_id
            ):
                raise NodeConflict("analysis input reference does not match its recording")
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
