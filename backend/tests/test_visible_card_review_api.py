from __future__ import annotations

import shutil
import threading
import time
from io import BytesIO
from pathlib import Path

from app_factory import create_test_app
from doko_operations import ExtractedVisibleCardFrame, VisibleCardDetectorIdentity
from fastapi.testclient import TestClient
from PIL import Image
from table_evidence_analyzer import ProviderResult

from dokodetector_backend.config import Settings

BACKEND_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"


def _image() -> bytes:
    output = BytesIO()
    Image.new("RGB", (20, 20), (40, 60, 80)).save(output, format="JPEG")
    return output.getvalue()


class _FixtureExtractor:
    def __init__(
        self,
        *,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
    ):
        self.started = started
        self.release = release
        self.image = _image()

    def extract(self, video_path: Path, *, event_time_s: float, target_offset_ms: int):
        del video_path
        assert target_offset_ms == 0
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            self.release.wait(timeout=2)
        return ExtractedVisibleCardFrame(
            frame_index=round(event_time_s * 10),
            actual_offset_ms=0,
            image_bytes=self.image,
            width=20,
            height=20,
        )


class _FlakyProvider:
    name = "local"
    version = "local-visible-cards-test-v1"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_next = True

    def propose(self, request) -> ProviderResult:
        self.calls.append(request.package_id)
        if self.fail_next:
            self.fail_next = False
            return ProviderResult(status="unavailable", error="fixture provider unavailable")
        return ProviderResult(status="ok", raw_response={"provider": self.name})


def _app(tmp_path: Path, provider: _FlakyProvider, extractor: _FixtureExtractor):
    intake_root = tmp_path / "data" / "intake" / "recordings"
    shutil.copytree(FIXTURE_ROOT, intake_root / "recording-both")
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'review.sqlite'}",
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "data" / "operations",
        repository_intake_root=intake_root,
        evidence_package_intake_root=tmp_path / "data" / "intake" / "evidence-packages",
        pending_video_root=tmp_path / "data" / "incoming" / "videos",
        visible_card_provider="local",
    )
    detector = VisibleCardDetectorIdentity(
        bundle_id="visible-card-fixture-bundle",
        bundle_digest="b" * 64,
        model="local-rfdetr",
        preprocessing="fixture-v1",
    )
    return create_test_app(
        settings,
        visible_card_provider=provider,
        visible_card_detector=detector,
        visible_card_frame_extractor=extractor,
    )


def _complete_card_event_review(client: TestClient) -> None:
    initial = client.get("/v1/recordings/recording-both/card-event-review").json()
    annotation = {
        "schema_version": "cardevent-annotation/v2",
        "video": "video-both.mov",
        "events": [
            {"time_s": 0.4, "type": "card_played", "confidence": "confirmed"},
            {"time_s": 1.2, "type": "card_played", "confidence": "confirmed"},
        ],
    }
    saved = client.put(
        "/v1/recordings/recording-both/card-event-review/draft",
        json={
            "annotation": annotation,
            "proposals": [
                {"proposal_id": initial["proposals"][0]["proposal_id"], "decision": "dismissed"}
            ],
            "expected_revision": 0,
        },
    )
    assert saved.status_code == 200
    completed = client.post(
        "/v1/recordings/recording-both/card-event-review/complete",
        json={
            "reviewer": "fixture-operator",
            "expected_revision": 1,
            "full_video_acknowledged": True,
        },
    )
    assert completed.status_code == 200


def _wait_for_batch(client: TestClient, batch_id: str) -> dict:
    for _ in range(200):
        state = client.get(f"/v1/visible-card-reviews/{batch_id}").json()
        if state["status"] != "preparing":
            return state
        time.sleep(0.01)
    raise AssertionError("visible-card batch did not reach a terminal state")


def test_preview_create_and_reload_persist_progress_without_duplicate_work(tmp_path: Path) -> None:
    provider = _FlakyProvider()
    started = threading.Event()
    release = threading.Event()
    app = _app(tmp_path, provider, _FixtureExtractor(started=started, release=release))
    with TestClient(app) as client:
        _complete_card_event_review(client)
        preview = client.post(
            "/v1/recordings/recording-both/visible-card-review/preview", json={}
        )
        assert preview.status_code == 200
        preview_body = preview.json()
        assert preview_body["validation"]["valid"] is True
        assert preview_body["selected_event_count"] == 2
        assert preview_body["detector"]["bundle_digest"] == "b" * 64

        payload = {
            "preview_digest": preview_body["preview_digest"],
            "request_digest": preview_body["request_digest"],
        }
        create_started_at = time.monotonic()
        created = client.post(
            "/v1/recordings/recording-both/visible-card-review/batches", json=payload
        )
        assert time.monotonic() - create_started_at < 1.0
        assert created.status_code == 202
        assert created.json()["status"] == "preparing"
        assert started.wait(timeout=1)
        duplicate = client.post(
            "/v1/recordings/recording-both/visible-card-review/batches", json=payload
        )
        assert duplicate.status_code == 202
        assert duplicate.json()["batch_id"] == created.json()["batch_id"]
        assert duplicate.json()["status"] == "preparing"

        release.set()
        state = _wait_for_batch(client, created.json()["batch_id"])
        assert state["status"] == "failed"
        assert state["progress"]["total_items"] == 2


def test_retry_reuses_successful_items_and_keeps_frozen_identity(tmp_path: Path) -> None:
    provider = _FlakyProvider()
    app = _app(tmp_path, provider, _FixtureExtractor())
    with TestClient(app) as client:
        _complete_card_event_review(client)
        preview = client.post(
            "/v1/recordings/recording-both/visible-card-review/preview", json={}
        ).json()
        created = client.post(
            "/v1/recordings/recording-both/visible-card-review/batches",
            json={
                "preview_digest": preview["preview_digest"],
                "request_digest": preview["request_digest"],
            },
        ).json()
        failed = _wait_for_batch(client, created["batch_id"])
        assert failed["status"] == "failed"
        successful_before = next(item for item in failed["items"] if item["failure"] is None)
        original_call_count = len(provider.calls)

        retried = client.post(f"/v1/visible-card-reviews/{created['batch_id']}/retry")
        assert retried.status_code == 202
        ready = _wait_for_batch(client, created["batch_id"])
        assert ready["status"] == "ready"
        assert len(provider.calls) == original_call_count + 1
        successful_after = next(
            item for item in ready["items"] if item["item_id"] == successful_before["item_id"]
        )
        assert successful_after["status"] == "finder_complete"
        assert ready["request_digest"] == preview["request_digest"]


def test_stale_preview_is_rejected_after_detector_identity_changes(tmp_path: Path) -> None:
    provider = _FlakyProvider()
    app = _app(tmp_path, provider, _FixtureExtractor())
    with TestClient(app) as client:
        _complete_card_event_review(client)
        preview = client.post(
            "/v1/recordings/recording-both/visible-card-review/preview", json={}
        ).json()
        app.state.visible_card_detector = VisibleCardDetectorIdentity(
            bundle_id="different-bundle",
            bundle_digest="c" * 64,
            model="local-rfdetr",
            preprocessing="fixture-v1",
        )
        response = client.post(
            "/v1/recordings/recording-both/visible-card-review/batches",
            json={
                "preview_digest": preview["preview_digest"],
                "request_digest": preview["request_digest"],
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "visible_card_review_preview_stale"


def test_ready_batch_exposes_queue_details_and_serves_owned_source_frames(tmp_path: Path) -> None:
    provider = _FlakyProvider()
    app = _app(tmp_path, provider, _FixtureExtractor())
    with TestClient(app) as client:
        _complete_card_event_review(client)
        preview = client.post(
            "/v1/recordings/recording-both/visible-card-review/preview", json={}
        ).json()
        created = client.post(
            "/v1/recordings/recording-both/visible-card-review/batches",
            json={
                "preview_digest": preview["preview_digest"],
                "request_digest": preview["request_digest"],
            },
        ).json()
        _wait_for_batch(client, created["batch_id"])
        retried = client.post(f"/v1/visible-card-reviews/{created['batch_id']}/retry")
        assert retried.status_code == 202
        ready = _wait_for_batch(client, created["batch_id"])

        assert ready["status"] == "ready"
        assert ready["revision"] == 0
        assert len(ready["items"]) == 2
        item = ready["items"][0]
        assert item["source"]["image_url"].endswith(
            f"/items/{item['item_id'].replace(':', '%3A')}/image"
        )
        assert item["finder"]["request_digest"]
        assert item["finder"]["result_digest"]
        assert item["finder"]["proposals"] == []
        assert item["review"]["status"] == "unreviewed"

        image = client.get(item["source"]["image_url"])
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/jpeg"
        assert image.content.startswith(b"\xff\xd8")

        direct = client.get(f"/v1/visible-card-reviews/{created['batch_id']}")
        assert direct.status_code == 200
        assert direct.json()["items"][0]["item_id"] == item["item_id"]
