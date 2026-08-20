from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from cardevent.video import VideoError, read_video_metadata


def test_read_video_metadata_reads_basic_properties(tmp_path: Path) -> None:
    path = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        15.0,
        (64, 48),
    )
    if not writer.isOpened():
        pytest.skip("OpenCV cannot create a test video with MJPG in this environment.")

    for value in (0, 60, 120):
        frame = np.full((48, 64, 3), value, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    metadata = read_video_metadata(path)

    assert metadata.path == path.resolve()
    assert metadata.width == 64
    assert metadata.height == 48
    assert metadata.fps == pytest.approx(15.0, rel=1e-3)
    assert metadata.frame_count == 3
    assert metadata.duration_s == pytest.approx(0.2, rel=1e-3)
    assert metadata.source_video == "sample.avi"


def test_read_video_metadata_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(VideoError, match="does not exist"):
        read_video_metadata(tmp_path / "missing.mov")
