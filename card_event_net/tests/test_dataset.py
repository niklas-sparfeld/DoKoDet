from __future__ import annotations

import json
import random
from pathlib import Path

import cv2
import numpy as np
import torch

from cardevent.dataset import CausalClipDataset, DatasetSample
from cardevent.transforms import ClipTransform


def write_test_cache(cache_dir: Path) -> None:
    frames_dir = cache_dir / "frames"
    frames_dir.mkdir(parents=True)
    timestamps = [index / 10.0 for index in range(4)]
    for index in range(4):
        frame = np.full((224, 224, 3), index * 40, dtype=np.uint8)
        assert cv2.imwrite(str(frames_dir / f"{index:06d}.jpg"), frame)
    (cache_dir / "metadata.json").write_text(
        json.dumps(
            {
                "source_video": "sample.mov",
                "cache_fps": 10.0,
                "duration_s": 0.3,
                "frame_timestamps_s": timestamps,
                "frame_size": 224,
            }
        ),
        encoding="utf-8",
    )


def test_dataset_returns_causal_clip_shape_and_float_label(tmp_path: Path) -> None:
    cache_dir = tmp_path / "sample"
    write_test_cache(cache_dir)
    dataset = CausalClipDataset(
        [
            DatasetSample(
                source_video="sample.mov",
                cache_dir=cache_dir,
                decision_time_s=0.15,
                label=1.0,
            )
        ]
    )

    clip, label = dataset[0]

    assert tuple(clip.shape) == (8, 3, 224, 224)
    assert clip.dtype == torch.float32
    assert label.shape == ()
    assert label.dtype == torch.float32
    assert label.item() == 1.0


def test_training_transform_uses_one_configuration_for_all_frames() -> None:
    clip = torch.full((8, 3, 16, 16), 0.5)
    transform = ClipTransform(training=True, rng=random.Random(7))

    transformed = transform(clip)

    assert tuple(transformed.shape) == (8, 3, 16, 16)
    assert torch.equal(transformed[0], transformed[-1])
