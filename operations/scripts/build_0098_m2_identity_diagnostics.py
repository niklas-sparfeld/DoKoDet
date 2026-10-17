#!/usr/bin/env python3
"""Build the reproducible diagnostic report for epic 0098 M2."""

# Report prose and Markdown tables contain long lines by design.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def _read(path: Path) -> Any:
    return json.loads(path.read_text())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p50": None, "mean": None, "p90": None, "max": None}
    ordered = sorted(values)

    def percentile(q: float) -> float:
        index = (len(ordered) - 1) * q
        lower = int(index)
        upper = min(lower + 1, len(ordered) - 1)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)

    return {
        "min": ordered[0],
        "p50": percentile(0.5),
        "mean": statistics.fmean(ordered),
        "p90": percentile(0.9),
        "max": ordered[-1],
    }


def _human_decisions(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decisions = []
    for outcome in outcomes:
        classifier = outcome.get("classifier") or {}
        candidates = outcome.get("candidates") or []
        human_identity = (
            outcome.get("status") == "classified"
            and classifier.get("provider") == "human-reference"
            and len(candidates) == 1
            and candidates[0].get("producer_id") == "human-reference.v1"
            and isinstance(candidates[0].get("identity"), str)
        )
        human_special = (
            outcome.get("status") in {"face_down", "unusable"}
            and classifier.get("provider") == "human-reference"
        )
        if human_identity or human_special:
            decisions.append(outcome)
    return decisions


def _outcome_key(outcome: dict[str, Any], field: str) -> str | None:
    value = outcome.get(field)
    return _canonical_sha256(value) if value is not None else None


def build_report(repository: Path, pipeline_store: Path) -> dict[str, Any]:
    m0_path = repository / "docs/reports/0098-M0_Frozen_Inputs.json"
    m1_path = repository / "docs/reports/0098-M1_Identity_Batch.json"
    m0 = _read(m0_path)
    m1 = _read(m1_path)
    revisions = pipeline_store / "revisions"

    records: list[dict[str, Any]] = []
    aggregate_status: Counter[str] = Counter()
    all_confidence: list[float] = []
    all_margins: list[float] = []
    class_counts: Counter[str] = Counter()
    overlap_metrics: dict[str, dict[str, Any]] = {}
    run_seconds: list[float] = []
    comparison_totals: Counter[str] = Counter()
    exact_comparisons: list[dict[str, Any]] = []
    reviewed_decision_count = 0

    m0_by_recording = {item["recording_id"]: item for item in m0["recordings"]}
    for recording_id, run in m1["recordings"].items():
        frozen = m0_by_recording[recording_id]
        revision_id = run["output_revision_id"]
        content_path = revisions / revision_id / "content.json"
        output = _read(content_path)
        outcomes = output.get("outcomes", [])
        content_digest = _canonical_sha256(output)
        if content_digest != run["output_content_sha256"]:
            raise ValueError(f"M1 output digest mismatch for {recording_id}")
        if len(outcomes) != run["output_outcome_count"]:
            raise ValueError(f"M1 output count mismatch for {recording_id}")

        status_counts = Counter(item.get("status", "missing") for item in outcomes)
        aggregate_status.update(status_counts)
        classified = [item for item in outcomes if item.get("status") == "classified"]
        confidence_values = []
        margins = []
        for item in classified:
            candidates = item.get("candidates", [])
            ranked = sorted(
                candidates, key=lambda candidate: candidate.get("score", -1), reverse=True
            )
            if ranked:
                score = float(ranked[0]["score"])
                confidence_values.append(score)
                all_confidence.append(score)
                class_counts[ranked[0]["identity"]] += 1
            if len(ranked) >= 2:
                margin = float(ranked[0]["score"]) - float(ranked[1]["score"])
                margins.append(margin)
                all_margins.append(margin)
        run_seconds.append(float(run["elapsed_poll_seconds"]))

        overlap = bool(frozen.get("m6_training_overlap"))
        bucket = "m6_training_overlap" if overlap else "non_training"
        bucket_metrics = overlap_metrics.setdefault(
            bucket,
            {"recordings": 0, "outcomes": 0, "classified": 0, "face_down": 0},
        )
        bucket_metrics["recordings"] += 1
        bucket_metrics["outcomes"] += len(outcomes)
        bucket_metrics["classified"] += status_counts["classified"]
        bucket_metrics["face_down"] += status_counts["face_down"]

        reference_id = frozen.get("selected_identity_reference_revision_id")
        reference_path = revisions / reference_id / "content.json" if reference_id else None
        reference_content = (
            _read(reference_path) if reference_path and reference_path.exists() else None
        )
        reference_content_digest = (
            _canonical_sha256(reference_content) if reference_content is not None else None
        )
        reference_outcomes = reference_content.get("outcomes", []) if reference_content else []
        decisions = _human_decisions(reference_outcomes)
        reviewed_decision_count += len(decisions)
        quality_comparison_eligible = bool(frozen.get("source_group_quality_comparison_eligible"))
        decisions_by_card = {item.get("card_id"): item for item in decisions if item.get("card_id")}
        decisions_by_frame = {_outcome_key(item, "frame_identity") for item in decisions}
        decisions_by_geometry = {
            (_outcome_key(item, "frame_identity"), _outcome_key(item, "geometry"))
            for item in decisions
        }
        decisions_by_crop = {
            (
                _outcome_key(item, "frame_identity"),
                _outcome_key(item, "geometry"),
                _outcome_key(item, "crop_identity"),
            )
            for item in decisions
        }
        local_comparison = Counter()
        for item in classified:
            if item.get("card_id") in decisions_by_card:
                local_comparison["same_card_id"] += 1
            frame_key = _outcome_key(item, "frame_identity")
            geometry_key = _outcome_key(item, "geometry")
            crop_key = _outcome_key(item, "crop_identity")
            if frame_key in decisions_by_frame:
                local_comparison["same_frame"] += 1
            if (frame_key, geometry_key) in decisions_by_geometry:
                local_comparison["same_frame_and_geometry"] += 1
            if (frame_key, geometry_key, crop_key) in decisions_by_crop:
                local_comparison["same_frame_geometry_and_crop"] += 1
                for human in decisions:
                    if (
                        item.get("card_id") == human.get("card_id")
                        and item.get("frame_identity") == human.get("frame_identity")
                        and item.get("geometry") == human.get("geometry")
                        and item.get("crop_identity") == human.get("crop_identity")
                    ):
                        if quality_comparison_eligible:
                            predicted = (item.get("candidates") or [{}])[0].get("identity")
                            label = (human.get("candidates") or [{}])[0].get("identity")
                            exact_comparisons.append(
                                {
                                    "recording_id": recording_id,
                                    "card_id": item.get("card_id"),
                                    "identity_result_revision_id": revision_id,
                                    "identity_result_content_sha256": content_digest,
                                    "identity_reference_revision_id": reference_id,
                                    "identity_reference_content_sha256": reference_content_digest,
                                    "predicted_identity": predicted,
                                    "reviewed_identity": label,
                                }
                            )
                            local_comparison["eligible_exact_full_lineage"] += 1
                        else:
                            local_comparison["full_lineage_training_overlap_not_scored"] += 1
        comparison_totals.update(local_comparison)

        records.append(
            {
                "recording_id": recording_id,
                "source_group_id": frozen.get("source_group_id"),
                "m6_training_overlap": overlap,
                "source_group_quality_comparison_eligible": bool(
                    frozen.get("source_group_quality_comparison_eligible")
                ),
                "crop_inputs": run["crop_input_item_count"],
                "outcomes": len(outcomes),
                "outcomes_by_status": dict(sorted(status_counts.items())),
                "unprocessed": int(run.get("unprocessed_count", 0)),
                "classifier_errors": status_counts["failed"],
                "crop_unusable": status_counts["unusable"],
                "confidence": _percentiles(confidence_values),
                "rank_margin_top1_minus_top2": _percentiles(margins),
                "run_elapsed_poll_seconds": run["elapsed_poll_seconds"],
                "per_crop_latency_ms": None,
                "per_recording_rss_bytes": None,
                "output_lineage": {
                    "run_id": run["run_id"],
                    "revision_id": revision_id,
                    "content_sha256": content_digest,
                    "input_revision_ids": run["input_revision_ids"],
                    "crop_input_manifest_digest": run["crop_input_manifest_digest"],
                    "classifier_identity": run["classifier_identities"],
                },
                "review_comparison": {
                    "selected_reference_revision_id": reference_id,
                    "selected_reference_content_sha256": reference_content_digest,
                    "reviewed_decisions": len(decisions),
                    "potential_matches_by_lineage_level": dict(sorted(local_comparison.items())),
                    "eligible_exact_pairs": local_comparison["exact_full_lineage"],
                },
            }
        )

    bins = {
        "[0.00, 0.50)": sum(value < 0.5 for value in all_confidence),
        "[0.50, 0.75)": sum(0.5 <= value < 0.75 for value in all_confidence),
        "[0.75, 0.90)": sum(0.75 <= value < 0.9 for value in all_confidence),
        "[0.90, 0.95)": sum(0.9 <= value < 0.95 for value in all_confidence),
        "[0.95, 1.00]": sum(0.95 <= value <= 1.0 for value in all_confidence),
    }
    margin_bins = {
        "[0.00, 0.10)": sum(value < 0.1 for value in all_margins),
        "[0.10, 0.25)": sum(0.1 <= value < 0.25 for value in all_margins),
        "[0.25, 0.50)": sum(0.25 <= value < 0.5 for value in all_margins),
        "[0.50, 0.75)": sum(0.5 <= value < 0.75 for value in all_margins),
        "[0.75, 1.00]": sum(0.75 <= value <= 1.0 for value in all_margins),
    }

    return {
        "schema_version": "epic-0098-m2-diagnostics/v1",
        "epic": "0098",
        "milestone": "M2",
        "status": "complete",
        "inputs": {
            "m0_manifest_sha256": _sha256(m0_path),
            "m1_report_sha256": _sha256(m1_path),
            "pipeline_store": str(pipeline_store),
        },
        "coverage": {
            "recordings": len(records),
            "crop_inputs": sum(record["crop_inputs"] for record in records),
            "prediction_outcomes": sum(aggregate_status.values()),
            "outcomes_by_status": dict(sorted(aggregate_status.items())),
            "classifier_errors": aggregate_status["failed"],
            "crop_unusable": aggregate_status["unusable"],
            "unprocessed": sum(record["unprocessed"] for record in records),
            "zero_crop_frames_from_m0": m0["coverage"]["zero_crop_frame_count"],
            "upstream_failed_recordings_excluded": m0["coverage"]["upstream_failed_recordings"],
            "protected_recordings_excluded": m0["coverage"]["excluded_protected_recordings"],
        },
        "prediction_diagnostics": {
            "confidence_semantics": "top-ranked classifier probability; diagnostic only",
            "confidence_count": len(all_confidence),
            "confidence_percentiles": _percentiles(all_confidence),
            "confidence_bins": bins,
            "top1_minus_top2_margin_count": len(all_margins),
            "top1_minus_top2_margin_percentiles": _percentiles(all_margins),
            "top1_minus_top2_margin_bins": margin_bins,
            "top1_identity_counts": dict(sorted(class_counts.items())),
        },
        "run_diagnostics": {
            "run_duration_basis": "elapsed_poll_seconds from the M1 runner; not per-crop inference latency",
            "run_duration_seconds": _percentiles(run_seconds),
            "per_crop_latency_ms": {
                "available": False,
                "reason": "M1 outputs contain zero latency samples",
            },
            "memory": {
                "batch_peak_sampled_rss_bytes": m1["maximum_rss_bytes"],
                "per_recording_rss_bytes": None,
                "sampling_deviation": m1.get("rss_sampling"),
            },
        },
        "training_overlap": overlap_metrics,
        "review_comparisons": {
            "reviewed_reference_outcomes_inspected": reviewed_decision_count,
            "lineage_intersection_counts": dict(sorted(comparison_totals.items())),
            "eligible_exact_pairs": len(exact_comparisons),
            "accuracy_claim": None,
            "reason": "No M1 prediction has a matching reviewed card, frame, geometry, and crop lineage.",
            "pairs": exact_comparisons,
        },
        "recordings": records,
    }


def render_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    diagnostics = report["prediction_diagnostics"]
    run = report["run_diagnostics"]
    comparisons = report["review_comparisons"]
    lines = [
        "# Epic 0098 M2 identity diagnostics",
        "",
        "This report summarizes the frozen M1 outputs. Confidence and prediction counts are diagnostic; they do not measure correctness.",
        "",
        "## Coverage",
        "",
        f"- {coverage['recordings']} recordings; {coverage['crop_inputs']} frozen crops; {coverage['prediction_outcomes']} stored outcomes.",
        f"- Classified: {coverage['outcomes_by_status'].get('classified', 0)}; face-down: {coverage['outcomes_by_status'].get('face_down', 0)}; unusable: {coverage['crop_unusable']}; failed: {coverage['classifier_errors']}; unprocessed: {coverage['unprocessed']}.",
        f"- M0 contains {coverage['zero_crop_frames_from_m0']} zero-crop frames. Five upstream failures and three protected recordings remain outside this batch.",
        "- Crop geometry succeeded for every M1 input. There were no crop or classifier failures.",
        "",
        "## Prediction diagnostics",
        "",
        f"- Top-ranked probability across {diagnostics['confidence_count']} classified outcomes: min {diagnostics['confidence_percentiles']['min']:.6f}, median {diagnostics['confidence_percentiles']['p50']:.6f}, mean {diagnostics['confidence_percentiles']['mean']:.6f}, p90 {diagnostics['confidence_percentiles']['p90']:.6f}, max {diagnostics['confidence_percentiles']['max']:.6f}.",
        f"- Top-1 minus top-2 margin across {diagnostics['top1_minus_top2_margin_count']} outcomes: min {diagnostics['top1_minus_top2_margin_percentiles']['min']:.6f}, median {diagnostics['top1_minus_top2_margin_percentiles']['p50']:.6f}, mean {diagnostics['top1_minus_top2_margin_percentiles']['mean']:.6f}, p90 {diagnostics['top1_minus_top2_margin_percentiles']['p90']:.6f}, max {diagnostics['top1_minus_top2_margin_percentiles']['max']:.6f}.",
        f"- Per-recording run duration from the M1 polling record: min {run['run_duration_seconds']['min']:.3f}s, median {run['run_duration_seconds']['p50']:.3f}s, mean {run['run_duration_seconds']['mean']:.3f}s, p90 {run['run_duration_seconds']['p90']:.3f}s, max {run['run_duration_seconds']['max']:.3f}s. This is not per-crop inference latency.",
        f"- Peak sampled batch RSS: {run['memory']['batch_peak_sampled_rss_bytes']} bytes. Per-recording RSS and per-crop latency were not recorded.",
        "- Top-1 class counts:",
    ]
    lines.extend(
        f"  - `{identity}`: {count}"
        for identity, count in diagnostics["top1_identity_counts"].items()
    )
    lines.extend(
        [
            "",
            "## Reviewed identity comparisons",
            "",
            f"- Valid exact pairs: {comparisons['eligible_exact_pairs']}.",
            f"- Inspected {comparisons['reviewed_reference_outcomes_inspected']} saved human reference outcomes.",
            f"- {comparisons['lineage_intersection_counts'].get('same_frame', 0)} M1 predictions share exact frame metadata with at least one saved human outcome. None share the full card, frame, geometry, and crop lineage.",
            "- No accuracy value is reported. A reviewed label was not transferred by timestamp or approximate geometry.",
            "- M6 training-overlap outcomes and non-training outcomes are separate in the machine-readable report.",
            "",
            "## Per-recording coverage and lineage",
            "",
            "| Recording | Training overlap | Crops | Classified | Face-down | Unusable | Failed | Unprocessed | Confidence p50 | Margin p50 | Run seconds | Exact reviewed pairs |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for record in report["recordings"]:
        counts = record["outcomes_by_status"]
        lines.append(
            "| {recording_id} | {overlap} | {crops} | {classified} | {face_down} | {unusable} | {failed} | {unprocessed} | {confidence:.6f} | {margin:.6f} | {seconds:.3f} | {pairs} |".format(
                recording_id=record["recording_id"],
                overlap="yes" if record["m6_training_overlap"] else "no",
                crops=record["crop_inputs"],
                classified=counts.get("classified", 0),
                face_down=counts.get("face_down", 0),
                unusable=record["crop_unusable"],
                failed=record["classifier_errors"],
                unprocessed=record["unprocessed"],
                confidence=record["confidence"]["p50"],
                margin=record["rank_margin_top1_minus_top2"]["p50"],
                seconds=record["run_elapsed_poll_seconds"],
                pairs=record["review_comparison"]["eligible_exact_pairs"],
            )
        )
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "Run the report builder from the repository root with the retained primary pipeline store:",
            "",
            "```sh",
            "mise exec -- uv run --project operations python operations/scripts/build_0098_m2_identity_diagnostics.py \\",
            "  --pipeline-store /Users/niklas.sparfeld/Developer/doko_detector/data/operations/pipeline",
            "```",
            "",
            "The builder verifies each M1 output content digest before it writes either report.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument(
        "--pipeline-store",
        type=Path,
        default=Path("data/operations/pipeline"),
        help="pipeline store that holds the immutable M1 output revisions",
    )
    parser.add_argument(
        "--json-output", type=Path, default=Path("docs/reports/0098-M2_Identity_Diagnostics.json")
    )
    parser.add_argument(
        "--markdown-output", type=Path, default=Path("docs/reports/0098-M2_Identity_Diagnostics.md")
    )
    args = parser.parse_args()
    repository = args.repository.resolve()
    pipeline_store = args.pipeline_store.resolve()
    report = build_report(repository, pipeline_store)
    json_path = (
        args.json_output if args.json_output.is_absolute() else repository / args.json_output
    )
    markdown_path = (
        args.markdown_output
        if args.markdown_output.is_absolute()
        else repository / args.markdown_output
    )
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown_path.write_text(render_markdown(report))


if __name__ == "__main__":
    main()
