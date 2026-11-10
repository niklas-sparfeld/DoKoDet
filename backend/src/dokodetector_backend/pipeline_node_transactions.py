"""Journaled publication for coordinated node revisions and exact selections."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from doko_operations.pipeline_data import canonical_json_bytes

from dokodetector_backend.filesystem import atomic_replace_json, contained_path
from dokodetector_backend.pipeline_node_store import (
    NodeConflict,
    NodeRevision,
    NodeUsed,
    PipelineNodeStore,
    _content,
    _object,
    _read_json,
)
from dokodetector_backend.pipeline_storage import (
    PipelineSelectionConflict,
    _canonical_timestamp,
    _process_lock,
    _safe_id,
)


class PipelineNodeTransactions:
    """Prepare and recover a set of node revisions and exact selection pointers.

    The durable journal is written before any head or selection changes. All node and selection
    reads recover prepared journals first, so a process restart cannot expose a partial state.
    Recovery rolls the transaction forward and is safe to repeat.
    """

    def __init__(self, node_store: PipelineNodeStore) -> None:
        self.node_store = node_store
        self.root = node_store.root / ".coordinated-transactions"
        self.pending_path = self.root / ".locator" / "pending.json"

    def commit(
        self,
        transaction_id: str,
        *,
        node_updates: Sequence[Mapping[str, Any]],
        selection_updates: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        _safe_id(transaction_id, "transaction_id")
        request_digest = hashlib.sha256(
            canonical_json_bytes(
                {"node_updates": list(node_updates), "selection_updates": list(selection_updates)}
            )
        ).hexdigest()
        journal = contained_path(self.root, f"{transaction_id}.json")
        with self.node_store.transaction_lock():
            self.node_store.recover_transactions()
            if journal.exists():
                previous = _read_json(journal)
                if previous.get("request_digest") != request_digest:
                    raise NodeConflict("transaction_id is already bound to different updates")
            else:
                plan = self._prepare_plan(node_updates, selection_updates)
                digest = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
                # Publish the locator first. If the process stops before the journal rename,
                # recovery sees the locator without a journal and clears it. If it stops after the
                # rename, the locator names the only journal that can need recovery.
                atomic_replace_json(
                    self.pending_path,
                    {
                        "schema_version": "pipeline-node-pending-transaction/v1",
                        "transaction_id": transaction_id,
                        "request_digest": request_digest,
                    },
                )
                self.node_store._after_durable_boundary("locator")
                atomic_replace_json(
                    journal,
                    {
                        "schema_version": "pipeline-node-transaction/v1",
                        "request_digest": request_digest,
                        "digest": digest,
                        "plan": plan,
                        "status": "prepared",
                    },
                )
                self.node_store._after_durable_boundary("journal")
            self.recover()
            result = _read_json(journal)
            return {
                "transaction_id": transaction_id,
                "digest": result["digest"],
                "status": "committed",
            }

    def recover(self) -> None:
        with self.node_store.transaction_lock():
            self.node_store.recover_transactions()

    def _recover_under_lock(self) -> None:
        if not self.root.exists() or self.root.is_symlink() or not self.root.is_dir():
            return
        if not self.pending_path.exists():
            return
        pending = _read_json(self.pending_path)
        if (
            set(pending) != {"schema_version", "transaction_id", "request_digest"}
            or pending["schema_version"] != "pipeline-node-pending-transaction/v1"
        ):
            raise ValueError("invalid pending coordinated transaction locator")
        transaction_id = pending["transaction_id"]
        request_digest = pending["request_digest"]
        if transaction_id is None:
            if request_digest is not None:
                raise ValueError("empty pending locator has a request digest")
            return
        transaction_id = _safe_id(transaction_id, "transaction_id")
        if not isinstance(request_digest, str):
            raise ValueError("pending locator has no request digest")
        journal = contained_path(self.root, f"{transaction_id}.json")
        if journal.exists():
            record = _read_json(journal)
            if record.get("request_digest") != request_digest:
                raise ValueError("pending locator does not match coordinated transaction")
            self._recover_one(journal)
        self.node_store._reconcile_revision_history_outbox_locked()
        # A committed journal is retained for direct idempotency lookup. A missing journal means
        # the process stopped after publishing the locator but before preparing the journal.
        atomic_replace_json(
            self.pending_path,
            {
                "schema_version": "pipeline-node-pending-transaction/v1",
                "transaction_id": None,
                "request_digest": None,
            },
        )

    def _prepare_plan(
        self,
        node_updates: Sequence[Mapping[str, Any]],
        selection_updates: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if not node_updates and not selection_updates:
            raise ValueError("a coordinated transaction needs at least one update")
        prepared_nodes = []
        seen_nodes: set[str] = set()
        for item in node_updates:
            if set(item) != {
                "node_id",
                "expected_revision_id",
                "revision_id",
                "content",
                "metadata",
            }:
                raise ValueError("invalid coordinated node update")
            node_id = _safe_id(item["node_id"], "node_id")
            expected = _safe_id(item["expected_revision_id"], "expected_revision_id")
            revision_id = _safe_id(item["revision_id"], "revision_id")
            if node_id in seen_nodes:
                raise ValueError("a coordinated transaction cannot update one node twice")
            seen_nodes.add(node_id)
            node = self.node_store.get(node_id)
            current = self.node_store.read_revision_record(node_id, expected)
            if node.head_revision_id != expected:
                raise NodeConflict("working head changed")
            content = _content(node.content_type, node.source, item["content"])
            metadata = _object(item["metadata"], "metadata")
            uses_root = self.node_store.root / ".accepted-uses"
            if (
                uses_root.exists()
                and any(
                    any(use["node_id"] == node_id for use in _read_json(path)["inputs"])
                    for path in uses_root.glob("*.json")
                )
                and content != current.content
            ):
                raise NodeUsed("accepted downstream use protects this node")
            prepared_nodes.append(
                {
                    "node_id": node_id,
                    "expected_revision_id": expected,
                    "revision_id": revision_id,
                    "parent_revision_id": expected,
                    "content": content,
                    "content_sha256": hashlib.sha256(canonical_json_bytes(content)).hexdigest(),
                    "metadata": metadata,
                    "created_at": _canonical_timestamp(None),
                    "name": node.name,
                    "content_type": node.content_type,
                    "recording_id": node.source.get("recording_id"),
                }
            )
        prepared_by_revision = {
            (item["node_id"], item["revision_id"]): item for item in prepared_nodes
        }
        selection_store = None
        if selection_updates:
            from dokodetector_backend.pipeline_node_selection_store import (
                PipelineNodeSelectionStore,
            )

            selection_store = PipelineNodeSelectionStore(self.node_store)
        prepared_selections = []
        for item in selection_updates:
            assert selection_store is not None
            if set(item) != {
                "recording_id",
                "content_type",
                "expected_revision",
                "selected_generated",
                "selected_completed_reference",
            }:
                raise ValueError("invalid coordinated selection update")
            recording_id = _safe_id(item["recording_id"], "recording_id")
            content_type = item["content_type"]
            if not isinstance(content_type, str):
                raise ValueError("content_type must be a string")
            expected = item["expected_revision"]
            if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
                raise ValueError("expected_revision must be a nonnegative integer")
            current_selection = selection_store.get_exact(recording_id, content_type)
            actual_selection_revision = (
                0 if current_selection is None else current_selection.revision
            )
            if actual_selection_revision != expected:
                raise PipelineSelectionConflict("selection changed before coordinated publication")
            for pointer in (item["selected_generated"], item["selected_completed_reference"]):
                if pointer is None:
                    continue
                if not isinstance(pointer, Mapping) or set(pointer) != {"node_id", "revision_id"}:
                    raise ValueError("selection pointer must contain node_id and revision_id")
                node_id = _safe_id(pointer["node_id"], "node_id")
                revision_id = _safe_id(pointer["revision_id"], "revision_id")
                planned = prepared_by_revision.get((node_id, revision_id))
                if planned is not None:
                    if (
                        planned["recording_id"] != recording_id
                        or planned["content_type"] != content_type
                    ):
                        raise ValueError("planned selection revision has incompatible identity")
                else:
                    selection_store._validate_exact_pointer(pointer, recording_id, content_type)
            prepared_selections.append(
                {
                    "recording_id": recording_id,
                    "content_type": content_type,
                    "expected_revision": expected,
                    "revision": expected + 1,
                    "selected_generated": item["selected_generated"],
                    "selected_completed_reference": item["selected_completed_reference"],
                }
            )
        if len({(x["recording_id"], x["content_type"]) for x in prepared_selections}) != len(
            prepared_selections
        ):
            raise ValueError("a coordinated transaction cannot update one selection twice")
        return {"nodes": prepared_nodes, "selections": prepared_selections}

    def _recover_one(self, path: Path) -> None:
        record = _read_json(path)
        if set(record) != {"schema_version", "request_digest", "digest", "plan", "status"}:
            raise ValueError("invalid coordinated transaction journal")
        plan = record["plan"]
        if (
            record["schema_version"] != "pipeline-node-transaction/v1"
            or not isinstance(record["request_digest"], str)
            or record["status"] not in {"prepared", "committed"}
            or hashlib.sha256(canonical_json_bytes(plan)).hexdigest() != record["digest"]
            or set(plan) != {"nodes", "selections"}
        ):
            raise ValueError("coordinated transaction journal failed validation")
        if record["status"] == "committed":
            return
        for update in plan["nodes"]:
            with _process_lock(
                self.node_store._lock_path(update["node_id"]), self.node_store._lock
            ):
                node = self.node_store._get_unrecovered(update["node_id"])
                if (
                    node.content_type != update["content_type"]
                    or node.source.get("recording_id") != update["recording_id"]
                ):
                    raise ValueError("coordinated node identity changed")
                revision = NodeRevision(
                    node_id=node.node_id,
                    revision_id=update["revision_id"],
                    parent_revision_id=update["parent_revision_id"],
                    content=update["content"],
                    content_sha256=update["content_sha256"],
                    metadata=update["metadata"],
                    created_at=update["created_at"],
                )
                self.node_store._queue_revision_history(
                    self.node_store._node_path(node.node_id), revision
                )
                if self.node_store.has_revision(node.node_id, update["revision_id"]):
                    existing = self.node_store._read_revision(node, update["revision_id"])
                    if existing != revision:
                        raise ValueError("coordinated revision ID already has different content")
                else:
                    self.node_store._publish_revision(
                        self.node_store._node_path(node.node_id), revision
                    )
                current = self.node_store._get_unrecovered(node.node_id)
                if current.head_revision_id == update["expected_revision_id"]:
                    previous = self.node_store._read_revision(
                        current, update["expected_revision_id"]
                    )
                    self.node_store._publish_publication(
                        self.node_store._node_path(node.node_id), previous
                    )
                    atomic_replace_json(
                        self.node_store._node_path(node.node_id) / "head.json",
                        {"revision_id": update["revision_id"]},
                    )
                    self.node_store._after_durable_boundary("head")
                elif current.head_revision_id != update["revision_id"]:
                    raise NodeConflict("node head changed during coordinated recovery")
                self.node_store._publish_publication(
                    self.node_store._node_path(node.node_id), revision
                )
                self.node_store._after_durable_boundary("publication")
        selections = None
        if plan["selections"]:
            from dokodetector_backend.pipeline_node_selection_store import (
                PipelineNodeSelectionStore,
            )

            selections = PipelineNodeSelectionStore(self.node_store)
        for update in plan["selections"]:
            assert selections is not None
            current = selections.get_exact(update["recording_id"], update["content_type"])
            actual = 0 if current is None else current.revision
            if actual == update["revision"]:
                if (
                    current.selected_generated != update["selected_generated"]
                    or current.selected_completed_reference
                    != update["selected_completed_reference"]
                ):
                    raise PipelineSelectionConflict("selection changed during coordinated recovery")
                continue
            if actual != update["expected_revision"]:
                raise PipelineSelectionConflict("selection changed during coordinated recovery")
            selections._update_exact_under_transaction(
                update["recording_id"],
                update["content_type"],
                expected_revision=actual,
                selected_generated=update["selected_generated"],
                selected_completed_reference=update["selected_completed_reference"],
            )
            self.node_store._after_durable_boundary("selection")
        atomic_replace_json(path, {**record, "status": "committed"})
        self.node_store._after_durable_boundary("commit")


__all__ = ["PipelineNodeTransactions"]
