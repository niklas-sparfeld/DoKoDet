"""Deterministic output comparisons for Epic 0103 model exports."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from PIL import Image, ImageChops, ImageDraw


def within_tolerance(left: float, right: float, *, atol: float, rtol: float) -> bool:
    """Return whether two finite numbers meet the frozen absolute and relative tolerance."""

    if not all(math.isfinite(value) for value in (left, right, atol, rtol)):
        return False
    if atol < 0 or rtol < 0:
        raise ValueError("comparison tolerances must be non-negative")
    return abs(left - right) <= atol + rtol * abs(right)


def ranked_indices(scores: Sequence[float]) -> tuple[int, ...]:
    """Return score ranks with stable index ordering for ties."""

    if not all(math.isfinite(score) for score in scores):
        raise ValueError("scores must be finite")
    return tuple(sorted(range(len(scores)), key=lambda index: (-scores[index], index)))


def compare_score_vectors(
    reference: Sequence[float],
    candidate: Sequence[float],
    *,
    atol: float,
    rtol: float,
) -> dict[str, Any]:
    """Compare same-class scores and ranks for one fixed-size model output."""

    if len(reference) != len(candidate) or not reference:
        raise ValueError("score vectors must have the same non-zero length")
    if not all(math.isfinite(value) for value in (*reference, *candidate)):
        raise ValueError("scores must be finite")
    if atol < 0 or rtol < 0:
        raise ValueError("comparison tolerances must be non-negative")
    differences = [abs(left - right) for left, right in zip(reference, candidate, strict=True)]
    mismatches = [
        index
        for index, (left, right) in enumerate(zip(reference, candidate, strict=True))
        if not within_tolerance(left, right, atol=atol, rtol=rtol)
    ]
    reference_rank = ranked_indices(reference)
    candidate_rank = ranked_indices(candidate)
    return {
        "class_count": len(reference),
        "max_absolute_difference": max(differences),
        "mismatched_indices": mismatches,
        "reference_rank": list(reference_rank),
        "candidate_rank": list(candidate_rank),
        "rank_changed": reference_rank != candidate_rank,
    }


def threshold_decision(score: float, threshold: float) -> bool:
    """Apply the model contract's inclusive score threshold."""

    if not math.isfinite(score) or not math.isfinite(threshold):
        raise ValueError("score and threshold must be finite")
    return score >= threshold


def polygon_iou(
    left: Sequence[Mapping[str, float]],
    right: Sequence[Mapping[str, float]],
    *,
    width: int = 1000,
    height: int = 1000,
) -> float:
    """Return raster mask IoU for two polygons in 0–1000 normalized coordinates."""

    if width <= 0 or height <= 0:
        raise ValueError("mask dimensions must be positive")
    left_mask = _polygon_mask(left, width=width, height=height)
    right_mask = _polygon_mask(right, width=width, height=height)
    intersection = ImageChops.logical_and(left_mask, right_mask).histogram()[255]
    union = ImageChops.logical_or(left_mask, right_mask).histogram()[255]
    return intersection / union if union else 1.0


def match_detections(
    reference: Sequence[Mapping[str, Any]],
    candidate: Sequence[Mapping[str, Any]],
    *,
    min_mask_iou: float = 0.5,
) -> dict[str, Any]:
    """Greedily match same-class masks by descending IoU and report unmatched items."""

    if not 0 <= min_mask_iou <= 1:
        raise ValueError("min_mask_iou must be in [0, 1]")
    pairs = []
    for reference_index, left in enumerate(reference):
        for candidate_index, right in enumerate(candidate):
            if left.get("class_id") != right.get("class_id"):
                continue
            iou = polygon_iou(left["visible_polygon"], right["visible_polygon"])
            if iou >= min_mask_iou:
                pairs.append((iou, reference_index, candidate_index))
    pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
    used_reference: set[int] = set()
    used_candidate: set[int] = set()
    matches = []
    for iou, reference_index, candidate_index in pairs:
        if reference_index in used_reference or candidate_index in used_candidate:
            continue
        used_reference.add(reference_index)
        used_candidate.add(candidate_index)
        matches.append(
            {
                "reference_index": reference_index,
                "candidate_index": candidate_index,
                "mask_iou": iou,
            }
        )
    return {
        "matches": matches,
        "unmatched_reference": [
            index for index in range(len(reference)) if index not in used_reference
        ],
        "unmatched_candidate": [
            index for index in range(len(candidate)) if index not in used_candidate
        ],
    }


def _polygon_mask(
    polygon: Sequence[Mapping[str, float]], *, width: int, height: int
) -> Image.Image:
    if len(polygon) < 3:
        raise ValueError("a mask polygon needs at least three points")
    points = []
    for point in polygon:
        x = float(point["x"])
        y = float(point["y"])
        if not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= 1000 or not 0 <= y <= 1000:
            raise ValueError("mask points must use finite 0–1000 coordinates")
        points.append((round(x * (width - 1) / 1000), round(y * (height - 1) / 1000)))
    image = Image.new("1", (width, height), 0)
    ImageDraw.Draw(image).polygon(points, fill=1)
    return image
