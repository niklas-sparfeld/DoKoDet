"""Independent, revision-bound review records and conservative applicability."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from dokodetector_backend.filesystem import atomic_write_json, contained_path
from dokodetector_backend.pipeline_item_provenance import _actor, _items
from dokodetector_backend.pipeline_node_store import (
    NodeConflict,
    NodeRevision,
    PipelineNodeStore,
    _object,
    _read_json,
)
from dokodetector_backend.pipeline_storage import _canonical_timestamp, _process_lock, _safe_id


class PipelineNodeReviews:
    """Store immutable decisions outside content revisions and compute their applicability."""

    def __init__(self, store: PipelineNodeStore) -> None:
        self.store = store
        self.root = store.root / ".review-records"

    def item(
        self,
        review_id: str,
        node_id: str,
        revision_id: str,
        item_id: str,
        question: str,
        decision: str,
        reviewer: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        revision = self.store.read_published_revision(node_id, revision_id)
        _safe_id(item_id, "item_id")
        items = self._revision_items(revision)
        if item_id not in items:
            raise ValueError("reviewed item is not present in the revision")
        return self._record(
            review_id,
            "item",
            revision,
            question,
            decision,
            reviewer,
            evidence,
            {"item_id": item_id, "item_sha256": items[item_id]["sha256"]},
        )

    def items(
        self,
        node_id: str,
        revision_id: str,
        decisions: Sequence[Mapping[str, str]],
        question: str,
        reviewer: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        """Record multiple item decisions after validating the revision once.

        Each ID remains individually replay-safe if publication is interrupted.
        """
        revision = self.store.read_published_revision(node_id, revision_id)
        items = self._revision_items(revision)
        prepared = []
        for decision in decisions:
            if set(decision) != {"review_id", "item_id", "decision"}:
                raise ValueError("invalid item review decision")
            _safe_id(decision["review_id"], "review_id")
            item_id = _safe_id(decision["item_id"], "item_id")
            if item_id not in items:
                raise ValueError("reviewed item is not present in the revision")
            prepared.append((decision, items[item_id]["sha256"]))
        return tuple(
            self._record(
                decision["review_id"],
                "item",
                revision,
                question,
                decision["decision"],
                reviewer,
                evidence,
                {"item_id": decision["item_id"], "item_sha256": digest},
            )
            for decision, digest in prepared
        )

    def coverage(
        self,
        review_id: str,
        node_id: str,
        revision_id: str,
        question: str,
        coverage: Mapping[str, Any],
        reviewer: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        revision = self.store.read_published_revision(node_id, revision_id)
        scope = _object(coverage, "coverage")
        if not scope:
            raise ValueError("coverage must identify the inspected scope")
        return self._record(
            review_id, "coverage", revision, question, None, reviewer, evidence, {"coverage": scope}
        )

    def overall(
        self,
        review_id: str,
        node_id: str,
        revision_id: str,
        question: str,
        decision: str,
        reviewer: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        revision = self.store.read_published_revision(node_id, revision_id)
        return self._record(
            review_id, "overall", revision, question, decision, reviewer, evidence, {}
        )

    def _record(
        self,
        review_id: str,
        kind: str,
        revision: NodeRevision,
        question: str,
        decision: str | None,
        reviewer: Mapping[str, Any],
        evidence: Mapping[str, Any],
        details: dict[str, Any],
    ) -> dict[str, Any]:
        _safe_id(review_id, "review_id")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("review question must not be empty")
        if kind != "coverage" and (not isinstance(decision, str) or not decision.strip()):
            raise ValueError("review decision must not be empty")
        evidence_data = _object(evidence, "evidence")
        if not evidence_data.get("policy") or not (set(evidence_data) - {"policy"}):
            raise ValueError("review evidence must identify evidence and policy")
        fields = {
            "schema_version": "pipeline-review/v1",
            "review_id": review_id,
            "kind": kind,
            "node_id": revision.node_id,
            "revision_id": revision.revision_id,
            "content_sha256": revision.content_sha256,
            "question": question,
            "decision": decision,
            "reviewer": _actor(reviewer),
            "evidence": evidence_data,
            **details,
        }
        path = contained_path(self.root, f"{review_id}.json")
        with _process_lock(self.store.root / ".transactions.lock", self.store._lock):
            if path.exists():
                old = _read_json(path)
                if {k: v for k, v in old.items() if k != "reviewed_at"} != fields:
                    raise NodeConflict("review ID is already used by another decision")
                return old
            record = {**fields, "reviewed_at": _canonical_timestamp(None)}
            atomic_write_json(path, record)
            return record

    def get(self, review_id: str) -> dict[str, Any]:
        path = contained_path(self.root, f"{_safe_id(review_id, 'review_id')}.json")
        record = _read_json(path)
        if (
            record.get("review_id") != review_id
            or record.get("schema_version") != "pipeline-review/v1"
        ):
            raise ValueError("invalid review record")
        return record

    def list_for_revision(self, node_id: str, revision_id: str) -> tuple[dict[str, Any], ...]:
        self.store.read_published_revision(node_id, revision_id)
        records = self._records_for_revisions({(node_id, revision_id)})
        return tuple(
            sorted(
                records,
                key=lambda record: (record["reviewed_at"], record["review_id"]),
                reverse=True,
            )
        )

    def _records_for_revisions(self, identities: set[tuple[str, str]]) -> list[dict[str, Any]]:
        """Read only records whose canonical identity matches the requested revisions."""
        if not self.root.is_dir() or self.root.is_symlink():
            return []
        needles = {
            (f'"node_id":"{node_id}"'.encode(), f'"revision_id":"{revision_id}"'.encode())
            for node_id, revision_id in identities
        }
        records = []
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink():
                continue
            payload = path.read_bytes()
            if any(
                node_id in payload and revision_id in payload for node_id, revision_id in needles
            ):
                record = self.get(path.stem)
                if (record["node_id"], record["revision_id"]) in identities:
                    records.append(record)
        return records

    def applicable_for_revision(self, node_id: str, revision_id: str) -> tuple[dict[str, Any], ...]:
        """Return recorded decisions that still apply through exact item lineage."""
        self.store.recover_transactions()
        nodes = {}

        def read_revision(source_node_id: str, source_revision_id: str) -> NodeRevision:
            node = nodes.get(source_node_id)
            if node is None:
                node = self.store._get_unrecovered(source_node_id)
                nodes[source_node_id] = node
            return self.store._read_revision(node, source_revision_id)

        target = read_revision(node_id, revision_id)
        lineage: list[NodeRevision] = []
        current = target
        seen: set[tuple[str, str]] = set()
        while True:
            identity = (current.node_id, current.revision_id)
            if identity in seen:
                raise ValueError("copy lineage contains a cycle")
            seen.add(identity)
            lineage.append(current)
            if current.parent_revision_id is not None:
                current = read_revision(current.node_id, current.parent_revision_id)
                continue
            copied = current.metadata.get("copied_from")
            if not isinstance(copied, dict):
                break
            current = read_revision(copied["node_id"], copied["revision_id"])

        index = {(revision.node_id, revision.revision_id): i for i, revision in enumerate(lineage)}
        records = self._records_for_revisions(set(index))

        item_hashes = [self._revision_items(revision) for revision in lineage]
        applicable = []
        for record in records:
            source_index = index[(record["node_id"], record["revision_id"])]
            if record["kind"] != "item":
                if source_index == 0 and record["content_sha256"] == target.content_sha256:
                    applicable.append(record)
                continue
            item_id = record["item_id"]
            if any(
                item_hashes[i].get(item_id, {}).get("sha256") != record["item_sha256"]
                for i in range(source_index + 1)
            ):
                continue
            source_revision = lineage[source_index]
            if source_revision.content_sha256 != record["content_sha256"]:
                raise ValueError("review content digest does not match its revision")
            applicable.append(record)
        return tuple(
            sorted(
                applicable,
                key=lambda record: (record["reviewed_at"], record["review_id"]),
                reverse=True,
            )
        )

    def applicability(
        self, review_id: str, node_id: str, revision_id: str, evidence: Mapping[str, Any] | None
    ) -> dict[str, str]:
        record = self.get(review_id)
        target = self.store.read_revision(node_id, revision_id)
        if evidence is None:
            return {"status": "unknown", "reason": "current evidence is not recorded"}
        if _object(evidence, "evidence") != record["evidence"]:
            return {"status": "inapplicable", "reason": "review evidence or policy changed"}
        if record["node_id"] == node_id and record["revision_id"] == revision_id:
            if record["content_sha256"] != target.content_sha256:
                raise ValueError("review content digest does not match its revision")
            return {"status": "applicable", "reason": "exact reviewed revision and evidence"}
        if record["kind"] != "item":
            return {"status": "inapplicable", "reason": "decision is tied to its exact revision"}
        seen = set()
        current = target
        while True:
            identity = (current.node_id, current.revision_id)
            if identity in seen:
                raise ValueError("copy lineage contains a cycle")
            seen.add(identity)
            items = self._revision_items(current)
            item = items.get(record["item_id"])
            if item is None or item["sha256"] != record["item_sha256"]:
                return {"status": "inapplicable", "reason": "reviewed item changed or was deleted"}
            if identity == (record["node_id"], record["revision_id"]):
                if current.content_sha256 != record["content_sha256"]:
                    raise ValueError("review content digest does not match its revision")
                return {"status": "applicable", "reason": "unchanged item and matching evidence"}
            if current.parent_revision_id is not None:
                current = self.store.read_revision(current.node_id, current.parent_revision_id)
                continue
            copied = current.metadata.get("copied_from")
            if not isinstance(copied, dict):
                return {"status": "inapplicable", "reason": "no explicit copy or revision lineage"}
            current = self.store.read_revision(copied["node_id"], copied["revision_id"])

    @staticmethod
    def _revision_items(revision: NodeRevision) -> dict[str, Any]:
        provenance = revision.metadata.get("item_provenance")
        if provenance is None:
            item_shapes = {
                "event-data/v1": ("events", "event_id"),
                "visible-card-data/v1": ("outcomes", "event_id"),
                "visible-card-data/v2": ("outcomes", "event_id"),
                "visual-identity-data/v1": ("outcomes", "card_id"),
                "visual-identity-data/v2": ("outcomes", "card_id"),
                "virtual-scene-data/v1": ("frames", "frame_id"),
            }
            shape = item_shapes.get(revision.content.get("schema_version"))
            if shape is None:
                raise ValueError("revision has no item provenance")
            key, id_key = shape
            values = revision.content.get(key)
            if not isinstance(values, list):
                raise ValueError("revision item collection is invalid")
            pointers = {}
            for index, value in enumerate(values):
                if not isinstance(value, dict) or not isinstance(value.get(id_key), str):
                    raise ValueError("revision item identity is invalid")
                item_id = value[id_key]
                if item_id in pointers:
                    raise ValueError("revision item identities are not unique")
                pointers[item_id] = f"/{key}/{index}"
            return _items(revision.content, pointers)
        if not isinstance(provenance, dict) or not isinstance(provenance.get("items"), dict):
            raise ValueError("revision has no item provenance")
        items = provenance["items"]
        if _items(revision.content, {k: v["pointer"] for k, v in items.items()}) != items:
            raise ValueError("item provenance does not match revision content")
        return items
