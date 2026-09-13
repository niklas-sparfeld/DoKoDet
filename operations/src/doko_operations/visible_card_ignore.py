"""Deterministic raster helpers for reviewed visible-card ignore regions."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from table_evidence_analyzer.pipeline_data import (
    DetectorBoxGeometry,
    PredictedVisibleRegionGeometry,
    ReviewedIgnoreRegionGeometry,
    ReviewedVisibleRegionGeometry,
)

IgnoreGeometry = (
    DetectorBoxGeometry
    | PredictedVisibleRegionGeometry
    | ReviewedVisibleRegionGeometry
    | ReviewedIgnoreRegionGeometry
)
Point = tuple[int, int]
Polygon = tuple[Point, ...]


def geometry_polygons(geometry: IgnoreGeometry) -> tuple[Polygon, ...]:
    """Return normalized polygons for a supported card or ignore geometry."""

    if isinstance(geometry, DetectorBoxGeometry):
        return (
            (
                (geometry.x_min, geometry.y_min),
                (geometry.x_max, geometry.y_min),
                (geometry.x_max, geometry.y_max),
                (geometry.x_min, geometry.y_max),
            ),
        )
    if isinstance(
        geometry,
        (
            PredictedVisibleRegionGeometry,
            ReviewedVisibleRegionGeometry,
            ReviewedIgnoreRegionGeometry,
        ),
    ):
        return geometry.polygons
    raise TypeError("geometry is not supported by the visible-card raster policy")


def geometry_bounds(geometry: IgnoreGeometry) -> tuple[int, int, int, int]:
    """Return the normalized bounding box of one geometry."""

    points = [point for polygon in geometry_polygons(geometry) for point in polygon]
    if not points:
        raise ValueError("geometry must contain at least one point")
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def rasterize_geometry(geometry: IgnoreGeometry, *, width: int, height: int) -> bytearray:
    """Rasterize one normalized geometry with exact pixel-center even-odd rules."""

    if width <= 0 or height <= 0:
        raise ValueError("raster dimensions must be positive")
    polygons = geometry_polygons(geometry)
    x_min, y_min, x_max, y_max = geometry_bounds(geometry)
    start_x = max(0, int(x_min * width / 1000) - 1)
    end_x = min(width - 1, int(x_max * width / 1000) + 1)
    start_y = max(0, int(y_min * height / 1000) - 1)
    end_y = min(height - 1, int(y_max * height / 1000) + 1)
    result = bytearray(width * height)
    for y in range(start_y, end_y + 1):
        y_num = 1000 * (2 * y + 1)
        y_den = 2 * height
        for x in range(start_x, end_x + 1):
            x_num = 1000 * (2 * x + 1)
            x_den = 2 * width
            if any(_point_in_polygon(x_num, x_den, y_num, y_den, polygon) for polygon in polygons):
                result[y * width + x] = 1
    return result


def union_masks(masks: Sequence[bytearray], *, size: int) -> bytearray:
    """Return the union of row-major byte masks."""

    result = bytearray(size)
    for mask in masks:
        if len(mask) != size:
            raise ValueError("mask dimensions do not match")
        for index, value in enumerate(mask):
            result[index] |= value
    return result


def subtract_mask(mask: bytearray, subtract: bytearray) -> bytearray:
    """Remove every set pixel in ``subtract`` from ``mask``."""

    if len(mask) != len(subtract):
        raise ValueError("mask dimensions do not match")
    return bytearray(value and not subtract[index] for index, value in enumerate(mask))


def pack_mask(mask: bytearray) -> bytes:
    """Pack a row-major byte mask into a stable least-significant-bit bitset."""

    packed = bytearray((len(mask) + 7) // 8)
    for index, value in enumerate(mask):
        if value:
            packed[index // 8] |= 1 << (index % 8)
    return bytes(packed)


def mask_digest(mask: bytearray) -> str:
    """Return the SHA-256 digest of the canonical packed mask bytes."""

    return hashlib.sha256(pack_mask(mask)).hexdigest()


def mask_count(mask: bytearray) -> int:
    """Count set pixels in a row-major byte mask."""

    return sum(1 for value in mask if value)


def _point_in_polygon(
    x_num: int,
    x_den: int,
    y_num: int,
    y_den: int,
    polygon: Polygon,
) -> bool:
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % len(polygon)]
        if _point_on_segment(x_num, x_den, y_num, y_den, x1, y1, x2, y2):
            return True
        first_above = y1 * y_den > y_num
        second_above = y2 * y_den > y_num
        if first_above == second_above:
            continue
        dy = y2 - y1
        intersection_num = x1 * dy * y_den + (y_num - y1 * y_den) * (x2 - x1)
        intersection_den = dy * y_den
        left = x_num * intersection_den
        right = intersection_num * x_den
        crosses = left < right if intersection_den > 0 else left > right
        if crosses:
            inside = not inside
    return inside


def _point_on_segment(
    x_num: int,
    x_den: int,
    y_num: int,
    y_den: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> bool:
    cross = (x_num - x1 * x_den) * (y2 - y1) * y_den - (y_num - y1 * y_den) * (x2 - x1) * x_den
    if cross != 0:
        return False
    x_first = x_num - x1 * x_den
    x_second = x_num - x2 * x_den
    y_first = y_num - y1 * y_den
    y_second = y_num - y2 * y_den
    return x_first * x_second <= 0 and y_first * y_second <= 0


__all__ = [
    "geometry_bounds",
    "geometry_polygons",
    "mask_count",
    "mask_digest",
    "pack_mask",
    "rasterize_geometry",
    "subtract_mask",
    "union_masks",
]
