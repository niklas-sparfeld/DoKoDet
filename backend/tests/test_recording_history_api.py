"""HTTP contract tests for bounded recording history pages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.recording_history_store import RecordingHistoryStore
from dokodetector_backend.recording_state_contract import (
    HistoryPageCursor,
    LineageEdgeHistoryItem,
    LineageEndpoint,
    ResourceHistoryItem,
    SnapshotHistoryItem,
)

RECORDING = "history-api-recording"
DIGEST = "a" * 64


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        repository_root=Path(__file__).parents[2],
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "operations",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "packages",
        pending_video_root=tmp_path / "incoming",
        frontend_dist=tmp_path / "frontend",
    )


def _snapshot(key: str) -> SnapshotHistoryItem:
    return SnapshotHistoryItem(
        item_key=f"snapshot-entry-{key}",
        snapshot_id=f"rs_{key * 64}",
        sha256=DIGEST,
        publication_sequence=1,
    )


def _revision(key: str) -> ResourceHistoryItem:
    return ResourceHistoryItem(
        collection="revisions",
        item_key=f"revision-entry-{key}",
        resource={
            "kind": "pipeline-node-revision",
            "resource_id": key,
            "revision_id": key,
            "node_id": "node-" + key,
            "schema_version": "event-data/v1",
            "sha256": DIGEST,
        },
        publication_sequence=1,
    )


def _edge(key: str, edge_kind: str = "used") -> LineageEdgeHistoryItem:
    return LineageEdgeHistoryItem(
        item_key=key,
        edge_kind=edge_kind,
        source=LineageEndpoint(kind="run", run_id="run-1"),
        target=LineageEndpoint(kind="run", run_id="run-2"),
        role="input",
        publication_sequence=1,
    )


def test_history_pages_freeze_membership_and_continue_after_restart(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    store: RecordingHistoryStore = app.state.recording_history_store
    for key in ("b", "c", "d"):
        store.publish(RECORDING, _snapshot(key))
    client = TestClient(app)
    first = client.get(f"/api/recordings/{RECORDING}/state/history", params={"limit": 2})
    assert first.status_code == 200
    first_page = first.json()
    assert [item["snapshot_id"] for item in first_page["items"]] == [
        f"rs_{'b' * 64}",
        f"rs_{'c' * 64}",
    ]
    cursor = first_page["next_cursor"]
    assert cursor

    # This key sorts before the cursor but is outside the frozen publication sequence.
    store.publish(RECORDING, _snapshot("a"))
    restarted = TestClient(create_app(_settings(tmp_path)))
    second = restarted.get(
        f"/api/recordings/{RECORDING}/state/history", params={"limit": 2, "cursor": cursor}
    )
    assert second.status_code == 200
    page = second.json()
    assert [item["snapshot_id"] for item in page["items"]] == [f"rs_{'d' * 64}"]
    assert page["next_cursor"] is None
    assert page["upper_bound_sequence"] == first_page["upper_bound_sequence"]


def test_all_collections_use_collection_specific_stable_order(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    store: RecordingHistoryStore = app.state.recording_history_store
    store.publish(RECORDING, _snapshot("c"))
    store.publish(RECORDING, _snapshot("a"))
    store.publish(RECORDING, _revision("rev-z"))
    store.publish(RECORDING, _revision("rev-a"))
    store.publish(RECORDING, _edge("edge-z", "used"))
    store.publish(RECORDING, _edge("edge-a", "copied"))
    client = TestClient(app)
    paths = {
        "snapshots": "history",
        "revisions": "revisions",
        "candidates": "candidates",
        "lineage_edges": "lineage-edges",
    }
    for collection, path in paths.items():
        response = client.get(f"/api/recordings/{RECORDING}/state/{path}", params={"limit": 100})
        assert response.status_code == 200
        payload = response.json()
        assert payload["collection"] == collection
        assert payload["has_more"] is False
        items = payload["items"]
        keys = [
            item["snapshot_id"]
            if item["item_kind"] == "snapshot"
            else item["item_key"]
            if item["item_kind"] == "lineage_edge"
            else (item["resource"]["kind"], item["resource"]["resource_id"], item["item_key"])
            for item in items
        ]
        assert keys == sorted(keys)


def test_cursor_tamper_request_binding_and_expiry(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    store: RecordingHistoryStore = app.state.recording_history_store
    store.publish(RECORDING, _snapshot("a"))
    store.publish(RECORDING, _snapshot("b"))
    client = TestClient(app)
    first = client.get(f"/api/recordings/{RECORDING}/state/history", params={"limit": 1}).json()
    cursor = first["next_cursor"]
    assert cursor
    tampered = cursor[:-2] + ("aa" if not cursor.endswith("aa") else "bb")
    assert (
        client.get(
            f"/api/recordings/{RECORDING}/state/history", params={"limit": 1, "cursor": tampered}
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/recordings/{RECORDING}/state/history", params={"limit": 2, "cursor": cursor}
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/recordings/{RECORDING}/state/revisions", params={"limit": 1, "cursor": cursor}
        ).status_code
        == 422
    )
    store.rebuild(RECORDING, [_snapshot("a"), _snapshot("b")])
    expired = client.get(
        f"/api/recordings/{RECORDING}/state/history", params={"limit": 1, "cursor": cursor}
    )
    assert expired.status_code == 410


def test_cursor_filter_binding_is_integrity_protected(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    store: RecordingHistoryStore = app.state.recording_history_store
    store.publish(RECORDING, _snapshot("a"))
    authority = store.get_authority(RECORDING)
    cursor = HistoryPageCursor(
        recording_id=RECORDING,
        collection="snapshots",
        filter_sha256=hashlib.sha256(b"different-filter").hexdigest(),
        upper_bound_sequence=authority.sequence,
        history_generation=authority.generation,
        last_key=None,
        page_size=50,
    )
    from dokodetector_backend.recording_state_api import _encode_history_cursor

    token = _encode_history_cursor(cursor, store.cursor_integrity_key())
    response = TestClient(app).get(
        f"/api/recordings/{RECORDING}/state/history", params={"cursor": token}
    )
    assert response.status_code == 422


def test_lineage_cursor_uses_full_composite_key_and_page_size_is_bounded(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    store: RecordingHistoryStore = app.state.recording_history_store
    for key, edge_kind in (("edge-a", "copied"), ("edge-b", "produced"), ("edge-c", "used")):
        store.publish(RECORDING, _edge(key, edge_kind))
    client = TestClient(app)
    response = client.get(f"/api/recordings/{RECORDING}/state/lineage-edges", params={"limit": 1})
    assert response.status_code == 200
    first = response.json()
    assert first["has_more"]
    continuation = client.get(
        f"/api/recordings/{RECORDING}/state/lineage-edges",
        params={"limit": 1, "cursor": first["next_cursor"]},
    )
    assert continuation.status_code == 200
    assert continuation.json()["items"][0]["edge_kind"] == "produced"
    assert (
        client.get(
            f"/api/recordings/{RECORDING}/state/lineage-edges", params={"limit": 101}
        ).status_code
        == 422
    )


def test_corrupt_requested_metadata_returns_internal_error(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    store: RecordingHistoryStore = app.state.recording_history_store
    store.publish(RECORDING, _snapshot("a"))
    path = next((store.root / RECORDING / "generations").glob("*/items/snapshots/*.json"))
    document = json.loads(path.read_text())
    document["item"]["sha256"] = "b" * 64
    path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")))
    response = TestClient(app).get(f"/api/recordings/{RECORDING}/state/history")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "recording_history_corrupt"
