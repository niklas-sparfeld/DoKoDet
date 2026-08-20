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
        roi=Roi(x=0.1, y=0.2, width=0.5, height=0.5),
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


def test_validate_annotation_rejects_invalid_roi() -> None:
    metadata = sample_metadata()
    annotation = VideoAnnotation(
        video="IMG_0090.mov",
        roi=Roi(x=0.8, y=0.2, width=0.3, height=0.5),
        events=(),
    )

    with pytest.raises(AnnotationError, match="roi"):
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
    save_annotation(
        VideoAnnotation(
            video="sample.mov",
            roi=Roi(x=0.1, y=0.1, width=0.6, height=0.6),
            events=(AnnotationEvent(time_s=1.0),),
        ),
        annotation_path,
        metadata=metadata,
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
    assert session.roi == Roi(x=0.1, y=0.1, width=0.6, height=0.6)
    assert [event.time_s for event in session.events] == [1.0]
