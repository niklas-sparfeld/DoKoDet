#!/usr/bin/env python3
"""Classify retained 0096 exact-reference failures for epic 0099 M1."""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import pathlib
import statistics
from typing import Any

from table_evidence_analyzer.pipeline_data import VisibleCardData

from doko_operations.card_plane_calibration import CalibrationRecipe, calibrate_recording
from doko_operations.proposed_card_scene_processor import visible_card_data_to_local_result

ROOT = pathlib.Path(__file__).resolve().parents[2]
EVALUATOR_PATH = ROOT / "operations/scripts/evaluate_0096_m3.py"
MANIFEST_PATH = ROOT / "docs/reports/0099-M0_Experiment_Manifest.json"


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def score(candidate: dict[str, Any]) -> float | None:
    for item in candidate.get("model_scores", []):
        if isinstance(item, dict) and isinstance(item.get("score"), (int, float)):
            return float(item["score"])
    return None


def summarize(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "minimum": None, "median": None, "maximum": None}
    return {
        "count": len(values),
        "minimum": round(min(values), 6),
        "median": round(statistics.median(values), 6),
        "maximum": round(max(values), 6),
    }


def calibration_evidence(evidence_root: pathlib.Path, m2: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for item in m2["recordings"]:
        if item.get("status") != "failed" or not item.get("failure_code"):
            continue
        run_path = (
            evidence_root / "data/operations/pipeline/runs" / item["m2_run_id"] / "state.json"
        )
        state = load_json(run_path)
        run = state.get("metrics", {}).get("calibration_run", {})
        diagnostics = run.get("diagnostics", {})
        revision_id = item["m1_revision_id"]
        revision_root = evidence_root / "data/operations/pipeline/revisions" / revision_id
        content_path = revision_root / "content.json"
        revision_manifest = load_json(revision_root / "manifest.json")
        if revision_manifest["content_sha256"] != item["m1_revision_sha256"]:
            raise ValueError(f"M1 revision digest mismatch for {item['recording_id']}")
        visible_cards = VisibleCardData.from_mapping(load_json(content_path))
        local_result = visible_card_data_to_local_result(
            visible_cards,
            recording_id=item["recording_id"],
            source_revision=revision_id,
        )
        recipe_values = {
            key: value for key, value in diagnostics["recipe"].items() if key != "schema_version"
        }
        replay = calibrate_recording(local_result, recipe=CalibrationRecipe(**recipe_values))
        replay_failure_code = None if replay.failure is None else replay.failure.code
        records.append(
            {
                "recording_id": item["recording_id"],
                "run_id": item["m2_run_id"],
                "failure_code": item["failure_code"],
                "progress": state.get("progress"),
                "unprocessed_frame_count": item.get("unprocessed_frame_count"),
                "run_state_sha256": sha256(run_path),
                "m1_revision_sha256": sha256(content_path),
                "run_digest": run.get("run_digest"),
                "replay_run_digest": replay.run_digest,
                "replay_matches_recorded_run": replay.run_digest == run.get("run_digest"),
                "replay_failure_code": replay_failure_code,
                "candidate_yield": diagnostics.get("candidate_yield"),
                "gates": diagnostics.get("gates"),
                "advisory_checks": diagnostics.get("advisory_checks"),
                "failed_gates": diagnostics.get("failed_gates"),
                "fit": {
                    key: diagnostics.get("fit", {}).get(key)
                    for key in (
                        "accepted_card_count",
                        "fit_attempt_count",
                        "median_boundary_error_px",
                        "p90_boundary_error_px",
                        "quality_passed",
                    )
                },
                "validation": {
                    "fit_count": diagnostics.get("validation", {}).get("fit_count"),
                    "held_out_count": diagnostics.get("validation", {}).get("held_out_count"),
                    "held_out_summary": diagnostics.get("validation", {}).get("held_out_summary"),
                },
                "calibration_error": diagnostics.get("calibration_error"),
            }
        )
    return records


def analyze(evidence_root: pathlib.Path) -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH)
    expected_artifacts = manifest["baseline"]["input_artifacts"]
    artifact_hashes = {}
    for name, expected in expected_artifacts.items():
        path = evidence_root / "docs/reports" / name
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"frozen input digest mismatch for {name}: {actual}")
        artifact_hashes[name] = actual

    for relative, expected in manifest["baseline"]["source_file_sha256"].items():
        actual = sha256(ROOT / relative)
        if actual != expected:
            raise ValueError(f"frozen source digest mismatch for {relative}: {actual}")

    spec = importlib.util.spec_from_file_location("evaluate_0096_m3", EVALUATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import evaluator: {EVALUATOR_PATH}")
    evaluator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator)
    reports = evidence_root / "docs/reports"
    evaluator.M0 = load_json(reports / "0096-M0_Preflight.json")
    evaluator.PAIRS = load_json(reports / "0096-M0_Exact_Frame_Comparison.json")
    evaluator.M1 = load_json(reports / "0096-M1_Run_Result.json")
    evaluator.M2 = load_json(reports / "0096-M2_Proposed_Scene_Results.json")
    evaluator.PIPELINE = evidence_root / "data/operations/pipeline"

    m0_by = {row["recording_id"]: row for row in evaluator.M0["recordings"]}
    m1_by = {row["recording_id"]: row for row in evaluator.M1["corrective_runs"]}
    pairs_by = {row["recording_id"]: row for row in evaluator.PAIRS["records"]}
    outside_rows = [
        row for row in manifest["per_recording_baseline"] if not row["m4_training_overlap"]
    ]
    outside_ids = {row["recording_id"] for row in outside_rows}
    counts: collections.Counter[str] = collections.Counter()
    per_recording: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    tags: collections.Counter[str] = collections.Counter()
    areas: dict[str, list[float]] = collections.defaultdict(list)
    scores: dict[str, list[float]] = collections.defaultdict(list)
    pile_statuses: collections.Counter[str] = collections.Counter()
    scoreless_prediction_count = 0

    for recording_id in sorted(outside_ids):
        preflight = m0_by[recording_id]
        prediction_run = m1_by[recording_id]
        prediction_outcomes = {
            item["event_id"]: item
            for item in evaluator.load_revision(prediction_run["output_revision_id"])["outcomes"]
        }
        reference_revision = preflight["comparison"]["selected_visible_card_reference_revision_id"]
        reference_outcomes = {
            item["event_id"]: item
            for item in evaluator.load_revision(reference_revision)["outcomes"]
        }
        pair_frames = pairs_by[recording_id]["frames"]

        for frame in pair_frames:
            if not frame["paired"]:
                continue
            counts["paired_frames"] += 1
            event_id = frame["event_id"]
            prediction = prediction_outcomes.get(event_id)
            reference = reference_outcomes.get(event_id)
            if prediction is None or reference is None:
                raise ValueError(f"missing exact paired outcome: {recording_id}/{event_id}")
            if prediction.get("frame_identity") != reference.get("frame_identity"):
                raise ValueError(f"frame identity mismatch: {recording_id}/{event_id}")
            if reference.get("ignored_regions"):
                counts["ignored_region_frames"] += 1
            if reference.get("status") not in {"detected", "empty"}:
                counts["unresolved_reference_frames"] += 1
                continue
            if reference.get("status") == "empty":
                counts["reviewed_empty_frames"] += 1

            predicted = (
                prediction.get("candidates", []) if prediction.get("status") == "detected" else []
            )
            reviewed = (
                reference.get("candidates", []) if reference.get("status") == "detected" else []
            )
            predicted_geometries = [
                evaluator.normalized_geometry(candidate) for candidate in predicted
            ]
            reviewed_geometries = [
                evaluator.normalized_geometry(candidate, reviewed=True) for candidate in reviewed
            ]
            cache: dict[int, Any] = {}
            ignored = [
                evaluator.ReviewedIgnoreRegionGeometry.from_mapping(item["geometry"])
                for item in reference.get("ignored_regions", [])
            ]
            neutralized = {
                index
                for index, geometry in enumerate(predicted_geometries)
                if any(
                    evaluator.geometry_iou_fast(geometry, region, cache) >= 0.5
                    for region in ignored
                )
            }
            ordinary_predictions = [
                candidate for index, candidate in enumerate(predicted) if index not in neutralized
            ]
            ordinary_geometries = [
                geometry
                for index, geometry in enumerate(predicted_geometries)
                if index not in neutralized
            ]
            matches = evaluator.greedy_match(
                ordinary_predictions, reviewed, ordinary_geometries, reviewed_geometries, cache
            )
            matched_predictions = {item[0] for item in matches}
            matched_references = {item[1] for item in matches}
            false_positives = [
                index
                for index in range(len(ordinary_predictions))
                if index not in matched_predictions
            ]
            false_negatives = [
                index for index in range(len(reviewed)) if index not in matched_references
            ]
            counts["scoreable_frames"] += 1
            counts["true_positives"] += len(matches)
            counts["false_positives"] += len(false_positives)
            counts["false_negatives"] += len(false_negatives)
            per_recording[recording_id].update(
                true_positives=len(matches),
                false_positives=len(false_positives),
                false_negatives=len(false_negatives),
            )
            pile_statuses[prediction.get("pile_detection_status", "missing")] += 1

            for index, candidate in enumerate(ordinary_predictions):
                candidate_score = score(candidate)
                if candidate_score is None:
                    scoreless_prediction_count += 1
                else:
                    scores["false_positive" if index in false_positives else "matched"].append(
                        candidate_score
                    )
                if index not in false_positives:
                    continue
                geometry = ordinary_geometries[index]
                x0, y0, x1, y1 = evaluator.geometry_box(geometry)
                raster = evaluator.raster_geometry(geometry)[2]
                areas["false_positive"].append(int(raster.sum()))
                edge = x0 <= 10 or y0 <= 10 or x1 >= 990 or y1 >= 990
                tags["false_positive_edge"] += int(edge)
                tags["false_positive_interior"] += int(not edge)
                duplicate = any(
                    evaluator.geometry_iou_fast(geometry, item, cache) >= 0.5
                    for item in reviewed_geometries
                )
                tags["false_positive_duplicate_overlap"] += int(duplicate)
                overlaps_prediction = any(
                    evaluator.geometry_iou_fast(geometry, other, cache) >= 0.25
                    for other_index, other in enumerate(ordinary_geometries)
                    if other_index != index
                )
                tags["false_positive_peer_iou_at_least_0_25"] += int(overlaps_prediction)

            for index, geometry in enumerate(reviewed_geometries):
                if index not in false_negatives:
                    continue
                x0, y0, x1, y1 = evaluator.geometry_box(geometry)
                raster = evaluator.raster_geometry(geometry)[2]
                areas["false_negative"].append(int(raster.sum()))
                edge = x0 <= 10 or y0 <= 10 or x1 >= 990 or y1 >= 990
                tags["false_negative_edge"] += int(edge)
                tags["false_negative_interior"] += int(not edge)

            for _prediction_index, reference_index, _iou in matches:
                raster = evaluator.raster_geometry(reviewed_geometries[reference_index])[2]
                areas["matched_reference"].append(int(raster.sum()))

    expected = manifest["baseline_metrics"]["outside_m4_refit_training"]
    for key in ("scoreable_frames", "true_positives", "false_positives", "false_negatives"):
        expected_key = {
            "scoreable_frames": "scoreable_frames",
            "true_positives": "true_positives",
            "false_positives": "false_positives",
            "false_negatives": "false_negatives",
        }[key]
        if counts[key] != expected[expected_key]:
            raise ValueError(f"recomputed {key} {counts[key]} != frozen {expected[expected_key]}")

    def area_summary(key: str) -> dict[str, int | None]:
        values = sorted(areas[key])
        if not values:
            return {"count": 0, "minimum": None, "median": None, "p90": None}
        return {
            "count": len(values),
            "minimum": values[0],
            "median": int(statistics.median(values)),
            "p90": values[int((len(values) - 1) * 0.9)],
        }

    m2 = evaluator.M2
    terminal_failure = manifest["terminal_m1_failure"]
    terminal_run_id = terminal_failure.get("run_id")
    terminal_path = (
        evidence_root / "data/operations/pipeline/runs" / terminal_run_id / "state.json"
        if terminal_run_id
        else None
    )
    terminal_state = load_json(terminal_path) if terminal_path and terminal_path.is_file() else None
    return {
        "schema_version": "0099-m1-failure-diagnosis/v1",
        "epic": "0099",
        "milestone": "M1",
        "status": "complete",
        "evidence_scope": (
            "Frozen 0096 detector outputs and maintained references. No media was opened, "
            "and no detector or scene proposal processor was rerun. The four calibration "
            "calls were replayed from saved detector outputs."
        ),
        "not_a_holdout": (
            "The source groups were previously examined during 0096. These measurements "
            "do not establish generalization."
        ),
        "inputs": {
            "m0_manifest_sha256": sha256(MANIFEST_PATH),
            "frozen_artifact_sha256": artifact_hashes,
            "comparison_policy": (
                "Reuse evaluate_0096_m3.py geometry, ignore-region, one-to-one matching, "
                "and duplicate policies."
            ),
        },
        "outside_refit_training": {
            "scoreable_frames": counts["scoreable_frames"],
            "true_positives": counts["true_positives"],
            "false_positives": counts["false_positives"],
            "false_negatives": counts["false_negatives"],
            "duplicate_proposals": tags["false_positive_duplicate_overlap"],
            "precision": round(
                counts["true_positives"] / (counts["true_positives"] + counts["false_positives"]), 6
            ),
            "recall": round(
                counts["true_positives"] / (counts["true_positives"] + counts["false_negatives"]), 6
            ),
        },
        "ranked_failure_families": [
            {
                "rank": 1,
                "family": "unmatched predicted visible-card masks",
                "count": counts["false_positives"],
                "by_recording": {
                    recording_id: values["false_positives"]
                    for recording_id, values in sorted(per_recording.items())
                    if values["false_positives"]
                },
                "geometry_tags": {
                    "frame_edge": tags["false_positive_edge"],
                    "interior": tags["false_positive_interior"],
                    "overlaps_reviewed_card_at_duplicate_threshold": tags[
                        "false_positive_duplicate_overlap"
                    ],
                    "overlaps_another_prediction_at_iou_0_25": tags[
                        "false_positive_peer_iou_at_least_0_25"
                    ],
                },
                "prediction_mask_area_pixels": area_summary("false_positive"),
                "confidence_score": summarize(scores["false_positive"]),
            },
            {
                "rank": 2,
                "family": "unmatched reviewed visible cards",
                "count": counts["false_negatives"],
                "by_recording": {
                    recording_id: values["false_negatives"]
                    for recording_id, values in sorted(per_recording.items())
                    if values["false_negatives"]
                },
                "geometry_tags": {
                    "frame_edge": tags["false_negative_edge"],
                    "interior": tags["false_negative_interior"],
                },
                "reference_mask_area_pixels": area_summary("false_negative"),
            },
        ],
        "context": {
            "comparison_limits": {
                "exact_paired_frames": counts["paired_frames"],
                "scoreable_frames": counts["scoreable_frames"],
                "ignored_region_frames": counts["ignored_region_frames"],
                "unresolved_reference_frames": counts["unresolved_reference_frames"],
                "explicit_reviewed_empty_frames": counts["reviewed_empty_frames"],
            },
            "matched_reference_area_pixels": area_summary("matched_reference"),
            "matched_prediction_confidence_score": summarize(scores["matched"]),
            "predictions_without_confidence_score": scoreless_prediction_count,
            "pile_status_in_scored_frames": dict(sorted(pile_statuses.items())),
            "pile_relation_quality": (
                "unsupported: references contain no reviewed pile-region targets"
            ),
            "pose_or_stacking_relation_quality": (
                "unsupported: references contain no reviewed poses, outlines, or stacking order"
            ),
        },
        "calibration_failures": calibration_evidence(evidence_root, m2),
        "terminal_runtime_failure": {
            "recording_id": terminal_failure["recording_id"],
            "run_id": terminal_run_id,
            "failure": terminal_state.get("terminal_failure") if terminal_state else None,
            "progress": terminal_state.get("progress") if terminal_state else None,
            "output_revision_ids": terminal_state.get("output_revision_ids")
            if terminal_state
            else None,
            "run_state_sha256": sha256(terminal_path)
            if terminal_path and terminal_path.is_file()
            else None,
            "classification": (
                "backend lifecycle failure before a frame completed; no detector or "
                "postprocessing behavior was exercised"
            ),
        },
        "fixture_decision": {
            "calibration_handoff": (
                "The IMG_0641 fit passes its fit-quality gate, but six-decimal transform "
                "serialization fails the reciprocal-transform gate. A minimal fixture is included."
            ),
            "segmentation_postprocessing": (
                "No single postprocessing defect is reproduced by the retained scoreable "
                "outputs. Geometry tags do not establish cause."
            ),
        },
        "candidate_readiness": {
            "automated_fix_evidence": [
                (
                    "Exact reviewed-card references support bounded assessment of segmentation "
                    "false positives and misses on the frozen corpus."
                ),
                ("Confidence distributions overlap. M1 does not establish a confidence-only rule."),
                (
                    "The IMG_0641 matrix serialization handoff has a reproducible fixture. "
                    "Any fix must preserve calibration gates."
                ),
            ],
            "insufficient_evidence": [
                (
                    "Pile relations, pose, stacking order, and zero-card quality have no "
                    "reviewed truth."
                ),
                (
                    "The four calibration failures do not justify lowering population, fit, "
                    "or transform safety gates."
                ),
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=pathlib.Path, default=ROOT)
    parser.add_argument(
        "--output", type=pathlib.Path, default=ROOT / "docs/reports/0099-M1_Failure_Diagnosis.json"
    )
    args = parser.parse_args()
    report = analyze(args.evidence_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {"output": str(args.output), "families": report["outside_refit_training"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
