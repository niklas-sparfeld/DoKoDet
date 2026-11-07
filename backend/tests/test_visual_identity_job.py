from __future__ import annotations

import math
import threading
from typing import Any
from uuid import uuid4

from app_factory import create_test_app
from doko_operations.pipeline_data import ProcessorRunRequest, RunProgress
from fastapi.testclient import TestClient
from table_evidence_analyzer import CardClassificationResult, VisualIdentityRequest
from test_visible_card_pipeline_api import _enqueue_event, _wait_event
from test_visual_identity_pipeline_api import (
    RECORDING_ID,
    _Detector,
    _EventProvider,
    _fixture_generated_visible_revision,
    _FrameResolver,
    _IdentityProvider,
    _install_recording,
    _node_input,
    _run_event_job,
    _selected_node_input,
    _settings,
    _wait,
    _wait_identity,
)

from dokodetector_backend.job_models import CancellationToken


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
        event_revision_id = _run_event_job(client, "events-for-identity-retry")

        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-for-identity-retry",
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
        visible_revision = app.state.pipeline_selection_store.require_processor_revision(
            visible_revision_id
        )
        fixture_revision_id = _fixture_generated_visible_revision(
            app,
            visible_revision.manifest.source,
            visible_result["revisions"][0]["content"]["outcomes"][0]["frame_identity"],
            visible_run_id,
        )

        baseline_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-retry-baseline",
                **_node_input(app, fixture_revision_id),
            },
        )
        assert baseline_response.status_code == 202
        baseline_run_id = baseline_response.json()["run_id"]
        assert _wait_identity(client, baseline_run_id)["state"]["status"] == "complete"
        baseline = app.state.pipeline_run_store.require(baseline_run_id)

        job_service = app.state.job_manager_service
        assert job_service.scheduler is not None
        job_service.scheduler.__exit__(None, None, None)
        job_service.scheduler = None
        manager = job_service.get_manager()
        retry_source_id = str(uuid4())
        request = app.state.visual_identity_pipeline_service._build_request(
            RECORDING_ID,
            {"run_id": retry_source_id, **_node_input(app, fixture_revision_id)},
        )
        source_job = manager.accept(
            str(uuid4()),
            {
                "type": "visual_identity_classification",
                "context": {"recording_id": RECORDING_ID},
                "request": {
                    "schema": "visual-identity-job-request/v1",
                    "processor_request": request.to_mapping(),
                },
            },
        )
        manager.transition(source_job.id, "running")
        app.state.pipeline_run_store.start(source_job.id)
        app.state.pipeline_run_store.partial(
            source_job.id,
            progress=RunProgress(completed=2, total=4),
            items=baseline.state.items[:2],
        )
        manager.transition(source_job.id, "failed")

        retry_response = client.post(
            f"/api/jobs/{source_job.id}/retry",
            headers={"Idempotency-Key": str(uuid4())},
            json={},
        )
        assert retry_response.status_code == 202
        retry_run_id = retry_response.json()["id"]
        retry_job = manager.get(retry_run_id)
        manager.transition(retry_run_id, "running")
        app.state.job_type_registry.handle(
            retry_job,
            app.state.job_type_registry.claims_for(retry_job),
            CancellationToken(),
        )
        assert manager.get(retry_run_id).state == "succeeded"
        status = _wait_identity(client, retry_run_id)
        retry_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{retry_run_id}/result"
        ).json()

    assert status["state"]["status"] == "complete"
    assert status["state"]["progress"] == {"completed": 4, "total": 4}
    assert len(status["revisions"][0]["content"]["outcomes"]) == 4
    assert status["request"]["crop_input"] == request.crop_input
    assert all(
        outcome["crop_input_provenance"]["manifest_digest"] == request.crop_input["manifest_digest"]
        for outcome in retry_result["revisions"][0]["content"]["outcomes"]
    )


def test_visual_identity_classification_runs_as_a_managed_job(
    tmp_path: Any, monkeypatch: Any
) -> None:
    _install_recording(tmp_path)
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=_IdentityProvider(),
    )

    with TestClient(app) as client:
        event_response = _enqueue_event(client, {"run_id": "events-for-managed-identity"})
        assert event_response.status_code == 202, event_response.text
        event_job_id = event_response.json()["id"]
        _wait_event(client, event_job_id)
        event_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/{event_job_id}/result"
        ).json()["state"]["output_revision_ids"][0]

        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-for-managed-identity",
                **_selected_node_input(client, "events", event_revision_id),
                "configuration": {"threshold": 0.5},
            },
        )
        assert visible_response.status_code == 202, visible_response.text
        visible_run_id = visible_response.json()["run_id"]
        visible_result = _wait(client, visible_run_id)
        visible_revision_id = visible_result["state"]["output_revision_ids"][0]

        identity_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-managed",
                **_selected_node_input(client, "visible_cards", visible_revision_id),
            },
        )
        assert identity_response.status_code == 202, identity_response.text
        identity_job_id = identity_response.json()["run_id"]
        identity_job = _wait_event(client, identity_job_id)
        identity_job_record = client.get(f"/api/jobs/{identity_job_id}").json()
        identity_run = identity_job_record
        service = app.state.visual_identity_pipeline_service

        assert not hasattr(service, "revision_store")
        canonical_input = service.canonical_input_revision(
            ProcessorRunRequest.from_mapping(identity_run["request"]["processor_request"])
        )

    assert identity_job["state"]["status"] == "complete"
    assert identity_job_record["state"] == "succeeded"
    assert identity_job_record["inputs"][0]["id"] == visible_revision_id
    assert identity_run["state"] == "succeeded"
    assert identity_run["request"]["processor_request"]["input_revision_ids"] == [
        visible_revision_id
    ]
    assert len(identity_run["request"]["processor_request"]["input_node_refs"]) == 1
    assert identity_run["request"]["processor_request"]["input_node_refs"][0]["revision_id"]
    assert canonical_input.manifest.revision_id == visible_revision_id
    _, revisions = service.get_result(RECORDING_ID, identity_job_id)
    assert len(revisions) == 1
    for outcome in revisions[0].content.outcomes:
        if outcome.status != "classified":
            continue
        probabilities = [candidate.score for candidate in outcome.candidates]
        assert all(score is not None and math.isfinite(score) for score in probabilities)
        assert math.isclose(sum(probabilities), 1.0, abs_tol=1e-9)


def test_identity_cancellation_wins_at_publication_arbitration(
    tmp_path: Any, monkeypatch: Any
) -> None:
    _install_recording(tmp_path)
    classifier_entered = threading.Event()
    release_classifier = threading.Event()

    class BlockingIdentityProvider:
        name = "blocking-identity"
        version = "blocking-identity/v1"
        model = "blocking-model/v1"

        def classify(self, request: VisualIdentityRequest) -> CardClassificationResult:
            classifier_entered.set()
            assert release_classifier.wait(3)
            from table_evidence_analyzer.table_observation import IdentityCandidate

            return CardClassificationResult(
                status="ok",
                candidates=(IdentityCandidate(card="CLUBS_NINE", probability=1.0),),
            )

    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=BlockingIdentityProvider(),
    )
    with TestClient(app) as client:
        event_revision_id = _run_event_job(client, "events-before-cancel-race")
        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-before-cancel-race",
                **_selected_node_input(client, "events", event_revision_id),
            },
        )
        assert visible_response.status_code == 202, visible_response.text
        visible_run_id = visible_response.json()["run_id"]
        visible_result = _wait(client, visible_run_id)
        assert visible_result["state"]["status"] == "complete"
        visible_revision_id = visible_result["state"]["output_revision_ids"][0]

        service = app.state.visual_identity_pipeline_service
        manager = app.state.job_manager_service.get_manager()
        existing_selection = service.selection_store.get_exact(RECORDING_ID, "visual_identities")
        original_publish = manager.publish
        identity_job_id: str | None = None

        def cancel_before_publish(job_id: str, results: list[dict[str, Any]], commit: Any) -> bool:
            if job_id == identity_job_id:
                manager.cancel(job_id)
            return original_publish(job_id, results, commit)

        monkeypatch.setattr(manager, "publish", cancel_before_publish)
        started = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-cancel-race",
                **_selected_node_input(client, "visible_cards", visible_revision_id),
            },
        )
        assert started.status_code == 202, started.text
        identity_job_id = started.json()["run_id"]
        assert classifier_entered.wait(2)
        release_classifier.set()

        job = _wait_event(client, identity_job_id)
        run = service.run_store.require(identity_job_id)
        selection_after = service.selection_store.get_exact(RECORDING_ID, "visual_identities")

    assert job["state"]["status"] == "cancelled"
    assert run.state.status == "failed"
    assert run.state.terminal_failure is not None
    assert run.state.terminal_failure.code == "cancelled"
    assert run.state.output_revision_ids == ()
    assert selection_after == existing_selection


def test_visual_identity_run_listing_uses_recording_scoped_storage(
    tmp_path: Any, monkeypatch: Any
) -> None:
    app = create_test_app(_settings(tmp_path))
    service = app.state.visual_identity_pipeline_service
    calls: list[str] = []

    def fail_broad_listing() -> object:
        raise AssertionError("visual identity listing must be recording-scoped")

    monkeypatch.setattr(service.run_store, "list", fail_broad_listing)
    monkeypatch.setattr(
        service.run_store,
        "list_for_recording",
        lambda recording_id: calls.append(recording_id) or (),
    )

    assert service.list_runs(RECORDING_ID) == ()
    assert calls == [RECORDING_ID]
