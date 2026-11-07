"""Revision-bound item provenance for the pipeline node foundation.

Item keys are editing identities scoped to a node, not physical-card identities. Callers provide
JSON pointers and explicit operations; this module does not infer correspondence between frames.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from doko_operations.pipeline_data import canonical_json_bytes, sha256_bytes

from dokodetector_backend.pipeline_node_store import NodeRevision, PipelineNodeStore, _object
from dokodetector_backend.pipeline_storage import _canonical_timestamp, _safe_id

_KEY = "item_provenance"


def _actor(value: Mapping[str, Any]) -> dict[str, Any]:
    actor = _object(value, "actor")
    if set(actor) != {"kind", "id"} or actor["kind"] not in {"human", "processor", "not_recorded"}:
        raise ValueError("actor must identify a human, processor, or not_recorded")
    if actor["kind"] == "not_recorded":
        if actor["id"] is not None:
            raise ValueError("not_recorded actor must not have an ID")
    else:
        _safe_id(actor["id"], "actor ID")
    return actor


def _resolve(content: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("item pointer must be a JSON pointer")
    value = content
    for token in pointer[1:].split("/"):
        if "~" in token:
            import re

            if re.search(r"~(?![01])", token):
                raise ValueError("invalid JSON pointer escape")
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif (
            isinstance(value, list)
            and token.isascii()
            and token.isdigit()
            and str(int(token)) == token
        ):
            index = int(token)
            if index >= len(value):
                raise ValueError("item pointer is out of range")
            value = value[index]
        else:
            raise ValueError("item pointer does not resolve")
    return value


def _items(content: Mapping[str, Any], pointers: Mapping[str, str]) -> dict[str, dict[str, str]]:
    if not isinstance(pointers, Mapping):
        raise ValueError("items must be an object")
    result = {}
    for item_id, pointer in sorted(pointers.items()):
        _safe_id(item_id, "item ID")
        value = _resolve(content, pointer)
        result[item_id] = {"pointer": pointer, "sha256": sha256_bytes(canonical_json_bytes(value))}
    if len({item["pointer"] for item in result.values()}) != len(result):
        raise ValueError("item pointers must be unique")
    return result


def _change(
    kind: str,
    before: dict[str, Any],
    after: dict[str, Any],
    actor: dict[str, Any],
    timestamp: str,
    evidence: Any,
    before_revision: dict[str, str] | None,
    after_revision: dict[str, str] | None,
) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "kind": kind,
        "before": before,
        "after": after,
        "actor": actor,
        "time": timestamp,
        "evidence": evidence,
        "before_revision": before_revision,
        "after_revision": after_revision,
    }


class ItemProvenanceService:
    """Record explicit item operations atomically with a node content revision."""

    def __init__(self, store: PipelineNodeStore) -> None:
        self.store = store

    def create(
        self,
        node_id: str,
        name: str,
        content_type: str,
        source: Mapping[str, Any],
        content: Mapping[str, Any],
        pointers: Mapping[str, str],
        actor: Mapping[str, Any],
        *,
        evidence: Any = None,
    ) -> NodeRevision:
        content_data = _object(content, "content")
        items = _items(content_data, pointers)
        who = _actor(actor)
        evidence = _object({"value": evidence}, "evidence")["value"]
        now = _canonical_timestamp(None)
        revision_id = str(uuid4())
        after_revision = {"node_id": node_id, "revision_id": revision_id}
        changes = [
            _change("insert", {}, {key: value}, who, now, evidence, None, after_revision)
            for key, value in items.items()
        ]
        return self.store.create(
            node_id,
            name,
            content_type,
            source,
            content_data,
            {_KEY: {"version": 1, "items": items, "changes": changes}},
            revision_id=revision_id,
        )

    def save(
        self,
        node_id: str,
        expected_revision_id: str,
        content: Mapping[str, Any],
        pointers: Mapping[str, str],
        operations: Sequence[Mapping[str, Any]],
        actor: Mapping[str, Any],
        *,
        evidence: Any = None,
    ) -> NodeRevision:
        current = self.store.read_revision(node_id, expected_revision_id)
        revision_id = str(uuid4())
        metadata = self.prepare_change(
            current, node_id, revision_id, content, pointers, operations, actor, evidence=evidence
        )
        return self.store.save(
            node_id, expected_revision_id, content, metadata, revision_id=revision_id
        )

    def prepare_change(
        self,
        current: NodeRevision,
        target_node_id: str,
        revision_id: str,
        content: Mapping[str, Any],
        pointers: Mapping[str, str],
        operations: Sequence[Mapping[str, Any]],
        actor: Mapping[str, Any],
        *,
        evidence: Any = None,
    ) -> dict[str, Any]:
        """Validate explicit changes before a revision or copy is published."""
        provenance = _object(current.metadata.get(_KEY), "item provenance")
        if set(provenance) != {"version", "items", "changes"} or provenance["version"] != 1:
            raise ValueError("invalid item provenance")
        old = provenance["items"]
        if not isinstance(old, dict) or not isinstance(provenance["changes"], list):
            raise ValueError("invalid item provenance")
        if _items(current.content, {k: v["pointer"] for k, v in old.items()}) != old:
            raise ValueError("stored item evidence does not match content")
        content_data = _object(content, "content")
        new = _items(content_data, pointers)
        who = _actor(actor)
        evidence = _object({"value": evidence}, "evidence")["value"]
        remaining_old = {k for k in old if k not in new or old[k]["sha256"] != new[k]["sha256"]}
        remaining_new = {k for k in new if k not in old or old[k]["sha256"] != new[k]["sha256"]}
        now = _canonical_timestamp(None)
        changes = list(provenance["changes"])
        before_revision = {"node_id": current.node_id, "revision_id": current.revision_id}
        after_revision = {"node_id": target_node_id, "revision_id": revision_id}
        for operation in operations:
            op = _object(operation, "operation")
            if set(op) != {"kind", "before", "after"}:
                raise ValueError("invalid item operation")
            kind, before, after = op["kind"], op["before"], op["after"]
            if not isinstance(before, list) or not isinstance(after, list):
                raise ValueError("operation references must be lists")
            if len(set(before)) != len(before) or len(set(after)) != len(after):
                raise ValueError("duplicate operation reference")
            shape = (len(before), len(after))
            if not (
                (kind == "insert" and shape == (0, 1))
                or (kind == "delete" and shape == (1, 0))
                or (kind == "replace" and shape == (1, 1))
                or (kind == "split" and shape[0] == 1 and shape[1] >= 2)
                or (kind == "merge" and shape[0] >= 2 and shape[1] == 1)
            ):
                raise ValueError("invalid operation shape")
            if not set(before) <= remaining_old or not set(after) <= remaining_new:
                raise ValueError("operation references unchanged, unknown, or already used items")
            changes.append(
                _change(
                    kind,
                    {k: old[k] for k in before},
                    {k: new[k] for k in after},
                    who,
                    now,
                    evidence,
                    before_revision if before else None,
                    after_revision if after else None,
                )
            )
            remaining_old.difference_update(before)
            remaining_new.difference_update(after)
        if remaining_old or remaining_new:
            raise ValueError("operations must account for each changed item")
        return {_KEY: {"version": 1, "items": new, "changes": changes}}

    def copy_unchanged(
        self,
        node_id: str,
        name: str,
        source_node_id: str,
        source_revision_id: str,
        actor: Mapping[str, Any],
        *,
        reason: str | None = None,
    ) -> NodeRevision:
        who = _actor(actor)
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError("copy reason must be nonempty when supplied")
        source_node = self.store.get(source_node_id)
        revision = self.store.read_revision(source_node_id, source_revision_id)
        provenance = _object(revision.metadata.get(_KEY), "item provenance")
        if (
            provenance.get("version") != 1
            or _items(revision.content, {k: v["pointer"] for k, v in provenance["items"].items()})
            != provenance["items"]
        ):
            raise ValueError("source provenance does not match content")
        return self.store.create(
            node_id,
            name,
            source_node.content_type,
            source_node.source,
            revision.content,
            {
                _KEY: provenance,
                "copied_from": {
                    "node_id": source_node_id,
                    "revision_id": source_revision_id,
                    "actor": who,
                    "time": _canonical_timestamp(None),
                    "reason": reason,
                },
            },
        )
