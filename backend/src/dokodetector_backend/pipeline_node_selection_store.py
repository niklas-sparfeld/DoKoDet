"""Persist pipeline selections as exact node and revision pointers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from doko_operations.pipeline_data import (
    canonical_json_bytes,
)

from dokodetector_backend.filesystem import atomic_replace_json, contained_path
from dokodetector_backend.pipeline_lineage_writer import PipelineLineageWriter
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_storage import (
    PipelineSelectionConflict,
    PipelineStoreError,
    _canonical_timestamp,
    _process_lock,
    _safe_id,
)

_NODE_CONTENT_TYPES = {
    "events",
    "visible_cards",
    "virtual_scenes",
    "visual_identities",
    "table_observations",
    "card_scene_proposals",
}


@dataclass(frozen=True, slots=True)
class ExactNodeSelection:
    """A selection whose pointers retain node and revision identity."""

    recording_id: str
    content_type: str
    revision: int
    selected_generated: dict[str, str] | None
    selected_completed_reference: dict[str, str] | None
    updated_at: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "recording_id": self.recording_id,
            "content_type": self.content_type,
            "revision": self.revision,
            "selected_generated": self.selected_generated,
            "selected_completed_reference": self.selected_completed_reference,
            "updated_at": self.updated_at,
        }


class PipelineNodeSelectionStore:
    """Store exact graph selections and expose explicit processor execution choices."""

    def __init__(
        self,
        node_store: PipelineNodeStore,
        lineage_writer: PipelineLineageWriter | None = None,
    ) -> None:
        self.node_store = node_store
        self.lineage_writer = lineage_writer
        self.root = node_store.root / ".pipeline-node-selections"
        self._lock = RLock()

    def selection_path(self, recording_id: str, content_type: str) -> Path:
        _safe_id(recording_id, "recording_id")
        if content_type not in _NODE_CONTENT_TYPES:
            raise ValueError("content_type is unsupported")
        return contained_path(self.root / recording_id, f"{content_type}.json")

    def get_exact(self, recording_id: str, content_type: str) -> ExactNodeSelection | None:
        """Read graph pointers without projecting them through the legacy revision map."""
        self.node_store.recover_transactions()
        path = self.selection_path(recording_id, content_type)
        try:
            payload = path.read_bytes()
            raw = json.loads(payload)
        except FileNotFoundError:
            return None
        if canonical_json_bytes(raw) != payload:
            raise ValueError("exact node selection record is not canonical")
        return self._parse_exact(raw, recording_id, content_type)

    def update_exact(
        self,
        recording_id: str,
        content_type: str,
        *,
        expected_revision: int,
        selected_generated: Mapping[str, str] | None,
        selected_completed_reference: Mapping[str, str] | None,
        updated_at: datetime | str | None = None,
    ) -> ExactNodeSelection:
        """Update exact graph pointers with compare-and-swap and node validation.

        This API is an additive foundation. Existing pipeline callers still use ``update``
        until a coordinated multi-node transaction can publish all related state together.
        """
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError("expected_revision must be an integer")
        if expected_revision < 0:
            raise ValueError("expected_revision must not be negative")
        path = self.selection_path(recording_id, content_type)
        with _process_lock(path.parent / f".{path.stem}.lock", self._lock):
            current = self.get_exact(recording_id, content_type)
            actual = 0 if current is None else current.revision
            if expected_revision != actual:
                raise PipelineSelectionConflict(
                    f"selection revision mismatch: expected {expected_revision}, actual {actual}"
                )
            generated = self._validate_exact_pointer(selected_generated, recording_id, content_type)
            completed = self._validate_exact_pointer(
                selected_completed_reference, recording_id, content_type
            )
            raw = {
                "schema_version": "pipeline-node-selection/v1",
                "recording_id": recording_id,
                "content_type": content_type,
                "revision": actual + 1,
                "selected_generated": generated,
                "selected_completed_reference": completed,
                "updated_at": _canonical_timestamp(updated_at),
            }
            atomic_replace_json(path, canonical_json_bytes(raw))
            stored = self.get_exact(recording_id, content_type)
            if stored is None:
                raise PipelineStoreError("The updated exact node selection failed validation.")
            return stored

    def _validate_exact_pointer(
        self,
        pointer: Mapping[str, str] | None,
        recording_id: str,
        content_type: str,
    ) -> dict[str, str] | None:
        if pointer is None:
            return None
        if not isinstance(pointer, Mapping) or set(pointer) != {"node_id", "revision_id"}:
            raise ValueError("selection pointer must contain node_id and revision_id")
        node_id = _safe_id(pointer["node_id"], "node_id")
        revision_id = _safe_id(pointer["revision_id"], "revision_id")
        node = self.node_store.get(node_id)
        if node.content_type != content_type or node.source.get("recording_id") != recording_id:
            raise ValueError("selection pointer does not match its recording and content type")
        if not self.node_store.has_revision(node_id, revision_id):
            raise ValueError("selection pointer has no matching node revision")
        return {"node_id": node_id, "revision_id": revision_id}

    def _parse_exact(self, raw: Any, recording_id: str, content_type: str) -> ExactNodeSelection:
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version",
            "recording_id",
            "content_type",
            "revision",
            "selected_generated",
            "selected_completed_reference",
            "updated_at",
        }:
            raise ValueError("invalid exact node selection record")
        if (
            raw["schema_version"] != "pipeline-node-selection/v1"
            or raw["recording_id"] != recording_id
            or raw["content_type"] != content_type
            or isinstance(raw["revision"], bool)
            or not isinstance(raw["revision"], int)
            or raw["revision"] < 1
            or not isinstance(raw["updated_at"], str)
        ):
            raise ValueError("exact node selection identity is invalid")
        generated = self._validate_exact_pointer(
            raw["selected_generated"], recording_id, content_type
        )
        completed = self._validate_exact_pointer(
            raw["selected_completed_reference"], recording_id, content_type
        )
        return ExactNodeSelection(
            recording_id, content_type, raw["revision"], generated, completed, raw["updated_at"]
        )

    def reference_for_processor_output(
        self, revision_id: str, recording_id: str, content_type: str
    ) -> dict[str, str]:
        """Resolve a newly published processor output to its exact graph revision."""
        if self.lineage_writer is None:
            raise PipelineStoreError("the processor lineage writer is unavailable")
        return self.lineage_writer.node_ref_for_processor_output(
            revision_id, recording_id, content_type
        )

    def publish_processor_revision(self, manifest: Any, content: Any):
        """Publish processor content once, as a canonical pipeline node revision."""
        if self.lineage_writer is None:
            raise PipelineStoreError("the processor lineage writer is unavailable")
        return self.lineage_writer.publish_processor_revision(manifest, content)

    def require_processor_revision(self, revision_id: str):
        """Read a processor output from its canonical node revision."""
        if self.lineage_writer is None:
            raise PipelineStoreError("the processor lineage writer is unavailable")
        return self.lineage_writer.require_revision(revision_id)

    def require_revision(self, revision_id: str):
        """Read one globally unique exact revision from the node store."""
        try:
            node, _ = self.node_store.find_revision(revision_id)
        except (FileNotFoundError, KeyError, ValueError) as error:
            raise PipelineStoreError(
                f"pipeline node revision is unavailable: {revision_id}"
            ) from error
        if self.lineage_writer is None:
            raise PipelineStoreError("the processor lineage writer is unavailable")
        return self.lineage_writer.read_node_revision(node.node_id, revision_id)

    def read_node_revision(self, node_id: str, revision_id: str):
        """Read the immutable processor data value for one exact node pointer."""
        if self.lineage_writer is None:
            raise PipelineStoreError("the processor lineage writer is unavailable")
        return self.lineage_writer.read_node_revision(node_id, revision_id)


__all__ = ["PipelineNodeSelectionStore"]
