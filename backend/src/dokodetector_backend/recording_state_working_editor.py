"""Selected working-content adapter for the recording-state vertical slice."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from dokodetector_backend.pipeline_node_edits import PipelineNodeEdits
from dokodetector_backend.recording_state_contract import (
    ExactResourceRef,
    RecordingHeadUpdate,
    RecordingStateSnapshot,
)
from dokodetector_backend.recording_state_store import (
    RecordingHeadConflict,
    RecordingStateSnapshotStore,
)


class RecordingStateWorkingEditor:
    """Edit one selected event resource and publish its exact replacement in HEAD."""

    def __init__(
        self, state_store: RecordingStateSnapshotStore, node_edits: PipelineNodeEdits
    ) -> None:
        self.state_store = state_store
        self.node_edits = node_edits

    def edit_events(
        self,
        recording_id: str,
        expected_head_version: int,
        idempotency_key: str,
        actor: Mapping[str, Any],
        content: Mapping[str, Any],
    ) -> dict[str, Any]:
        state = self.state_store.get_current(recording_id)
        if state.head.version != expected_head_version:
            raise RecordingHeadConflict(
                f"expected recording HEAD {expected_head_version}, found {state.head.version}"
            )

        event_stage = state.snapshot.slots["events"]
        selected_field = (
            "generated"
            if event_stage.generated.state == "selected"
            else "completed_reference"
            if event_stage.completed_reference.state == "selected"
            else None
        )
        if selected_field is None:
            raise ValueError("recording has no selected event working content")
        selection = getattr(event_stage, selected_field)
        resource = selection.resource
        if resource is None or resource.kind != "pipeline-node-revision":
            raise ValueError("selected event content is not a pipeline node revision")
        node_id = resource.node_id
        revision_id = resource.revision_id
        assert node_id is not None and revision_id is not None

        store = self.node_edits.store
        node = store.get(node_id)
        if node.source.get("recording_id") != recording_id or node.content_type != "events":
            raise ValueError("selected event content belongs to another recording")
        revision = store.read_authorized_revision(node_id, revision_id)
        if (
            revision.revision_id != resource.resource_id
            or revision.content_sha256 != resource.sha256
            or revision.content.get("schema_version") != resource.schema_version
        ):
            raise ValueError("selected event content identity or digest mismatch")

        edit = self.node_edits.edit(
            node_id,
            revision_id,
            content,
            idempotency_key,
            actor,
        )
        edited_node_id = edit["node_id"]
        edited_revision = store.read_authorized_revision(edited_node_id, edit["revision_id"])
        updated_resource = ExactResourceRef(
            kind="pipeline-node-revision",
            resource_id=edited_revision.revision_id,
            schema_version=edited_revision.content["schema_version"],
            sha256=edited_revision.content_sha256,
            node_id=edited_node_id,
            revision_id=edited_revision.revision_id,
        )

        payload = state.snapshot.model_dump(mode="json")
        payload["predecessor_snapshot_id"] = state.snapshot.snapshot_id
        payload["slots"]["events"][selected_field]["resource"] = updated_resource.model_dump(
            mode="json"
        )
        payload.pop("snapshot_id")
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        payload["snapshot_id"] = "rs_" + hashlib.sha256(canonical).hexdigest()
        snapshot = RecordingStateSnapshot.model_validate(payload)
        stored = self.state_store.put(snapshot)
        published = self.state_store.publish(
            RecordingHeadUpdate(
                recording_id=recording_id,
                expected_head_version=expected_head_version,
                snapshot_id=stored.snapshot.snapshot_id,
                action="select_snapshot",
            )
        )
        return {
            "edit": edit,
            "head": published.head.model_dump(mode="json"),
            "snapshot": published.snapshot.model_dump(mode="json"),
            "summary": published.summary.model_dump(mode="json"),
        }
