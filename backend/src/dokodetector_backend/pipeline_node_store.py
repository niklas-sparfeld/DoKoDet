"""Named pipeline nodes with immutable content revisions and optimistic heads.

This foundation is independent of the existing pipeline stores. Downstream-use protection and
copy-on-edit are added in M3; callers must not use this store for production processing until then.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock, local
from typing import Any
from uuid import uuid4

from doko_operations.pipeline_data import (
    RecordingVideoSource,
    canonical_json_bytes,
    parse_event_data_bytes,
    parse_source,
    sha256_bytes,
)
from table_evidence_analyzer.pipeline_data import (
    parse_proposed_card_scene_data_bytes,
    parse_table_observation_data_bytes,
    parse_visible_card_data_bytes,
    parse_visual_identity_data_bytes,
)

from dokodetector_backend.filesystem import (
    atomic_replace_json,
    commit_staged_directory,
    contained_path,
    staging_directory,
)
from dokodetector_backend.pipeline_storage import _canonical_timestamp, _process_lock, _safe_id
from dokodetector_backend.virtual_scene_data import validate_virtual_scenes


class NodeConflict(ValueError):
    """A node already exists or its working head has changed."""


class NodeUsed(NodeConflict):
    """An accepted run protects this node from direct content edits."""


_transaction_locks_guard = RLock()
_transaction_locks: dict[Path, RLock] = {}
_transaction_lock_state = local()
_transaction_recovery_state = local()


@contextmanager
def _transaction_lock(store: "PipelineNodeStore"):
    """Take the root transaction lock once per thread, including nested store calls."""
    path = store.root / ".transactions.lock"
    with _transaction_locks_guard:
        thread_lock = _transaction_locks.setdefault(path, RLock())
    with thread_lock:
        held = getattr(_transaction_lock_state, "held", None)
        if held is None:
            held = _transaction_lock_state.held = set()
        if path in held:
            yield
            return
        held.add(path)
        try:
            with _process_lock(path, store._lock):
                yield
        finally:
            held.remove(path)


@dataclass(frozen=True)
class Node:
    node_id: str
    name: str
    content_type: str
    source: dict[str, Any]
    created_at: str
    head_revision_id: str


@dataclass(frozen=True)
class NodeRevision:
    node_id: str
    revision_id: str
    parent_revision_id: str | None
    content: dict[str, Any]
    content_sha256: str
    metadata: dict[str, Any]
    created_at: str


def _object(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    try:
        result = json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must contain valid JSON") from error
    if not isinstance(result, dict):
        raise ValueError(f"{field} must be an object")
    return result


def _content(content_type: str, source: dict[str, Any], value: Mapping[str, Any]) -> dict[str, Any]:
    data = _object(value, "content")
    raw = canonical_json_bytes(data)
    if content_type == "virtual_scenes":
        result = validate_virtual_scenes(data)
        parsed_source = parse_source(source)
        if isinstance(parsed_source, RecordingVideoSource) and any(
            frame["frame_identity"]["source_video_sha256"] != parsed_source.video_sha256
            for frame in result["frames"]
        ):
            raise ValueError("virtual scene frame does not match its source video")
        return result
    if content_type == "events":
        parsed_source = parse_source(source)
        duration = (
            parsed_source.duration_us
            if isinstance(parsed_source, RecordingVideoSource)
            else 2**63 - 1
        )
        parsed = parse_event_data_bytes(raw, duration_us=duration)
    else:
        parsers = {
            "visible_cards": parse_visible_card_data_bytes,
            "visual_identities": parse_visual_identity_data_bytes,
            "table_observations": parse_table_observation_data_bytes,
            "card_scene_proposals": parse_proposed_card_scene_data_bytes,
        }
        if content_type not in parsers:
            raise ValueError("unsupported content type")
        parsed = parsers[content_type](raw)
        if content_type == "visible_cards":
            parsed_source = parse_source(source)
            if isinstance(parsed_source, RecordingVideoSource) and any(
                outcome.frame_identity is not None
                and outcome.frame_identity.source_video_sha256 != parsed_source.video_sha256
                for outcome in parsed.outcomes
            ):
                raise ValueError("visible-card frame does not match its source video")
    return parsed.to_mapping()


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise ValueError(f"invalid canonical object: {path}")
    return value


class PipelineNodeStore:
    """Persist validated node revisions with atomic publication and compare-and-swap."""

    def __init__(self, root: Path | str, catalog_index: Any | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self._lock = RLock()
        self.catalog_index = catalog_index

    def transaction_lock(self):
        """Serialize all node and selection publication for this storage root."""
        return _transaction_lock(self)

    def recover_transactions(self) -> None:
        """Complete any prepared coordinated node/selection transaction before reads."""
        with self.transaction_lock():
            active = getattr(_transaction_recovery_state, "roots", None)
            if active is None:
                active = _transaction_recovery_state.roots = set()
            if self.root in active:
                return
            active.add(self.root)
            try:
                from dokodetector_backend.pipeline_node_transactions import PipelineNodeTransactions

                PipelineNodeTransactions(self)._recover_under_lock()
            finally:
                active.remove(self.root)

    def _node_path(self, node_id: str) -> Path:
        return contained_path(self.root, _safe_id(node_id, "node_id"))

    def revision_path(self, node_id: str, revision_id: str) -> Path:
        """Return the path to one exact immutable node revision directory."""
        return contained_path(
            self._node_path(node_id), Path("revisions") / _safe_id(revision_id, "revision_id")
        )

    def publication_path(self, node_id: str, revision_id: str) -> Path:
        """Return the durable authority directory for one published node revision."""
        return contained_path(
            self._node_path(node_id),
            Path("publications") / _safe_id(revision_id, "revision_id"),
        )

    @property
    def _history_outbox_path(self) -> Path:
        return contained_path(self.root, ".recording-history-revision-outbox.json")

    def _queue_revision_history(self, node_path: Path, revision: NodeRevision) -> None:
        """Record a recoverable history intent before a recording revision is committed."""
        manifest_path = node_path / "manifest.json"
        manifest = _read_json(manifest_path)
        recording_id = manifest.get("source", {}).get("recording_id")
        if not isinstance(recording_id, str) or not recording_id:
            return
        path = self._history_outbox_path
        entries: list[dict[str, str]] = []
        if path.exists():
            current = _read_json(path)
            if (
                set(current) != {"schema_version", "entries"}
                or current["schema_version"] != "pipeline-revision-history-outbox/v1"
                or not isinstance(current["entries"], list)
            ):
                raise ValueError("invalid pipeline revision history outbox")
            entries = current["entries"]
        entry = {
            "recording_id": recording_id,
            "node_id": revision.node_id,
            "revision_id": revision.revision_id,
            "content_sha256": revision.content_sha256,
            "schema_version": revision.content.get("schema_version"),
        }
        if not isinstance(entry["schema_version"], str) or not entry["schema_version"]:
            raise ValueError("pipeline revision has no content schema version")
        if entry not in entries:
            entries.append(entry)
        atomic_replace_json(
            path, {"schema_version": "pipeline-revision-history-outbox/v1", "entries": entries}
        )
        self._after_durable_boundary("history_outbox")

    def _reconcile_revision_history_outbox_locked(self) -> None:
        """Replay named durable revision intents while the node transaction lock is held."""
        path = self._history_outbox_path
        if not path.exists():
            return
        current = _read_json(path)
        if (
            set(current) != {"schema_version", "entries"}
            or current["schema_version"] != "pipeline-revision-history-outbox/v1"
            or not isinstance(current["entries"], list)
        ):
            raise ValueError("invalid pipeline revision history outbox")
        remaining: list[dict[str, str]] = []
        for entry in current["entries"]:
            if not isinstance(entry, dict) or set(entry) != {
                "recording_id",
                "node_id",
                "revision_id",
                "content_sha256",
                "schema_version",
            }:
                raise ValueError("invalid pipeline revision history outbox entry")
            node_path = self._node_path(entry["node_id"])
            if node_path.is_symlink():
                raise ValueError("pipeline revision history node path cannot be a symlink")
            if not node_path.exists():
                # The intent is written before a new node's staged directory is committed.
                # Absence is the only state that proves this create did not commit.
                continue
            # An existing but unreadable node is corruption. Let it fail closed and retain the
            # outbox entry for repair; do not turn source corruption into a permanent omission.
            if not node_path.is_dir():
                raise ValueError("pipeline revision history node path is not a directory")
            node = self._get_unrecovered(entry["node_id"])
            if node.source.get("recording_id") != entry["recording_id"]:
                raise ValueError("pipeline revision history recording identity mismatch")
            revision_path = self.revision_path(node.node_id, entry["revision_id"])
            publication = self.publication_path(node.node_id, entry["revision_id"])
            has_publication = publication.exists() or publication.is_symlink()
            has_head = node.head_revision_id == entry["revision_id"]
            if not revision_path.exists() or revision_path.is_symlink():
                if has_publication or has_head:
                    raise ValueError("committed pipeline revision is missing")
                continue
            if not revision_path.is_dir():
                raise ValueError("pipeline revision path is not a directory")
            revision_record = revision_path / "revision.json"
            if not revision_record.is_file() or revision_record.is_symlink():
                raise ValueError("pipeline revision record is missing or invalid")
            if has_publication:
                if publication.is_symlink() or not publication.is_dir():
                    raise ValueError("pipeline revision publication authority is invalid")
                authority = self._read_publication(node.node_id, entry["revision_id"])
                if authority["content_sha256"] != entry["content_sha256"]:
                    raise ValueError("pipeline revision history outbox digest mismatch")
            elif not has_head:
                # An uncommitted revision is not part of durable node history.
                continue
            else:
                self._publish_publication_metadata(
                    self._node_path(node.node_id),
                    node.node_id,
                    entry["revision_id"],
                    entry["content_sha256"],
                )
            from dokodetector_backend.recording_history_store import RecordingHistoryStore
            from dokodetector_backend.recording_state_contract import (
                ExactResourceRef,
                ResourceHistoryItem,
            )

            schema_version = entry["schema_version"]
            if not isinstance(schema_version, str) or not schema_version:
                raise ValueError("pipeline revision has no content schema version")
            item = ResourceHistoryItem(
                collection="revisions",
                item_key="r_"
                + hashlib.sha256(
                    f"{node.node_id}:{entry['revision_id']}".encode("utf-8")
                ).hexdigest(),
                resource=ExactResourceRef(
                    kind="pipeline-node-revision",
                    resource_id=entry["revision_id"],
                    schema_version=schema_version,
                    sha256=entry["content_sha256"],
                    node_id=node.node_id,
                    revision_id=entry["revision_id"],
                ),
                publication_sequence=1,
            )
            RecordingHistoryStore(self.root.parent).publish(entry["recording_id"], item)
            if self.catalog_index is not None:
                self.catalog_index.publish_latest(
                    source_key=f"pipeline-node:{node.node_id}",
                    recording_id=entry["recording_id"],
                    source_value={
                        "node_id": node.node_id,
                        "recording_id": entry["recording_id"],
                        "content_type": node.content_type,
                        "head_revision_id": node.head_revision_id,
                    },
                    metadata_delta={},
                    counter_delta={f"pipeline_node:{node.content_type}": 1},
                )
            self._after_durable_boundary("history_published")
        atomic_replace_json(
            path,
            {"schema_version": "pipeline-revision-history-outbox/v1", "entries": remaining},
        )
        self._after_durable_boundary("history_outbox_cleared")

    def reconcile_revision_history_outbox(self) -> None:
        """Recover node transactions, then replay the bounded pending revision outbox."""
        self.recover_transactions()
        with self.transaction_lock():
            self._reconcile_revision_history_outbox_locked()

    def _lock_path(self, node_id: str) -> Path:
        return contained_path(self.root, f".{_safe_id(node_id, 'node_id')}.lock")

    def create(
        self,
        node_id: str,
        name: str,
        content_type: str,
        source: Mapping[str, Any],
        content: Mapping[str, Any],
        metadata: Mapping[str, Any],
        *,
        revision_id: str | None = None,
    ) -> NodeRevision:
        node_path = self._node_path(node_id)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must not be empty")
        source_data = parse_source(_object(source, "source")).to_mapping()
        content_data = _content(content_type, source_data, content)
        metadata_data = _object(metadata, "metadata")
        now = _canonical_timestamp(None)
        revision = self._new_revision(node_id, None, content_data, metadata_data, now, revision_id)
        manifest = {
            "schema_version": "pipeline-node/v1",
            "node_id": node_id,
            "name": name,
            "content_type": content_type,
            "source": source_data,
            "created_at": now,
        }
        self.reconcile_revision_history_outbox()
        with self.transaction_lock(), _process_lock(self._lock_path(node_id), self._lock):
            if node_path.exists():
                raise NodeConflict("node already exists")
            with staging_directory(self.root) as staging:
                (staging / "manifest.json").write_bytes(canonical_json_bytes(manifest))
                (staging / "revisions").mkdir()
                (staging / "publications").mkdir()
                self._queue_revision_history(staging, revision)
                self._publish_revision(staging, revision)
                self._publish_publication(staging, revision)
                (staging / "head.json").write_bytes(
                    canonical_json_bytes({"revision_id": revision.revision_id})
                )
                commit_staged_directory(staging, node_path)
                self._after_durable_boundary("node_created")
                self._reconcile_revision_history_outbox_locked()
        return revision

    def get(self, node_id: str) -> Node:
        self.recover_transactions()
        return self._get_unrecovered(node_id)

    def _get_unrecovered(self, node_id: str) -> Node:
        path = self._node_path(node_id)
        manifest = _read_json(path / "manifest.json")
        if set(manifest) != {
            "schema_version",
            "node_id",
            "name",
            "content_type",
            "source",
            "created_at",
        }:
            raise ValueError("invalid node manifest")
        if manifest["schema_version"] != "pipeline-node/v1" or manifest["node_id"] != node_id:
            raise ValueError("invalid node identity")
        parse_source(manifest["source"])
        head = _read_json(path / "head.json")
        if set(head) != {"revision_id"}:
            raise ValueError("invalid head")
        _safe_id(head["revision_id"], "revision_id")
        return Node(
            node_id,
            manifest["name"],
            manifest["content_type"],
            manifest["source"],
            manifest["created_at"],
            head["revision_id"],
        )

    def list_nodes(self) -> tuple[Node, ...]:
        if not self.root.exists():
            return ()
        return tuple(
            self.get(p.name)
            for p in sorted(self.root.iterdir())
            if not p.name.startswith(".") and p.is_dir() and not p.is_symlink()
        )

    def find_revision(self, revision_id: str) -> tuple[Node, NodeRevision]:
        """Find one globally unique node revision by its exact revision ID."""
        self.recover_transactions()
        matches = []
        for node in self.list_nodes():
            try:
                revision = self.read_revision(node.node_id, revision_id)
            except (FileNotFoundError, KeyError, ValueError):
                continue
            matches.append((node, revision))
        if len(matches) != 1:
            raise FileNotFoundError(f"node revision is not unique or unavailable: {revision_id}")
        return matches[0]

    def save(
        self,
        node_id: str,
        expected_revision_id: str,
        content: Mapping[str, Any],
        metadata: Mapping[str, Any],
        *,
        revision_id: str | None = None,
    ) -> NodeRevision:
        _safe_id(expected_revision_id, "expected_revision_id")
        # Serialize recovery, transaction preparation, and ordinary saves before taking a node lock.
        with self.transaction_lock():
            self.recover_transactions()
            return self._save_under_transaction(
                node_id, expected_revision_id, content, metadata, revision_id
            )

    def _save_under_transaction(
        self,
        node_id: str,
        expected_revision_id: str,
        content: Mapping[str, Any],
        metadata: Mapping[str, Any],
        revision_id: str | None,
    ) -> NodeRevision:
        """Save under the store transaction lock, then the per-node lock."""
        with _process_lock(self._lock_path(node_id), self._lock):
            node = self._get_unrecovered(node_id)
            if node.head_revision_id != expected_revision_id:
                raise NodeConflict("working head changed")
            current = self._read_revision(node, node.head_revision_id)
            content_data = _content(node.content_type, node.source, content)
            metadata_data = _object(metadata, "metadata")
            if content_data == current.content:
                return current
            uses_root = self.root / ".accepted-uses"
            if uses_root.exists():
                for path in uses_root.glob("*.json"):
                    record = _read_json(path)
                    if any(item["node_id"] == node_id for item in record["inputs"]):
                        raise NodeUsed("accepted downstream use protects this node")
            revision = self._new_revision(
                node_id,
                current.revision_id,
                content_data,
                metadata_data,
                _canonical_timestamp(None),
                revision_id,
            )
            revision_path = self.revision_path(node_id, revision.revision_id)
            publication_path = self.publication_path(node_id, revision.revision_id)
            if any(
                path.exists() or path.is_symlink() for path in (revision_path, publication_path)
            ):
                raise NodeConflict("revision ID already exists")
            self._queue_revision_history(self._node_path(node_id), revision)
            self._publish_revision(self._node_path(node_id), revision)
            self._after_durable_boundary("revision")
            self._publish_publication(self._node_path(node_id), current)
            self._after_durable_boundary("previous_publication")
            atomic_replace_json(
                self._node_path(node_id) / "head.json", {"revision_id": revision.revision_id}
            )
            self._after_durable_boundary("head")
            self._publish_publication(self._node_path(node_id), revision)
            self._after_durable_boundary("publication")
            self._reconcile_revision_history_outbox_locked()
            return revision

    def history(self, node_id: str) -> tuple[NodeRevision, ...]:
        node = self.get(node_id)
        result = []
        seen = set()
        revision_id: str | None = node.head_revision_id
        while revision_id is not None:
            if revision_id in seen:
                raise ValueError("revision history contains a cycle")
            seen.add(revision_id)
            revision = self._read_revision(node, revision_id)
            result.append(revision)
            revision_id = revision.parent_revision_id
        return tuple(result)

    def read_revision(self, node_id: str, revision_id: str) -> NodeRevision:
        """Read an exact revision only when the current node head publishes it."""
        return self.read_published_revision(node_id, revision_id)

    def read_published_revision(self, node_id: str, revision_id: str) -> NodeRevision:
        """Verify one revision is reachable from the current head without listing history."""
        _safe_id(revision_id, "revision_id")
        node = self.get(node_id)
        current_id: str | None = node.head_revision_id
        seen: set[str] = set()
        while current_id is not None:
            if current_id == revision_id:
                return self._read_revision(node, revision_id)
            if current_id in seen:
                raise ValueError("revision history contains a cycle")
            seen.add(current_id)
            current_id = self._read_revision(node, current_id).parent_revision_id
        raise KeyError(revision_id)

    def read_authorized_revision(self, node_id: str, revision_id: str) -> NodeRevision:
        """Read one revision from its durable authority record without parent traversal."""
        _safe_id(revision_id, "revision_id")
        # Keep recovery and the exact read in one root-lock interval. Otherwise a coordinated
        # writer can publish between them and expose one member of a partially applied journal.
        with self.transaction_lock():
            self.recover_transactions()
            with _process_lock(self._lock_path(node_id), self._lock):
                node = self._get_unrecovered(node_id)
                publication_path = self.publication_path(node_id, revision_id)
                authority = None
                if publication_path.exists():
                    authority = self._read_publication(node_id, revision_id)
                elif node.head_revision_id != revision_id:
                    raise KeyError(revision_id)
                revision = self._read_revision(node, revision_id)
                if authority is not None and authority["content_sha256"] != revision.content_sha256:
                    raise ValueError("publication authority content digest mismatch")
                return revision

    def read_revision_record(self, node_id: str, revision_id: str) -> NodeRevision:
        """Read one exact revision that the current head publishes."""
        return self.read_published_revision(node_id, revision_id)

    def _read_unpublished_revision_record(self, node_id: str, revision_id: str) -> NodeRevision:
        """Read one raw record for idempotent orphan recovery only."""
        _safe_id(revision_id, "revision_id")
        if not self.has_revision(node_id, revision_id):
            raise KeyError(revision_id)
        node = self.get(node_id)
        return self._read_revision(node, revision_id)

    def has_revision(self, node_id: str, revision_id: str) -> bool:
        """Check whether one revision record exists without loading its content."""
        _safe_id(revision_id, "revision_id")
        path = contained_path(
            self._node_path(node_id), Path("revisions") / revision_id / "revision.json"
        )
        return path.is_file() and not path.is_symlink()

    @staticmethod
    def _new_revision(
        node_id: str,
        parent: str | None,
        content: dict[str, Any],
        metadata: dict[str, Any],
        now: str,
        revision_id: str | None = None,
    ) -> NodeRevision:
        if revision_id is not None:
            _safe_id(revision_id, "revision_id")
        return NodeRevision(
            node_id,
            revision_id or str(uuid4()),
            parent,
            content,
            sha256_bytes(canonical_json_bytes(content)),
            metadata,
            now,
        )

    @staticmethod
    def _publish_revision(node_path: Path, revision: NodeRevision) -> None:
        root = node_path / "revisions"
        with staging_directory(root) as staging:
            payload = {"schema_version": "pipeline-node-revision/v1", **revision.__dict__}
            (staging / "revision.json").write_bytes(canonical_json_bytes(payload))
            commit_staged_directory(staging, root / revision.revision_id)

    @staticmethod
    def _publication_record(revision: NodeRevision) -> dict[str, str]:
        return {
            "schema_version": "pipeline-node-publication/v1",
            "node_id": revision.node_id,
            "revision_id": revision.revision_id,
            "content_sha256": revision.content_sha256,
        }

    @classmethod
    def _publish_publication(cls, node_path: Path, revision: NodeRevision) -> None:
        cls._publish_publication_metadata(
            node_path, revision.node_id, revision.revision_id, revision.content_sha256
        )

    @classmethod
    def _publish_publication_metadata(
        cls, node_path: Path, node_id: str, revision_id: str, content_sha256: str
    ) -> None:
        root = node_path / "publications"
        root.mkdir(parents=True, exist_ok=True)
        destination = root / revision_id
        expected = {
            "schema_version": "pipeline-node-publication/v1",
            "node_id": node_id,
            "revision_id": revision_id,
            "content_sha256": content_sha256,
        }
        if destination.exists():
            actual = _read_json(destination / "authority.json")
            if actual != expected:
                raise ValueError("publication authority conflicts with revision")
            return
        with staging_directory(root) as staging:
            (staging / "authority.json").write_bytes(canonical_json_bytes(expected))
            try:
                commit_staged_directory(staging, destination)
            except FileExistsError:
                actual = _read_json(destination / "authority.json")
                if actual != expected:
                    raise ValueError("publication authority conflicts with revision") from None

    def _read_publication(self, node_id: str, revision_id: str) -> dict[str, str]:
        path = self.publication_path(node_id, revision_id)
        try:
            if path.is_symlink() or {item.name for item in path.iterdir()} != {"authority.json"}:
                raise ValueError("unexpected files in publication authority")
            authority = _read_json(path / "authority.json")
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            raise ValueError("invalid publication authority") from error
        if set(authority) != {"schema_version", "node_id", "revision_id", "content_sha256"}:
            raise ValueError("invalid publication authority")
        if (
            authority["schema_version"] != "pipeline-node-publication/v1"
            or authority["node_id"] != node_id
            or authority["revision_id"] != revision_id
            or not isinstance(authority["content_sha256"], str)
        ):
            raise ValueError("publication authority identity mismatch")
        return authority

    def _after_durable_boundary(self, boundary: str) -> None:
        """Hook for deterministic process-death tests at node publication boundaries."""

    def _read_revision(self, node: Node, revision_id: str) -> NodeRevision:
        _safe_id(revision_id, "revision_id")
        path = contained_path(
            self._node_path(node.node_id), Path("revisions") / revision_id / "revision.json"
        )
        if {item.name for item in path.parent.iterdir()} != {"revision.json"}:
            raise ValueError("node revision directory contains unexpected files")
        raw = _read_json(path)
        if set(raw) != {
            "schema_version",
            "node_id",
            "revision_id",
            "parent_revision_id",
            "content",
            "content_sha256",
            "metadata",
            "created_at",
        }:
            raise ValueError("invalid revision manifest")
        if raw.pop("schema_version") != "pipeline-node-revision/v1":
            raise ValueError("unsupported revision schema")
        revision = NodeRevision(**raw)
        if revision.node_id != node.node_id or revision.revision_id != revision_id:
            raise ValueError("revision identity mismatch")
        if revision.parent_revision_id is not None:
            _safe_id(revision.parent_revision_id, "parent_revision_id")
        if _content(node.content_type, node.source, revision.content) != revision.content:
            raise ValueError("revision content is not canonical")
        if sha256_bytes(canonical_json_bytes(revision.content)) != revision.content_sha256:
            raise ValueError("revision content digest mismatch")
        _object(revision.metadata, "metadata")
        return revision
