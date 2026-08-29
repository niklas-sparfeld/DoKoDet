from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from cardevent.evidence_extraction import (
    EvidenceExtractionError,
    extract_annotation_evidence,
)
from cardevent.vision_annotation import import_evidence_packages


def _write_video(path: Path, *, frame_count: int = 10, fps: float = 10.0) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        (64, 48),
    )
    if not writer.isOpened():
        pytest.skip("OpenCV cannot create a test video with MJPG in this environment.")
    for index in range(frame_count):
        writer.write(np.full((48, 64, 3), index * 20, dtype=np.uint8))
    writer.release()


def _write_inputs(tmp_path: Path, *, event_time_s: float = 0.4) -> tuple[Path, Path, Path]:
    videos_dir = tmp_path / "videos"
    annotations_dir = tmp_path / "annotations"
    videos_dir.mkdir()
    annotations_dir.mkdir()
    video_path = videos_dir / "sample.avi"
    _write_video(video_path)
    (annotations_dir / "sample.json").write_text(
        json.dumps(
            {
                "schema_version": "cardevent-annotation/v2",
                "video": "sample.avi",
                "events": [
                    {"time_s": event_time_s, "type": "card_played"},
                    {
                        "time_s": min(0.7, event_time_s + 0.2),
                        "type": "card_played",
                        "confidence": "uncertain",
                    },
                    {"time_s": 0.8, "type": "trick_cleared", "confidence": "confirmed"},
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "dataset-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "cardevent-video-metadata/v1",
                "videos": [
                    {
                        "video_id": "sample",
                        "file_name": "sample.avi",
                        "content_type": "staged_trick_sequence",
                        "session_id": "session-sample",
                        "game_id": None,
                        "recording_date": "2026-08-29T10:00:00Z",
                        "device": "test-camera",
                        "camera": "back",
                        "resolution": "64x48",
                        "frame_rate": 10.0,
                        "duration_s": 1.0,
                        "orientation": "landscape",
                        "camera_view": "high_oblique",
                        "camera_motion": "fixed",
                        "camera_framing": "table_fills_frame",
                        "table_setup": "setup-sample",
                        "lighting": ["room_light"],
                        "background": None,
                        "card_deck": None,
                        "scenario_tags": ["normal_card_play"],
                        "known_limitations": [],
                        "source": "self_recorded",
                        "annotation_version": "cardevent-annotation/v2",
                        "source_permission": "project_use",
                        "notes": "Generated extraction test input.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return videos_dir, annotations_dir, manifest_path


def test_extract_annotation_evidence_writes_source_resolution_packages(tmp_path: Path) -> None:
    videos_dir, annotations_dir, manifest_path = _write_inputs(tmp_path)
    output_dir = tmp_path / "evidence"

    result = extract_annotation_evidence(
        videos_dir=videos_dir,
        annotations_dir=annotations_dir,
        dataset_manifest=manifest_path,
        output_dir=output_dir,
        target_offsets_ms=(-100, 100),
    )

    assert result.package_count == 1
    assert result.excluded_event_count == 2
    extraction = json.loads((output_dir / "extraction-manifest.json").read_text())
    assert extraction["schema_version"] == "annotation-evidence-extraction/v1"
    assert extraction["source_kind"] == "reviewed_event_annotations"
    assert extraction["target_offsets_ms"] == [-100, 100]
    assert extraction["packages"][0]["session_id"] == "session-sample"
    assert extraction["packages"][0]["annotation_event_index"] == 0
    assert (
        extraction["packages"][0]["source_video_sha256"]
        == hashlib.sha256((videos_dir / "sample.avi").read_bytes()).hexdigest()
    )

    package_path = output_dir / extraction["packages"][0]["relative_path"]
    evidence = json.loads((package_path / "manifest.json").read_text())
    assert evidence["schema_version"] == "cardevent-evidence/v2"
    assert evidence["event"] == {
        "event_time_ms": 400,
        "emitted_at_ms": 400,
        "evidence_complete": True,
    }
    assert evidence["model"]["name"] == "HumanAnnotation"
    assert evidence["event_decoder"]["algorithm"] == "reviewed_annotation_v1"
    assert [frame["target_offset_ms"] for frame in evidence["frames"]] == [-100, 100]
    assert [frame["actual_offset_ms"] for frame in evidence["frames"]] == [-100, 100]
    assert all(frame["width"] == 64 and frame["height"] == 48 for frame in evidence["frames"])
    for frame in evidence["frames"]:
        frame_path = package_path / "frames" / f"{frame['part_name']}.jpg"
        assert cv2.imread(str(frame_path)).shape == (48, 64, 3)
        assert hashlib.sha256(frame_path.read_bytes()).hexdigest() == frame["sha256"]

    imported = import_evidence_packages([package_path])
    assert len(imported) == 1
    assert len(imported[0].observed_cards[0].frame_observations) == 2

    second_output = tmp_path / "second-evidence"
    extract_annotation_evidence(
        videos_dir=videos_dir,
        annotations_dir=annotations_dir,
        dataset_manifest=manifest_path,
        output_dir=second_output,
        target_offsets_ms=(-100, 100),
    )
    second_extraction = json.loads(
        (second_output / "extraction-manifest.json").read_text(encoding="utf-8")
    )
    assert second_extraction["packages"][0]["package_id"] == evidence["package_id"]


def test_extract_annotation_evidence_records_targets_outside_the_video_as_missing(
    tmp_path: Path,
) -> None:
    videos_dir, annotations_dir, manifest_path = _write_inputs(tmp_path, event_time_s=0.05)
    output_dir = tmp_path / "evidence"

    extract_annotation_evidence(
        videos_dir=videos_dir,
        annotations_dir=annotations_dir,
        dataset_manifest=manifest_path,
        output_dir=output_dir,
        target_offsets_ms=(-100, 100),
    )

    extraction = json.loads((output_dir / "extraction-manifest.json").read_text())
    package_path = output_dir / extraction["packages"][0]["relative_path"]
    evidence = json.loads((package_path / "manifest.json").read_text())
    assert evidence["event"]["evidence_complete"] is False
    assert evidence["missing_frame_targets_ms"] == [-100]
    assert [frame["target_offset_ms"] for frame in evidence["frames"]] == [100]


def test_extract_annotation_evidence_refuses_to_replace_an_output(tmp_path: Path) -> None:
    videos_dir, annotations_dir, manifest_path = _write_inputs(tmp_path)
    output_dir = tmp_path / "evidence"
    output_dir.mkdir()

    with pytest.raises(EvidenceExtractionError, match="already exists"):
        extract_annotation_evidence(
            videos_dir=videos_dir,
            annotations_dir=annotations_dir,
            dataset_manifest=manifest_path,
            output_dir=output_dir,
        )


def test_extract_annotation_evidence_can_exclude_the_test_partition(tmp_path: Path) -> None:
    videos_dir, annotations_dir, manifest_path = _write_inputs(tmp_path)
    split_path = tmp_path / "split.json"
    split_path.write_text(
        json.dumps({"train": [], "val": [], "test": ["sample"]}), encoding="utf-8"
    )

    result = extract_annotation_evidence(
        videos_dir=videos_dir,
        annotations_dir=annotations_dir,
        dataset_manifest=manifest_path,
        output_dir=tmp_path / "evidence",
        split_path=split_path,
        partitions=("train", "val"),
    )

    assert result.package_count == 0
    extraction = json.loads((result.output_dir / "extraction-manifest.json").read_text())
    assert extraction["split_sha256"] == hashlib.sha256(split_path.read_bytes()).hexdigest()
    assert extraction["partitions"] == ["train", "val"]


def test_extract_annotation_evidence_explains_missing_git_lfs_media(tmp_path: Path) -> None:
    videos_dir, annotations_dir, manifest_path = _write_inputs(tmp_path)
    (videos_dir / "sample.avi").write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
        "size 100\n",
        encoding="utf-8",
    )

    with pytest.raises(EvidenceExtractionError, match="Git LFS pointer"):
        extract_annotation_evidence(
            videos_dir=videos_dir,
            annotations_dir=annotations_dir,
            dataset_manifest=manifest_path,
            output_dir=tmp_path / "evidence",
        )
    assert not (tmp_path / "evidence").exists()
