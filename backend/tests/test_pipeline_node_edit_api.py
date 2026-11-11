from fastapi import FastAPI
from fastapi.testclient import TestClient

from dokodetector_backend.errors import register_error_handlers
from dokodetector_backend.pipeline_item_provenance import ItemProvenanceService
from dokodetector_backend.pipeline_node_edit_api import router
from dokodetector_backend.pipeline_node_edits import PipelineNodeEdits
from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
from dokodetector_backend.pipeline_node_store import PipelineNodeStore

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}
EVENTS = {
    "schema_version": "event-data/v1",
    "events": [
        {"event_id": "e", "event_type": "card_state_changed", "start_us": 100, "end_us": 200}
    ],
}
VISIBLE = {"schema_version": "visible-card-data/v1", "outcomes": []}
ACTOR = {"kind": "human", "id": "workspace-operator"}


def _client(tmp_path):
    store = PipelineNodeStore(tmp_path)
    event = store.create("events", "Events", "events", SOURCE, EVENTS, {})
    ItemProvenanceService(store).create(
        "visible", "Visible cards", "visible_cards", SOURCE, VISIBLE, {}, ACTOR
    )
    app = FastAPI()
    app.state.pipeline_node_edits = PipelineNodeEdits(store)
    app.state.pipeline_node_reviews = PipelineNodeReviews(store)
    app.include_router(router)
    register_error_handlers(app)
    return TestClient(app), store, event


def test_event_node_editor_and_review_routes_are_removed(tmp_path):
    client, _, event = _client(tmp_path)
    assert (
        client.get(f"/api/pipeline/nodes/events/revisions/{event.revision_id}").status_code == 404
    )
    assert (
        client.post(
            "/api/pipeline/nodes/events/edit",
            json={
                "expected_revision_id": event.revision_id,
                "idempotency_key": "edit-event",
                "actor": ACTOR,
                "content": EVENTS,
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/pipeline/nodes/events/reviews/overall",
            json={
                "review_id": "review-event",
                "revision_id": event.revision_id,
                "question": "Is this event set correct?",
                "decision": "accepted",
                "reviewer": ACTOR,
                "evidence": {},
            },
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/pipeline/nodes/events/revisions/{event.revision_id}/reviews").status_code
        == 404
    )


def test_generic_non_event_revision_route_remains_available(tmp_path):
    client, store, _ = _client(tmp_path)
    node = store.get("visible")
    response = client.get(f"/api/pipeline/nodes/visible/revisions/{node.head_revision_id}")
    assert response.status_code == 200
    assert response.json()["content_type"] == "visible_cards"
