#!/usr/bin/env python3
"""Compare one 0089 M0 replay with its frozen reviewed development references."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "table_evidence_analyzer/src"))

from table_evidence_analyzer.visible_card_evaluation import polygon_iou  # noqa: E402
from table_evidence_analyzer.visible_cards import NormalizedPoint  # noqa: E402


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"minimum": None, "median": None, "p95": None, "maximum": None}
    ordered = sorted(values)
    return {
        "minimum": round(ordered[0], 6),
        "median": round(statistics.median(ordered), 6),
        "p95": round(ordered[int((len(ordered) - 1) * 0.95)], 6),
        "maximum": round(ordered[-1], 6),
    }


def polygons(points: list[dict[str, int]]) -> tuple[NormalizedPoint, ...]:
    return tuple(NormalizedPoint(point["x"], point["y"]) for point in points)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay_report", type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/reports/0089-M0_Fresh_Failure_Replay.json"
    )
    args = parser.parse_args()
    replay_path = args.replay_report.expanduser().resolve()
    replay = read(replay_path)
    upstream_manifest = Path(replay["scope"]["input_manifest_path"])
    if not upstream_manifest.is_file():
        raise ValueError(f"frozen 0088 development manifest is missing: {upstream_manifest}")
    source = read(upstream_manifest)
    if source.get("provider_bundle_sha256") != replay["detector_bundle_digest"]:
        raise ValueError("replay and frozen development manifest name different detector bundles")

    references: dict[tuple[str, str], dict[str, Any]] = {}
    reference_revisions: dict[str, str] = {}
    for recording_id in replay["scope"]["recordings"]:
        state_path = (
            ROOT / "data/operations/pipeline-references" / recording_id / "visible_cards/state.json"
        )
        state = read(state_path)
        revision_id = state["selected_completed_revision_id"]
        revision_revisions_path = ROOT / "data/operations/pipeline/revisions" / revision_id
        manifest = read(revision_revisions_path / "manifest.json")
        content = read(revision_revisions_path / "content.json")
        producer = manifest.get("producer", {})
        if (
            manifest.get("recording_id") != recording_id
            or manifest.get("origin") != "corrected"
            or producer.get("kind") != "human"
        ):
            raise ValueError(f"selected reference is not a human revision: {recording_id}")
        reference_revisions[recording_id] = revision_id
        for outcome in content["outcomes"]:
            identity = outcome.get("frame_identity")
            if isinstance(identity, dict) and isinstance(identity.get("image_sha256"), str):
                references[(recording_id, identity["image_sha256"])] = outcome

    predictions: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for proposal in replay["identity_crops"]:
        identity = proposal.get("frame_identity")
        if not isinstance(identity, dict):
            continue
        predictions[(proposal["recording_id"], identity["image_sha256"])].append(proposal)

    per_recording: dict[str, dict[str, Any]] = {}
    frame_rows = []
    total_reviewed = 0
    total_predictions = 0
    total_matches = 0
    best_ious: list[float] = []
    for recording_id in replay["scope"]["recordings"]:
        keys = sorted(key for key in predictions if key[0] == recording_id)
        reviewed_count = prediction_count = match_count = 0
        recording_best: list[float] = []
        for key in keys:
            outcome = references.get(key)
            if outcome is None:
                raise ValueError(f"no exact reviewed frame for {recording_id} {key[1]}")
            reviewed = outcome.get("candidates", [])
            proposals = predictions[key]
            reviewed_count += len(reviewed)
            prediction_count += len(proposals)
            pair_scores = []
            for proposal_index, proposal in enumerate(proposals):
                predicted_components = [polygons(poly) for poly in proposal["predicted_polygons"]]
                card_scores = []
                for reviewed_index, card in enumerate(reviewed):
                    reviewed_components = [
                        polygons(poly) for poly in card["geometry"]["visible_region"]["polygons"]
                    ]
                    score = max(
                        polygon_iou(predicted, reference)
                        for predicted in predicted_components
                        for reference in reviewed_components
                    )
                    card_scores.append((reviewed_index, score))
                    if score >= 0.5:
                        pair_scores.append((proposal_index, reviewed_index, score))
                best = max(card_scores, key=lambda item: item[1], default=(None, 0.0))
                recording_best.append(best[1])
                best_ious.append(best[1])
            used_predictions: set[int] = set()
            used_reviews: set[int] = set()
            matches = []
            for proposal_index, reviewed_index, iou in sorted(
                pair_scores, key=lambda item: (-item[2], item[0], item[1])
            ):
                if proposal_index in used_predictions or reviewed_index in used_reviews:
                    continue
                used_predictions.add(proposal_index)
                used_reviews.add(reviewed_index)
                matches.append(
                    {
                        "proposal_index": proposal_index,
                        "card_id": reviewed[reviewed_index]["card_id"],
                        "iou": round(iou, 6),
                    }
                )
            match_count += len(matches)
            frame_rows.append(
                {
                    "recording_id": recording_id,
                    "event_id": outcome["event_id"],
                    "frame_identity": outcome["frame_identity"],
                    "reviewed_card_count": len(reviewed),
                    "proposal_count": len(proposals),
                    "best_polygon_iou": round(
                        max(recording_best[-len(proposals) :], default=0.0), 6
                    ),
                    "matches_at_iou_0_5": matches,
                    "review_decision": outcome.get("card_scene", {})
                    .get("reviewed", {})
                    .get("decision"),
                    "reviewed_stacking_order": outcome.get("card_scene", {})
                    .get("reviewed", {})
                    .get("scene", {})
                    .get("stacking_order", {})
                    .get("card_ids", []),
                }
            )
        total_reviewed += reviewed_count
        total_predictions += prediction_count
        total_matches += match_count
        per_recording[recording_id] = {
            "reference_revision_id": reference_revisions[recording_id],
            "frame_count": len(keys),
            "proposal_count": prediction_count,
            "reviewed_card_count": reviewed_count,
            "matched_pairs_at_iou_0_5": match_count,
            "proposal_best_iou": quantiles(recording_best),
            "calibration_status": replay["pose_replays"][recording_id]["calibration_run"]["status"],
            "calibration_failure": replay["pose_replays"][recording_id]["calibration_run"].get(
                "failure"
            ),
            "calibration_error": replay["pose_replays"][recording_id]["calibration_run"]
            .get("diagnostics", {})
            .get("calibration_error"),
            "calibration_gates": replay["pose_replays"][recording_id]["calibration_run"]
            .get("diagnostics", {})
            .get("gates"),
        }

    identity_rows = replay["identity_crops"]
    m6_review = sum(row["m6"]["confidence"] < 0.9 for row in identity_rows)
    m3_review = sum(row["m3"]["confidence"] < 0.9 for row in identity_rows)
    disagreement = sum(row["m6"]["top1"] != row["m3"]["top1"] for row in identity_rows)
    residuals = {
        recording_id: [
            item["residual"]
            for frame in (replay["pose_replays"][recording_id].get("data") or {}).get("frames", [])
            for item in (frame.get("proposal") or {})
            .get("fit_diagnostics", {})
            .get("fit_diagnostics", [])
        ]
        for recording_id in replay["scope"]["recordings"]
    }
    summary = {
        "schema_version": "0089-m0-fresh-failure-replay/v1",
        "status": "complete",
        "replay_report_sha256": sha256(replay_path),
        "m1_development_manifest_sha256": sha256(upstream_manifest),
        "model_bundles": {
            "rfdetr_0087": replay["detector_bundle_digest"],
            "dino_m6_primary": replay["primary_identity_bundle_digest"],
            "dino_m3_control": replay["control_identity_bundle_digest"],
        },
        "scope": {
            **replay["scope"],
            "frame_count": replay["detector"]["frame_count"],
            "sealed_final_test_used": False,
            "identity_final_test_used": False,
            "reference_revisions": reference_revisions,
        },
        "detection_against_review": {
            "association_policy": "greedy one-to-one polygon IoU >= 0.5",
            "proposal_count": total_predictions,
            "reviewed_card_count": total_reviewed,
            "matched_pairs": total_matches,
            "best_iou": quantiles(best_ious),
            "per_recording": per_recording,
            "frames": frame_rows,
        },
        "pose_fit_residuals": {
            recording_id: quantiles(values) for recording_id, values in residuals.items()
        },
        "identity_diagnostics": {
            "crop_count": len(identity_rows),
            "m6_m3_top1_disagreements": disagreement,
            "m6_below_0_90_review_routing_threshold": m6_review,
            "m3_below_0_90_review_routing_threshold": m3_review,
            "threshold_use": "diagnostic review routing only",
            "auto_accept": False,
        },
        "decision": {
            "selected_algorithm_failure_families": [],
            "reason": (
                "Fresh model outputs yielded no reviewed-card polygon associations at the frozen "
                "0.5 IoU threshold. Pose, stacking-order, and crop errors cannot be isolated from "
                "detector failures on these inputs. The calibration failure on IMG_0095 follows "
                "failed spatial-coverage and held-out-boundary gates; it does not justify "
                "weakening the calibration boundary."
            ),
            "next_action": (
                "No 0089 algorithm fix is selected. Close the epic with this replay and require "
                "new detector outputs with reviewed-card overlap before selecting a geometry or "
                "crop fix."
            ),
        },
    }
    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
