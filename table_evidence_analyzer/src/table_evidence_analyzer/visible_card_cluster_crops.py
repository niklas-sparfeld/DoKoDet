"""Image operations for deterministic visible-card cluster crops."""

from __future__ import annotations

import math
from typing import Any

from PIL import Image

from .visible_card_cluster_geometry import PixelBox


def crop_source_image(source: Image.Image, crop: Any) -> Image.Image:
    """Copy the in-frame part of a padded cluster square onto its neutral canvas."""

    canvas = Image.new("RGB", (crop.crop_width, crop.crop_height), crop.padding_color)
    source_box = crop.padded_square_box.intersection(
        PixelBox(0, 0, crop.source_width, crop.source_height)
    )
    if source_box is None:
        return canvas
    rectangle = (
        math.floor(source_box.x_min),
        math.floor(source_box.y_min),
        math.ceil(source_box.x_max),
        math.ceil(source_box.y_max),
    )
    piece = source.crop(rectangle)
    destination = (
        math.floor(source_box.x_min - crop.padded_square_box.x_min),
        math.floor(source_box.y_min - crop.padded_square_box.y_min),
    )
    canvas.paste(piece, destination)
    return canvas


__all__ = ["crop_source_image"]
