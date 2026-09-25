"""Evaluate Epic 0082's full-frame and far-cluster refinement policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from table_evidence_analyzer.visible_card_evaluation import _clip_polygon
from table_evidence_analyzer.visible_card_fine_frame_provider import (
    FINE_FRAME_PROVIDER_NAME,
    LocalVisibleCardFineFrameProvider,
)
from table_evidence_analyzer.visible_cards import VisibleCardRequest

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / ".runtime/rfdetr-visible-card-detector-0068-m2-training/bundle"
SEALED = ROOT / ".runtime/rfdetr-segmentation-0068/sealed_test"
REVIEW_REVISION = ROOT / (
    "data/operations/pipeline/revisions/reference-visible_cards-44c56fc8fc395ee43f3220e9b60bb1e9"
)
FIXTURE_ROOT = ROOT / "table_evidence_analyzer/tests/fixtures/visible_card_fine_prepass"
DERIVED_VIEWS = ROOT / ".runtime/pipeline/derived-views"
DEFAULT_OUTPUT = ROOT / "docs/reports/0082-M3_Fine_Frame_Refinement_Evaluation.json"
IOU_THRESHOLD = 0.5
IGNORE_COVERAGE_THRESHOLD = 0.5
SMALL_CARD_AREA_THRESHOLD = 0.013576


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _point_pairs(points: list[dict[str, float]]) -> tuple[tuple[float, float], ...]:
    return tuple((float(point["x"]), float(point["y"])) for point in points)


def _normalise_polygon(
    points: list[dict[str, float]], *, width: int, height: int
) -> tuple[tuple[float, float], ...]:
    return tuple(
        (float(point["x"]) * 1000.0 / width, float(point["y"]) * 1000.0 / height)
        for point in points
    )


def _bbox(polygons: tuple[tuple[tuple[float, float], ...], ...]) -> tuple[float, ...]:
    points = [point for polygon in polygons for point in polygon]
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _boxes_overlap(left: tuple[float, ...], right: tuple[float, ...]) -> bool:
    return min(left[2], right[2]) > max(left[0], right[0]) and min(left[3], right[3]) > max(
        left[1], right[1]
    )


def _coalesce_iou(
    proposals: list[tuple[tuple[float, float], ...]],
    references: list[tuple[tuple[float, float], ...]],
) -> tuple[list[tuple[int, int, float]], set[int], set[int]]:
    scores = [
        [_polygon_iou(proposal, reference) for reference in references] for proposal in proposals
    ]
    pairs = sorted(
        (
            score,
            proposal_index,
            reference_index,
        )
        for proposal_index, row in enumerate(scores)
        for reference_index, score in enumerate(row)
        if score >= IOU_THRESHOLD
    )
    used_proposals: set[int] = set()
    used_references: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for score, proposal_index, reference_index in sorted(
        pairs, key=lambda item: (-item[0], item[1], item[2])
    ):
        if proposal_index in used_proposals or reference_index in used_references:
            continue
        used_proposals.add(proposal_index)
        used_references.add(reference_index)
        matches.append((proposal_index, reference_index, score))
    return matches, used_proposals, used_references


def _area(polygon: tuple[tuple[float, float], ...]) -> float:
    return abs(
        sum(
            polygon[index][0] * polygon[(index + 1) % len(polygon)][1]
            - polygon[(index + 1) % len(polygon)][0] * polygon[index][1]
            for index in range(len(polygon))
        )
        / 2.0
    )


def _polygon_iou(
    left: tuple[tuple[float, float], ...], right: tuple[tuple[float, float], ...]
) -> float:
    left_area = _area(left)
    right_area = _area(right)
    if left_area <= 0.0 or right_area <= 0.0:
        return 0.0
    intersection = _area(tuple(_clip_polygon(list(left), list(right))))
    union = left_area + right_area - intersection
    return intersection / union if union > 0.0 else 0.0


def _covered_by_ignore(
    proposal: tuple[tuple[float, float], ...],
    ignore_mask: Image.Image,
) -> bool:
    """Exclude an unmatched proposal mostly inside any reviewed ignore region."""

    x0 = max(0, min(1000, round(min(point[0] for point in proposal))))
    y0 = max(0, min(1000, round(min(point[1] for point in proposal))))
    x1 = max(0, min(1000, round(max(point[0] for point in proposal))))
    y1 = max(0, min(1000, round(max(point[1] for point in proposal))))
    proposal_mask = Image.new("L", (x1 - x0 + 1, y1 - y0 + 1))
    ImageDraw.Draw(proposal_mask).polygon(
        [(round(x) - x0, round(y) - y0) for x, y in proposal], fill=255
    )
    proposal_pixels = np.asarray(proposal_mask) > 0
    proposal_area = int(proposal_pixels.sum())
    if proposal_area == 0:
        return False
    region = ignore_mask.crop((x0, y0, x1 + 1, y1 + 1))
    intersection = int(np.logical_and(proposal_pixels, np.asarray(region) > 0).sum())
    return intersection / proposal_area >= IGNORE_COVERAGE_THRESHOLD


def _build_ignore_mask(
    ignore_polygons: list[tuple[tuple[float, float], ...]],
) -> Image.Image:
    mask = Image.new("L", (1001, 1001))
    draw = ImageDraw.Draw(mask)
    for polygon in ignore_polygons:
        draw.polygon([(round(x), round(y)) for x, y in polygon], fill=255)
    return mask


def _load_cache() -> dict[str, tuple[Path, dict[str, Any]]]:
    entries: dict[str, tuple[Path, dict[str, Any]]] = {}
    for manifest_path in DERIVED_VIEWS.glob("*/manifest.json"):
        manifest = _read_json(manifest_path)
        identity = manifest.get("identity", {})
        if (
            manifest.get("view_kind") == "exact-event/v1"
            and identity.get("transform_version") == "ffmpeg-mjpeg/8.1.2"
            and isinstance(identity.get("image_sha256"), str)
        ):
            entries[identity["image_sha256"]] = (manifest_path.parent / "content.bin", identity)
    return entries


def _load_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    annotation_path = SEALED / "_annotations.coco.json"
    coco = _read_json(annotation_path)
    training_recordings = set()
    for partition in ("train", "valid"):
        training_annotations = _read_json(
            ROOT / f".runtime/rfdetr-segmentation-0068/{partition}/_annotations.coco.json"
        )
        training_recordings.update(
            image["recording_id"] for image in training_annotations["images"]
        )
    annotations_by_image: dict[int, list[dict[str, Any]]] = {}
    for annotation in coco["annotations"]:
        annotations_by_image.setdefault(int(annotation["image_id"]), []).append(annotation)
    for image in sorted(coco["images"], key=lambda item: item["id"]):
        image_path = SEALED / image["file_name"]
        image_bytes = image_path.read_bytes()
        if _sha256(image_bytes) != image["sha256"]:
            raise ValueError(f"sealed image digest mismatch: {image['item_id']}")
        references = []
        for annotation in annotations_by_image.get(int(image["id"]), []):
            segmentation = annotation["segmentation"]
            if not isinstance(segmentation, list) or not segmentation:
                raise ValueError("sealed annotation is not polygon geometry")
            for polygon in segmentation:
                points = [
                    {"x": polygon[index], "y": polygon[index + 1]}
                    for index in range(0, len(polygon), 2)
                ]
                references.append(
                    _normalise_polygon(
                        points, width=int(image["width"]), height=int(image["height"])
                    )
                )
        cases.append(
            {
                "recording_id": image["recording_id"],
                "event_id": image["item_id"],
                "image_sha256": image["sha256"],
                "width": int(image["width"]),
                "height": int(image["height"]),
                "image_bytes": image_bytes,
                "references": references,
                "ignore_polygons": [],
                "dataset": "0068_sealed_test",
            }
        )

    revision_manifest = _read_json(REVIEW_REVISION / "manifest.json")
    if revision_manifest["recording_id"] in training_recordings:
        raise ValueError("supplemental recording overlaps 0068 training or validation")
    revision_content_path = REVIEW_REVISION / "content.json"
    revision_content = _read_json(revision_content_path)
    cache = _load_cache()
    for outcome in revision_content["outcomes"]:
        if outcome["status"] != "detected":
            continue
        identity = outcome["frame_identity"]
        image_sha = identity["image_sha256"]
        cached = cache.get(image_sha)
        if cached is None:
            raise ValueError(f"missing exact source frame from cache: {outcome['event_id']}")
        image_path, cached_identity = cached
        if cached_identity != identity:
            raise ValueError(f"cached frame identity mismatch: {outcome['event_id']}")
        image_bytes = image_path.read_bytes()
        if _sha256(image_bytes) != image_sha:
            raise ValueError(f"cached frame digest mismatch: {outcome['event_id']}")
        references = []
        for candidate in outcome["candidates"]:
            polygons = candidate["geometry"]["visible_region"]["polygons"]
            if len(polygons) != 1:
                raise ValueError("supplemental reference has multiple polygon components")
            references.append(_point_pairs(polygons[0]))
        ignore_polygons = [
            _point_pairs(polygon)
            for region in outcome["ignored_regions"]
            for polygon in region["geometry"]["polygons"]
        ]
        cases.append(
            {
                "recording_id": revision_manifest["recording_id"],
                "event_id": outcome["event_id"],
                "image_sha256": image_sha,
                "width": int(identity["width"]),
                "height": int(identity["height"]),
                "image_bytes": image_bytes,
                "references": references,
                "ignore_polygons": ignore_polygons,
                "dataset": "supplemental_reviewed_IMG_0644",
            }
        )

    sources = {
        "0068_sealed_test": {
            "path": str(annotation_path.relative_to(ROOT)),
            "file_sha256": _sha256(annotation_path.read_bytes()),
            "campaign_manifest_digest": coco["info"]["campaign_manifest_digest"],
            "reference_count": len(coco["annotations"]),
            "frame_count": len(coco["images"]),
            "recording_ids": sorted({image["recording_id"] for image in coco["images"]}),
        },
        "supplemental_reviewed_IMG_0644": {
            "revision_id": revision_manifest["revision_id"],
            "content_sha256": revision_manifest["content_sha256"],
            "content_file_sha256": _sha256(revision_content_path.read_bytes()),
            "source_video_sha256": revision_manifest["source"]["video_sha256"],
            "frame_count": sum(
                case["dataset"] == "supplemental_reviewed_IMG_0644" for case in cases
            ),
            "reference_count": sum(
                len(case["references"])
                for case in cases
                if case["dataset"] == "supplemental_reviewed_IMG_0644"
            ),
            "excluded_failed_frames": sum(
                outcome["status"] != "detected" for outcome in revision_content["outcomes"]
            ),
            "recording_id": revision_manifest["recording_id"],
            "review_origin": revision_manifest["origin"],
            "review_operator": revision_manifest["producer"].get("operator_id"),
        },
    }
    return cases, sources


def _load_support_fixtures() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest_path = FIXTURE_ROOT / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    video_path = FIXTURE_ROOT / manifest["source_video"]["path"]
    if _sha256(video_path.read_bytes()) != manifest["source_video"]["sha256"]:
        raise ValueError("central regression source video digest mismatch")
    cases = []
    for case in manifest["cases"]:
        image_bytes = (FIXTURE_ROOT / case["image"]).read_bytes()
        if _sha256(image_bytes) != case["image_sha256"]:
            raise ValueError(f"central regression image digest mismatch: {case['event_id']}")
        with Image.open(FIXTURE_ROOT / case["image"]) as image:
            if image.size != (case["width"], case["height"]):
                raise ValueError(f"central regression dimensions mismatch: {case['event_id']}")
        cases.append(
            {
                "event_id": case["event_id"],
                "image_sha256": case["image_sha256"],
                "width": case["width"],
                "height": case["height"],
                "image_bytes": image_bytes,
                "support_regions": case["central_card_support_regions_normalized_1000"],
                "regions_are_reviewed_ground_truth": case[
                    "expected_regions_are_reviewed_ground_truth"
                ],
            }
        )
    source = {
        "manifest_path": str(manifest_path.relative_to(ROOT)),
        "manifest_sha256": _sha256(manifest_bytes),
        "source_video_sha256": manifest["source_video"]["sha256"],
    }
    return cases, source


def _prediction_polygons(raw_predictions: list[dict[str, Any]], width: int, height: int):
    return [
        _normalise_polygon(polygon, width=width, height=height)
        for prediction in raw_predictions
        for polygon in prediction["polygons"][:1]
    ]


def _proposal_polygons(result: Any):
    return [
        tuple((float(point.x), float(point.y)) for point in proposal.polygon)
        for proposal in result.proposals
    ]


def _metric_bundle(
    proposals: list[tuple[tuple[float, float], ...]],
    references: list[tuple[tuple[float, float], ...]],
    ignore_mask: Image.Image,
) -> dict[str, Any]:
    matches, used_proposals, used_references = _coalesce_iou(proposals, references)
    duplicate_indices = {
        index
        for index, proposal in enumerate(proposals)
        if index not in used_proposals
        and any(_polygon_iou(proposal, reference) >= IOU_THRESHOLD for reference in references)
    }
    ignored_indices = {
        index
        for index, proposal in enumerate(proposals)
        if index not in used_proposals
        and index not in duplicate_indices
        and _covered_by_ignore(proposal, ignore_mask)
    }
    false = len(proposals) - len(used_proposals) - len(duplicate_indices) - len(ignored_indices)
    return {
        "targets": len(references),
        "predictions": len(proposals),
        "matched": len(matches),
        "recall": len(matches) / len(references) if references else 0.0,
        "false": false,
        "duplicates": len(duplicate_indices),
        "ignored_unmatched": len(ignored_indices),
        "duplicate_prediction_indices": sorted(duplicate_indices),
        "ignored_prediction_indices": sorted(ignored_indices),
        "matched_pairs": [
            {"prediction_index": pi, "reference_index": ri, "polygon_iou": score}
            for pi, ri, score in matches
        ],
    }


def _frame_groups(case: dict[str, Any]) -> set[str]:
    boxes = [_bbox((polygon,)) for polygon in case["references"]]
    groups: set[str] = set()
    if any(
        (box[3] - box[1]) * (box[2] - box[0]) / 1_000_000 <= SMALL_CARD_AREA_THRESHOLD
        for box in boxes
    ):
        groups.add("small_card_frames")
    if any(
        330 <= (box[1] + box[3]) / 2 <= 670 and 330 <= (box[0] + box[2]) / 2 <= 670 for box in boxes
    ):
        groups.add("central_card_frames")
    if any((box[1] + box[3]) / 2 <= 330 for box in boxes):
        groups.add("far_field_frames")
    if any(min(box[0], box[1], 1000 - box[2], 1000 - box[3]) <= 50 for box in boxes):
        groups.add("frame_edge_frames")
    if len(boxes) == 1:
        groups.add("single_card_frames")
    for index, left in enumerate(boxes):
        for right in boxes[index + 1 :]:
            intersection = max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * max(
                0.0, min(left[3], right[3]) - max(left[1], right[1])
            )
            left_area = (left[2] - left[0]) * (left[3] - left[1])
            right_area = (right[2] - right[0]) * (right[3] - right[1])
            if min(left_area, right_area) > 0 and intersection / min(left_area, right_area) >= 0.1:
                groups.add("overlap_frames")
                break
    return groups


def _aggregate(frame_rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "frame_count": len(frame_rows),
        "target_count": 0,
        "recording_ids": sorted({row["recording_id"] for row in frame_rows}),
    }
    for key in ("full_frame", "refined"):
        targets = sum(row[key]["targets"] for row in frame_rows)
        matches = sum(row[key]["matched"] for row in frame_rows)
        result["target_count"] = targets
        result[key] = {
            "matched": matches,
            "recall": matches / targets if targets else 0.0,
            "predictions": sum(row[key]["predictions"] for row in frame_rows),
            "false": sum(row[key]["false"] for row in frame_rows),
            "duplicates": sum(row[key]["duplicates"] for row in frame_rows),
            "ignored_unmatched": sum(row[key]["ignored_unmatched"] for row in frame_rows),
            "mean_matched_polygon_iou": statistics.mean(
                pair["polygon_iou"] for row in frame_rows for pair in row[key]["matched_pairs"]
            )
            if matches
            else 0.0,
            "median_matched_polygon_iou": statistics.median(
                pair["polygon_iou"] for row in frame_rows for pair in row[key]["matched_pairs"]
            )
            if matches
            else 0.0,
        }
    return result


def _canonical_geometry(case: dict[str, Any], result: Any) -> dict[str, Any]:
    return {
        "event_id": case["event_id"],
        "proposals": [
            [[point.x, point.y] for point in proposal.polygon] for proposal in result.proposals
        ],
        "provenance": result.raw_response["final_provenance"],
    }


def _support_fixture_run(
    provider: Any, cases: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    geometries = []
    for case in cases:
        request = VisibleCardRequest(
            package_id="epic-0082-regression",
            frame_part_name=case["event_id"],
            target_offset_ms=0,
            image_bytes=case["image_bytes"],
            width=case["width"],
            height=case["height"],
            provider=FINE_FRAME_PROVIDER_NAME,
        )
        if request.image_sha256 != case["image_sha256"]:
            raise ValueError(f"central regression request digest mismatch: {case['event_id']}")
        result = provider.propose(request)
        if result.status != "ok":
            raise RuntimeError(f"provider failed on {case['event_id']}: {result.error}")
        raw = result.raw_response
        full_predictions = _prediction_polygons(
            raw["full_frame"]["predictions"], case["width"], case["height"]
        )
        final_predictions = _proposal_polygons(result)
        regions = []
        for region in case["support_regions"]:
            support_box = (
                region["x_min"],
                region["y_min"],
                region["x_max"],
                region["y_max"],
            )

            regions.append(
                {
                    "support_region": region,
                    "full_frame_hit": any(
                        _boxes_overlap(_bbox((polygon,)), support_box)
                        for polygon in full_predictions
                    ),
                    "final_hit": any(
                        _boxes_overlap(_bbox((polygon,)), support_box)
                        for polygon in final_predictions
                    ),
                }
            )
        rows.append(
            {
                "event_id": case["event_id"],
                "image_sha256": case["image_sha256"],
                "regions_are_reviewed_ground_truth": case["regions_are_reviewed_ground_truth"],
                "full_frame_prediction_count": len(full_predictions),
                "final_prediction_count": len(final_predictions),
                "support_regions": regions,
                "full_frame_support_regions_hit": sum(
                    region["full_frame_hit"] for region in regions
                ),
                "final_support_regions_hit": sum(region["final_hit"] for region in regions),
                "timing_ms": raw["timing"],
            }
        )
        geometries.append(_canonical_geometry(case, result))
    return rows, geometries


def _run(
    provider: Any, cases: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    frame_rows: list[dict[str, Any]] = []
    geometries: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        request = VisibleCardRequest(
            package_id="epic-0082-m3",
            frame_part_name=case["event_id"],
            target_offset_ms=0,
            image_bytes=case["image_bytes"],
            width=case["width"],
            height=case["height"],
            provider=FINE_FRAME_PROVIDER_NAME,
        )
        if request.image_sha256 != case["image_sha256"]:
            raise ValueError(f"request image digest mismatch: {case['event_id']}")
        result = provider.propose(request)
        if result.status != "ok":
            raise RuntimeError(f"provider failed on {case['event_id']}: {result.error}")
        raw = result.raw_response
        full_frame = _prediction_polygons(
            raw["full_frame"]["predictions"], case["width"], case["height"]
        )
        refined = _proposal_polygons(result)
        ignore_mask = _build_ignore_mask(case["ignore_polygons"])
        main_metrics = _metric_bundle(full_frame, case["references"], ignore_mask)
        refined_metrics = _metric_bundle(refined, case["references"], ignore_mask)
        provenance = raw["final_provenance"]
        added_indices = [
            proposal_index
            for proposal_index, item in enumerate(provenance)
            if item["source"] == "cluster_crop_addition"
        ]
        refinement = raw["arbitration"]
        routing = raw["clusters"]["routing"]
        crop_rows = raw["refinement"]["clusters"]
        crop_area_ratio = sum(
            item["crop"]["crop_dimensions"]["width"]
            * item["crop"]["crop_dimensions"]["height"]
            / (case["width"] * case["height"])
            for item in crop_rows
            if item["status"] != "skipped"
        )
        refined_geometries = sum(
            item["decision"] == "refine_geometry" for item in refinement["matched_pairs"]
        )
        improved_matches = sum(
            _polygon_iou(
                refined[item["prediction_index"]],
                case["references"][item["reference_index"]],
            )
            > _polygon_iou(
                full_frame[item["prediction_index"]],
                case["references"][item["reference_index"]],
            )
            for item in main_metrics["matched_pairs"]
            if item["prediction_index"] < len(full_frame)
            and item["prediction_index"] < len(refined)
        )
        matched_final_indices = {
            item["prediction_index"] for item in refined_metrics["matched_pairs"]
        }
        duplicate_final_indices = set(refined_metrics["duplicate_prediction_indices"])
        ignored_final_indices = set(refined_metrics["ignored_prediction_indices"])
        row = {
            "recording_id": case["recording_id"],
            "event_id": case["event_id"],
            "dataset": case["dataset"],
            "image_sha256": case["image_sha256"],
            "reference_count": len(case["references"]),
            "full_frame": main_metrics,
            "refined": refined_metrics,
            "crop": {
                "cluster_count": len(routing),
                "routed_cluster_count": len(raw["clusters"]["routed_cluster_ids"]),
                "skipped_cluster_count": sum(item["route"] is False for item in routing),
                "failed_cluster_count": sum(item["status"] == "unavailable" for item in crop_rows),
                "crop_area_ratio_sum": crop_area_ratio,
                "crop_predictions": refinement["crop_predictions_before_reconciliation"],
                "matched_pairs": len(refinement["matched_pairs"]),
                "geometries_refined": refined_geometries,
                "crop_additions": len(added_indices),
                "crop_addition_matched": sum(
                    index in matched_final_indices for index in added_indices
                ),
                "crop_addition_duplicate": sum(
                    index in duplicate_final_indices for index in added_indices
                ),
                "crop_addition_ignored": sum(
                    index in ignored_final_indices for index in added_indices
                ),
                "crop_addition_false": sum(
                    index not in matched_final_indices
                    and index not in duplicate_final_indices
                    and index not in ignored_final_indices
                    for index in added_indices
                ),
                "strict_duplicate_discards": sum(
                    item["reason"] == "duplicate_of_main_result"
                    for item in raw["reconciliation"]["discarded"]
                ),
                "full_frame_candidates_removed": refinement["full_frame_candidates_removed"],
                "matched_geometry_iou_improvements": improved_matches,
            },
            "timing_ms": {
                "prepass": raw["full_frame"]["latency_ms"],
                "crop": raw["refinement"]["latency_ms"],
                "total": raw["timing"]["total_latency_ms"],
            },
            "groups": sorted(_frame_groups(case)),
        }
        frame_rows.append(row)
        geometries.append(_canonical_geometry(case, result))
        if index % 20 == 0 or index == len(cases):
            print(f"processed {index}/{len(cases)} frames", flush=True)
    return frame_rows, geometries


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round((len(values) - 1) * percentile)))]


def _run_summary(frame_rows: list[dict[str, Any]]) -> dict[str, Any]:
    datasets = sorted({row["dataset"] for row in frame_rows})
    groups = sorted({group for row in frame_rows for group in row["groups"]})
    return {
        "datasets": {
            dataset: _aggregate([row for row in frame_rows if row["dataset"] == dataset])
            for dataset in datasets
        },
        "overall": _aggregate(frame_rows),
        "groups": {
            group: _aggregate([row for row in frame_rows if group in row["groups"]])
            for group in groups
        },
        "groups_by_dataset": {
            dataset: {
                group: _aggregate(
                    [
                        row
                        for row in frame_rows
                        if row["dataset"] == dataset and group in row["groups"]
                    ]
                )
                for group in groups
                if any(row["dataset"] == dataset and group in row["groups"] for row in frame_rows)
            }
            for dataset in datasets
        },
        "crop": {
            "cluster_count": sum(row["crop"]["cluster_count"] for row in frame_rows),
            "routed_cluster_count": sum(row["crop"]["routed_cluster_count"] for row in frame_rows),
            "routed_cluster_fraction": (
                sum(row["crop"]["routed_cluster_count"] for row in frame_rows)
                / sum(row["crop"]["cluster_count"] for row in frame_rows)
                if sum(row["crop"]["cluster_count"] for row in frame_rows)
                else 0.0
            ),
            "skipped_cluster_count": sum(
                row["crop"]["skipped_cluster_count"] for row in frame_rows
            ),
            "failed_cluster_count": sum(row["crop"]["failed_cluster_count"] for row in frame_rows),
            "crop_predictions": sum(row["crop"]["crop_predictions"] for row in frame_rows),
            "matched_pairs": sum(row["crop"]["matched_pairs"] for row in frame_rows),
            "geometries_refined": sum(row["crop"]["geometries_refined"] for row in frame_rows),
            "crop_additions": sum(row["crop"]["crop_additions"] for row in frame_rows),
            "crop_addition_matched": sum(
                row["crop"]["crop_addition_matched"] for row in frame_rows
            ),
            "crop_addition_duplicate": sum(
                row["crop"]["crop_addition_duplicate"] for row in frame_rows
            ),
            "crop_addition_ignored": sum(
                row["crop"]["crop_addition_ignored"] for row in frame_rows
            ),
            "crop_addition_false": sum(row["crop"]["crop_addition_false"] for row in frame_rows),
            "strict_duplicate_discards": sum(
                row["crop"]["strict_duplicate_discards"] for row in frame_rows
            ),
            "full_frame_candidates_removed": sum(
                row["crop"]["full_frame_candidates_removed"] for row in frame_rows
            ),
            "matched_geometry_iou_improvements": sum(
                row["crop"]["matched_geometry_iou_improvements"] for row in frame_rows
            ),
            "crop_area_ratio_sum_median_per_frame": statistics.median(
                row["crop"]["crop_area_ratio_sum"] for row in frame_rows
            ),
        },
        "timing_ms": {
            name: {
                "median": statistics.median(row["timing_ms"][name] for row in frame_rows),
                "p95": _percentile([row["timing_ms"][name] for row in frame_rows], 0.95),
            }
            for name in ("prepass", "crop", "total")
        },
    }


def _compact_frame(row: dict[str, Any]) -> dict[str, Any]:
    compact = dict(row)
    for variant in ("full_frame", "refined"):
        compact[variant] = {
            key: value
            for key, value in row[variant].items()
            if key
            not in {
                "matched_pairs",
                "duplicate_prediction_indices",
                "ignored_prediction_indices",
            }
        }
    return compact


def _interpretation(frame_rows: list[dict[str, Any]]) -> dict[str, Any]:
    far_rows = [row for row in frame_rows if "far_field_frames" in row["groups"]]
    recording_ids = sorted({row["recording_id"] for row in far_rows})
    routed_clusters = sum(row["crop"]["routed_cluster_count"] for row in frame_rows)
    cluster_count = sum(row["crop"]["cluster_count"] for row in frame_rows)
    routed_fraction = routed_clusters / cluster_count if cluster_count else 0.0
    return {
        "far_field_sample": {
            "frame_count": len(far_rows),
            "target_count": sum(row["reference_count"] for row in far_rows),
            "recording_ids": recording_ids,
            "assessment": "insufficient",
            "reason": (
                "The initial six-frame far-field slice was already identified as insufficient "
                "in the M3 plan."
            ),
        },
        "limitations": [
            f"{len(far_rows)} far-field frames span only {len(recording_ids)} held-out recordings.",
            "IMG_0644 adds held-out overlap and edge cases but no top-third targets.",
            (
                "The current rule routed "
                f"{routed_clusters} of {cluster_count} card clusters, "
                f"so crop inference ran on {routed_fraction:.1%} of clusters."
            ),
            f"None of the {len(far_rows)} top-third frames changed after crop refinement.",
            "Unfinished IMG_0650/0652/0653/0654/0656/0671 drafts are excluded.",
            "The evaluation has positive examples only, not background-only frames.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=("mps", "cpu", "cuda"), default="mps")
    args = parser.parse_args()
    cases, sources = _load_cases()
    support_cases, support_source = _load_support_fixtures()
    sources["central_regression_fixtures"] = support_source
    sealed_recordings = set(sources["0068_sealed_test"]["recording_ids"])
    if "cardeventnet-IMG_0644" in sealed_recordings:
        raise ValueError("supplemental recording overlaps the 0068 held-out partition")
    bundle_manifest = _read_json(BUNDLE / "manifest.json")
    provider = LocalVisibleCardFineFrameProvider(BUNDLE, device=args.device)
    support_rows, support_geometry_first = _support_fixture_run(provider, support_cases)
    started = time.monotonic()
    frame_rows, geometry_first = _run(provider, cases)
    repeated_rows, geometry_second = _run(provider, cases)
    evaluation_elapsed = time.monotonic() - started
    repeated_support_rows, support_geometry_second = _support_fixture_run(provider, support_cases)
    if [row["event_id"] for row in frame_rows] != [row["event_id"] for row in repeated_rows]:
        raise ValueError("repeat run frame order changed")
    digest_first = _sha256(
        json.dumps(geometry_first, sort_keys=True, separators=(",", ":")).encode()
    )
    digest_second = _sha256(
        json.dumps(geometry_second, sort_keys=True, separators=(",", ":")).encode()
    )
    changed = [
        first["event_id"]
        for first, second in zip(geometry_first, geometry_second, strict=True)
        if first != second
    ]
    support_digest_first = _sha256(
        json.dumps(support_geometry_first, sort_keys=True, separators=(",", ":")).encode()
    )
    support_digest_second = _sha256(
        json.dumps(support_geometry_second, sort_keys=True, separators=(",", ":")).encode()
    )
    support_deterministic = support_digest_first == support_digest_second
    if [row["event_id"] for row in support_rows] != [
        row["event_id"] for row in repeated_support_rows
    ]:
        raise ValueError("central regression fixture order changed")
    for row, _repeated in zip(frame_rows, repeated_rows, strict=True):
        if row["crop"]["full_frame_candidates_removed"] != 0:
            raise ValueError(f"full-frame candidate was removed in {row['event_id']}")
    report = {
        "schema_version": "epic-0082-m3-refinement-evaluation/v1",
        "provider": {
            "name": FINE_FRAME_PROVIDER_NAME,
            "version": provider.version,
            "device": args.device,
            "bundle_digest": bundle_manifest["bundle_digest"],
            "checkpoint_sha256": bundle_manifest["checkpoint_sha256"],
            "confidence_threshold": provider.confidence_threshold,
            "far_cluster_routing": {
                "max_full_frame_model_span_px": 96.0,
                "min_crop_scale_gain": 1.5,
            },
            "refinement": {
                "minimum_box_iou": 0.5,
                "minimum_visible_mask_iou": 0.5,
                "ambiguity_margin": 0.1,
                "minimum_score_gain": 0.05,
                "crop_addition_minimum_score": 0.7,
                "duplicate_iou_threshold": 0.9,
            },
        },
        "method": {
            "polygon_iou_threshold": IOU_THRESHOLD,
            "matching": "descending-IoU one-to-one greedy assignment with stable input-order ties",
            "full_frame_is_main_result": True,
            "supplemental_unmatched_predictions_inside_ignore_regions": (
                "not counted as false when at least "
                f"{IGNORE_COVERAGE_THRESHOLD:.0%} of prediction polygon area is covered"
            ),
            "small_card_frame_area_threshold": SMALL_CARD_AREA_THRESHOLD,
            "far_field_frame_definition": (
                "at least one reviewed card bounding-box center has normalized y <= 0.330"
            ),
            "frame_edge_definition": (
                "at least one reviewed card bounding box is within 5% of a frame edge"
            ),
            "overlap_definition": (
                "reviewed bounding-box intersection covers at least 10% of the smaller box"
            ),
            "determinism_digest_scope": (
                "final normalized proposal geometry and provenance; timing excluded"
            ),
        },
        "sources": sources,
        "determinism": {
            "repeated_runs": 2,
            "first_geometry_sha256": digest_first,
            "second_geometry_sha256": digest_second,
            "identical": digest_first == digest_second,
            "changed_frame_count": len(changed),
            "changed_event_ids": changed,
        },
        "evaluation": _run_summary(frame_rows),
        "central_regression_fixtures": {
            "regions_are_reviewed_ground_truth": False,
            "full_frame_pass_intersects_each_fixture": all(
                row["full_frame_support_regions_hit"] > 0 for row in support_rows
            ),
            "final_pass_intersects_each_fixture": all(
                row["final_support_regions_hit"] > 0 for row in support_rows
            ),
            "repeated_output_deterministic": support_deterministic,
            "first_geometry_sha256": support_digest_first,
            "second_geometry_sha256": support_digest_second,
            "cases": support_rows,
        },
        "frames": [_compact_frame(row) for row in frame_rows],
        "elapsed_seconds": round(evaluation_elapsed, 3),
        "interpretation": _interpretation(frame_rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "frames": len(frame_rows),
                "deterministic": report["determinism"]["identical"],
                "elapsed_seconds": report["elapsed_seconds"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
