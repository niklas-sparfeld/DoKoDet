from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from doko_operations.pending_video import PendingVideoCompletionError, complete_pending_video

ROOT = Path(__file__).parents[2]
VIDEO = ROOT / "fixtures" / "evidence" / "v2" / "example-complete" / "snippet.mp4"


def _metadata() -> dict[str, object]:
    return {
        "schema_version": "pending-video-completion/v1",
        "source_asset_id": "source-upload-001",
        "recording_id": "recording-upload-001",
        "video_id": "video-upload-001",
        "session_id": "session-upload-001",
        "acquisition_method": "operator_completed_pending_upload",
        "source_permission": "training_and_evaluation",
        "allowed_uses": ["train", "validation", "evaluation"],
        "game_id": "game-upload-001",
        "round_id": None,
        "table_setup": "table-upload-v1",
        "content_type": "real_game",
        "notes": "Completed by the fixture operator.",
        "task_enrollments": [
            {
                "task_enrollment_id": "enrollment-upload-cardevent",
                "task": "cardevent_event_detection",
                "disposition": "selected",
                "lifecycle_state": "intake",
                "operator": "fixture-operator",
                "created_at_utc": "2026-08-28T16:00:00Z",
                "reason": None,
            },
            {
                "task_enrollment_id": "enrollment-upload-table",
                "task": "table_evidence_analysis",
                "disposition": "selected",
                "lifecycle_state": "intake",
                "operator": "fixture-operator",
                "created_at_utc": "2026-08-28T16:00:00Z",
                "reason": None,
            },
        ],
    }


def _write_pending(root: Path, upload_id: str = "upload-001") -> bytes:
    video = VIDEO.read_bytes()
    pending = root / upload_id
    pending.mkdir(parents=True)
    (pending / "pending.mov").write_bytes(video)
    (pending / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "pending-video/v1",
                "upload_id": upload_id,
                "state": "pending",
                "original_filename": "pending.mov",
                "byte_length": len(video),
                "sha256": hashlib.sha256(video).hexdigest(),
                "media_type": "video/quicktime",
                "received_at_utc": "2026-08-28T15:00:00Z",
                "media_facts": {
                    "container": "mp4",
                    "video_codec": "h264",
                    "width": 640,
                    "height": 360,
                    "nominal_frame_rate": 15.0,
                    "duration_ms": 2133,
                    "frame_count": 32,
                },
            }
        )
    )
    return video


def test_completion_promotes_the_same_video_bytes_atomically(tmp_path: Path) -> None:
    incoming = tmp_path / "data" / "incoming" / "videos"
    intake = tmp_path / "data" / "intake" / "recordings"
    video = _write_pending(incoming)

    result = complete_pending_video(tmp_path, "upload-001", _metadata())

    bundle = intake / "recording-upload-001"
    assert result.state == "complete"
    assert result.recording_id == "recording-upload-001"
    assert (bundle / "videos" / "video-upload-001.mov").read_bytes() == video
    assert hashlib.sha256(
        (bundle / "videos" / "video-upload-001.mov").read_bytes()
    ).hexdigest() == (hashlib.sha256(video).hexdigest())
    assert json.loads((bundle / "manifest.json").read_text())["source_sha256"] == (
        hashlib.sha256(video).hexdigest()
    )
    assert not (incoming / "upload-001").exists()
    assert list(intake.glob(".upload-*")) == []

    repeated = complete_pending_video(tmp_path, "upload-001", _metadata())
    assert repeated == result


def test_invalid_completion_leaves_pending_upload_untouched(tmp_path: Path) -> None:
    incoming = tmp_path / "data" / "incoming" / "videos"
    video = _write_pending(incoming)
    before = {
        path.relative_to(incoming / "upload-001").as_posix(): path.read_bytes()
        for path in (incoming / "upload-001").iterdir()
    }
    metadata = _metadata()
    metadata["content_type"] = "staged_scenario"
    metadata["game_id"] = "game-not-allowed"

    with pytest.raises(PendingVideoCompletionError):
        complete_pending_video(tmp_path, "upload-001", metadata)

    after = {
        path.relative_to(incoming / "upload-001").as_posix(): path.read_bytes()
        for path in (incoming / "upload-001").iterdir()
    }
    assert after == before
    assert not (tmp_path / "data" / "intake" / "recordings").exists()
    intake_parent = tmp_path / "data" / "intake"
    assert not intake_parent.exists() or list(intake_parent.glob(".upload-*")) == []
    assert (
        hashlib.sha256(video).hexdigest()
        == json.loads((incoming / "upload-001" / "manifest.json").read_text())["sha256"]
    )


def test_completion_conflict_leaves_pending_upload_and_existing_bundle_unchanged(
    tmp_path: Path,
) -> None:
    incoming = tmp_path / "data" / "incoming" / "videos"
    _write_pending(incoming, "upload-001")
    complete_pending_video(tmp_path, "upload-001", _metadata())

    _write_pending(incoming, "upload-002")
    conflicting = _metadata()
    conflicting["recording_id"] = "recording-upload-001"
    conflicting["source_asset_id"] = "source-upload-002"

    with pytest.raises(PendingVideoCompletionError, match="already exists"):
        complete_pending_video(tmp_path, "upload-002", conflicting)

    assert (incoming / "upload-002").exists()
    assert (tmp_path / "data" / "intake" / "recordings" / "recording-upload-001").is_dir()
