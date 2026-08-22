from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from cardevent.cache import cache_is_usable, extract_video_cache, load_cache_metadata


def test_extract_video_cache_writes_roi_frames_and_timestamps(tmp_path: Path) -> None:
    raw_dir = tmp_path / "data" / "raw"
    annotation_dir = tmp_path / "data" / "annotations"
    raw_dir.mkdir(parents=True)
    annotation_dir.mkdir()
    video_path = raw_dir / "sample.avi"

    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        20.0,
        (80, 60),
    )
    if not writer.isOpened():
        pytest.skip("OpenCV cannot create a test video with MJPG in this environment.")
    for value in range(6):
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        frame[:, :, 0] = value * 20
        writer.write(frame)
    writer.release()

    (annotation_dir / "sample.json").write_text(
        json.dumps(
            {
                "video": "sample.avi",
                "roi": {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
                "events": [],
            }
        ),
        encoding="utf-8",
    )

    progress: list[tuple[int, int]] = []
    cache_dir = extract_video_cache(
        video_path,
        cache_fps=10.0,
        size=32,
        progress_callback=lambda current, total: progress.append((current, total)),
    )
    metadata = load_cache_metadata(cache_dir)
    frames = sorted((cache_dir / "frames").glob("*.jpg"))

    assert metadata.source_video == "sample.avi"
    assert metadata.frame_size == 32
    assert metadata.frame_timestamps_s == pytest.approx((0.0, 0.1, 0.2))
    assert len(frames) == len(metadata.frame_timestamps_s)
    assert cv2.imread(str(frames[0])).shape == (32, 32, 3)
    assert progress[0] == (0, 6)
    assert progress[-1] == (6, 6)
    assert [current for current, _ in progress] == list(range(7))


def test_cache_is_usable_requires_matching_complete_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache" / "sample"
    frames_dir = cache_dir / "frames"
    frames_dir.mkdir(parents=True)
    (cache_dir / "metadata.json").write_text(
        json.dumps(
            {
                "source_video": "sample.mov",
                "cache_fps": 10.0,
                "duration_s": 0.1,
                "frame_timestamps_s": [0.0, 0.1],
                "frame_size": 224,
            }
        ),
        encoding="utf-8",
    )
    (frames_dir / "000000.jpg").write_bytes(b"frame")

    assert not cache_is_usable(
        "sample.mov", cache_root=tmp_path / "cache", cache_fps=10.0, size=224
    )
    (frames_dir / "000001.jpg").write_bytes(b"frame")
    assert cache_is_usable(
        "sample.mov", cache_root=tmp_path / "cache", cache_fps=10.0, size=224
    )
    assert not cache_is_usable(
        "sample.mov", cache_root=tmp_path / "cache", cache_fps=5.0, size=224
    )
