#!/usr/bin/env python3
"""Exercise both locked 0088 identity bundles on the frozen automatic development view."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "operations/src"), str(ROOT / "table_evidence_analyzer/src")]

from table_evidence_analyzer.dinov3_bundle import load_dinov3_identity_bundle  # noqa: E402
from table_evidence_analyzer.dinov3_inference import (  # noqa: E402
    DinoV3IdentityClassifier,
    DinoV3InferenceError,
)
from table_evidence_analyzer.visual_identity import (  # noqa: E402
    CardIdentityClassifierProvider,
    VisualIdentityRequest,
)

M1_SUMMARY = ROOT / "docs/reports/0088-M1_Campaign_Views.json"
AUTO_MANIFEST = ROOT / ".runtime/dinov3-identity-0088/automatic-development/manifest.json"
LOCK = ROOT / "docs/reports/0088-M12_Final_Evaluation_Lock.json"
OUTPUT_JSON = ROOT / "docs/reports/0088-M14_Development_Exercise.json"
OUTPUT_MD = ROOT / "docs/reports/0088-M14_Development_Exercise.md"
BUNDLES = {
    "M3": ROOT / ".runtime/dinov3-identity-0088/m12-final-lock/candidate-bundle",
    "M6": ROOT / ".runtime/dinov3-identity-0088/m12-final-lock/m6-candidate-bundle",
}
FINAL_RECORDING = "cardeventnet-IMG_0659"
REVIEW_THRESHOLD = 0.90


def file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 3)


def validate_inputs() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    summary = read_json(M1_SUMMARY)
    manifest_bytes = AUTO_MANIFEST.read_bytes()
    expected_auto_digest = summary["automatic_development_view"]["automatic_manifest_sha256"]
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_auto_digest:
        raise ValueError("M1 automatic-development manifest differs from its frozen digest")
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema_version") != "0088-m1-automatic-development-view/v1":
        raise ValueError("unsupported automatic-development manifest")
    expected_count = summary["automatic_development_view"]["automatic_crops"]
    rows = manifest.get("rows")
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise ValueError("automatic-development crop membership differs from M1")
    if manifest.get("prediction_count") != expected_count:
        raise ValueError("automatic-development prediction count differs from M1")
    if any(row.get("recording_id") == FINAL_RECORDING for row in rows):
        raise ValueError("the sealed final recording is present in the development view")
    if len({row.get("automatic_crop_path") for row in rows}) != expected_count:
        raise ValueError("automatic-development crop paths are not unique")
    if manifest.get("provider_unavailable_frames"):
        raise ValueError("M1 recorded unavailable upstream detector frames")

    lock = read_json(LOCK)
    lock_candidates = lock["candidates"]
    expected_bundles = {
        "M3": "e54952030a1f87aadf4c5c3befb71537e588074cd9959c98c4c51bbbc6ddac87",
        "M6": "a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79",
    }
    actual_bundles: dict[str, str] = {}
    for name, path in BUNDLES.items():
        bundle = load_dinov3_identity_bundle(path)
        actual = bundle.manifest["bundle_digest"]
        if actual != expected_bundles[name]:
            raise ValueError(f"{name} bundle differs from the M12 lock")
        lock_row = next(
            row for row in lock_candidates if row["candidate_id"].startswith(name.lower() + "-")
        )
        if lock_row["bundle_digest"] != actual:
            raise ValueError(f"{name} bundle differs from the M12 candidate record")
        actual_bundles[name] = actual
    return manifest, rows, actual_bundles


def run_candidate(
    name: str,
    bundle_digest: str,
    rows: list[dict[str, Any]],
    *,
    device: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    classifier = DinoV3IdentityClassifier(BUNDLES[name], device=device)
    provider = CardIdentityClassifierProvider(classifier)
    recording_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "rows": 0,
            "failures": 0,
            "review_required": 0,
            "gate_covered": 0,
            "face_down_top1": 0,
            "latencies_ms": [],
        }
    )
    predictions: list[dict[str, Any]] = []
    wall_started = time.monotonic()
    total_failures = 0
    total_review = 0
    total_covered = 0
    for row in rows:
        recording_id = row["recording_id"]
        relative = row.get("automatic_crop_path")
        crop_path = (AUTO_MANIFEST.parent / str(relative)).resolve()
        if not crop_path.is_relative_to(AUTO_MANIFEST.parent.resolve()) or not crop_path.is_file():
            raise ValueError(f"automatic crop is missing or escapes its frozen view: {relative}")
        crop_bytes = crop_path.read_bytes()
        if hashlib.sha256(crop_bytes).hexdigest() != row.get("automatic_crop_sha256"):
            raise ValueError(f"automatic crop digest mismatch: {relative}")
        request = VisualIdentityRequest(
            card_id=f"{recording_id}:{row['frame_key']}:{row['provider_proposal_index']}",
            provider=provider.name,
            model=provider.model,
            crop_bytes=crop_bytes,
        )
        started = time.monotonic()
        result = provider.classify(request)
        measured_latency = round((time.monotonic() - started) * 1000.0, 3)
        detail: dict[str, Any] = {
            "recording_id": recording_id,
            "frame_key": row["frame_key"],
            "requested_time_us": row["frame_identity"]["requested_time_us"],
            "provider_proposal_index": row["provider_proposal_index"],
            "crop_sha256": request.crop_sha256,
            "status": result.status,
            "latency_ms": measured_latency,
            "association_state": row["association_state"],
            "predicted_side": row.get("predicted_side"),
        }
        stats = recording_stats[recording_id]
        stats["rows"] += 1
        stats["latencies_ms"].append(measured_latency)
        raw = result.raw_response if isinstance(result.raw_response, dict) else {}
        if result.status != "ok":
            total_failures += 1
            stats["failures"] += 1
            total_review += 1
            stats["review_required"] += 1
            detail["error"] = result.error or "classifier returned an unavailable result"
        else:
            ranked_targets = raw.get("ranked_targets")
            ranked_probabilities = raw.get("ranked_probabilities")
            if not isinstance(ranked_targets, list) or not isinstance(ranked_probabilities, list):
                raise ValueError("local classifier omitted ranked target metadata")
            if len(ranked_targets) != 25 or len(ranked_probabilities) != 25:
                raise ValueError("local classifier did not preserve all 25 ranked outputs")
            if ranked_targets[0] == "FACE_DOWN":
                stats["face_down_top1"] += 1
            confidence = float(ranked_probabilities[0])
            covered = confidence >= REVIEW_THRESHOLD
            if covered:
                total_covered += 1
                stats["gate_covered"] += 1
            else:
                total_review += 1
                stats["review_required"] += 1
            detail.update(
                {
                    "classification": result.classification,
                    "ranked_targets": ranked_targets,
                    "ranked_probabilities": [
                        round(float(value), 9) for value in ranked_probabilities
                    ],
                    "raw_ranked_probabilities": [
                        round(float(value), 9) for value in raw["raw_ranked_probabilities"]
                    ],
                    "confidence": round(confidence, 9),
                    "review_threshold": REVIEW_THRESHOLD,
                    "confidence_gate_covered": covered,
                    "calibration": raw.get("score_metadata"),
                    "tensor_sha256": raw.get("input_tensor_digest"),
                }
            )
        predictions.append(detail)

    elapsed = time.monotonic() - wall_started
    all_latencies = [item["latency_ms"] for item in predictions if item["status"] == "ok"]
    summary = {
        "candidate": name,
        "bundle_digest": bundle_digest,
        "provider": provider.name,
        "provider_version": provider.version,
        "model": provider.model,
        "device": device,
        "model_load_ms": round(classifier.load_latency_ms, 3),
        "inference_wall_seconds": round(elapsed, 3),
        "input_count": len(rows),
        "success_count": len(rows) - total_failures,
        "classifier_failure_count": total_failures,
        "p95_inference_ms": percentile(all_latencies, 0.95),
        "median_inference_ms": (
            round(statistics.median(all_latencies), 3) if all_latencies else None
        ),
        "confidence_gate_threshold": REVIEW_THRESHOLD,
        "confidence_gate_covered": total_covered,
        "confidence_gate_coverage": round(total_covered / len(rows), 6),
        "review_required_count": total_review,
        "review_required_fraction": round(total_review / len(rows), 6),
        "face_down_top1_count": sum(item["face_down_top1"] for item in recording_stats.values()),
        "per_recording": {
            recording_id: {
                "input_count": stats["rows"],
                "classifier_failures": stats["failures"],
                "confidence_gate_covered": stats["gate_covered"],
                "review_required_count": stats["review_required"],
                "review_required_fraction": round(stats["review_required"] / stats["rows"], 6),
                "face_down_top1_count": stats["face_down_top1"],
                "median_inference_ms": round(statistics.median(stats["latencies_ms"]), 3),
                "p95_inference_ms": percentile(stats["latencies_ms"], 0.95),
            }
            for recording_id, stats in sorted(recording_stats.items())
        },
        "predictions": predictions,
    }

    # Exercise the provider's real malformed-crop outcome path. This diagnostic row is kept
    # outside the frozen development denominator.
    try:
        bad = provider.classify(
            VisualIdentityRequest(
                card_id=f"m14-{name.lower()}-malformed-crop-control",
                provider=provider.name,
                model=provider.model,
                crop_bytes=b"not a P6 PPM image",
            )
        )
    except DinoV3InferenceError as error:
        summary["malformed_crop_control"] = {
            "outcome": "raised_crop_contract_exception",
            "error": str(error),
            "counted_in_development_denominator": False,
        }
    else:
        if bad.status == "ok":
            raise ValueError(f"{name} accepted the malformed-crop control")
        summary["malformed_crop_control"] = {
            "outcome": "unavailable_result",
            "status": bad.status,
            "error": bad.error,
            "counted_in_development_denominator": False,
        }
    return summary, predictions


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# 0088 M14 development sequence exercise",
        "",
        f"Date: {result['date']}",
        "",
        "## Result",
        "",
        "**Complete.** Both M12 candidates ran through the existing visual-identity provider "
        "boundary on the same frozen automatic-crop development view. This is a runtime and "
        "review-burden exercise, not an accuracy evaluation: M1 matched none of these proposals "
        "to reviewed identity samples.",
        "",
        f"The view contained {result['upstream']['frame_count']} detector frames and "
        f"{result['upstream']['crop_count']} automatic crops from "
        f"{len(result['upstream']['recording_crop_counts'])} recordings. The source manifest "
        f"digest is `{result['upstream']['manifest_sha256']}`. No final-test recording was used.",
        "",
        "| Candidate | Inputs | Failures | Coverage | Review | Median / p95 ms | Load ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for candidate in result["candidates"]:
        lines.append(
            f"| {candidate['candidate']} | {candidate['input_count']} | "
            f"{candidate['classifier_failure_count']} | "
            f"{candidate['confidence_gate_covered']}/{candidate['input_count']} "
            f"({candidate['confidence_gate_coverage']:.1%}) | "
            f"{candidate['review_required_count']}/{candidate['input_count']} "
            f"({candidate['review_required_fraction']:.1%}) | "
            f"{candidate['median_inference_ms']} / {candidate['p95_inference_ms']} ms | "
            f"{candidate['model_load_ms']} ms |"
        )
    lines.extend(
        [
            "",
            "## Per-recording burden",
            "",
            "| Recording | Crops | M3 review | M6 review |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    per_recording = result["candidates"][0]["per_recording"]
    for recording_id, stats in per_recording.items():
        m6 = result["candidates"][1]["per_recording"][recording_id]
        lines.append(
            f"| `{recording_id}` | {stats['input_count']} | "
            f"{stats['review_required_count']} ({stats['review_required_fraction']:.1%}) | "
            f"{m6['review_required_count']} ({m6['review_required_fraction']:.1%}) |"
        )
    lines.extend(
        [
            "",
            "## Findings and limits",
            "",
            "- All automatic crops were unmatched at M1's frozen IoU threshold. "
            "The recorded review "
            "burden is a diagnostic routing estimate: inputs below 0.90 confidence or with an "
            "inference failure need review. This does not validate 0.90 as a safe automatic-accept "
            "threshold.",
            "- The crop request contains automatic PPM bytes and no reviewed-side label. The "
            "classifier ranks `FACE_DOWN` from pixels. The report counts face-down top predictions "
            "but has no ground truth for them, so it makes no face-down quality claim.",
            "- Both candidates retained all 25 ranked outputs, calibrated and raw probabilities, "
            "confidence metadata, and per-input latency. The malformed-crop control raised the "
            "expected crop-contract exception for each candidate. The existing pipeline catches "
            "per-card exceptions and records a failed identity outcome. The control is outside the "
            "development denominator.",
            "- M1 reports zero unavailable detector frames. Its 314 missing inputs are reviewed "
            "samples without a matched automatic proposal, not detector or classifier failures.",
            "- The 495 crops span model-selection and confidence-calibration recordings. They are "
            "diagnostic development sequences and are not a held-out test. M13 remains sealed and "
            "must not be rerun.",
            "- No candidate is selected or promoted here. M3 and M6 both continue to M15 because "
            "the observed one-recording point difference cannot justify excluding either model.",
            "",
            "Detailed ranked outputs and timing are in the [machine-readable report]"
            "(0088-M14_Development_Exercise.json). The runner is "
            "[`run_0088_m14_development_exercise.py`](../../operations/scripts/"
            "run_0088_m14_development_exercise.py).",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    args = parser.parse_args()
    manifest, rows, bundle_digests = validate_inputs()
    rows = sorted(
        rows,
        key=lambda row: (
            row["recording_id"],
            row["frame_identity"]["requested_time_us"],
            row["provider_proposal_index"],
        ),
    )
    recording_counts = Counter(row["recording_id"] for row in rows)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        peak *= 1
    else:
        peak *= 1024
    candidates = []
    for name in ("M3", "M6"):
        candidate, _ = run_candidate(name, bundle_digests[name], rows, device=args.device)
        candidates.append(candidate)
    unit = 1 if sys.platform == "darwin" else 1024
    peak = max(peak, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * unit)
    result = {
        "schema_version": "0088-m14-development-exercise/v1",
        "date": "2026-10-16",
        "result": "complete",
        "purpose": "development runtime and review-burden exercise; not accuracy evaluation",
        "confidence_review_threshold": REVIEW_THRESHOLD,
        "both_locked_candidates_retained": True,
        "upstream": {
            "manifest_sha256": file_sha256(AUTO_MANIFEST),
            "provider_bundle_sha256": manifest["provider_bundle_sha256"],
            "frame_count": manifest["provider_frame_count"],
            "proposal_count": manifest["provider_proposal_count"],
            "crop_count": len(rows),
            "provider_unavailable_frame_count": len(manifest["provider_unavailable_frames"]),
            "reviewed_sample_unmatched_count": manifest["missing_input_count"],
            "recording_crop_counts": dict(sorted(recording_counts.items())),
            "final_test_recording_excluded": FINAL_RECORDING,
        },
        "peak_process_memory_bytes": peak,
        "candidates": candidates,
        "accuracy_claims": "none; all 495 automatic crops are unmatched to reviewed identities",
        "face_down_claims": "none; top predictions are pixel-based but lack face-down ground truth",
    }
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + "\n")
    OUTPUT_MD.write_text(render_markdown(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(OUTPUT_MD.relative_to(ROOT)),
                "candidates": [
                    {
                        "candidate": item["candidate"],
                        "successes": item["success_count"],
                        "failures": item["classifier_failure_count"],
                        "review_required": item["review_required_count"],
                        "p95_ms": item["p95_inference_ms"],
                    }
                    for item in candidates
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
