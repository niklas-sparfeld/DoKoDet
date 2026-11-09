"""Idempotent, protected node edits and copies for the lineage foundation."""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from doko_operations.pipeline_data import canonical_json_bytes, sha256_bytes

from dokodetector_backend.filesystem import atomic_write_json, contained_path
from dokodetector_backend.pipeline_item_provenance import (
    ItemProvenanceService,
    _actor,
    _items,
)
from dokodetector_backend.pipeline_node_store import (
    NodeConflict,
    PipelineNodeStore,
    _content,
    _object,
    _read_json,
)
from dokodetector_backend.pipeline_storage import _canonical_timestamp, _safe_id

_NAMESPACE = UUID("2fc4e4a7-0d82-55a9-912a-c17d9b2f2f6a")


class PipelineNodeEdits:
    """Publish a complete revision or copy under the accepted-use transaction lock."""

    def __init__(self, store: PipelineNodeStore) -> None:
        self.store = store

    def edit(
        self,
        node_id: str,
        expected_revision_id: str,
        content: Mapping[str, Any],
        key: str,
        actor: Mapping[str, Any],
        *,
        pointers: Mapping[str, str] | None = None,
        base_pointers: Mapping[str, str] | None = None,
        operations: Sequence[Mapping[str, Any]] = (),
        evidence: Any = None,
    ) -> dict[str, Any]:
        return self._execute(
            "edit",
            node_id,
            expected_revision_id,
            key,
            actor,
            content=content,
            pointers=pointers,
            base_pointers=base_pointers,
            operations=operations,
            evidence=evidence,
        )

    def copy(
        self,
        node_id: str,
        revision_id: str,
        key: str,
        actor: Mapping[str, Any],
        *,
        reason: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        return self._execute(
            "copy", node_id, revision_id, key, actor, reason=reason, copy_name=name
        )

    def restore(
        self,
        node_id: str,
        expected_revision_id: str,
        historical_revision_id: str,
        key: str,
        actor: Mapping[str, Any],
        *,
        pointers: Mapping[str, str] | None = None,
        base_pointers: Mapping[str, str] | None = None,
        operations: Sequence[Mapping[str, Any]] = (),
        evidence: Any = None,
    ) -> dict[str, Any]:
        return self._execute(
            "restore",
            node_id,
            expected_revision_id,
            key,
            actor,
            historical_revision_id=historical_revision_id,
            pointers=pointers,
            base_pointers=base_pointers,
            operations=operations,
            evidence=evidence,
        )

    def _execute(
        self,
        kind: str,
        node_id: str,
        expected: str,
        key: str,
        actor: Mapping[str, Any],
        *,
        content: Mapping[str, Any] | None = None,
        historical_revision_id: str | None = None,
        pointers: Mapping[str, str] | None = None,
        base_pointers: Mapping[str, str] | None = None,
        operations: Sequence[Mapping[str, Any]] = (),
        evidence: Any = None,
        reason: str | None = None,
        copy_name: str | None = None,
    ) -> dict[str, Any]:
        _safe_id(node_id, "node_id")
        _safe_id(expected, "revision_id")
        _safe_id(key, "idempotency key")
        who = _actor(actor)
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError("reason must be nonempty when supplied")
        request = _object(
            {
                "kind": kind,
                "node_id": node_id,
                "expected": expected,
                "content": content,
                "historical_revision_id": historical_revision_id,
                "pointers": pointers,
                "base_pointers": base_pointers,
                "operations": list(operations),
                "actor": who,
                "evidence": evidence,
                "reason": reason,
                "copy_name": copy_name,
            },
            "request",
        )
        digest = sha256_bytes(canonical_json_bytes(request))
        token = str(uuid5(_NAMESPACE, key))
        output_node_id = f"copy-{token}"
        output_revision_id = str(uuid5(_NAMESPACE, f"revision:{key}"))
        journal = contained_path(self.store.root / ".edit-journal", f"{token}.json")
        with self.store.transaction_lock():
            previous = _read_json(journal) if journal.exists() else None
            if previous is not None and (previous["key"] != key or previous["digest"] != digest):
                raise NodeConflict("idempotency key is already bound to a different request")
            if previous is not None and previous.get("result") is not None:
                return previous["result"]
            recovered = self._recover(node_id, output_node_id, output_revision_id, digest)
            if recovered is not None:
                self._journal(journal, key, digest, recovered)
                return recovered
            self._remove_uncommitted_revision(node_id, output_revision_id, digest)
            node = self.store.get(node_id)
            current = self.store.read_published_revision(node_id, expected)
            if kind != "copy" and node.head_revision_id != expected:
                raise NodeConflict("working head changed")
            if kind == "restore":
                if historical_revision_id is None:
                    raise ValueError("historical revision is required")
                target_content = self.store.read_published_revision(
                    node_id, historical_revision_id
                ).content
            elif kind == "copy":
                target_content = current.content
            else:
                target_content = _object(content, "content")
            target_content = _content(node.content_type, node.source, target_content)
            used = self._is_used(node_id)
            copied = kind == "copy" or (used and target_content != current.content)
            destination = output_node_id if copied else node_id
            if kind != "copy" and target_content == current.content:
                result = {
                    "node_id": node_id,
                    "revision_id": expected,
                    "copied": False,
                    "reason": "no_change",
                }
                self._journal(journal, key, digest, result)
                return result
            metadata = dict(current.metadata)
            metadata.pop("_edit_operation", None)
            if target_content != current.content and "item_provenance" in metadata:
                if pointers is None:
                    raise ValueError("item provenance requires pointers and operations")
                metadata.update(
                    ItemProvenanceService(self.store).prepare_change(
                        current,
                        destination,
                        output_revision_id,
                        target_content,
                        pointers,
                        operations,
                        who,
                        evidence=evidence,
                    )
                )
            elif target_content != current.content and pointers is not None:
                if base_pointers is None:
                    raise ValueError("initial item provenance requires base pointers")
                metadata["item_provenance"] = {
                    "version": 1,
                    "items": _items(current.content, base_pointers),
                    "changes": [],
                }
                current = replace(current, metadata=metadata)
                metadata.update(
                    ItemProvenanceService(self.store).prepare_change(
                        current,
                        destination,
                        output_revision_id,
                        target_content,
                        pointers,
                        operations,
                        who,
                        evidence=evidence,
                    )
                )
            elif pointers is not None or operations:
                raise ValueError("item operations require tracked provenance and changed content")
            if kind == "restore":
                metadata["restored_from"] = {
                    "node_id": node_id,
                    "revision_id": historical_revision_id,
                    "actor": who,
                    "time": _canonical_timestamp(None),
                }
            copy_reason = "explicit_copy" if kind == "copy" else "downstream_use"
            if copied:
                metadata["copied_from"] = {
                    "node_id": node_id,
                    "revision_id": expected,
                    "actor": who,
                    "time": _canonical_timestamp(None),
                    "reason": reason if kind == "copy" else "downstream_use",
                }
            result = {
                "node_id": destination,
                "revision_id": output_revision_id,
                "copied": copied,
                "reason": copy_reason if copied else kind,
            }
            metadata["_edit_operation"] = {"key": key, "digest": digest, "result": result}
            self._journal(journal, key, digest, None)
            if copied:
                name = copy_name or self._copy_name(node.name)
                self.store.create(
                    destination,
                    name,
                    node.content_type,
                    node.source,
                    target_content,
                    metadata,
                    revision_id=output_revision_id,
                )
            else:
                self.store.recover_transactions()
                self.store._save_under_transaction(
                    node_id, expected, target_content, metadata, output_revision_id
                )
            self._journal(journal, key, digest, result)
            return result

    def _copy_name(self, source_name: str) -> str:
        # Node IDs provide identity. Names are labels and do not require a full catalog scan.
        return f"{source_name} copy"

    def _remove_uncommitted_revision(self, node_id: str, revision_id: str, digest: str) -> None:
        path = self.store._node_path(node_id) / "revisions" / revision_id
        if not path.exists():
            return
        record = _read_json(path / "revision.json")
        operation = record.get("metadata", {}).get("_edit_operation", {})
        if operation.get("digest") != digest:
            raise NodeConflict("uncommitted revision conflicts with existing data")
        if self._revision_has_dependents(node_id, revision_id):
            raise NodeConflict("unpublished revision has review or accepted-use records")
        # The caller checked exact HEAD reachability under the transaction lock first.
        shutil.rmtree(path)

    def _revision_has_dependents(self, node_id: str, revision_id: str) -> bool:
        uses_root = self.store.root / ".accepted-uses"
        if uses_root.exists():
            for path in uses_root.glob("*.json"):
                if any(
                    item["node_id"] == node_id and item["revision_id"] == revision_id
                    for item in _read_json(path)["inputs"]
                ):
                    return True
        reviews_root = self.store.root / ".review-records"
        if reviews_root.exists():
            for path in reviews_root.glob("*.json"):
                record = _read_json(path)
                if record.get("node_id") == node_id and record.get("revision_id") == revision_id:
                    return True
        return False

    def _is_used(self, node_id: str) -> bool:
        root = self.store.root / ".accepted-uses"
        return root.exists() and any(
            item["node_id"] == node_id
            for path in root.glob("*.json")
            for item in _read_json(path)["inputs"]
        )

    def _recover(
        self, node_id: str, copy_id: str, revision_id: str, digest: str
    ) -> dict[str, Any] | None:
        for candidate in (node_id, copy_id):
            if not self.store._node_path(candidate).exists():
                continue
            if not self.store.has_revision(candidate, revision_id):
                continue
            revision = self.store._read_unpublished_revision_record(candidate, revision_id)
            operation = revision.metadata.get("_edit_operation")
            if not isinstance(operation, dict) or operation.get("digest") != digest:
                raise NodeConflict("operation revision conflicts with existing data")
            try:
                self.store.read_published_revision(candidate, revision_id)
            except KeyError:
                continue
            else:
                return operation["result"]
        return None

    @staticmethod
    def _journal(path: Path, key: str, digest: str, result: dict[str, Any] | None) -> None:
        atomic_write_json(
            path,
            {
                "schema_version": "pipeline-edit-journal/v1",
                "key": key,
                "digest": digest,
                "result": result,
            },
        )
