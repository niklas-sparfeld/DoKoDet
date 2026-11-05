from fastapi import FastAPI
from fastapi.testclient import TestClient

from dokodetector_backend.errors import register_error_handlers
from dokodetector_backend.pipeline_node_edit_api import router
from dokodetector_backend.pipeline_node_edits import PipelineNodeEdits
from dokodetector_backend.pipeline_node_store import PipelineNodeStore
from dokodetector_backend.pipeline_node_uses import PipelineNodeUses

SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": "a" * 64,
    "byte_length": 100,
    "duration_us": 10_000_000,
}
CONTENT = {
    "schema_version": "event-data/v1",
    "events": [
        {"event_id": "e", "event_type": "card_state_changed", "start_us": 100, "end_us": 200}
    ],
}
ACTOR = {"kind": "human", "id": "workspace-operator"}


def test_edit_api_copies_first_changed_edit_after_downstream_use(tmp_path):
    store = PipelineNodeStore(tmp_path)
    revision = store.create("events", "Event timing", "events", SOURCE, CONTENT, {})
    PipelineNodeUses(store).accept("run-1", [("events", revision.revision_id)])
    app = FastAPI()
    app.state.pipeline_node_edits = PipelineNodeEdits(store)
    app.include_router(router)
    register_error_handlers(app)
    client = TestClient(app)

    response = client.post(
        "/api/pipeline/nodes/events/edit",
        json={
            "expected_revision_id": revision.revision_id,
            "idempotency_key": "edit-1",
            "actor": ACTOR,
            "content": {
                "schema_version": "event-data/v1",
                "events": [
                    {
                        "event_id": "e",
                        "event_type": "card_state_changed",
                        "start_us": 100,
                        "end_us": 300,
                    }
                ],
            },
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["copied"] is True
    assert result["reason"] == "downstream_use"
    assert result["node_id"] != "events"
    assert store.get("events").head_revision_id == revision.revision_id
    retry = client.post(
        "/api/pipeline/nodes/events/edit",
        json={
            "expected_revision_id": revision.revision_id,
            "idempotency_key": "edit-1",
            "actor": ACTOR,
            "content": {
                "schema_version": "event-data/v1",
                "events": [
                    {
                        "event_id": "e",
                        "event_type": "card_state_changed",
                        "start_us": 100,
                        "end_us": 300,
                    }
                ],
            },
        },
    )
    assert retry.json() == result
    assert len(store.list_nodes()) == 2


def test_copy_api_uses_automatic_name_and_returns_revision(tmp_path):
    store = PipelineNodeStore(tmp_path)
    revision = store.create("events", "Event timing", "events", SOURCE, CONTENT, {})
    app = FastAPI()
    app.state.pipeline_node_edits = PipelineNodeEdits(store)
    app.include_router(router)
    register_error_handlers(app)
    client = TestClient(app)

    response = client.post(
        "/api/pipeline/nodes/events/copy",
        json={
            "revision_id": revision.revision_id,
            "idempotency_key": "copy-1",
            "actor": ACTOR,
            "reason": "user_requested_copy",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["name"] == "Event timing copy"
    assert result["node_id"] != "events"
    assert result["revision_id"]
