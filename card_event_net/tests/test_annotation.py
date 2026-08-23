from __future__ import annotations

import json
from pathlib import Path

import pytest

from cardevent.annotation import (
    AnnotationError,
    AnnotationEvent,
    AnnotationSession,
    Roi,
    VideoAnnotation,
    annotation_path_for_video,
    load_annotation,
    load_annotation_proposals,
    save_annotation,
    validate_annotation,
)
from cardevent.video import VideoMetadata


def sample_metadata() -> VideoMetadata:
    return VideoMetadata(
        path=Path("IMG_0090.mov"),
        width=1920,
        height=1080,
        fps=30.0,
        frame_count=300,
        duration_s=10.0,
    )


def test_annotation_path_for_video_uses_project_layout() -> None:
    path = annotation_path_for_video(Path("card_event_net/data/raw/IMG_0090.mov"))

    assert path == Path("card_event_net/data/annotations/IMG_0090.json")


def test_save_annotation_sorts_events_and_warns(tmp_path: Path) -> None:
    metadata = sample_metadata()
    annotation = VideoAnnotation(
        video="IMG_0090.mov",
        events=(
            AnnotationEvent(time_s=2.0),
            AnnotationEvent(time_s=1.0),
            AnnotationEvent(time_s=1.05),
        ),
    )
    path = tmp_path / "IMG_0090.json"

    with pytest.warns(UserWarning, match="less than 100 ms apart"):
        save_annotation(annotation, path, metadata=metadata)
        loaded = load_annotation(path)
        validate_annotation(loaded, metadata)

    assert [event.time_s for event in loaded.events] == [1.0, 1.05, 2.0]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "cardevent-annotation/v2"
    assert "roi" not in saved


def test_load_annotation_rejects_unsorted_events(tmp_path: Path) -> None:
    path = tmp_path / "IMG_0090.json"
    path.write_text(
        json.dumps(
            {
                "video": "IMG_0090.mov",
                "roi": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.5},
                "events": [
                    {"time_s": 2.0, "type": "card_played"},
                    {"time_s": 1.0, "type": "card_played"},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AnnotationError, match="sorted"):
        load_annotation(path)


def test_validate_annotation_allows_v2_without_roi() -> None:
    metadata = sample_metadata()
    annotation = VideoAnnotation(
        video="IMG_0090.mov",
        events=(),
    )

    validate_annotation(annotation, metadata)


def test_annotation_session_resumes_existing_file(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.mov"
    video_path.write_bytes(b"placeholder")
    metadata = sample_metadata()
    metadata = VideoMetadata(
        path=video_path,
        width=metadata.width,
        height=metadata.height,
        fps=metadata.fps,
        frame_count=metadata.frame_count,
        duration_s=metadata.duration_s,
    )
    annotations_dir = tmp_path / "annotations"
    annotation_path = annotations_dir / "sample.json"
    annotations_dir.mkdir()
    annotation_path.write_text(
        json.dumps(
            {
                "video": "sample.mov",
                "roi": {"x": 0.1, "y": 0.1, "width": 0.6, "height": 0.6},
                "events": [{"time_s": 1.0, "type": "card_played"}],
            }
        ),
        encoding="utf-8",
    )

    def fake_read_video_metadata(_: str | Path) -> VideoMetadata:
        return metadata

    from cardevent import annotation as annotation_module

    original_reader = annotation_module.read_video_metadata
    annotation_module.read_video_metadata = fake_read_video_metadata
    try:
        session = AnnotationSession.open(video_path, annotations_dir=annotations_dir)
    finally:
        annotation_module.read_video_metadata = original_reader

    assert session.annotation_path == annotation_path
    assert [event.time_s for event in session.events] == [1.0]
    session.add_event(2.0)
    session.save()
    saved = json.loads(annotation_path.read_text(encoding="utf-8"))
    assert saved == {
        "schema_version": "cardevent-annotation/v2",
        "video": "sample.mov",
        "events": [
            {"time_s": 1.0, "type": "card_played"},
            {"time_s": 2.0, "type": "card_played", "confidence": "confirmed"},
        ],
    }


def test_new_annotation_session_saves_without_roi(tmp_path: Path) -> None:
    metadata = sample_metadata()
    session = AnnotationSession(
        video_path=metadata.path,
        metadata=metadata,
        annotation_path=tmp_path / "IMG_0090.json",
    )

    session.add_event(1.0)

    assert json.loads(session.annotation_path.read_text(encoding="utf-8")) == {
        "schema_version": "cardevent-annotation/v2",
        "video": "IMG_0090.mov",
        "events": [{"time_s": 1.0, "type": "card_played", "confidence": "confirmed"}],
    }


def test_extended_event_types_and_optional_fields_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "IMG_0090.json"
    annotation = VideoAnnotation(
        video="IMG_0090.mov",
        events=(
            AnnotationEvent(
                time_s=1.0,
                type="trick_cleared",
                confidence="confirmed",
                notes="all cards removed",
            ),
        ),
    )

    save_annotation(annotation, path, metadata=sample_metadata())

    assert load_annotation(path).events[0] == annotation.events[0]


def test_annotation_rejects_unknown_event_type() -> None:
    annotation = VideoAnnotation(
        video="IMG_0090.mov",
        events=(AnnotationEvent(time_s=1.0, type="unknown"),),
    )

    with pytest.raises(AnnotationError, match="Unknown event type"):
        validate_annotation(annotation, sample_metadata())


def test_load_annotation_preserves_legacy_roi_but_saves_v2(tmp_path: Path) -> None:
    path = tmp_path / "IMG_0090.json"
    path.write_text(
        json.dumps(
            {
                "video": "IMG_0090.mov",
                "roi": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.5},
                "events": [{"time_s": 1.0, "type": "card_played", "notes": "legacy"}],
            }
        ),
        encoding="utf-8",
    )

    annotation = load_annotation(path)

    assert annotation.roi == Roi(x=0.1, y=0.2, width=0.5, height=0.5)
    save_annotation(annotation, path, metadata=sample_metadata())
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": "cardevent-annotation/v2",
        "video": "IMG_0090.mov",
        "events": [{"time_s": 1.0, "type": "card_played", "notes": "legacy"}],
    }


def test_load_annotation_rejects_v2_with_roi_or_wrong_version(tmp_path: Path) -> None:
    path = tmp_path / "IMG_0090.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "cardevent-annotation/v2",
                "video": "IMG_0090.mov",
                "roi": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.5},
                "events": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AnnotationError, match="invalid keys"):
        load_annotation(path)

    path.write_text(
        json.dumps(
            {"schema_version": "cardevent-annotation/v1", "video": "IMG_0090.mov", "events": []}
        ),
        encoding="utf-8",
    )
    with pytest.raises(AnnotationError, match="schema_version"):
        load_annotation(path)


def test_model_proposals_load_without_becoming_ground_truth(tmp_path: Path) -> None:
    path = tmp_path / "predictions.json"
    path.write_text(
        json.dumps({"events": [{"time_s": 2.0, "probability": 0.91}]}), encoding="utf-8"
    )

    proposals = load_annotation_proposals(path)

    assert proposals[0].time_s == 2.0
    assert proposals[0].probability == 0.91
