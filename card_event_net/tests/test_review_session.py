from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cardevent.annotation import AnnotationEvent, VideoAnnotation, save_annotation
from cardevent.review import ReviewQueueError, apply_review_queue
from cardevent.review_session import ReviewSession, ReviewSessionError
from cardevent.video import VideoMetadata


def queue_payload() -> dict[str, object]:
    return {
        "format": "cardevent-review-queue-v1",
        "partition": "val",
        "items": [
            {
                "id": "item-a",
                "video": "game-a.mov",
                "timestamp_s": 1.0,
                "category": "unmatched_model_candidate",
                "score": 0.9,
                "nearest_annotation": None,
                "distance_s": None,
                "event_type": None,
                "status": "unreviewed",
                "outcome": "unreviewed",
            },
            {
                "id": "item-b",
                "video": "game-b.MOV",
                "timestamp_s": 2.0,
                "category": "missed_annotation",
                "score": 0.2,
                "nearest_annotation": {"time_s": 2.1, "type": "card_played"},
                "distance_s": 0.1,
                "event_type": "card_played",
                "status": "unreviewed",
                "outcome": "unreviewed",
            },
        ],
    }


def write_queue(tmp_path: Path) -> tuple[Path, Path]:
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue_payload()), encoding="utf-8")
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    (videos_dir / "game-a.mov").write_bytes(b"a")
    (videos_dir / "game-b.MOV").write_bytes(b"b")
    return queue_path, videos_dir


def test_session_creates_reviewed_copy_and_autosaves_decisions(tmp_path: Path) -> None:
    queue_path, videos_dir = write_queue(tmp_path)
    source_before = queue_path.read_bytes()
    session = ReviewSession.open(
        queue_path,
        tmp_path / "reviewed.json",
        videos_dir=videos_dir,
        annotations_dir=tmp_path / "annotations",
        reviewer="niklas",
    )

    assert session.summary() == {"selected": 2, "reviewed": 0, "remaining": 2}
    assert session.video_path_for().name == "game-a.mov"
    session.set_event_type("card_moved")
    session.decide("confirmed_positive", current_time_s=1.25)

    saved = json.loads((tmp_path / "reviewed.json").read_text(encoding="utf-8"))
    item = saved["items"][0]
    assert item["status"] == "reviewed"
    assert item["outcome"] == "confirmed_positive"
    assert item["positive_target"] == "new_event"
    assert item["original_timestamp_s"] == 1.0
    assert item["timestamp_s"] == 1.25
    assert item["event_type"] == "card_moved"
    assert saved["source_queue_sha256"] == hashlib.sha256(source_before).hexdigest()
    assert queue_path.read_bytes() == source_before

    session.next_item()
    session.decide("confirmed_positive", positive_target="existing_annotation")
    second = json.loads((tmp_path / "reviewed.json").read_text(encoding="utf-8"))["items"][1]
    assert second["timestamp_s"] == 2.1
    assert second["source_annotation_time_s"] == 2.1
    assert second["positive_target"] == "existing_annotation"


def test_invalid_decision_does_not_change_item_state(tmp_path: Path) -> None:
    queue_path, videos_dir = write_queue(tmp_path)
    session = ReviewSession.open(
        queue_path,
        tmp_path / "reviewed.json",
        videos_dir=videos_dir,
        annotations_dir=tmp_path / "annotations",
        reviewer="niklas",
    )

    with pytest.raises(ReviewSessionError, match="nearest source annotation"):
        session.decide("confirmed_positive", positive_target="existing_annotation")

    assert session.current_item is not None
    assert session.current_item["status"] == "unreviewed"
    assert session.current_item["outcome"] == "unreviewed"


def test_session_filters_keep_queue_order_and_resume_requires_same_source(tmp_path: Path) -> None:
    queue_path, videos_dir = write_queue(tmp_path)
    output_path = tmp_path / "reviewed.json"
    session = ReviewSession.open(
        queue_path,
        output_path,
        videos_dir=videos_dir,
        annotations_dir=tmp_path / "annotations",
        reviewer="niklas",
        category="missed_annotation",
    )
    assert [item["id"] for item in session.items if item["id"] in {"item-a", "item-b"}] == [
        "item-a",
        "item-b",
    ]
    assert session.current_item is not None
    assert session.current_item["id"] == "item-b"

    with pytest.raises(ReviewSessionError, match="reviewer"):
        ReviewSession.open(
            queue_path,
            output_path,
            videos_dir=videos_dir,
            annotations_dir=tmp_path / "annotations",
            reviewer="someone-else",
        )

    changed_queue = tmp_path / "changed.json"
    changed = queue_payload()
    changed["items"][0]["score"] = 0.1  # type: ignore[index]
    changed_queue.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ReviewSessionError, match="checksum"):
        ReviewSession.open(
            changed_queue,
            output_path,
            videos_dir=videos_dir,
            annotations_dir=tmp_path / "annotations",
            reviewer="niklas",
        )


def test_session_rejects_ambiguous_video_stems(tmp_path: Path) -> None:
    queue_path, videos_dir = write_queue(tmp_path)
    (videos_dir / "game-a.mp4").write_bytes(b"other")

    with pytest.raises(ReviewSessionError, match="ambiguous"):
        ReviewSession.open(
            queue_path,
            tmp_path / "reviewed.json",
            videos_dir=videos_dir,
            annotations_dir=tmp_path / "annotations",
            reviewer="niklas",
        )


def test_apply_uses_explicit_existing_target_without_duplicate_event(tmp_path: Path) -> None:
    queue = queue_payload()
    queue["items"] = [queue["items"][1]]
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    (videos_dir / "game-b.MOV").write_bytes(b"video")
    annotations_dir = tmp_path / "annotations"
    metadata = VideoMetadata(
        path=tmp_path / "game-b.MOV",
        width=10,
        height=10,
        fps=10.0,
        frame_count=100,
        duration_s=10.0,
    )
    source_annotation = annotations_dir / "game-b.json"
    save_annotation(
        VideoAnnotation(
            video="game-b.MOV",
            events=(AnnotationEvent(time_s=2.1, type="card_played", confidence="confirmed"),),
        ),
        source_annotation,
        metadata=metadata,
    )

    session = ReviewSession.open(
        queue_path,
        tmp_path / "reviewed.json",
        videos_dir=videos_dir,
        annotations_dir=annotations_dir,
        reviewer="niklas",
    )
    session.decide("confirmed_positive", positive_target="existing_annotation")

    destination = tmp_path / "applied"
    summary = apply_review_queue(
        tmp_path / "reviewed.json",
        annotations_dir=annotations_dir,
        out_dir=destination,
    )
    result = json.loads((destination / "game-b.json").read_text(encoding="utf-8"))
    assert len(result["events"]) == 1
    assert summary["annotations_added"] == 0
    assert (destination / "validation-hard-negatives.json").is_file()


def test_apply_rejects_partial_queue_without_allow_partial(tmp_path: Path) -> None:
    queue_path, videos_dir = write_queue(tmp_path)
    annotations_dir = tmp_path / "annotations"
    for name in ("game-a.mov", "game-b.MOV"):
        metadata = VideoMetadata(
            path=tmp_path / name,
            width=10,
            height=10,
            fps=10.0,
            frame_count=100,
            duration_s=10.0,
        )
        save_annotation(
            VideoAnnotation(video=name),
            annotations_dir / f"{Path(name).stem}.json",
            metadata=metadata,
        )
    session = ReviewSession.open(
        queue_path,
        tmp_path / "reviewed.json",
        videos_dir=videos_dir,
        annotations_dir=annotations_dir,
        reviewer="niklas",
    )
    session.decide("ignore")

    with pytest.raises(ReviewQueueError, match="allow-partial"):
        apply_review_queue(
            tmp_path / "reviewed.json",
            annotations_dir=annotations_dir,
            out_dir=tmp_path / "applied",
            reviewer="niklas",
        )
