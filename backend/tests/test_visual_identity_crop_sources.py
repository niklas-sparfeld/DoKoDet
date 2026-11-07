from __future__ import annotations

from dataclasses import replace
from typing import Any

from app_factory import create_test_app
from doko_operations.pipeline_data import (
    DataRevision,
    HumanProducer,
    RecordingVideoSource,
    sha256_bytes,
)
from fastapi.testclient import TestClient
from table_evidence_analyzer import (
    VisibleCardCandidate,
    VisibleCardData,
    VisibleCardFrameIdentity,
    VisibleCardOutcome,
    canonical_visible_card_data_bytes,
)
from table_evidence_analyzer.pipeline_data import VisibleCardPileRegion
from test_visual_identity_pipeline_api import (
    RECORDING_ID,
    _Detector,
    _EventProvider,
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

from dokodetector_backend import (
    visual_identity_pipeline_service as visual_identity_pipeline_service_module,
)
from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
from dokodetector_backend.visual_identity_pipeline_service import (
    VisualIdentityPipelineError,
    VisualIdentityPipelineService,
)


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
    stored, _ = service.selection_store.publish_processor_revision(manifest, content)
    pointer = service.selection_store.reference_for_processor_output(
        stored.manifest.revision_id, RECORDING_ID, "visible_cards"
    )
    node_id, node_revision_id = pointer["node_id"], pointer["revision_id"]
    reviews = PipelineNodeReviews(service.node_store)
    reviews.overall(
        "completed-visible-review",
        node_id,
        node_revision_id,
        "Retained data-set completion",
        "complete",
        {"kind": "not_recorded", "id": None},
        {"policy": "test-visible-card-completion/v1", "revision_id": stored.manifest.revision_id},
    )
    service.selection_store.update_exact(
        RECORDING_ID,
        "visible_cards",
        expected_revision=0,
        selected_generated=None,
        selected_completed_reference={"node_id": node_id, "revision_id": node_revision_id},
    )
    frozen = service._freeze_crop_input(
        RECORDING_ID,
        stored,
        source=source,
        requested_kind="reviewed_virtual_card",
        require_current_reference=True,
    )
    frozen_result = service.crop_input_freezer.freeze(
        RECORDING_ID,
        stored,
        source=source,
        requested_kind="reviewed_virtual_card",
        require_current_reference=True,
    )
    assert frozen_result.exact_input_revision_id == stored.manifest.revision_id
    assert frozen_result.crop_input == frozen
    assert frozen_result.crop_items == frozen.items
    assert frozen_result.provenance.manifest_digest == frozen.computed_manifest_digest
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
    service.selection_store.update_exact(
        RECORDING_ID,
        "visible_cards",
        expected_revision=1,
        selected_generated=None,
        selected_completed_reference=None,
    )
    with pytest.raises(VisualIdentityPipelineError, match="completed visible-card node"):
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
        event_revision_id = _run_event_job(client, "events-for-identity-source-validation")

        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "visible-for-identity-source-validation",
                **_selected_node_input(client, "events", event_revision_id),
            },
        )
        assert visible_response.status_code == 202
        visible_run_id = visible_response.json()["run_id"]
        assert _wait(client, visible_run_id)["state"]["status"] == ("complete")
        visible_revision_id = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards/{visible_run_id}/result"
        ).json()["state"]["output_revision_ids"][0]

        visible_revision = app.state.pipeline_selection_store.require_processor_revision(
            visible_revision_id
        )
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
        app.state.pipeline_lineage_writer.publish_processor_revision(pile_manifest, pile_content)

        identity_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-source-validation",
                **_node_input(app, "visible-revision-with-pile"),
            },
        )
        assert identity_response.status_code == 202, identity_response.text
        identity_run_id = identity_response.json()["run_id"]
        assert _wait_identity(client, identity_run_id)["state"]["status"] == ("complete")
        identity_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{identity_run_id}/result"
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
        app.state.pipeline_lineage_writer.publish_processor_revision(
            pile_only_manifest, pile_only_content
        )
        pile_only_identity = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-pile-only",
                **_node_input(app, "visible-pile-only"),
            },
        )
        assert pile_only_identity.status_code == 202, pile_only_identity.text
        pile_only_run_id = pile_only_identity.json()["run_id"]
        assert _wait_identity(client, pile_only_run_id)["state"]["status"] == "complete"
        pile_only_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{pile_only_run_id}/result"
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
        app.state.pipeline_lineage_writer.publish_processor_revision(mixed_manifest, mixed_content)
        mixed_identity = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "identity-mixed-card-and-empty",
                **_node_input(app, "visible-mixed-card-and-empty"),
            },
        )
        assert mixed_identity.status_code == 202, mixed_identity.text
        mixed_run_id = mixed_identity.json()["run_id"]
        assert _wait_identity(client, mixed_run_id)["state"]["status"] == ("complete")
        mixed_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{mixed_run_id}/result"
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
        app.state.pipeline_lineage_writer.publish_processor_revision(empty_manifest, empty_content)
        empty_identity = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={"run_id": "identity-empty", **_node_input(app, "visible-empty")},
        )
        assert empty_identity.status_code == 202, empty_identity.text
        empty_run_id = empty_identity.json()["run_id"]
        assert _wait_identity(client, empty_run_id)["state"]["status"] == "complete"
        empty_result = client.get(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities/{empty_run_id}/result"
        ).json()
        assert empty_result["request"]["crop_input"]["items"] == []
        assert empty_result["revisions"][0]["content"]["outcomes"] == []
        assert len(crop_calls) == candidate_crop_count
        assert len(provider.requests) == candidate_model_call_count
        assert len(resolve_calls) == candidate_frame_resolve_count

    assert resolve_calls
    assert set(resolve_calls) == {False}
