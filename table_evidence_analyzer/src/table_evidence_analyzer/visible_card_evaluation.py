"""Offline evaluation of visible-card polygon proposals against reviewed references."""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .visible_cards import (
    NormalizedPoint,
    VisibleCardError,
    load_run_artifact,
    normalize_prediction,
)

VISIBLE_CARD_REFERENCE_SCHEMA = "visible-card-reference/v1"
VISIBLE_CARD_EVALUATION_SCHEMA = "visible-card-evaluation/v1"
VISIBLE_CARD_REFERENCE_SIDES = ("face_up", "face_down", "unknown")


class VisibleCardEvaluationError(VisibleCardError):
    """Raised when visible-card evaluation inputs are invalid or incomplete."""


@dataclass(frozen=True, slots=True)
class ReferenceCard:
    """One reviewed visible physical card polygon."""

    card_id: str
    polygon: tuple[NormalizedPoint, ...]
    side: Literal["face_up", "face_down", "unknown"]
    usable_for_crop: bool

    def __post_init__(self) -> None:
        _require_identifier(self.card_id, "card_id")
        if len(self.polygon) < 3:
            raise VisibleCardEvaluationError("reference polygon needs at least three points")
        if self.side not in VISIBLE_CARD_REFERENCE_SIDES:
            raise VisibleCardEvaluationError("reference side is invalid")
        if not isinstance(self.usable_for_crop, bool):
            raise VisibleCardEvaluationError("usable_for_crop must be a boolean")
        if _polygon_area(self.polygon) <= 0.0:
            raise VisibleCardEvaluationError("reference polygon must have positive area")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "polygon": [point.to_mapping() for point in self.polygon],
            "side": self.side,
            "usable_for_crop": self.usable_for_crop,
        }


@dataclass(frozen=True, slots=True)
class VisibleCardReference:
    """Reviewed visible-card references for one provider request frame."""

    package_id: str
    frame_part_name: str
    target_offset_ms: int
    image_sha256: str
    cards: tuple[ReferenceCard, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.package_id, "package_id")
        _require_identifier(self.frame_part_name, "frame_part_name")
        if isinstance(self.target_offset_ms, bool) or not isinstance(self.target_offset_ms, int):
            raise VisibleCardEvaluationError("target_offset_ms must be an integer")
        if not isinstance(self.image_sha256, str) or len(self.image_sha256) != 64:
            raise VisibleCardEvaluationError("image_sha256 must be a SHA-256 digest")
        if any(character not in "0123456789abcdef" for character in self.image_sha256):
            raise VisibleCardEvaluationError("image_sha256 must be a lower-case SHA-256 digest")
        card_ids = [card.card_id for card in self.cards]
        if len(card_ids) != len(set(card_ids)):
            raise VisibleCardEvaluationError("reference card IDs must be unique")

    @property
    def key(self) -> tuple[str, str, int, str]:
        return self.package_id, self.frame_part_name, self.target_offset_ms, self.image_sha256

    def to_mapping(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "frame_part_name": self.frame_part_name,
            "target_offset_ms": self.target_offset_ms,
            "image_sha256": self.image_sha256,
            "cards": [card.to_mapping() for card in self.cards],
        }


@dataclass(frozen=True, slots=True)
class VisibleCardReferenceSet:
    """Strict collection of reviewed references used by one evaluation."""

    references: tuple[VisibleCardReference, ...]

    def __post_init__(self) -> None:
        keys = [reference.key for reference in self.references]
        if len(keys) != len(set(keys)):
            raise VisibleCardEvaluationError("visible-card references must be unique")

    def by_key(self) -> dict[tuple[str, str, int, str], VisibleCardReference]:
        return {reference.key: reference for reference in self.references}

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": VISIBLE_CARD_REFERENCE_SCHEMA,
            "references": [
                reference.to_mapping()
                for reference in sorted(self.references, key=lambda item: item.key)
            ],
        }


@dataclass(frozen=True, slots=True)
class VisibleCardEvaluationConfig:
    """Inputs for one deterministic visible-card proposal evaluation."""

    results: tuple[Path, ...]
    references: Path
    output: Path
    iou_threshold: float = 0.5

    def __post_init__(self) -> None:
        if not self.results:
            raise VisibleCardEvaluationError("at least one visible-card result is required")
        if not 0.0 < self.iou_threshold <= 1.0:
            raise VisibleCardEvaluationError("iou_threshold must be greater than 0 and at most 1")


def _require_identifier(value: Any, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
            for character in value
        )
    ):
        raise VisibleCardEvaluationError(f"{field} must be a simple non-empty identifier")


def _parse_reference_card(value: Any, index: int) -> ReferenceCard:
    if not isinstance(value, dict) or set(value) != {
        "card_id",
        "polygon",
        "side",
        "usable_for_crop",
    }:
        raise VisibleCardEvaluationError(f"reference card {index} has unexpected fields")
    polygon = value["polygon"]
    if not isinstance(polygon, list) or len(polygon) < 3:
        raise VisibleCardEvaluationError(f"reference card {index} polygon is invalid")
    points: list[NormalizedPoint] = []
    for point_index, point in enumerate(polygon):
        if not isinstance(point, dict) or set(point) != {"x", "y"}:
            raise VisibleCardEvaluationError(
                f"reference card {index} point {point_index} has unexpected fields"
            )
        try:
            points.append(NormalizedPoint(x=point["x"], y=point["y"]))
        except (TypeError, VisibleCardError) as error:
            raise VisibleCardEvaluationError(
                f"reference card {index} point {point_index} is invalid"
            ) from error
    try:
        return ReferenceCard(
            card_id=value["card_id"],
            polygon=tuple(points),
            side=value["side"],
            usable_for_crop=value["usable_for_crop"],
        )
    except (TypeError, VisibleCardError) as error:
        raise VisibleCardEvaluationError(f"reference card {index} is invalid") from error


def load_visible_card_references(path: str | Path) -> VisibleCardReferenceSet:
    """Load and strictly validate reviewed visible-card polygon references."""

    reference_path = Path(path)
    try:
        payload = json.loads(reference_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardEvaluationError(
            f"could not read visible-card references: {path}"
        ) from error
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "references"}:
        raise VisibleCardEvaluationError("visible-card reference set has unexpected fields")
    if payload["schema_version"] != VISIBLE_CARD_REFERENCE_SCHEMA:
        raise VisibleCardEvaluationError("unsupported visible-card reference schema")
    raw_references = payload["references"]
    if not isinstance(raw_references, list) or not raw_references:
        raise VisibleCardEvaluationError("visible-card references must be a non-empty list")
    references: list[VisibleCardReference] = []
    for index, value in enumerate(raw_references):
        fields = {"package_id", "frame_part_name", "target_offset_ms", "image_sha256", "cards"}
        if not isinstance(value, dict) or set(value) != fields:
            raise VisibleCardEvaluationError(f"reference {index} has unexpected fields")
        cards = value["cards"]
        if not isinstance(cards, list):
            raise VisibleCardEvaluationError(f"reference {index} cards must be a list")
        try:
            references.append(
                VisibleCardReference(
                    package_id=value["package_id"],
                    frame_part_name=value["frame_part_name"],
                    target_offset_ms=value["target_offset_ms"],
                    image_sha256=value["image_sha256"],
                    cards=tuple(
                        _parse_reference_card(card, card_index)
                        for card_index, card in enumerate(cards)
                    ),
                )
            )
        except (TypeError, VisibleCardError) as error:
            raise VisibleCardEvaluationError(f"reference {index} is invalid") from error
    return VisibleCardReferenceSet(tuple(references))


def _polygon_area(polygon: Any) -> float:
    points = [
        (point.x, point.y) if isinstance(point, NormalizedPoint) else point for point in polygon
    ]
    if not points:
        return 0.0
    return abs(
        sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )
        / 2.0
    )


def _signed_area(points: list[tuple[float, float]]) -> float:
    return (
        sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )
        / 2.0
    )


def _intersection(
    start: tuple[float, float],
    end: tuple[float, float],
    edge_start: tuple[float, float],
    edge_end: tuple[float, float],
) -> tuple[float, float]:
    dx1 = end[0] - start[0]
    dy1 = end[1] - start[1]
    dx2 = edge_end[0] - edge_start[0]
    dy2 = edge_end[1] - edge_start[1]
    denominator = dx1 * dy2 - dy1 * dx2
    if abs(denominator) < 1e-12:
        return end
    t = ((edge_start[0] - start[0]) * dy2 - (edge_start[1] - start[1]) * dx2) / denominator
    return start[0] + t * dx1, start[1] + t * dy1


def _clip_polygon(
    subject: list[tuple[float, float]], clip: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    if not subject:
        return []
    orientation = 1.0 if _signed_area(clip) >= 0 else -1.0
    result = subject
    for index, edge_start in enumerate(clip):
        edge_end = clip[(index + 1) % len(clip)]
        previous = result
        result = []
        for point_index, current in enumerate(previous):
            previous_point = previous[point_index - 1]
            current_inside = orientation * _cross(edge_start, edge_end, current) >= -1e-9
            previous_inside = orientation * _cross(edge_start, edge_end, previous_point) >= -1e-9
            if current_inside:
                if not previous_inside:
                    result.append(_intersection(previous_point, current, edge_start, edge_end))
                result.append(current)
            elif previous_inside:
                result.append(_intersection(previous_point, current, edge_start, edge_end))
    return result


def _cross(
    left: tuple[float, float], right: tuple[float, float], point: tuple[float, float]
) -> float:
    return (right[0] - left[0]) * (point[1] - left[1]) - (right[1] - left[1]) * (point[0] - left[0])


def polygon_iou(left: tuple[NormalizedPoint, ...], right: tuple[NormalizedPoint, ...]) -> float:
    """Compute IoU for two convex normalized polygons."""

    left_points = [(point.x, point.y) for point in left]
    right_points = [(point.x, point.y) for point in right]
    left_area = _polygon_area(left_points)
    right_area = _polygon_area(right_points)
    if left_area <= 0.0 or right_area <= 0.0:
        return 0.0
    intersection = _polygon_area(_clip_polygon(left_points, right_points))
    union = left_area + right_area - intersection
    return intersection / union if union > 0.0 else 0.0


def _match(
    proposals: list[Any], references: list[ReferenceCard], threshold: float
) -> tuple[list[tuple[int, int, float]], set[int], set[int]]:
    scores = [
        [polygon_iou(proposal.polygon, reference.polygon) for reference in references]
        for proposal in proposals
    ]
    pairs: list[tuple[int, int, float]] = []
    used_proposals: set[int] = set()
    used_references: set[int] = set()
    candidates = sorted(
        (
            score,
            proposal_index,
            reference_index,
        )
        for proposal_index, row in enumerate(scores)
        for reference_index, score in enumerate(row)
        if score >= threshold
    )
    for score, proposal_index, reference_index in sorted(
        candidates, key=lambda item: (-item[0], item[1], item[2])
    ):
        if proposal_index in used_proposals or reference_index in used_references:
            continue
        used_proposals.add(proposal_index)
        used_references.add(reference_index)
        pairs.append((proposal_index, reference_index, score))
    return pairs, used_proposals, used_references


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate_visible_card_runs(config: VisibleCardEvaluationConfig) -> dict[str, Any]:
    """Evaluate strict provider run artifacts against reviewed polygon references."""

    reference_set = load_visible_card_references(config.references)
    reference_by_key = reference_set.by_key()
    runs: list[tuple[Path, dict[str, Any], VisibleCardReference]] = []
    seen_keys: set[tuple[str, str, int, str]] = set()
    for result_path in config.results:
        run = load_run_artifact(result_path)
        request = run["request"]
        key = (
            request["package_id"],
            request["frame_part_name"],
            request["target_offset_ms"],
            request["image_sha256"],
        )
        reference = reference_by_key.get(key)
        if reference is None:
            raise VisibleCardEvaluationError(
                f"no reviewed reference matches provider run: {result_path}"
            )
        if key in seen_keys:
            raise VisibleCardEvaluationError(f"duplicate provider run for reference: {key}")
        seen_keys.add(key)
        runs.append((Path(result_path), run, reference))
    if seen_keys != set(reference_by_key):
        missing = sorted(set(reference_by_key) - seen_keys)
        raise VisibleCardEvaluationError(f"provider runs do not cover references: {missing[0]}")

    frame_reports: list[dict[str, Any]] = []
    matched_ious: list[float] = []
    matched = 0
    reference_count = 0
    proposal_count = 0
    false_count = 0
    duplicate_count = 0
    usable_reference_count = 0
    usable_matched_count = 0
    side_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    unavailable_count = 0
    retry_count = 0
    latency_values: list[float] = []
    input_tokens = 0
    output_tokens = 0
    estimated_cost = 0.0
    for result_path, run, reference in sorted(runs, key=lambda item: item[2].key):
        proposals = []
        if run["status"] == "ok":
            proposals = run["prediction"]["cards"]
        else:
            unavailable_count += 1
        # The strict run loader has already validated the prediction shape.
        normalized_proposals = list(normalize_prediction({"cards": proposals}).cards)
        pairs, used_proposals, used_references = _match(
            normalized_proposals, list(reference.cards), config.iou_threshold
        )
        pair_ious = [score for _proposal, _reference, score in pairs]
        matched += len(pairs)
        reference_count += len(reference.cards)
        proposal_count += len(normalized_proposals)
        duplicate_indices = {
            proposal_index
            for proposal_index in range(len(normalized_proposals))
            if proposal_index not in used_proposals
            and any(
                polygon_iou(normalized_proposals[proposal_index].polygon, card.polygon)
                >= config.iou_threshold
                for card in reference.cards
            )
        }
        duplicate_count += len(duplicate_indices)
        false_count += len(normalized_proposals) - len(used_proposals) - len(duplicate_indices)
        usable_reference_count += sum(card.usable_for_crop for card in reference.cards)
        usable_matched_count += sum(
            reference.cards[reference_index].usable_for_crop
            for _proposal_index, reference_index, _score in pairs
        )
        for proposal_index, reference_index, _score in pairs:
            reference_card = reference.cards[reference_index]
            predicted_card = normalized_proposals[proposal_index]
            side_counts[reference_card.side][predicted_card.side] += 1
        matched_ious.extend(pair_ious)
        usage = run["usage"]
        input_tokens += usage["input_tokens"]
        output_tokens += usage["output_tokens"]
        estimated_cost += run["estimated_cost_usd"]
        retry_count += run["retry_count"]
        latency_values.append(run["latency_ms"])
        frame_reports.append(
            {
                "package_id": reference.package_id,
                "frame_part_name": reference.frame_part_name,
                "target_offset_ms": reference.target_offset_ms,
                "image_sha256": reference.image_sha256,
                "reference_card_count": len(reference.cards),
                "proposal_count": len(normalized_proposals),
                "matched_count": len(pairs),
                "false_proposal_count": len(normalized_proposals)
                - len(used_proposals)
                - len(duplicate_indices),
                "duplicate_proposal_count": len(duplicate_indices),
                "boundary_iou": pair_ious,
                "status": run["status"],
                "result": str(result_path),
            }
        )
    denominator = len(runs)
    side_metrics = {
        side: {
            "reference_count": sum(counts.values()),
            "matched_count": sum(counts.values()),
            "instance_recall": 1.0,
            "predicted_side_counts": dict(sorted(counts.items())),
        }
        for side, counts in sorted(side_counts.items())
    }
    # Include reference sides that had no matched proposal in the side report.
    for reference in reference_set.references:
        for card in reference.cards:
            side_metrics.setdefault(
                card.side,
                {
                    "reference_count": 0,
                    "matched_count": 0,
                    "instance_recall": 0.0,
                    "predicted_side_counts": {},
                },
            )
            if card.side not in side_counts:
                side_metrics[card.side]["reference_count"] += 1
    for side, metrics in side_metrics.items():
        reference_side_count = sum(
            card.side == side for reference in reference_set.references for card in reference.cards
        )
        matched_side_count = sum(side_counts[side].values())
        metrics["reference_count"] = reference_side_count
        metrics["matched_count"] = matched_side_count
        metrics["instance_recall"] = (
            matched_side_count / reference_side_count if reference_side_count else 0.0
        )
    report = {
        "schema_version": VISIBLE_CARD_EVALUATION_SCHEMA,
        "reference_schema_version": VISIBLE_CARD_REFERENCE_SCHEMA,
        "reference_sha256": _sha256_file(config.references),
        "results": [
            {"path": str(path), "sha256": _sha256_file(path)}
            for path, _run, _reference in sorted(runs, key=lambda item: item[2].key)
        ],
        "result_count": len(runs),
        "iou_threshold": config.iou_threshold,
        "metrics": {
            "frame_count": denominator,
            "reference_card_count": reference_count,
            "proposal_count": proposal_count,
            "matched_card_count": matched,
            "instance_recall": matched / reference_count if reference_count else 0.0,
            "instance_recall_by_side": side_metrics,
            "false_proposal_count": false_count,
            "false_proposals_per_frame": false_count / denominator,
            "duplicate_proposal_count": duplicate_count,
            "duplicate_proposals_per_frame": duplicate_count / denominator,
            "median_boundary_iou": statistics.median(matched_ious) if matched_ious else 0.0,
            "mean_boundary_iou": statistics.mean(matched_ious) if matched_ious else 0.0,
            "usable_reference_count": usable_reference_count,
            "usable_crop_recall": usable_matched_count / usable_reference_count
            if usable_reference_count
            else 0.0,
            "unavailable_count": unavailable_count,
            "unavailable_rate": unavailable_count / denominator,
            "malformed_count": 0,
            "retry_count": retry_count,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": round(estimated_cost, 10),
            "latency_median_ms": statistics.median(latency_values),
            "latency_p95_ms": _percentile(latency_values, 0.95),
        },
        "side_confusion": {
            reference_side: dict(sorted(predicted.items()))
            for reference_side, predicted in sorted(side_counts.items())
        },
        "frames": frame_reports,
        "selection_note": (
            "This evaluates visible-card proposals against reviewed polygons. It does not select "
            "a production provider or create table observations."
        ),
    }
    _write_json(config.output, report)
    return report


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


__all__ = [
    "VISIBLE_CARD_EVALUATION_SCHEMA",
    "VISIBLE_CARD_REFERENCE_SCHEMA",
    "ReferenceCard",
    "VisibleCardEvaluationConfig",
    "VisibleCardEvaluationError",
    "VisibleCardReference",
    "VisibleCardReferenceSet",
    "evaluate_visible_card_runs",
    "load_visible_card_references",
    "polygon_iou",
]
