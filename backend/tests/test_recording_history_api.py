"""HTTP contract tests for bounded recording history pages."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import shutil
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.recording_history_store import (
    RecordingHistoryCorrupt,
    RecordingHistoryStore,
    _canonical_json,
)
from dokodetector_backend.recording_state_contract import (
    HistoryPageCursor,
    LineageEdgeHistoryItem,
    LineageEndpoint,
    ResourceHistoryItem,
    SnapshotHistoryItem,
)

RECORDING = "recording-both"
DIGEST = "a" * 64
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"


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


def _create_app(tmp_path: Path):
    settings = _settings(tmp_path)
    bundle_path = settings.repository_intake_root / RECORDING
    if not bundle_path.exists():
        shutil.copytree(FIXTURE_ROOT, bundle_path)
    return create_app(settings)


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


def _crash_after_history_cursor_key(root: str) -> None:
    store = RecordingHistoryStore(root)

    def stop_after_key(boundary: str) -> None:
        if boundary == "key_published":
            os._exit(79)

    store._after_cursor_key_boundary = stop_after_key
    store.cursor_integrity_key()


def test_history_pages_freeze_membership_and_continue_after_restart(tmp_path: Path):
    app = _create_app(tmp_path)
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
    restarted = TestClient(_create_app(tmp_path))
    second = restarted.get(
        f"/api/recordings/{RECORDING}/state/history", params={"limit": 2, "cursor": cursor}
    )
    assert second.status_code == 200
    page = second.json()
    assert [item["snapshot_id"] for item in page["items"]] == [f"rs_{'d' * 64}"]
    assert page["next_cursor"] is None
    assert page["upper_bound_sequence"] == first_page["upper_bound_sequence"]


def test_all_collections_use_collection_specific_stable_order(tmp_path: Path):
    app = _create_app(tmp_path)
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
    app = _create_app(tmp_path)
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


def test_unknown_recording_is_404_without_history_side_effects(tmp_path: Path):
    client = TestClient(_create_app(tmp_path))
    response = client.get("/api/recordings/recording-missing/state/history")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "recording_not_found"
    history_root = tmp_path / "operations" / "recording-history"
    assert not history_root.exists()


def test_cursor_key_is_private_durable_and_detects_loss(tmp_path: Path):
    store = RecordingHistoryStore(tmp_path)
    key = store.cursor_integrity_key()
    key_path = store.root / "cursor-integrity-key"
    state_path = store.root / "cursor-integrity-key-state.json"
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert RecordingHistoryStore(tmp_path).cursor_integrity_key() == key

    key_path.unlink()
    with pytest.raises(RecordingHistoryCorrupt, match="established.*missing"):
        RecordingHistoryStore(tmp_path).cursor_integrity_key()
    key_path.write_bytes(key)
    assert RecordingHistoryStore(tmp_path).cursor_integrity_key() == key


def test_cursor_key_recovers_crash_between_key_and_state_publication(tmp_path: Path):
    process = multiprocessing.get_context("fork").Process(
        target=_crash_after_history_cursor_key, args=(str(tmp_path),)
    )
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 79

    key_path = tmp_path / "recording-history" / "cursor-integrity-key"
    assert key_path.exists()
    original = key_path.read_bytes()
    restarted = RecordingHistoryStore(tmp_path)
    assert restarted.cursor_integrity_key() == original
    assert (key_path.parent / "cursor-integrity-key-state.json").exists()


def test_cursor_key_publication_is_atomic_before_replace(tmp_path: Path, monkeypatch):
    store = RecordingHistoryStore(tmp_path)
    key_path = store.root / "cursor-integrity-key"
    state_path = store.root / "cursor-integrity-key-state.json"
    original_replace = os.replace

    def fail_replace(source, destination):
        if Path(destination) == key_path:
            raise OSError("simulated death before key publication")
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="before key publication"):
        store.cursor_integrity_key()
    assert not key_path.exists()
    assert not state_path.exists()
    assert not list(store.root.glob(".cursor-integrity-key.*"))


def test_cursor_key_state_corruption_is_not_repaired_silently(tmp_path: Path):
    store = RecordingHistoryStore(tmp_path)
    store.cursor_integrity_key()
    state_path = store.root / "cursor-integrity-key-state.json"
    state = json.loads(state_path.read_bytes())
    state["sha256"] = "0" * 64
    state_path.write_bytes(_canonical_json(state))
    with pytest.raises(RecordingHistoryCorrupt, match="does not match"):
        RecordingHistoryStore(tmp_path).cursor_integrity_key()


def test_established_cursor_key_loss_returns_http_500(tmp_path: Path):
    app = _create_app(tmp_path)
    client = TestClient(app)
    first = client.get(f"/api/recordings/{RECORDING}/state/history")
    assert first.status_code == 200
    key_path = app.state.recording_history_store.root / "cursor-integrity-key"
    key_path.unlink()
    response = client.get(f"/api/recordings/{RECORDING}/state/history")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "recording_history_corrupt"


def test_simultaneous_revisions_stay_outside_frozen_history_page(tmp_path: Path):
    app = _create_app(tmp_path)
    store: RecordingHistoryStore = app.state.recording_history_store
    for key in ("rev-b", "rev-c", "rev-d"):
        store.publish(RECORDING, _revision(key))
    client = TestClient(app)
    first = client.get(f"/api/recordings/{RECORDING}/state/revisions", params={"limit": 2}).json()
    assert [item["resource"]["resource_id"] for item in first["items"]] == ["rev-b", "rev-c"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        published = list(
            executor.map(lambda key: store.publish(RECORDING, _revision(key)), ("rev-a", "rev-z"))
        )
    assert len(published) == 2
    continuation = client.get(
        f"/api/recordings/{RECORDING}/state/revisions",
        params={"limit": 2, "cursor": first["next_cursor"]},
    ).json()
    assert [item["resource"]["resource_id"] for item in continuation["items"]] == ["rev-d"]
    assert not continuation["has_more"]


def test_lineage_pages_return_exact_metadata_without_payload_reads(tmp_path: Path, monkeypatch):
    app = _create_app(tmp_path)
    store: RecordingHistoryStore = app.state.recording_history_store
    for index in range(64):
        store.publish(RECORDING, _revision(f"rev-{index:03}"))
    store.publish(
        RECORDING,
        LineageEdgeHistoryItem(
            item_key="edge-exact",
            edge_kind="used",
            source=LineageEndpoint(kind="revision", node_id="node-exact", revision_id="rev-exact"),
            target=LineageEndpoint(kind="run", run_id="run-exact"),
            role="input",
            publication_sequence=1,
        ),
    )
    metadata_reads = 0
    original_read = store._read_history_item

    def count_metadata_reads(*args, **kwargs):
        nonlocal metadata_reads
        metadata_reads += 1
        return original_read(*args, **kwargs)

    store._read_history_item = count_metadata_reads

    def reject_payload_read(*args, **kwargs):
        raise AssertionError("history page read a revision payload")

    from dokodetector_backend.pipeline_node_store import PipelineNodeStore

    monkeypatch.setattr(PipelineNodeStore, "read_authorized_revision", reject_payload_read)
    response = TestClient(app).get(
        f"/api/recordings/{RECORDING}/state/lineage-edges", params={"limit": 1}
    )
    assert response.status_code == 200
    edge = response.json()["items"][0]
    assert edge["item_key"] == "edge-exact"
    assert edge["source"]["revision_id"] == "rev-exact"
    assert edge["target"]["run_id"] == "run-exact"
    assert metadata_reads == 1
    revisions = TestClient(app).get(
        f"/api/recordings/{RECORDING}/state/revisions", params={"limit": 2}
    )
    assert revisions.status_code == 200
    assert len(revisions.json()["items"]) == 2
    assert metadata_reads == 3


def test_cursor_filter_binding_is_integrity_protected(tmp_path: Path):
    app = _create_app(tmp_path)
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
    app = _create_app(tmp_path)
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
    app = _create_app(tmp_path)
    store: RecordingHistoryStore = app.state.recording_history_store
    store.publish(RECORDING, _snapshot("a"))
    path = next((store.root / RECORDING / "generations").glob("*/items/snapshots/*.json"))
    document = json.loads(path.read_text())
    document["item"]["sha256"] = "b" * 64
    path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")))
    response = TestClient(app).get(f"/api/recordings/{RECORDING}/state/history")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "recording_history_corrupt"
