import json
import shutil
from pathlib import Path
from types import SimpleNamespace

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


def test_event_set_api_saves_selects_edits_and_reopens_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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
    monkeypatch.setattr(
        "dokodetector_backend.event_pipeline_service.probe_video_path_metadata",
        lambda _path: SimpleNamespace(duration_ms=2_000),
    )
    first = create_test_app(settings)
    selection_store = first.state.pipeline_selection_store
    get_exact = selection_store.get_exact
    update_exact = selection_store.update_exact

    def forbid_event_get(recording_id, content_type):
        if content_type == "events":
            raise AssertionError("legacy event selection read was called")
        return get_exact(recording_id, content_type)

    def forbid_event_update(recording_id, content_type, **kwargs):
        if content_type == "events":
            raise AssertionError("legacy event selection write was called")
        return update_exact(recording_id, content_type, **kwargs)

    selection_store.get_exact = forbid_event_get
    selection_store.update_exact = forbid_event_update
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
        event_selection = client.get("/api/recordings/recording-both/pipeline/events/selection")
        assert event_selection.status_code == 200
        assert event_selection.json()["selection"]["selected_completed_reference"] == {
            "set_id": "second",
            "version": "1",
        }
        advanced = client.put(
            "/api/recordings/recording-both/pipeline/events/selection",
            json={
                "expected_recording_version": 2,
                "selected_generated": {"set_id": "first", "version": "1"},
            },
        )
        assert advanced.status_code == 200, advanced.text
        listed_recordings = client.get("/v1/recordings")
        event_row = next(
            row
            for row in listed_recordings.json()["recordings"][0]["selections"]
            if row["content_type"] == "events"
        )
        assert event_row["selected_generated"] == {"set_id": "first", "version": "1"}
        assert event_row["selected_completed_reference"] == {
            "set_id": "second",
            "version": "1",
        }
        workspace = client.get("/api/recordings/recording-both/pipeline?stage=events")
        assert workspace.status_code == 200, workspace.text
        event_stage = next(
            stage for stage in workspace.json()["stages"] if stage["key"] == "events"
        )
        assert event_stage["selected_generated"] is None
        assert event_stage["selected_event_set_generated"] == {
            "set_id": "first",
            "version": "1",
        }
        assert event_stage["selected_event_set_reference"] == {
            "set_id": "second",
            "version": "1",
        }
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
    assert listing.json()["head"]["generated"] == {"set_id": "first", "version": "1"}
    assert reopened.status_code == 200
    assert reopened.json()["content"] == _content(20)
