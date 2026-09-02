from __future__ import annotations

import shutil
import time
from io import BytesIO
from pathlib import Path

from app_factory import create_test_app
from doko_operations import ExtractedVisibleCardFrame, VisibleCardDetectorIdentity
from fastapi.testclient import TestClient
from PIL import Image
from table_evidence_analyzer import (
    CardClassificationResult,
    IdentityCandidate,
    ProviderResult,
    normalize_prediction,
)

from dokodetector_backend.config import Settings

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1" / "both"


def _image() -> bytes:
    output = BytesIO()
    Image.new("RGB", (20, 20), (40, 60, 80)).save(output, format="JPEG")
    return output.getvalue()


class _Extractor:
    def __init__(self) -> None:
        self.image = _image()

    def extract(self, video_path: Path, *, event_time_s: float, target_offset_ms: int):
        del video_path
        assert target_offset_ms == 0
        return ExtractedVisibleCardFrame(
            frame_index=round(event_time_s * 10),
            actual_offset_ms=0,
            image_bytes=self.image,
            width=20,
            height=20,
        )


class _Detector:
    name = "local"
    version = "local-visible-cards-test-v1"

    def propose(self, request) -> ProviderResult:
        return ProviderResult(
            status="ok",
            proposals=normalize_prediction(
                {
                    "cards": [
                        {
                            "box_2d": {"y_min": 100, "x_min": 100, "y_max": 900, "x_max": 900},
                            "polygon": [
                                {"x": 100, "y": 100},
                                {"x": 900, "y": 100},
                                {"x": 900, "y": 900},
                                {"x": 100, "y": 900},
                            ],
                            "side": "face_up",
                            "label": "visible_card",
                        }
                    ]
                }
            ).cards,
            raw_response={"fixture": True, "request": request.request_key},
        )


class _Classifier:
    name = "fixture-identity"
    version = "fixture-identity-v1"
    calibration = "uncalibrated"

    def __init__(self) -> None:
        self.calls = 0

    def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
        assert crop_bytes.startswith(b"P6\n")
        self.calls += 1
        return CardClassificationResult(
            status="ok",
            candidates=(IdentityCandidate(card="CLUBS_NINE", probability=1.0),),
            latency_ms=1.5,
            raw_response={"fixture": True},
        )


def _app(tmp_path: Path) -> tuple[object, _Classifier]:
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
    classifier = _Classifier()
    app = create_test_app(
        settings,
        visible_card_provider=_Detector(),
        visible_card_detector=VisibleCardDetectorIdentity(
            bundle_id="visible-card-fixture-bundle",
            bundle_digest="b" * 64,
            model="local-rfdetr",
            preprocessing="fixture-v1",
        ),
        visible_card_frame_extractor=_Extractor(),
        visible_card_identity_classifier=classifier,
    )
    return app, classifier


def _complete_card_event_review(client: TestClient) -> None:
    initial = client.get("/v1/recordings/recording-both/card-event-review").json()
    annotation = {
        "schema_version": "cardevent-annotation/v2",
        "video": "video-both.mov",
        "events": [{"time_s": 0.4, "type": "card_played", "confidence": "confirmed"}],
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


def _complete_visible_card_review(client: TestClient) -> dict:
    preview = client.post(
        "/v1/recordings/recording-both/visible-card-review/preview", json={}
    ).json()
    created = client.post(
        "/v1/recordings/recording-both/visible-card-review/batches",
        json={
            "preview_digest": preview["preview_digest"],
            "request_digest": preview["request_digest"],
        },
    )
    assert created.status_code == 202
    batch_id = created.json()["batch_id"]
    for _ in range(100):
        state = client.get(f"/v1/visible-card-reviews/{batch_id}").json()
        if state["status"] != "preparing":
            break
        time.sleep(0.01)
    assert state["status"] == "ready"
    item_id = state["items"][0]["item_id"].replace(":", "%3A")
    state = client.put(
        f"/v1/visible-card-reviews/{batch_id}/items/{item_id}",
        json={
            "expected_revision": 0,
            "review": {
                "status": "reviewed",
                "decision": "GOOD",
                "empty_frame": False,
                "failure_tags": [],
                "actions": [
                    {
                        "card_id": "card-01",
                        "action": "accepted",
                        "proposal_index": 0,
                        "reviewed_card": {
                            "card_id": "card-01",
                            "visible_region": {
                                "polygons": [state["items"][0]["finder"]["proposals"][0]["polygon"]]
                            },
                            "derived_box": state["items"][0]["finder"]["proposals"][0]["box_2d"],
                            "identity_usability": {
                                "usable": True,
                                "reason": "sufficient_identity_evidence",
                            },
                            "side": "face_up",
                            "failure_tags": [],
                        },
                    }
                ],
                "reviewer": "fixture-operator",
            },
        },
    ).json()
    completed = client.post(
        f"/v1/visible-card-reviews/{batch_id}/complete",
        json={"reviewer": "fixture-operator", "expected_revision": state["revision"]},
    )
    assert completed.status_code == 200
    return completed.json()


def _wait_for_identity_batch(client: TestClient, batch_id: str) -> dict:
    for _ in range(100):
        state = client.get(f"/v1/identity-reviews/{batch_id}").json()
        if state["status"] != "preparing":
            return state
        time.sleep(0.01)
    raise AssertionError("identity batch did not reach a terminal state")


def test_identity_review_preview_create_and_crop_route(tmp_path: Path) -> None:
    app, classifier = _app(tmp_path)
    with TestClient(app) as client:
        _complete_card_event_review(client)
        visible = _complete_visible_card_review(client)
        preview = client.post("/v1/recordings/recording-both/identity-review/preview", json={})
        assert preview.status_code == 200
        preview_body = preview.json()
        assert preview_body["validation"]["valid"] is True
        assert preview_body["selected_card_count"] == 1
        assert preview_body["visible_card_review_version_id"] == visible["completed_version_id"]

        created = client.post(
            "/v1/recordings/recording-both/identity-review/batches",
            json={
                "preview_digest": preview_body["preview_digest"],
                "request_digest": preview_body["request_digest"],
            },
        )
        assert created.status_code == 202
        state = _wait_for_identity_batch(client, created.json()["batch_id"])
        assert state["status"] == "ready"
        assert state["progress"]["total_items"] == 1
        assert state["items"][0]["proposal"]["candidates"][0]["card"] == "CLUBS_NINE"
        crop = client.get(state["items"][0]["crop"]["image_url"])
        assert crop.status_code == 200
        assert crop.headers["content-type"] == "image/x-portable-pixmap"
        assert crop.content.startswith(b"P6\n")
        assert classifier.calls == 1
