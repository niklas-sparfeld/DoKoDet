import json
import shutil
from pathlib import Path

import pytest
from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.event_set_store import EventSetError, EventSetStore
from dokodetector_backend.operator_corpus_import import import_recordings
from dokodetector_backend.recording_folder_store import (
    RecordingFolderStore,
    RecordingVersionConflict,
)

FIXTURE = Path(__file__).parents[2] / "fixtures/repository-bundle/v1/both"


def _store(tmp_path: Path) -> tuple[EventSetStore, Path]:
    corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE, corpus / "recording-both")
    root = tmp_path / "data" / "recordings"
    import_recordings(corpus, root, ("recording-both",))
    return EventSetStore(RecordingFolderStore(root)), root


def _content(start: int):
    return {
        "schema_version": "event-data/v1",
        "events": [
            {
                "event_id": "event-1",
                "event_type": "card_state_changed",
                "start_us": start,
                "end_us": start + 100,
            }
        ],
    }


def test_saves_immutable_event_alternatives_and_reopens_exact_versions(tmp_path: Path):
    store, root = _store(tmp_path)
    original = store.save(
        "recording-both",
        set_id="generated",
        version="1",
        content=_content(10),
        origin="processor",
        provenance={"source": {"video_sha256": "a" * 64}},
    )
    alternative = store.save(
        "recording-both",
        set_id="corrected",
        version="1",
        content=_content(20),
        origin="manual",
        provenance={"source": {"event_set": "generated/1"}},
    )

    reopened = EventSetStore(RecordingFolderStore(root)).get("recording-both", "generated", "1")

    assert reopened is not None
    assert reopened["content"] == original["content"]
    assert alternative["content"] != original["content"]
    event_path = root / "recording-both/event-sets/generated/versions/1/events/event-1/event.json"
    assert json.loads(event_path.read_text()) == {
        "schema_version": "event/v1",
        **original["content"]["events"][0],
    }
    with pytest.raises(EventSetError, match="already exists"):
        store.save(
            "recording-both",
            set_id="generated",
            version="1",
            content=_content(30),
            origin="manual",
            provenance={},
        )

    edited = store.save(
        "recording-both",
        set_id="generated",
        version="2",
        content=_content(30),
        origin="corrected",
        provenance={"source": {"set_id": "generated", "version": "1"}},
    )
    assert edited["content"] == _content(30)
    assert store.get("recording-both", "generated", "1")["content"] == _content(10)


def test_selection_is_exact_and_recording_version_checked(tmp_path: Path):
    store, root = _store(tmp_path)
    store.save(
        "recording-both",
        set_id="alternative",
        version="1",
        content=_content(10),
        origin="manual",
        provenance={},
    )

    selected = store.select(
        "recording-both",
        choice="reference",
        reference={"set_id": "alternative", "version": "1"},
        expected_version=1,
    )

    assert selected["recording_version"] == 2
    assert selected["head"]["events"]["reference"] == {"set_id": "alternative", "version": "1"}
    assert RecordingFolderStore(root).get("recording-both").head == selected["head"]
    with pytest.raises(RecordingVersionConflict):
        store.select("recording-both", choice="generated", reference=None, expected_version=1)
    with pytest.raises(EventSetError, match="unavailable"):
        store.select(
            "recording-both",
            choice="generated",
            reference={"set_id": "alternative", "version": "2"},
            expected_version=2,
        )


def test_event_set_api_saves_selects_edits_and_reopens_after_restart(tmp_path: Path):
    repository = Path(__file__).parents[2]
    corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE, corpus / "recording-both")
    recordings_root = tmp_path / "data" / "recordings"
    import_recordings(corpus, recordings_root, ("recording-both",))
    settings = Settings(
        _env_file=None,
        repository_root=repository,
        recordings_root=recordings_root,
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "operations",
        frontend_dist=tmp_path / "frontend",
    )
    first = create_test_app(settings)
    with TestClient(first) as client:
        for set_id, start in (("first", 10), ("second", 20)):
            saved = client.post(
                "/api/recordings/recording-both/event-sets",
                json={
                    "set_id": set_id,
                    "version": "1",
                    "content": _content(start),
                    "origin": "manual",
                    "provenance": {"source": None},
                },
            )
            assert saved.status_code == 200, saved.text
        selected = client.put(
            "/api/recordings/recording-both/event-sets/selection",
            json={
                "choice": "reference",
                "reference": {"set_id": "second", "version": "1"},
                "expected_recording_version": 1,
            },
        )
        assert selected.status_code == 200, selected.text
        stale = client.put(
            "/api/recordings/recording-both/event-sets/selection",
            json={"choice": "generated", "reference": None, "expected_recording_version": 1},
        )
        assert stale.status_code == 409
    with TestClient(create_test_app(settings)) as client:
        listing = client.get("/api/recordings/recording-both/event-sets")
        reopened = client.get("/api/recordings/recording-both/event-sets/second/versions/1")
    assert listing.status_code == 200
    assert len(listing.json()["event_sets"]) == 2
    assert listing.json()["head"]["reference"] == {"set_id": "second", "version": "1"}
    assert reopened.status_code == 200
    assert reopened.json()["content"] == _content(20)
