from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from cardevent import infer_from_files, load_cache_metadata
from cardevent.cache import FULL_FRAME_LETTERBOX_V1


def test_infer_from_files_prepares_missing_cache_without_annotation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video_path = tmp_path / "accepted-recording.mov"
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10.0,
        (32, 24),
    )
    if not writer.isOpened():
        pytest.skip("OpenCV cannot create the test video with MJPG.")
    for value in range(4):
        frame = np.full((24, 32, 3), value * 20, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    loaded = SimpleNamespace(
        config=SimpleNamespace(
            input=SimpleNamespace(
                cache_fps=10.0,
                size=224,
                preprocessing=FULL_FRAME_LETTERBOX_V1,
            ),
            inference=SimpleNamespace(merge_window_s=0.6),
        ),
        device="cpu",
    )
    infer_module = importlib.import_module("cardevent.infer")
    observed: dict[str, object] = {}
    monkeypatch.setattr(infer_module, "load_checkpoint", lambda *_args, **_kwargs: loaded)

    def fake_infer_cached_video(_loaded, cache_path, **_kwargs):
        observed["metadata"] = load_cache_metadata(cache_path)
        return []

    monkeypatch.setattr(infer_module, "infer_cached_video", fake_infer_cached_video)

    progress: list[tuple[int, int]] = []
    payload = infer_from_files(
        "unused-checkpoint.pt",
        video_path,
        out_path=tmp_path / "predictions.json",
        cache_dir=tmp_path / "cache",
        progress_callback=lambda current, total: progress.append((current, total)),
    )

    metadata = observed["metadata"]
    assert metadata.source_video == video_path.name
    assert metadata.cache_fps == 10.0
    assert metadata.frame_size == 224
    assert payload["probabilities"] == []
    assert progress[0] == (0, 4)
    assert progress[-1] == (4, 4)
    assert all(total == 4 for _, total in progress)
