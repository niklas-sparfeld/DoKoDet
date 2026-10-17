#!/usr/bin/env python3
"""Evaluate epic 0096 segmentation outputs on M0-frozen exact reference pairs."""
from __future__ import annotations

import cv2
import numpy as np
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "table_evidence_analyzer" / "src"))
sys.path.insert(0, str(ROOT / "operations" / "src"))
from table_evidence_analyzer.pipeline_data import ReviewedIgnoreRegionGeometry, parse_pipeline_geometry  # noqa: E402

PIPELINE = ROOT / "data/operations/pipeline"
REPORTS = ROOT / "docs/reports"
M0 = json.loads((REPORTS / "0096-M0_Preflight.json").read_text())
PAIRS = json.loads((REPORTS / "0096-M0_Exact_Frame_Comparison.json").read_text())
M1 = json.loads((REPORTS / "0096-M1_Run_Result.json").read_text())
M2 = json.loads((REPORTS / "0096-M2_Proposed_Scene_Results.json").read_text())


def load_revision(revision_id: str) -> dict:
    return json.loads((PIPELINE / "revisions" / revision_id / "content.json").read_text())


def normalized_geometry(candidate: dict, *, reviewed: bool = False):
    geometry = json.loads(json.dumps(candidate["geometry"]))
    normalization = candidate["normalization"]
    width, height = normalization["width"], normalization["height"]
    geometry["kind"] = "reviewed-visible-region/v1" if reviewed else "visible-region/v1"
    for polygon in geometry["visible_region"]["polygons"]:
        for point in polygon:
            point["x"] = round(1000 * point["x"] / width)
            point["y"] = round(1000 * point["y"] / height)
    return parse_pipeline_geometry(geometry)


def geometry_polygons(geometry):
    return geometry.polygons


def geometry_box(geometry):
    points = [point for polygon in geometry_polygons(geometry) for point in polygon]
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def raster_geometry(geometry):
    # Vectorized implementation of the pipeline comparator's exact pixel-center/even-odd rasterizer.
    polygons = geometry_polygons(geometry)
    xs = [x for polygon in polygons for x, _ in polygon]
    ys = [y for polygon in polygons for _, y in polygon]
    if not xs or not ys:
        return (0, 0, np.zeros((0, 0), dtype=np.uint8))
    x0 = max(0, min(999, min(xs) - 1)); y0 = max(0, min(999, min(ys) - 1))
    x1 = min(999, max(xs) + 1); y1 = min(999, max(ys) + 1)
    x_num = (2 * np.arange(x0, x1 + 1, dtype=np.int64) + 1)[None, :]
    y_num = (2 * np.arange(y0, y1 + 1, dtype=np.int64) + 1)[:, None]
    union = np.zeros((y1-y0+1, x1-x0+1), dtype=bool)
    for polygon in polygons:
        inside = np.zeros_like(union); boundary = np.zeros_like(union)
        for index, (x1p, y1p) in enumerate(polygon):
            x2p, y2p = polygon[(index + 1) % len(polygon)]
            dx, dy = x2p-x1p, y2p-y1p
            cross = (x_num-2*x1p)*dy*2 - (y_num-2*y1p)*dx*2
            on_edge = ((cross == 0) & ((x_num-2*x1p)*(x_num-2*x2p) <= 0)
                       & ((y_num-2*y1p)*(y_num-2*y2p) <= 0))
            boundary |= on_edge
            first_above = y1p*2 > y_num; second_above = y2p*2 > y_num
            crossing_row = first_above != second_above
            if not crossing_row.any(): continue
            intersection_num = x1p*dy*2 + (y_num-y1p*2)*dx
            intersection_den = dy*2
            left = x_num*intersection_den; right = intersection_num*2
            crosses = (left < right) if intersection_den > 0 else (left > right)
            inside ^= crossing_row & crosses
        union |= inside | boundary
    return x0, y0, union.astype(np.uint8)


def geometry_iou_fast(left, right, cache):
    if id(left) not in cache: cache[id(left)] = raster_geometry(left)
    if id(right) not in cache: cache[id(right)] = raster_geometry(right)
    lm_data = cache[id(left)]
    rm_data = cache[id(right)]
    lx, ly, lm = lm_data; rx, ry, rm = rm_data
    if lm.size == 0 or rm.size == 0:
        return 0.0
    x0, y0 = max(lx, rx), max(ly, ry)
    x1, y1 = min(lx + lm.shape[1], rx + rm.shape[1]), min(ly + lm.shape[0], ry + rm.shape[0])
    inter = 0
    if x1 > x0 and y1 > y0:
        inter = int(np.logical_and(lm[y0-ly:y1-ly, x0-lx:x1-lx], rm[y0-ry:y1-ry, x0-rx:x1-rx]).sum())
    union = int(lm.sum()) + int(rm.sum()) - inter
    return inter / union if union else 0.0


def greedy_match(predictions: list[dict], references: list[dict], pred_geoms, ref_geoms, cache: dict):
    # Match with the same highest-IoU and stable geometry/card-ID tie breaks as the pipeline comparator.
    candidates = [(geometry_iou_fast(pred_geoms[pi], ref_geoms[ri], cache), pi, ri)
                  for pi in range(len(predictions)) for ri in range(len(references))]
    candidates = [row for row in candidates if row[0] >= 0.5]
    candidates.sort(key=lambda row: (-row[0], geometry_box(pred_geoms[row[1]]), predictions[row[1]]["card_id"],
                                     geometry_box(ref_geoms[row[2]]), references[row[2]]["card_id"]))
    used_p: set[int] = set(); used_r: set[int] = set(); result = []
    for score, pi, ri in candidates:
        if pi in used_p or ri in used_r: continue
        used_p.add(pi); used_r.add(ri); result.append((pi, ri, score))
    return result


def empty_metrics():
    return {"paired_frames": 0, "scoreable_frames": 0, "ignored_region_frames": 0, "neutralized_predictions": 0,
            "unresolved_reference_frames": 0, "reviewed_empty_frames": 0,
            "predicted_cards": 0, "reviewed_cards": 0, "true_positives": 0,
            "false_positives": 0, "false_negatives": 0, "duplicate_proposals": 0,
            "iou_scores": [], "zero_card_outcomes_correct": 0,
            "zero_card_outcomes_incorrect": 0}


def add_frame(metric: dict, pred_outcome: dict, ref_outcome: dict) -> None:
    metric["paired_frames"] += 1
    if ref_outcome.get("ignored_regions"):
        metric["ignored_region_frames"] += 1
    if ref_outcome.get("status") not in {"detected", "empty"}:
        metric["unresolved_reference_frames"] += 1
        return
    metric["scoreable_frames"] += 1
    refs = ref_outcome.get("candidates", []) if ref_outcome["status"] == "detected" else []
    preds = pred_outcome.get("candidates", []) if pred_outcome.get("status") == "detected" else []
    metric["reviewed_cards"] += len(refs)
    metric["predicted_cards"] += len(preds)
    if ref_outcome["status"] == "empty":
        metric["reviewed_empty_frames"] += 1
        if not preds:
            metric["zero_card_outcomes_correct"] += 1
        else:
            metric["zero_card_outcomes_incorrect"] += 1
    cache: dict[int, tuple[int, int, np.ndarray]] = {}
    pred_geoms = [normalized_geometry(candidate) for candidate in preds]
    ref_geoms = [normalized_geometry(candidate, reviewed=True) for candidate in refs]
    ignore_geometries = [ReviewedIgnoreRegionGeometry.from_mapping(region["geometry"]) for region in ref_outcome.get("ignored_regions", [])]
    neutralized = {pi for pi, geometry in enumerate(pred_geoms)
                   if any(geometry_iou_fast(geometry, ignore, cache) >= 0.5 for ignore in ignore_geometries)}
    ordinary = [pred for pi, pred in enumerate(preds) if pi not in neutralized]
    ordinary_geoms = [pred_geoms[pi] for pi in range(len(preds)) if pi not in neutralized]
    metric["neutralized_predictions"] += len(neutralized)
    pairs = greedy_match(ordinary, refs, ordinary_geoms, ref_geoms, cache)
    tp = len(pairs)
    fp = len(ordinary) - tp
    fn = len(refs) - tp
    matched_p = {pi for pi, _, _ in pairs}
    duplicate = sum(
        any(geometry_iou_fast(geometry, ref_geom, cache) >= 0.5 for ref_geom in ref_geoms)
        for pi, geometry in enumerate(ordinary_geoms) if pi not in matched_p
    )
    metric["true_positives"] += tp
    metric["false_positives"] += fp
    metric["false_negatives"] += fn
    metric["duplicate_proposals"] += duplicate
    metric["iou_scores"].extend(score for _, _, score in pairs)


def generate_report():
    m0_by = {row["recording_id"]: row for row in M0["recordings"]}
    m1_by = {row["recording_id"]: row for row in M1["corrective_runs"]}
    m2_by = {row["recording_id"]: row for row in M2["recordings"]}
    pair_by = {row["recording_id"]: row for row in PAIRS["records"]}
    groups = {"all_evaluable": empty_metrics(), "outside_m4_refit_training": empty_metrics(), "overlaps_m4_refit_training": empty_metrics()}
    per_recording = []
    lineage_errors = []
    exact_pairs = 0
    excluded_ineligible_pairs = 0
    unprocessed_exact_pairs = 0

    for recording_id, preflight in m0_by.items():
        pair_record = pair_by.get(recording_id)
        if not pair_record:
            continue
        paired = [frame for frame in pair_record["frames"] if frame["paired"]]
        if not paired:
            continue
        if not preflight["evaluation_eligibility"]["eligible"]:
            excluded_ineligible_pairs += len(paired)
            continue
        exact_pairs += len(paired)
        m1_row = m1_by.get(recording_id)
        if not m1_row:
            unprocessed_exact_pairs += len(paired)
            continue
        pred_outcomes = {outcome["event_id"]: outcome for outcome in load_revision(m1_row["output_revision_id"])["outcomes"]}
        ref_revision = preflight["comparison"]["selected_visible_card_reference_revision_id"]
        ref_outcomes = {outcome["event_id"]: outcome for outcome in load_revision(ref_revision)["outcomes"]}
        record_metrics = empty_metrics()
        frame_errors = []
        for frame in paired:
            event_id = frame["event_id"]
            pred = pred_outcomes.get(event_id)
            ref = ref_outcomes.get(event_id)
            if pred is None or ref is None:
                frame_errors.append({"event_id": event_id, "reason": "missing outcome"})
                continue
            # The M0 pair flag is authoritative; verify that the prediction receipt and maintained
            # reference still carry the exact same decoded image identity.
            if pred.get("frame_identity") != ref.get("frame_identity"):
                lineage_errors.append({"recording_id": recording_id, "event_id": event_id,
                                       "reason": "prediction and reference frame receipts differ"})
                continue
            add_frame(record_metrics, pred, ref)
        training_overlap = preflight["m4_training_overlap"]
        group = "overlaps_m4_refit_training" if training_overlap else "outside_m4_refit_training"
        for target in (groups["all_evaluable"], groups[group]):
            for key in ("paired_frames", "scoreable_frames", "ignored_region_frames", "neutralized_predictions", "unresolved_reference_frames",
                        "reviewed_empty_frames", "predicted_cards", "reviewed_cards", "true_positives",
                        "false_positives", "false_negatives", "duplicate_proposals",
                        "zero_card_outcomes_correct", "zero_card_outcomes_incorrect"):
                target[key] += record_metrics[key]
            target["iou_scores"].extend(record_metrics["iou_scores"])
        per_recording.append({"recording_id": recording_id,
                              "m4_training_overlap": training_overlap,
                              "exact_paired_frames": len(paired),
                              "metrics": {k: v for k, v in record_metrics.items() if k != "iou_scores"},
                              "mean_matched_iou": round(sum(record_metrics["iou_scores"])/len(record_metrics["iou_scores"]), 6) if record_metrics["iou_scores"] else None,
                              "lineage_errors": frame_errors})


    def finish(metric):
        tp, fp, fn = metric["true_positives"], metric["false_positives"], metric["false_negatives"]
        p = tp / (tp + fp) if tp + fp else None
        r = tp / (tp + fn) if tp + fn else None
        metric["precision"] = round(p, 6) if p is not None else None
        metric["recall"] = round(r, 6) if r is not None else None
        metric["f1"] = round(2*p*r/(p+r), 6) if p is not None and r is not None and p+r else None
        scores = metric.pop("iou_scores")
        metric["mean_matched_iou"] = round(sum(scores)/len(scores), 6) if scores else None
        metric["matched_iou_count"] = len(scores)
        return metric

    for key in groups:
        groups[key] = finish(groups[key])

    report = {
        "schema_version": "0096-m3-exact-reference-evaluation/v1",
        "epic": "0096", "milestone": "M3", "date": "2026-10-17", "status": "complete",
        "inputs": {"m0_preflight": "0096-M0_Preflight.json", "m0_exact_frame_comparison": "0096-M0_Exact_Frame_Comparison.json",
                   "m1_result": "0096-M1_Run_Result.json", "m2_result": "0096-M2_Proposed_Scene_Results.json"},
        "policy": {"pairing": "M0 paired exact decoded images only; check full M1 and reference frame receipts agree",
                   "eligibility": "M0 evaluation_eligibility must be true; exclude training-only recordings",
                   "association": "reuse the pipeline-comparison geometry IoU and greedy one-to-one matcher at threshold 0.5; this rasterizes normalized polygon unions with the maintained pixel-center even-odd rule, supports concave contours, and neutralizes predictions inside reviewed ignore regions",
                   "unscored_frames": "report frames with ignore regions; neutralize predictions that overlap ignored geometry; exclude reference outcomes with status other than detected/empty",
                   "duplicate_proposal": "unmatched predicted card with IoU >= 0.5 to any reviewed card in the same frame",
                   "zero_card": "score only explicit reviewed empty outcomes; missing candidates are not empty labels"},
        "coverage": {"m0_exact_pairs_all_permissions": PAIRS["summary"]["paired_exact_frames"],
                     "exact_pairs_excluded_by_evaluation_permission": excluded_ineligible_pairs,
                     "exact_pairs_eligible": exact_pairs,
                     "eligible_pairs_without_m1_output": unprocessed_exact_pairs,
                     "scoreable_frame_count": groups["all_evaluable"]["scoreable_frames"],
                     "M0_unpaired_reference_frames": PAIRS["summary"]["unpaired_reference_frames"]},
        "segmentation": groups,
        "scene_evaluation": {"calibration": {"published": M2["summary"]["completed_runs"], "failed": M2["summary"]["failed_runs"],
                                               "publication_rate": round(M2["summary"]["completed_runs"] / len(M2["recordings"]), 6)},
                             "pile_precision_recall": "unsupported: maintained references have no reviewed pile-region targets",
                             "pose_outline_agreement": "unsupported: maintained references contain no reviewed 3D card poses or scene outlines",
                             "stacking_order_agreement": "unsupported: maintained references contain no reviewed stacking order"},
        "zero_card_review": {"explicit_reviewed_empty_frames": groups["all_evaluable"]["reviewed_empty_frames"],
                             "correct": groups["all_evaluable"]["zero_card_outcomes_correct"],
                             "incorrect": groups["all_evaluable"]["zero_card_outcomes_incorrect"],
                             "status": "unsupported" if not groups["all_evaluable"]["reviewed_empty_frames"] else "scored"},
        "lineage_errors": lineage_errors,
        "recordings": per_recording,
    }
    # Record the frame that the user reviewed in the WebUI so visual feedback has exact lineage.
    example_recording = "cardeventnet-IMG_0645"
    example_event = "cardeventnet-event-img_0645-015"
    example_m1 = m1_by[example_recording]
    example_ref_id = m0_by[example_recording]["comparison"]["selected_visible_card_reference_revision_id"]
    example_pred = next(o for o in load_revision(example_m1["output_revision_id"])["outcomes"] if o["event_id"] == example_event)
    example_ref = next(o for o in load_revision(example_ref_id)["outcomes"] if o["event_id"] == example_event)
    example_metrics = empty_metrics()
    add_frame(example_metrics, example_pred, example_ref)
    report["user_reviewed_frame"] = {
        "recording_id": example_recording, "event_id": example_event,
        "m0_exact_decoded_image_pair": True,
        "prediction_revision_id": example_m1["output_revision_id"],
        "reference_revision_id": example_ref_id,
        "prediction_candidate_count": len(example_pred["candidates"]),
        "reviewed_candidate_count": len(example_ref["candidates"]),
        "ignored_region_count": len(example_ref["ignored_regions"]),
        "matched_card_count": example_metrics["true_positives"],
        "unmatched_prediction_count": example_metrics["false_positives"],
        "unmatched_reviewed_card_count": example_metrics["false_negatives"],
        "matched_iou": example_metrics["iou_scores"][0] if example_metrics["iou_scores"] else None,
        "neutralized_prediction_count": example_metrics["neutralized_predictions"],
    }

    (REPORTS / "0096-M3_Exact_Reference_Evaluation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"coverage": report["coverage"], "segmentation": report["segmentation"],
                      "zero_card_review":report["zero_card_review"],"lineage_errors":lineage_errors},indent=2))
    return report


if __name__ == "__main__":
    generate_report()
