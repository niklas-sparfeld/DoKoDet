from __future__ import annotations

import threading
import time
from typing import Any

from app_factory import create_test_app
from fastapi.testclient import TestClient
from table_evidence_analyzer import CardClassificationResult, VisualIdentityRequest
from table_evidence_analyzer.table_observation import IdentityCandidate
from test_visual_identity_pipeline_api import (
    RECORDING_ID,
    _Detector,
    _EventProvider,
    _fixture_generated_visible_revision,
    _FrameResolver,
    _IdentityProvider,
    _install_recording,
    _LocalPpmIdentityClassifier,
    _node_input,
    _run_event_job,
    _selected_node_input,
    _settings,
    _wait,
    _wait_identity,
)

from dokodetector_backend import (
    visual_identity_classification as visual_identity_classification_module,
)


def test_visual_identity_candidates_are_bounded_and_ordered(
    tmp_path: Any, monkeypatch: Any
) -> None:
    _install_recording(tmp_path)
    active = 0
    maximum = 0
    lock = threading.Lock()
    started_one = threading.Event()
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
                started_one.set()
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
        event_revision_id = _run_event_job(client, "events-for-identity-blocking")
        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-for-identity-blocking",
                **_selected_node_input(client, "events", event_revision_id),
            },
        )
        assert visible_response.status_code == 202
        visible_run_id = visible_response.json()["run_id"]
        assert _wait(client, visible_run_id)["state"]["status"] == "complete"
        visible_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{visible_run_id}/result"
        ).json()
        visible_revision_id = visible_result["state"]["output_revision_ids"][0]
        source = app.state.pipeline_selection_store.require_processor_revision(
            visible_revision_id
        ).manifest.source
        fixture_revision_id = _fixture_generated_visible_revision(
            app,
            source,
            visible_result["revisions"][0]["content"]["outcomes"][0]["frame_identity"],
            visible_run_id,
        )
        resolve_calls = []
        original_resolve = visual_identity_classification_module.resolve_exact_event

        def record_frame(*args: Any, **kwargs: Any) -> Any:
            resolve_calls.append(1)
            return original_resolve(*args, **kwargs)

        monkeypatch.setattr(
            visual_identity_classification_module, "resolve_exact_event", record_frame
        )
        identity_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-blocking",
                **_node_input(app, fixture_revision_id),
            },
        )
        assert identity_response.status_code == 202, identity_response.text
        identity_run_id = identity_response.json()["run_id"]
        assert started_one.wait(2)
        time.sleep(0.05)
        assert maximum == 1
        release.set()
        assert _wait_identity(client, identity_run_id)["state"]["status"] == "complete"
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{identity_run_id}/result"
        ).json()
        assert len(resolve_calls) == 1

    outcomes = result["revisions"][0]["content"]["outcomes"]
    assert [outcome["card_id"] for outcome in outcomes] == [
        "card-classified",
        "card-empty",
        "card-failed",
        "card-unusable",
    ]
    assert [outcome["status"] for outcome in outcomes] == [
        "classified",
        "unusable",
        "failed",
        "face_down",
    ]
    stored_identity_run = app.state.pipeline_run_store.require(identity_run_id, include_items=True)
    assert [item.item_id for item in stored_identity_run.state.items] == [
        "card-classified",
        "card-empty",
        "card-failed",
        "card-unusable",
    ]
    assert stored_identity_run.state.progress.to_mapping() == {"completed": 4, "total": 4}


def test_visual_identity_resolves_concrete_local_classifier_name_from_local_registry(
    tmp_path: Any,
) -> None:
    app = create_test_app(
        _settings(tmp_path),
        visible_card_identity_classifier=_IdentityProvider(),
    )
    service = app.state.visual_identity_pipeline_service
    service.classification.classifier = None
    service.classification.identity_classifiers = {"local": _LocalPpmIdentityClassifier()}

    resolved = service._classifier_for_selection("local-dinov3")

    assert resolved is not None
    assert resolved.name == "local-dinov3"
