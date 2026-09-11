from __future__ import annotations

import shutil
import threading
from typing import Any

from app_factory import create_test_app
from doko_operations.pipeline_data import (
    DataRevision,
    HumanProducer,
    RunProgress,
    sha256_bytes,
)
from fastapi.testclient import TestClient
from table_evidence_analyzer import (
    CardClassificationResult,
    PredictedVisibleRegionGeometry,
    ReviewedVisibleRegionGeometry,
    VisibleCardCandidate,
    VisibleCardData,
    VisibleCardFrameIdentity,
    VisibleCardOutcome,
    VisualIdentityRequest,
    canonical_visible_card_data_bytes,
)
from table_evidence_analyzer.table_observation import IdentityCandidate
from test_visible_card_pipeline_api import (
    RECORDING_ID,
    _Detector,
    _EventProvider,
    _FrameResolver,
    _install_recording,
    _settings,
    _wait,
    _wait_event,
)


class _IdentityProvider:
    name = "fixture-identity"
    version = "fixture-identity/v1"
    model = "fixture-model/v1"

    def __init__(self) -> None:
        self.requests: list[VisualIdentityRequest] = []

    def classify(self, request: VisualIdentityRequest) -> CardClassificationResult:
        self.requests.append(request)
        if request.card_id.endswith("empty"):
            return CardClassificationResult(status="ok", candidates=())
        if request.card_id.endswith("failed"):
            return CardClassificationResult(status="unavailable", error="fixture failure")
        return CardClassificationResult(
            status="ok",
            candidates=(
                IdentityCandidate(card="CLUBS_NINE", probability=0.75),
                IdentityCandidate(card="SPADES_NINE", probability=0.25),
            ),
        )


def _manual_visible_revision(app: Any, source: Any, frame: dict[str, Any]) -> str:
    frame_identity = VisibleCardFrameIdentity.from_mapping(frame)
    candidates = (
        VisibleCardCandidate(
            card_id="card-classified",
            geometry=PredictedVisibleRegionGeometry(
                polygons=(((100, 100), (900, 100), (900, 900), (100, 900)),)
            ),
            normalization={"width": 64, "height": 64, "policy_id": "fixture/v1"},
            side="face_up",
        ),
        VisibleCardCandidate(
            card_id="card-empty",
            geometry=ReviewedVisibleRegionGeometry(
                polygons=(((100, 100), (900, 100), (900, 900), (100, 900)),)
            ),
            normalization={"width": 64, "height": 64, "policy_id": "fixture/v1"},
            side="unknown",
        ),
        VisibleCardCandidate(
            card_id="card-unusable",
            geometry=ReviewedVisibleRegionGeometry(
                polygons=(((0, 0), (10, 0), (10, 10), (0, 10)),)
            ),
            normalization={"width": 64, "height": 64, "policy_id": "fixture/v1"},
            side="face_down",
        ),
        VisibleCardCandidate(
            card_id="card-failed",
            geometry=ReviewedVisibleRegionGeometry(
                polygons=(((100, 100), (900, 100), (900, 900), (100, 900)),)
            ),
            normalization={"width": 64, "height": 64, "policy_id": "fixture/v1"},
            side="unknown",
        ),
    )
    content = VisibleCardData(
        outcomes=(
            VisibleCardOutcome(
                event_id="event-000000",
                frame_identity=frame_identity,
                status="detected",
                candidates=candidates,
            ),
        )
    )
    revision_id = "visible-cards-completed-reference"
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="visible_cards",
        content_schema="visible-card-data/v1",
        recording_id=RECORDING_ID,
        source=source,
        content_sha256=sha256_bytes(canonical_visible_card_data_bytes(content)),
        input_revision_ids=(),
        origin="manual",
        producer=HumanProducer(review_id="review-1", operator_id="operator-1"),
        coverage={"kind": "completed-reference", "card_ids": [item.card_id for item in candidates]},
        created_at="2026-01-01T00:00:00Z",
    )
    stored, _ = app.state.pipeline_revision_store.publish(manifest, content)
    current = app.state.pipeline_selection_store.get(RECORDING_ID, "visible_cards")
    app.state.pipeline_selection_store.update_pointers(
        RECORDING_ID,
        "visible_cards",
        expected_revision=0 if current is None else current.revision,
        selected_generated_revision_id=(
            None if current is None else current.selected_generated_revision_id
        ),
        selected_completed_reference_revision_id=stored.manifest.revision_id,
    )
    return stored.manifest.revision_id


def test_visual_identity_pipeline_uses_generated_and_completed_geometry_and_restarts(
    tmp_path: Any,
) -> None:
    _install_recording(tmp_path)
    provider = _IdentityProvider()
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=provider,
    )

    with TestClient(app) as client:
        event_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json={"run_id": "events-generated"},
        )
        assert event_response.status_code == 202
        _wait_event(client, "events-generated")
        client.get(f"/api/recordings/{RECORDING_ID}/pipeline/events/events-generated/result")

        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={"run_id": "visible-generated"},
        )
        assert visible_response.status_code == 202
        assert _wait(client, "visible-generated")["state"]["status"] == "complete"
        visible_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/visible-generated/result"
        ).json()
        generated_revision_id = visible_result["state"]["output_revision_ids"][0]
        generated_content = visible_result["revisions"][0]["content"]
        manual_revision_id = _manual_visible_revision(
            app,
            app.state.pipeline_revision_store.require(generated_revision_id).manifest.source,
            generated_content["outcomes"][0]["frame_identity"],
        )

        generated_identity = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-generated",
                "input_revision_ids": [generated_revision_id],
            },
        )
        assert generated_identity.status_code == 202
        assert _wait_identity(client, "identity-generated")["state"]["status"] == "complete"
        generated_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/identity-generated/result"
        ).json()
        generated_outcome = generated_result["revisions"][0]["content"]["outcomes"][0]
        assert generated_result["request"]["input_revision_ids"] == [generated_revision_id]
        assert generated_result["request"]["crop_policy"] == {
            "policy_id": "predicted_visible_region",
            "output_encoding": "ppm",
        }
        assert generated_outcome["status"] == "classified"
        assert generated_outcome["crop_identity"]["status"] == "usable"
        assert generated_outcome["crop_identity"]["crop_policy"] == "predicted_visible_region"
        assert generated_outcome["classifier"]["provider"] == "fixture-identity"
        identity_revision_id = generated_result["state"]["output_revision_ids"][0]
        shutil.rmtree(
            app.state.visual_identity_pipeline_service.storage.derived_views_root,
            ignore_errors=True,
        )
        crop_response = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
            f"{identity_revision_id}/{generated_outcome['card_id']}"
        )
        assert crop_response.status_code == 200, crop_response.text
        assert crop_response.headers["cache-control"].startswith("private")
        assert crop_response.content
        preview_response = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
            f"{identity_revision_id}/{generated_outcome['card_id']}?preview=browser"
        )
        assert preview_response.status_code == 200, preview_response.text
        assert preview_response.headers["content-type"] == "image/jpeg"
        assert preview_response.content.startswith(b"\xff\xd8\xff")
        assert generated_outcome["candidates"] == [
            {
                "identity": "CLUBS_NINE",
                "score": 0.75,
                "score_meaning": "probability",
                "producer_id": "fixture-model-v1.fixture-identity-v1",
            },
            {
                "identity": "SPADES_NINE",
                "score": 0.25,
                "score_meaning": "probability",
                "producer_id": "fixture-model-v1.fixture-identity-v1",
            },
        ]
        frozen_provider = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-generated",
                "configuration": {"provider": "different-provider"},
            },
        )
        assert frozen_provider.status_code == 422

        completed_identity = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-completed",
                "crop_policy": {
                    "policy_id": "oracle_visible_region",
                    "output_encoding": "ppm",
                },
            },
        )
        assert completed_identity.status_code == 202
        assert _wait_identity(client, "identity-completed")["state"]["status"] == "complete"
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/identity-completed/result"
        ).json()
        assert result["request"]["input_revision_ids"] == [manual_revision_id]
        assert result["request"]["crop_policy"] == {
            "policy_id": "oracle_visible_region",
            "output_encoding": "ppm",
        }
        outcomes = result["revisions"][0]["content"]["outcomes"]
        assert [outcome["status"] for outcome in outcomes] == [
            "classified",
            "unusable",
            "unusable",
            "failed",
        ]
        assert outcomes[1]["geometry"]["kind"] == "reviewed-visible-region/v1"
        assert outcomes[1]["candidates"] == []
        assert outcomes[1]["unusable_reason"] == "The classifier returned no identity candidates."
        assert outcomes[0]["status"] == "classified"
        assert outcomes[0]["crop_identity"]["crop_policy"] == "predicted_visible_region"
        assert outcomes[2]["crop_identity"]["status"] == "unusable"
        assert outcomes[2]["unusable_reason"] == "face_down"
        assert outcomes[3]["crop_identity"]["status"] == "usable"
        assert outcomes[3]["error"] == "The visual identity classifier failed for this card."
        assert sorted(request.card_id for request in provider.requests[-3:]) == sorted(
            ["card-classified", "card-empty", "card-failed"]
        )

    restarted = create_test_app(
        _settings(tmp_path),
        visible_card_identity_classifier=_IdentityProvider(),
        visible_card_frame_resolver=_FrameResolver(),
    )
    with TestClient(restarted) as client:
        persisted = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/identity-completed/result"
        )
        assert persisted.status_code == 200
        assert [
            outcome["status"] for outcome in persisted.json()["revisions"][0]["content"]["outcomes"]
        ] == ["classified", "unusable", "unusable", "failed"]


def test_visual_identity_pipeline_retry_resumes_retained_items(tmp_path: Any) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=_IdentityProvider(),
    )

    with TestClient(app) as client:
        event_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json={"run_id": "events-for-identity-retry"},
        )
        assert event_response.status_code == 202
        _wait_event(client, "events-for-identity-retry")
        event_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/events-for-identity-retry/result"
        ).json()["state"]["output_revision_ids"][0]

        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-for-identity-retry",
                "event_revision_id": event_revision_id,
            },
        )
        assert visible_response.status_code == 202
        assert _wait(client, "visible-for-identity-retry")["state"]["status"] == "complete"
        visible_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/visible-for-identity-retry/result"
        ).json()
        visible_revision_id = visible_result["state"]["output_revision_ids"][0]
        visible_revision = app.state.pipeline_revision_store.require(visible_revision_id)
        manual_revision_id = _manual_visible_revision(
            app,
            visible_revision.manifest.source,
            visible_result["revisions"][0]["content"]["outcomes"][0]["frame_identity"],
        )

        baseline_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-retry-baseline",
                "input_revision_ids": [manual_revision_id],
            },
        )
        assert baseline_response.status_code == 202
        assert _wait_identity(client, "identity-retry-baseline")["state"]["status"] == "complete"
        baseline = app.state.pipeline_run_store.require("identity-retry-baseline")

        request = app.state.visual_identity_pipeline_service._build_request(
            RECORDING_ID,
            {"run_id": "identity-retry", "input_revision_ids": [manual_revision_id]},
        )
        stored, created = app.state.pipeline_run_store.create(request)
        assert created
        app.state.pipeline_run_store.start(stored.run_id)
        app.state.pipeline_run_store.partial(
            stored.run_id,
            progress=RunProgress(completed=2, total=4),
            items=baseline.state.items[:2],
        )

        retry_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/identity-retry/retry"
        )
        assert retry_response.status_code == 202
        status = _wait_identity(client, "identity-retry")

    assert status["state"]["status"] == "complete"
    assert status["state"]["progress"] == {"completed": 4, "total": 4}
    assert len(status["state"]["items"]) == 4


def test_visual_identity_candidates_are_bounded_and_ordered(tmp_path: Any) -> None:
    _install_recording(tmp_path)
    active = 0
    maximum = 0
    lock = threading.Lock()
    started_two = threading.Event()
    release = threading.Event()

    class BlockingIdentityProvider:
        name = "blocking-identity"
        version = "blocking-identity/v1"
        model = "blocking-model/v1"

        def classify(self, request: VisualIdentityRequest) -> CardClassificationResult:
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
                if active == 2:
                    started_two.set()
            try:
                assert release.wait(2)
                if request.card_id.endswith("failed"):
                    return CardClassificationResult(status="unavailable", error="fixture failure")
                if request.card_id.endswith("empty"):
                    return CardClassificationResult(status="ok", candidates=())
                return CardClassificationResult(
                    status="ok",
                    candidates=(IdentityCandidate(card="CLUBS_NINE", probability=1.0),),
                )
            finally:
                with lock:
                    active -= 1

    app = create_test_app(
        _settings(tmp_path, gemini_max_concurrent_requests=2),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=BlockingIdentityProvider(),
    )
    with TestClient(app) as client:
        event_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/events",
            json={"run_id": "events-for-identity-blocking"},
        )
        assert event_response.status_code == 202
        _wait_event(client, "events-for-identity-blocking")
        event_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/events-for-identity-blocking/result"
        ).json()["state"]["output_revision_ids"][0]
        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-for-identity-blocking",
                "event_revision_id": event_revision_id,
            },
        )
        assert visible_response.status_code == 202
        assert _wait(client, "visible-for-identity-blocking")["state"]["status"] == "complete"
        visible_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/visible-for-identity-blocking/result"
        ).json()
        visible_revision_id = visible_result["state"]["output_revision_ids"][0]
        source = app.state.pipeline_revision_store.require(visible_revision_id).manifest.source
        manual_revision_id = _manual_visible_revision(
            app,
            source,
            visible_result["revisions"][0]["content"]["outcomes"][0]["frame_identity"],
        )
        identity_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-blocking",
                "input_revision_ids": [manual_revision_id],
            },
        )
        assert identity_response.status_code == 202
        assert started_two.wait(2)
        assert maximum == 2
        release.set()
        assert _wait_identity(client, "identity-blocking")["state"]["status"] == "complete"
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/identity-blocking/result"
        ).json()

    outcomes = result["revisions"][0]["content"]["outcomes"]
    assert [outcome["card_id"] for outcome in outcomes] == [
        "card-classified",
        "card-empty",
        "card-unusable",
        "card-failed",
    ]
    assert [outcome["status"] for outcome in outcomes] == [
        "classified",
        "unusable",
        "unusable",
        "failed",
    ]
    assert [item["item_id"] for item in result["state"]["items"]] == [
        "card-classified",
        "card-empty",
        "card-unusable",
        "card-failed",
    ]
    assert result["state"]["progress"] == {"completed": 4, "total": 4}


def _wait_identity(client: TestClient, run_id: str) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + 5
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{run_id}")
        body = response.json()
        if body["state"]["status"] in {"complete", "failed"}:
            return body
        time.sleep(0.01)
    return body
