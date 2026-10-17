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
        assert page["items"][0]["editor_target"]["revision_id"]

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


def test_save_review_receipt_requires_and_tracks_the_current_explicit_draft(
    tmp_path: Path,
) -> None:
    app = create_test_app(_settings(tmp_path))
    with TestClient(app) as client:
        page = client.get("/api/frame-reviews/0096-M4?limit=100").json()
        item = next(
            candidate for candidate in page["items"] if candidate["editor_target"] is not None
        )
        route = (
            f"/api/frame-reviews/0096-M4/items/{item['recording_id']}/{item['item_id']}/workflow"
        )
        manifest_path = REPOSITORY_ROOT / "docs/reports/0096-M4_Human_Review_Queue.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw_frame = next(
            frame
            for recording in manifest["recordings"]
            for frame in recording["review_frames"]
            if recording["recording_id"] == item["recording_id"]
            and frame["item_id"] == item["item_id"]
        )
        app.state.pipeline_revision_store.list_manifests = lambda: [
            SimpleNamespace(
                revision_id=item["editor_target"]["revision_id"],
                recording_id=item["recording_id"],
                content_type="visible_cards",
                content_sha256=raw_frame["m1_revision_sha256"],
            )
        ]
        app.state.pipeline_reference_store.get = lambda _recording, _stage: SimpleNamespace(
            draft=SimpleNamespace(
                revision=7,
                source_revision_id=item["editor_target"]["revision_id"],
                items=(SimpleNamespace(item_id=item["item_id"], review_state="accepted"),),
            )
        )
        stale = client.put(
            route,
            json={
                "queue_digest": page["queue_digest"],
                "action": "save_review",
                "draft_revision": 6,
            },
        )
        assert stale.status_code == 409
        assert (
            app.state.frame_review_workflow_store.read_receipt(
                "0096-M4", f'["{item["recording_id"]}","{item["item_id"]}"]'
            )
            is None
        )

        saved = client.put(
            route,
            json={
                "queue_digest": page["queue_digest"],
                "action": "save_review",
                "draft_revision": 7,
            },
        )
        assert saved.status_code == 200
        refreshed = client.get("/api/frame-reviews/0096-M4?limit=100").json()
        saved_item = next(
            candidate
            for candidate in refreshed["items"]
            if candidate["recording_id"] == item["recording_id"]
            and candidate["item_id"] == item["item_id"]
        )
        assert saved_item["state"] == "saved_review"
