from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from app_factory import create_test_app
from doko_operations.card_plane_geometry import (
    CardPose,
    CardStackingOrder,
    ReviewedCardScene,
    derive_pose_scene_visible_regions,
)
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
    visible_frame_indexes: tuple[int, ...] = (0,),
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
                    "event_id": f"event-{index + 1:02d}",
                    "frame_identity": {
                        **frame,
                        "frame_index": frame_index,
                        "requested_time_us": (frame_index + 1) * 1_000_000,
                        "presentation_timestamp_us": (frame_index + 1) * 1_000_000,
                    },
                    "status": "detected",
                    "candidates": candidates,
                    "ignored_regions": [],
                    "error": None,
                }
                for index, frame_index in enumerate(visible_frame_indexes)
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
            "schema_version": "visual-identity-data/v2",
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
        schema = "visual-identity-data/v2"
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
    monkeypatch: pytest.MonkeyPatch,
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

    revision_reads: list[str] = []
    read_revision = revision_store._read_path

    def track_read(path: Path, **kwargs: object) -> object:
        revision_reads.append(path.name)
        return read_revision(path, **kwargs)

    monkeypatch.setattr(revision_store, "_read_path", track_read)
    completed = service.complete_reference(
        "recording-01",
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "coverage": {"kind": "full_recording"},
        },
    )
    assert revision_reads.count(source_revision_id) == 1
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


def test_completion_retry_reuses_revision_published_before_partial_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _source_revision(revision_store)
    service.create_reference(
        SOURCE.recording_id,
        "events",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    service.update_draft(
        SOURCE.recording_id,
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "accept", "item_id": "event-01"}],
        },
    )
    original_select_completed = service._select_completed

    def fail_after_publish(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("fixture failure after revision publish")

    monkeypatch.setattr(service, "_select_completed", fail_after_publish)
    payload = {
        "operator_id": "operator-01",
        "expected_revision": 1,
        "coverage": {"kind": "full_recording"},
    }
    with pytest.raises(RuntimeError, match="fixture failure after revision publish"):
        service.complete_reference(SOURCE.recording_id, "events", payload)

    monkeypatch.setattr(service, "_select_completed", original_select_completed)
    completed = service.complete_reference(SOURCE.recording_id, "events", payload)

    assert completed.state.draft_state == "completed"
    assert completed.state.selected_completed_revision_id is not None


def test_completion_revalidates_source_lineage_on_the_next_request(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_id = _source_revision(revision_store)
    service.create_reference(
        SOURCE.recording_id,
        "events",
        {"operator_id": "operator-01", "source_revision_id": source_id},
    )
    service.update_draft(
        SOURCE.recording_id,
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [{"operation": "accept", "item_id": "event-01"}],
        },
    )
    service.complete_reference(
        SOURCE.recording_id,
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "coverage": {"kind": "full_recording"},
        },
    )
    service.update_draft(
        SOURCE.recording_id,
        "events",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "operations": [{"operation": "accept", "item_id": "event-01"}],
        },
    )
    (revision_store.revision_path(source_id) / "content.json").write_bytes(b"{}")
    with pytest.raises(PipelineReferenceInputError, match="source revision was not found"):
        service.complete_reference(
            SOURCE.recording_id,
            "events",
            {
                "operator_id": "operator-01",
                "expected_revision": 2,
                "coverage": {"kind": "full_recording"},
            },
        )


def test_reference_store_get_state_skips_draft(tmp_path: Path, monkeypatch) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _source_revision(revision_store)
    service.create_reference(
        "recording-01",
        "events",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    store = service.reference_store
    reads: list[str] = []
    real_read = Path.read_bytes

    def tracked_read(self: Path) -> bytes:
        reads.append(self.name)
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", tracked_read)

    state = store.get_state("recording-01", "events")
    assert state is not None
    assert state.draft_state == "draft"
    assert state.source_revision_id == source_revision_id
    assert "draft.json" not in reads
    assert "state.json" in reads


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


def test_identity_coverage_reports_manual_upstream_card_without_crashing(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path)
    handler = service._handlers["visual_identities"]
    handler._selected_revision = lambda recording_id, content_type: SimpleNamespace(
        content=SimpleNamespace(
            to_mapping=lambda: {
                "outcomes": [
                    {
                        "status": "detected",
                        "candidates": [{"card_id": "manual-card-1"}],
                    }
                ]
            }
        )
    )

    with pytest.raises(PipelineReferenceCoverageError) as error:
        handler.validate_coverage(
            {
                "cards": [{"card_id": "manual-card-1", "decision": "identity"}],
            },
            (),
            SOURCE,
            SOURCE.recording_id,
        )

    assert error.value.details == [
        {
            "field": "coverage.cards.manual-card-1",
            "message": "upstream card has no identity result; mark it unusable",
        }
    ]


def test_identity_coverage_uses_frame_scoped_result_for_manual_upstream_card(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path)
    handler = service._handlers["visual_identities"]
    frame_identity = {"frame_index": 2671}
    geometry = {"kind": "fixture-geometry"}
    handler._selected_revision = lambda recording_id, content_type: SimpleNamespace(
        content=SimpleNamespace(
            to_mapping=lambda: {
                "outcomes": [
                    {
                        "status": "detected",
                        "frame_identity": frame_identity,
                        "candidates": [{"card_id": "manual-card-1", "geometry": geometry}],
                    }
                ]
            }
        )
    )
    identity_item = SimpleNamespace(
        item_id="manual-card-1-frame-2671-abc123",
        item={
            "frame_identity": frame_identity,
            "geometry": geometry,
            "status": "classified",
            "candidates": [{"identity": "CLUBS_NINE"}],
        },
        review_state="accepted",
    )

    coverage = handler.validate_coverage(
        {
            "cards": [
                {"card_id": identity_item.item_id, "decision": "identity"},
            ],
        },
        (identity_item,),
        SOURCE,
        SOURCE.recording_id,
    )

    assert coverage["cards"] == [{"card_id": identity_item.item_id, "decision": "identity"}]


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


def test_set_frame_pending_preserves_virtual_card_decisions(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    proposal_revision_id = _proposal_revision(revision_store, source_revision_id)
    seeded = service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "proposal_revision_id": proposal_revision_id},
    )
    rejected = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": seeded.draft.revision,
            "operations": [
                {
                    "operation": "reject_card",
                    "item_id": "event-01",
                    "card_id": "card-01",
                }
            ],
        },
    )
    reviewed_item = rejected.draft.items[0].item

    pending = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": rejected.draft.revision,
            "operations": [{"operation": "set_frame_pending", "item_id": "event-01"}],
        },
    )

    assert pending.draft.items[0].review_state == "pending"
    assert pending.draft.items[0].item == reviewed_item


def test_ignore_region_added_after_virtual_card_review_removes_covered_pose(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    proposal_revision_id = _proposal_revision(revision_store, source_revision_id)
    seeded = service.create_reference(
        SOURCE.recording_id,
        "visible_cards",
        {"operator_id": "operator-01", "proposal_revision_id": proposal_revision_id},
    )
    accepted = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": seeded.draft.revision,
            "operations": [
                {
                    "operation": "accept_card",
                    "item_id": "event-01",
                    "card_id": "card-01",
                }
            ],
        },
    )
    accepted = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": accepted.draft.revision,
            "operations": [
                {"operation": "accept_card", "item_id": "event-01", "card_id": "card-01"}
            ],
        },
    )
    region = {
        "region_id": "ignore-all-01",
        "geometry": {
            "kind": "reviewed-ignore-region/v1",
            "polygons": [
                [
                    {"x": 0, "y": 0},
                    {"x": 1000, "y": 0},
                    {"x": 1000, "y": 1000},
                    {"x": 0, "y": 1000},
                ]
            ],
        },
        "normalization": {"width": 100, "height": 100, "policy_id": "full-frame-0-1000/v1"},
        "reason": "untidy_stack",
        "source_candidates": [],
    }

    updated = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": accepted.draft.revision,
            "operations": [
                {"operation": "create_ignore_region", "item_id": "event-01", "region": region}
            ],
        },
    )

    item = updated.draft.items[0].item
    assert item["candidates"] == []
    assert item["card_scene"]["reviewed"] is None
    assert item["card_scene"]["card_states"][0]["state"] == "rejected"


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
    assert item.item["card_scene"]["projection"]["card_short_size"] == 20.0
    assert item.item["card_scene"]["projection"]["card_long_size"] == pytest.approx(
        20.0 * 91.0 / 59.0
    )

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


def test_convert_to_ignore_rejects_proposal_cards_and_survive_rederive(
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
    accepted = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": seeded.draft.revision,
            "operations": [
                {"operation": "accept_card", "item_id": "event-01", "card_id": "card-01"},
                {"operation": "accept_card", "item_id": "event-01", "card_id": "card-02"},
            ],
        },
    )
    assert {candidate["card_id"] for candidate in accepted.draft.items[0].item["candidates"]} == {
        "card-01",
        "card-02",
    }

    region = {
        "region_id": "ignore-stack-01",
        "geometry": {
            "kind": "reviewed-ignore-region/v1",
            "polygons": [
                [
                    {"x": 0, "y": 0},
                    {"x": 500, "y": 0},
                    {"x": 500, "y": 1000},
                    {"x": 0, "y": 1000},
                ]
            ],
        },
        "normalization": {"width": 100, "height": 100, "policy_id": "full-frame-0-1000/v1"},
        "reason": "untidy_stack",
        "source_candidates": [],
    }
    converted = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": accepted.draft.revision,
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
    item = converted.draft.items[0].item
    assert [candidate["card_id"] for candidate in item["candidates"]] == ["card-02"]
    assert item["ignored_regions"][0]["source_candidates"][0]["card_id"] == "card-01"
    states = {state["card_id"]: state["state"] for state in item["card_scene"]["card_states"]}
    assert states == {"card-01": "rejected", "card-02": "accepted"}
    assert [pose["card_id"] for pose in item["card_scene"]["reviewed"]["scene"]["poses"]] == [
        "card-02"
    ]

    refreshed = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": converted.draft.revision,
            "operations": [{"operation": "accept_frame_suggestions", "item_id": "event-01"}],
        },
    )
    refreshed_item = refreshed.draft.items[0].item
    assert [candidate["card_id"] for candidate in refreshed_item["candidates"]] == ["card-02"]
    assert refreshed_item["ignored_regions"][0]["source_candidates"][0]["card_id"] == "card-01"
    refreshed_states = {
        state["card_id"]: state["state"] for state in refreshed_item["card_scene"]["card_states"]
    }
    assert refreshed_states["card-01"] == "rejected"


def test_proposal_scene_angle_correction_updates_reviewed_scene(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    proposal_revision_id = _proposal_revision(revision_store, source_revision_id)
    seeded = service.create_reference(
        SOURCE.recording_id,
        "visible_cards",
        {"operator_id": "operator-01", "proposal_revision_id": proposal_revision_id},
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
    accepted_item = accepted.draft.items[0].item
    selected_scene = ReviewedCardScene.from_mapping(
        accepted_item["card_scene"]["reviewed"]["scene"]
    )
    adjusted_scene = ReviewedCardScene.create(
        source_frame_id=selected_scene.source_frame_id,
        source_frame_width=selected_scene.source_frame_width,
        source_frame_height=selected_scene.source_frame_height,
        calibration_revision_id=selected_scene.calibration_revision_id,
        calibration_digest=selected_scene.calibration_digest,
        poses=tuple(replace(pose, rotation_degrees=17.0) for pose in selected_scene.poses),
        stacking_order=selected_scene.stacking_order,
    )
    projection = accepted_item["card_scene"]["projection"]
    derivation = derive_pose_scene_visible_regions(adjusted_scene, projection)
    corrected = dict(accepted_item)
    corrected["card_scene"] = {
        "schema_version": "reviewed-card-scene-editor/v1",
        "scene": adjusted_scene.to_mapping(),
        "initialized_scene": accepted_item["card_scene"]["proposal"]["initialized_scene"],
        "projection": projection,
        "derived_region_receipt": derivation.receipt.to_mapping(),
    }
    corrected["candidates"] = [
        {
            "card_id": region["card_id"],
            "geometry": region["geometry"],
            "normalization": region["normalization"],
            "side": "unknown",
        }
        for region in derivation.regions
    ]

    updated = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": accepted.draft.revision,
            "operations": [
                {"operation": "set_frame_review", "item_id": "event-01", "item": corrected}
            ],
        },
    )

    assert updated.draft.items[0].review_state == "corrected"
    assert (
        updated.draft.items[0].item["card_scene"]["reviewed"]["scene"]["poses"][0][
            "rotation_degrees"
        ]
        == 17.0
    )


def test_set_frame_review_persists_a_removed_virtual_card(tmp_path: Path) -> None:
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
    accepted = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": seeded.draft.revision,
            "operations": [
                {"operation": "accept_frame_suggestions", "item_id": "event-01"},
            ],
        },
    )
    accepted_item = accepted.draft.items[0].item
    accepted_scene = ReviewedCardScene.from_mapping(
        accepted_item["card_scene"]["reviewed"]["scene"]
    )
    remaining_pose = next(pose for pose in accepted_scene.poses if pose.card_id == "card-02")
    deleted_scene = ReviewedCardScene.create(
        source_frame_id=accepted_scene.source_frame_id,
        source_frame_width=accepted_scene.source_frame_width,
        source_frame_height=accepted_scene.source_frame_height,
        calibration_revision_id=accepted_scene.calibration_revision_id,
        calibration_digest=accepted_scene.calibration_digest,
        poses=(remaining_pose,),
        stacking_order=CardStackingOrder(
            card_ids=(remaining_pose.card_id,), uncertain_edges=(), contradictions=()
        ),
    )
    projection = accepted_item["card_scene"]["projection"]
    derivation = derive_pose_scene_visible_regions(deleted_scene, projection)
    corrected_item = dict(accepted_item)
    corrected_item["card_scene"] = {
        "schema_version": "reviewed-card-scene-editor/v1",
        "scene": deleted_scene.to_mapping(),
        "initialized_scene": accepted_item["card_scene"]["proposal"]["initialized_scene"],
        "projection": projection,
    }
    corrected_item["candidates"] = [
        {
            "card_id": region["card_id"],
            "geometry": region["geometry"],
            "normalization": region["normalization"],
            "side": "unknown",
        }
        for region in derivation.regions
    ]

    updated = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": accepted.draft.revision,
            "operations": [
                {"operation": "set_frame_review", "item_id": "event-01", "item": corrected_item}
            ],
        },
    )

    updated_item = updated.draft.items[0].item
    assert [candidate["card_id"] for candidate in updated_item["candidates"]] == ["card-02"]
    assert [
        pose["card_id"] for pose in updated_item["card_scene"]["reviewed"]["scene"]["poses"]
    ] == ["card-02"]
    states = {
        state["card_id"]: state["state"] for state in updated_item["card_scene"]["card_states"]
    }
    assert states == {"card-01": "rejected", "card-02": "adjusted"}


def test_proposal_scene_can_add_manual_card(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    proposal_revision_id = _proposal_revision(revision_store, source_revision_id)
    seeded = service.create_reference(
        SOURCE.recording_id,
        "visible_cards",
        {"operator_id": "operator-01", "proposal_revision_id": proposal_revision_id},
    )
    item = dict(seeded.draft.items[0].item)
    card_scene = item["card_scene"]
    initial_scene = ReviewedCardScene.from_mapping(card_scene["proposal"]["initialized_scene"])
    manual_poses = (
        CardPose("manual-card-1", (70.0, 70.0), 0.0, None, None),
        CardPose("manual-card-2", (75.0, 75.0), 0.0, None, None),
    )
    corrected_scene = ReviewedCardScene.create(
        source_frame_id=initial_scene.source_frame_id,
        source_frame_width=initial_scene.source_frame_width,
        source_frame_height=initial_scene.source_frame_height,
        calibration_revision_id=initial_scene.calibration_revision_id,
        calibration_digest=initial_scene.calibration_digest,
        poses=(*initial_scene.poses, *manual_poses),
        stacking_order=CardStackingOrder(
            card_ids=(
                *initial_scene.stacking_order.card_ids,
                *(pose.card_id for pose in manual_poses),
            ),
            uncertain_edges=initial_scene.stacking_order.uncertain_edges,
            contradictions=initial_scene.stacking_order.contradictions,
        ),
    )
    projection = card_scene["projection"]
    derivation = derive_pose_scene_visible_regions(corrected_scene, projection)
    item["card_scene"] = {
        "schema_version": "reviewed-card-scene-editor/v1",
        "scene": corrected_scene.to_mapping(),
        "initialized_scene": card_scene["proposal"]["initialized_scene"],
        "projection": projection,
    }
    item["candidates"] = [
        {
            "card_id": region["card_id"],
            "geometry": region["geometry"],
            "normalization": region["normalization"],
            "side": "unknown",
        }
        for region in derivation.regions
    ]

    updated = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": seeded.draft.revision,
            "operations": [{"operation": "set_frame_review", "item_id": "event-01", "item": item}],
        },
    )

    updated_item = updated.draft.items[0].item
    states = {state["card_id"]: state for state in updated_item["card_scene"]["card_states"]}
    for pose in manual_poses:
        assert states[pose.card_id]["source"] == "manual"
        assert states[pose.card_id]["proposal_id"] is None
        assert states[pose.card_id]["state"] == "adjusted"
    assert {candidate["card_id"] for candidate in updated_item["candidates"]} == {
        "card-01",
        "manual-card-1",
        "manual-card-2",
    }

    accepted = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": updated.draft.revision,
            "operations": [
                {"operation": "accept_card", "item_id": "event-01", "card_id": "card-01"}
            ],
        },
    )
    accepted_item = accepted.draft.items[0].item
    assert {
        pose["card_id"] for pose in accepted_item["card_scene"]["reviewed"]["scene"]["poses"]
    } == {"card-01", "manual-card-1", "manual-card-2"}


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


def test_proposal_rebase_preserves_ignore_regions_for_unchanged_frames(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    proposal_revision_id = _proposal_revision(revision_store, source_revision_id)
    existing = service.create_reference(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "source_revision_id": source_revision_id,
        },
    )
    region = {
        "region_id": "ignore-region-01",
        "geometry": {
            "kind": "reviewed-ignore-region/v1",
            "polygons": [
                [
                    {"x": 0, "y": 0},
                    {"x": 1000, "y": 0},
                    {"x": 1000, "y": 1000},
                    {"x": 0, "y": 1000},
                ]
            ],
        },
        "normalization": {
            "width": 100,
            "height": 100,
            "policy_id": "full-frame-0-1000/v1",
        },
        "reason": "untidy_stack",
        "source_candidates": [],
    }
    with_region = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": existing.draft.revision,
            "operations": [
                {
                    "operation": "create_ignore_region",
                    "item_id": "event-01",
                    "region": region,
                }
            ],
        },
    )

    rebased = service.update_draft(
        SOURCE.recording_id,
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": with_region.draft.revision,
            "operations": [
                {
                    "operation": "rebase",
                    "source_revision_id": source_revision_id,
                    "proposal_revision_id": proposal_revision_id,
                }
            ],
        },
    )

    rebased_region = rebased.draft.items[0].item["ignored_regions"][0]
    assert {key: value for key, value in rebased_region.items() if key != "source_candidates"} == {
        key: value for key, value in region.items() if key != "source_candidates"
    }
    assert rebased_region["source_candidates"] == [
        {"revision_id": source_revision_id, "card_id": "card-01"}
    ]


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


def test_pile_grouping_is_reversible_and_pile_only_coverage_completes(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(
        revision_store, "visible_cards", visible_candidate_ids=("card-01", "card-02")
    )
    service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    region = {
        "pile_id": "pile-01",
        "geometry": {
            "kind": "pile-region/v1",
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
        "source_candidates": [],
    }
    grouped = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {
                    "operation": "group_cards_into_pile",
                    "item_id": "event-01",
                    "candidate_ids": ["card-01"],
                    "region": region,
                }
            ],
        },
    )
    grouped_item = grouped.draft.items[0].item
    assert [candidate["card_id"] for candidate in grouped_item["candidates"]] == ["card-02"]
    pile = grouped_item["pile_regions"][0]
    assert pile["source_candidates"] == [{"revision_id": source_revision_id, "card_id": "card-01"}]
    assert [candidate["card_id"] for candidate in pile["grouped_candidates"]] == ["card-01"]

    restored = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": grouped.draft.revision,
            "operations": [
                {
                    "operation": "delete_pile_region",
                    "item_id": "event-01",
                    "pile_id": "pile-01",
                }
            ],
        },
    )
    restored_item = restored.draft.items[0].item
    assert {candidate["card_id"] for candidate in restored_item["candidates"]} == {
        "card-01",
        "card-02",
    }
    assert restored_item["pile_regions"] == []

    second_region = {**region, "pile_id": "pile-02"}
    pile_seeded = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": restored.draft.revision,
            "operations": [
                {
                    "operation": "group_cards_into_pile",
                    "item_id": "event-01",
                    "candidate_ids": ["card-02"],
                    "region": second_region,
                }
            ],
        },
    )
    pile_only = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": pile_seeded.draft.revision,
            "operations": [
                {
                    "operation": "group_cards_into_pile",
                    "item_id": "event-01",
                    "candidate_ids": ["card-01"],
                    "region": {**region, "pile_id": "pile-03"},
                }
            ],
        },
    )
    accepted = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": pile_only.draft.revision,
            "operations": [{"operation": "accept_frame_suggestions", "item_id": "event-01"}],
        },
    )
    completed = service.complete_reference(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": accepted.draft.revision,
            "coverage": {
                "kind": "visible_frames",
                "frames": [
                    {
                        "frame_identity": accepted.draft.items[0].item["frame_identity"],
                        "decision": "piles",
                    }
                ],
            },
        },
    )
    stored = revision_store.require(completed.state.selected_completed_revision_id)
    assert {pile.pile_id for pile in stored.content.outcomes[0].pile_regions} == {
        "pile-02",
        "pile-03",
    }
    assert stored.content.outcomes[0].candidates == ()


def test_pile_grouping_removes_and_restores_proposal_card_review_state(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    proposal_revision_id = _proposal_revision(
        revision_store, source_revision_id, card_ids=("card-01", "card-02")
    )
    seeded = service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "proposal_revision_id": proposal_revision_id},
    )
    accepted = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": seeded.draft.revision,
            "operations": [
                {
                    "operation": "accept_card",
                    "item_id": "event-01",
                    "card_id": "card-01",
                }
            ],
        },
    )
    region = {
        "pile_id": "pile-proposal",
        "geometry": {
            "kind": "pile-region/v1",
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
        "source_candidates": [],
    }
    grouped = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": accepted.draft.revision,
            "operations": [
                {
                    "operation": "group_cards_into_pile",
                    "item_id": "event-01",
                    "candidate_ids": ["card-01"],
                    "region": region,
                }
            ],
        },
    )
    grouped_item = grouped.draft.items[0].item
    states = {item["card_id"]: item["state"] for item in grouped_item["card_scene"]["card_states"]}
    assert states == {"card-01": "rejected", "card-02": "pending"}
    assert grouped_item["pile_regions"][0]["grouped_card_states"][0]["state"] == "accepted"

    restored = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": grouped.draft.revision,
            "operations": [
                {
                    "operation": "delete_pile_region",
                    "item_id": "event-01",
                    "pile_id": "pile-proposal",
                }
            ],
        },
    )
    restored_states = {
        item["card_id"]: item["state"]
        for item in restored.draft.items[0].item["card_scene"]["card_states"]
    }
    assert restored_states == {"card-01": "accepted", "card-02": "pending"}
    assert restored.draft.items[0].item["card_scene"]["reviewed"]["decision"] == "accepted"


def test_pile_create_replace_and_ignore_conversion_commands(tmp_path: Path) -> None:
    service, revision_store = _service(tmp_path)
    source_revision_id = _vision_source_revision(revision_store, "visible_cards")
    service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": source_revision_id},
    )
    ignore = {
        "region_id": "ignore-01",
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
    pile = {
        "pile_id": "pile-converted",
        "geometry": {
            "kind": "pile-region/v1",
            "polygons": [
                [
                    {"x": 120, "y": 120},
                    {"x": 680, "y": 120},
                    {"x": 680, "y": 680},
                    {"x": 120, "y": 680},
                ]
            ],
        },
        "normalization": {"width": 100, "height": 100, "policy_id": "full-frame-0-1000/v1"},
        "source_candidates": [],
    }
    ignored = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {
                    "operation": "create_ignore_region",
                    "item_id": "event-01",
                    "region": ignore,
                }
            ],
        },
    )
    converted = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": ignored.draft.revision,
            "operations": [
                {
                    "operation": "convert_ignore_region_to_pile",
                    "item_id": "event-01",
                    "region_id": "ignore-01",
                    "region": pile,
                }
            ],
        },
    )
    assert converted.draft.items[0].item["ignored_regions"] == []
    assert converted.draft.items[0].item["pile_regions"][0]["pile_id"] == "pile-converted"

    updated_pile = {
        **pile,
        "geometry": {
            **pile["geometry"],
            "polygons": [
                [
                    {"x": 200, "y": 200},
                    {"x": 600, "y": 200},
                    {"x": 600, "y": 600},
                    {"x": 200, "y": 600},
                ]
            ],
        },
    }
    replaced = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": converted.draft.revision,
            "operations": [
                {
                    "operation": "replace_pile_region",
                    "item_id": "event-01",
                    "pile_id": "pile-converted",
                    "region": updated_pile,
                }
            ],
        },
    )
    assert replaced.draft.items[0].item["pile_regions"][0]["geometry"] == updated_pile["geometry"]
    deleted = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": replaced.draft.revision,
            "operations": [
                {
                    "operation": "delete_pile_region",
                    "item_id": "event-01",
                    "pile_id": "pile-converted",
                }
            ],
        },
    )
    assert deleted.draft.items[0].item["pile_regions"] == []


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


def test_identity_annotation_reference_keeps_one_latest_observation_per_card(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    visible_source_id = _vision_source_revision(
        revision_store,
        "visible_cards",
        visible_candidate_ids=("card-01",),
        visible_frame_indexes=(0, 1),
    )
    visible = service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": visible_source_id},
    )
    reviewed_geometry = {
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
    }
    reviewed_items = []
    for item in visible.draft.items:
        value = dict(item.item)
        value["candidates"] = [
            {**candidate, "geometry": reviewed_geometry} for candidate in value["candidates"]
        ]
        reviewed_items.append((item.item_id, value))
    updated = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {"operation": "set_frame_review", "item_id": item_id, "item": value}
                for item_id, value in reviewed_items
            ],
        },
    )
    updated = service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": updated.draft.revision,
            "operations": [
                {"operation": "accept_frame_suggestions", "item_id": item.item_id}
                for item in updated.draft.items
            ],
        },
    )
    completed = service.complete_reference(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": updated.draft.revision,
            "coverage": {
                "kind": "visible_frames",
                "frames": [
                    {
                        "frame_identity": item.item["frame_identity"],
                        "decision": "cards",
                        "item_id": item.item_id,
                    }
                    for item in updated.draft.items
                ],
            },
        },
    )
    visible_revision_id = completed.state.selected_completed_revision_id
    assert visible_revision_id is not None
    visible_revision = revision_store.require(visible_revision_id)
    source = {
        "visible_card_revision_id": visible_revision_id,
        "visible_card_revision_digest": visible_revision.manifest.content_sha256,
    }

    identity_reference = service.create_reference(
        "recording-01",
        "visual_identities",
        {"operator_id": "operator-01", "annotation_source": source},
    )

    assert [item.item_id for item in identity_reference.draft.items] == ["card-01"]
    assert identity_reference.draft.items[0].item["frame_identity"]["frame_index"] == 1
    rebased = service.update_draft(
        "recording-01",
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": identity_reference.draft.revision,
            "operations": [{"operation": "rebase_annotation_source", "annotation_source": source}],
        },
    )
    assert [item.item_id for item in rebased.draft.items] == ["card-01"]


def test_annotation_reference_seeds_exact_reviewed_back_without_classifier(
    tmp_path: Path,
) -> None:
    service, revision_store = _service(tmp_path)
    visible_source_id = _vision_source_revision(
        revision_store,
        "visible_cards",
        visible_candidate_ids=("card-01", "card-02"),
    )
    visible = service.create_reference(
        "recording-01",
        "visible_cards",
        {"operator_id": "operator-01", "source_revision_id": visible_source_id},
    )
    visible_item = dict(visible.draft.items[0].item)
    geometry = {
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
    }
    for candidate in visible_item["candidates"]:
        candidate["geometry"] = geometry
    service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {
                    "operation": "set_frame_review",
                    "item_id": "event-01",
                    "item": visible_item,
                }
            ],
        },
    )
    service.update_draft(
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
                        "frame_identity": visible_item["frame_identity"],
                        "decision": "cards",
                        "item_id": "event-01",
                    }
                ],
            },
        },
    )
    visible_revision_id = completed.state.selected_completed_revision_id
    assert visible_revision_id is not None
    revision = revision_store.require(visible_revision_id)
    assert isinstance(revision.content, VisibleCardData)
    frame = revision.content.outcomes[0].frame_identity
    assert frame is not None
    crop = {
        "schema_version": "visible-region-crop/v1",
        "status": "usable",
        "frame_identity": frame.to_mapping(),
        "geometry": geometry,
        "pixel_bounds": {"x_min": 5, "y_min": 5, "x_max": 60, "y_max": 60},
        "crop_policy": "oracle_visible_region",
        "output_encoding": "ppm",
        "content_type": "image/x-portable-pixmap",
        "decoder_version": "decoder.v1",
        "transform_version": "transform.v1",
        "image_sha256": DIGEST,
        "unusable_reason": None,
    }
    service.annotation_crop_resolver = lambda recording_id, revision_id: {
        "card-01": crop,
        "card-02": "The exact source frame is unavailable.",
    }
    source = {
        "visible_card_revision_id": visible_revision_id,
        "visible_card_revision_digest": revision.manifest.content_sha256,
    }
    with pytest.raises(PipelineReferenceInputError, match="digest does not match"):
        service.create_reference(
            "recording-01",
            "visual_identities",
            {
                "operator_id": "operator-01",
                "annotation_source": {
                    **source,
                    "visible_card_revision_digest": "0" * 64,
                },
            },
        )
    reference = service.create_reference(
        "recording-01",
        "visual_identities",
        {"operator_id": "operator-01", "annotation_source": source},
    )
    assert reference.draft.annotation_source == source
    assert reference.draft.source_revision_id is None
    assert len(reference.draft.items) == 2
    item = reference.draft.items[0]
    assert item.review_state == "pending"
    assert item.item["classifier"] is None
    assert item.item["status"] == "face_down"
    assert item.item["crop_identity"] == crop
    assert item.item["annotation_provenance"]["visible_card_revision_id"] == visible_revision_id
    missing_crop = reference.draft.items[1]
    assert missing_crop.item_id == "card-02"
    assert missing_crop.review_state == "pending"
    assert missing_crop.item["status"] == "failed"
    assert missing_crop.item["crop_identity"] is None
    assert missing_crop.item["annotation_provenance"]["visible_card_revision_id"] == (
        visible_revision_id
    )
    repeated = service.create_reference(
        "recording-01",
        "visual_identities",
        {"operator_id": "operator-01", "annotation_source": source},
    )
    assert [draft_item.item_id for draft_item in repeated.draft.items] == ["card-01", "card-02"]

    corrected = service.update_draft(
        "recording-01",
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 0,
            "operations": [
                {
                    "operation": "select_identity",
                    "item_id": "card-01",
                    "identity": "CLUBS_NINE",
                }
            ],
        },
    )
    corrected_item = corrected.draft.items[0].item
    assert corrected_item["status"] == "classified"
    assert corrected_item["classifier"] is None
    assert corrected_item["annotation_provenance"] == item.item["annotation_provenance"]
    source_problem = service.update_draft(
        "recording-01",
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": 1,
            "operations": [{"operation": "report_identity_source_problem", "item_id": "card-02"}],
        },
    )
    assert source_problem.draft.items[1].review_state == "source_problem"
    assert (
        source_problem.draft.items[1].item["annotation_provenance"]
        == (missing_crop.item["annotation_provenance"])
    )

    visible_current = service.reference_store.get("recording-01", "visible_cards")
    assert visible_current is not None
    changed_visible_item = dict(visible_current.draft.items[0].item)
    changed_geometry = {
        "kind": "reviewed-visible-region/v1",
        "visible_region": {
            "polygons": [
                [
                    {"x": 6, "y": 5},
                    {"x": 60, "y": 5},
                    {"x": 60, "y": 60},
                    {"x": 6, "y": 60},
                ]
            ]
        },
    }
    changed_visible_item["candidates"][1]["geometry"] = changed_geometry
    service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": visible_current.draft.revision,
            "operations": [
                {
                    "operation": "set_frame_review",
                    "item_id": "event-01",
                    "item": changed_visible_item,
                }
            ],
        },
    )
    service.update_draft(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": visible_current.draft.revision + 1,
            "operations": [{"operation": "accept_frame_suggestions", "item_id": "event-01"}],
        },
    )
    changed_visible = service.complete_reference(
        "recording-01",
        "visible_cards",
        {
            "operator_id": "operator-01",
            "expected_revision": visible_current.draft.revision + 2,
            "coverage": {
                "kind": "visible_frames",
                "frames": [
                    {
                        "frame_identity": visible_item["frame_identity"],
                        "decision": "cards",
                        "item_id": "event-01",
                    }
                ],
            },
        },
    )
    changed_visible_revision_id = changed_visible.state.selected_completed_revision_id
    assert changed_visible_revision_id is not None
    changed_revision = revision_store.require(changed_visible_revision_id)
    changed_crop = dict(crop, geometry=changed_geometry, image_sha256="1" * 64)
    service.annotation_crop_resolver = lambda recording_id, revision_id: {
        "card-01": crop,
        "card-02": changed_crop,
    }
    with pytest.raises(PipelineReferenceInputError, match="digest does not match"):
        service.update_draft(
            "recording-01",
            "visual_identities",
            {
                "operator_id": "operator-01",
                "expected_revision": source_problem.draft.revision,
                "operations": [
                    {
                        "operation": "rebase_annotation_source",
                        "annotation_source": {
                            "visible_card_revision_id": changed_visible_revision_id,
                            "visible_card_revision_digest": "0" * 64,
                        },
                    }
                ],
            },
        )
    rebased = service.update_draft(
        "recording-01",
        "visual_identities",
        {
            "operator_id": "operator-01",
            "expected_revision": source_problem.draft.revision,
            "operations": [
                {
                    "operation": "rebase_annotation_source",
                    "annotation_source": {
                        "visible_card_revision_id": changed_visible_revision_id,
                        "visible_card_revision_digest": changed_revision.manifest.content_sha256,
                    },
                }
            ],
        },
    )
    assert rebased.draft.items[0].review_state == "accepted"
    assert rebased.draft.items[0].item["status"] == "classified"
    assert (
        rebased.draft.items[0].item["annotation_provenance"]["visible_card_revision_id"]
        == changed_visible_revision_id
    )
    assert rebased.draft.items[1].review_state == "affected"
    assert rebased.draft.items[1].item["crop_identity"] == changed_crop


def test_annotation_reference_http_api_creates_and_corrects_back_without_classifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_test_app(_settings(tmp_path))
    service = app.state.pipeline_reference_service
    revision_store = app.state.pipeline_revision_store
    visible_source_id = _vision_source_revision(revision_store, "visible_cards")
    with TestClient(app) as client:
        visible_path = "/api/recordings/recording-01/pipeline/references/visible_cards"
        created = client.post(
            visible_path,
            json={"operator_id": "operator-01", "source_revision_id": visible_source_id},
        )
        assert created.status_code == 201
        visible_item = created.json()["draft"]["items"][0]["item"]
        geometry = {
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
        }
        visible_item["candidates"][0]["geometry"] = geometry
        reviewed = client.put(
            visible_path + "/draft",
            json={
                "operator_id": "operator-01",
                "expected_revision": 0,
                "operations": [
                    {
                        "operation": "set_frame_review",
                        "item_id": "event-01",
                        "item": visible_item,
                    }
                ],
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        accepted = client.put(
            visible_path + "/draft",
            json={
                "operator_id": "operator-01",
                "expected_revision": 1,
                "operations": [
                    {
                        "operation": "accept_frame_suggestions",
                        "item_id": "event-01",
                    }
                ],
            },
        )
        assert accepted.status_code == 200, accepted.text
        completed = client.post(
            visible_path + "/complete",
            json={
                "operator_id": "operator-01",
                "expected_revision": 2,
                "coverage": {
                    "kind": "visible_frames",
                    "frames": [
                        {
                            "frame_identity": visible_item["frame_identity"],
                            "decision": "cards",
                            "item_id": "event-01",
                        }
                    ],
                },
            },
        )
        assert completed.status_code == 201, completed.text
        visible_revision_id = completed.json()["state"]["selected_completed_revision_id"]
        revision = revision_store.require(visible_revision_id)
        frame = revision.content.outcomes[0].frame_identity
        assert frame is not None
        crop = {
            "schema_version": "visible-region-crop/v1",
            "status": "usable",
            "frame_identity": frame.to_mapping(),
            "geometry": geometry,
            "pixel_bounds": {"x_min": 5, "y_min": 5, "x_max": 60, "y_max": 60},
            "crop_policy": "oracle_visible_region",
            "output_encoding": "ppm",
            "content_type": "image/x-portable-pixmap",
            "decoder_version": "decoder.v1",
            "transform_version": "transform.v1",
            "image_sha256": DIGEST,
            "unusable_reason": None,
        }
        service.annotation_crop_resolver = lambda recording_id, revision_id: {"card-01": crop}
        identity_path = "/api/recordings/recording-01/pipeline/references/visual_identities"
        seeded = client.post(
            identity_path,
            json={
                "operator_id": "operator-01",
                "annotation_source": {
                    "visible_card_revision_id": visible_revision_id,
                    "visible_card_revision_digest": revision.manifest.content_sha256,
                },
            },
        )
        assert seeded.status_code == 201, seeded.text
        item = seeded.json()["draft"]["items"][0]
        assert item["review_state"] == "pending"
        assert item["item"]["status"] == "face_down"
        assert item["item"]["classifier"] is None
        crop_path = (
            "/api/recordings/recording-01/pipeline/derived-views/reviewed-identity-crops/card-01"
        )
        stale_crop = client.get(crop_path, params={"crop_sha256": "0" * 64})
        assert stale_crop.status_code == 404
        resolved: list[tuple[str, str, str]] = []

        def resolve_crop(
            recording_id: str, revision_id: str, item_id: str, _outcome: object
        ) -> SimpleNamespace:
            resolved.append((recording_id, revision_id, item_id))
            return SimpleNamespace(content_type="image/jpeg", image_bytes=b"reviewed-crop")

        monkeypatch.setattr(
            app.state.visual_identity_pipeline_service,
            "resolve_reviewed_annotation_crop",
            resolve_crop,
        )
        crop_response = client.get(crop_path, params={"crop_sha256": DIGEST, "preview": "browser"})
        assert crop_response.status_code == 200, crop_response.text
        assert crop_response.content == b"reviewed-crop"
        assert resolved == [("recording-01", visible_revision_id, "card-01")]
        untouched = service.get_reference("recording-01", "visual_identities")
        generated_revision_id = _vision_source_revision(revision_store, "visual_identities")
        switched = client.put(
            identity_path + "/draft",
            json={
                "operator_id": "operator-01",
                "expected_revision": 0,
                "operations": [
                    {"operation": "rebase", "source_revision_id": generated_revision_id}
                ],
            },
        )
        assert switched.status_code == 200, switched.text
        switched_draft = switched.json()["draft"]
        assert switched_draft.get("annotation_source") is None
        assert switched_draft["source_revision_id"] == generated_revision_id
        assert switched_draft["items"][0]["review_state"] == "pending"
        assert switched_draft["items"][0]["item"]["status"] == "classified"
        # Restore the untouched fixture to test the separate manual correction path.
        with service.reference_store.locked("recording-01", "visual_identities"):
            service.reference_store.write_locked(untouched)
        corrected = client.put(
            identity_path + "/draft",
            json={
                "operator_id": "operator-01",
                "expected_revision": 0,
                "operations": [
                    {
                        "operation": "select_identity",
                        "item_id": "card-01",
                        "identity": "CLUBS_NINE",
                    }
                ],
            },
        )
        assert corrected.status_code == 200, corrected.text
        outcome = corrected.json()["draft"]["items"][0]["item"]
        assert outcome["status"] == "classified"
        assert outcome["classifier"] is None
        assert outcome["annotation_provenance"]["visible_card_revision_id"] == (visible_revision_id)
        rejected_switch = client.put(
            identity_path + "/draft",
            json={
                "operator_id": "operator-01",
                "expected_revision": 1,
                "operations": [
                    {"operation": "rebase", "source_revision_id": generated_revision_id}
                ],
            },
        )
        assert rejected_switch.status_code == 422
