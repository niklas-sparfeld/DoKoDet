import json
import shutil
from pathlib import Path

import pytest
from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.operator_corpus_import import import_recordings
from dokodetector_backend.recording_folder_store import (
    RecordingFolderStore,
    RecordingVersionConflict,
)

FIXTURE = Path(__file__).parents[2] / "fixtures/repository-bundle/v1/both"


def test_recording_folder_publishes_source_and_intake_facts(tmp_path: Path) -> None:
    store = RecordingFolderStore(tmp_path / "data" / "recordings")
    transport = tmp_path / "transport"
    shutil.copytree(FIXTURE, transport)

    recording = store.publish_bundle(transport, recording_id="recording-both")

    folder = store.recording_path("recording-both")
    root = json.loads((folder / "recording.json").read_text(encoding="utf-8"))
    assert recording.version == 1
    assert root["schema_version"] == "recording/v1"
    assert root["head"] == {}
    assert root["source"]["source_permission"] == "training_and_evaluation"
    assert root["task_enrollment"]["schema_version"] == "task-enrollment/v1"
    assert (folder / root["media"]["relative_path"]).read_bytes() == (
        transport / "videos/video-both.mov"
    ).read_bytes()
    assert len(store.list()) == 1


def test_recording_root_replace_checks_version_and_reopens_after_restart(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    store = RecordingFolderStore(root)
    transport = tmp_path / "transport"
    shutil.copytree(FIXTURE, transport)
    store.publish_bundle(transport, recording_id="recording-both")
    original = json.loads((root / "recording-both" / "recording.json").read_text())
    updated = store.replace_root("recording-both", original, expected_version=1)

    assert updated.version == 2
    reopened = RecordingFolderStore(root).get("recording-both")
    assert reopened is not None and reopened.version == 2
    with pytest.raises(RecordingVersionConflict):
        store.replace_root("recording-both", original, expected_version=1)


def test_import_list_and_media_open_survive_backend_restart(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[2]
    corpus_root = tmp_path / "corpus"
    shutil.copytree(FIXTURE, corpus_root / "recording-both")
    recordings_root = tmp_path / "data" / "recordings"
    import_recordings(corpus_root, recordings_root, ("recording-both",))
    settings = Settings(
        _env_file=None,
        repository_root=repository_root,
        recordings_root=recordings_root,
        evidence_root=tmp_path / "runtime",
        frontend_dist=tmp_path / "frontend",
    )

    for _ in range(2):
        with TestClient(create_test_app(settings)) as client:
            listed = client.get("/v1/recordings")
            assert listed.status_code == 200
            assert [row["recording_id"] for row in listed.json()["recordings"]] == [
                "recording-both"
            ]
            video = client.get("/v1/repository-bundles/recording-both/video")
            assert video.status_code == 200
            assert (
                video.content == (corpus_root / "recording-both/videos/video-both.mov").read_bytes()
            )
