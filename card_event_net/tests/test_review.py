from __future__ import annotations

import json
from pathlib import Path

import pytest

from cardevent.annotation import AnnotationEvent, VideoAnnotation, save_annotation
from cardevent.cli import build_parser
from cardevent.evaluation import ScoredVideo
from cardevent.events import ProbabilitySample
from cardevent.review import (
    ReviewQueueError,
    apply_review_queue,
    build_review_queue,
)
from cardevent.video import VideoMetadata


def test_review_commands_parse_required_inputs() -> None:
    queue_args = build_parser().parse_args(
        [
            "review-queue",
            "--checkpoint",
            "run/best.pt",
            "--split",
            "split.yaml",
            "--partition",
            "val",
            "--out",
            "queue.json",
        ]
    )
    apply_args = build_parser().parse_args(
        [
            "apply-review",
            "--queue",
            "queue.json",
            "--out-dir",
            "annotations-v2",
            "--reviewer",
            "reviewer",
        ]
    )

    assert queue_args.command_name == "review-queue"
    assert queue_args.partition == "val"
    assert apply_args.command_name == "apply-review"
    assert apply_args.reviewer == "reviewer"


def scored_video() -> ScoredVideo:
    samples = tuple(
        ProbabilitySample(time_s=float(index), probability=probability)
        for index, probability in enumerate(
            [0.05, 0.1, 0.2, 0.1, 0.68, 0.1, 0.2, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.95, 0.1]
        )
    )
    return ScoredVideo(
        name="game-a",
        duration_s=16.0,
        ground_truth_times_s=(4.0, 10.0),
        ground_truth_types=("card_played", "trick_cleared"),
        probabilities=samples,
    )


def test_review_queue_is_deterministic_and_keeps_outcomes_unreviewed() -> None:
    kwargs = {
        "partition": "val",
        "threshold": 0.65,
        "merge_window_s": 0.6,
        "event_match_tolerance_s": 0.75,
        "empty_count": 2,
        "seed": 123,
    }

    first = build_review_queue([scored_video()], **kwargs)
    second = build_review_queue([scored_video()], **kwargs)

    assert first == second
    assert first["format"] == "cardevent-review-queue-v1"
    assert first["items"]
    assert all(item["status"] == "unreviewed" for item in first["items"])
    assert all(item["outcome"] == "unreviewed" for item in first["items"])
    assert {item["category"] for item in first["items"]} >= {
        "unmatched_model_candidate",
        "low_confidence_match",
        "missed_annotation",
        "empty_interval",
    }
    required = {
        "video",
        "timestamp_s",
        "category",
        "score",
        "nearest_annotation",
        "distance_s",
        "event_type",
        "preview",
        "status",
        "outcome",
    }
    assert required <= set(first["items"][0])


def test_apply_review_writes_new_version_and_preserves_source(tmp_path: Path) -> None:
    metadata = VideoMetadata(
        path=tmp_path / "game-a.mov",
        width=10,
        height=10,
        fps=10.0,
        frame_count=100,
        duration_s=10.0,
    )
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_path = source_dir / "game-a.json"
    save_annotation(
        VideoAnnotation(
            video="game-a.mov",
            events=(AnnotationEvent(time_s=4.0, type="card_played", confidence="confirmed"),),
        ),
        source_path,
        metadata=metadata,
    )
    source_before = source_path.read_bytes()
    other_source_path = source_dir / "game-b.json"
    save_annotation(
        VideoAnnotation(video="game-b.mov"),
        other_source_path,
        metadata=VideoMetadata(
            path=tmp_path / "game-b.mov",
            width=10,
            height=10,
            fps=10.0,
            frame_count=100,
            duration_s=10.0,
        ),
    )
    other_source_before = other_source_path.read_bytes()

    queue_path = tmp_path / "queue.json"
    queue = build_review_queue(
        [scored_video()],
        partition="val",
        threshold=0.65,
        merge_window_s=0.6,
        event_match_tolerance_s=0.75,
        empty_count=0,
    )
    for item in queue["items"]:
        item["status"] = "reviewed"
        item["outcome"] = "ignore"
    queue["items"][0]["outcome"] = "confirmed_positive"
    queue["items"][0]["timestamp_s"] = 2.0
    queue["items"][0]["event_type"] = "card_moved"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    destination = tmp_path / "version-2"
    summary = apply_review_queue(
        queue_path,
        annotations_dir=source_dir,
        out_dir=destination,
        reviewer="niklas",
    )

    assert source_path.read_bytes() == source_before
    assert other_source_path.read_bytes() == other_source_before
    result = json.loads((destination / "game-a.json").read_text(encoding="utf-8"))
    assert any(event["time_s"] == 2.0 for event in result["events"])
    assert (destination / "game-b.json").is_file()
    assert summary["reviewer"] == "niklas"
    assert summary["video_count"] == 2
    assert summary["reviewed_video_count"] == 1
    assert summary["annotations_added"] == 1
    assert "review_queue=" in next(
        event["notes"] for event in result["events"] if event["time_s"] == 2.0
    )
    assert next(event["type"] for event in result["events"] if event["time_s"] == 2.0) == (
        "card_moved"
    )
    assert (destination / "review-application.json").is_file()
    assert json.loads((destination / "reviewed-queue.json").read_text(encoding="utf-8")) == queue
    assert (destination / "review-hard-negatives.json").is_file()


def test_apply_review_rejects_source_as_output(tmp_path: Path) -> None:
    queue = build_review_queue(
        [scored_video()],
        partition="val",
        threshold=0.65,
        merge_window_s=0.6,
        event_match_tolerance_s=0.75,
        empty_count=0,
    )
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    annotations_dir = tmp_path / "annotations"
    annotations_dir.mkdir()

    with pytest.raises(ReviewQueueError, match="must differ"):
        apply_review_queue(
            queue_path,
            annotations_dir=annotations_dir,
            out_dir=annotations_dir,
            reviewer="reviewer",
        )


def test_apply_review_rejects_outcome_without_reviewed_status(tmp_path: Path) -> None:
    queue = build_review_queue(
        [scored_video()],
        partition="val",
        threshold=0.65,
        merge_window_s=0.6,
        event_match_tolerance_s=0.75,
        empty_count=0,
    )
    queue["items"][0]["outcome"] = "confirmed_hard_negative"
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    with pytest.raises(ReviewQueueError, match="unreviewed item has an outcome"):
        apply_review_queue(
            queue_path,
            annotations_dir=tmp_path / "annotations",
            out_dir=tmp_path / "reviewed",
            reviewer="reviewer",
        )


def test_apply_review_requires_event_type_for_new_positive(tmp_path: Path) -> None:
    metadata = VideoMetadata(
        path=tmp_path / "game-a",
        width=10,
        height=10,
        fps=10.0,
        frame_count=200,
        duration_s=20.0,
    )
    source_dir = tmp_path / "annotations"
    save_annotation(VideoAnnotation(video="game-a"), source_dir / "game-a.json", metadata=metadata)
    queue = build_review_queue(
        [scored_video()],
        partition="val",
        threshold=0.65,
        merge_window_s=0.6,
        event_match_tolerance_s=0.75,
        empty_count=0,
    )
    item = next(item for item in queue["items"] if item["category"] == "unmatched_model_candidate")
    item["status"] = "reviewed"
    item["outcome"] = "confirmed_positive"
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    with pytest.raises(ReviewQueueError, match="needs a valid event_type"):
        apply_review_queue(
            queue_path,
            annotations_dir=source_dir,
            out_dir=tmp_path / "reviewed",
            reviewer="reviewer",
        )
