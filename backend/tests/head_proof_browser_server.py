"""Disposable real backend for the recording HEAD browser proof."""

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi.testclient import TestClient
from test_recording_state_workflow import (
    ACTOR,
    RECORDING,
    SOURCE,
    _import_fixture_recording,
    _reference,
    _settings,
    _snapshot_payload,
)

from dokodetector_backend.app import create_app
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer


def settings_for(directory: str):
    return _settings(Path(directory)).model_copy(
        update={"recording_list_head_proof": True, "repository_root": Path(directory).resolve()}
    )


def seed(directory: str):
    settings = settings_for(directory)
    app = create_app(settings, analyzer=create_local_poc_analyzer())
    store = app.state.pipeline_node_edits.store
    content = {
        "schema_version": "event-data/v1",
        "events": [
            {
                "event_id": "event-1",
                "event_type": "card_state_changed",
                "start_us": 100,
                "end_us": 200,
            }
        ],
    }
    with TestClient(app) as client:
        _import_fixture_recording(app, client, RECORDING, Path(directory))
        _import_fixture_recording(app, client, "missing-head", Path(directory))
        stored = app.state.recording_bundle_store.get_metadata(RECORDING)
        source = dict(
            SOURCE,
            video_sha256=stored.source_sha256,
            byte_length=stored.video_byte_length,
            duration_us=1_000_000,
        )
        revision = store.create("events-proof", "Events", "events", source, content, {})
        response = client.post(
            f"/api/recordings/{RECORDING}/state",
            json=_snapshot_payload(generated=_reference(revision, "events-proof")),
        )
        assert response.status_code == 200, response.text
        edited = dict(content, events=[dict(content["events"][0], end_us=250)])
        response = client.put(
            f"/api/recordings/{RECORDING}/state/events/working-content",
            json={
                "expected_head_version": 1,
                "idempotency_key": "browser-edit",
                "actor": ACTOR,
                "content": edited,
            },
        )
        assert response.status_code == 200, response.text


def main():
    with TemporaryDirectory(prefix="recording-head-browser-") as directory:
        subprocess.run([sys.executable, __file__, "--seed", directory], check=True)
        app = create_app(settings_for(directory), analyzer=create_local_poc_analyzer())

        def forbidden(*_args, **_kwargs):
            raise AssertionError("legacy list discovery called")

        app.state.pipeline_workspace_service.get_statuses = forbidden
        uvicorn.run(app, host="127.0.0.1", port=8766, log_level="warning")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--seed":
        seed(sys.argv[2])
    else:
        main()
