from __future__ import annotations

import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app_factory import create_test_app
from doko_operations.derived_view import crop_jpeg_preview_cache_key_for_source_digest
from doko_operations.pipeline_data import DataRevision, ProcessorProducer, sha256_bytes
from fastapi.testclient import TestClient
from table_evidence_analyzer import CardClassificationResult, VisualIdentityRequest
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

from dokodetector_backend.visual_identity_pipeline_service import VisualIdentityPipelineError


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
        cold_validate_provenance = service.crop_queries._validate_crop_input_provenance

        def count_cold_validation(*args: Any, **kwargs: Any) -> Any:
            nonlocal cold_validation_calls
            cold_validation_calls += 1
            return cold_validate_provenance(*args, **kwargs)

        with monkeypatch.context() as cold_patch:
            cold_patch.setattr(
                service.crop_queries, "_validate_crop_input_provenance", count_cold_validation
            )
            warm_preview = client.get(
                f"/api/recordings/{RECORDING_ID}/pipeline/derived-views/identity-crops/"
                f"{identity_revision_id}/{generated_outcome['card_id']}?preview=browser"
            )
        assert cold_validation_calls == 1
        assert warm_preview.status_code == 200, warm_preview.text
        assert warm_preview.headers["content-type"] == "image/jpeg"
        assert preview_path.is_dir()
        canonical_cache = None
        for entry in service.storage.derived_views_root.iterdir():
            manifest_path = entry / "manifest.json"
            if not manifest_path.is_file():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("view_kind") == "visible-region-crop/v1":
                canonical_cache = manifest
                break
        assert canonical_cache is not None
        assert canonical_cache["schema_version"] == "derived-view-cache/v2"
        assert canonical_cache["storage_codec"] == "gzip/level-1/v1"
        assert len(canonical_cache["stored_content_sha256"]) == 64
        assert canonical_cache["stored_byte_length"] > 0
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
            cached_patch.setattr(
                service.crop_queries, "resolve_identity_crop", fail_if_canonical_resolution
            )
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
        service.crop_queries._crop_contexts.clear()
        validation_calls = 0
        validate_provenance = service.crop_queries._validate_crop_input_provenance

        def count_validation(*args: Any, **kwargs: Any) -> Any:
            nonlocal validation_calls
            validation_calls += 1
            return validate_provenance(*args, **kwargs)

        with monkeypatch.context() as concurrent_patch:
            concurrent_patch.setattr(
                service.crop_queries, "_validate_crop_input_provenance", count_validation
            )
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
        original_resolve_identity_crop = service.crop_queries._resolve_identity_crop_from_validated

        def count_canonical_resolution(*args: object, **kwargs: object) -> object:
            nonlocal resolve_calls
            resolve_calls += 1
            return original_resolve_identity_crop(*args, **kwargs)

        monkeypatch.setattr(
            service.crop_queries,
            "_resolve_identity_crop_from_validated",
            count_canonical_resolution,
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

        service.job_executor._publish_revision = fail_result_publish

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
