from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from table_evidence_analyzer.dinov3_training import (
    DinoV3TrainingError,
    _apply_source_augmentation,
)
from table_evidence_analyzer.local_identity import DINOV3_AUGMENTATION_CONFIG


def _image_and_mask() -> tuple[bytes, bytes]:
    image = Image.new("RGB", (80, 60), (128, 128, 128))
    for x in range(18, 62):
        for y in range(12, 48):
            image.putpixel((x, y), (220, 25, 20) if x < 40 else (20, 20, 20))
    image_buffer = BytesIO()
    image.save(image_buffer, format="PPM")
    mask = Image.new("L", image.size, 0)
    for x in range(18, 62):
        for y in range(12, 48):
            mask.putpixel((x, y), 255)
    mask_buffer = BytesIO()
    mask.save(mask_buffer, format="PNG")
    return image_buffer.getvalue(), mask_buffer.getvalue()


def test_source_augmentation_replays_and_keeps_image_mask_aligned() -> None:
    image_bytes, mask_bytes = _image_and_mask()
    kwargs = {
        "visible_mask_bytes": mask_bytes,
        "seed": 17,
        "sample_id": "sample-a",
    }
    first = _apply_source_augmentation(image_bytes, epoch=0, **kwargs)
    replay = _apply_source_augmentation(image_bytes, epoch=0, **kwargs)
    next_epoch = _apply_source_augmentation(image_bytes, epoch=1, **kwargs)

    with Image.open(BytesIO(first[0])) as augmented, Image.open(BytesIO(first[1])) as mask:
        assert augmented.size == mask.size
        assert mask.getbbox() is not None
        assert augmented.getbbox() is not None
    assert first == replay
    assert first != next_epoch
    assert DINOV3_AUGMENTATION_CONFIG["mirror"] is False
    assert DINOV3_AUGMENTATION_CONFIG["operations"]["rotation_degrees"] == [-15.0, 15.0]


def test_source_augmentation_rejects_invalid_visible_masks() -> None:
    image = Image.new("RGB", (16, 16), (128, 128, 128))
    image_buffer = BytesIO()
    image.save(image_buffer, format="PPM")
    mismatched = Image.new("L", (8, 8), 255)
    mask_buffer = BytesIO()
    mismatched.save(mask_buffer, format="PNG")
    with pytest.raises(DinoV3TrainingError, match="sizes differ"):
        _apply_source_augmentation(
            image_buffer.getvalue(),
            visible_mask_bytes=mask_buffer.getvalue(),
            seed=1,
            epoch=0,
            sample_id="sample-a",
        )

    empty = Image.new("L", (16, 16), 0)
    mask_buffer = BytesIO()
    empty.save(mask_buffer, format="PNG")
    with pytest.raises(DinoV3TrainingError, match="no support"):
        _apply_source_augmentation(
            image_buffer.getvalue(),
            visible_mask_bytes=mask_buffer.getvalue(),
            seed=1,
            epoch=0,
            sample_id="sample-a",
        )
