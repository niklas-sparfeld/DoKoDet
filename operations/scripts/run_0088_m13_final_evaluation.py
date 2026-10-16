#!/usr/bin/env python3
"""Run the one locked 0088 final comparison for M3, M6, and Gemini."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import resource
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "operations/src"), str(ROOT / "table_evidence_analyzer/src")]

from table_evidence_analyzer.card_classification import (  # noqa: E402
    CardClassificationRequest,
    GeminiCardClassifier,
)
from table_evidence_analyzer.dinov3_bundle import load_dinov3_identity_bundle  # noqa: E402
from table_evidence_analyzer.dinov3_inference import DinoV3IdentityClassifier  # noqa: E402

from doko_operations.derived_view import ExactEventRequest, FFmpegFrameResolver  # noqa: E402
from doko_operations.pipeline_data import RecordingVideoSource  # noqa: E402
from doko_operations.visual_identity_materialization import (  # noqa: E402
    materialize_reviewed_visual_identity_crops,
)

LOCK_DEFAULT = ROOT / "docs/reports/0088-M12_Final_Evaluation_Lock.json"
HANDOFF = ROOT / "docs/reports/0086-M5_DINO_Campaign_Handoff.json"
M0 = ROOT / "docs/reports/0088-M0_Campaign_Readiness.json"
SOURCE_RECEIPT = ROOT / "docs/reports/0088-M1_Source_Verification.json"
M1_VIEWS = ROOT / "docs/reports/0088-M1_Campaign_Views.json"
CLASSIFIER_SOURCE = (
    ROOT / "table_evidence_analyzer/src/table_evidence_analyzer/card_classification.py"
)
CONFIG_SOURCE = ROOT / "backend/src/dokodetector_backend/config.py"
TARGETS = tuple(
    [
        f"{suit}_{rank}"
        for suit in ("CLUBS", "SPADES", "HEARTS", "DIAMONDS")
        for rank in ("NINE", "JACK", "QUEEN", "KING", "TEN", "ACE")
    ]
    + ["FACE_DOWN"]
)
SUPPORTED = frozenset(target for target in TARGETS if not target.endswith("_NINE"))


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n")


def selected_revision(recording_id: str, kind: str, expected: dict[str, Any]) -> dict[str, Any]:
    state_path = ROOT / "data/operations/pipeline-references" / recording_id / kind / "state.json"
    state = read_json(state_path)
    revision_id = state.get("selected_completed_revision_id")
    if revision_id != expected.get("revision_id"):
        raise ValueError(f"{recording_id} {kind} selected revision differs from the lock")
    revision_root = ROOT / "data/operations/pipeline/revisions" / revision_id
    content = read_json(revision_root / "content.json")
    manifest = read_json(revision_root / "manifest.json")
    if manifest.get("recording_id") != recording_id:
        raise ValueError(f"{recording_id} {kind} revision belongs to another recording")
    if digest_bytes(canonical(content)) != expected.get("content_sha256"):
        raise ValueError(f"{recording_id} {kind} content digest differs from the lock")
    if digest_bytes(canonical(manifest)) != expected.get("manifest_sha256"):
        raise ValueError(f"{recording_id} {kind} manifest digest differs from the lock")
    if digest_file(state_path) != expected.get("state_sha256"):
        raise ValueError(f"{recording_id} {kind} state digest differs from the lock")
    return {
        "revision_id": revision_id,
        "content_digest": digest_bytes(canonical(content)),
        "content": content,
        "manifest": manifest,
    }


def resolve_source(recording_id: str, expected_sha: str, frozen_source: dict[str, Any]):
    intake = ROOT / "data/intake/recordings" / recording_id
    manifest = read_json(intake / "manifest.json")
    record = read_json(intake / "source-record.json")
    video = manifest["files"]["video"]
    path = (intake / video["relative_path"]).resolve()
    if not path.is_relative_to(intake.resolve()):
        raise ValueError("frozen recording video path escapes its intake bundle")
    if (
        video.get("sha256") != expected_sha
        or record.get("sha256") != expected_sha
        or frozen_source.get("video_sha256") != expected_sha
        or frozen_source.get("relative_path") != path.relative_to(ROOT).as_posix()
    ):
        raise ValueError("final-test source metadata differs from the frozen lock")
    if path.stat().st_size != video.get("byte_length") or digest_file(path) != expected_sha:
        raise ValueError("final-test source bytes differ from the frozen lock")
    source = RecordingVideoSource.from_mapping(
        {
            "schema_version": "recording-video/v1",
            "recording_id": recording_id,
            "relative_path": frozen_source["relative_path"],
            "video_sha256": expected_sha,
            "byte_length": path.stat().st_size,
            "duration_us": frozen_source["duration_us"],
        }
    )
    return source, path


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total <= 0:
        return None
    p = successes / total
    den = 1 + z * z / total
    center = (p + z * z / (2 * total)) / den
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / den
    return [max(0.0, center - half), min(1.0, center + half)]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def classify_gemini_result(result: Any) -> str:
    if result.status != "ok":
        return "UNAVAILABLE"
    if result.classification == "face_down":
        return "FACE_DOWN"
    if result.classification == "unknown":
        return "UNKNOWN"
    if not result.candidates:
        return "UNKNOWN"
    return str(result.candidates[0].card)


def metrics(rows: list[dict[str, Any]], *, is_dino: bool) -> dict[str, Any]:
    total = len(rows)
    correct = sum(row["prediction"] == row["target"] for row in rows)
    face_up = [row for row in rows if row["target"] != "FACE_DOWN"]
    face_down = [row for row in rows if row["target"] == "FACE_DOWN"]
    fd_tp = sum(row["prediction"] == "FACE_DOWN" for row in face_down)
    fd_fp = sum(row["prediction"] == "FACE_DOWN" for row in face_up)
    confusion: dict[str, dict[str, int]] = {}
    per_class: dict[str, dict[str, Any]] = {}
    f1_values: list[float] = []
    for target in sorted(SUPPORTED):
        target_rows = [row for row in rows if row["target"] == target]
        tp = sum(row["prediction"] == target for row in target_rows)
        fp = sum(row["prediction"] == target and row["target"] != target for row in rows)
        fn = len(target_rows) - tp
        f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
        f1_values.append(f1)
        per_class[target] = {
            "support": len(target_rows),
            "correct": tp,
            "errors": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / len(target_rows) if target_rows else None,
            "f1": f1,
            "accuracy_wilson_95": wilson(tp, len(target_rows)),
        }
        confusion[target] = dict(sorted(Counter(row["prediction"] for row in target_rows).items()))
    result: dict[str, Any] = {
        "sample_count": total,
        "correct": correct,
        "top_1_accuracy": correct / total if total else 0.0,
        "top_1_wilson_95": wilson(correct, total),
        "face_up_support": len(face_up),
        "face_up_correct": sum(row["prediction"] == row["target"] for row in face_up),
        "face_up_top_1_accuracy": (
            sum(row["prediction"] == row["target"] for row in face_up) / len(face_up)
            if face_up
            else None
        ),
        "face_down_support": len(face_down),
        "face_down_precision": fd_tp / (fd_tp + fd_fp) if fd_tp + fd_fp else None,
        "face_down_recall": fd_tp / len(face_down) if face_down else None,
        "false_face_down_rate_on_face_up": fd_fp / len(face_up) if face_up else None,
        "macro_f1_supported_targets": statistics.fmean(f1_values) if f1_values else None,
        "per_class": per_class,
        "confusion_matrix": confusion,
        "source_group_results": {
            group: {
                "support": len(group_rows),
                "correct": sum(row["prediction"] == row["target"] for row in group_rows),
            }
            for group in sorted({row["source_group_id"] for row in rows})
            for group_rows in [[row for row in rows if row["source_group_id"] == group]]
        },
        "grouped_uncertainty": {
            "method": "source_group_bootstrap_95_percent",
            "independent_group_count": len({row["source_group_id"] for row in rows}),
            "interval": None,
            "status": "insufficient; fewer than 3 independent source groups",
        },
        "all_supported_cards_correct_per_frame": _frame_accuracy(rows),
        "usable_prediction_coverage": sum(row.get("usable", True) for row in rows) / total
        if total
        else 0,
    }
    if is_dino:
        top3 = sum(row["target"] in row.get("top_k", [])[:3] for row in rows)
        confident = [row for row in rows if row.get("top_1_probability", 0.0) >= 0.9]
        result["top_3"] = {"correct": top3, "accuracy": top3 / total if total else 0.0}
        result["confidence_gate"] = {
            "threshold": 0.9,
            "selected": len(confident),
            "coverage": len(confident) / total if total else 0.0,
            "errors": sum(row["prediction"] != row["target"] for row in confident),
            "error_rate": (
                sum(row["prediction"] != row["target"] for row in confident) / len(confident)
                if confident
                else None
            ),
            "confident_errors": [
                {
                    "sample_id": row["sample_id"],
                    "target": row["target"],
                    "prediction": row["prediction"],
                    "probability": row["top_1_probability"],
                }
                for row in confident
                if row["prediction"] != row["target"]
            ],
        }
    return result


def _frame_accuracy(rows: list[dict[str, Any]]) -> dict[str, int]:
    frames: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        frames[row["frame_key"]].append(row)
    return {
        "frame_count": len(frames),
        "all_correct_frame_count": sum(
            all(row["prediction"] == row["target"] for row in frame_rows)
            for frame_rows in frames.values()
        ),
    }


def _physical_memory_bytes() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (ValueError, OSError, AttributeError):
        return 0


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes; Linux reports KiB.
    return value if sys.platform == "darwin" else value * 1024


def _validate_lock(lock: dict[str, Any]) -> None:
    lock_digest = lock.get("lock_digest")
    core = dict(lock)
    core.pop("lock_digest", None)
    if digest_bytes(canonical(core)) != lock_digest:
        raise ValueError("M12 lock digest is invalid")
    execution = lock["m13_execution"]
    if len(lock.get("candidates", [])) != 2 or lock["evaluation_contract"]["candidate_count"] != 2:
        raise ValueError("M13 lock must contain exactly the two frozen finalists")
    if lock["test_membership"]["previously_scored"]:
        raise ValueError("M13 final test is already marked as scored")
    if lock["test_membership"]["expected_positive_crop_count"] != 108:
        raise ValueError("M13 locked test denominator changed")
    for name, path, expected in (
        (
            "M0 readiness",
            M0,
            lock["test_membership"]["membership_sources"]["m0_readiness_json_sha256"],
        ),
        (
            "M1 campaign views",
            M1_VIEWS,
            lock["test_membership"]["membership_sources"]["m1_views_json_sha256"],
        ),
        (
            "M1 source verification",
            SOURCE_RECEIPT,
            lock["test_membership"]["membership_sources"]["source_verification_json_sha256"],
        ),
    ):
        if digest_file(path) != expected:
            raise ValueError(f"locked {name} receipt has changed")
    if execution.get("must_not") is None:
        raise ValueError("M13 lock has no execution guards")
    for key, path, expected in (
        (
            "classifier implementation",
            CLASSIFIER_SOURCE,
            lock["gemini_reference"]["classifier_implementation_sha256"],
        ),
        ("Gemini configuration", CONFIG_SOURCE, lock["gemini_reference"]["configuration_sha256"]),
    ):
        if digest_file(path) != expected:
            raise ValueError(f"locked {key} has changed")
    response_schema = lock["gemini_reference"]["response_schema"]
    if (
        response_schema.get("required") != ["card"]
        or response_schema.get("additional_properties") is not False
        or not response_schema.get("allowed_values")
        or "UNKNOWN" not in response_schema["allowed_values"]
        or "FACE_DOWN" not in response_schema["allowed_values"]
        or not isinstance(lock["gemini_reference"].get("prompt"), str)
    ):
        raise ValueError("Gemini response schema differs from M12 lock")


def run(lock_path: Path, output: Path, device: str) -> dict[str, Any]:
    lock = read_json(lock_path)
    _validate_lock(lock)
    if output.exists():
        raise ValueError(
            f"M13 output already exists; this one-time evaluation cannot be repeated: {output}"
        )
    if not os.environ.get("GEMINI_API_KEY"):
        raise ValueError(
            "GEMINI_API_KEY is not set; stopped before opening or scoring the final test"
        )
    if (
        lock["test_membership"]["expected_positive_crop_count"]
        > lock["gemini_reference"]["maximum_requests"]
    ):
        raise ValueError("locked crop count exceeds Gemini request cap")

    # Validate both bundles and load local models before resolving any final-test crop.
    classifiers: dict[str, DinoV3IdentityClassifier] = {}
    bundle_receipts: dict[str, dict[str, Any]] = {}
    for candidate in lock["candidates"]:
        bundle_root = ROOT / candidate["bundle_path"]
        bundle = load_dinov3_identity_bundle(bundle_root)
        if bundle.manifest.get("bundle_digest") != candidate["bundle_digest"]:
            raise ValueError(f"bundle digest differs from M12 lock: {candidate['candidate_id']}")
        if bundle.manifest.get("source_checkpoint_sha256") != candidate["checkpoint_sha256"]:
            raise ValueError(
                f"checkpoint digest differs from M12 lock: {candidate['candidate_id']}"
            )
        for name, expected in candidate["bundle_files_sha256"].items():
            path = bundle_root / name
            if not path.is_file() or digest_file(path) != expected:
                raise ValueError(
                    f"bundle file digest differs from M12 lock: {candidate['candidate_id']}/{name}"
                )
        classifier = DinoV3IdentityClassifier(bundle, device=device)
        classifiers[candidate["candidate_id"]] = classifier
        bundle_receipts[candidate["candidate_id"]] = {
            "bundle_digest": bundle.manifest["bundle_digest"],
            "load_latency_ms": classifier.load_latency_ms,
            "device": device,
        }

    m0, handoff, source_receipt = read_json(M0), read_json(HANDOFF), read_json(SOURCE_RECEIPT)
    if (
        source_receipt.get("failed_recordings")
        or source_receipt.get("verified_recording_count") != 20
    ):
        raise ValueError("0088 M1 source verification is incomplete")
    expected_sources = {
        item["recording_id"]: item for item in lock["test_membership"]["recordings"]
    }
    frozen_partition = m0["frozen_partitions"]["final_test"]
    if len(frozen_partition) != 1 or frozen_partition[0]["recording_id"] not in expected_sources:
        raise ValueError("M0 final-test partition differs from the M12 lock")
    recording_id = frozen_partition[0]["recording_id"]
    if frozen_partition[0]["source_group_id"] != expected_sources[recording_id]["source_group_id"]:
        raise ValueError("M0 source group differs from the M12 lock")
    handoff_row = next(row for row in handoff["recordings"] if row["recording_id"] == recording_id)
    if (
        handoff_row["source_group"]["source_sha256"]
        != expected_sources[recording_id]["source_video_sha256"]
    ):
        raise ValueError("0086 handoff source digest differs from the M12 lock")
    visible = selected_revision(recording_id, "visible_cards", handoff_row["visible_card_revision"])
    identity = selected_revision(
        recording_id, "visual_identities", handoff_row["visual_identity_revision"]
    )
    frozen_source = identity["manifest"].get("source")
    if not isinstance(frozen_source, dict):
        raise ValueError("final-test identity revision has no frozen source metadata")
    source, video_path = resolve_source(
        recording_id, expected_sources[recording_id]["source_video_sha256"], frozen_source
    )
    if identity["manifest"].get("source", {}).get("video_sha256") != source.video_sha256:
        raise ValueError("identity revision source differs from the verified recording")
    materialization_input = {
        "recording_id": recording_id,
        "source_lineage_group": dict(handoff_row["source_group"]),
        "source": source.to_mapping(),
        "visible_card_revision": visible,
        "visual_identity_revision": identity,
    }

    output.mkdir(parents=True)
    crop_root = output / "reviewed-final-crops"
    resolver = FFmpegFrameResolver()
    frame_cache: dict[bytes, Any] = {}

    def resolve(frame_identity: dict[str, Any]):
        key = canonical(frame_identity)
        if key not in frame_cache:
            resolved = resolver.resolve(
                ExactEventRequest(
                    source, frame_identity["requested_time_us"], frame_identity["output_encoding"]
                ),
                video_path,
            )
            if resolved.identity_mapping() != frame_identity:
                raise ValueError("resolved final-test frame differs from reviewed frame identity")
            frame_cache[key] = resolved
        return frame_cache[key]

    materialized = materialize_reviewed_visual_identity_crops(
        [materialization_input], crop_root, resolve
    )
    expected_count = lock["test_membership"]["expected_positive_crop_count"]
    membership = {
        "recording_id": recording_id,
        "source_video_sha256": source.video_sha256,
        "source_group_id": handoff_row["source_group"]["source_group_id"],
        "expected_count": expected_count,
        "actual_count": materialized["sample_count"],
        "materialization_digest": materialized["manifest_digest"],
        "crop_digests": [row["crop_sha256"] for row in materialized["samples"]],
        "class_support": {
            target: values["sample_count"]
            for target, values in materialized["class_support"].items()
            if values["sample_count"]
        },
        "exclusion_counts": materialized["exclusion_counts"],
    }
    if materialized["sample_count"] != expected_count:
        write_json(
            output / "membership-mismatch.json",
            {
                "schema_version": "0088-m13-membership-mismatch/v1",
                "lock_digest": lock["lock_digest"],
                "membership": membership,
                "status": "stopped_without_scoring",
            },
        )
        raise ValueError(
            "final-test membership did not resolve to exactly "
            f"{expected_count} eligible crops; stopped before scoring"
        )
    write_json(
        output / "membership.json",
        {
            "schema_version": "0088-m13-final-membership/v1",
            "lock_digest": lock["lock_digest"],
            **membership,
        },
    )
    # This durable marker prevents a second run if a provider call or process fails midway.
    write_json(
        output / "scoring-started.json",
        {
            "schema_version": "0088-m13-scoring-started/v1",
            "lock_digest": lock["lock_digest"],
            "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "candidate_ids": list(classifiers),
            "gemini_requests_planned": expected_count,
        },
    )

    gemini_lock = lock["gemini_reference"]
    gemini = GeminiCardClassifier.from_environment(
        model=gemini_lock["model"],
        timeout_s=gemini_lock["timeout_seconds"],
        max_retries=gemini_lock["automatic_retries"],
    )
    rows_by_candidate: dict[str, list[dict[str, Any]]] = {name: [] for name in classifiers}
    gemini_rows: list[dict[str, Any]] = []
    latencies: dict[str, list[float]] = {name: [] for name in classifiers}
    provider_cost = 0.0
    request_records: list[dict[str, Any]] = []
    for sample in materialized["samples"]:
        crop_bytes = (crop_root / sample["crop_path"]).read_bytes()
        crop_sha = digest_bytes(crop_bytes)
        if crop_sha != sample["crop_sha256"]:
            raise ValueError(f"materialized final crop changed: {sample['sample_id']}")
        frame_key = digest_bytes(canonical(sample["frame_identity"]))
        for candidate in lock["candidates"]:
            candidate_id = candidate["candidate_id"]
            result = classifiers[candidate_id].classify_ppm(crop_bytes)
            raw = result.raw_response
            if result.status != "ok" or not isinstance(raw, dict):
                prediction, top_k, probability, usable = "UNAVAILABLE", [], 0.0, False
            else:
                top_k = list(raw["ranked_targets"])
                prediction = top_k[0]
                probability = float(raw["ranked_probabilities"][0])
                usable = True
            latencies[candidate_id].append(float(result.latency_ms))
            rows_by_candidate[candidate_id].append(
                {
                    "sample_id": sample["sample_id"],
                    "recording_id": recording_id,
                    "source_group_id": handoff_row["source_group"]["source_group_id"],
                    "frame_key": frame_key,
                    "card_id": sample["card_id"],
                    "crop_sha256": crop_sha,
                    "target": sample["target"],
                    "prediction": prediction,
                    "top_k": top_k,
                    "top_1_probability": probability,
                    "usable": usable,
                    "latency_ms": float(result.latency_ms),
                    "raw_logits": raw.get("logits") if isinstance(raw, dict) else None,
                    "raw_probabilities": raw.get("raw_probabilities")
                    if isinstance(raw, dict)
                    else None,
                }
            )
        started = time.monotonic()
        response_schema = {
            "type": "object",
            "properties": {
                "card": {
                    "type": "string",
                    "enum": gemini_lock["response_schema"]["allowed_values"],
                }
            },
            "required": gemini_lock["response_schema"]["required"],
            "additionalProperties": gemini_lock["response_schema"]["additional_properties"],
        }
        request = CardClassificationRequest(
            crop_bytes=crop_bytes,
            model=gemini_lock["model"],
            prompt=gemini_lock["prompt"],
            response_schema=response_schema,
            api_version=gemini_lock["api_version"],
            thinking_level=gemini_lock["thinking_level"],
        )
        gemini_result = gemini.classify(request)
        request_key = request.request_key
        prediction = classify_gemini_result(gemini_result)
        provider_cost += float(gemini_result.estimated_cost_usd)
        gemini_row = {
            "sample_id": sample["sample_id"],
            "recording_id": recording_id,
            "source_group_id": handoff_row["source_group"]["source_group_id"],
            "frame_key": frame_key,
            "card_id": sample["card_id"],
            "crop_sha256": crop_sha,
            "request_key": request_key,
            "target": sample["target"],
            "prediction": prediction,
            "status": gemini_result.status,
            "failure_kind": gemini_result.failure_kind,
            "error": gemini_result.error,
            "retry_count": gemini_result.retry_count,
            "latency_ms": max(float(gemini_result.latency_ms), (time.monotonic() - started) * 1000),
            "estimated_cost_usd": float(gemini_result.estimated_cost_usd),
            "usable": gemini_result.status == "ok" and prediction != "UNKNOWN",
        }
        gemini_rows.append(gemini_row)
        request_records.append(
            {
                "sample_id": sample["sample_id"],
                "request_key": request_key,
                "crop_sha256": crop_sha,
                "status": gemini_result.status,
                "retry_count": gemini_result.retry_count,
                "estimated_cost_usd": float(gemini_result.estimated_cost_usd),
            }
        )
        write_json(
            output / "provider-request-ledger.json",
            {
                "schema_version": "0088-m13-provider-request-ledger/v1",
                "request_count": len(request_records),
                "requests": request_records,
                "estimated_cost_usd": provider_cost,
            },
        )
        if provider_cost > float(gemini_lock["spend_cap_usd"]):
            raise ValueError("Gemini estimated spend exceeded the locked USD 10 cap; stopped")

    evaluation_rows: dict[str, Any] = {}
    candidate_results: dict[str, Any] = {}
    for candidate in lock["candidates"]:
        cid = candidate["candidate_id"]
        rows = rows_by_candidate[cid]
        candidate_metrics = metrics(rows, is_dino=True)
        p95 = percentile(latencies[cid], 0.95)
        candidate_results[cid] = {
            **candidate_metrics,
            "bundle": bundle_receipts[cid],
            "latency": {
                "sample_count": len(latencies[cid]),
                "p50_ms": percentile(latencies[cid], 0.50),
                "p95_ms": p95,
            },
            "all_predictions": rows,
        }
        evaluation_rows[cid] = rows
    gemini_metrics = metrics(gemini_rows, is_dino=False)
    evaluation_rows["gemini"] = gemini_rows
    reference = {
        **gemini_metrics,
        "model": gemini_lock["model"],
        "request_count": len(request_records),
        "provider_failure_count": sum(row["status"] != "ok" for row in gemini_rows),
        "total_estimated_cost_usd": provider_cost,
        "all_predictions": gemini_rows,
    }
    groups = {row["source_group_id"] for row in gemini_rows}
    result = {
        "schema_version": "0088-m13-final-evaluation/v1",
        "status": "completed",
        "lock_digest": lock["lock_digest"],
        "membership": membership,
        "candidate_comparison_decision": lock["candidate_comparison_decision"],
        "candidate_results": candidate_results,
        "gemini_reference": reference,
        "paired_comparison": {
            cid: {
                "same_crop_count": len(
                    set(row["crop_sha256"] for row in evaluation_rows[cid])
                    & set(row["crop_sha256"] for row in gemini_rows)
                ),
                "candidate_minus_gemini_top_1_percentage_points": round(
                    100 * (candidate_results[cid]["top_1_accuracy"] - reference["top_1_accuracy"]),
                    4,
                ),
            }
            for cid in candidate_results
        },
        "quality_gates": lock["evaluation_contract"]["quality_gates"],
        "quality_decision": "insufficient_evidence_for_generalization_single_source_group",
        "independent_source_group_count": len(groups),
        "resource": {
            "physical_memory_bytes": _physical_memory_bytes(),
            "peak_rss_bytes": _peak_rss_bytes(),
            "peak_memory_fraction_of_physical_ram": (
                _peak_rss_bytes() / _physical_memory_bytes() if _physical_memory_bytes() else None
            ),
        },
    }
    result_bytes = json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2).encode() + b"\n"
    (output / "final-evaluation.json").write_bytes(result_bytes)
    result["result_sha256"] = digest_bytes(result_bytes)
    write_json(
        output / "receipt.json",
        {
            "schema_version": "0088-m13-final-evaluation-receipt/v1",
            "lock_digest": lock["lock_digest"],
            "result_sha256": result["result_sha256"],
            "crop_manifest_digest": materialized["manifest_digest"],
            "request_count": len(request_records),
            "gemini_estimated_cost_usd": provider_cost,
            "status": "completed",
        },
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=LOCK_DEFAULT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "mps", "cuda"), default="mps")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        result = run(
            args.lock if args.lock.is_absolute() else ROOT / args.lock, output, args.device
        )
    except Exception as error:
        print(f"M13 stopped: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": result["status"],
                "result": str(output / "final-evaluation.json"),
                "request_count": result["gemini_reference"]["request_count"],
                "gemini_estimated_cost_usd": result["gemini_reference"]["total_estimated_cost_usd"],
                "candidate_accuracy": {
                    key: value["top_1_accuracy"]
                    for key, value in result["candidate_results"].items()
                },
                "gemini_accuracy": result["gemini_reference"]["top_1_accuracy"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
