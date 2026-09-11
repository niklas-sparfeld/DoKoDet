from __future__ import annotations

import json
from pathlib import Path

from doko_operations.pipeline_data import (
    CARD_STATE_CHANGED_EVENT_TYPE,
    DataRevision,
    EventData,
    EventRecord,
    HumanProducer,
    RecordingVideoSource,
    canonical_data_revision_bytes,
    canonical_event_data_bytes,
    canonical_json_bytes,
    sha256_bytes,
)
from doko_operations.pipeline_reference import (
    PipelineReferenceDraft,
    PipelineReferenceState,
    ReferenceDraftItem,
)

from dokodetector_backend.cardeventnet_canonicalization import (
    canonicalize,
)
from dokodetector_backend.pipeline_reference_store import (
    PipelineReferenceStore,
    StoredPipelineReference,
)
from dokodetector_backend.pipeline_store import (
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    PipelineSelectionStore,
)

DIGEST = "a" * 64
SOURCE = RecordingVideoSource(
    recording_id="recording-01",
    relative_path="data/intake/recordings/recording-01/video.mov",
    video_sha256=DIGEST,
    byte_length=100,
    duration_us=10_000_000,
)


def _publish_event_revision(
    store: PipelineRevisionStore,
    revision_id: str,
    *,
    origin: str,
    input_revision_ids: tuple[str, ...] = (),
    base_revision_id: str | None = None,
) -> None:
    content = EventData(
        events=(
            EventRecord(
                event_id="event-01",
                event_type="card_played",
                start_us=1_000_000,
                end_us=1_250_000,
            ),
        )
    )
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="events",
        content_schema="event-data/v1",
        recording_id=SOURCE.recording_id,
        source=SOURCE,
        content_sha256=sha256_bytes(canonical_event_data_bytes(content, allow_legacy=True)),
        input_revision_ids=input_revision_ids,
        origin=origin,
        producer=HumanProducer(
            review_id=f"review-{revision_id}",
            operator_id="operator-01",
            base_revision_id=base_revision_id,
        ),
        coverage={"kind": "event_intervals", "intervals": [{"start_us": 0, "end_us": 10_000_000}]},
        created_at="2026-09-05T10:00:00Z",
    )
    revision_path = store.revision_path(revision_id)
    revision_path.mkdir(parents=True)
    (revision_path / "manifest.json").write_bytes(canonical_data_revision_bytes(manifest))
    (revision_path / "content.json").write_bytes(canonical_json_bytes(content.to_mapping()))


def _write_active_reference(backend_root: Path, source_revision_id: str) -> None:
    store = PipelineReferenceStore(backend_root / "data" / "operations" / "pipeline-references")
    timestamp = "2026-09-05T10:00:00Z"
    draft = PipelineReferenceDraft(
        recording_id=SOURCE.recording_id,
        content_type="events",
        revision=1,
        source_revision_id=source_revision_id,
        items=(
            ReferenceDraftItem(
                item_id="event-01",
                base_item_id=None,
                review_state="accepted",
                item={
                    "event_id": "event-01",
                    "event_type": "card_played",
                    "start_us": 1_000_000,
                    "end_us": 1_250_000,
                },
            ),
        ),
        coverage={"kind": "event_intervals"},
        impact=(),
        updated_at=timestamp,
    )
    state = PipelineReferenceState(
        recording_id=SOURCE.recording_id,
        content_type="events",
        draft_revision=1,
        draft_state="completed",
        source_revision_id=source_revision_id,
        selected_completed_revision_id=source_revision_id,
        updated_at=timestamp,
    )
    with store.locked(SOURCE.recording_id, "events"):
        store.write_locked(StoredPipelineReference(state=state, draft=draft))


def _write_source_files(source_root: Path) -> None:
    annotations = source_root / "annotations"
    reviews = source_root / "reviews"
    annotations.mkdir(parents=True)
    reviews.mkdir(parents=True)
    (annotations / "recording-01.json").write_text(
        json.dumps(
            {
                "schema_version": "cardevent-annotation/v2",
                "video": "recording-01.mov",
                "events": [
                    {
                        "time_s": 1.25,
                        "type": "card_played",
                        "confidence": "confirmed",
                        "notes": "retain this note",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (reviews / "review.json").write_text(
        json.dumps(
            {
                "ground_truth_events": [{"time_s": 1.25, "type": "card_played"}],
                "items": [{"event_type": "card_played", "score": 0.9}],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_canonicalize_replaces_current_reference_and_selection_but_keeps_history(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "card-event-data"
    backend_root = tmp_path / "backend"
    backend_root.mkdir()
    _write_source_files(source_root)

    revision_store = PipelineRevisionStore(
        PipelineRuntimeStorage(backend_root / ".runtime", backend_root / "data" / "operations")
    )
    _publish_event_revision(revision_store, "base-events", origin="manual")
    _publish_event_revision(
        revision_store,
        "reference-events",
        origin="corrected",
        input_revision_ids=("base-events",),
        base_revision_id="base-events",
    )
    _write_active_reference(backend_root, "reference-events")
    selection_store = PipelineSelectionStore(
        PipelineRuntimeStorage(backend_root / ".runtime", backend_root / "data" / "operations"),
        revision_store=revision_store,
    )
    selection_store.update_pointers(
        SOURCE.recording_id,
        "events",
        expected_revision=0,
        selected_generated_revision_id=None,
        selected_completed_reference_revision_id="reference-events",
        updated_at="2026-09-05T10:00:00Z",
    )

    receipt = canonicalize(source_root=source_root, backend_root=backend_root)

    assert receipt["totals"] == {
        "tracked_annotation_files": 1,
        "tracked_annotation_events": 1,
        "tracked_legacy_events": 1,
        "active_fixture_files": 1,
        "active_fixture_legacy_events": 2,
        "durable_event_revisions": 2,
        "durable_legacy_events": 2,
        "source_values_changed": 3,
        "replacement_revisions": 1,
        "changed_references": 1,
        "changed_selections": 1,
    }
    replacement_id = "canonical-card-state-reference-events"
    assert receipt["revision_replacements"][0]["replacement_revision_id"] == replacement_id
    assert revision_store.require("base-events").content.events[0].event_type == "card_played"
    assert (
        revision_store.require(replacement_id).content.events[0].event_type
        == CARD_STATE_CHANGED_EVENT_TYPE
    )
    assert revision_store.require(replacement_id).manifest.input_revision_ids == ("base-events",)

    references = PipelineReferenceStore(
        backend_root / "data" / "operations" / "pipeline-references"
    )
    current = references.require(SOURCE.recording_id, "events")
    assert current.state.selected_completed_revision_id == replacement_id
    assert current.draft.source_revision_id == replacement_id
    assert current.draft.items[0].item["event_type"] == CARD_STATE_CHANGED_EVENT_TYPE

    current_selection = PipelineSelectionStore(
        PipelineRuntimeStorage(backend_root / ".runtime", backend_root / "data" / "operations"),
        revision_store=revision_store,
    ).get(SOURCE.recording_id, "events")
    assert current_selection is not None
    assert current_selection.selected_completed_reference_revision_id == replacement_id
    assert current_selection.revision == 2

    annotation = json.loads((source_root / "annotations" / "recording-01.json").read_text())
    assert annotation["events"] == [
        {
            "time_s": 1.25,
            "type": CARD_STATE_CHANGED_EVENT_TYPE,
            "confidence": "confirmed",
            "notes": "retain this note",
        }
    ]
    review = json.loads((source_root / "reviews" / "review.json").read_text())
    assert review["ground_truth_events"][0]["type"] == CARD_STATE_CHANGED_EVENT_TYPE
    assert review["items"][0]["event_type"] == CARD_STATE_CHANGED_EVENT_TYPE

    assert canonicalize(source_root=source_root, backend_root=backend_root) == receipt
    assert (
        json.loads(
            (
                backend_root / "data" / "operations" / "cardeventnet-canonicalization-m0.json"
            ).read_text()
        )["receipt_digest"]
        == receipt["receipt_digest"]
    )


def test_canonicalize_records_frozen_dataset_without_rewriting_it(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    backend_root = tmp_path / "backend"
    backend_root.mkdir()
    _write_source_files(source_root)
    dataset = backend_root / "data" / "operations" / "pipeline-datasets" / "frozen.json"
    dataset.parent.mkdir(parents=True)
    dataset.write_text(
        json.dumps({"event_type": "card_played", "frozen": True}) + "\n",
        encoding="utf-8",
    )
    before = dataset.read_bytes()

    receipt = canonicalize(source_root=source_root, backend_root=backend_root)

    assert dataset.read_bytes() == before
    assert receipt["frozen_datasets"][0]["path"] == "pipeline-datasets/frozen.json"
    assert receipt["event_revisions"]["frozen_datasets_unchanged"] == receipt["frozen_datasets"]
