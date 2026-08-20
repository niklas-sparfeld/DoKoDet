from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


class TransformError(ValueError):
    pass


@dataclass(slots=True)
class ClipTransform:
    """Apply one sampled image augmentation configuration to every clip frame."""

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
        if tensor.ndim != 4:
            raise TransformError("A clip must have shape [T, C, H, W].")
        if tensor.shape[1] != 3:
            raise TransformError("A clip must have three RGB channels.")
        if not tensor.is_floating_point():
            tensor = tensor.float().div(255.0)
        else:
            tensor = tensor.float()
            if tensor.numel() and float(tensor.max()) > 1.0:
                tensor = tensor.div(255.0)
        tensor = tensor.clamp(0.0, 1.0)

        if self.training:
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

            transformed_frames = []
            for frame in tensor:
                if do_flip:
                    frame = functional.hflip(frame)
                frame = functional.adjust_brightness(frame, brightness)
                frame = functional.adjust_contrast(frame, contrast)
                frame = functional.adjust_saturation(frame, saturation)
                if hue:
                    frame = functional.adjust_hue(frame, hue)
                if blur:
                    frame = functional.gaussian_blur(frame, kernel_size=[3, 3], sigma=[0.1, 1.0])
                transformed_frames.append(frame)
            tensor = torch.stack(transformed_frames)

        mean = tensor.new_tensor((0.485, 0.456, 0.406)).view(1, 3, 1, 1)
        std = tensor.new_tensor((0.229, 0.224, 0.225)).view(1, 3, 1, 1)
        return (tensor - mean) / std
