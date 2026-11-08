import hashlib
import json
import os
import shutil
from pathlib import Path

from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.operator_corpus_import import import_recordings
from dokodetector_backend.pipeline_node_store import PipelineNodeStore

FIXTURE = Path(__file__).parents[2] / "fixtures/pipeline-data/v1/event-data-interval.json"
OPERATOR_BUNDLE_FIXTURE = Path(__file__).parents[2] / "fixtures/repository-bundle/v1/both"
ACTOR = {"kind": "human", "id": "storage-contract-test"}


def test_worktree_root_pipeline_edit_survives_restart_and_keeps_fixture_identity(
    tmp_path: Path, monkeypatch
) -> None:
    storage_root = Path(os.environ.get("DOKO_STORAGE_ROOT", tmp_path / "worktree-state")).resolve()
    monkeypatch.setenv("DOKO_STORAGE_ROOT", str(storage_root))
    settings = Settings(_env_file=None)
    corpus_root = tmp_path / "operator-corpus"
    source_bundle = corpus_root / "recording-both"
    source_bundle.parent.mkdir(parents=True)
    shutil.copytree(OPERATOR_BUNDLE_FIXTURE, source_bundle)
    source_manifest = {
        path.relative_to(source_bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(source_bundle.rglob("*"))
        if path.is_file()
    }
    import_recordings(corpus_root, settings.repository_intake_root, ("recording-both",))
    imported_video = settings.repository_intake_root / "recording-both/videos/video-both.mov"
    video_bytes = imported_video.read_bytes()
    video_digest = hashlib.sha256(video_bytes).hexdigest()
    fixture_bytes = FIXTURE.read_bytes()
    content = json.loads(fixture_bytes)
    source = {
        "schema_version": "recording-video/v1",
        "recording_id": "recording-both",
        "relative_path": "fixtures/pipeline-data/v1/event-data-interval.json",
        "video_sha256": video_digest,
        "byte_length": len(video_bytes),
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
        upload_files = [
            (
                "manifest",
                (
                    "manifest.json",
                    (source_bundle / "manifest.json").read_bytes(),
                    "application/json",
                ),
            ),
            (
                "source_record",
                (
                    "source-record.json",
                    (source_bundle / "source-record.json").read_bytes(),
                    "application/json",
                ),
            ),
            (
                "task_enrollment",
                (
                    "initial-task-enrollment.json",
                    (source_bundle / "initial-task-enrollment.json").read_bytes(),
                    "application/json",
                ),
            ),
            (
                "video",
                (
                    "video-both.mov",
                    (source_bundle / "videos/video-both.mov").read_bytes(),
                    "video/quicktime",
                ),
            ),
            (
                "proposal",
                (
                    "proposal-both.json",
                    (source_bundle / "predictions/proposal-both.json").read_bytes(),
                    "application/json",
                ),
            ),
        ]
        upload = client.put("/v1/repository-bundles/recording-both", files=upload_files)
        assert upload.status_code == 200
        assert upload.json()["created"] is False
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
        assert readback.json()["source"]["video_sha256"] == video_digest
        recording = client.get("/v1/repository-bundles/recording-both")
        assert recording.status_code == 200
        assert recording.json()["source_sha256"] == video_digest

    restarted = create_test_app(settings)
    with TestClient(restarted) as client:
        readback = client.get(f"/api/pipeline/nodes/fixture-events/revisions/{saved_revision}")
        assert readback.status_code == 200
        assert readback.json()["content"] == edited
        assert readback.json()["source"]["video_sha256"] == video_digest
        recording = client.get("/v1/repository-bundles/recording-both")
        assert recording.status_code == 200
        assert recording.json()["source_sha256"] == video_digest

    assert settings.evidence_root == storage_root / "runtime"
    assert settings.operations_root == storage_root / "data/operations"
    legacy_node_path = settings.repository_root / "data/operations/pipeline-nodes/fixture-events"
    assert not legacy_node_path.exists()
    assert source_manifest == {
        path.relative_to(source_bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(source_bundle.rglob("*"))
        if path.is_file()
    }
    assert video_digest == hashlib.sha256(imported_video.read_bytes()).hexdigest()
