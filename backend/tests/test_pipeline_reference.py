from __future__ import annotations

from pathlib import Path

import pytest
from app_factory import create_test_app
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
    canonical_visible_card_data_bytes,
    canonical_visual_identity_data_bytes,
)

from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_reference_service import (
    PipelineReferenceConflict,
    PipelineReferenceService,
)
from dokodetector_backend.pipeline_reference_store import PipelineReferenceStore
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
                event_type="card_played",
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


def _vision_source_revision(
    revision_store: PipelineRevisionStore, content_type: str
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
        content = {
            "schema_version": "visible-card-data/v1",
            "outcomes": [
                {
                    "event_id": "event-01",
                    "frame_identity": frame,
                    "status": "detected",
                    "candidates": [
                        {
                            "card_id": "card-01",
                            "geometry": geometry,
                            "normalization": {
                                "width": 64,
                                "height": 64,
                                "policy_id": "fixture.v1",
                            },
                            "model_scores": [{"producer_id": "detector.v1", "score": 0.8}],
                        }
                    ],
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
                    "status": "classified",
                    "candidates": [
                        {
                            "identity": "CLUBS_NINE",
                            "score": 0.8,
                            "score_meaning": "probability",
                            "producer_id": "identity.v1",
                        }
                    ],
                    "unusable_reason": None,
                    "error": None,
                }
            ],
        }
        content_sha256 = sha256_bytes(canonical_visual_identity_data_bytes(content))
        content_bytes = canonical_visual_identity_data_bytes(content)
        schema = "visual-identity-data/v1"
    manifest = DataRevision(
        revision_id=f"generated-{content_type}-01",
        content_type=content_type,
        content_schema=schema,
        recording_id=SOURCE.recording_id,
        source=SOURCE,
        content_sha256=content_sha256,
        input_revision_ids=(),
        origin="processor",
        producer=ProcessorProducer(
            run_id=f"run-{content_type}-01",
            processor_type=content_type,
            implementation_id="fixture.v1",
            model_id="fixture-model.v1",
        ),
        coverage={"kind": "processed"},
        created_at="2026-09-05T10:00:00Z",
    )
    revision_store.publish(manifest, content_bytes)
    return manifest.revision_id


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

    completed = service.complete_reference(
        "recording-01",
        "events",
        {"operator_id": "operator-01", "expected_revision": 1},
    )
    revision_id = completed.state.selected_completed_revision_id
    assert revision_id is not None
    stored_revision = revision_store.require(revision_id)
    assert stored_revision.manifest.origin == "corrected"
    assert stored_revision.manifest.producer.base_revision_id == source_revision_id
    assert stored_revision.content.events[0].model_scores is None

    restarted = PipelineReferenceStore(tmp_path / "operations" / "pipeline-references")
    restored = restarted.require("recording-01", "events")
    assert restored.state.draft_state == "completed"
    assert restored.state.selected_completed_revision_id == revision_id
    assert restored.draft.items[0].item_id == "event-01"


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
                        "event_type": "card_played",
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
                        "event_type": "card_played",
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
        {"operator_id": "operator-01", "expected_revision": 1},
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
                "operations": [{"operation": "accept", "item_id": "event-01"}],
            },
        )
        assert updated.status_code == 200
        stale = client.put(
            base + "/draft",
            json={
                "operator_id": "operator-02",
                "expected_revision": 0,
                "operations": [{"operation": "reject", "item_id": "event-01"}],
            },
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["details"] == [
            {"field": "current_revision", "message": "1"}
        ]
        completed = client.post(
            base + "/complete",
            json={"operator_id": "operator-01", "expected_revision": 1},
        )
        assert completed.status_code == 201
        revision_id = completed.json()["state"]["selected_completed_revision_id"]
        selection = client.get(
            "/api/recordings/recording-01/pipeline/events/selection"
        )
        assert selection.status_code == 200
        assert (
            selection.json()["selection"]["selected_completed_reference_revision_id"]
            == revision_id
        )

    restarted = create_test_app(settings)
    with TestClient(restarted) as client:
        response = client.get(
            "/api/recordings/recording-01/pipeline/references/events"
        )
        assert response.status_code == 200
        assert response.json()["state"]["selected_completed_revision_id"] == revision_id
