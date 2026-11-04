from __future__ import annotations

import json
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from app_factory import create_test_app
from doko_operations.derived_view import crop_jpeg_preview_cache_key_for_source_digest
from doko_operations.pipeline_data import (
    DataRevision,
    HumanProducer,
    ProcessorProducer,
    RecordingVideoSource,
    RunProgress,
    sha256_bytes,
)
from fastapi.testclient import TestClient
from table_evidence_analyzer import (
    CardClassificationResult,
    PredictedVisibleRegionGeometry,
    VisibleCardCandidate,
    VisibleCardData,
    VisibleCardFrameIdentity,
    VisibleCardOutcome,
    VisualIdentityRequest,
    canonical_visible_card_data_bytes,
)
from table_evidence_analyzer.pipeline_data import VisibleCardPileRegion
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
from dokodetector_backend.visual_identity_pipeline_service import (
    VisualIdentityPipelineError,
    VisualIdentityPipelineService,
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


def test_duplicate_source_card_ids_get_stable_frame_scoped_identity_ids() -> None:
    items = (
        SimpleNamespace(
            card_id="manual-card-1",
            frame_identity=SimpleNamespace(frame_index=2671),
        ),
        SimpleNamespace(
            card_id="manual-card-1",
            frame_identity=SimpleNamespace(frame_index=3285),
        ),
        SimpleNamespace(
            card_id="pose-card-1",
            frame_identity=SimpleNamespace(frame_index=3285),
        ),
    )

    item_ids = VisualIdentityPipelineService._identity_item_ids(items)

    assert item_ids == VisualIdentityPipelineService._identity_item_ids(items)
    assert len(item_ids) == len(set(item_ids))
    assert item_ids[0].startswith("manual-card-1-frame-2671-")
    assert item_ids[1].startswith("manual-card-1-frame-3285-")
    assert item_ids[2] == "pose-card-1"


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


def _fixture_generated_visible_revision(
    app: Any, source: Any, frame: dict[str, Any], producer_run_id: str
) -> str:
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
            geometry=PredictedVisibleRegionGeometry(
                polygons=(((100, 100), (900, 100), (900, 900), (100, 900)),)
            ),
            normalization={"width": 64, "height": 64, "policy_id": "fixture/v1"},
            side="unknown",
        ),
        VisibleCardCandidate(
            card_id="card-unusable",
            geometry=PredictedVisibleRegionGeometry(
                polygons=(((0, 0), (10, 0), (10, 10), (0, 10)),)
            ),
            normalization={"width": 64, "height": 64, "policy_id": "fixture/v1"},
            side="face_down",
        ),
        VisibleCardCandidate(
            card_id="card-failed",
            geometry=PredictedVisibleRegionGeometry(
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
        origin="processor",
        producer=ProcessorProducer(
            run_id=producer_run_id,
            processor_type="visible-card-detection",
            implementation_id="visible-card-detector-adapter.v1",
        ),
        coverage={"kind": "completed-reference", "card_ids": [item.card_id for item in candidates]},
        created_at="2026-01-01T00:00:00Z",
    )
    stored, _ = app.state.pipeline_revision_store.publish(manifest, content)
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
    crop_calls: list[str] = []
    original_resolve_exact_event = visual_identity_pipeline_service_module.resolve_exact_event
    original_resolve_visible_region_crop = (
        visual_identity_pipeline_service_module.resolve_visible_region_crop
    )

    def record_resolve_call(*args: object, **kwargs: object) -> object:
        resolve_calls.append(kwargs.get("validate_source"))
        return original_resolve_exact_event(*args, **kwargs)

    def record_crop_call(*args: object, **kwargs: object) -> object:
        crop_calls.append("crop")
        return original_resolve_visible_region_crop(*args, **kwargs)

    monkeypatch.setattr(
        visual_identity_pipeline_service_module,
        "resolve_exact_event",
        record_resolve_call,
    )
    monkeypatch.setattr(
        visual_identity_pipeline_service_module,
        "resolve_visible_region_crop",
        record_crop_call,
    )
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

        visible_revision = app.state.pipeline_revision_store.require(visible_revision_id)
        frame_identity = visible_revision.content.outcomes[0].frame_identity
        assert frame_identity is not None
        pile = VisibleCardPileRegion.from_mapping(
            {
                "pile_id": "pile-identity-isolation",
                "geometry": {
                    "kind": "pile-region/v1",
                    "polygons": [
                        [
                            {"x": 100, "y": 200},
                            {"x": 400, "y": 200},
                            {"x": 400, "y": 600},
                            {"x": 100, "y": 600},
                        ]
                    ],
                },
                "normalization": {
                    "width": 64,
                    "height": 64,
                    "policy_id": "full-frame-0-1000/v1",
                },
                "source_candidates": [],
                "origin": "model_prediction",
                "confidence": 0.9,
                "model_lineage": {"bundle_id": "pile-fixture"},
            }
        )
        pile_content = replace(
            visible_revision.content,
            outcomes=(replace(visible_revision.content.outcomes[0], pile_regions=(pile,)),),
        )
        pile_manifest = replace(
            visible_revision.manifest,
            revision_id="visible-revision-with-pile",
            content_sha256=sha256_bytes(canonical_visible_card_data_bytes(pile_content)),
        )
        app.state.pipeline_revision_store.publish(pile_manifest, pile_content)

        identity_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-source-validation",
                "input_revision_ids": ["visible-revision-with-pile"],
            },
        )
        assert identity_response.status_code == 202, identity_response.text
        assert _wait_identity(client, "identity-source-validation")["state"]["status"] == (
            "complete"
        )
        identity_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/"
            "identity-source-validation/result"
        ).json()
        assert {item["card_id"] for item in identity_result["request"]["crop_input"]["items"]} == {
            candidate.card_id for candidate in pile_content.outcomes[0].candidates
        }
        pile_only_content = replace(
            pile_content,
            outcomes=(
                replace(
                    pile_content.outcomes[0],
                    status="detected",
                    candidates=(),
                ),
            ),
        )
        pile_only_manifest = replace(
            pile_manifest,
            revision_id="visible-pile-only",
            content_sha256=sha256_bytes(canonical_visible_card_data_bytes(pile_only_content)),
        )
        app.state.pipeline_revision_store.publish(pile_only_manifest, pile_only_content)
        pile_only_identity = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-pile-only",
                "input_revision_ids": ["visible-pile-only"],
            },
        )
        assert pile_only_identity.status_code == 202, pile_only_identity.text
        assert _wait_identity(client, "identity-pile-only")["state"]["status"] == "complete"
        pile_only_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/identity-pile-only/result"
        ).json()
        assert pile_only_result["request"]["crop_input"]["items"] == []
        assert pile_only_result["revisions"][0]["content"]["outcomes"] == []

        mixed_content = replace(
            visible_revision.content,
            outcomes=(
                visible_revision.content.outcomes[0],
                replace(
                    visible_revision.content.outcomes[0],
                    event_id="event-without-card-candidates",
                    frame_identity=replace(
                        frame_identity, frame_index=frame_identity.frame_index + 1
                    ),
                    status="empty",
                    candidates=(),
                ),
            ),
        )
        mixed_manifest = replace(
            visible_revision.manifest,
            revision_id="visible-mixed-card-and-empty",
            content_sha256=sha256_bytes(canonical_visible_card_data_bytes(mixed_content)),
        )
        app.state.pipeline_revision_store.publish(mixed_manifest, mixed_content)
        mixed_identity = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-mixed-card-and-empty",
                "input_revision_ids": ["visible-mixed-card-and-empty"],
            },
        )
        assert mixed_identity.status_code == 202, mixed_identity.text
        assert _wait_identity(client, "identity-mixed-card-and-empty")["state"]["status"] == (
            "complete"
        )
        mixed_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/"
            "identity-mixed-card-and-empty/result"
        ).json()
        assert {item["card_id"] for item in mixed_result["request"]["crop_input"]["items"]} == {
            candidate.card_id for candidate in visible_revision.content.outcomes[0].candidates
        }
        candidate_crop_count = len(crop_calls)
        candidate_model_call_count = len(provider.requests)
        candidate_frame_resolve_count = len(resolve_calls)

        empty_content = replace(
            pile_content,
            outcomes=(
                replace(
                    pile_content.outcomes[0],
                    status="empty",
                    candidates=(),
                    pile_regions=(),
                ),
            ),
        )
        empty_manifest = replace(
            pile_manifest,
            revision_id="visible-empty",
            content_sha256=sha256_bytes(canonical_visible_card_data_bytes(empty_content)),
        )
        app.state.pipeline_revision_store.publish(empty_manifest, empty_content)
        empty_identity = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={"run_id": "identity-empty", "input_revision_ids": ["visible-empty"]},
        )
        assert empty_identity.status_code == 202, empty_identity.text
        assert _wait_identity(client, "identity-empty")["state"]["status"] == "complete"
        empty_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/identity-empty/result"
        ).json()
        assert empty_result["request"]["crop_input"]["items"] == []
        assert empty_result["revisions"][0]["content"]["outcomes"] == []
        assert len(crop_calls) == candidate_crop_count
        assert len(provider.requests) == candidate_model_call_count
        assert len(resolve_calls) == candidate_frame_resolve_count

    assert resolve_calls
    assert set(resolve_calls) == {False}


def test_visual_identity_pipeline_uses_generated_geometry_and_restarts(
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
        implicit_input = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={"run_id": "identity-implicit-input"},
        )
        assert implicit_input.status_code == 422
        fixture_revision_id = _fixture_generated_visible_revision(
            app,
            app.state.pipeline_revision_store.require(generated_revision_id).manifest.source,
            generated_content["outcomes"][0]["frame_identity"],
            "visible-generated",
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
        assert generated_result["request"]["crop_input"]["input_kind"] == "gemini_polygon"
        assert generated_result["request"]["crop_input"]["source_revision_id"] == (
            generated_revision_id
        )
        assert (
            generated_outcome["crop_input_provenance"]["manifest_digest"]
            == (generated_result["request"]["crop_input"]["manifest_digest"])
        )
        assert generated_outcome["crop_input_provenance"]["input_kind"] == "gemini_polygon"
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
        generated_revision = app.state.pipeline_revision_store.require(generated_revision_id)
        original_require = service.run_store.require
        generated_run = original_require("visible-generated")
        rfdetr_run = SimpleNamespace(
            request=SimpleNamespace(
                configuration={
                    **generated_run.request.configuration,
                    "provider": "local-rfdetr-segmentation",
                }
            )
        )
        with monkeypatch.context() as source_patch:
            source_patch.setattr(
                service.run_store,
                "require",
                lambda run_id, **kwargs: (
                    rfdetr_run
                    if run_id == "visible-generated"
                    else original_require(run_id, **kwargs)
                ),
            )
            rfdetr_input = service._freeze_crop_input(
                RECORDING_ID,
                generated_revision,
                source=generated_revision.manifest.source,
            )
        assert rfdetr_input.input_kind == "rfdetr_segment"
        preview_path = (
            service.storage.derived_views_root
            / crop_jpeg_preview_cache_key_for_source_digest(
                generated_outcome["crop_identity"]["image_sha256"]
            )
        )
        assert not preview_path.exists()
        cold_validation_calls = 0
        cold_validate_provenance = service._validate_crop_input_provenance

        def count_cold_validation(*args: Any, **kwargs: Any) -> Any:
            nonlocal cold_validation_calls
            cold_validation_calls += 1
            return cold_validate_provenance(*args, **kwargs)

        with monkeypatch.context() as cold_patch:
            cold_patch.setattr(service, "_validate_crop_input_provenance", count_cold_validation)
            warm_preview = client.get(
                f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
                f"{identity_revision_id}/{generated_outcome['card_id']}?preview=browser"
            )
        assert cold_validation_calls == 1
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
            revision_reads: list[str] = []
            read_revision = service.revision_store._read_path

            def track_revision_read(path: Any, **kwargs: Any) -> Any:
                revision_reads.append(path.name)
                return read_revision(path, **kwargs)

            cached_patch.setattr(service.revision_store, "_read_path", track_revision_read)
            cached_only_preview = client.get(
                f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
                f"{identity_revision_id}/{generated_outcome['card_id']}?preview=browser"
            )
        assert cached_only_preview.status_code == 200, cached_only_preview.text
        assert cached_only_preview.headers["content-type"] == "image/jpeg"
        assert revision_reads == []

        # A warm JPEG must not hide changes to any validated dependency.
        preview_url = (
            f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
            f"{identity_revision_id}/{generated_outcome['card_id']}?preview=browser"
        )
        service._crop_contexts.clear()
        validation_calls = 0
        validate_provenance = service._validate_crop_input_provenance

        def count_validation(*args: Any, **kwargs: Any) -> Any:
            nonlocal validation_calls
            validation_calls += 1
            return validate_provenance(*args, **kwargs)

        with monkeypatch.context() as concurrent_patch:
            concurrent_patch.setattr(service, "_validate_crop_input_provenance", count_validation)
            with ThreadPoolExecutor(max_workers=6) as pool:
                responses = list(pool.map(lambda _: client.get(preview_url), range(6)))
        assert all(response.status_code == 200 for response in responses)
        assert validation_calls == 1

        dependency_files = [
            service.revision_store.revision_path(identity_revision_id) / "content.json",
            service.revision_store.revision_path(generated_revision_id) / "content.json",
            service.run_store.run_path("identity-generated") / "request.json",
            service._video_path(RECORDING_ID),
        ]
        for dependency in dependency_files:
            original = dependency.read_bytes()
            original_stat = dependency.stat()
            dependency.write_bytes(b"x" * len(original))
            os.utime(dependency, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            rejected = client.get(preview_url)
            assert rejected.status_code in {404, 409}, (dependency, rejected.text)
            dependency.write_bytes(original)
            restored = client.get(preview_url)
            assert restored.status_code == 200, (dependency, restored.text)

        added_member = service.revision_store.revision_path(generated_revision_id) / "extra.json"
        added_member.write_text("{}", encoding="utf-8")
        assert client.get(preview_url).status_code in {404, 409}
        added_member.unlink()
        assert client.get(preview_url).status_code == 200

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

        changed_manifest = dict(generated_result["request"]["crop_input"])
        changed_manifest["manifest_digest"] = "0" * 64
        changed_input = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-changed-crop-input",
                "input_revision_ids": [generated_revision_id],
                "crop_input": changed_manifest,
            },
        )
        assert changed_input.status_code == 422
        incompatible_policy = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-incompatible-policy",
                "input_revision_ids": [generated_revision_id],
                "crop_policy": {
                    "policy_id": "oracle_visible_region",
                    "output_encoding": "ppm",
                },
            },
        )
        assert incompatible_policy.status_code == 422

        completed_identity = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-completed",
                "input_revision_ids": [fixture_revision_id],
                "crop_policy": {
                    "policy_id": "predicted_visible_region",
                    "output_encoding": "ppm",
                },
            },
        )
        assert completed_identity.status_code == 202
        assert _wait_identity(client, "identity-completed")["state"]["status"] == "complete"
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/identity-completed/result"
        ).json()
        assert result["request"]["input_revision_ids"] == [fixture_revision_id]
        assert result["request"]["crop_policy"] == {
            "policy_id": "predicted_visible_region",
            "output_encoding": "ppm",
        }
        outcomes = result["revisions"][0]["content"]["outcomes"]
        by_card_id = {outcome["card_id"]: outcome for outcome in outcomes}
        assert [outcome["card_id"] for outcome in outcomes] == sorted(by_card_id)
        assert {card_id: outcome["status"] for card_id, outcome in by_card_id.items()} == {
            "card-classified": "classified",
            "card-empty": "unusable",
            "card-failed": "failed",
            "card-unusable": "face_down",
        }
        assert by_card_id["card-empty"]["geometry"]["kind"] == "visible-region/v1"
        assert by_card_id["card-empty"]["candidates"] == []
        assert by_card_id["card-empty"]["unusable_reason"] == (
            "The classifier returned no identity candidates."
        )
        assert by_card_id["card-classified"]["crop_identity"]["crop_policy"] == (
            "predicted_visible_region"
        )
        assert by_card_id["card-unusable"]["candidates"] == []
        assert by_card_id["card-unusable"]["unusable_reason"] is None
        assert by_card_id["card-failed"]["crop_identity"]["status"] == "usable"
        assert by_card_id["card-failed"]["error"] == "fixture failure"
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
        persisted_result = persisted.json()
        assert persisted_result["request"]["crop_input"] == result["request"]["crop_input"]
        assert {
            outcome["card_id"]: outcome["status"]
            for outcome in persisted_result["revisions"][0]["content"]["outcomes"]
        } == {
            "card-classified": "classified",
            "card-empty": "unusable",
            "card-failed": "failed",
            "card-unusable": "face_down",
        }


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
        fixture_revision_id = _fixture_generated_visible_revision(
            app,
            visible_revision.manifest.source,
            visible_result["revisions"][0]["content"]["outcomes"][0]["frame_identity"],
            "visible-for-identity-retry",
        )

        baseline_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-retry-baseline",
                "input_revision_ids": [fixture_revision_id],
            },
        )
        assert baseline_response.status_code == 202
        assert _wait_identity(client, "identity-retry-baseline")["state"]["status"] == "complete"
        baseline = app.state.pipeline_run_store.require("identity-retry-baseline")

        request = app.state.visual_identity_pipeline_service._build_request(
            RECORDING_ID,
            {"run_id": "identity-retry", "input_revision_ids": [fixture_revision_id]},
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
        retry_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/identity-retry/result"
        ).json()

    assert status["state"]["status"] == "complete"
    assert status["state"]["progress"] == {"completed": 4, "total": 4}
    assert len(status["state"]["items"]) == 4
    assert status["request"]["crop_input"] == request.crop_input
    assert all(
        outcome["crop_input_provenance"]["manifest_digest"] == request.crop_input["manifest_digest"]
        for outcome in retry_result["revisions"][0]["content"]["outcomes"]
    )


def test_visual_identity_candidates_are_bounded_and_ordered(
    tmp_path: Any, monkeypatch: Any
) -> None:
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
        fixture_revision_id = _fixture_generated_visible_revision(
            app,
            source,
            visible_result["revisions"][0]["content"]["outcomes"][0]["frame_identity"],
            "visible-for-identity-blocking",
        )
        resolve_calls = []
        original_resolve = visual_identity_pipeline_service_module.resolve_exact_event

        def record_frame(*args: Any, **kwargs: Any) -> Any:
            resolve_calls.append(1)
            return original_resolve(*args, **kwargs)

        monkeypatch.setattr(
            visual_identity_pipeline_service_module, "resolve_exact_event", record_frame
        )
        identity_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-blocking",
                "input_revision_ids": [fixture_revision_id],
            },
        )
        assert identity_response.status_code == 202, identity_response.text
        assert started_two.wait(2)
        assert maximum == 2
        release.set()
        assert _wait_identity(client, "identity-blocking")["state"]["status"] == "complete"
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/identity-blocking/result"
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
    assert [item["item_id"] for item in result["state"]["items"]] == [
        "card-classified",
        "card-empty",
        "card-failed",
        "card-unusable",
    ]
    assert result["state"]["progress"] == {"completed": 4, "total": 4}


def test_visual_identity_accepts_typed_card_scene_draft_views(tmp_path: Any) -> None:
    import pytest
    from doko_operations.card_plane_geometry import (
        CardPose,
        CardStackingOrder,
        ReviewedCardScene,
        derive_pose_scene_visible_regions,
    )
    from table_evidence_analyzer.card_scene_contract import (
        CardReviewState,
        CardSceneDraft,
        FrameReviewCompletion,
        ProposedCardScene,
        ReviewedCardSceneRecord,
    )

    digest = "a" * 64
    scene = ReviewedCardScene.create(
        source_frame_id="frame-01",
        source_frame_width=100,
        source_frame_height=100,
        calibration_revision_id="calibration-01",
        calibration_digest=digest,
        poses=[CardPose("card-01", (50.0, 50.0), 0.0, "suggestion-01", None)],
        stacking_order=CardStackingOrder(
            card_ids=("card-01",), uncertain_edges=(), contradictions=()
        ),
    )
    projection = {
        "table_to_image_homography": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "card_short_size": 20.0,
        "card_long_size": 30.0,
    }
    derivation = derive_pose_scene_visible_regions(scene, projection)
    proposal = ProposedCardScene.create(
        proposal_id="proposal-01",
        source_frame_id="frame-01",
        source_frame_digest=digest,
        detector_revision_id="detector-01",
        detector_revision_digest=digest,
        calibration_revision_id="calibration-01",
        calibration_digest=digest,
        initializer_recipe_version="initializer/v1",
        status="supported",
        initialized_scene=scene.to_mapping(),
        fit_diagnostics={"accepted": ["card-01"]},
    )
    draft = CardSceneDraft.create(
        proposal=proposal,
        reviewed=ReviewedCardSceneRecord.create(
            proposal_id=proposal.proposal_id,
            scene=scene.to_mapping(),
            decision="accepted",
        ),
        card_states=[
            CardReviewState.create(
                card_id="card-01",
                source="proposal",
                proposal_id=proposal.proposal_id,
                state="accepted",
            )
        ],
        completion=FrameReviewCompletion.create(state="complete", unresolved_card_ids=()),
        projection=projection,
        derived_region_receipt=derivation.receipt.to_mapping(),
    )
    region = derivation.regions[0]
    detected_outcome = VisibleCardOutcome(
        event_id="event-01",
        frame_identity=VisibleCardFrameIdentity.from_mapping(
            {
                "schema_version": "exact-event/v1",
                "policy": "exact-event/v1",
                "source_video_sha256": digest,
                "requested_time_us": 1_000_000,
                "presentation_timestamp_us": 1_000_000,
                "frame_index": 0,
                "width": 100,
                "height": 100,
                "image_sha256": digest,
                "content_type": "image/jpeg",
                "decoder_version": "ffmpeg/test",
                "transform_version": "ffmpeg-mjpeg/test",
                "output_encoding": "jpeg",
            }
        ),
        status="detected",
        candidates=(
            VisibleCardCandidate.from_mapping(
                {
                    "card_id": region["card_id"],
                    "geometry": region["geometry"],
                    "normalization": region["normalization"],
                    "side": "unknown",
                }
            ),
        ),
        ignored_regions=(),
        error=None,
        card_scene=draft,
    )
    unusable_outcome = VisibleCardOutcome(
        event_id="event-unusable",
        frame_identity=detected_outcome.frame_identity,
        status="failed",
        candidates=(),
        error="operator marked this frame unusable",
        ignored_regions=(),
        card_scene=draft,
    )
    content = VisibleCardData(outcomes=(detected_outcome, unusable_outcome))

    VisualIdentityPipelineService._validate_scene_derived_views(content)

    crop_items, lineage = VisualIdentityPipelineService._reviewed_virtual_card_items(
        content,
        fallback_scene_revision_id="completed-visible-reference-01",
    )
    repeated_items, repeated_lineage = VisualIdentityPipelineService._reviewed_virtual_card_items(
        content,
        fallback_scene_revision_id="completed-visible-reference-01",
    )
    assert len(crop_items) == 1
    assert crop_items[0].geometry.to_mapping() == region["geometry"]
    assert crop_items[0].identity_usable
    assert lineage.card_scene_revision_id == "completed-visible-reference-01"
    assert lineage.calibration_revision_id == "calibration-01"
    assert crop_items == repeated_items
    assert lineage == repeated_lineage

    app = create_test_app(_settings(tmp_path))
    service = app.state.visual_identity_pipeline_service
    source = RecordingVideoSource(
        recording_id=RECORDING_ID,
        relative_path=f"recordings/{RECORDING_ID}/video.mov",
        video_sha256=digest,
        byte_length=100,
        duration_us=1_000_000,
    )
    manifest = DataRevision(
        revision_id="reviewed-visible-reference-01",
        content_type="visible_cards",
        content_schema="visible-card-data/v1",
        recording_id=RECORDING_ID,
        source=source,
        content_sha256=sha256_bytes(canonical_visible_card_data_bytes(content)),
        input_revision_ids=(),
        origin="manual",
        producer=HumanProducer(review_id="review-01", operator_id="operator-01"),
        coverage={"kind": "fixture"},
        created_at="2026-01-01T00:00:00Z",
    )
    stored, _ = service.revision_store.publish(manifest, content)
    service.reference_store = SimpleNamespace(
        get=lambda _recording_id, _content_type: SimpleNamespace(
            state=SimpleNamespace(
                draft_state="completed",
                selected_completed_revision_id=stored.manifest.revision_id,
            )
        )
    )
    frozen = service._freeze_crop_input(
        RECORDING_ID,
        stored,
        source=source,
        requested_kind="reviewed_virtual_card",
        require_current_reference=True,
    )
    assert frozen.input_kind == "reviewed_virtual_card"
    assert frozen.source_revision_id == stored.manifest.revision_id
    assert frozen.items[0].geometry.to_mapping() == region["geometry"]
    assert frozen.virtual_card_lineage is not None
    assert frozen.virtual_card_lineage.derived_visible_region_digest
    visible_input = service._freeze_crop_input(
        RECORDING_ID,
        stored,
        source=source,
        requested_kind="reviewed_visible_card",
        require_current_reference=True,
    )
    assert (
        service._freeze_crop_input(
            RECORDING_ID,
            stored,
            source=source,
            requested=visible_input.to_mapping(),
        ).to_mapping()
        == visible_input.to_mapping()
    )
    service.reference_store = SimpleNamespace(
        get=lambda _recording_id, _content_type: SimpleNamespace(
            state=SimpleNamespace(
                draft_state="completed",
                selected_completed_revision_id="a-different-reference",
            )
        )
    )
    with pytest.raises(VisualIdentityPipelineError, match="completed maintained"):
        service._freeze_crop_input(
            RECORDING_ID,
            stored,
            source=source,
            requested_kind="reviewed_virtual_card",
            require_current_reference=True,
        )

    assert draft.derived_region_receipt is not None
    stale_receipt = {**draft.derived_region_receipt, "scene_digest": "b" * 64}
    stale = VisibleCardData(
        outcomes=(
            VisibleCardOutcome(
                event_id="event-01",
                frame_identity=content.outcomes[0].frame_identity,
                status="detected",
                candidates=content.outcomes[0].candidates,
                ignored_regions=(),
                error=None,
                card_scene=CardSceneDraft.create(
                    proposal=draft.proposal,
                    reviewed=draft.reviewed,
                    card_states=draft.card_states,
                    completion=draft.completion,
                    projection=draft.projection,
                    derived_region_receipt=stale_receipt,
                ),
            ),
        )
    )
    with pytest.raises(VisualIdentityPipelineError, match="stale or invalid"):
        VisualIdentityPipelineService._validate_scene_derived_views(stale)


def _wait_identity(client: TestClient, run_id: str) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + 5
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{run_id}")
        body = response.json()
        if body["state"]["status"] in {"complete", "partial", "failed"}:
            return body
        time.sleep(0.01)
    return body


def test_local_pipeline_requests_record_actual_bundle_and_crop(tmp_path: Any) -> None:
    _install_recording(tmp_path)
    detector = _Detector()
    detector.name = "local-rfdetr-segmentation"
    detector.bundle_identity = {"bundle_digest": "a" * 64}
    detector.device = "cpu"
    identity = _IdentityProvider()
    identity.name = "local-dinov3"
    identity.bundle_identity = {"bundle_digest": "b" * 64}
    identity.device = "cpu"
    app = create_test_app(
        _settings(tmp_path),
        event_provider=_EventProvider(),
        visible_card_provider=detector,
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=identity,
    )
    with TestClient(app) as client:
        assert (
            client.post(
                f"/api/recordings/{RECORDING_ID}/pipeline/events", json={"run_id": "events-local"}
            ).status_code
            == 202
        )
        _wait_event(client, "events-local")
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={"run_id": "cards-local", "configuration": {"provider": detector.name}},
        )
        assert response.status_code == 202, response.text
        assert (
            response.json()["request"]["configuration"]["bundle_identity"]
            == detector.bundle_identity
        )
        assert response.json()["request"]["configuration"]["device"] == "cpu"
        _wait(client, "cards-local")
        revision = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/cards-local/result"
        ).json()["state"]["output_revision_ids"][0]
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-local",
                "visible_card_revision_id": revision,
                "configuration": {"provider": "local"},
                "crop_policy": {"policy_id": "predicted_visible_region", "output_encoding": "ppm"},
            },
        )
        assert response.status_code == 202, response.text
        saved = response.json()["request"]
        assert saved["configuration"]["provider"] == identity.name
        assert saved["configuration"]["bundle_identity"] == identity.bundle_identity
        assert saved["configuration"]["device"] == "cpu"
        assert saved["crop_policy"]["policy_id"] == "predicted_visible_region"
        assert _wait_identity(client, "identity-local")["state"]["status"] == "complete"
        request = app.state.visual_identity_pipeline_service.run_store.require(
            "identity-local"
        ).request
        identity.device = "mps"
        with pytest.raises(VisualIdentityPipelineError, match="device changed"):
            app.state.visual_identity_pipeline_service._classifier_for_request(request)


def test_proposed_virtual_card_identity_run_reopens_and_previews_after_restart(
    tmp_path: Any,
) -> None:
    from doko_operations.card_plane_calibration import CalibrationRun
    from doko_operations.card_plane_geometry import (
        CardPose,
        CardStackingOrder,
        ReviewedCardScene,
        TablePlaneCalibration,
    )
    from table_evidence_analyzer import (
        PROPOSED_CARD_SCENE_DATA_SCHEMA_VERSION,
        ProposedCardScene,
        ProposedCardSceneData,
        ProposedCardSceneFrame,
        canonical_proposed_card_scene_data_bytes,
    )

    _install_recording(tmp_path)

    class RetryIdentityProvider(_IdentityProvider):
        name = "local-dinov3"

        def __init__(self) -> None:
            super().__init__()
            self.fail = False

        def classify(self, request: VisualIdentityRequest) -> CardClassificationResult:
            if self.fail:
                return CardClassificationResult(status="unavailable", error="retry fixture")
            return super().classify(request)

    identity = RetryIdentityProvider()
    settings = _settings(tmp_path)
    app = create_test_app(
        settings,
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=identity,
    )
    service = app.state.visual_identity_pipeline_service
    with TestClient(app) as client:
        assert (
            client.post(
                f"/api/recordings/{RECORDING_ID}/pipeline/events",
                json={"run_id": "events-for-proposed-identity"},
            ).status_code
            == 202
        )
        _wait_event(client, "events-for-proposed-identity")
        assert (
            client.post(
                f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
                json={"run_id": "cards-for-proposed-identity"},
            ).status_code
            == 202
        )
        _wait(client, "cards-for-proposed-identity")
        detector_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/"
            "cards-for-proposed-identity/result"
        ).json()["state"]["output_revision_ids"][0]
        detector_revision = app.state.pipeline_revision_store.require(detector_revision_id)
        frame_outcome = detector_revision.content.outcomes[0]
        frame_identity = frame_outcome.frame_identity
        assert frame_identity is not None

        calibration = TablePlaneCalibration.create(
            calibration_revision_id="calibration-proposed-identity",
            recording_id=RECORDING_ID,
            source_revision=detector_revision_id,
            frame_width=frame_identity.width,
            frame_height=frame_identity.height,
            image_to_table=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            table_to_image=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            card_short_size=20.0,
            card_long_size=30.0,
            candidate_receipt_digests=(),
            diagnostics={"fixture": True},
        )
        service.calibration_store.publish(
            CalibrationRun(
                recording_id=RECORDING_ID,
                source_revision=detector_revision_id,
                status="published",
                candidate_receipts=(),
                diagnostics={"fixture": True},
                calibration=calibration,
                calibration_fit_candidate=None,
                failure=None,
                run_digest="",
            )
        )
        scene = ReviewedCardScene.create(
            source_frame_id=frame_outcome.event_id,
            source_frame_width=frame_identity.width,
            source_frame_height=frame_identity.height,
            calibration_revision_id=calibration.calibration_revision_id,
            calibration_digest=calibration.calibration_digest,
            poses=(
                CardPose("proposal-card-01", (32.0, 32.0), 0.0, "suggestion-01", None),
                CardPose("proposal-hidden-01", (32.0, 32.0), 0.0, "suggestion-02", None),
            ),
            stacking_order=CardStackingOrder(
                card_ids=("proposal-card-01", "proposal-hidden-01"),
                uncertain_edges=(),
                contradictions=(),
            ),
        )
        proposal = ProposedCardScene.create(
            proposal_id="proposal-card-scene-01",
            source_frame_id=frame_outcome.event_id,
            source_frame_digest=frame_identity.image_sha256,
            detector_revision_id=detector_revision_id,
            detector_revision_digest=detector_revision.manifest.content_sha256,
            calibration_revision_id=calibration.calibration_revision_id,
            calibration_digest=calibration.calibration_digest,
            initializer_recipe_version="fixture-initializer/v1",
            status="supported",
            initialized_scene=scene.to_mapping(),
            fit_diagnostics={"fixture": True},
        )
        proposal_data = ProposedCardSceneData.create(
            detector_revision_id=detector_revision_id,
            detector_revision_digest=detector_revision.manifest.content_sha256,
            calibration_revision_id=calibration.calibration_revision_id,
            calibration_digest=calibration.calibration_digest,
            calibration=calibration.to_mapping(),
            calibration_diagnostics={"fixture": True},
            frames=(
                ProposedCardSceneFrame(
                    frame_id=frame_outcome.event_id,
                    source_frame_digest=frame_identity.image_sha256,
                    status="supported",
                    proposal=proposal,
                    unsupported_reason=None,
                    source_identity=frame_identity,
                    detector_status="detected",
                ),
                ProposedCardSceneFrame(
                    frame_id="unsupported-frame-01",
                    source_frame_digest=frame_identity.image_sha256,
                    status="unsupported",
                    proposal=None,
                    unsupported_reason="fixture unsupported pose",
                ),
            ),
        )
        proposal_revision_id = "card-scene-proposals-identity-fixture"
        proposal_manifest = DataRevision(
            revision_id=proposal_revision_id,
            content_type="card_scene_proposals",
            content_schema=PROPOSED_CARD_SCENE_DATA_SCHEMA_VERSION,
            recording_id=RECORDING_ID,
            source=detector_revision.manifest.source,
            content_sha256=sha256_bytes(canonical_proposed_card_scene_data_bytes(proposal_data)),
            input_revision_ids=(detector_revision_id,),
            origin="processor",
            producer=ProcessorProducer(
                run_id="proposal-run-fixture",
                processor_type="visible-card-scene-proposal",
                implementation_id="proposed-card-scene-processor/v2",
            ),
            coverage={
                "kind": "proposed-card-scenes",
                "detector_revision_digest": detector_revision.manifest.content_sha256,
            },
            created_at="2026-11-04T00:00:00Z",
        )
        app.state.pipeline_revision_store.publish(proposal_manifest, proposal_data)
        frozen = service._freeze_crop_input(
            RECORDING_ID,
            app.state.pipeline_revision_store.require(proposal_revision_id),
            source=detector_revision.manifest.source,
            requested_kind="proposed_virtual_cards",
        )
        assert frozen.proposed_virtual_card_lineage is not None
        stale_lineage = replace(
            frozen.proposed_virtual_card_lineage,
            calibration_digest="0" * 64,
        )
        stale_crop_input = replace(
            frozen,
            proposed_virtual_card_lineage=stale_lineage,
            manifest_digest=None,
        )
        with pytest.raises(VisualIdentityPipelineError, match="descriptor does not match"):
            service._build_request(
                RECORDING_ID,
                {
                    "run_id": "identity-stale-proposal-lineage",
                    "card_scene_proposal_revision_id": proposal_revision_id,
                    "crop_input_kind": "proposed_virtual_cards",
                    "crop_input": stale_crop_input.to_mapping(),
                    "configuration": {"provider": "local"},
                },
            )
        listed = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/proposed-crop-inputs"
        ).json()["inputs"]
        assert [item["revision_id"] for item in listed] == [proposal_revision_id]

        def fail_result_publish(*_args: Any, **_kwargs: Any) -> Any:
            raise OSError("fixture temporary publish failure")

        service._publish_revision = fail_result_publish

        started = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-from-proposal",
                "input_revision_ids": [proposal_revision_id],
                "card_scene_proposal_revision_id": proposal_revision_id,
                "crop_input_kind": "proposed_virtual_cards",
                "configuration": {"provider": "local"},
            },
        )
        assert started.status_code == 202, started.text
        assert _wait_identity(client, "identity-from-proposal")["state"]["status"] == "failed"
        crop_input = started.json()["request"]["crop_input"]
        assert started.json()["request"]["input_revision_ids"] == [proposal_revision_id]
        assert crop_input["input_kind"] == "proposed_virtual_cards"
        assert crop_input["source_revision_id"] == proposal_revision_id
        lineage = crop_input["proposed_virtual_card_lineage"]
        assert lineage["detector_revision_id"] == detector_revision_id
        assert lineage["calibration_revision_id"] == calibration.calibration_revision_id
        assert lineage["unsupported_frame_ids"] == ["unsupported-frame-01"]
        assert lineage["hidden_cards"] == [f"{frame_outcome.event_id}:proposal-hidden-01"]

    restarted = create_test_app(
        settings,
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=identity,
    )
    with TestClient(restarted) as client:
        reopened = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/identity-from-proposal"
        )
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["request"]["crop_input"] == crop_input
        retried = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/"
            "identity-from-proposal/retry"
        )
        assert retried.status_code == 202, retried.text
        assert _wait_identity(client, "identity-from-proposal")["state"]["status"] == "complete"
        reopened = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/"
            "identity-from-proposal/result"
        )
        assert reopened.status_code == 200, reopened.text
        outcomes = reopened.json()["revisions"][0]["content"]["outcomes"]
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome["card_id"] == "proposal-card-01"
        assert outcome["geometry"]["kind"] == "visible-region/v1"
        assert outcome["crop_input_provenance"]["input_kind"] == "proposed_virtual_cards"
        revision_id = reopened.json()["state"]["output_revision_ids"][0]
        card_id = reopened.json()["revisions"][0]["content"]["outcomes"][0]["card_id"]
        preview = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
            f"{revision_id}/{card_id}?preview=browser"
        )
        assert preview.status_code == 200, preview.text
