"""Durable accepted uses of exact node revisions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from dokodetector_backend.filesystem import atomic_write_json, contained_path
from dokodetector_backend.pipeline_node_store import NodeConflict, PipelineNodeStore, _read_json
from dokodetector_backend.pipeline_store import _canonical_timestamp, _process_lock, _safe_id


class PipelineNodeUses:
    """Serialize run acceptance with node edits before a worker can read its inputs."""

    def __init__(self, store: PipelineNodeStore) -> None:
        self.store = store

    def accept(self, run_id: str, inputs: Sequence[tuple[str, str]]) -> dict[str, Any]:
        _safe_id(run_id, "run_id")
        refs = []
        for node_id, revision_id in inputs:
            refs.append(
                {
                    "node_id": _safe_id(node_id, "node_id"),
                    "revision_id": _safe_id(revision_id, "revision_id"),
                }
            )
        refs.sort(key=lambda item: (item["node_id"], item["revision_id"]))
        if len({(item["node_id"], item["revision_id"]) for item in refs}) != len(refs):
            raise ValueError("duplicate accepted input")
        root = self.store.root / ".accepted-uses"
        path = contained_path(root, f"{run_id}.json")
        with _process_lock(self.store.root / ".transactions.lock", self.store._lock):
            if path.exists():
                previous = _read_json(path)
                if previous["inputs"] != refs:
                    raise NodeConflict("run ID is already bound to different inputs")
                return previous
            for ref in refs:
                node = self.store.get(ref["node_id"])
                if node.head_revision_id != ref["revision_id"]:
                    raise NodeConflict("input working head changed before acceptance")
                self.store.read_revision(ref["node_id"], ref["revision_id"])
            record = {
                "schema_version": "pipeline-accepted-use/v1",
                "run_id": run_id,
                "inputs": refs,
                "accepted_at": _canonical_timestamp(None),
            }
            atomic_write_json(path, record)
            return record
