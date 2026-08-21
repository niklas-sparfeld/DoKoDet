from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


class TransformError(ValueError):
    pass


@dataclass(slots=True)
class ClipTransform:
    """Apply one sampled image augmentation configuration to each clip."""

    training: bool = False
    horizontal_flip_p: float = 0.5
    brightness_jitter: float = 0.15
    contrast_jitter: float = 0.15
    saturation_jitter: float = 0.15
    hue_jitter: float = 0.02
    blur_p: float = 0.1
    rng: random.Random | None = None

    def __call__(self, clip: Any) -> Any:
        try:
            import torch
            import torchvision.transforms.functional as functional
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "PyTorch and torchvision are required for clip transforms. "
                "Run `uv sync` to install the project dependencies."
            ) from exc

        tensor = torch.as_tensor(clip)
        if tensor.ndim not in (4, 5):
            raise TransformError("A clip must have shape [T, C, H, W] or [B, T, C, H, W].")
        if tensor.shape[-3] != 3:
            raise TransformError("A clip must have three RGB channels.")
        if not tensor.is_floating_point():
            tensor = tensor.float().div(255.0)
        else:
            tensor = tensor.float()
            if tensor.numel() and float(tensor.max()) > 1.0:
                tensor = tensor.div(255.0)
        tensor = tensor.clamp(0.0, 1.0)

        if self.training:
            if tensor.ndim == 4:
                tensor = self._augment_clip(tensor, functional)
            else:
                tensor = torch.stack([self._augment_clip(sample, functional) for sample in tensor])

        shape = (1, 3, 1, 1) if tensor.ndim == 4 else (1, 1, 3, 1, 1)
        mean = tensor.new_tensor((0.485, 0.456, 0.406)).view(shape)
        std = tensor.new_tensor((0.229, 0.224, 0.225)).view(shape)
        return (tensor - mean) / std

    def _augment_clip(self, clip: Any, functional: Any) -> Any:
        """Augment all frames in one clip with one shared configuration."""
        rng = self.rng if self.rng is not None else random
        do_flip = rng.random() < self.horizontal_flip_p
        brightness = rng.uniform(
            max(0.0, 1.0 - self.brightness_jitter),
            1.0 + self.brightness_jitter,
        )
        contrast = rng.uniform(
            max(0.0, 1.0 - self.contrast_jitter),
            1.0 + self.contrast_jitter,
        )
        saturation = rng.uniform(
            max(0.0, 1.0 - self.saturation_jitter),
            1.0 + self.saturation_jitter,
        )
        hue = rng.uniform(-self.hue_jitter, self.hue_jitter)
        blur = rng.random() < self.blur_p

        if do_flip:
            clip = functional.hflip(clip)
        clip = functional.adjust_brightness(clip, brightness)
        clip = functional.adjust_contrast(clip, contrast)
        clip = functional.adjust_saturation(clip, saturation)
        if hue:
            clip = functional.adjust_hue(clip, hue)
        if blur:
            sigma = rng.uniform(0.1, 1.0)
            clip = functional.gaussian_blur(clip, kernel_size=[3, 3], sigma=[sigma, sigma])
        return clip
