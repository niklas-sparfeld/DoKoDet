"""Bounded joint pose and order search for overlapping card proposals."""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from .card_plane_geometry import project_fixed_card


def _mask(
    calibration: Any, pose: dict[str, Any], width: int, height: int, scale: int
) -> np.ndarray:
    points = project_fixed_card(
        np.asarray(calibration.table_to_image),
        pose["center"],
        pose["angle"],
        calibration.card_short_size,
        calibration.card_long_size,
    )
    result = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(result, [np.rint(points / scale).astype(np.int32)], 255)
    return result


def _score(
    masks: dict[int, np.ndarray], full: dict[int, np.ndarray], order: tuple[int, ...]
) -> float:
    covered = np.zeros_like(next(iter(full.values())))
    scores = []
    for index in order:
        visible = full[index] & ~covered
        intersection = cv2.countNonZero(visible & masks[index])
        union = cv2.countNonZero(visible | masks[index])
        scores.append(intersection / max(union, 1))
        covered |= full[index]
    return sum(scores) / len(scores)


def _edge_score(
    source: np.ndarray, full: np.ndarray, occluder: np.ndarray
) -> tuple[float, float] | None:
    kernel = np.ones((3, 3), np.uint8)
    grown = cv2.dilate(occluder, np.ones((17, 17), np.uint8))
    source_edge = cv2.subtract(source, cv2.erode(source, kernel)) & ~grown
    predicted_edge = cv2.subtract(full, cv2.erode(full, kernel)) & ~grown
    if cv2.countNonZero(source_edge) < 8 or cv2.countNonZero(predicted_edge) < 8:
        return None
    a = cv2.distanceTransform(cv2.bitwise_not(predicted_edge), cv2.DIST_L2, 3)
    b = cv2.distanceTransform(cv2.bitwise_not(source_edge), cv2.DIST_L2, 3)
    edge = (
        1.0
        - (
            float(np.mean(np.minimum(a[source_edge > 0], 12)))
            + float(np.mean(np.minimum(b[predicted_edge > 0], 12)))
        )
        / 24.0
    )
    visible = full & ~occluder
    intersection = cv2.countNonZero(visible & source)
    overlap = intersection / max(cv2.countNonZero(visible | source), 1)
    return edge, overlap


def search_joint_scene(
    calibration: Any, candidates: list[Any], order: tuple[str, ...]
) -> dict[str, Any]:
    """Search overlapping cards with a width-three beam and refine selected visible edges.

    Input masks use source pixels. The joint search uses 1/8 resolution. Edge refinement uses
    1/4 resolution, a 32 source-pixel occlusion margin and one-degree angle steps.
    """
    if not candidates:
        return {"order": [], "poses": {}, "score": None, "margin": None}
    if len(candidates) > 8:
        return {
            "order": list(order),
            "poses": {},
            "score": None,
            "margin": None,
            "status": "skipped_card_limit",
            "maximum_cards": 8,
        }
    height, width = candidates[0].candidate.source_mask.shape
    ids = [item.pose.card_id for item in candidates]
    indices = {card_id: index for index, card_id in enumerate(ids)}
    original = {
        i: {"center": list(item.pose.center), "angle": item.pose.rotation_degrees}
        for i, item in enumerate(candidates)
    }
    small_w, small_h = (width + 7) // 8, (height + 7) // 8
    masks = {
        i: cv2.resize(
            item.candidate.source_mask, (small_w, small_h), interpolation=cv2.INTER_NEAREST
        )
        for i, item in enumerate(candidates)
    }
    full = {i: _mask(calibration, pose, small_w, small_h, 8) for i, pose in original.items()}
    saved = tuple(indices[item] for item in order)
    base = _score(masks, full, saved)
    connected = {
        i for i in full if any(i != j and cv2.countNonZero(full[i] & full[j]) >= 4 for j in full)
    }
    variants: dict[int, list[tuple[dict[str, Any], np.ndarray, tuple[float, float, float]]]] = {}
    for i in connected:
        pose = original[i]
        choices = []
        for turn in (0, 90):
            angle = pose["angle"] + turn
            radians = math.radians(angle)
            short = np.array([math.cos(radians), math.sin(radians)]) * calibration.card_short_size
            long = np.array([-math.sin(radians), math.cos(radians)]) * calibration.card_long_size
            for sx in (-0.5, -0.25, 0.0, 0.25, 0.5):
                for ly in (-0.5, -0.25, 0.0, 0.25, 0.5):
                    if turn == 0 and sx == 0 and ly == 0:
                        continue
                    center = (np.asarray(pose["center"]) + sx * short + ly * long).tolist()
                    candidate = {"center": center, "angle": angle}
                    choices.append(
                        (
                            candidate,
                            _mask(calibration, candidate, small_w, small_h, 8),
                            (turn, sx, ly),
                        )
                    )
        variants[i] = choices
    beam = [(base, saved, {}, full, {})]
    for _ in range(2):
        pool = list(beam)
        for _, current_order, changed, current_full, desc in beam:
            for i in sorted(connected - set(changed)):
                for pose, card_mask, variant in variants[i]:
                    trial = {**current_full, i: card_mask}
                    orders = [current_order]
                    for j in range(len(current_order) - 1):
                        if (
                            cv2.countNonZero(trial[current_order[j]] & trial[current_order[j + 1]])
                            >= 4
                        ):
                            orders.append(
                                current_order[:j]
                                + (current_order[j + 1], current_order[j])
                                + current_order[j + 2 :]
                            )
                    for alternative in orders:
                        pool.append(
                            (
                                _score(masks, trial, alternative),
                                alternative,
                                {**changed, i: pose},
                                trial,
                                {**desc, i: variant},
                            )
                        )
        pool.sort(key=lambda entry: -entry[0])
        seen = set()
        beam = []
        for entry in pool:
            key = (entry[1], tuple(sorted(entry[4].items())))
            if key not in seen:
                seen.add(key)
                beam.append(entry)
            if len(beam) == 3:
                break
    score, chosen_order, chosen, _, _ = beam[0]
    refined = dict(chosen)
    quarter_w, quarter_h = (width + 3) // 4, (height + 3) // 4
    poses = {**original, **chosen}
    quarter_full = {
        i: _mask(calibration, pose, quarter_w, quarter_h, 4) for i, pose in poses.items()
    }
    for i in chosen_order:
        if i not in chosen:
            continue
        occluder = np.zeros((quarter_h, quarter_w), np.uint8)
        for front in chosen_order:
            if front == i:
                break
            occluder |= quarter_full[front]
        if not cv2.countNonZero(occluder):
            continue
        source = cv2.resize(
            candidates[i].candidate.source_mask,
            (quarter_w, quarter_h),
            interpolation=cv2.INTER_NEAREST,
        )
        seed = chosen[i]
        radians = math.radians(seed["angle"])
        short = np.array([math.cos(radians), math.sin(radians)]) * calibration.card_short_size
        long = np.array([-math.sin(radians), math.cos(radians)]) * calibration.card_long_size
        center = np.asarray(seed["center"])
        best = None
        for angle_delta in range(-2, 10):
            for sx in np.linspace(-0.2, 0.2, 17):
                for ly in np.linspace(-0.2, 0.2, 17):
                    trial = {
                        "center": (center + sx * short + ly * long).tolist(),
                        "angle": seed["angle"] + angle_delta,
                    }
                    card_mask = _mask(calibration, trial, quarter_w, quarter_h, 4)
                    metrics = _edge_score(source, card_mask, occluder)
                    if metrics is None:
                        continue
                    value = sum(metrics) / 2
                    if best is None or value > best[0]:
                        best = (value, trial, card_mask)
        if best is not None:
            refined[i] = best[1]
            quarter_full[i] = best[2]
    final_full = {
        i: _mask(calibration, refined.get(i, original[i]), small_w, small_h, 8) for i in original
    }
    final_score = _score(masks, final_full, chosen_order)
    if final_score < base:
        refined = {}
        chosen_order = saved
        final_score = base
    return {
        "order": [ids[i] for i in chosen_order],
        "poses": {ids[i]: pose for i, pose in refined.items()},
        "score": final_score,
        "beam_score_before_edge_refinement": score,
        "baseline_score": base,
        "margin": score - beam[1][0] if len(beam) > 1 else None,
        "margin_stage": "beam_before_edge_refinement",
        "status": "complete",
    }
