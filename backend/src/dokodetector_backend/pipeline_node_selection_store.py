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
    PipelineSelection,
    PipelineSelectionUpdate,
    canonical_json_bytes,
)

from dokodetector_backend.filesystem import atomic_replace_json, contained_path
from dokodetector_backend.pipeline_lineage_writer import PipelineLineageWriter
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_store import (
    PipelineRevisionStore,
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
    """Bridge existing pipeline callers to graph-backed selection records."""

    def __init__(
        self,
        node_store: PipelineNodeStore,
        revision_store: PipelineRevisionStore,
        lineage_writer: PipelineLineageWriter | None = None,
    ) -> None:
        self.node_store = node_store
        self.revision_store = revision_store
        self.lineage_writer = lineage_writer
        self.root = node_store.root / ".migrated-selections"
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
                "legacy_selection_id": f"{recording_id}/{content_type}",
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
            "legacy_selection_id",
        }:
            raise ValueError("invalid exact node selection record")
        if (
            raw["schema_version"] != "pipeline-node-selection/v1"
            or raw["recording_id"] != recording_id
            or raw["content_type"] != content_type
            or isinstance(raw["revision"], bool)
            or not isinstance(raw["revision"], int)
            or raw["revision"] < 1
            or raw["legacy_selection_id"] != f"{recording_id}/{content_type}"
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

    def get(
        self,
        recording_id: str,
        content_type: str,
        *,
        revision_cache: dict[str, Any] | None = None,
        revision_manifests: Mapping[str, Any] | None = None,
    ) -> PipelineSelection | None:
        self.node_store.recover_transactions()
        try:
            path = self.selection_path(recording_id, content_type)
            raw = json.loads(path.read_bytes())
            if not isinstance(raw, dict) or set(raw) != {
                "schema_version",
                "recording_id",
                "content_type",
                "revision",
                "selected_generated",
                "selected_completed_reference",
                "updated_at",
                "legacy_selection_id",
            }:
                raise ValueError("invalid node selection record")
            if (
                raw["schema_version"] != "pipeline-node-selection/v1"
                or raw["recording_id"] != recording_id
                or raw["content_type"] != content_type
            ):
                raise ValueError("node selection identity mismatch")
            legacy_ids = {
                "generated": self._legacy_id(
                    raw["selected_generated"],
                    recording_id,
                    content_type,
                    revision_cache=revision_cache,
                    revision_manifests=revision_manifests,
                ),
                "completed_reference": self._legacy_id(
                    raw["selected_completed_reference"],
                    recording_id,
                    content_type,
                    revision_cache=revision_cache,
                    revision_manifests=revision_manifests,
                ),
            }
            return PipelineSelection.from_mapping(
                {
                    "schema_version": "pipeline-selection/v1",
                    "revision": raw["revision"],
                    "recording_id": recording_id,
                    "content_type": content_type,
                    "selected_generated_revision_id": legacy_ids["generated"],
                    "selected_completed_reference_revision_id": legacy_ids["completed_reference"],
                    "updated_at": raw["updated_at"],
                }
            )
        except FileNotFoundError:
            return None
        except (OSError, TypeError, UnicodeError, ValueError, KeyError):
            return None

    def list(self) -> tuple[PipelineSelection, ...]:
        if self.root.is_symlink() or not self.root.is_dir():
            return ()
        selections = []
        revision_cache: dict[str, Any] = {}
        for directory in sorted(self.root.iterdir(), key=lambda item: item.name):
            if directory.is_symlink() or not directory.is_dir() or directory.name.startswith("."):
                continue
            for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
                selection = self.get(directory.name, path.stem, revision_cache=revision_cache)
                if selection is not None:
                    selections.append(selection)
        return tuple(selections)

    def list_for_recording(self, recording_id: str) -> tuple[PipelineSelection, ...]:
        return tuple(item for item in self.list() if item.recording_id == recording_id)

    def update(
        self,
        recording_id: str,
        content_type: str,
        update: PipelineSelectionUpdate | Mapping[str, Any],
        *,
        updated_at: datetime | str | None = None,
        revision_cache: dict[str, Any] | None = None,
    ) -> PipelineSelection:
        parsed = (
            PipelineSelectionUpdate.from_mapping(update.to_mapping())
            if isinstance(update, PipelineSelectionUpdate)
            else PipelineSelectionUpdate.from_mapping(update)
        )
        path = self.selection_path(recording_id, content_type)
        with _process_lock(path.parent / f".{path.stem}.lock", self._lock):
            current = self.get(recording_id, content_type, revision_cache=revision_cache)
            if current is None and (path.exists() or path.is_symlink()):
                raise PipelineStoreError("The existing graph selection is invalid.")
            current_revision = 0 if current is None else current.revision
            if parsed.expected_revision != current_revision:
                raise PipelineSelectionConflict(
                    f"selection revision mismatch: expected {parsed.expected_revision}, "
                    f"actual {current_revision}"
                )
            generated = self._node_reference(
                parsed.selected_generated_revision_id, recording_id, content_type
            )
            completed = self._node_reference(
                parsed.selected_completed_reference_revision_id, recording_id, content_type
            )
            record = {
                "schema_version": "pipeline-node-selection/v1",
                "recording_id": recording_id,
                "content_type": content_type,
                "revision": current_revision + 1,
                "selected_generated": generated,
                "selected_completed_reference": completed,
                "updated_at": _canonical_timestamp(updated_at),
                "legacy_selection_id": f"{recording_id}/{content_type}",
            }
            atomic_replace_json(path, canonical_json_bytes(record))
            stored = self.get(recording_id, content_type)
            if stored is None:
                raise PipelineStoreError("The updated graph selection failed validation.")
            return stored

    def update_pointers(
        self,
        recording_id: str,
        content_type: str,
        *,
        expected_revision: int,
        selected_generated_revision_id: str | None,
        selected_completed_reference_revision_id: str | None,
        updated_at: datetime | str | None = None,
        revision_cache: dict[str, Any] | None = None,
    ) -> PipelineSelection:
        return self.update(
            recording_id,
            content_type,
            PipelineSelectionUpdate(
                expected_revision=expected_revision,
                selected_generated_revision_id=selected_generated_revision_id,
                selected_completed_reference_revision_id=selected_completed_reference_revision_id,
            ),
            updated_at=updated_at,
            revision_cache=revision_cache,
        )

    def _node_reference(
        self, revision_id: str | None, recording_id: str, content_type: str
    ) -> dict[str, str] | None:
        if revision_id is None:
            return None
        stored = self.revision_store.require(revision_id)
        if (
            stored.manifest.recording_id != recording_id
            or stored.manifest.content_type != content_type
        ):
            raise ValueError("selection revision does not match its recording or content type")
        if self.lineage_writer is not None:
            node_id, node_revision_id = self.lineage_writer.ensure_revision_node(stored)
            return {"node_id": node_id, "revision_id": node_revision_id}
        if self.lineage_writer is not None:
            node_id, node_revision_id = self.lineage_writer.ensure_revision_node(stored)
        else:
            node_id, node_revision_id = None, None
        if node_id is None:
            for node in self.node_store.list_nodes():
                if (
                    node.content_type != content_type
                    or node.source.get("recording_id") != recording_id
                ):
                    continue
                for revision in self.node_store.history(node.node_id):
                    if (
                        revision.metadata.get("legacy_revision_id") == revision_id
                        or revision.revision_id == revision_id
                    ):
                        node_id, node_revision_id = node.node_id, revision.revision_id
                        break
                if node_id is not None:
                    break
        if node_id is None:
            raise ValueError("selection revision has no matching graph revision")
        return {"node_id": node_id, "revision_id": node_revision_id}

    def _legacy_id(
        self,
        reference: Any,
        recording_id: str,
        content_type: str,
        *,
        revision_cache: dict[str, Any] | None = None,
        revision_manifests: Mapping[str, Any] | None = None,
    ) -> str | None:
        if reference is None:
            return None
        if not isinstance(reference, dict) or set(reference) != {"node_id", "revision_id"}:
            raise ValueError("invalid node selection pointer")
        node_id = reference["node_id"]
        revision_id = reference["revision_id"]
        node = self.node_store.get(node_id)
        record = self.node_store.read_revision_record(node_id, revision_id)
        legacy_id = record.metadata.get("legacy_revision_id", revision_id)
        if (
            node.content_type != content_type
            or node.source.get("recording_id") != recording_id
            or not isinstance(legacy_id, str)
            or not self.node_store.has_revision(node_id, revision_id)
        ):
            raise ValueError("node selection points to an incompatible revision")
        return legacy_id


__all__ = ["PipelineNodeSelectionStore"]
