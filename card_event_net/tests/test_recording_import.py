from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from cardevent.annotation import load_annotation_proposals
from cardevent.cli import main
from cardevent.manifest import MANIFEST_SCHEMA_VERSION, load_dataset_manifest
from cardevent.recording_import import (
    RecordingImportError,
    event_proposals_from_device_predictions,
    import_recording,
    load_device_predictions,
    probability_stream_from_device_predictions,
)
from cardevent.review_session import load_review_queue

FIXTURE_ROOT = (
    Path(__file__).parents[2] / "fixtures" / "training-recording" / "v1" / "recording-fixture-001"
).resolve()


def _metadata_path(tmp_path: Path) -> Path:
    path = tmp_path / "completed-dataset-record.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "videos": [
                    {
                        "video_id": "video-fixture-001",
                        "file_name": "video-fixture-001.mov",
                        "content_type": "staged_scenario",
                        "session_id": "session-fixture-001",
                        "game_id": None,
                        "recording_date": "2026-08-27T10:00:00Z",
                        "device": "fixture-mac",
                        "camera": "back",
                        "resolution": "640x360",
                        "frame_rate": 10.0,
                        "duration_s": 0.3,
                        "orientation": "landscape",
                        "camera_view": "overhead",
                        "camera_motion": "fixed",
                        "camera_framing": "table_fills_frame",
                        "table_setup": "setup-fixture-001",
                        "lighting": [],
                        "background": "fixture",
                        "card_deck": None,
                        "scenario_tags": [],
                        "known_limitations": ["no_game_decisions"],
                        "source": "self_recorded",
                        "annotation_version": None,
                        "source_permission": "training_and_evaluation",
                        "notes": "Complete operator-approved fixture metadata.",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _recording_dir(tmp_path: Path, *, candidate_queue: bool = False) -> Path:
    destination = tmp_path / "backend" / "training-recordings" / "recording-fixture-001"
    (destination / "videos").mkdir(parents=True)
    (destination / "predictions").mkdir()
    shutil.copy2(FIXTURE_ROOT / "manifest.json", destination / "manifest.json")
    shutil.copy2(
        FIXTURE_ROOT / "video-fixture-001.mov",
        destination / "videos" / "video-fixture-001.mov",
    )
    shutil.copy2(
        FIXTURE_ROOT / "video-fixture-001.json",
        destination / "predictions" / "video-fixture-001.json",
    )
    if candidate_queue:
        (destination / "intake").mkdir()
        (destination / "intake" / "candidate-review-queue.json").write_text(
            json.dumps(
                {
                    "format": "cardevent-review-queue-v1",
                    "provenance": "candidate_only",
                    "recording_id": "recording-fixture-001",
                    "items": [
                        {
                            "id": "candidate-001",
                            "video": "video-fixture-001.mov",
                            "timestamp_s": 0.125,
                            "category": "unmatched_model_candidate",
                            "status": "unreviewed",
                            "outcome": "unreviewed",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    return destination


def test_import_recording_copies_backend_bundle_and_receipt(tmp_path: Path) -> None:
    recording_dir = _recording_dir(tmp_path, candidate_queue=True)
    videos_dir = tmp_path / "data" / "raw"
    predictions_dir = tmp_path / "data" / "device-predictions"
    review_dir = tmp_path / "data" / "reviews" / "intake"
    manifest_path = tmp_path / "data" / "dataset-manifest.yaml"
    receipt_path = tmp_path / "data" / "recording-import-receipt.json"
    metadata_path = _metadata_path(tmp_path)

    result = import_recording(
        recording_dir,
        videos_dir=videos_dir,
        predictions_dir=predictions_dir,
        metadata=metadata_path,
        manifest=manifest_path,
        review_dir=review_dir,
        receipt=receipt_path,
    )

    assert result.recording_id == "recording-fixture-001"
    assert result.video_path == videos_dir / "video-fixture-001.mov"
    assert result.predictions_path == predictions_dir / "video-fixture-001.json"
    assert result.video_path.read_bytes() == (FIXTURE_ROOT / "video-fixture-001.mov").read_bytes()
    assert (
        result.predictions_path.read_bytes()
        == (FIXTURE_ROOT / "video-fixture-001.json").read_bytes()
    )
    records = load_dataset_manifest(manifest_path)
    assert records[0].session_id == "session-fixture-001"
    assert records[0].content_type == "staged_scenario"

    queue = load_review_queue(result.review_queue_path)
    assert queue["provenance"] == "candidate_only"
    receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt_payload["schema_version"] == "cardevent-recording-import/v1"
    assert receipt_payload["recording_id"] == "recording-fixture-001"
    assert (
        receipt_payload["files"]["video"]["sha256"]
        == hashlib.sha256(result.video_path.read_bytes()).hexdigest()
    )


def test_repeated_identical_import_is_safe(tmp_path: Path) -> None:
    recording_dir = _recording_dir(tmp_path)
    kwargs = {
        "videos_dir": tmp_path / "raw",
        "predictions_dir": tmp_path / "predictions",
        "metadata": _metadata_path(tmp_path),
        "manifest": tmp_path / "manifest.yaml",
        "receipt": tmp_path / "receipt.json",
    }

    first = import_recording(recording_dir, **kwargs)
    first_manifest = kwargs["manifest"].read_bytes()
    second = import_recording(recording_dir, **kwargs)

    assert second.video_path == first.video_path
    assert kwargs["manifest"].read_bytes() == first_manifest
    assert second.receipt_path == first.receipt_path


def test_import_rejects_incomplete_metadata_before_writing(tmp_path: Path) -> None:
    recording_dir = _recording_dir(tmp_path)
    metadata = tmp_path / "draft.yaml"
    metadata.write_text(
        "schema_version: cardevent-video-metadata/v1\nvideos:\n  - video_id: video-fixture-001\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.yaml"

    with pytest.raises(RecordingImportError, match="complete operator-approved"):
        import_recording(
            recording_dir,
            videos_dir=tmp_path / "raw",
            predictions_dir=tmp_path / "predictions",
            metadata=metadata,
            manifest=manifest_path,
            receipt=tmp_path / "receipt.json",
        )

    assert not manifest_path.exists()
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "predictions").exists()


def test_import_rejects_video_id_collision_with_different_content(tmp_path: Path) -> None:
    recording_dir = _recording_dir(tmp_path)
    kwargs = {
        "videos_dir": tmp_path / "raw",
        "predictions_dir": tmp_path / "predictions",
        "metadata": _metadata_path(tmp_path),
        "manifest": tmp_path / "manifest.yaml",
        "receipt": tmp_path / "receipt.json",
    }
    import_recording(recording_dir, **kwargs)
    original_manifest = kwargs["manifest"].read_bytes()

    conflicting_dir = tmp_path / "conflicting-recording"
    shutil.copytree(recording_dir, conflicting_dir)
    video_path = conflicting_dir / "videos" / "video-fixture-001.mov"
    video_path.write_bytes(video_path.read_bytes() + b"changed")
    manifest = json.loads((conflicting_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["video"]["byte_length"] = video_path.stat().st_size
    manifest["video"]["sha256"] = hashlib.sha256(video_path.read_bytes()).hexdigest()
    (conflicting_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RecordingImportError, match="collision"):
        import_recording(conflicting_dir, **kwargs)

    assert kwargs["manifest"].read_bytes() == original_manifest
    assert (
        kwargs["videos_dir"].joinpath("video-fixture-001.mov").read_bytes()
        == (FIXTURE_ROOT / "video-fixture-001.mov").read_bytes()
    )


def test_versioned_device_predictions_are_annotation_proposals() -> None:
    proposals = load_annotation_proposals(FIXTURE_ROOT / "video-fixture-001.json")

    assert len(proposals) == 1
    assert proposals[0].time_s == 0.125
    assert proposals[0].probability == 0.8


def test_versioned_device_predictions_convert_to_existing_stream_types() -> None:
    predictions = load_device_predictions(FIXTURE_ROOT / "video-fixture-001.json")

    probability_stream = probability_stream_from_device_predictions(predictions)
    event_proposals = event_proposals_from_device_predictions(predictions)

    assert probability_stream[1].time_s == 0.125
    assert probability_stream[1].probability == 0.8
    assert event_proposals[0].time_s == 0.125
    assert event_proposals[0].emitted_at_s == 0.25


def test_import_recording_cli_writes_the_import_artifacts(tmp_path: Path) -> None:
    recording_dir = _recording_dir(tmp_path)
    manifest_path = tmp_path / "data" / "dataset-manifest.yaml"
    receipt_path = tmp_path / "data" / "receipt.json"

    exit_code = main(
        [
            "import-recording",
            "--recording-dir",
            str(recording_dir),
            "--videos-dir",
            str(tmp_path / "data" / "raw"),
            "--predictions-dir",
            str(tmp_path / "data" / "device-predictions"),
            "--metadata",
            str(_metadata_path(tmp_path)),
            "--manifest",
            str(manifest_path),
            "--receipt",
            str(receipt_path),
        ]
    )

    assert exit_code == 0
    assert manifest_path.is_file()
    assert receipt_path.is_file()
