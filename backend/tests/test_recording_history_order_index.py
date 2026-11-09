from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dokodetector_backend.recording_history_order_index import (
    RecordingHistoryOrderIndex,
    stable_history_key,
)
from dokodetector_backend.recording_history_store import (
    RecordingHistoryCorrupt,
    RecordingHistoryStore,
)
from dokodetector_backend.recording_state_contract import (
    ExactResourceRef,
    LineageEdgeHistoryItem,
    LineageEndpoint,
    ResourceHistoryItem,
    SnapshotHistoryItem,
)

_DIGEST = hashlib.sha256(b"ordered history").hexdigest()


def _snapshot(item_key: str, snapshot_byte: str) -> SnapshotHistoryItem:
    return SnapshotHistoryItem(
        item_key=item_key,
        snapshot_id="rs_" + snapshot_byte * 64,
        sha256=_DIGEST,
        publication_sequence=1,
    )


def _edge(item_key: str, edge_kind: str, role: str) -> LineageEdgeHistoryItem:
    return LineageEdgeHistoryItem(
        item_key=item_key,
        edge_kind=edge_kind,
        source=LineageEndpoint(kind="revision", node_id="node-1", revision_id="rev-1"),
        target=LineageEndpoint(
            kind="artifact",
            artifact_id="evidence-package/package-1",
            sha256=_DIGEST,
        ),
        role=role,
        publication_sequence=1,
    )


def _resource(
    item_key: str, resource_id: str, collection: str = "revisions"
) -> ResourceHistoryItem:
    return ResourceHistoryItem(
        collection=collection,
        item_key=item_key,
        resource=ExactResourceRef(
            kind="pipeline-node-revision",
            resource_id=resource_id,
            schema_version="pipeline-node-revision/v1",
            sha256=_DIGEST,
            node_id="node-1",
            revision_id=resource_id,
        ),
        publication_sequence=1,
    )


def test_ordered_index_uses_stable_keys_and_freezes_membership(tmp_path: Path):
    store = RecordingHistoryStore(tmp_path)
    store.publish("recording-1", _snapshot("snapshot-z", "f"))
    store.publish("recording-1", _snapshot("snapshot-a", "1"))
    store.publish("recording-1", _snapshot("snapshot-m", "8"))
    authority = store.get_authority("recording-1")

    _, first, has_more = store.ordered_page(
        "recording-1", "snapshots", upper_bound_sequence=authority.sequence, limit=1
    )
    assert [item.snapshot_id for item in first] == ["rs_" + "1" * 64]
    assert has_more

    store.publish("recording-1", _snapshot("snapshot-earlier", "0"))
    _, second, has_more = store.ordered_page(
        "recording-1",
        "snapshots",
        upper_bound_sequence=authority.sequence,
        history_generation=authority.generation,
        after_key=stable_history_key(first[-1]),
        limit=2,
    )
    assert [item.snapshot_id for item in second] == ["rs_" + "8" * 64, "rs_" + "f" * 64]
    assert not has_more


def test_lineage_order_continues_on_full_composite_key(tmp_path: Path):
    store = RecordingHistoryStore(tmp_path)
    items = [
        _edge("edge-copied", "copied", "source"),
        _edge("edge-used-z", "used", "z-role"),
        _edge("edge-used-a", "used", "a-role"),
    ]
    for item in items:
        store.publish("recording-1", item)
    authority = store.get_authority("recording-1")
    expected = sorted(items, key=stable_history_key)

    after_key = None
    traversed = []
    for _ in range(len(items)):
        _, page, has_more = store.ordered_page(
            "recording-1",
            "lineage_edges",
            upper_bound_sequence=authority.sequence,
            history_generation=authority.generation,
            after_key=after_key,
            limit=1,
        )
        assert len(page) == 1
        traversed.extend(page)
        after_key = stable_history_key(page[-1])
        assert has_more == (len(traversed) < len(items))

    assert [stable_history_key(item) for item in traversed] == [
        stable_history_key(item) for item in expected
    ]
    assert traversed[0].target.artifact_id == "evidence-package/package-1"


def test_revision_and_candidate_indexes_sort_by_exact_resource_identity(tmp_path: Path):
    store = RecordingHistoryStore(tmp_path)
    store.publish("recording-1", _resource("revision-z", "rev-z"))
    store.publish("recording-1", _resource("revision-a", "rev-a"))
    store.publish("recording-1", _resource("candidate-z", "candidate-z", "candidates"))
    store.publish("recording-1", _resource("candidate-a", "candidate-a", "candidates"))
    authority = store.get_authority("recording-1")

    _, revisions, _ = store.ordered_page(
        "recording-1", "revisions", upper_bound_sequence=authority.sequence, limit=10
    )
    _, candidates, _ = store.ordered_page(
        "recording-1", "candidates", upper_bound_sequence=authority.sequence, limit=10
    )
    assert [item.resource.resource_id for item in revisions] == ["rev-a", "rev-z"]
    assert [item.resource.resource_id for item in candidates] == ["candidate-a", "candidate-z"]


def test_ordered_page_rejects_a_missing_index_node(tmp_path: Path):
    store = RecordingHistoryStore(tmp_path)
    store.publish("recording-1", _snapshot("snapshot-1", "1"))
    authority = store.get_authority("recording-1")
    generation_root = store.root / "recording-1" / "generations" / authority.generation
    root_id = RecordingHistoryOrderIndex(generation_root).read_roots(1)["snapshots"]
    assert root_id is not None
    (generation_root / "history-order" / "nodes" / f"{root_id}.json").unlink()

    with pytest.raises(RecordingHistoryCorrupt):
        store.ordered_page("recording-1", "snapshots", upper_bound_sequence=1, limit=1)


def test_ordered_page_reads_only_tree_path_and_returned_item_metadata(tmp_path, monkeypatch):
    store = RecordingHistoryStore(tmp_path)
    for index in range(256):
        store.publish("recording-1", _resource(f"revision-{index:04}", f"rev-{index:04}"))
    authority = store.get_authority("recording-1")

    node_reads = 0
    item_reads = 0
    original_load_node = RecordingHistoryOrderIndex._load_node
    original_read_item = store._read_history_item

    def count_node_reads(index, node_id):
        nonlocal node_reads
        node_reads += 1
        return original_load_node(index, node_id)

    def count_item_reads(*args, **kwargs):
        nonlocal item_reads
        item_reads += 1
        return original_read_item(*args, **kwargs)

    monkeypatch.setattr(
        "dokodetector_backend.recording_history_order_index.RecordingHistoryOrderIndex._load_node",
        count_node_reads,
    )
    monkeypatch.setattr(store, "_read_history_item", count_item_reads)
    _, items, _ = store.ordered_page(
        "recording-1", "revisions", upper_bound_sequence=authority.sequence, limit=4
    )
    assert len(items) == 4
    assert item_reads == 4
    assert node_reads < 40
