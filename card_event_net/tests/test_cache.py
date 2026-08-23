from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

from cardevent.cache import (
    FULL_FRAME_LETTERBOX_V1,
    CacheError,
    _full_frame_letterbox,
    cache_is_usable,
    extract_video_cache,
    load_cache_metadata,
    require_cache_preprocessing,
)
from cardevent.transforms import ClipTransform


def test_extract_video_cache_writes_full_frames_and_timestamps(tmp_path: Path) -> None:
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
    assert metadata.preprocessing == FULL_FRAME_LETTERBOX_V1
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
                "preprocessing": FULL_FRAME_LETTERBOX_V1,
            }
        ),
        encoding="utf-8",
    )
    (frames_dir / "000000.jpg").write_bytes(b"frame")

    assert not cache_is_usable(
        "sample.mov", cache_root=tmp_path / "cache", cache_fps=10.0, size=224
    )
    (frames_dir / "000001.jpg").write_bytes(b"frame")
    assert cache_is_usable("sample.mov", cache_root=tmp_path / "cache", cache_fps=10.0, size=224)
    assert not cache_is_usable("sample.mov", cache_root=tmp_path / "cache", cache_fps=5.0, size=224)


def test_legacy_cache_without_preprocessing_is_not_usable(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache" / "sample"
    frames_dir = cache_dir / "frames"
    frames_dir.mkdir(parents=True)
    (cache_dir / "metadata.json").write_text(
        json.dumps(
            {
                "source_video": "sample.mov",
                "cache_fps": 10.0,
                "duration_s": 0.0,
                "frame_timestamps_s": [0.0],
                "frame_size": 224,
            }
        ),
        encoding="utf-8",
    )
    (frames_dir / "000000.jpg").write_bytes(b"frame")

    assert not cache_is_usable(
        "sample.mov", cache_root=tmp_path / "cache", cache_fps=10.0, size=224
    )


def test_full_frame_letterbox_keeps_edge_content() -> None:
    frame = np.zeros((2, 4, 3), dtype=np.uint8)
    frame[:, 0] = (10, 20, 30)
    frame[:, -1] = (40, 50, 60)

    result = _full_frame_letterbox(frame, size=8, cv2=cv2)

    assert result.shape == (8, 8, 3)
    assert np.all(result[:2] == 0)
    assert np.all(result[6:] == 0)
    assert tuple(result[2, 0]) == (10, 20, 30)
    assert tuple(result[2, -1]) == (40, 50, 60)


def test_require_cache_preprocessing_rejects_mismatch(tmp_path: Path) -> None:
    cache_dir = tmp_path / "sample"
    cache_dir.mkdir()
    (cache_dir / "metadata.json").write_text(
        json.dumps(
            {
                "source_video": "sample.mov",
                "cache_fps": 10.0,
                "duration_s": 1.0,
                "frame_timestamps_s": [0.0],
                "frame_size": 224,
                "preprocessing": "roi_letterbox_v1",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CacheError, match="preprocessing mismatch"):
        require_cache_preprocessing(cache_dir, FULL_FRAME_LETTERBOX_V1)


def test_full_frame_preprocessing_fixture_has_expected_tensor() -> None:
    frame = np.zeros((2, 4, 3), dtype=np.uint8)
    frame[:, 0] = (10, 20, 30)
    letterboxed = _full_frame_letterbox(frame, size=8, cv2=cv2)
    rgb = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB)
    clip = torch.from_numpy(rgb).permute(2, 0, 1).repeat(8, 1, 1, 1)

    tensor = ClipTransform(training=False)(clip)

    expected_edge = torch.tensor(
        [
            (30 / 255 - 0.485) / 0.229,
            (20 / 255 - 0.456) / 0.224,
            (10 / 255 - 0.406) / 0.225,
        ]
    )
    expected_black = torch.tensor([-0.485 / 0.229, -0.456 / 0.224, -0.406 / 0.225])
    assert torch.allclose(tensor[0, :, 2, 0], expected_edge)
    assert torch.allclose(tensor[0, :, 0, 0], expected_black)
