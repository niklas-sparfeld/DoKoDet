import hashlib
import json
from pathlib import Path

from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_node_store import PipelineNodeStore

FIXTURE = Path(__file__).parents[2] / "fixtures/pipeline-data/v1/event-data-interval.json"
ACTOR = {"kind": "human", "id": "storage-contract-test"}


def test_worktree_root_pipeline_edit_survives_restart_and_keeps_fixture_identity(
    tmp_path: Path, monkeypatch
) -> None:
    storage_root = tmp_path / "worktree-state"
    monkeypatch.setenv("DOKO_STORAGE_ROOT", str(storage_root))
    settings = Settings(_env_file=None)
    fixture_bytes = FIXTURE.read_bytes()
    fixture_digest = hashlib.sha256(fixture_bytes).hexdigest()
    content = json.loads(fixture_bytes)
    source = {
        "schema_version": "recording-video/v1",
        "recording_id": "storage-contract-recording",
        "relative_path": "fixtures/pipeline-data/v1/event-data-interval.json",
        "video_sha256": fixture_digest,
        "byte_length": len(fixture_bytes),
        "duration_us": 10_000_000,
    }
    node_store = PipelineNodeStore(settings.operations_root / "pipeline-nodes")
    revision = node_store.create(
        "fixture-events",
        "Fixture events",
        "events",
        source,
        content,
        {"event-interval-01": "/events/0"},
    )
    edited = json.loads(fixture_bytes)
    edited["events"][0]["end_us"] += 1

    with TestClient(create_test_app(settings)) as client:
        response = client.post(
            "/api/pipeline/nodes/fixture-events/edit",
            json={
                "expected_revision_id": revision.revision_id,
                "idempotency_key": "storage-contract-edit-1",
                "actor": ACTOR,
                "pointers": {"event-interval-01": "/events/0"},
                "base_pointers": {"event-interval-01": "/events/0"},
                "operations": [
                    {
                        "kind": "replace",
                        "before": ["event-interval-01"],
                        "after": ["event-interval-01"],
                    }
                ],
                "content": edited,
            },
        )
        assert response.status_code == 200, response.text
        saved_revision = response.json()["revision_id"]
        readback = client.get(f"/api/pipeline/nodes/fixture-events/revisions/{saved_revision}")
        assert readback.status_code == 200
        assert readback.json()["content"] == edited
        assert readback.json()["source"]["video_sha256"] == fixture_digest

    restarted = create_test_app(settings)
    with TestClient(restarted) as client:
        readback = client.get(f"/api/pipeline/nodes/fixture-events/revisions/{saved_revision}")
        assert readback.status_code == 200
        assert readback.json()["content"] == edited
        assert readback.json()["source"]["video_sha256"] == fixture_digest

    assert settings.evidence_root == storage_root / "runtime"
    assert settings.operations_root == storage_root / "data/operations"
    assert not (settings.repository_root / "data/operations/pipeline-nodes").exists()
