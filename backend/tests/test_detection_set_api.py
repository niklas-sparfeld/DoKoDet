import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.detection_set_store import DetectionSetStore
from dokodetector_backend.event_set_store import EventSetStore
from dokodetector_backend.operator_corpus_import import import_recordings
from dokodetector_backend.recording_folder_store import RecordingFolderStore

FIXTURE = Path(__file__).parents[2] / "fixtures/repository-bundle/v1/both"
SOURCE_SHA256 = "7184fd89dd78b265e8f617989e8a9659897e060bde2d4f8d47dc05708771f8a8"


def _identity(frame_index: int, timestamp: int) -> dict:
    return {
        "schema_version": "exact-event/v1",
        "source_video_sha256": SOURCE_SHA256,
        "requested_time_us": timestamp,
        "frame_index": frame_index,
        "presentation_timestamp_us": timestamp,
        "width": 640,
        "height": 480,
        "decoder_version": "fixture-decoder/1",
        "transform_version": "identity/1",
        "output_encoding": "jpeg",
        "content_type": "image/jpeg",
        "image_sha256": f"{frame_index:064x}",
        "policy": "exact-event/v1",
    }


def _polygon(x: int, y: int) -> list[dict[str, int]]:
    return [
        {"x": x, "y": y},
        {"x": x + 20, "y": y},
        {"x": x + 20, "y": y + 30},
        {"x": x, "y": y + 30},
    ]


def _frame(frame_id: str, index: int, timestamp: int, *, event_ids=None, detections=None) -> dict:
    return {
        "frame_id": frame_id,
        "frame_identity": _identity(index, timestamp),
        "event_ids": event_ids or [],
        "detections": detections or [],
    }


def _settings(tmp_path: Path) -> Settings:
    corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE, corpus / "recording-both")
    recordings_root = tmp_path / "data" / "recordings"
    import_recordings(corpus, recordings_root, ("recording-both",))
    return Settings(
        _env_file=None,
        repository_root=Path(__file__).parents[2],
        recordings_root=recordings_root,
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "operations",
        frontend_dist=tmp_path / "frontend",
    )


def test_detection_set_api_saves_exact_frames_and_reopens_after_restart(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(
        "dokodetector_backend.event_pipeline_service.probe_video_path_metadata",
        lambda _path: SimpleNamespace(duration_ms=2_000),
    )
    first = create_test_app(settings)
    events = {
        "schema_version": "event-data/v1",
        "events": [
            {"event_id": "evt-1", "event_type": "card_state_changed", "start_us": 10, "end_us": 20}
        ],
    }
    with TestClient(first) as client:
        saved_events = client.post(
            "/api/recordings/recording-both/event-sets",
            json={
                "set_id": "event-alt",
                "version": "1",
                "content": events,
                "origin": "manual",
                "provenance": {},
            },
        )
        assert saved_events.status_code == 200, saved_events.text
        event_version = client.get(
            "/api/recordings/recording-both/event-sets/event-alt/versions/1"
        ).json()
        content = {
            "set_id": "det-alt",
            "version": "1",
            "origin": "manual",
            "source": {"source_video_sha256": SOURCE_SHA256},
            "producer": {"tool": "test-editor"},
            "event_sets": [
                {
                    "set_id": "event-alt",
                    "version": "1",
                    "content_sha256": event_version["content_sha256"],
                }
            ],
            "frames": [
                _frame(
                    "frame-direct",
                    3,
                    30,
                    detections=[
                        {
                            "object_id": "card-1",
                            "kind": "visible_card",
                            "side": "face_up",
                            "segments": [
                                {"segment_id": "left", "polygon": _polygon(10, 10)},
                                {"segment_id": "right", "polygon": _polygon(40, 10)},
                            ],
                        },
                        {
                            "object_id": "pile-1",
                            "kind": "pile",
                            "side": None,
                            "segments": [
                                {"segment_id": "pile-area", "polygon": _polygon(100, 100)}
                            ],
                        },
                        {
                            "object_id": "ignore-1",
                            "kind": "ignore",
                            "side": None,
                            "segments": [
                                {"segment_id": "ignore-area", "polygon": _polygon(150, 100)}
                            ],
                        },
                    ],
                ),
                _frame(
                    "frame-event",
                    4,
                    40,
                    event_ids=[{"set_id": "event-alt", "version": "1", "event_id": "evt-1"}],
                ),
                _frame("frame-empty", 5, 50),
            ],
        }
        response = client.post("/api/recordings/recording-both/detection-sets", json=content)
        assert response.status_code == 200, response.text
        assert response.json()["content"]["frames"] == content["frames"]
        version_path = settings.recordings_root / "recording-both/detection-sets/det-alt/versions/1"
        card_path = version_path / "frames/frame-direct/detections/card-1"
        assert (version_path / "frames/frame-direct/frame.json").is_file()
        assert (card_path / "detection.json").is_file()
        assert (card_path / "segments/left.json").is_file()
        assert (card_path / "segments/right.json").is_file()
        assert not (version_path / "frames/frame-direct.json").exists()
        review_payload = {
            "review_id": "geom-review-1",
            "reviewer": {"kind": "human", "id": "worker"},
            "question": "visible geometry is correct",
            "decision": "accepted",
            "covered_frame_ids": ["frame-direct"],
            "covered_object_ids": ["card-1"],
        }
        expected_review_path = (
            settings.recordings_root
            / "recording-both/detection-sets/det-alt/reviews/geom-review-1.json"
        )
        review_response = client.post(
            "/api/recordings/recording-both/detection-sets/det-alt/versions/1/reviews",
            json=review_payload,
        )
        assert review_response.status_code == 200, review_response.text
        assert expected_review_path.is_file()
        assert review_response.json()["content_sha256"] == response.json()["content_sha256"]
        listed_reviews = client.get(
            "/api/recordings/recording-both/detection-sets/det-alt/versions/1/reviews"
        )
        assert listed_reviews.json()["reviews"] == [review_response.json()]
        invalid_review = {
            **review_payload,
            "review_id": "geom-review-invalid",
            "covered_object_ids": ["absent-object"],
        }
        assert (
            client.post(
                "/api/recordings/recording-both/detection-sets/det-alt/versions/1/reviews",
                json=invalid_review,
            ).status_code
            == 422
        )
        assert (
            client.post("/api/recordings/recording-both/detection-sets", json=content).status_code
            == 422
        )
        invalid = {
            **content,
            "set_id": "invalid",
            "frames": [
                _frame(
                    "bad",
                    0,
                    0,
                    event_ids=[{"set_id": "missing", "version": "1", "event_id": "absent"}],
                )
            ],
        }
        assert (
            client.post("/api/recordings/recording-both/detection-sets", json=invalid).status_code
            == 422
        )
        mismatched_digest = {
            **content,
            "set_id": "bad-event-digest",
            "event_sets": [
                {
                    "set_id": "event-alt",
                    "version": "1",
                    "content_sha256": "0" * 64,
                }
            ],
        }
        assert (
            client.post(
                "/api/recordings/recording-both/detection-sets", json=mismatched_digest
            ).status_code
            == 422
        )
        bad_polygon = _frame(
            "bad-geometry",
            6,
            60,
            detections=[
                {
                    "object_id": "card-bad",
                    "kind": "visible_card",
                    "side": "unknown",
                    "segments": [
                        {
                            "segment_id": "outside",
                            "polygon": _polygon(630, 470),
                        }
                    ],
                }
            ],
        )
        assert (
            client.post(
                "/api/recordings/recording-both/detection-sets",
                json={**content, "set_id": "bad-geometry", "frames": [bad_polygon]},
            ).status_code
            == 422
        )
        self_intersecting = _frame(
            "self-intersecting",
            7,
            70,
            detections=[
                {
                    "object_id": "card-crossed",
                    "kind": "visible_card",
                    "side": "unknown",
                    "segments": [
                        {
                            "segment_id": "crossing",
                            "polygon": [
                                {"x": 10, "y": 10},
                                {"x": 50, "y": 50},
                                {"x": 10, "y": 50},
                                {"x": 40, "y": 10},
                            ],
                        }
                    ],
                }
            ],
        )
        assert (
            client.post(
                "/api/recordings/recording-both/detection-sets",
                json={**content, "set_id": "self-intersecting", "frames": [self_intersecting]},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/recordings/recording-both/detection-sets",
                json={
                    **content,
                    "set_id": "bad-source",
                    "source": {"source_video_sha256": "0" * 64},
                },
            ).status_code
            == 422
        )
        absent = client.get("/api/recordings/recording-both/detection-sets/det-alt/versions/2")
        assert absent.status_code == 404
    with TestClient(create_test_app(settings)) as client:
        reopened = client.get("/api/recordings/recording-both/detection-sets/det-alt/versions/1")
    assert reopened.status_code == 200
    assert reopened.json()["content"]["frames"] == content["frames"]
    assert reopened.json()["content"]["frames"][2]["detections"] == []
    assert reopened.json()["event_sets"] == content["event_sets"]
    with TestClient(create_test_app(settings)) as client:
        reopened_review = client.get(
            "/api/recordings/recording-both/detection-sets/det-alt/versions/1/reviews"
        )
    assert reopened_review.status_code == 200
    assert reopened_review.json()["reviews"][0]["review_id"] == "geom-review-1"


def test_failed_detection_set_publication_leaves_no_version(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    app = create_test_app(settings)
    store = app.state.detection_set_store
    frame = _frame("frame-1", 0, 0)
    original_rename = __import__("os").rename

    def fail_publish(source, destination):
        if ".detection-set-" in str(source):
            raise OSError("simulated interrupted publication")
        original_rename(source, destination)

    monkeypatch.setattr("dokodetector_backend.detection_set_store.os.rename", fail_publish)
    with pytest.raises(OSError, match="interrupted"):
        store.save(
            "recording-both",
            set_id="set",
            version="1",
            origin="manual",
            source={"source_video_sha256": SOURCE_SHA256},
            producer={},
            event_sets=[],
            frames=[frame],
        )
    assert store.get("recording-both", "set", "1") is None
    assert not list(
        (settings.recordings_root / "recording-both/detection-sets/set/versions").glob(
            ".detection-set-*"
        )
    )


def test_process_interruption_leaves_unpublished_staging_and_restart_cannot_open_it(tmp_path):
    settings = _settings(tmp_path)
    script = """
import os
import sys
from pathlib import Path
import dokodetector_backend.detection_set_store as detection_module
from dokodetector_backend.detection_set_store import DetectionSetStore
from dokodetector_backend.event_set_store import EventSetStore
from dokodetector_backend.recording_folder_store import RecordingFolderStore

root = Path(sys.argv[1])
recordings = RecordingFolderStore(root)
events = EventSetStore(recordings)
store = DetectionSetStore(recordings, events)
original_rename = os.rename
def interrupt_before_publish(source, destination):
    if ".detection-set-" in str(source):
        os._exit(73)
    original_rename(source, destination)
detection_module.os.rename = interrupt_before_publish
identity = {
    "schema_version": "exact-event/v1",
    "source_video_sha256": "7184fd89dd78b265e8f617989e8a9659897e060bde2d4f8d47dc05708771f8a8",
    "requested_time_us": 0,
    "frame_index": 0,
    "presentation_timestamp_us": 0,
    "width": 640,
    "height": 480,
    "decoder_version": "fixture-decoder/1",
    "transform_version": "identity/1",
    "output_encoding": "jpeg",
    "content_type": "image/jpeg",
    "image_sha256": "0" * 64,
    "policy": "exact-event/v1",
}
store.save(
    "recording-both", set_id="interrupted", version="1", origin="manual",
    source={"source_video_sha256": identity["source_video_sha256"]}, producer={},
    event_sets=[], frames=[{"frame_id": "frame-1", "frame_identity": identity,
                            "event_ids": [], "detections": []}],
)
"""
    process = subprocess.run(
        [sys.executable, "-c", script, str(settings.recordings_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 73, process.stderr

    recordings = RecordingFolderStore(settings.recordings_root)
    reopened = DetectionSetStore(recordings, EventSetStore(recordings))
    assert reopened.get("recording-both", "interrupted", "1") is None
    staging = list(
        (settings.recordings_root / "recording-both/detection-sets/interrupted/versions").glob(
            ".detection-set-*"
        )
    )
    assert len(staging) == 1
    assert (staging[0] / "detection-set.json").is_file()
    assert (staging[0] / "frames/frame-1/frame.json").is_file()
