from __future__ import annotations

import json
import random
from pathlib import Path

import cv2
import numpy as np
import pytest
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
    assert clip.dtype == torch.uint8
    assert clip[0].min().item() == 0
    assert clip[-1].max().item() == 40
    assert label.shape == ()
    assert label.dtype == torch.float32
    assert label.item() == 1.0


def test_dataset_preserves_rgb_channel_order_without_normalization(tmp_path: Path) -> None:
    cache_dir = tmp_path / "sample"
    write_test_cache(cache_dir)
    frames_dir = cache_dir / "frames"
    red_bgr = np.zeros((224, 224, 3), dtype=np.uint8)
    red_bgr[..., 2] = 255
    assert cv2.imwrite(str(frames_dir / "000000.jpg"), red_bgr)
    dataset = CausalClipDataset(
        [
            DatasetSample(
                source_video="sample.mov",
                cache_dir=cache_dir,
                decision_time_s=0.0,
                label=0.0,
            )
        ]
    )

    clip, _ = dataset[0]

    assert clip.dtype == torch.uint8
    assert clip[0, 0].float().mean() > 250
    assert clip[0, 2].float().mean() < 5


def test_evaluation_transform_normalizes_uint8_clips_and_batches() -> None:
    transform = ClipTransform(training=False)
    clip = torch.full((8, 3, 16, 16), 255, dtype=torch.uint8)
    batch = torch.stack((clip, torch.zeros_like(clip)))
    expected_white = torch.tensor(
        [(1.0 - 0.485) / 0.229, (1.0 - 0.456) / 0.224, (1.0 - 0.406) / 0.225]
    )

    transformed_clip = transform(clip)
    transformed_batch = transform(batch)

    assert transformed_clip.dtype == torch.float32
    assert tuple(transformed_clip.shape) == tuple(clip.shape)
    assert torch.allclose(transformed_clip[:, :, 0, 0], expected_white.expand(8, -1))
    assert transformed_batch.dtype == torch.float32
    assert tuple(transformed_batch.shape) == tuple(batch.shape)
    assert torch.allclose(transformed_batch[0, :, :, 0, 0], expected_white.expand(8, -1))
    assert torch.allclose(
        transformed_batch[1, :, :, 0, 0],
        torch.tensor([[-0.485 / 0.229, -0.456 / 0.224, -0.406 / 0.225]]).expand(8, -1),
    )


def test_training_transform_uses_one_configuration_for_all_frames() -> None:
    clip = torch.full((8, 3, 16, 16), 128, dtype=torch.uint8)
    transform = ClipTransform(training=True, rng=random.Random(7))

    transformed = transform(clip)

    assert tuple(transformed.shape) == (8, 3, 16, 16)
    assert torch.equal(transformed[0], transformed[-1])


def test_training_transform_uses_independent_configuration_per_batch_clip() -> None:
    clip = torch.full((8, 3, 16, 16), 128, dtype=torch.uint8)
    transform = ClipTransform(
        training=True,
        horizontal_flip_p=0.0,
        contrast_jitter=0.0,
        saturation_jitter=0.0,
        hue_jitter=0.0,
        blur_p=0.0,
        rng=random.Random(7),
    )

    transformed = transform(torch.stack((clip, clip)))

    assert transformed.is_contiguous()
    assert torch.equal(transformed[0, 0], transformed[0, -1])
    assert torch.equal(transformed[1, 0], transformed[1, -1])
    assert not torch.equal(transformed[0], transformed[1])


def test_training_transform_returns_contiguous_mps_batch() -> None:
    if not torch.backends.mps.is_available():
        pytest.skip("MPS is not available")

    clip = torch.full((2, 8, 3, 224, 224), 128, dtype=torch.uint8, device="mps")

    transformed = ClipTransform(training=True, rng=random.Random(0))(clip)

    assert transformed.is_contiguous()


@pytest.mark.parametrize("device_type", ("cuda", "mps"))
def test_evaluation_transform_keeps_available_accelerator_device(device_type: str) -> None:
    if device_type == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA is not available")
    if device_type == "mps" and not torch.backends.mps.is_available():
        pytest.skip("MPS is not available")

    device = torch.device(device_type)
    transformed = ClipTransform(training=False)(
        torch.full((2, 8, 3, 16, 16), 128, dtype=torch.uint8, device=device)
    )

    assert transformed.device == device
