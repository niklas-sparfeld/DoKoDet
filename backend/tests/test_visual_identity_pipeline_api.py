from __future__ import annotations

import json
import shutil
import threading
from types import SimpleNamespace
from typing import Any

from app_factory import create_test_app
from doko_operations.derived_view import crop_jpeg_preview_cache_key_for_source_digest
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

from dokodetector_backend import (
    visual_identity_pipeline_service as visual_identity_pipeline_service_module,
)
from dokodetector_backend.visual_identity_pipeline_service import VisualIdentityPipelineService


class _IdentityProvider:
    name = "fixture-identity"
    version = "fixture-identity/v1"
    model = "fixture-model/v1"

    def __init__(self) -> None:
        self.requests: list[VisualIdentityRequest] = []

    def classify(self, request: VisualIdentityRequest) -> CardClassificationResult:
        self.requests.append(request)
        if request.card_id.endswith("empty"):
            return CardClassificationResult(status="ok", classification="unknown")
        if request.card_id.endswith("failed"):
            return CardClassificationResult(status="unavailable", error="fixture failure")
        return CardClassificationResult(
            status="ok",
            candidates=(
                IdentityCandidate(card="CLUBS_NINE", probability=0.75),
                IdentityCandidate(card="SPADES_NINE", probability=0.25),
            ),
        )


class _LocalPpmIdentityClassifier:
    name = "local-dinov3"
    version = "dinov3-local-identity-test-v1"
    model = "facebook/dinov3-vits16-pretrain-lvd1689m"
    calibration = "uncalibrated"

    def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
        raise AssertionError("the resolver test must not classify a crop")


def test_auto_approval_reason_requires_matching_classified_outcomes() -> None:
    classified = SimpleNamespace(
        status="classified", candidates=(SimpleNamespace(identity="CLUBS_NINE"),)
    )

    assert (
        VisualIdentityPipelineService._auto_approval_reason(
            "pending", classified, ("local-result", classified)
        )
        == "eligible"
    )
    assert (
        VisualIdentityPipelineService._auto_approval_reason(
            "accepted", classified, ("local-result", classified)
        )
        == "already_reviewed"
    )
    assert VisualIdentityPipelineService._auto_approval_reason("pending", classified, None) == (
        "local_unavailable"
    )


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


def test_auto_approval_plan_reuses_one_local_run_and_reports_matching_results(
    tmp_path: Any,
) -> None:
    _install_recording(tmp_path)
    gemini = _IdentityProvider()
    gemini.name = "gemini"
    local = _IdentityProvider()
    local.name = "local-dinov3"
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=gemini,
    )
    app.state.visual_identity_pipeline_service.identity_classifiers = {"local": local}

    with TestClient(app) as client:
        assert (
            client.post(
                f"/api/recordings/{RECORDING_ID}/pipeline/events", json={"run_id": "events-auto"}
            ).status_code
            == 202
        )
        _wait_event(client, "events-auto")
        assert (
            client.post(
                f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
                json={"run_id": "visible-auto"},
            ).status_code
            == 202
        )
        assert _wait(client, "visible-auto")["state"]["status"] == "complete"
        visible_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/visible-auto/result"
        ).json()["state"]["output_revision_ids"][0]
        assert (
            client.post(
                f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
                json={"run_id": "gemini-auto", "visible_card_revision_id": visible_revision_id},
            ).status_code
            == 202
        )
        assert _wait_identity(client, "gemini-auto")["state"]["status"] == "complete"
        gemini_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/gemini-auto/result"
        ).json()["state"]["output_revision_ids"][0]
        assert (
            client.post(
                f"/api/recordings/{RECORDING_ID}/pipeline/references/visual_identities",
                json={"operator_id": "operator-1", "source_revision_id": gemini_revision_id},
            ).status_code
            == 201
        )
        selection_path = f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/selection"
        assert (
            client.get(selection_path).json()["selection"]["selected_generated_revision_id"]
            == gemini_revision_id
        )

        path = f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/auto-approval-plan"
        first = client.post(path)
        assert first.status_code == 202, first.text
        local_run_id = first.json()["local_run"]["run_id"]
        assert _wait_identity(client, local_run_id)["state"]["status"] == "complete"
        repeated = client.post(path)
        assert repeated.status_code == 202, repeated.text
        assert repeated.json()["local_run"] is None
        assert (
            client.get(selection_path).json()["selection"]["selected_generated_revision_id"]
            == gemini_revision_id
        )
        planned = client.post(path)
        assert planned.status_code == 202, planned.text
        items = planned.json()["items"]
        assert items[0]["reason"] == "eligible"
        assert items[0]["gemini_result"]["result_id"] == gemini_revision_id
        assert items[0]["local_result"]["classifier"]["provider"] == "local-dinov3"
        accepted = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/auto-approval",
            json={
                "expected_revision": planned.json()["draft_revision"],
                "operator_id": "operator-1",
                "command_id": "auto-approve-1",
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["accepted_item_ids"] == [items[0]["item_id"]]
        retry = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/auto-approval",
            json={
                "expected_revision": planned.json()["draft_revision"],
                "operator_id": "operator-1",
                "command_id": "auto-approve-1",
            },
        )
        assert retry.json() == accepted.json()
        reference = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/references/visual_identities"
        ).json()
        assert reference["draft"]["items"][0]["review_state"] == "accepted"

    restarted = create_test_app(_settings(tmp_path))
    with TestClient(restarted) as client:
        after_restart = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/auto-approval",
            json={
                "expected_revision": planned.json()["draft_revision"],
                "operator_id": "operator-1",
                "command_id": "auto-approve-1",
            },
        )
        assert after_restart.status_code == 200, after_restart.text
        assert after_restart.json() == accepted.json()


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


def test_visual_identity_resolves_concrete_local_classifier_name_from_local_registry(
    tmp_path: Any,
) -> None:
    app = create_test_app(
        _settings(tmp_path),
        visible_card_identity_classifier=_IdentityProvider(),
    )
    service = app.state.visual_identity_pipeline_service
    service.classifier = None
    service.identity_classifiers = {"local": _LocalPpmIdentityClassifier()}

    resolved = service._classifier_for_selection("local-dinov3")

    assert resolved is not None
    assert resolved.name == "local-dinov3"


def test_visual_identity_reuses_run_source_validation_for_each_card(
    tmp_path: Any, monkeypatch: Any
) -> None:
    _install_recording(tmp_path)
    resolve_calls: list[bool | None] = []
    original_resolve_exact_event = visual_identity_pipeline_service_module.resolve_exact_event

    def record_resolve_call(*args: object, **kwargs: object) -> object:
        resolve_calls.append(kwargs.get("validate_source"))
        return original_resolve_exact_event(*args, **kwargs)

    monkeypatch.setattr(
        visual_identity_pipeline_service_module,
        "resolve_exact_event",
        record_resolve_call,
    )
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
            json={"run_id": "events-for-identity-source-validation"},
        )
        assert event_response.status_code == 202
        _wait_event(client, "events-for-identity-source-validation")
        event_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/events/"
            "events-for-identity-source-validation/result"
        ).json()["state"]["output_revision_ids"][0]

        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-for-identity-source-validation",
                "event_revision_id": event_revision_id,
            },
        )
        assert visible_response.status_code == 202
        assert _wait(client, "visible-for-identity-source-validation")["state"]["status"] == (
            "complete"
        )
        visible_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/"
            "visible-for-identity-source-validation/result"
        ).json()["state"]["output_revision_ids"][0]

        identity_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-source-validation",
                "input_revision_ids": [visible_revision_id],
            },
        )
        assert identity_response.status_code == 202
        assert _wait_identity(client, "identity-source-validation")["state"]["status"] == (
            "complete"
        )

    assert resolve_calls
    assert set(resolve_calls) == {False}


def test_visual_identity_pipeline_uses_generated_and_completed_geometry_and_restarts(
    tmp_path: Any, monkeypatch: Any
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

        service = app.state.visual_identity_pipeline_service
        preview_path = (
            service.storage.derived_views_root
            / crop_jpeg_preview_cache_key_for_source_digest(
                generated_outcome["crop_identity"]["image_sha256"]
            )
        )
        assert not preview_path.exists()
        warm_preview = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
            f"{identity_revision_id}/{generated_outcome['card_id']}?preview=browser"
        )
        assert warm_preview.status_code == 200, warm_preview.text
        assert warm_preview.headers["content-type"] == "image/jpeg"
        assert preview_path.is_dir()
        for entry in service.storage.derived_views_root.iterdir():
            manifest_path = entry / "manifest.json"
            if (
                entry.is_dir()
                and manifest_path.is_file()
                and json.loads(manifest_path.read_text(encoding="utf-8")).get("view_kind")
                != "visible-region-crop-jpeg-preview/v1"
            ):
                shutil.rmtree(entry)

        def fail_if_canonical_resolution(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("warm browser preview must not resolve the canonical crop")

        with monkeypatch.context() as cached_patch:
            cached_patch.setattr(service, "resolve_identity_crop", fail_if_canonical_resolution)
            cached_only_preview = client.get(
                f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
                f"{identity_revision_id}/{generated_outcome['card_id']}?preview=browser"
            )
        assert cached_only_preview.status_code == 200, cached_only_preview.text
        assert cached_only_preview.headers["content-type"] == "image/jpeg"

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

        preview_path.joinpath("content.bin").write_bytes(b"corrupt preview")
        resolve_calls = 0
        original_resolve_identity_crop = service.resolve_identity_crop

        def count_canonical_resolution(*args: object, **kwargs: object) -> object:
            nonlocal resolve_calls
            resolve_calls += 1
            return original_resolve_identity_crop(*args, **kwargs)

        monkeypatch.setattr(service, "resolve_identity_crop", count_canonical_resolution)
        regenerated_preview = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
            f"{identity_revision_id}/{generated_outcome['card_id']}?preview=browser"
        )
        assert regenerated_preview.status_code == 200, regenerated_preview.text
        assert regenerated_preview.headers["content-type"] == "image/jpeg"
        assert regenerated_preview.content.startswith(b"\xff\xd8\xff")
        assert resolve_calls == 1
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
            "face_down",
            "failed",
        ]
        assert outcomes[1]["geometry"]["kind"] == "reviewed-visible-region/v1"
        assert outcomes[1]["candidates"] == []
        assert outcomes[1]["unusable_reason"] == "The classifier returned no identity candidates."
        assert outcomes[0]["status"] == "classified"
        assert outcomes[0]["crop_identity"]["crop_policy"] == "predicted_visible_region"
        assert outcomes[2]["status"] == "face_down"
        assert outcomes[2]["candidates"] == []
        assert outcomes[2]["unusable_reason"] is None
        assert outcomes[3]["crop_identity"]["status"] == "usable"
        assert outcomes[3]["error"] == "fixture failure"
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
        ] == ["classified", "unusable", "face_down", "failed"]


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
        "face_down",
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
