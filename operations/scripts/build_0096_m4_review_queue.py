#!/usr/bin/env python3
"""Freeze epic 0096's bounded, deterministic human review queue."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "operations" / "scripts"))
import evaluate_0096_m3 as evaluator
from table_evidence_analyzer.pipeline_data import ReviewedIgnoreRegionGeometry

M0, M1, M2 = evaluator.M0, evaluator.M1, evaluator.M2
PIPELINE = evaluator.PIPELINE
M0_BY = {r["recording_id"]: r for r in M0["recordings"]}
M1_BY = {r["recording_id"]: r for r in M1["corrective_runs"]}
M2_BY = {r["recording_id"]: r for r in M2["recordings"]}
PAIR_BY = {r["recording_id"]: r for r in evaluator.PAIRS["records"]}
M1_FAILURES = {M1["terminal_failure"]["recording_id"]: M1["terminal_failure"]}


def frame_diagnostics(pred: dict, ref: dict | None, scene: dict | None) -> dict:
    pred_cards = pred.get("candidates", [])
    pile_count = len(pred.get("pile_regions", []))
    diagnostics = (((scene or {}).get("proposal") or {}).get("fit_diagnostics") or {}).get("diagnostics", {})
    low_confidence = len(diagnostics.get("low_confidence_suggestion_ids", []))
    order = diagnostics.get("order") or {}
    uncertain = len(order.get("uncertain_edges", []))
    contradictions = len(order.get("contradictions", []))
    scene_piles = len((scene or {}).get("pile_regions", []))
    boxes = []
    small = False
    edge = False
    for card in pred_cards:
        norm = card["normalization"]
        width, height = norm["width"], norm["height"]
        points = [point for polygon in card["geometry"]["visible_region"]["polygons"] for point in polygon]
        if not points:
            continue
        xs = [p["x"] for p in points]; ys = [p["y"] for p in points]
        box = (min(xs), min(ys), max(xs), max(ys))
        boxes.append(box)
        area = (box[2]-box[0]) * (box[3]-box[1])
        small |= area / (width*height) < 0.01
        edge |= box[0] <= width*0.01 or box[1] <= height*0.01 or box[2] >= width*0.99 or box[3] >= height*0.99
    overlap = 0
    for i, a in enumerate(boxes):
        for b in boxes[i+1:]:
            iw=max(0,min(a[2],b[2])-max(a[0],b[0])); ih=max(0,min(a[3],b[3])-max(a[1],b[1]))
            overlap += iw*ih > 0
    result = {"card_count": len(pred_cards), "pile_region_count": max(pile_count, scene_piles),
              "low_confidence_pose_count": low_confidence, "uncertain_order_edge_count": uncertain,
              "order_contradiction_count": contradictions, "card_box_overlap_count": overlap,
              "small_card_present": small, "frame_edge_card_present": edge,
              "scene_status": (scene or {}).get("status")}
    if ref is not None:
        result.update({"review_reference_status": ref.get("status"),
                       "review_reference_card_count": len(ref.get("candidates", [])),
                       "review_ignore_region_count": len(ref.get("ignored_regions", []))})
    return result


def score_frame(pred: dict, ref: dict | None) -> dict:
    if ref is None or ref.get("status") not in {"detected", "empty"}:
        return {"reference_score_available": False, "misses": 0, "extras": 0, "duplicates": 0,
                "matched_iou_scores": []}
    preds = pred.get("candidates", []) if pred.get("status") == "detected" else []
    refs = ref.get("candidates", []) if ref.get("status") == "detected" else []
    cache = {}
    pred_geoms = [evaluator.normalized_geometry(c) for c in preds]
    ref_geoms = [evaluator.normalized_geometry(c, reviewed=True) for c in refs]
    ignores = [ReviewedIgnoreRegionGeometry.from_mapping(item["geometry"]) for item in ref.get("ignored_regions", [])]
    neutralized = {i for i, geom in enumerate(pred_geoms)
                   if any(evaluator.geometry_iou_fast(geom, ignore, cache) >= 0.5 for ignore in ignores)}
    ordinary = [c for i,c in enumerate(preds) if i not in neutralized]
    ordinary_geoms = [g for i,g in enumerate(pred_geoms) if i not in neutralized]
    pairs = evaluator.greedy_match(ordinary, refs, ordinary_geoms, ref_geoms, cache)
    used_pred={i for i,_,_ in pairs}; used_ref={i for _,i,_ in pairs}
    duplicates=sum(any(evaluator.geometry_iou_fast(geom, rgeom, cache)>=0.5 for rgeom in ref_geoms)
                   for i,geom in enumerate(ordinary_geoms) if i not in used_pred)
    return {"reference_score_available": True,
            "misses": len(refs)-len(used_ref), "extras": len(ordinary)-len(used_pred),
            "duplicates": duplicates, "neutralized_predictions": len(neutralized),
            "matched_iou_scores": [round(iou,6) for _,_,iou in pairs]}


def select_reason_codes(d: dict, score: dict, m2_status: str, m2_failure: dict | None, *, user_selected: bool) -> list[str]:
    reasons=[]
    if user_selected: reasons.append("user_flagged_near_perfect_detection; verify remaining reviewed card and pile/scene context")
    if m2_failure: reasons.append("calibration_failure_diagnostic:"+m2_failure["code"])
    if score["misses"]: reasons.append("reviewed_card_miss")
    if score["extras"]: reasons.append("unmatched_card_proposal")
    if score["duplicates"]: reasons.append("duplicate_proposal")
    if d["low_confidence_pose_count"]: reasons.append("low_confidence_pose")
    if d["uncertain_order_edge_count"] or d["order_contradiction_count"]: reasons.append("uncertain_or_conflicting_stack_order")
    if d["pile_region_count"]: reasons.append("pile_region_or_occlusion")
    if d["card_box_overlap_count"]: reasons.append("overlapping_card_candidates")
    if d["small_card_present"]: reasons.append("small_card")
    if d["frame_edge_card_present"]: reasons.append("frame_edge_card")
    if not reasons and m2_status == "complete" and d["scene_status"] == "supported":
        reasons.append("successful_scene_control")
    if not reasons: reasons.append("coverage_control")
    return reasons


rows=[]
for m0row in M0["recordings"]:
    eligibility=m0row.get("execution_eligibility")
    if not isinstance(eligibility,dict) or not eligibility.get("eligible"):
        continue
    rid=m0row["recording_id"]
    m1row=M1_BY.get(rid)
    m2row=M2_BY.get(rid)
    if m1row is None:
        rows.append({"recording_id":rid,"reviewability":"not_reviewable",
                     "reason":"terminal M1 dependency failure; no corrected detector revision is available",
                     "unprocessed_frame_count":M1_FAILURES.get(rid,{}).get("unprocessed_frame_count"),
                     "review_frames":[]})
        continue
    pred_content=evaluator.load_revision(m1row["output_revision_id"])
    pred_by={o["event_id"]:o for o in pred_content["outcomes"]}
    scene_by={}
    if m2row and m2row["status"]=="complete":
        scene_content=evaluator.load_revision(m2row["scene_revision_id"])
        scene_by={f["frame_id"]:f for f in scene_content["frames"]}
    ref_by={}
    paired_ids=set()
    reference_id=m0row.get("comparison",{}).get("selected_visible_card_reference_revision_id")
    pair_record=PAIR_BY.get(rid)
    if reference_id and pair_record and m0row.get("evaluation_eligibility",{}).get("eligible"):
        ref_by={o["event_id"]:o for o in evaluator.load_revision(reference_id)["outcomes"]}
        paired_ids={f["event_id"] for f in pair_record["frames"] if f["paired"]}
    candidates=[]
    for event_id,pred in pred_by.items():
        ref=ref_by.get(event_id) if event_id in paired_ids else None
        scene=scene_by.get(event_id)
        d=frame_diagnostics(pred,ref,scene)
        score=score_frame(pred,ref)
        user_selected=(rid=="cardeventnet-IMG_0645" and event_id=="cardeventnet-event-img_0645-015")
        failure=m2row.get("terminal_failure") if m2row and m2row["status"]=="failed" else None
        reasons=select_reason_codes(d,score,m2row["status"] if m2row else "failed",failure,user_selected=user_selected)
        issue_score=(score["misses"]*20+score["extras"]*12+score["duplicates"]*18+
                     d["low_confidence_pose_count"]*6+d["uncertain_order_edge_count"]*8+
                     d["order_contradiction_count"]*12+d["pile_region_count"]*5+
                     d["card_box_overlap_count"]*4+int(d["small_card_present"])*3+int(d["frame_edge_card_present"])*3)
        if user_selected: issue_score+=10000
        if failure: issue_score+=1000
        if not issue_score and d["scene_status"]=="supported": issue_score=1
        candidates.append({"event_id":event_id,"item_id":event_id,"issue_score":issue_score,
                           "reasons":reasons,"diagnostics":d,"score":score,
                           "scene_revision_id":(m2row.get("scene_revision_id") if m2row and m2row["status"]=="complete" else None)})
    # Deterministic category passes ensure the queue covers each major review question.
    selected=[]; selected_ids=set()
    def add_best(predicate):
        if len(selected) >= 5: return
        options=[c for c in candidates if c["event_id"] not in selected_ids and predicate(c)]
        if not options:return
        options.sort(key=lambda c:(-c["issue_score"], c["event_id"]))
        selected.append(options[0]);selected_ids.add(options[0]["event_id"])
    m2_failure=m2row.get("terminal_failure") if m2row and m2row["status"]=="failed" else None
    add_best(lambda c:"user_flagged_near_perfect_detection" in " ".join(c["reasons"]))
    if m2_failure:
        # Calibration failures have no scene frame output. Select five detector frames that show
        # the largest card/pile support, plus edges and overlaps through the deterministic score.
        others=sorted((c for c in candidates if c["event_id"] not in selected_ids),key=lambda c:(-c["issue_score"],-c["diagnostics"]["card_count"],c["event_id"]))
        for c in others[:5-len(selected)]:selected.append(c);selected_ids.add(c["event_id"])
    else:
        add_best(lambda c:c["score"]["misses"]>0 or c["score"]["extras"]>0 or c["score"]["duplicates"]>0)
        add_best(lambda c:c["diagnostics"]["low_confidence_pose_count"]>0 or c["diagnostics"]["uncertain_order_edge_count"]>0 or c["diagnostics"]["order_contradiction_count"]>0)
        add_best(lambda c:c["diagnostics"]["pile_region_count"]>0 or c["diagnostics"]["card_box_overlap_count"]>0 or c["diagnostics"]["small_card_present"] or c["diagnostics"]["frame_edge_card_present"])
        add_best(lambda c:c["diagnostics"]["scene_status"]=="supported" and c["score"]["reference_score_available"] and c["score"]["misses"]==0 and c["score"]["extras"]==0)
        others=sorted((c for c in candidates if c["event_id"] not in selected_ids),key=lambda c:(-c["issue_score"],c["event_id"]))
        for c in others[:5-len(selected)]:selected.append(c);selected_ids.add(c["event_id"])
    for c in selected:
        rev=m1row["output_revision_id"]
        c.update({"recording_id":rid,"m1_revision_id":rev,
                  "m1_revision_sha256":m1row["output_revision_content_sha256"],
                  "m2_run_id":m2row["m2_run_id"] if m2row else None,
                  "m2_status":m2row["status"] if m2row else "missing",
                  "m2_failure":m2_failure,
                  "reference_revision_id":reference_id,
                  "m4_training_overlap":m0row["m4_training_overlap"],
                  "evaluation_eligibility":m0row["evaluation_eligibility"]["eligible"],
                  "review_url":f"http://localhost:5173/recordings/{rid}/pipeline/visible_cards?view=generated&start_review=proposal&revision={rev}&item={c['event_id']}"})
    rows.append({"recording_id":rid,"reviewability":"reviewable","m1_revision_id":m1row["output_revision_id"],
                 "m2_run_id":m2row["m2_run_id"] if m2row else None,"m2_status":m2row["status"] if m2row else "missing",
                 "review_frame_count":len(selected),"review_frames":selected})

queue={"schema_version":"0096-m4-human-review-queue/v1","epic":"0096","milestone":"M4",
       "date":"2026-10-17","status":"awaiting_human_review",
       "selection_policy":{"max_frames_per_recording":5,"max_frames_total":195,
                            "recording_count":len(rows),
                            "exact_frame_evidence":"Use M3 issue metrics only for M0 exact paired frames with evaluation permission; all other choices use detector/scene diagnostics, not quality claims.",
                            "human_scope":"Review card geometry, calibration, and stacking order where available. Do not accept proposals or edit references without the operator's review.",
                            "selection":"User-flagged frame first; then calibration failures or M3 misses/extras/duplicates; pose/order diagnostics; pile/overlap; small/edge cards; one successful control; deterministic fill."},
       "counts":{"included_recordings":len(rows),"reviewable_recordings":sum(r["reviewability"]=="reviewable" for r in rows),
                 "not_reviewable_recordings":sum(r["reviewability"]!="reviewable" for r in rows),
                 "selected_frames":sum(r.get("review_frame_count",0) for r in rows),
                 "review_limit":195},"recordings":rows}
canonical=json.dumps(queue,ensure_ascii=False,sort_keys=True,separators=(",",":" )).encode()
queue["selection_sha256"]=hashlib.sha256(canonical).hexdigest()
out=ROOT/"docs/reports/0096-M4_Human_Review_Queue.json"
out.write_text(json.dumps(queue,indent=2,ensure_ascii=False)+"\n")
print(json.dumps(queue["counts"],indent=2))
print("selection sha",queue["selection_sha256"])
for r in rows:
 if r["recording_id"] in ("cardeventnet-IMG_0645","cardeventnet-IMG_0090","cardeventnet-IMG_0635","cardeventnet-IMG_0641","game-2026-08-20-01-005","game-2026-08-20-01-001"):
  print(r["recording_id"],r["reviewability"],[(f["event_id"],f["reasons"]) for f in r.get("review_frames",[])])
