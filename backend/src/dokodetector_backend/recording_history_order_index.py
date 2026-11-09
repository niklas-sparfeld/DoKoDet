"""Persistent collection-order index for bounded, frozen history pages."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from dokodetector_backend.filesystem import atomic_replace_json, contained_path
from dokodetector_backend.recording_state_contract import (
    HistoryItem,
    LineageEdgeHistoryItem,
    ResourceHistoryItem,
    SnapshotHistoryItem,
)

_COLLECTIONS = ("snapshots", "revisions", "candidates", "lineage_edges")
_ROOT_SCHEMA = "recording-history-order-root/v1"
_NODE_SCHEMA = "recording-history-order-node/v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def stable_history_key(item: HistoryItem) -> tuple[str, ...]:
    """Return the M1 collection-specific total-order key for a history item."""
    if isinstance(item, SnapshotHistoryItem):
        return item.snapshot_id, item.item_key
    if isinstance(item, ResourceHistoryItem):
        return item.resource.kind, item.resource.resource_id, item.item_key
    if isinstance(item, LineageEdgeHistoryItem):
        return item.stable_sort_key()
    raise TypeError("unsupported history item")


class RecordingHistoryOrderIndex:
    """Immutable AVL roots address every authority sequence in one generation.

    Each publication writes content-addressed treap nodes and the sequence root before the
    RecordingHistoryAuthority advances. A cursor at sequence N therefore reads the immutable tree
    that represented exactly the first N publications, even when later keys sort before its cursor.
    """

    def __init__(self, generation_root: Path | str) -> None:
        self.root = Path(generation_root)
        self.nodes_root = contained_path(self.root, Path("history-order") / "nodes")
        self.roots_root = contained_path(self.root, Path("history-order") / "roots")

    def initialize(self) -> None:
        if self._root_path(0).exists():
            self.read_roots(0)
            return
        self._write_roots(0, {collection: None for collection in _COLLECTIONS})

    def publish(self, item: HistoryItem) -> None:
        sequence = item.publication_sequence
        if sequence < 1:
            raise ValueError("history index items require a publication sequence")
        roots = self.read_roots(sequence - 1)
        collection = self._collection(item)
        new_root = self._insert(
            roots[collection], stable_history_key(item), item.item_key, sequence
        )
        roots[collection] = new_root
        self._write_roots(sequence, roots)

    def read_roots(self, sequence: int) -> dict[str, str | None]:
        path = self._root_path(sequence)
        try:
            raw = path.read_bytes()
            value = json.loads(raw)
            if not isinstance(value, dict) or _canonical(value) != raw:
                raise ValueError("not canonical")
        except (OSError, TypeError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"invalid history order root at sequence {sequence}") from error
        payload = {key: part for key, part in value.items() if key != "sha256"}
        if (
            set(value) != {"schema_version", "sequence", "roots", "sha256"}
            or value["schema_version"] != _ROOT_SCHEMA
            or value["sequence"] != sequence
            or not isinstance(value["roots"], dict)
            or set(value["roots"]) != set(_COLLECTIONS)
            or any(
                root is not None and not self._valid_node_id(root)
                for root in value["roots"].values()
            )
            or value["sha256"] != hashlib.sha256(_canonical(payload)).hexdigest()
        ):
            raise ValueError(f"corrupt history order root at sequence {sequence}")
        return dict(value["roots"])

    def write_order_root(self, sequence: int, roots: dict[str, str | None]) -> None:
        """Create an empty root record for an authority sequence during rebuild."""
        self._write_roots(sequence, roots)

    def next_refs(
        self,
        collection: str,
        sequence: int,
        after_key: Sequence[str] | None,
        limit: int,
    ) -> tuple[list[tuple[tuple[str, ...], str, int]], bool]:
        if collection not in _COLLECTIONS:
            raise ValueError("unknown history collection")
        if not 1 <= limit <= 100:
            raise ValueError("history page bounds are invalid")
        roots = self.read_roots(sequence)
        root = roots[collection]
        refs: list[tuple[tuple[str, ...], str, int]] = []
        for node in self._ordered_after(root, None if after_key is None else tuple(after_key)):
            if node["sequence"] > sequence:
                raise ValueError("history order root contains a later publication")
            refs.append((tuple(node["key"]), node["item_key"], node["sequence"]))
            if len(refs) > limit:
                return refs[:limit], True
        return refs, False

    def contains(
        self,
        collection: str,
        sequence: int,
        key: Sequence[str],
        item_key: str,
        publication_sequence: int,
    ) -> bool:
        """Check one indexed item without scanning its collection."""
        if collection not in _COLLECTIONS:
            raise ValueError("unknown history collection")
        root = self.read_roots(sequence)[collection]
        expected = tuple(key)
        current = root
        while current is not None:
            node = self._load_node(current)
            node_key = tuple(node["key"])
            if expected == node_key:
                return node["item_key"] == item_key and node["sequence"] == publication_sequence
            current = node["left"] if expected < node_key else node["right"]
        return False

    def validate_latest(self, sequence: int) -> dict[str, list[tuple[tuple[str, ...], str, int]]]:
        """Validate every current tree and return its exact indexed entries."""
        roots = self.read_roots(sequence)
        entries: dict[str, list[tuple[tuple[str, ...], str, int]]] = {}
        for collection, root in roots.items():
            collection_entries: list[tuple[tuple[str, ...], str, int]] = []
            previous_key: tuple[str, ...] | None = None
            for node in self._ordered_after(root, None):
                key = tuple(node["key"])
                if node["sequence"] > sequence or (
                    previous_key is not None and key <= previous_key
                ):
                    raise ValueError("history order tree is inconsistent")
                collection_entries.append((key, node["item_key"], node["sequence"]))
                previous_key = key
            entries[collection] = collection_entries
        return entries

    def _write_roots(self, sequence: int, roots: dict[str, str | None]) -> None:
        if set(roots) != set(_COLLECTIONS):
            raise ValueError("history order roots have an invalid collection set")
        payload = {
            "schema_version": _ROOT_SCHEMA,
            "sequence": sequence,
            "roots": dict(roots),
        }
        document = {**payload, "sha256": hashlib.sha256(_canonical(payload)).hexdigest()}
        path = self._root_path(sequence)
        if path.exists():
            existing = self.read_roots(sequence)
            if existing != roots:
                raise ValueError("history order root already names different metadata")
            return
        atomic_replace_json(path, document)

    def _root_path(self, sequence: int) -> Path:
        return contained_path(self.roots_root, f"{sequence:020d}.json")

    def _node_path(self, node_id: str) -> Path:
        return contained_path(self.nodes_root, f"{node_id}.json")

    def _load_node(self, node_id: str) -> dict[str, Any]:
        path = self._node_path(node_id)
        try:
            raw = path.read_bytes()
            node = json.loads(raw)
            if not isinstance(node, dict) or _canonical(node) != raw:
                raise ValueError("not canonical")
        except (OSError, TypeError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise ValueError("invalid history order node") from error
        if (
            set(node)
            != {"schema_version", "key", "item_key", "sequence", "height", "left", "right"}
            or node["schema_version"] != _NODE_SCHEMA
            or not isinstance(node["key"], list)
            or not node["key"]
            or any(not isinstance(part, str) for part in node["key"])
            or not isinstance(node["item_key"], str)
            or isinstance(node["sequence"], bool)
            or not isinstance(node["sequence"], int)
            or node["sequence"] < 1
            or isinstance(node["height"], bool)
            or not isinstance(node["height"], int)
            or node["height"] < 1
            or any(
                child is not None and not self._valid_node_id(child)
                for child in (node["left"], node["right"])
            )
            or hashlib.sha256(raw).hexdigest() != node_id
        ):
            raise ValueError("corrupt history order node")
        return node

    def _save_node(
        self,
        key: tuple[str, ...],
        item_key: str,
        sequence: int,
        left: str | None,
        right: str | None,
    ) -> str:
        node = {
            "schema_version": _NODE_SCHEMA,
            "key": list(key),
            "item_key": item_key,
            "sequence": sequence,
            "height": max(self._height(left), self._height(right)) + 1,
            "left": left,
            "right": right,
        }
        raw = _canonical(node)
        node_id = hashlib.sha256(raw).hexdigest()
        path = self._node_path(node_id)
        if path.exists():
            if self._load_node(node_id) != node:
                raise ValueError("history order node digest collision")
        else:
            atomic_replace_json(path, node)
        return node_id

    def _height(self, root: str | None) -> int:
        return 0 if root is None else self._load_node(root)["height"]

    @staticmethod
    def _valid_node_id(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _collection(item: HistoryItem) -> str:
        if isinstance(item, SnapshotHistoryItem):
            return "snapshots"
        if isinstance(item, LineageEdgeHistoryItem):
            return "lineage_edges"
        if isinstance(item, ResourceHistoryItem):
            return item.collection
        raise TypeError("unsupported history item")

    def _insert(
        self,
        root: str | None,
        key: tuple[str, ...],
        item_key: str,
        sequence: int,
    ) -> str:
        if root is None:
            return self._save_node(key, item_key, sequence, None, None)
        node = self._load_node(root)
        node_key = tuple(node["key"])
        if key == node_key:
            raise ValueError("duplicate stable history key")
        if key < node_key:
            left = self._insert(node["left"], key, item_key, sequence)
            updated = self._save_node(
                node_key, node["item_key"], node["sequence"], left, node["right"]
            )
        else:
            right = self._insert(node["right"], key, item_key, sequence)
            updated = self._save_node(
                node_key, node["item_key"], node["sequence"], node["left"], right
            )
        return self._balance(updated)

    def _balance(self, root: str) -> str:
        node = self._load_node(root)
        balance = self._height(node["left"]) - self._height(node["right"])
        if balance > 1:
            left = self._load_node(node["left"])
            if self._height(left["left"]) < self._height(left["right"]):
                rotated_left = self._rotate_left(node["left"])
                root = self._save_node(
                    tuple(node["key"]),
                    node["item_key"],
                    node["sequence"],
                    rotated_left,
                    node["right"],
                )
            return self._rotate_right(root)
        if balance < -1:
            right = self._load_node(node["right"])
            if self._height(right["right"]) < self._height(right["left"]):
                rotated_right = self._rotate_right(node["right"])
                root = self._save_node(
                    tuple(node["key"]),
                    node["item_key"],
                    node["sequence"],
                    node["left"],
                    rotated_right,
                )
            return self._rotate_left(root)
        return root

    def _rotate_left(self, root: str) -> str:
        node = self._load_node(root)
        pivot = self._load_node(node["right"])
        new_left = self._save_node(
            tuple(node["key"]),
            node["item_key"],
            node["sequence"],
            node["left"],
            pivot["left"],
        )
        return self._save_node(
            tuple(pivot["key"]),
            pivot["item_key"],
            pivot["sequence"],
            new_left,
            pivot["right"],
        )

    def _rotate_right(self, root: str) -> str:
        node = self._load_node(root)
        pivot = self._load_node(node["left"])
        new_right = self._save_node(
            tuple(node["key"]),
            node["item_key"],
            node["sequence"],
            pivot["right"],
            node["right"],
        )
        return self._save_node(
            tuple(pivot["key"]),
            pivot["item_key"],
            pivot["sequence"],
            pivot["left"],
            new_right,
        )

    def _ordered_after(
        self, root: str | None, after_key: tuple[str, ...] | None
    ) -> Iterator[dict[str, Any]]:
        stack: list[dict[str, Any]] = []
        current = root
        while current is not None or stack:
            while current is not None:
                node = self._load_node(current)
                if after_key is not None and tuple(node["key"]) <= after_key:
                    current = node["right"]
                    continue
                stack.append(node)
                current = node["left"]
            if stack:
                node = stack.pop()
                yield node
                current = node["right"]


__all__ = ["RecordingHistoryOrderIndex", "stable_history_key"]
