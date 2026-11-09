"""Exact node bindings for the frozen frame review queue."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dokodetector_backend.frame_review_queue import parse_frozen_queue


def build_frame_review_bindings(
    queue: Mapping[str, Any], revisions: Mapping[str, Any], store: Any
) -> dict[str, Any]:
    """Resolve the migration inventory once, preserving missing pinned sources."""
    items = parse_frozen_queue(queue)
    verified: dict[tuple[str, str], tuple[Any, Any]] = {}
    result = []
    for item in items:
        target = revisions.get(item.source_revision_id) if item.source_revision_id else None
        if target is not None:
            if not isinstance(target, dict) or set(target) != {"node_id", "revision_id"}:
                raise ValueError("invalid frame review source mapping")
            pair = (target["node_id"], target["revision_id"])
            if pair not in verified:
                verified[pair] = (store.get(pair[0]), store.read_revision(pair[0], pair[1]))
            node, revision = verified[pair]
            if (
                node.content_type != "visible_cards"
                or node.source.get("recording_id") != item.recording_id
                or (
                    item.source_revision_sha256 is not None
                    and revision.content_sha256 != item.source_revision_sha256
                )
                or (
                    item.source_revision_sha256 is None
                    and revision.revision_id != item.source_revision_id
                )
            ):
                raise ValueError("frame review source identity does not match its frozen input")
        result.append(
            {"recording_id": item.recording_id, "item_id": item.item_id, "source": target}
        )
    return {
        "schema_version": "frame-review-node-bindings/v1",
        "queue_id": "0096-M4",
        "queue_digest": queue["selection_sha256"],
        "items": result,
    }


def _binding_path(root: Any):
    from pathlib import Path

    from dokodetector_backend.filesystem import contained_path

    return contained_path(Path(root).expanduser().resolve(), ".frame-review-bindings/0096-M4.json")


def load_frame_review_bindings(
    root: Any, queue_digest: str
) -> dict[tuple[str, str], dict[str, str] | None]:
    """Load exact node references for the current frozen queue."""
    import json

    raw = json.loads(_binding_path(root).read_bytes())
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != "frame-review-node-bindings/v1"
        or raw.get("queue_id") != "0096-M4"
        or raw.get("queue_digest") != queue_digest
    ):
        raise ValueError("frame review binding digest does not match the frozen queue")
    items = raw.get("items")
    if not isinstance(items, list):
        raise ValueError("frame review bindings have invalid items")
    result = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {"recording_id", "item_id", "source"}:
            raise ValueError("frame review binding is invalid")
        recording, item_id, source = item["recording_id"], item["item_id"], item["source"]
        if (
            not isinstance(recording, str)
            or not recording
            or not isinstance(item_id, str)
            or not item_id
        ):
            raise ValueError("frame review binding identity is invalid")
        if source is not None and (
            not isinstance(source, dict)
            or set(source) != {"node_id", "revision_id"}
            or any(not isinstance(value, str) or not value for value in source.values())
        ):
            raise ValueError("frame review source binding is invalid")
        key = (recording, item_id)
        if key in result:
            raise ValueError("duplicate frame review binding")
        result[key] = source
    return result


def write_frame_review_bindings(root: Any, bindings: Mapping[str, Any]) -> None:
    """Publish the migration result once without replacing an existing binding."""
    from dokodetector_backend.filesystem import atomic_write_json
    from dokodetector_backend.pipeline_node_store import PipelineNodeStore, _object, _read_json

    store = PipelineNodeStore(root)
    path = _binding_path(store.root)
    data = _object(bindings, "frame review bindings")
    with store.transaction_lock():
        if path.exists():
            if _read_json(path) != data:
                raise ValueError("frame review bindings conflict with existing data")
            return
        atomic_write_json(path, data)
