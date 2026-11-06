from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.frame_review_workflow_store import FrameReviewWorkflowStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        repository_root=REPOSITORY_ROOT,
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "operations",
        frontend_dist=tmp_path / "frontend",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "packages",
        pending_video_root=tmp_path / "pending",
    )


def test_frame_review_api_pages_queue_and_persists_queue_only_workflow(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    draft_path = (
        tmp_path / "operations" / "pipeline-references" / "keep" / "visible_cards" / "draft.json"
    )
    draft_path.parent.mkdir(parents=True)
    draft_path.write_text('{"untouched":true}', encoding="utf-8")

    with TestClient(app) as client:
        first = client.get("/api/frame-reviews/0096-M4?limit=2")
        assert first.status_code == 200
        page = first.json()
        assert page["counts"]["total"] == 165
        assert page["next_cursor"] == 2
        assert len(page["items"]) == 2
        assert page["items"][0]["state"] == "unavailable"
        assert "pinned detector result" in page["items"][0]["unavailable_reason"]
        assert page["items"][0]["editor_target"] is None

        item = page["items"][0]
        route = (
            f"/api/frame-reviews/0096-M4/items/{item['recording_id']}/{item['item_id']}/workflow"
        )
        digest = page["queue_digest"]
        deferred = client.put(route, json={"queue_digest": digest, "action": "defer"})
        assert deferred.status_code == 200
        assert deferred.json()["deferred"] is True

        resumed_item = client.put(route, json={"queue_digest": digest, "action": "resume"})
        assert resumed_item.status_code == 200
        assert resumed_item.json()["deferred"] is False
        client.put(route, json={"queue_digest": digest, "action": "defer"})

        resumed = client.put(route, json={"queue_digest": digest, "action": "set_resume"})
        assert resumed.status_code == 200
        assert resumed.json()["resume_item_id"] == item["item_id"]

        next_page = client.get("/api/frame-reviews/0096-M4?limit=2&cursor=2")
        assert next_page.json()["items"][0]["item_id"] != item["item_id"]
        assert next_page.json()["resume_recording_id"] == item["recording_id"]

        stale = client.put(
            route,
            json={"queue_digest": "0" * 64, "action": "resume"},
        )
        assert stale.status_code == 409
        absent = client.put(
            "/api/frame-reviews/0096-M4/items/missing/nope/workflow",
            json={"queue_digest": digest, "action": "defer"},
        )
        assert absent.status_code == 404

    assert draft_path.read_text(encoding="utf-8") == '{"untouched":true}'
    progress = FrameReviewWorkflowStore(tmp_path / "operations" / "frame-review-queues").read(
        "0096-M4", digest
    )
    assert progress["deferred_item_keys"]
    assert progress["resume_item_key"]
    restarted = FrameReviewWorkflowStore(tmp_path / "operations" / "frame-review-queues").read(
        "0096-M4", digest
    )
    assert restarted == progress


def test_frame_review_api_returns_deterministic_counts_and_pages(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    with TestClient(app) as client:
        one = client.get("/api/frame-reviews/0096-M4?limit=7")
        two = client.get("/api/frame-reviews/0096-M4?limit=7")
    assert one.json() == two.json()
    assert sum(one.json()["counts"]["by_state"].values()) == 165
    assert sum(item["state"] == "unavailable" for item in one.json()["items"]) == 7


def test_save_review_receipt_requires_exact_applicable_node_review(tmp_path: Path) -> None:
    from test_virtual_scene_data import FRAME, SOURCE

    app = create_test_app(_settings(tmp_path))
    with TestClient(app) as client:
        page = client.get("/api/frame-reviews/0096-M4?limit=1").json()
        item = page["items"][0]
        manifest = json.loads(
            (REPOSITORY_ROOT / "docs/reports/0096-M4_Human_Review_Queue.json").read_text()
        )
        frame = next(
            frame
            for row in manifest["recordings"]
            for frame in row["review_frames"]
            if row["recording_id"] == item["recording_id"] and frame["item_id"] == item["item_id"]
        )
        source_id = frame["m1_revision_id"]
        writer = app.state.pipeline_lineage_writer
        source = {**SOURCE, "recording_id": item["recording_id"]}
        content = {
            "schema_version": "visible-card-data/v2",
            "outcomes": [
                {
                    "event_id": item["item_id"],
                    "frame_identity": FRAME,
                    "status": "empty",
                    "candidates": [],
                    "ignored_regions": [],
                    "pile_regions": [],
                    "pile_detection_status": "unsupported",
                    "error": None,
                }
            ],
        }
        node = writer.node_store.create(
            "fixture-node",
            "Detector",
            "visible_cards",
            source,
            content,
            {},
            revision_id="fixture-revision",
        )
        writer.migrated_revisions[source_id] = {
            "node_id": "fixture-node",
            "revision_id": node.revision_id,
        }
        app.state.pipeline_revision_store.get = lambda revision_id, **_kwargs: (
            SimpleNamespace(
                manifest=SimpleNamespace(
                    recording_id=item["recording_id"],
                    content_type="visible_cards",
                    content_sha256=frame["m1_revision_sha256"],
                ),
                content=SimpleNamespace(outcomes=[SimpleNamespace(event_id=item["item_id"])]),
            )
            if revision_id == source_id
            else None
        )
        review = app.state.pipeline_node_reviews.item(
            "review-1",
            "fixture-node",
            node.revision_id,
            item["item_id"],
            "visible_card_outcome",
            "accepted",
            {"kind": "human", "id": "reviewer"},
            {"policy": "visible-card-review/v1", "frame": FRAME["image_sha256"]},
        )
        route = (
            f"/api/frame-reviews/0096-M4/items/{item['recording_id']}/{item['item_id']}/workflow"
        )
        payload = {
            "queue_digest": page["queue_digest"],
            "action": "save_review",
            "node_id": "fixture-node",
            "revision_id": node.revision_id,
            "review_id": review["review_id"],
        }
        assert client.put(route, json={**payload, "review_id": "missing"}).status_code == 409
        assert client.put(route, json=payload).status_code == 200
        saved = client.get("/api/frame-reviews/0096-M4?limit=1").json()["items"][0]
        assert saved["state"] == "saved_review"
        changed = {
            **content,
            "outcomes": [
                {
                    **content["outcomes"][0],
                    "frame_identity": {**FRAME, "requested_time_us": 2_000_000},
                }
            ],
        }
        writer.node_store.save("fixture-node", node.revision_id, changed, {})
        stale = client.get("/api/frame-reviews/0096-M4?limit=1").json()["items"][0]
        assert stale["state"] == "unavailable"


def test_queue_rejects_a_revision_without_the_pinned_frame(tmp_path: Path) -> None:
    app = create_test_app(_settings(tmp_path))
    with TestClient(app) as client:
        page = client.get("/api/frame-reviews/0096-M4?limit=1").json()
        item = page["items"][0]
        raw = json.loads(
            (REPOSITORY_ROOT / "docs/reports/0096-M4_Human_Review_Queue.json").read_text()
        )
        frame = next(
            frame
            for recording in raw["recordings"]
            for frame in recording["review_frames"]
            if recording["recording_id"] == item["recording_id"]
            and frame["item_id"] == item["item_id"]
        )
        target = frame["m1_revision_id"]
        app.state.pipeline_revision_store.get = lambda revision_id, **_kwargs: (
            SimpleNamespace(
                manifest=SimpleNamespace(
                    recording_id=item["recording_id"],
                    content_type="visible_cards",
                    content_sha256=frame["m1_revision_sha256"],
                ),
                content=SimpleNamespace(outcomes=[]),
            )
            if revision_id == target
            else None
        )
        result = client.get("/api/frame-reviews/0096-M4?limit=1").json()["items"][0]
        assert result["state"] == "unavailable"
        assert "does not contain this frame" in result["unavailable_reason"]
