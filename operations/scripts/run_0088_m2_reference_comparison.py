#!/usr/bin/env python3
"""Reuse exact Gemini cache entries for the frozen 0088 M2 development view."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from table_evidence_analyzer.card_classification import (
    CachedCardClassifier,
    CardClassificationRequest,
    GeminiCardClassifier,
)

MODEL = "gemini-3.8-flash"
MAX_REQUESTS = 250
SPEND_CAP_USD = 10.0


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")


def _source_groups(dataset: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in dataset.get("entries", []):
        groups = {name: value for name, value in item.get("group_keys", [])}
        result[item["dataset_item_id"]] = groups.get("source_group_id", "unknown")
    return result


def _confusion(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        result[row["target"]][row["prediction"]] += 1
    return {
        target: dict(sorted(predictions.items())) for target, predictions in sorted(result.items())
    }


def _markdown(report: dict[str, Any]) -> str:
    gemini = report["gemini"]
    poc = report["retained_poc"]
    lines = [
        "# 0088 M2 Gemini and PoC references",
        "",
        "## Result",
        "",
        f"Gemini classified {gemini['sample_count']} exact reviewed development crops. "
        f"It returned {gemini['face_up_correct']}/{gemini['face_up_sample_count']} face-up "
        f"identities correctly ({gemini['face_up_top_1_accuracy']:.1%} top-1). The full "
        f"21-class view returned {gemini['correct']}/{gemini['sample_count']} reviewed identities "
        f"correctly ({gemini['top_1_accuracy']:.1%} top-1). It returned "
        f"{gemini['failure_count']} provider failures. All results came from exact request-cache "
        "matches, so this milestone made no new Gemini requests and incurred no new provider "
        "spend.",
        "",
        f"The retained 0043 PoC result covers {poc['sample_count']} crops, with "
        f"{poc['top_1_correct']}/{poc['sample_count']} top-1 correct "
        f"({poc['top_1_accuracy']:.1%}). This is a different historical validation set. "
        "The retained bundle is now rejected by the current loader as an obsolete uncalibrated "
        "smoke format, so M2 does not claim a new same-crop PoC run. The report keeps the two "
        "reference conditions separate and lists their input differences.",
        "",
        "The Gemini score is a development reference against human labels, not ground truth for "
        "future training. The paired rows contain crop digests, reviewed labels, Gemini outputs, "
        "and source groups. The held-out final test remains unopened.",
        "",
        "## Gemini coverage",
        "",
        f"- Exact cache hits: {gemini['cache_hits']}/{gemini['sample_count']}.",
        f"- New requests: {gemini['new_requests']} (limit {gemini['request_limit']}).",
        f"- New spend: USD {gemini['new_spend_usd']:.2f} (cap USD {gemini['spend_cap_usd']:.2f}).",
        f"- Reused receipts record USD {gemini['reused_receipt_cost_usd']:.4f} in provider cost.",
        f"- FACE_DOWN support: {gemini['class_support'].get('FACE_DOWN', 0)}; report this as "
        "exploratory evidence only. It does not support precision, recall, calibration, or "
        "generalization claims.",
        "",
        "## Retained PoC limits",
        "",
        f"- Historical evaluation schema: `{poc['schema_version']}`.",
        f"- Historical status: `{poc['quality_state']}`.",
        f"- Unsupported positive classes: {', '.join(poc['unsupported_classes'])}.",
        f"- FACE_DOWN measured: {poc['face_down_measured']}.",
        "- The Gemini and PoC sample IDs do not form a same-crop pair. Their metrics must not be "
        "read as a direct model ranking.",
        "",
        "## Error examples",
        "",
        "| Sample | Source group | Reviewed label | Gemini result | Crop SHA-256 |",
        "| --- | --- | --- | --- | --- |",
    ]
    errors = gemini["error_examples"]
    if errors:
        for row in errors:
            lines.append(
                f"| `{row['sample_id']}` | `{row['source_group_id']}` | `{row['target']}` | "
                f"`{row['prediction']}` | `{row['crop_sha256']}` |"
            )
    else:
        lines.append("| None | | | | |")
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "Run `operations/scripts/run_0088_m2_reference_comparison.py` with the M1 campaign "
            "directory and exact Gemini request cache. The script disables live requests and "
            "fails if any crop lacks an exact cached request receipt.",
            "",
            "The full class confusion matrices and all paired rows are in "
            "[the machine-readable report](0088-M2_Reference_Comparison.json).",
            "",
        ]
    )
    return "\n".join(lines)


def run(
    repository: Path,
    campaign: Path,
    gemini_cache: Path,
    poc_path: Path,
    output: Path,
) -> dict[str, Any]:
    dataset = json.loads((campaign / "data/dataset.json").read_text(encoding="utf-8"))
    split = json.loads((campaign / "data/split.json").read_text(encoding="utf-8"))
    crop_manifest_path = campaign / "crop-cache/crop-manifest.json"
    crop_manifest = json.loads(crop_manifest_path.read_text(encoding="utf-8"))
    manifest = json.loads((campaign / "manifest.json").read_text(encoding="utf-8"))
    poc = json.loads(poc_path.read_text(encoding="utf-8"))
    readiness_path = repository / "docs/reports/0088-M0_Campaign_Readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    expected_poc_digest = readiness["inputs"]["0043_poc_evaluation"]["sha256"]
    if _digest(poc_path) != expected_poc_digest:
        raise ValueError("retained PoC evaluation differs from the frozen M0 receipt")
    if manifest.get("milestone") != "M1":
        raise ValueError("M2 requires the frozen 0088 M1 campaign materialization")
    if manifest.get("dataset", {}).get("digest") != dataset.get("dataset_version_digest"):
        raise ValueError("M1 campaign dataset digest does not match its manifest")
    if manifest.get("split", {}).get("digest") != split.get("split_version_digest"):
        raise ValueError("M1 campaign split digest does not match its manifest")
    if crop_manifest.get("cache_digest") != manifest.get("crop_inventory", {}).get("digest"):
        raise ValueError("M1 crop inventory digest does not match its manifest")

    validation = [
        row for row in crop_manifest.get("crops", []) if row.get("partition") == "validation"
    ]
    if not validation or len(validation) > MAX_REQUESTS:
        raise ValueError(f"M2 validation crop count must be 1..{MAX_REQUESTS}")
    group_by_item = _source_groups(dataset)
    cache_only_classifier = GeminiCardClassifier(
        api_key="cache-only; live Gemini requests are disabled",
        model=MODEL,
        max_retries=0,
        urlopen=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("live Gemini request was blocked by the M2 cache-only runner")
        ),
    )
    classifier = CachedCardClassifier(cache_only_classifier, gemini_cache)
    rows: list[dict[str, Any]] = []
    new_requests = 0
    new_spend = 0.0
    reused_cost = 0.0
    failures = 0
    for item in sorted(validation, key=lambda value: value["dataset_item_id"]):
        crop_path = campaign / "crop-cache" / item["relative_path"]
        crop_bytes = crop_path.read_bytes()
        crop_sha = hashlib.sha256(crop_bytes).hexdigest()
        if crop_sha != item["sha256"]:
            raise ValueError(f"crop digest mismatch for {item['dataset_item_id']}")
        request_key = CardClassificationRequest(
            crop_bytes=crop_bytes,
            model=MODEL,
        ).request_key
        result = classifier.classify_ppm(crop_bytes)
        if not result.cache_hit:
            new_requests += 1
            new_spend += result.estimated_cost_usd
        else:
            reused_cost += result.estimated_cost_usd
        if result.status == "unavailable":
            failures += 1
            prediction = "UNAVAILABLE"
        elif result.classification == "face_down":
            prediction = "FACE_DOWN"
        elif result.classification == "unknown":
            prediction = "UNKNOWN"
        else:
            prediction = result.candidates[0].card
        rows.append(
            {
                "sample_id": item["dataset_item_id"],
                "source_group_id": group_by_item.get(item["dataset_item_id"], "unknown"),
                "crop_sha256": crop_sha,
                "gemini_request_key": request_key,
                "target": item["visual_card_identity"],
                "prediction": prediction,
                "status": result.status,
                "cache_hit": result.cache_hit,
                "provider_failure": result.error,
                "estimated_receipt_cost_usd": result.estimated_cost_usd,
            }
        )
    if new_requests:
        raise ValueError(f"cache-only M2 run encountered {new_requests} uncached crops")
    if new_spend > SPEND_CAP_USD:
        raise ValueError("M2 Gemini spend exceeded the frozen cap")

    support = Counter(row["target"] for row in rows)
    correct = sum(row["target"] == row["prediction"] for row in rows)
    face_up_rows = [row for row in rows if row["target"] != "FACE_DOWN"]
    face_up_correct = sum(row["target"] == row["prediction"] for row in face_up_rows)
    per_class: dict[str, dict[str, int]] = {}
    for target, count in sorted(support.items()):
        class_rows = [row for row in rows if row["target"] == target]
        per_class[target] = {
            "support": count,
            "correct": sum(row["prediction"] == target for row in class_rows),
            "errors": sum(row["prediction"] != target for row in class_rows),
        }
    grouped: dict[str, dict[str, int]] = {}
    for group in sorted({row["source_group_id"] for row in rows}):
        group_rows = [row for row in rows if row["source_group_id"] == group]
        grouped[group] = {
            "support": len(group_rows),
            "correct": sum(row["prediction"] == row["target"] for row in group_rows),
        }
    wrong = [row for row in rows if row["target"] != row["prediction"]]
    historical_predictions = poc.get("predictions", [])
    historical_correct = sum(
        row.get("prediction") == row.get("target") for row in historical_predictions
    )
    poc_unsupported = poc.get("unsupported_class_coverage", {})
    poc_excluded = poc.get("excluded_class_coverage", {})
    report = {
        "schema_version": "0088-m2-reference-comparison/v1",
        "campaign_manifest_digest": manifest["manifest_digest"],
        "dataset_digest": dataset["dataset_version_digest"],
        "split_digest": split["split_version_digest"],
        "crop_inventory_digest": crop_manifest["cache_digest"],
        "gemini": {
            "model": MODEL,
            "crop_policy": "reviewed_visible_region; exact M1 PPM bytes",
            "request_limit": MAX_REQUESTS,
            "spend_cap_usd": SPEND_CAP_USD,
            "sample_count": len(rows),
            "cache_hits": sum(row["cache_hit"] for row in rows),
            "new_requests": new_requests,
            "new_spend_usd": round(new_spend, 6),
            "reused_receipt_cost_usd": round(reused_cost, 6),
            "failure_count": failures,
            "correct": correct,
            "top_1_accuracy": correct / len(rows),
            "face_up_sample_count": len(face_up_rows),
            "face_up_correct": face_up_correct,
            "face_up_top_1_accuracy": face_up_correct / len(face_up_rows),
            "class_support": dict(sorted(support.items())),
            "per_class": per_class,
            "confusion_matrix": _confusion(rows),
            "source_groups": grouped,
            "error_examples": wrong[:30],
            "paired_rows": rows,
        },
        "retained_poc": {
            "evaluation_digest": _digest(poc_path),
            "schema_version": poc.get("schema_version"),
            "quality_state": poc.get("quality_state"),
            "sample_count": len(historical_predictions),
            "top_1_correct": historical_correct,
            "top_1_accuracy": historical_correct / len(historical_predictions)
            if historical_predictions
            else None,
            "unsupported_classes": sorted({*poc_unsupported, *poc_excluded}),
            "face_down_measured": poc_excluded.get("FACE_DOWN", {}).get("measured", False),
            "input_set": (
                "retained 0043 historical validation predictions; not the M1 development view"
            ),
            "same_crop_paired_with_gemini": False,
            "loader_status": "rejected: obsolete uncalibrated smoke format",
        },
        "input_differences": {
            "gemini": "209 M1 model-selection crops from IMG_0657 and IMG_0662, exact PPM bytes",
            "poc": "301 retained 0043 validation predictions from its historical split",
            "same_sample_ids": len(
                {row["sample_id"] for row in rows}
                & {row["sample_id"] for row in historical_predictions}
            ),
            "poc_bundle_reloaded": False,
            "final_test_opened": False,
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "0088-M2_Reference_Comparison.json", report)
    (output / "0088-M2_Reference_Comparison.md").write_text(_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--gemini-cache", type=Path)
    parser.add_argument("--poc-evaluation", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repository = args.repository.resolve()
    campaign = (args.campaign or repository / ".runtime/dinov3-identity-0088").resolve()
    gemini_cache = (
        args.gemini_cache or repository / ".runtime/gemini-cache/card-classification"
    ).resolve()
    poc = (
        args.poc_evaluation
        or repository
        / "data/operations/dinov3-identity-bundles/"
        "0043-m1-dinov3-identity-75000a5eec53a52f088f9e6e/evaluation.json"
    ).resolve()
    output = (args.output or repository / "docs/reports").resolve()
    report = run(repository, campaign, gemini_cache, poc, output)
    print(
        json.dumps(
            {
                "gemini_samples": report["gemini"]["sample_count"],
                "gemini_top_1_accuracy": report["gemini"]["top_1_accuracy"],
                "cache_hits": report["gemini"]["cache_hits"],
                "poc_samples": report["retained_poc"]["sample_count"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
