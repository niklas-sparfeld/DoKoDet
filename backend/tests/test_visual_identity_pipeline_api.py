from __future__ import annotations

import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app_factory import create_test_app
from doko_operations.derived_view import crop_jpeg_preview_cache_key_for_source_digest
from doko_operations.pipeline_data import (
    DataRevision,
    ProcessorProducer,
    ProcessorRunRequest,
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
from table_evidence_analyzer.table_observation import IdentityCandidate
from test_visible_card_pipeline_api import (
    RECORDING_ID,
    _Detector,
    _enqueue_event,
    _EventProvider,
    _FrameResolver,
    _install_recording,
    _run_event_job,
    _selected_node_input,
    _settings,
    _wait,
    _wait_event,
)

from dokodetector_backend import (
    visual_identity_pipeline_service as visual_identity_pipeline_service_module,
)
from dokodetector_backend.job_store import CancellationToken
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
    stored, _ = app.state.pipeline_lineage_writer.publish_processor_revision(manifest, content)
    return stored.manifest.revision_id


def _node_input(app: Any, revision_id: str) -> dict[str, object]:
    nodes = app.state.visual_identity_pipeline_service.node_store
    node, _ = nodes.find_revision(revision_id)
    return {
        "input_node_ref": {
            "node_id": node.node_id,
            "revision_id": revision_id,
            "revision_policy": "current_head"
            if node.head_revision_id == revision_id
            else "historical",
        }
    }


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
        _run_event_job(client, "events-generated")
        client.get(f"/api/recordings/{RECORDING_ID}/pipeline/events/events-generated/result")

        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={"run_id": "visible-generated", **_selected_node_input(client, "events")},
        )
        assert visible_response.status_code == 202
        visible_run_id = visible_response.json()["run_id"]
        assert _wait(client, visible_run_id)["state"]["status"] == "complete"
        visible_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{visible_run_id}/result"
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
            app.state.pipeline_selection_store.require_processor_revision(
                generated_revision_id
            ).manifest.source,
            generated_content["outcomes"][0]["frame_identity"],
            visible_run_id,
        )

        generated_identity = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-generated",
                **_selected_node_input(client, "visible_cards", generated_revision_id),
            },
        )
        assert generated_identity.status_code == 202
        identity_run_id = generated_identity.json()["run_id"]
        assert _wait_identity(client, identity_run_id)["state"]["status"] == "complete"
        generated_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{identity_run_id}/result"
        ).json()
        generated_outcome = generated_result["revisions"][0]["content"]["outcomes"][0]
        assert generated_result["request"]["input_revision_ids"] == [generated_revision_id]
        assert generated_result["request"]["crop_input"]["input_kind"] == "gemini_polygon"
        crop_input = generated_result["request"]["crop_input"]
        input_node_ref = generated_result["request"]["input_node_refs"][0]
        assert crop_input["schema_version"] == "visual-identity-crop-input/v4"
        assert crop_input["source_node_id"] == input_node_ref["node_id"]
        assert crop_input["source_node_revision_id"] == input_node_ref["revision_id"]
        assert generated_result["request"]["crop_input"]["source_revision_id"] == (
            generated_revision_id
        )
        assert (
            generated_outcome["crop_input_provenance"]["manifest_digest"]
            == (generated_result["request"]["crop_input"]["manifest_digest"])
        )
        assert generated_outcome["crop_input_provenance"]["input_kind"] == "gemini_polygon"
        assert generated_outcome["crop_input_provenance"]["schema_version"] == (
            "visual-identity-crop-input-provenance/v3"
        )
        assert (
            generated_outcome["crop_input_provenance"]["source_node_id"]
            == (crop_input["source_node_id"])
        )
        assert (
            generated_outcome["crop_input_provenance"]["source_node_revision_id"]
            == (crop_input["source_node_revision_id"])
        )
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
        generated_revision = app.state.pipeline_selection_store.require_processor_revision(
            generated_revision_id
        )
        original_require = service.run_store.require
        generated_run = original_require(visible_run_id)
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
                    rfdetr_run if run_id == visible_run_id else original_require(run_id, **kwargs)
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
            assert not hasattr(service, "revision_store")
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

        identity_node = service.node_store.find_revision(identity_revision_id)[0]
        generated_node = service.node_store.find_revision(generated_revision_id)[0]
        identity_manifest = service.selection_store.require_processor_revision(
            identity_revision_id
        ).manifest
        generated_manifest = service.selection_store.require_processor_revision(
            generated_revision_id
        ).manifest
        dependency_files = [
            service.node_store.revision_path(identity_node.node_id, identity_revision_id)
            / "revision.json",
            service.node_store.revision_path(generated_node.node_id, generated_revision_id)
            / "revision.json",
            service.run_store.run_path(identity_run_id) / "request.json",
            service._video_path(RECORDING_ID),
        ]
        for dependency in dependency_files:
            original = dependency.read_bytes()
            original_stat = dependency.stat()
            dependency.write_bytes(b"x" * len(original))
            os.utime(dependency, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            rejected = client.get(preview_url)
            if rejected.status_code == 200:
                # Node-store recovery may restore an interrupted immutable revision read.
                current = service.selection_store.require_processor_revision(
                    identity_revision_id
                    if identity_revision_id in dependency.parts
                    else generated_revision_id
                )
                expected_digest = (
                    identity_manifest.content_sha256
                    if identity_revision_id in dependency.parts
                    else generated_manifest.content_sha256
                )
                assert current.manifest.content_sha256 == expected_digest
            else:
                assert rejected.status_code in {404, 409}, (dependency, rejected.text)
            dependency.write_bytes(original)
            restored = client.get(preview_url)
            assert restored.status_code == 200, (dependency, restored.text)

        added_member = (
            service.node_store.revision_path(generated_node.node_id, generated_revision_id)
            / "extra.json"
        )
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
        original_resolve_identity_crop = service._resolve_identity_crop_from_validated

        def count_canonical_resolution(*args: object, **kwargs: object) -> object:
            nonlocal resolve_calls
            resolve_calls += 1
            return original_resolve_identity_crop(*args, **kwargs)

        monkeypatch.setattr(
            service, "_resolve_identity_crop_from_validated", count_canonical_resolution
        )
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
                "run_id": "identity-frozen-provider-changed",
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
                **_node_input(app, fixture_revision_id),
                "crop_policy": {
                    "policy_id": "predicted_visible_region",
                    "output_encoding": "ppm",
                },
            },
        )
        assert completed_identity.status_code == 202
        completed_run_id = completed_identity.json()["run_id"]
        assert _wait_identity(client, completed_run_id)["state"]["status"] == "complete"
        result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{completed_run_id}/result"
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
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{completed_run_id}/result"
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


def _wait_identity(client: TestClient, run_id: str) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + 5
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        job_response = client.get(f"/api/jobs/{run_id}")
        if job_response.status_code == 200:
            job = job_response.json()
            if job["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
                response = client.get(
                    f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{run_id}/result"
                )
                if response.status_code == 200:
                    body = response.json()
                else:
                    body = {"state": {"progress": {"completed": 0, "total": 0}, "items": []}}
                status = "complete" if job["state"] == "succeeded" else job["state"]
                body.setdefault("state", {})["status"] = status
                body["state"].setdefault("progress", {"completed": 0, "total": 0})
                body["state"].setdefault("items", [])
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
        assert _run_event_job(client, "events-local")
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "cards-local",
                **_selected_node_input(client, "events"),
                "configuration": {"provider": detector.name},
            },
        )
        assert response.status_code == 202, response.text
        assert (
            response.json()["request"]["configuration"]["bundle_identity"]
            == detector.bundle_identity
        )
        assert response.json()["request"]["configuration"]["device"] == "cpu"
        visible_run_id = response.json()["run_id"]
        _wait(client, visible_run_id)
        revision = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{visible_run_id}/result"
        ).json()["state"]["output_revision_ids"][0]
        response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-local",
                **_selected_node_input(client, "visible_cards", revision),
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
        identity_run_id = response.json()["run_id"]
        assert _wait_identity(client, identity_run_id)["state"]["status"] == "complete"
        request = app.state.visual_identity_pipeline_service.run_store.require(
            identity_run_id
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
        _run_event_job(client, "events-for-proposed-identity")
        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "cards-for-proposed-identity",
                **_selected_node_input(client, "events"),
            },
        )
        assert visible_response.status_code == 202, visible_response.text
        visible_run_id = visible_response.json()["run_id"]
        _wait(client, visible_run_id)
        detector_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{visible_run_id}/result"
        ).json()["state"]["output_revision_ids"][0]
        detector_revision = app.state.pipeline_selection_store.require_processor_revision(
            detector_revision_id
        )
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
                CardPose(
                    "proposal-card-01",
                    (32.0, 32.0),
                    0.0,
                    frame_outcome.candidates[0].card_id,
                    None,
                ),
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
        app.state.pipeline_selection_store.publish_processor_revision(
            proposal_manifest, proposal_data
        )
        frozen = service._freeze_crop_input(
            RECORDING_ID,
            app.state.pipeline_selection_store.require_processor_revision(proposal_revision_id),
            source=detector_revision.manifest.source,
            requested_kind="proposed_virtual_cards",
        )
        assert frozen.proposed_virtual_card_lineage is not None
        assert [item.card_id for item in frozen.items] == [frame_outcome.candidates[0].card_id]
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
                    **_node_input(app, proposal_revision_id),
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
                **_node_input(app, proposal_revision_id),
                "crop_input_kind": "proposed_virtual_cards",
                "configuration": {"provider": "local"},
            },
        )
        assert started.status_code == 202, started.text
        identity_run_id = started.json()["run_id"]
        assert _wait_identity(client, identity_run_id)["state"]["status"] == "failed"
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
        reopened = client.get(f"/api/jobs/{identity_run_id}")
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["request"]["processor_request"]["crop_input"] == crop_input
        retried = client.post(
            f"/api/jobs/{identity_run_id}/retry",
            headers={"Idempotency-Key": str(uuid4())},
            json={},
        )
        assert retried.status_code == 202, retried.text
        retry_run_id = retried.json()["id"]
        assert _wait_identity(client, retry_run_id)["state"]["status"] == "complete"
        reopened = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{retry_run_id}/result"
        )
        assert reopened.status_code == 200, reopened.text
        outcomes = reopened.json()["revisions"][0]["content"]["outcomes"]
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome["card_id"] == frame_outcome.candidates[0].card_id
        assert outcome["geometry"]["kind"] == "visible-region/v1"
        assert outcome["crop_input_provenance"]["input_kind"] == "proposed_virtual_cards"
        revision_id = reopened.json()["state"]["output_revision_ids"][0]
        card_id = reopened.json()["revisions"][0]["content"]["outcomes"][0]["card_id"]
        preview = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
            f"{revision_id}/{card_id}?preview=browser"
        )
        assert preview.status_code == 200, preview.text
