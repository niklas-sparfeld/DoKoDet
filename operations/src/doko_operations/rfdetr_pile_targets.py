"""Deterministic pixel ownership and COCO RLE for reviewed pile targets."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np


class RfdetrPileTargetError(ValueError):
    """A reviewed pile target cannot be projected without losing evidence."""


def project_pile_masks(
    card_targets: Sequence[Mapping[str, Any]],
    pile_targets: Sequence[Mapping[str, Any]],
    *,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    """Return pile COCO targets after assigning reviewed card pixels to cards.

    Polygon coordinates use ``full-frame-0-1000/v1``. Rasterization tests pixel centers,
    applies even-odd fill to each polygon, and unions disjoint polygons. The output uses
    uncompressed COCO RLE in column-major order so holes and separated pieces remain exact.
    """

    if width <= 0 or height <= 0:
        raise RfdetrPileTargetError("frame dimensions must be positive")
    card_union = np.zeros((height, width), dtype=np.bool_)
    for index, target in enumerate(card_targets):
        card_union |= _target_mask(target, width, height, f"card target {index}")

    masks: list[tuple[str, np.ndarray, str, Mapping[str, Any]]] = []
    for index, target in enumerate(pile_targets):
        pile_id = target.get("pile_id")
        if not isinstance(pile_id, str) or not pile_id:
            raise RfdetrPileTargetError(f"pile target {index} has no pile_id")
        geometry = target.get("geometry")
        if not isinstance(geometry, Mapping) or geometry.get("kind") != "pile-region/v1":
            raise RfdetrPileTargetError(f"pile {pile_id} has unsupported geometry")
        polygons = geometry.get("polygons")
        mask = _polygons_mask(polygons, width, height, f"pile {pile_id}")
        geometry_digest = hashlib.sha256(_canonical(geometry)).hexdigest()
        masks.append((pile_id, mask, geometry_digest, target))

    for index, (pile_id, mask, _, _) in enumerate(masks):
        for other_id, other_mask, _, _ in masks[index + 1 :]:
            if np.any(mask & other_mask):
                raise RfdetrPileTargetError(
                    f"pile targets {pile_id} and {other_id} intersect; "
                    "correct the reviewed footprints"
                )

    projected: list[dict[str, Any]] = []
    for pile_id, original_mask, geometry_digest, source in masks:
        owned = original_mask & ~card_union
        if not np.any(owned):
            raise RfdetrPileTargetError(
                f"pile {pile_id} has an empty effective footprint after card pixel ownership"
            )
        ys, xs = np.nonzero(owned)
        x_min, x_max = int(xs.min()), int(xs.max())
        y_min, y_max = int(ys.min()), int(ys.max())
        projected.append(
            {
                "pile_id": pile_id,
                "geometry": dict(source["geometry"]),
                "geometry_sha256": geometry_digest,
                "segmentation": _uncompressed_rle(owned),
                "area": int(owned.sum()),
                "bbox": [x_min, y_min, x_max - x_min + 1, y_max - y_min + 1],
                "pixel_ownership": {
                    "policy": "reviewed-card-pixels-priority-v1",
                    "card_pixels_removed": int(np.count_nonzero(original_mask & card_union)),
                },
                "source_candidates": source.get("source_candidates", []),
                "grouped_candidates": source.get("grouped_candidates", []),
            }
        )
    return projected


def decode_uncompressed_rle(rle: Mapping[str, Any]) -> np.ndarray:
    """Decode the uncompressed COCO RLE subset emitted by this module."""

    size = rle.get("size")
    counts = rle.get("counts")
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in size)
        or not isinstance(counts, list)
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in counts)
    ):
        raise RfdetrPileTargetError("COCO RLE has invalid size or counts")
    total = size[0] * size[1]
    if sum(counts) != total:
        raise RfdetrPileTargetError("COCO RLE counts do not match its dimensions")
    flat = np.zeros(total, dtype=np.bool_)
    offset = 0
    value = False
    for count in counts:
        if value:
            flat[offset : offset + count] = True
        offset += count
        value = not value
    return flat.reshape((size[0], size[1]), order="F")


def _target_mask(target: Mapping[str, Any], width: int, height: int, context: str) -> np.ndarray:
    geometry = target.get("geometry")
    if not isinstance(geometry, Mapping) or geometry.get("kind") not in {
        "visible-region/v1",
        "reviewed-visible-region/v1",
    }:
        raise RfdetrPileTargetError(f"{context} has unsupported geometry")
    visible_region = geometry.get("visible_region")
    polygons = visible_region.get("polygons") if isinstance(visible_region, Mapping) else None
    return _polygons_mask(polygons, width, height, context)


def _polygons_mask(raw: Any, width: int, height: int, context: str) -> np.ndarray:
    if not isinstance(raw, list) or not raw:
        raise RfdetrPileTargetError(f"{context} must contain at least one polygon")
    result = np.zeros((height, width), dtype=np.bool_)
    x_centers = np.arange(width, dtype=np.float64) + 0.5
    for polygon_index, polygon in enumerate(raw):
        if not isinstance(polygon, list) or len(polygon) < 3:
            raise RfdetrPileTargetError(
                f"{context} polygon {polygon_index} has fewer than 3 points"
            )
        points: list[tuple[float, float]] = []
        for point in polygon:
            if not isinstance(point, Mapping):
                raise RfdetrPileTargetError(f"{context} polygon point must be an object")
            x, y = point.get("x"), point.get("y")
            if (
                isinstance(x, bool)
                or not isinstance(x, int)
                or isinstance(y, bool)
                or not isinstance(y, int)
                or not 0 <= x <= 1000
                or not 0 <= y <= 1000
            ):
                raise RfdetrPileTargetError(f"{context} polygon points must be integers in 0..1000")
            points.append((x * width / 1000.0, y * height / 1000.0))
        min_y = max(0, math.floor(min(point[1] for point in points) - 0.5))
        max_y = min(height, math.ceil(max(point[1] for point in points) - 0.5) + 1)
        for row in range(min_y, max_y):
            y_center = row + 0.5
            intersections: list[float] = []
            for edge in range(len(points)):
                x1, y1 = points[edge]
                x2, y2 = points[(edge + 1) % len(points)]
                if (y1 <= y_center < y2) or (y2 <= y_center < y1):
                    intersections.append(x1 + (y_center - y1) * (x2 - x1) / (y2 - y1))
            intersections.sort()
            inside = np.zeros(width, dtype=np.bool_)
            for index in range(0, len(intersections) - 1, 2):
                inside |= (x_centers >= intersections[index]) & (
                    x_centers < intersections[index + 1]
                )
            result[row] |= inside
    if not np.any(result):
        raise RfdetrPileTargetError(f"{context} has an empty rasterized footprint")
    return result


def _uncompressed_rle(mask: np.ndarray) -> dict[str, Any]:
    flat = mask.reshape(-1, order="F")
    counts: list[int] = []
    last = False
    run = 0
    for value in flat:
        current = bool(value)
        if current == last:
            run += 1
        else:
            counts.append(run)
            run = 1
            last = current
    counts.append(run)
    return {"size": [int(mask.shape[0]), int(mask.shape[1])], "counts": counts}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
