"""Durable accepted uses of exact node revisions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from dokodetector_backend.filesystem import atomic_write_json, contained_path
from dokodetector_backend.pipeline_node_store import NodeConflict, PipelineNodeStore, _read_json
from dokodetector_backend.pipeline_storage import _canonical_timestamp, _safe_id


class PipelineNodeUses:
    """Serialize run acceptance with node edits before a worker can read its inputs."""

    def __init__(self, store: PipelineNodeStore) -> None:
        self.store = store

    def accept(
        self,
        run_id: str,
        inputs: Sequence[tuple[str, str]],
        *,
        revision_policy: Literal["current_head", "historical"] = "current_head",
    ) -> dict[str, Any]:
        """Accept exact node revisions under an explicit head policy.

        ``current_head`` preserves the normal execution contract. ``historical``
        accepts an exact immutable revision that exists on each specified node.
        """
        if revision_policy not in {"current_head", "historical"}:
            raise ValueError("invalid revision policy")
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
        with self.store.transaction_lock():
            if path.exists():
                previous = _read_json(path)
                if previous["inputs"] != refs:
                    raise NodeConflict("run ID is already bound to different inputs")
                return previous
            for ref in refs:
                node = self.store.get(ref["node_id"])
                if (
                    revision_policy == "current_head"
                    and node.head_revision_id != ref["revision_id"]
                ):
                    raise NodeConflict("input working head changed before acceptance")
                self.store.read_published_revision(ref["node_id"], ref["revision_id"])
            record = {
                "schema_version": "pipeline-accepted-use/v1",
                "run_id": run_id,
                "inputs": refs,
                "accepted_at": _canonical_timestamp(None),
            }
            atomic_write_json(path, record)
            return record
