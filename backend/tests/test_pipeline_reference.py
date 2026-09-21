from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from app_factory import create_test_app
from doko_operations.card_plane_geometry import CardPose, CardStackingOrder, ReviewedCardScene
from doko_operations.pipeline_data import (
    DataRevision,
    EventData,
    EventDataRevision,
    EventRecord,
    ProcessorProducer,
    RecordingVideoSource,
    canonical_event_data_bytes,
    sha256_bytes,
)
from fastapi.testclient import TestClient
from table_evidence_analyzer.pipeline_data import (
    ProposedCardScene,
    ProposedCardSceneData,
    ProposedCardSceneFrame,
    VisibleCardData,
    canonical_proposed_card_scene_data_bytes,
    canonical_visible_card_data_bytes,
    canonical_visual_identity_data_bytes,
)

from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_reference_errors import (
    PipelineReferenceConflict,
    PipelineReferenceCoverageError,
    PipelineReferenceInputError,
)
from dokodetector_backend.pipeline_reference_service import (
    PipelineReferenceService,
)
from dokodetector_backend.pipeline_reference_store import (
    PipelineReferenceStore,
    StoredPipelineReference,
)
from dokodetector_backend.pipeline_store import (
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    PipelineSelectionStore,
    ProcessorRunStore,
)

DIGEST = "a" * 64
SOURCE = RecordingVideoSource(
    recording_id="recording-01",
    relative_path="recordings/recording-01/video.mov",
    video_sha256=DIGEST,
    byte_length=100,
    duration_us=10_000_000,
)


class _Settings:
    repository_root = Path(".").resolve()


class _RecordingStore:
    def get(self, recording_id: str) -> None:
        del recording_id
        return None


class _RepositoryStorage:
    pass


def _service(tmp_path: Path) -> tuple[PipelineReferenceService, PipelineRevisionStore]:
    revision_store = PipelineRevisionStore(tmp_path / "runtime")
    run_store = ProcessorRunStore(
        PipelineRuntimeStorage(tmp_path / "runtime"), revision_store=revision_store
    )
    selection_store = PipelineSelectionStore(
        PipelineRuntimeStorage(tmp_path / "runtime"),
        revision_store=revision_store,
        run_store=run_store,
    )
    service = PipelineReferenceService(
        _Settings(),
        _RecordingStore(),
        _RepositoryStorage(),
        reference_store=PipelineReferenceStore(tmp_path / "operations" / "pipeline-references"),
        revision_store=revision_store,
        selection_store=selection_store,
    )
    return service, revision_store


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        repository_root=tmp_path,
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "operations",
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
        pending_video_root=tmp_path / "pending-videos",
    )


def _source_revision(revision_store: PipelineRevisionStore) -> str:
    content = EventData(
        events=(
            EventRecord(
                event_id="event-01",
                event_type="card_state_changed",
                start_us=1_000_000,
                end_us=1_250_000,
                model_scores=(),
            ),
        )
    )
    manifest = DataRevision(
        revision_id="generated-events-01",
        content_type="events",
        content_schema="event-data/v1",
        recording_id=SOURCE.recording_id,
        source=SOURCE,
        content_sha256=sha256_bytes(canonical_event_data_bytes(content)),
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id="run-01",
            processor_type="event-detection",
            implementation_id="fixture.v1",
            model_id="fixture-model.v1",
        ),
        coverage={"kind": "processed"},
        created_at="2026-09-05T10:00:00Z",
    )
    revision_store.publish(EventDataRevision(manifest=manifest, content=content))
    return manifest.revision_id


def _event_revision_variant(
    revision_store: PipelineRevisionStore,
    revision_id: str,
    *,
    start_us: int = 1_000_000,
) -> str:
    content = EventData(
        events=(
            EventRecord(
                event_id="event-01",
                event_type="card_state_changed",
                start_us=start_us,
                end_us=start_us + 250_000,
                model_scores=(),
            ),
        )
    )
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="events",
        content_schema="event-data/v1",
        recording_id=SOURCE.recording_id,
        source=SOURCE,
        content_sha256=sha256_bytes(canonical_event_data_bytes(content)),
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id=f"run-{revision_id}",
            processor_type="event-detection",
            implementation_id="fixture.v1",
            model_id="fixture-model.v1",
        ),
        coverage={"kind": "processed"},
        created_at="2026-09-05T10:00:00Z",
    )
    revision_store.publish(EventDataRevision(manifest=manifest, content=content))
    return manifest.revision_id


def _vision_source_revision(
    revision_store: PipelineRevisionStore,
    content_type: str,
    *,
    visible_candidate_ids: tuple[str, ...] = ("card-01",),
    revision_id: str | None = None,
    identity_status: str = "classified",
) -> str:
    frame = {
        "schema_version": "exact-event/v1",
        "source_video_sha256": DIGEST,
        "requested_time_us": 1_000_000,
        "frame_index": 0,
        "presentation_timestamp_us": 1_000_000,
        "width": 100,
        "height": 100,
        "decoder_version": "decoder.v1",
        "transform_version": "transform.v1",
        "output_encoding": "png",
        "content_type": "image/png",
        "image_sha256": DIGEST,
        "policy": "exact-event/v1",
    }
    geometry = {
        "kind": "detector-box/v1",
        "box_2d": {"x_min": 1, "y_min": 1, "x_max": 50, "y_max": 50},
    }
    if content_type == "visible_cards":
        candidates = [
            {
                "card_id": card_id,
                "geometry": geometry,
                "normalization": {
                    "width": 64,
                    "height": 64,
                    "policy_id": "fixture.v1",
                },
                "side": "face_down",
                "model_scores": [{"producer_id": "detector.v1", "score": 0.8}],
            }
            for card_id in visible_candidate_ids
        ]
        content = {
            "schema_version": "visible-card-data/v1",
            "outcomes": [
                {
                    "event_id": "event-01",
                    "frame_identity": frame,
                    "status": "detected",
                    "candidates": candidates,
                    "ignored_regions": [],
                    "error": None,
                }
            ],
        }
        content_sha256 = sha256_bytes(canonical_visible_card_data_bytes(content))
        content_bytes = canonical_visible_card_data_bytes(content)
        schema = "visible-card-data/v1"
    else:
        crop = {
            "schema_version": "visible-region-crop/v1",
            "status": "usable",
            "frame_identity": frame,
            "geometry": geometry,
            "pixel_bounds": {"x_min": 1, "y_min": 1, "x_max": 50, "y_max": 50},
            "crop_policy": "crop.v1",
            "output_encoding": "png",
            "content_type": "image/png",
            "decoder_version": "decoder.v1",
            "transform_version": "transform.v1",
            "image_sha256": DIGEST,
            "unusable_reason": None,
        }
        identity_candidates = (
            []
            if identity_status == "face_down"
            else [
                {
                    "identity": "CLUBS_NINE",
                    "score": 0.8,
                    "score_meaning": "probability",
                    "producer_id": "identity.v1",
                }
            ]
        )
        content = {
            "schema_version": "visual-identity-data/v1",
            "outcomes": [
                {
                    "card_id": "card-01",
                    "frame_identity": frame,
                    "geometry": geometry,
                    "crop_identity": crop,
                    "classifier": {
                        "provider": "fixture.identity",
                        "implementation": {"name": "fixture", "version": "v1"},
                        "model": {"name": "fixture-model", "version": "v1"},
                    },
                    "status": identity_status,
                    "candidates": identity_candidates,
                    "unusable_reason": None,
                    "error": None,
                }
            ],
        }
        content_sha256 = sha256_bytes(canonical_visual_identity_data_bytes(content))
        content_bytes = canonical_visual_identity_data_bytes(content)
        schema = "visual-identity-data/v1"
    published_revision_id = revision_id or f"generated-{content_type}-01"
    manifest = DataRevision(
        revision_id=published_revision_id,
        content_type=content_type,
        content_schema=schema,
        recording_id=SOURCE.recording_id,
        source=SOURCE,
        content_sha256=content_sha256,
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id=f"run-{published_revision_id}",
            processor_type=content_type,
            implementation_id="fixture.v1",
            model_id="fixture-model.v1",
        ),
        coverage={"kind": "processed"},
        created_at="2026-09-05T10:00:00Z",
    )
    revision_store.publish(manifest, content_bytes)
    return manifest.revision_id


def _proposal_revision(
    revision_store: PipelineRevisionStore,
    source_revision_id: str,
    *,
    card_ids: tuple[str, ...] = ("card-01",),
    revision_id: str = "card-scene-proposals-01",
) -> str:
    source = revision_store.require(source_revision_id)
    scene = ReviewedCardScene.create(
        source_frame_id="event-01",
        source_frame_width=100,
        source_frame_height=100,
        calibration_revision_id="calibration-01",
        calibration_digest="c" * 64,
        poses=tuple(
            CardPose(card_id, (25.0 + index * 30.0, 25.0), 0.0, card_id, None)
            for index, card_id in enumerate(card_ids)
        ),
        stacking_order=CardStackingOrder(
            card_ids=card_ids,
            uncertain_edges=(),
            contradictions=(),
        ),
    )
    proposal = ProposedCardScene.create(
        proposal_id="proposal-event-01",
        source_frame_id="event-01",
        source_frame_digest=DIGEST,
        detector_revision_id=source_revision_id,
        detector_revision_digest=source.manifest.content_sha256,
        calibration_revision_id="calibration-01",
        calibration_digest="c" * 64,
        initializer_recipe_version="initializer/v1",
        status="supported",
        initialized_scene=scene.to_mapping(),
        fit_diagnostics={"accepted": list(card_ids)},
    )
    calibration = {
        "schema_version": "table-plane-calibration/v1",
        "calibration_revision_id": "calibration-01",
        "recording_id": SOURCE.recording_id,
        "source_revision": source_revision_id,
        "frame_width": 100,
        "frame_height": 100,
        "image_to_table": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "table_to_image": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "table_to_image_homography": [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        "card_short_size": 20.0,
        "card_long_size": 30.0,
        "calibration_digest": "c" * 64,
    }
    content = ProposedCardSceneData.create(
        detector_revision_id=source_revision_id,
        detector_revision_digest=source.manifest.content_sha256,
        calibration_revision_id="calibration-01",
        calibration_digest="c" * 64,
        calibration=calibration,
        calibration_diagnostics={"fit": {"quality_passed": True}},
        frames=(
            ProposedCardSceneFrame(
                frame_id="event-01",
                source_frame_digest=DIGEST,
                status="supported",
                proposal=proposal,
                unsupported_reason=None,
            ),
        ),
    )
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="card_scene_proposals",
        content_schema="proposed-card-scene-data/v1",
        recording_id=SOURCE.recording_id,
        source=SOURCE,
        content_sha256=sha256_bytes(canonical_proposed_card_scene_data_bytes(content)),
        input_revision_ids=(source_revision_id,),
        origin="processor",
        producer=ProcessorProducer(
            run_id="proposal-run-01",
            processor_type="visible-card-scene-proposal",
            implementation_id="proposal-processor.v1",
            model_id=None,
        ),
        coverage={
            "kind": "proposed-card-scenes",
            "detector_revision_digest": source.manifest.content_sha256,
        },
        created_at="2026-09-05T10:00:00Z",
    )
    revision_store.publish(manifest, content)
    return revision_id


def test_reference_accepts_and_completes_without_model_scores_and_survives_restart(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _source_revision(revision_store)

    created = service.create_reference(
        "recording-01",
        "events",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    assert created.draft.items[0].item_id == "event-01"
    assert created.draft.items[0].review_state == "pending"
    assert (created.draft.items[0].item["start_us"], created.draft.items[0].item["end_us"]) == (
        1_000_000,
        1_250_000,
    )

    accepted = service.update_draft(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "accept", "item_id": "event-01"}],
        },
    )
    assert accepted.draft.revision == 1
    assert accepted.draft.items[0].review_state == "accepted"
    assert (accepted.draft.items[0].item["start_us"], accepted.draft.items[0].item["end_us"]) == (
        1_000_000,
        1_250_000,
    )

    completed = service.complete_reference(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "coverage": {"kind": "full_recording"},
        },
    )
    revision_id = completed.state.selected_completed_revision_id
    assert revision_id is not None
    stored_revision = revision_store.require(revision_id)
    assert stored_revision.manifest.origin == "corrected"
    assert stored_revision.manifest.producer.base_revision_id == source_revision_id
    assert stored_revision.content.events[0].model_scores is None
    assert (
        stored_revision.content.events[0].start_us,
        stored_revision.content.events[0].end_us,
    ) == (1_000_000, 1_250_000)

    restarted = PipelineReferenceStore(tmp_path / "operations" / "pipeline-references")
    restored = restarted.require("recording-01", "events")
    assert restored.state.draft_state == "completed"
    assert restored.state.selected_completed_revision_id == revision_id
    assert restored.draft.items[0].item_id == "event-01"
    assert (restored.draft.items[0].item["start_us"], restored.draft.items[0].item["end_us"]) == (
        1_000_000,
        1_250_000,
    )


def test_event_reference_completion_orders_added_events_by_time(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _source_revision(revision_store)

    service.create_reference(
        "recording-01",
        "events",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    accepted = service.update_draft(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "accept", "item_id": "event-01"}],
        },
    )
    added = service.update_draft(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": accepted.draft.revision,
            "operations": [
                {
                    "operation": "add",
                    "item": {
                        "event_id": "manual-01",
                        "event_type": "card_state_changed",
                        "start_us": 0,
                        "end_us": 0,
                    },
                }
            ],
        },
    )

    completed = service.complete_reference(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": added.draft.revision,
            "coverage": {"kind": "full_recording"},
        },
    )

    revision_id = completed.state.selected_completed_revision_id
    assert revision_id is not None
    published = revision_store.require(revision_id)
    assert [event.event_id for event in published.content.events] == [
        "manual-01",
        "event-01",
    ]
    assert [item.item_id for item in completed.draft.items] == ["manual-01", "event-01"]


def test_stale_reference_edit_returns_current_revision_without_losing_newer_draft(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _source_revision(revision_store)
    service.create_reference(
        "recording-01",
        "events",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    current = service.update_draft(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "reject", "item_id": "event-01"}],
        },
    )

    with pytest.raises(PipelineReferenceConflict) as error:
        service.update_draft(
            "recording-01",
            "events",
            {
                "operator_id": "operator-02",
                "expected_revision": 0,
                "operations": [{"operation": "accept", "item_id": "event-01"}],
            },
        )
    assert error.value.current.draft.revision == 1
    assert error.value.current.draft.items[0].review_state == "rejected"
    assert current.draft.items[0].review_state == "rejected"


def test_correction_keeps_new_item_id_and_records_base_item_id(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _source_revision(revision_store)
    service.create_reference(
        "recording-01",
        "events",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    corrected = service.update_draft(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {
                    "operation": "correct",
                    "item_id": "event-01",
                    "item": {
                        "event_id": "event-corrected",
                        "event_type": "card_state_changed",
                        "start_us": 2_000_000,
                        "end_us": 2_250_000,
                    },
                }
            ],
        },
    )
    item = corrected.draft.items[0]
    assert item.item_id == "event-corrected"
    assert item.base_item_id == "event-01"
    assert item.review_state == "corrected"


def test_reference_write_rejects_retired_event_types(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _source_revision(revision_store)
    service.create_reference(
        "recording-01",
        "events",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )

    with pytest.raises(PipelineReferenceInputError, match="reference item failed"):
        service.update_draft(
            "recording-01",
            "events",
            {
                "operator_id": "operator-01",
                "expected_revision": 0,
                "operations": [
                    {
                        "operation": "add",
                        "item": {
                            "event_id": "event-retired",
                            "event_type": "card_played",
                            "start_us": 2_000_000,
                            "end_us": 2_250_000,
                        },
                    }
                ],
            },
        )


def test_completion_requires_declared_coverage_and_reports_missing_scope(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _source_revision(revision_store)
    service.create_reference(
        "recording-01",
        "events",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )

    with pytest.raises(PipelineReferenceCoverageError) as error:
        service.complete_reference(
            "recording-01",
            "events",
            {"operator_id": "operator-01", "expected_revision": 0},
        )
    assert error.value.details == [
        {"field": "coverage", "message": "declare the reviewed scope before completion"}
    ]

    with pytest.raises(PipelineReferenceCoverageError) as error:
        service.complete_reference(
            "recording-01",
            "events",
            {
                "operator_id": "operator-01",
                "expected_revision": 0,
                "coverage": {"kind": "full_recording", "item_ids": []},
            },
        )
    assert "missing explicit review decision" in error.value.details[0]["message"]

    service.update_draft(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "accept", "item_id": "event-01"}],
        },
    )
    with pytest.raises(PipelineReferenceCoverageError) as error:
        service.complete_reference(
            "recording-01",
            "events",
            {
                "operator_id": "operator-01",
                "expected_revision": 1,
                "coverage": {
                    "kind": "event_intervals",
                    "intervals": [{"start_us": 0, "end_us": 5_000_000}],
                },
            },
        )
    assert "missing coverage interval" in error.value.details[0]["message"]


def test_visible_and_identity_coverage_use_content_specific_decisions(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    visible_revision_id = _vision_source_revision(revision_store, "visible_cards")
    created = service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": visible_revision_id},
    )
    service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {
                    "operation": "decide",
                    "item_id": "event-01",
                    "decision": "empty",
                }
            ],
        },
    )
    with pytest.raises(PipelineReferenceCoverageError) as error:
        service.complete_reference(
            "recording-01",
            "visible_cards",
            {
                "operator_id": "operator-01",
                "expected_revision": 1,
                "coverage": {
                    "kind": "visible_frames",
                    "frames": [
                        {
                            "frame_identity": created.draft.items[0].item["frame_identity"],
                            "decision": "cards",
                        }
                    ],
                },
            },
        )
    assert (
        "positive frame needs an accept, add, or correct decision"
        in error.value.details[0]["message"]
    )

    identity_revision_id = _vision_source_revision(revision_store, "visual_identities")
    identity_created = service.create_reference(
        "recording-01",
        "visual_identities",
        {"operator_id": "operator-01", "source_revision_id": identity_revision_id},
    )
    service.update_draft(
        "recording-01",
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {
                    "operation": "decide",
                    "item_id": "card-01",
                    "decision": "source_problem",
                }
            ],
        },
    )
    with pytest.raises(PipelineReferenceCoverageError) as error:
        service.complete_reference(
            "recording-01",
            "visual_identities",
            {
                "operator_id": "operator-01",
                "expected_revision": 1,
                "coverage": {
                    "kind": "visual_identities",
                    "cards": [
                        {"card_id": identity_created.draft.items[0].item_id, "decision": "identity"}
                    ],
                },
            },
        )
    assert (
        "card needs an accepted identity or a correct decision" in error.value.details[0]["message"]
    )


def test_visible_card_frame_commands_keep_source_identity_and_record_outcomes(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    created = service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    original = dict(created.draft.items[0].item)
    corrected = dict(original)
    corrected["candidates"] = [
        {
            **original["candidates"][0],
            "geometry": {
                "kind": "reviewed-visible-region/v1",
                "visible_region": {
                    "polygons": [
                        [
                            {"x": 5, "y": 5},
                            {"x": 60, "y": 5},
                            {"x": 60, "y": 60},
                            {"x": 5, "y": 60},
                        ]
                    ]
                },
            },
        }
    ]

    reviewed = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {"operation": "set_frame_review", "item_id": "event-01", "item": corrected}
            ],
        },
    )
    assert reviewed.draft.items[0].review_state == "corrected"
    assert reviewed.draft.items[0].item["frame_identity"] == original["frame_identity"]
    assert reviewed.draft.items[0].item["candidates"][0]["side"] == "face_down"
    assert reviewed.draft.items[0].item["candidates"][0]["geometry"]["kind"] == (
        "reviewed-visible-region/v1"
    )

    restored = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "operations": [
                {
                    "operation": "restore_frame_suggestions",
                    "item_id": "event-01",
                    "item": original,
                }
            ],
        },
    )
    assert restored.draft.items[0].review_state == "pending"
    assert restored.draft.items[0].item == original
    assert restored.draft.items[0].item["candidates"][0]["side"] == "face_down"

    accepted = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 2,
            "operations": [{"operation": "accept_frame_suggestions", "item_id": "event-01"}],
        },
    )
    assert accepted.draft.items[0].review_state == "accepted"

    unreviewed = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 3,
            "operations": [{"operation": "set_frame_unreviewed", "item_id": "event-01"}],
        },
    )
    assert unreviewed.draft.items[0].review_state == "pending"
    assert unreviewed.draft.items[0].base_item_id is None
    assert unreviewed.draft.items[0].item == original

    empty = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 4,
            "operations": [{"operation": "set_frame_empty", "item_id": "event-01"}],
        },
    )
    assert empty.draft.items[0].review_state == "empty"
    assert empty.draft.items[0].item["status"] == "empty"
    assert empty.draft.items[0].item["candidates"] == []

    unusable = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 5,
            "operations": [{"operation": "set_frame_unusable", "item_id": "event-01"}],
        },
    )
    assert unusable.draft.items[0].review_state == "unusable"
    assert unusable.draft.items[0].item["status"] == "failed"

    changed_identity = dict(original)
    changed_identity["frame_identity"] = {
        **original["frame_identity"],
        "requested_time_us": 2_000_000,
    }
    with pytest.raises(PipelineReferenceInputError, match="resolved frame identity"):
        service.update_draft(
            "recording-01",
            "visible_cards",
            {
                "operator_id": "operator-01",
                "expected_revision": 6,
                "operations": [
                    {
                        "operation": "set_frame_review",
                        "item_id": "event-01",
                        "item": changed_identity,
                    }
                ],
            },
        )


def _pose_card_scene(*, hidden_back_card: bool = False) -> dict[str, object]:
    poses = [CardPose("card-01", (50.0, 50.0), 0.0, "suggestion-01", None)]
    order = ["card-01"]
    if hidden_back_card:
        poses.append(CardPose("card-back", (50.0, 50.0), 0.0, None, None))
        order = ["card-01", "card-back"]
    scene = ReviewedCardScene.create(
        source_frame_id="frame-01",
        source_frame_width=100,
        source_frame_height=100,
        calibration_revision_id="calibration-01",
        calibration_digest="a" * 64,
        poses=poses,
        stacking_order=CardStackingOrder(
            card_ids=tuple(order), uncertain_edges=(), contradictions=()
        ),
    )
    return {
        "schema_version": "reviewed-card-scene-editor/v1",
        "scene": scene.to_mapping(),
        "initialized_scene": scene.to_mapping(),
        "projection": {
            "table_to_image_homography": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "card_short_size": 20.0,
            "card_long_size": 30.0,
        },
    }


def test_pose_scene_updates_derive_candidates_and_completion_rejects_stale_views(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    created = service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    item = dict(created.draft.items[0].item)
    item["card_scene"] = _pose_card_scene()
    updated = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "set_frame_review", "item_id": "event-01", "item": item}],
        },
    )
    derived_item = updated.draft.items[0].item
    assert derived_item["candidates"][0]["card_id"] == "card-01"
    assert derived_item["candidates"][0]["geometry"]["kind"] == ("reviewed-visible-region/v1")
    assert "derived_region_receipt" in derived_item["card_scene"]

    stale = service.get_reference("recording-01", "visible_cards")
    stale_item = dict(stale.draft.items[0].item)
    stale_scene = dict(stale_item["card_scene"])
    stale_scene["derived_region_receipt"] = {
        **stale_scene["derived_region_receipt"],
        "scene_digest": "b" * 64,
    }
    stale_item["card_scene"] = stale_scene
    with service.reference_store.locked("recording-01", "visible_cards"):
        service.reference_store.write_locked(
            replace(
                stale,
                draft=replace(stale.draft, items=(replace(stale.draft.items[0], item=stale_item),)),
            )
        )
    with pytest.raises(PipelineReferenceCoverageError) as stale_error:
        service.complete_reference(
            "recording-01",
            "visible_cards",
            {
                "operator_id": "operator-01",
                "expected_revision": 1,
                "coverage": {
                    "kind": "visible_frames",
                    "frames": [
                        {"frame_identity": stale_item["frame_identity"], "decision": "cards"}
                    ],
                },
            },
        )
    assert "pose scene derivation" in stale_error.value.details[0]["message"]


def test_proposal_seed_keeps_immutable_scene_and_supports_card_decisions(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(
        revision_store,
        "visible_cards",
        visible_candidate_ids=("card-01", "card-02"),
    )
    proposal_revision_id = _proposal_revision(
        revision_store,
        source_revision_id,
        card_ids=("card-01", "card-02"),
    )

    seeded = service.create_reference(
        SOURCE.recording_id,
        "visible_cards",
        {"operator_id": "operator-01", "proposal_revision_id": proposal_revision_id},
    )
    item = seeded.draft.items[0]
    assert seeded.draft.proposal_revision_id == proposal_revision_id
    assert item.review_state == "pending"
    assert item.item["candidates"] == []
    assert item.item["card_scene"]["proposal_revision_id"] == proposal_revision_id
    assert item.item["card_scene"]["projection"]["table_to_image_homography"]

    with pytest.raises(PipelineReferenceCoverageError):
        service.complete_reference(
            SOURCE.recording_id,
            "visible_cards",
            {
                "operator_id": "operator-01",
                "expected_revision": seeded.draft.revision,
                "coverage": {
                    "kind": "visible_frames",
                    "frames": [
                        {"frame_identity": item.item["frame_identity"], "decision": "cards"}
                    ],
                },
            },
        )

    accepted = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": seeded.draft.revision,
            "operations": [
                {"operation": "accept_card", "item_id": "event-01", "card_id": "card-01"}
            ],
        },
    )
    accepted_item = accepted.draft.items[0]
    assert accepted_item.review_state == "pending"
    assert accepted_item.item["card_scene"]["card_states"] == [
        {
            "card_id": "card-01",
            "source": "proposal",
            "proposal_id": "proposal-event-01",
            "state": "accepted",
        },
        {
            "card_id": "card-02",
            "source": "proposal",
            "proposal_id": "proposal-event-01",
            "state": "pending",
        },
    ]
    assert [candidate["card_id"] for candidate in accepted_item.item["candidates"]] == ["card-01"]
    assert accepted_item.item["card_scene"]["proposal"]["proposal_digest"]

    with pytest.raises(PipelineReferenceConflict):
        service.update_draft(
            SOURCE.recording_id,
            "visible_cards",
            {
                "operator_id": "operator-01",
                "expected_revision": seeded.draft.revision,
                "operations": [
                    {"operation": "reject_card", "item_id": "event-01", "card_id": "card-02"}
                ],
            },
        )

    resolved = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": accepted.draft.revision,
            "operations": [
                {"operation": "reject_card", "item_id": "event-01", "card_id": "card-02"}
            ],
        },
    )
    resolved_item = resolved.draft.items[0]
    assert resolved_item.review_state == "accepted"
    assert resolved_item.item["card_scene"]["completion"]["state"] == "complete"
    assert resolved_item.item["card_scene"]["reviewed"]["scene"]["poses"][0]["card_id"] == (
        "card-01"
    )

    completed = service.complete_reference(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": resolved.draft.revision,
            "coverage": {
                "kind": "visible_frames",
                "frames": [
                    {"frame_identity": resolved_item.item["frame_identity"], "decision": "cards"}
                ],
            },
        },
    )
    completed_revision_id = completed.state.selected_completed_revision_id
    assert completed_revision_id is not None
    completed_revision = revision_store.require(completed_revision_id)
    assert completed_revision.manifest.input_revision_ids == (
        source_revision_id,
        proposal_revision_id,
    )
    stored_item = completed_revision.content.to_mapping()["outcomes"][0]
    assert stored_item["card_scene"]["proposal_revision_id"] == proposal_revision_id
    assert stored_item["card_scene"]["projection"]["table_to_image_homography"]


def test_empty_visible_card_reference_can_rebase_from_proposal_revision(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    proposal_revision_id = _proposal_revision(revision_store, source_revision_id)

    empty = service.create_reference(
        SOURCE.recording_id,
        "visible_cards",
        {"operator_id": "operator-01", "seed": "empty"},
    )
    seeded = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": empty.draft.revision,
            "operations": [
                {
                    "operation": "rebase",
                    "source_revision_id": source_revision_id,
                    "proposal_revision_id": proposal_revision_id,
                }
            ],
        },
    )

    assert seeded.draft.source_revision_id == source_revision_id
    assert seeded.draft.proposal_revision_id == proposal_revision_id
    assert seeded.draft.items[0].item["card_scene"]["proposal_revision_id"] == (
        proposal_revision_id
    )
    assert seeded.draft.items[0].review_state == "pending"


def test_pose_scene_draft_can_keep_hidden_pose_but_completion_rejects_it(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    created = service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    item = dict(created.draft.items[0].item)
    item["card_scene"] = _pose_card_scene(hidden_back_card=True)
    updated = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "set_frame_review", "item_id": "event-01", "item": item}],
        },
    )
    assert updated.draft.items[0].item["candidates"]
    with pytest.raises(PipelineReferenceCoverageError) as hidden_error:
        service.complete_reference(
            "recording-01",
            "visible_cards",
            {
                "operator_id": "operator-01",
                "expected_revision": 1,
                "coverage": {
                    "kind": "visible_frames",
                    "frames": [
                        {
                            "frame_identity": updated.draft.items[0].item["frame_identity"],
                            "decision": "cards",
                        }
                    ],
                },
            },
        )
    assert "fully hidden" in hidden_error.value.details[0]["message"]


def test_visible_card_ignore_region_operations_are_atomic_idempotent_and_durable(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(
        revision_store,
        "visible_cards",
        visible_candidate_ids=("card-01", "card-02"),
    )
    service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    region = {
        "region_id": "ignore-region-01",
        "geometry": {
            "kind": "reviewed-ignore-region/v1",
            "polygons": [
                [
                    {"x": 100, "y": 100},
                    {"x": 700, "y": 100},
                    {"x": 700, "y": 700},
                    {"x": 100, "y": 700},
                ]
            ],
        },
        "normalization": {"width": 100, "height": 100, "policy_id": "full-frame-0-1000/v1"},
        "reason": "untidy_stack",
        "source_candidates": [],
    }

    with pytest.raises(PipelineReferenceInputError, match="ignore region already exists"):
        service.update_draft(
            "recording-01",
            "visible_cards",
            {
                "operator_id": "operator-01",
                "expected_revision": 0,
                "operations": [
                    {
                        "operation": "convert_to_ignore_region",
                        "item_id": "event-01",
                        "candidate_ids": ["card-01"],
                        "region": region,
                    },
                    {
                        "operation": "create_ignore_region",
                        "item_id": "event-01",
                        "region": region,
                    },
                ],
            },
        )
    unchanged = service.get_reference("recording-01", "visible_cards")
    assert unchanged.draft.revision == 0
    assert unchanged.draft.items[0].item["candidates"]
    assert unchanged.draft.items[0].item["ignored_regions"] == []

    converted = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "command_id": "convert-card-01",
            "operations": [
                {
                    "operation": "convert_to_ignore_region",
                    "item_id": "event-01",
                    "candidate_ids": ["card-01"],
                    "region": region,
                }
            ],
        },
    )
    outcome = converted.draft.items[0].item
    assert converted.draft.revision == 1
    assert [candidate["card_id"] for candidate in outcome["candidates"]] == ["card-02"]
    assert outcome["ignored_regions"][0]["source_candidates"] == [
        {"revision_id": source_revision_id, "card_id": "card-01"}
    ]
    assert converted.draft.impact == ()

    replayed = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "command_id": "convert-card-01",
            "operations": [
                {
                    "operation": "convert_to_ignore_region",
                    "item_id": "event-01",
                    "candidate_ids": ["card-01"],
                    "region": region,
                }
            ],
        },
    )
    assert replayed == converted

    accepted = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "operations": [{"operation": "accept_frame_suggestions", "item_id": "event-01"}],
        },
    )
    completed = service.complete_reference(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 2,
            "coverage": {
                "kind": "visible_frames",
                "frames": [
                    {
                        "frame_identity": accepted.draft.items[0].item["frame_identity"],
                        "decision": "cards_and_ignored",
                    }
                ],
            },
        },
    )
    revision_id = completed.state.selected_completed_revision_id
    assert revision_id is not None
    stored = revision_store.require(revision_id)
    assert stored.content.outcomes[0].candidates[0].card_id == "card-02"
    assert stored.content.outcomes[0].ignored_regions[0].source_candidates[0].revision_id == (
        source_revision_id
    )
    restored = PipelineReferenceStore(tmp_path / "operations" / "pipeline-references").require(
        "recording-01", "visible_cards"
    )
    assert restored.draft.items[0].item["ignored_regions"] == outcome["ignored_regions"]


def test_visible_card_ignore_region_create_replace_delete_preserves_lineage_and_is_atomic(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    region = {
        "region_id": "ignore-region-01",
        "geometry": {
            "kind": "reviewed-ignore-region/v1",
            "polygons": [
                [
                    {"x": 100, "y": 100},
                    {"x": 300, "y": 100},
                    {"x": 300, "y": 300},
                    {"x": 100, "y": 300},
                ]
            ],
        },
        "normalization": {"width": 100, "height": 100, "policy_id": "full-frame-0-1000/v1"},
        "reason": "untidy_stack",
        "source_candidates": [],
    }
    service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {"operation": "create_ignore_region", "item_id": "event-01", "region": region}
            ],
        },
    )
    replacement = {
        **region,
        "geometry": {
            **region["geometry"],
            "polygons": [
                [
                    {"x": 150, "y": 150},
                    {"x": 350, "y": 150},
                    {"x": 350, "y": 350},
                    {"x": 150, "y": 350},
                ]
            ],
        },
    }
    replaced = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "operations": [
                {
                    "operation": "replace_ignore_region",
                    "item_id": "event-01",
                    "region_id": "ignore-region-01",
                    "region": replacement,
                }
            ],
        },
    )
    assert replaced.draft.items[0].item["ignored_regions"][0]["geometry"] == replacement["geometry"]
    assert replaced.draft.items[0].item["ignored_regions"][0]["source_candidates"] == []

    with pytest.raises(PipelineReferenceInputError, match="region was not found"):
        service.update_draft(
            "recording-01",
            "visible_cards",
            {
                "operator_id": "operator-01",
                "expected_revision": 2,
                "operations": [
                    {
                        "operation": "delete_ignore_region",
                        "item_id": "event-01",
                        "region_id": "missing-region",
                    }
                ],
            },
        )
    still_replaced = service.get_reference("recording-01", "visible_cards")
    assert still_replaced.draft.revision == 2

    deleted = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 2,
            "operations": [
                {
                    "operation": "delete_ignore_region",
                    "item_id": "event-01",
                    "region_id": "ignore-region-01",
                }
            ],
        },
    )
    assert deleted.draft.items[0].item["ignored_regions"] == []


def test_visible_card_ignore_region_consumes_enclosed_candidates_on_create_not_replace(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(
        revision_store,
        "visible_cards",
        visible_candidate_ids=("card-inside", "card-outside"),
    )
    source = revision_store.require(source_revision_id)
    source_mapping = source.content.to_mapping()
    source_mapping["outcomes"][0]["candidates"][0]["geometry"] = {
        "kind": "detector-box/v1",
        "box_2d": {"x_min": 200, "y_min": 200, "x_max": 400, "y_max": 400},
    }
    source_mapping["outcomes"][0]["candidates"][1]["geometry"] = {
        "kind": "detector-box/v1",
        "box_2d": {"x_min": 700, "y_min": 700, "x_max": 900, "y_max": 900},
    }
    content = VisibleCardData.from_mapping(source_mapping)
    source_revision_id = "generated-visible-cards-geometry"
    revision_store.publish(
        replace(
            source.manifest,
            revision_id=source_revision_id,
            content_sha256=sha256_bytes(canonical_visible_card_data_bytes(content)),
        ),
        content,
    )

    service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    region = {
        "region_id": "ignore-region-01",
        "geometry": {
            "kind": "reviewed-ignore-region/v1",
            "polygons": [
                [
                    {"x": 100, "y": 100},
                    {"x": 500, "y": 100},
                    {"x": 500, "y": 500},
                    {"x": 100, "y": 500},
                ]
            ],
        },
        "normalization": {"width": 100, "height": 100, "policy_id": "full-frame-0-1000/v1"},
        "reason": "untidy_stack",
        "source_candidates": [],
    }
    created = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {"operation": "create_ignore_region", "item_id": "event-01", "region": region}
            ],
        },
    )
    created_outcome = created.draft.items[0].item
    assert [candidate["card_id"] for candidate in created_outcome["candidates"]] == ["card-outside"]
    assert created_outcome["ignored_regions"][0]["source_candidates"] == [
        {"revision_id": source_revision_id, "card_id": "card-inside"}
    ]

    expanded = {
        **region,
        "geometry": {
            **region["geometry"],
            "polygons": [
                [
                    {"x": 0, "y": 0},
                    {"x": 1000, "y": 0},
                    {"x": 1000, "y": 1000},
                    {"x": 0, "y": 1000},
                ]
            ],
        },
        "source_candidates": [{"revision_id": source_revision_id, "card_id": "card-outside"}],
    }
    replaced = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "operations": [
                {
                    "operation": "replace_ignore_region",
                    "item_id": "event-01",
                    "region_id": "ignore-region-01",
                    "region": expanded,
                }
            ],
        },
    )
    replaced_outcome = replaced.draft.items[0].item
    assert [candidate["card_id"] for candidate in replaced_outcome["candidates"]] == [
        "card-outside"
    ]
    assert replaced_outcome["ignored_regions"][0]["source_candidates"] == [
        {"revision_id": source_revision_id, "card_id": "card-inside"},
    ]


def test_visible_card_ignore_region_edit_migrates_missing_legacy_regions(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    current = service.get_reference("recording-01", "visible_cards")
    legacy_item = dict(current.draft.items[0].item)
    legacy_item.pop("ignored_regions")
    legacy = StoredPipelineReference(
        state=current.state,
        draft=replace(
            current.draft,
            items=(replace(current.draft.items[0], item=legacy_item),),
        ),
    )
    with service.reference_store.locked("recording-01", "visible_cards"):
        service.reference_store.write_locked(legacy)

    region = {
        "region_id": "ignore-region-legacy",
        "geometry": {
            "kind": "reviewed-ignore-region/v1",
            "polygons": [
                [
                    {"x": 100, "y": 100},
                    {"x": 700, "y": 100},
                    {"x": 700, "y": 700},
                    {"x": 100, "y": 700},
                ]
            ],
        },
        "normalization": {"width": 100, "height": 100, "policy_id": "full-frame-0-1000/v1"},
        "reason": "untidy_stack",
        "source_candidates": [],
    }

    updated = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {"operation": "create_ignore_region", "item_id": "event-01", "region": region}
            ],
        },
    )

    assert updated.draft.items[0].item["ignored_regions"] == [region]


def test_visible_card_frame_review_migrates_missing_legacy_regions(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    current = service.get_reference("recording-01", "visible_cards")
    legacy_item = dict(current.draft.items[0].item)
    legacy_item.pop("ignored_regions")
    legacy = StoredPipelineReference(
        state=current.state,
        draft=replace(
            current.draft,
            items=(replace(current.draft.items[0], item=legacy_item),),
        ),
    )
    with service.reference_store.locked("recording-01", "visible_cards"):
        service.reference_store.write_locked(legacy)

    corrected = {**legacy_item, "ignored_regions": []}
    updated = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {"operation": "set_frame_review", "item_id": "event-01", "item": corrected}
            ],
        },
    )

    assert updated.draft.items[0].review_state == "corrected"
    assert updated.draft.items[0].item["ignored_regions"] == []


def test_visible_card_completion_migrates_missing_legacy_regions(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    current = service.get_reference("recording-01", "visible_cards")
    legacy_item = dict(current.draft.items[0].item)
    legacy_item.pop("ignored_regions")
    legacy = StoredPipelineReference(
        state=current.state,
        draft=replace(
            current.draft,
            items=(replace(current.draft.items[0], review_state="accepted", item=legacy_item),),
        ),
    )
    with service.reference_store.locked("recording-01", "visible_cards"):
        service.reference_store.write_locked(legacy)

    completed = service.complete_reference(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "coverage": {
                "kind": "visible_frames",
                "frames": [
                    {
                        "frame_identity": legacy_item["frame_identity"],
                        "decision": "cards",
                    }
                ],
            },
        },
    )

    revision_id = completed.state.selected_completed_revision_id
    assert revision_id is not None
    stored = revision_store.require(revision_id)
    assert stored.content.outcomes[0].ignored_regions == ()
    assert completed.draft.items[0].item["ignored_regions"] == []


def test_visible_card_ignore_only_coverage_and_rebase_preserve_region(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    first_revision = _vision_source_revision(revision_store, "visible_cards")
    second_revision = _vision_source_revision(
        revision_store, "visible_cards", revision_id="generated-visible_cards-02"
    )
    service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": first_revision},
    )
    region = {
        "region_id": "ignore-region-01",
        "geometry": {
            "kind": "reviewed-ignore-region/v1",
            "polygons": [
                [
                    {"x": 100, "y": 100},
                    {"x": 700, "y": 100},
                    {"x": 700, "y": 700},
                    {"x": 100, "y": 700},
                ]
            ],
        },
        "normalization": {"width": 100, "height": 100, "policy_id": "full-frame-0-1000/v1"},
        "reason": "untidy_stack",
        "source_candidates": [],
    }
    converted = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {
                    "operation": "convert_to_ignore_region",
                    "item_id": "event-01",
                    "candidate_ids": ["card-01"],
                    "region": region,
                }
            ],
        },
    )
    rebased = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "source_revision_id": second_revision,
            "operations": [],
        },
    )
    assert rebased.draft.source_revision_id == second_revision
    assert rebased.draft.items[0].item["candidates"] == []
    assert rebased.draft.items[0].item["ignored_regions"][0]["source_candidates"] == [
        {"revision_id": first_revision, "card_id": "card-01"}
    ]

    completed = service.complete_reference(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 2,
            "coverage": {
                "kind": "visible_frames",
                "frames": [
                    {
                        "frame_identity": converted.draft.items[0].item["frame_identity"],
                        "decision": "ignored",
                    }
                ],
            },
        },
    )
    assert completed.draft.items[0].item["ignored_regions"]


def test_identity_commands_preserve_geometry_and_support_manual_labels(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    identity_revision_id = _vision_source_revision(revision_store, "visual_identities")
    created = service.create_reference(
        SOURCE.recording_id,
        "visual_identities",
        {"operator_id": "operator-01", "source_revision_id": identity_revision_id},
    )
    original = created.draft.items[0].item

    selected = service.update_draft(
        SOURCE.recording_id,
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "command_id": "identity-select-1",
            "operations": [
                {
                    "operation": "select_identity",
                    "item_id": "card-01",
                    "identity": "HEARTS_QUEEN",
                }
            ],
        },
    )
    selected_item = selected.draft.items[0]
    assert selected_item.review_state == "accepted"
    assert selected_item.item["geometry"] == original["geometry"]
    assert selected_item.item["candidates"] == [
        {
            "identity": "HEARTS_QUEEN",
            "score": None,
            "score_meaning": None,
            "producer_id": "human-reference.v1",
        }
    ]

    unusable = service.update_draft(
        SOURCE.recording_id,
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "operations": [{"operation": "set_identity_unusable", "item_id": "card-01"}],
        },
    )
    assert unusable.draft.items[0].review_state == "identity_unusable"
    assert unusable.draft.items[0].item["status"] == "unusable"

    unreviewed = service.update_draft(
        SOURCE.recording_id,
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 2,
            "operations": [{"operation": "set_identity_unreviewed", "item_id": "card-01"}],
        },
    )
    assert unreviewed.draft.items[0].review_state == "pending"
    assert unreviewed.draft.items[0].base_item_id is None
    assert unreviewed.draft.items[0].item["status"] == "unusable"

    source_problem = service.update_draft(
        SOURCE.recording_id,
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 3,
            "operations": [
                {
                    "operation": "report_identity_source_problem",
                    "item_id": "card-01",
                }
            ],
        },
    )
    assert source_problem.draft.items[0].review_state == "source_problem"
    assert source_problem.draft.items[0].item["status"] == "failed"

    face_down = service.update_draft(
        SOURCE.recording_id,
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 4,
            "operations": [{"operation": "set_identity_face_down", "item_id": "card-01"}],
        },
    )
    assert face_down.draft.items[0].review_state == "face_down"
    assert face_down.draft.items[0].item["status"] == "face_down"
    assert face_down.draft.items[0].item["geometry"] == original["geometry"]
    assert face_down.draft.items[0].item["candidates"] == []

    completed = service.complete_reference(
        SOURCE.recording_id,
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 5,
            "coverage": {
                "kind": "visual_identities",
                "cards": [{"card_id": "card-01", "decision": "face_down"}],
            },
        },
    )
    completed_id = completed.state.selected_completed_revision_id
    assert completed_id is not None
    assert revision_store.require(completed_id).content.outcomes[0].status == "face_down"


def test_completed_identity_reference_repairs_visible_face_down_as_new_revision(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    visible_revision_id = _vision_source_revision(revision_store, "visible_cards")
    visible = service.create_reference(
        SOURCE.recording_id,
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": visible_revision_id},
    )
    service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "accept", "item_id": "event-01"}],
        },
    )
    service.complete_reference(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "coverage": {
                "kind": "visible_frames",
                "frames": [
                    {
                        "frame_identity": visible.draft.items[0].item["frame_identity"],
                        "decision": "cards",
                    }
                ],
            },
        },
    )

    identity_revision_id = _vision_source_revision(revision_store, "visual_identities")
    identity = service.create_reference(
        SOURCE.recording_id,
        "visual_identities",
        {"operator_id": "operator-01", "source_revision_id": identity_revision_id},
    )
    service.update_draft(
        SOURCE.recording_id,
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "set_identity_unusable", "item_id": "card-01"}],
        },
    )
    completed = service.complete_reference(
        SOURCE.recording_id,
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "coverage": {
                "kind": "visual_identities",
                "cards": [{"card_id": identity.draft.items[0].item_id, "decision": "unusable"}],
            },
        },
    )
    old_revision_id = completed.state.selected_completed_revision_id
    assert old_revision_id is not None

    repaired = service.get_reference(SOURCE.recording_id, "visual_identities")
    new_revision_id = repaired.state.selected_completed_revision_id
    assert new_revision_id is not None
    assert new_revision_id != old_revision_id
    assert repaired.draft.items[0].review_state == "face_down"
    assert repaired.draft.items[0].item["status"] == "face_down"
    assert repaired.draft.coverage is not None
    assert repaired.draft.coverage["cards"] == [{"card_id": "card-01", "decision": "face_down"}]
    assert revision_store.require(old_revision_id).content.outcomes[0].status == "unusable"
    assert revision_store.require(new_revision_id).content.outcomes[0].status == "face_down"
    assert (
        service.selection_store.get(
            SOURCE.recording_id, "visual_identities"
        ).selected_completed_reference_revision_id
        == new_revision_id
    )
    assert (
        service.get_reference(
            SOURCE.recording_id, "visual_identities"
        ).state.selected_completed_revision_id
        == new_revision_id
    )


def test_face_down_identity_suggestion_can_be_accepted(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    identity_revision_id = _vision_source_revision(
        revision_store, "visual_identities", identity_status="face_down"
    )

    service.create_reference(
        SOURCE.recording_id,
        "visual_identities",
        {"operator_id": "operator-01", "source_revision_id": identity_revision_id},
    )

    accepted = service.update_draft(
        SOURCE.recording_id,
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "accept_identity_suggestion", "item_id": "card-01"}],
        },
    )

    item = accepted.draft.items[0]
    assert item.review_state == "accepted"
    assert item.item["status"] == "face_down"
    assert item.item["candidates"] == []


def test_identity_status_batch_skips_full_draft_revalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, revision_store = _service(tmp_path)
    identity_revision_id = _vision_source_revision(revision_store, "visual_identities")
    service.create_reference(
        SOURCE.recording_id,
        "visual_identities",
        {"operator_id": "operator-01", "source_revision_id": identity_revision_id},
    )
    handler = service._handler("visual_identities")

    def fail_full_validation(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("status-only identity operations must not revalidate the full draft")

    monkeypatch.setattr(handler, "validate_draft_items", fail_full_validation)
    updated = service.update_draft(
        SOURCE.recording_id,
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {"operation": "accept_identity_suggestion", "item_id": "card-01"},
                {"operation": "set_identity_unreviewed", "item_id": "card-01"},
                {"operation": "accept_identity_suggestion", "item_id": "card-01"},
            ],
        },
    )

    assert updated.draft.revision == 1
    assert updated.draft.items[0].review_state == "accepted"


def test_correction_records_downstream_impact_and_coverage_survives_restart(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    event_revision_id = _source_revision(revision_store)
    visible_revision_id = _vision_source_revision(revision_store, "visible_cards")
    identity_revision_id = _vision_source_revision(revision_store, "visual_identities")
    for content_type, revision_id, kind in (
        ("visible_cards", visible_revision_id, "visible_frames"),
        ("visual_identities", identity_revision_id, "visual_identities"),
    ):
        service.create_reference(
            "recording-01",
            content_type,
            {"operator_id": "operator-01", "source_revision_id": revision_id},
        )
        draft_item = service.get_reference("recording-01", content_type).draft.items[0]
        item_id = draft_item.item_id
        service.update_draft(
            "recording-01",
            content_type,
            {
                "operator_id": "operator-01",
                "expected_revision": 0,
                "operations": [{"operation": "accept", "item_id": item_id}],
            },
        )
        service.complete_reference(
            "recording-01",
            content_type,
            {
                "operator_id": "operator-01",
                "expected_revision": 1,
                "coverage": {
                    "kind": kind,
                    "frames": [
                        {
                            "frame_identity": draft_item.item["frame_identity"],
                            "decision": "cards",
                        }
                    ],
                }
                if content_type == "visible_cards"
                else {
                    "kind": kind,
                    "cards": [{"card_id": item_id, "decision": "identity"}],
                },
            },
        )
    service.create_reference(
        "recording-01",
        "events",
        {"operator_id": "operator-01", "source_revision_id": event_revision_id},
    )
    corrected = service.update_draft(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {
                    "operation": "correct",
                    "item_id": "event-01",
                    "item": {
                        "event_id": "event-corrected",
                        "event_type": "card_state_changed",
                        "start_us": 2_000_000,
                        "end_us": 2_250_000,
                    },
                }
            ],
        },
    )
    assert {
        (entry["downstream_content_type"], tuple(entry["affected_item_ids"]))
        for entry in corrected.draft.impact
    } == {("visible_cards", ("event-01",)), ("visual_identities", ("card-01",))}

    completed = service.complete_reference(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "coverage": {"kind": "full_recording"},
        },
    )
    revision_id = completed.state.selected_completed_revision_id
    assert revision_id is not None
    assert revision_store.require(revision_id).manifest.coverage["impact"] == list(
        completed.draft.impact
    )
    restored = PipelineReferenceStore(tmp_path / "operations" / "pipeline-references").require(
        "recording-01", "events"
    )
    assert restored.draft.coverage == completed.draft.coverage
    assert restored.draft.impact == completed.draft.impact


def test_rebase_preserves_unchanged_event_decisions_and_marks_changed_items_affected(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    original_revision_id = _source_revision(revision_store)
    matching_revision_id = _event_revision_variant(revision_store, "generated-events-02")
    changed_revision_id = _event_revision_variant(
        revision_store, "generated-events-03", start_us=2_000_000
    )
    service.create_reference(
        "recording-01",
        "events",
        {"operator_id": "operator-01", "source_revision_id": original_revision_id},
    )
    service.update_draft(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "accept", "item_id": "event-01"}],
        },
    )
    matching = service.update_draft(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "source_revision_id": matching_revision_id,
        },
    )
    assert matching.draft.source_revision_id == matching_revision_id
    assert matching.draft.items[0].review_state == "accepted"

    changed = service.update_draft(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 2,
            "source_revision_id": changed_revision_id,
        },
    )
    assert changed.draft.items[0].review_state == "affected"
    with pytest.raises(PipelineReferenceCoverageError) as error:
        service.complete_reference(
            "recording-01",
            "events",
            {
                "operator_id": "operator-01",
                "expected_revision": 3,
                "coverage": {"kind": "full_recording"},
            },
        )
    assert "evidence changed" in error.value.details[0]["message"]


def test_empty_reference_can_add_a_source_linked_manual_item(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    service._source_for = lambda recording_id, source_revision_id: SOURCE  # type: ignore[method-assign]
    created = service.create_reference(
        "recording-01",
        "events",
        {"operator_id": "operator-01", "seed": "empty"},
    )
    assert created.draft.items == ()

    added = service.update_draft(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {
                    "operation": "add",
                    "item": {
                        "event_id": "event-added",
                        "event_type": "card_state_changed",
                        "start_us": 1_000_000,
                        "end_us": 1_250_000,
                    },
                }
            ],
        },
    )
    assert added.draft.items[0].review_state == "added"
    completed = service.complete_reference(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "coverage": {"kind": "full_recording"},
        },
    )
    revision_id = completed.state.selected_completed_revision_id
    assert revision_id is not None
    revision = revision_store.require(revision_id)
    assert revision.manifest.origin == "manual"
    assert revision.manifest.producer.base_revision_id is None


@pytest.mark.parametrize("content_type", ["visible_cards", "visual_identities"])
def test_each_vision_content_type_has_an_independent_reference(
    tmp_path: Path, content_type: str
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, content_type)

    created = service.create_reference(
        "recording-01",
        content_type,
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    item_id = created.draft.items[0].item_id
    service.update_draft(
        "recording-01",
        content_type,
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "accept", "item_id": item_id}],
        },
    )
    completed = service.complete_reference(
        "recording-01",
        content_type,
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "coverage": {
                "kind": "visible_frames",
                "frames": [
                    {
                        "frame_identity": created.draft.items[0].item["frame_identity"],
                        "decision": "cards",
                    }
                ],
            }
            if content_type == "visible_cards"
            else {
                "kind": "visual_identities",
                "cards": [{"card_id": item_id, "decision": "identity"}],
            },
        },
    )
    assert completed is not None


def test_reference_http_api_exposes_conflicts_and_completed_selection(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_test_app(settings)
    with TestClient(app) as client:
        source_revision_id = _source_revision(app.state.pipeline_revision_store)
        base = "/api/recordings/recording-01/pipeline/references/events"
        created = client.post(
            base,
            json={"operator_id": "operator-01", "source_revision_id": source_revision_id},
        )
        assert created.status_code == 201
        updated = client.put(
            base + "/draft",
            json={
                "operator_id": "operator-01",
                "expected_revision": 0,
                "command_id": "command-01",
                "operations": [{"operation": "accept", "item_id": "event-01"}],
            },
        )
        assert updated.status_code == 200
        replayed = client.put(
            base + "/draft",
            json={
                "operator_id": "operator-01",
                "expected_revision": 0,
                "command_id": "command-01",
                "operations": [{"operation": "accept", "item_id": "event-01"}],
            },
        )
        assert replayed.status_code == 200
        assert replayed.json()["draft"]["revision"] == 1
        assert replayed.json()["draft"]["items"][0]["review_state"] == "accepted"
        stale = client.put(
            base + "/draft",
            json={
                "operator_id": "operator-02",
                "expected_revision": 0,
                "operations": [{"operation": "reject", "item_id": "event-01"}],
            },
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["details"] == [{"field": "current_revision", "message": "1"}]
        incomplete = client.post(
            base + "/complete",
            json={"operator_id": "operator-01", "expected_revision": 1},
        )
        assert incomplete.status_code == 422
        assert incomplete.json()["error"]["code"] == "incomplete_reference_coverage"
        assert incomplete.json()["error"]["details"] == [
            {"field": "coverage", "message": "declare the reviewed scope before completion"}
        ]
        completed = client.post(
            base + "/complete",
            json={
                "operator_id": "operator-01",
                "expected_revision": 1,
                "coverage": {"kind": "full_recording"},
            },
        )
        assert completed.status_code == 201
        revision_id = completed.json()["state"]["selected_completed_revision_id"]
        selection = client.get("/api/recordings/recording-01/pipeline/events/selection")
        assert selection.status_code == 200
        assert (
            selection.json()["selection"]["selected_completed_reference_revision_id"] == revision_id
        )

    restarted = create_test_app(settings)
    with TestClient(restarted) as client:
        response = client.get("/api/recordings/recording-01/pipeline/references/events")
        assert response.status_code == 200
        assert response.json()["state"]["selected_completed_revision_id"] == revision_id
