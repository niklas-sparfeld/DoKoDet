"""Compare and lock the CardEventNet M13 timing candidate."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import median
from typing import Any

from .cardevent_m12 import M12_CAMPAIGN_ID, M12_GATES
from .model_improvement import sha256_mapping

M13_SCHEMA_VERSION = "cardeventnet-m13-timing-comparison/v1"
M13_LOCK_SCHEMA_VERSION = "cardeventnet-m13-candidate-lock/v1"
M13_CAMPAIGN_ID = M12_CAMPAIGN_ID
M13_CANDIDATE_ID = "interval_endpoint_focus_v1"
M13_BASELINE_EVALUATION = "m13-baseline-successor-evaluation.json"


class CardEventM13Error(ValueError):
    """Raised when the M12 candidate cannot support an M13 comparison."""


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventM13Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise CardEventM13Error(f"{context} {path} must contain an object")
    return dict(value)


def _read_yaml(path: Path, context: str) -> dict[str, Any]:
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError, yaml.YAMLError) as error:
        raise CardEventM13Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise CardEventM13Error(f"{context} {path} must contain an object")
    return dict(value)


def _sha256_file(path: Path, context: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise CardEventM13Error(f"Could not hash {context} {path}: {error}") from error
    return digest.hexdigest()


def _required(path: Path, context: str) -> Path:
    if not path.is_file():
        raise CardEventM13Error(f"{context} is missing: {path}")
    return path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise CardEventM13Error(f"path must stay inside the repository: {path}") from error


def _write_immutable(path: Path, payload: bytes, context: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise CardEventM13Error(f"immutable M13 artifact differs: {path}")
    if not path.exists():
        path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any], context: str) -> str:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    return _write_immutable(path, payload, context)


def _number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CardEventM13Error(f"{context} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise CardEventM13Error(f"{context} must be finite")
    return result


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * 0.95
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _load_cardevent_stream(path: Path) -> tuple[Any, ...]:
    source_root = str(path.parents[4] / "card_event_net" / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    try:
        from cardevent.transition_diagnostics import load_validation_stream  # type: ignore
    except ImportError as error:
        raise CardEventM13Error("CardEventNet decoder sources are unavailable") from error
    try:
        return load_validation_stream(path)
    except (OSError, ValueError, RuntimeError) as error:
        raise CardEventM13Error(f"Could not load validation stream {path}: {error}") from error


def _stream_metrics(
    stream_path: Path,
    *,
    threshold: float,
    peak_confirmation_s: float,
    min_event_gap_s: float,
    event_match_tolerance_s: float,
) -> dict[str, Any]:
    """Replay the fixed decoder on a saved stream without model inference."""
    source_root = str(stream_path.parents[4] / "card_event_net" / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    try:
        from cardevent.events import (  # type: ignore
            classify_prediction_outcomes,
            probabilities_to_events,
        )
    except ImportError as error:
        raise CardEventM13Error("CardEventNet decoder sources are unavailable") from error
    videos = _load_cardevent_stream(stream_path)
    totals = {
        "point_matches": 0,
        "stable_end_matches": 0,
        "detections_inside_intervals": 0,
        "confirmed_no_event_triggers": 0,
        "duplicate_detections_per_reviewed_change": 0,
    }
    emission_delays: list[float] = []
    per_video: list[dict[str, Any]] = []
    for video in videos:
        events = probabilities_to_events(
            video.probabilities,
            threshold=threshold,
            peak_confirmation_s=peak_confirmation_s,
            min_event_gap_s=min_event_gap_s,
        )
        outcomes = classify_prediction_outcomes(
            events,
            video.ground_truth_intervals_s,
            tolerance_s=event_match_tolerance_s,
        )
        counts = {
            "point_matches": sum(item.outcome == "point_match" for item in outcomes),
            "stable_end_matches": sum(item.outcome == "stable_end_match" for item in outcomes),
            "detections_inside_intervals": sum(
                item.outcome == "in_progress_detection" for item in outcomes
            ),
            "confirmed_no_event_triggers": sum(
                item.outcome == "confirmed_false_trigger" for item in outcomes
            ),
        }
        duplicates = 0
        for start_s, end_s in video.ground_truth_intervals_s:
            matching = [
                event
                for event in events
                if abs(event.time_s - end_s) <= event_match_tolerance_s
                or start_s <= event.time_s < end_s
            ]
            duplicates += max(0, len(matching) - 1)
        counts["duplicate_detections_per_reviewed_change"] = duplicates
        for key in totals:
            totals[key] += counts[key]
        video_delays: list[float] = []
        for item in outcomes:
            if item.outcome not in {"point_match", "stable_end_match"}:
                continue
            if item.prediction.emitted_at_s is not None and item.anchor_time_s is not None:
                delay = item.prediction.emitted_at_s - float(item.anchor_time_s)
                emission_delays.append(delay)
                video_delays.append(delay)
        per_video.append(
            {
                "recording_id": video.name,
                "reviewed_changes": len(video.ground_truth_intervals_s),
                **counts,
                "event_presence_recall": (
                    (counts["point_matches"] + counts["stable_end_matches"])
                    / len(video.ground_truth_intervals_s)
                    if video.ground_truth_intervals_s
                    else 0.0
                ),
                "causal_emission_delay_p95_s": _p95(video_delays),
            }
        )
    reviewed_changes = sum(video["reviewed_changes"] for video in per_video)
    matched_changes = totals["point_matches"] + totals["stable_end_matches"]
    return {
        "event_diagnostics": totals,
        "event_presence": {
            "reviewed_changes": reviewed_changes,
            "matched_changes": matched_changes,
            "recall": matched_changes / reviewed_changes if reviewed_changes else 0.0,
        },
        "causal_emission_delay_s": {
            "count": len(emission_delays),
            "median": median(emission_delays) if emission_delays else 0.0,
            "p95": _p95(emission_delays),
        },
        "recordings": per_video,
    }


def evaluate_cardeventnet_m13_gates(
    metrics: Mapping[str, Any], gates: Mapping[str, Mapping[str, Any]] = M12_GATES
) -> dict[str, Any]:
    """Apply the immutable M12 validation gates to one replay result."""
    values = {
        "stable_end_matches": metrics["event_diagnostics"]["stable_end_matches"],
        "confirmed_no_event_triggers": metrics["event_diagnostics"]["confirmed_no_event_triggers"],
        "duplicate_detections_per_reviewed_change": metrics["event_diagnostics"][
            "duplicate_detections_per_reviewed_change"
        ],
        "causal_emission_delay_p95_s": metrics["causal_emission_delay_s"]["p95"],
        "event_presence_recall": metrics["event_presence"]["recall"],
    }
    result: dict[str, Any] = {}
    for name, value in values.items():
        gate = gates[name]
        if "minimum" in gate:
            limit = _number(gate["minimum"], f"gate {name}.minimum")
            passed = value >= limit
            comparison = "minimum"
        else:
            limit = _number(gate["maximum"], f"gate {name}.maximum")
            passed = value <= limit
            comparison = "maximum"
        result[name] = {
            "value": value,
            "limit": limit,
            "comparison": comparison,
            "passed": passed,
        }
    return result


def _failure_reasons(gates: Mapping[str, Mapping[str, Any]]) -> list[str]:
    reasons = []
    for name, gate in gates.items():
        if gate["passed"]:
            continue
        if gate["comparison"] == "minimum":
            reasons.append(f"{name} {gate['value']:.6g} is below minimum {gate['limit']:.6g}")
        else:
            reasons.append(f"{name} {gate['value']:.6g} exceeds maximum {gate['limit']:.6g}")
    return reasons


def _decoder(config: Mapping[str, Any]) -> dict[str, Any]:
    inference = config.get("inference")
    metrics = config.get("metrics")
    if not isinstance(inference, Mapping) or not isinstance(metrics, Mapping):
        raise CardEventM13Error("CardEventNet config has no inference or metrics section")
    return {
        "algorithm": "causal_peak",
        "peak_confirmation_s": _number(
            inference.get("peak_confirmation_s"), "decoder peak_confirmation_s"
        ),
        "min_event_gap_s": _number(inference.get("min_event_gap_s"), "decoder min_event_gap_s"),
        "event_match_tolerance_s": _number(
            metrics.get("event_match_tolerance_s"), "decoder event_match_tolerance_s"
        ),
    }


def _verify_successor_lineage(root: Path, m12: Mapping[str, Any]) -> dict[str, Any]:
    successor = dict(m12["lineage"]["successor_dataset"])
    dataset_dir = root / str(successor["path"])
    if not dataset_dir.is_dir():
        raise CardEventM13Error(f"successor dataset directory is missing: {dataset_dir}")
    dataset_path = _required(dataset_dir / "dataset.json", "successor dataset")
    split_path = _required(dataset_dir / "split.json", "successor split")
    dataset = _read_json(dataset_path, "successor dataset")
    split = _read_json(split_path, "successor split")
    if dataset.get("dataset_version_id") != successor["id"]:
        raise CardEventM13Error("successor dataset ID differs from M12")
    if dataset.get("dataset_version_digest") != successor["digest"]:
        raise CardEventM13Error("successor dataset digest differs from M12")
    if split.get("test_sealed") is not True:
        raise CardEventM13Error("successor test partition is not sealed")
    if _sha256_file(dataset_path, "successor dataset") != successor["dataset_sha256"]:
        raise CardEventM13Error("successor dataset file digest differs from M12")
    if _sha256_file(split_path, "successor split") != successor["split_sha256"]:
        raise CardEventM13Error("successor split file digest differs from M12")
    view = root / str(successor["materialized_view"])
    if not view.is_dir():
        raise CardEventM13Error(f"successor materialized view is missing: {view}")
    materialization = _read_json(
        _required(view / "materialization.json", "materialization manifest"),
        "materialization manifest",
    )
    if materialization.get("dataset") != {
        "id": successor["id"],
        "digest": successor["digest"],
    }:
        raise CardEventM13Error("materialized view is bound to a different successor dataset")
    successor["split_id"] = split["split_version_id"]
    successor["split_digest"] = split["split_version_digest"]
    return {"dataset": dataset, "split": split, "view": view, "successor": successor}


def _reference_lineage(dataset: Mapping[str, Any]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for entry in dataset.get("entries", []):
        if not isinstance(entry, Mapping):
            raise CardEventM13Error("successor dataset contains an invalid entry")
        for kind, path_key, sha_key in (
            (
                "event_reference_content",
                "event_revision_content_path",
                "event_revision_content_sha256",
            ),
            (
                "event_reference_manifest",
                "event_revision_manifest_path",
                "event_revision_manifest_sha256",
            ),
        ):
            references.append(
                {
                    "kind": kind,
                    "path": entry[path_key],
                    "recording_id": entry["recording_id"],
                    "sha256": entry[sha_key],
                }
            )
    return sorted(references, key=lambda item: (item["recording_id"], item["kind"]))


def _verify_m12_outputs(root: Path, campaign_dir: Path) -> dict[str, Any]:
    result_path = _required(campaign_dir / "m12-result.json", "M12 result")
    m12 = _read_json(result_path, "M12 result")
    result_core = {key: value for key, value in m12.items() if key not in {"result_digest"}}
    if m12.get("result_digest") != sha256_mapping(result_core):
        raise CardEventM13Error("M12 result digest does not match its contents")
    if m12.get("schema_version") != "cardeventnet-m12-timing-response/v1":
        raise CardEventM13Error("M12 result has an unsupported schema")
    if m12.get("sealed_test_read") or m12.get("system_holdout_read"):
        raise CardEventM13Error("M12 read sealed or system-holdout output")
    response = m12.get("response")
    if not isinstance(response, Mapping) or response.get("response_id") != M13_CANDIDATE_ID:
        raise CardEventM13Error("M12 did not select the expected timing candidate")
    for raw_path in m12.get("expected_outputs", []):
        _required(root / str(raw_path), "M12 expected output")
    lineage = _verify_successor_lineage(root, m12)
    run_dir = (
        root
        / "data/model-campaigns"
        / M13_CAMPAIGN_ID
        / "runs/candidate-interval-endpoint-focus-v1"
    )
    config_path = _required(run_dir / "config.yaml", "M12 candidate config")
    root_config = _required(root / str(response["config_path"]), "M12 response config")
    if _sha256_file(root_config, "M12 response config") != response["config_sha256"]:
        raise CardEventM13Error("M12 response config digest does not match its result")
    config = _read_yaml(config_path, "M12 candidate config")
    if config != _read_yaml(root_config, "M12 response config"):
        raise CardEventM13Error("candidate config differs from the M12 response config")
    candidate_eval_path = campaign_dir / "validation-evaluation.json"
    candidate_diag_path = campaign_dir / "validation-evaluation-transition-diagnostics.json"
    candidate_eval = _read_json(candidate_eval_path, "M12 validation evaluation")
    candidate_diag = _read_json(candidate_diag_path, "M12 transition diagnostics")
    candidate_identity = candidate_eval.get("data_identity")
    if not isinstance(candidate_identity, Mapping):
        raise CardEventM13Error("M12 validation evaluation has no data identity")
    if candidate_identity.get("dataset") != {
        "id": lineage["dataset"]["dataset_version_id"],
        "digest": lineage["dataset"]["dataset_version_digest"],
    }:
        raise CardEventM13Error("M12 validation evaluation uses a different dataset")
    if candidate_identity.get("split") != {
        "id": lineage["split"]["split_version_id"],
        "digest": lineage["split"]["split_version_digest"],
    }:
        raise CardEventM13Error("M12 validation evaluation uses a different split")
    if candidate_eval.get("partition") != "val":
        raise CardEventM13Error("M12 validation evaluation is not validation-only")
    if candidate_eval.get("transition_diagnostics") != _relative(root, candidate_diag_path):
        raise CardEventM13Error("M12 validation evaluation points to a different diagnostics file")
    references = sorted(
        candidate_identity.get("event_references", []),
        key=lambda item: (item.get("recording_id", ""), item.get("kind", "")),
    )
    expected_references = _reference_lineage(lineage["dataset"])
    if references != expected_references:
        raise CardEventM13Error(
            "M12 validation evaluation reference lineage differs from the successor dataset"
        )
    candidate_environment = _read_json(run_dir / "environment.json", "M12 candidate environment")
    candidate_summary = _read_json(run_dir / "summary.json", "M12 candidate summary")
    if candidate_summary.get("environment") != candidate_environment:
        raise CardEventM13Error("M12 candidate summary and environment differ")
    summary_identity = candidate_summary.get("data_identity")
    if not isinstance(summary_identity, Mapping):
        raise CardEventM13Error("M12 candidate summary has no data identity")
    identity_keys = set(candidate_identity) - {"environment"}
    if any(summary_identity.get(key) != candidate_identity.get(key) for key in identity_keys):
        raise CardEventM13Error("M12 candidate summary uses different data identity")
    if candidate_diag.get("threshold") != candidate_eval.get("threshold"):
        raise CardEventM13Error(
            "M12 evaluation and transition diagnostics use different thresholds"
        )
    return {
        "m12": m12,
        "lineage": lineage,
        "config": config,
        "candidate_eval": candidate_eval,
        "candidate_diag": candidate_diag,
        "candidate_environment": candidate_environment,
        "candidate_summary": candidate_summary,
        "candidate_checkpoint": _required(run_dir / "best.pt", "M12 candidate checkpoint"),
        "candidate_stream": _required(
            campaign_dir / "validation-streams" / "evaluation.json.gz",
            "M12 candidate validation stream",
        ),
    }


def _verify_baseline(
    root: Path,
    campaign_dir: Path,
    *,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_path = _required(campaign_dir / M13_BASELINE_EVALUATION, "M13 baseline evaluation")
    baseline = _read_json(baseline_path, "M13 baseline evaluation")
    if baseline.get("partition") != "val":
        raise CardEventM13Error("M13 baseline evaluation is not validation-only")
    if baseline.get("sealed_test_read") or baseline.get("system_holdout_read"):
        raise CardEventM13Error("M13 baseline evaluation read sealed or system-holdout output")
    successor = candidate["lineage"]["successor"]
    if baseline.get("successor_dataset_view") != successor["materialized_view"]:
        raise CardEventM13Error("M13 baseline evaluation uses a different materialized view")
    baseline_checkpoint = root / str(baseline.get("checkpoint"))
    _required(baseline_checkpoint, "M9 baseline checkpoint")
    expected_checkpoint = candidate["m12"]["lineage"]["m9_checkpoint"]
    if baseline.get("checkpoint") != expected_checkpoint["path"]:
        raise CardEventM13Error("M13 baseline evaluation uses a different checkpoint")
    if _sha256_file(baseline_checkpoint, "M9 baseline checkpoint") != expected_checkpoint["sha256"]:
        raise CardEventM13Error("M9 baseline checkpoint digest differs from M12 lineage")
    threshold_path = _required(
        root
        / "data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation"
        / "runs/candidate-hard-negative-v1/threshold.json",
        "M9 baseline threshold",
    )
    threshold = _read_json(threshold_path, "M9 baseline threshold")
    if baseline.get("threshold") != threshold.get("threshold"):
        raise CardEventM13Error("M13 baseline evaluation uses a different threshold")
    stream_path = _required(
        root / str(baseline["validation_stream"]), "M13 baseline validation stream"
    )
    candidate_videos = _load_cardevent_stream(candidate["candidate_stream"])
    baseline_videos = _load_cardevent_stream(stream_path)
    candidate_shape = [
        (video.name, video.ground_truth_times_s, video.ground_truth_intervals_s)
        for video in candidate_videos
    ]
    baseline_shape = [
        (video.name, video.ground_truth_times_s, video.ground_truth_intervals_s)
        for video in baseline_videos
    ]
    if candidate_shape != baseline_shape:
        raise CardEventM13Error("candidate and baseline do not use the same successor references")
    return {"payload": baseline, "path": baseline_path, "stream": stream_path}


def _verify_metric_summary(
    payload: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    metrics: Mapping[str, Any],
    *,
    context: str,
) -> None:
    overall = payload.get("overall")
    aggregate = diagnostics.get("aggregate")
    if not isinstance(overall, Mapping) or not isinstance(aggregate, Mapping):
        raise CardEventM13Error(f"{context} has no aggregate metrics")
    events = metrics["event_diagnostics"]
    expected_overall = {
        "real_events": metrics["event_presence"]["reviewed_changes"],
        "detected_true_events": metrics["event_presence"]["matched_changes"],
        "missed_events": (
            metrics["event_presence"]["reviewed_changes"]
            - metrics["event_presence"]["matched_changes"]
        ),
        "false_events": events["confirmed_no_event_triggers"],
        "in_progress_detections": events["detections_inside_intervals"],
    }
    for name, expected in expected_overall.items():
        if overall.get(name) != expected:
            raise CardEventM13Error(f"{context} {name} differs from the saved stream")
    stored_events = aggregate.get("event_diagnostics")
    if not isinstance(stored_events, Mapping):
        raise CardEventM13Error(f"{context} has no transition event diagnostics")
    transition_names = {
        "point_matches": "point_matches",
        "stable_end_matches": "stable_end_matches",
        "in_progress_detections": "detections_inside_intervals",
        "confirmed_false_triggers": "confirmed_no_event_triggers",
    }
    for name, metric_name in transition_names.items():
        if stored_events.get(name) != events[metric_name]:
            raise CardEventM13Error(f"{context} transition {name} differs from the saved stream")
    if stored_events.get("misses") != expected_overall["missed_events"]:
        raise CardEventM13Error(f"{context} transition misses differs from the saved stream")


def _lock_payload(
    *,
    result_digest: str,
    comparison_digest: str,
    root: Path,
    candidate: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    successor = candidate["lineage"]["successor"]
    identity = candidate["candidate_eval"]["data_identity"]
    core = {
        "schema_version": M13_LOCK_SCHEMA_VERSION,
        "campaign_id": M13_CAMPAIGN_ID,
        "candidate_id": M13_CANDIDATE_ID,
        "checkpoint": {
            "path": _relative(root, candidate["candidate_checkpoint"]),
            "sha256": _sha256_file(candidate["candidate_checkpoint"], "M13 candidate checkpoint"),
        },
        "threshold": {
            "value": candidate["candidate_eval"]["threshold"],
            "source": "candidate validation evaluation",
        },
        "decoder": _decoder(candidate["config"]),
        "data": {
            "dataset": {
                "id": successor["id"],
                "digest": successor["digest"],
                "path": successor["path"],
                "sha256": successor["dataset_sha256"],
            },
            "split": {
                "id": successor["split_id"],
                "digest": successor["split_digest"],
                "sha256": successor["split_sha256"],
                "partition": "val",
            },
            "reference_revisions": identity["event_references"],
            "hard_negative_manifest": candidate["m12"]["lineage"]["hard_negative_manifest"],
        },
        "validation": {
            "comparison_digest": comparison_digest,
            "result_digest": result_digest,
            "metrics": metrics,
        },
        "code": {
            "revision": candidate["candidate_environment"].get("git_commit"),
            "environment": candidate["candidate_environment"],
        },
        "sealed_test_read": False,
        "system_holdout_read": False,
    }
    return {**core, "lock_digest": sha256_mapping(core)}


def _render_report(result: Mapping[str, Any]) -> str:
    candidate = result["comparison"]["candidate"]["metrics"]
    baseline = result["comparison"]["baseline"]["metrics"]
    baseline_events = baseline["event_diagnostics"]
    candidate_events = candidate["event_diagnostics"]
    baseline_delay = baseline["causal_emission_delay_s"]["p95"]
    candidate_delay = candidate["causal_emission_delay_s"]["p95"]
    lines = [
        "# CardEventNet M13 timing comparison",
        "",
        f"- Campaign: `{result['campaign_id']}`",
        f"- Decision: `{result['decision']['state']}`",
        f"- Candidate: `{M13_CANDIDATE_ID}`",
        "",
        "M13 validates lineage before reading validation metrics. It reads no sealed test or "
        "system-holdout output.",
        "",
        "## Strict stable-end and interval-presence metrics",
        "",
        "| Metric | M9 baseline | M12 candidate |",
        "| --- | ---: | ---: |",
        f"| Stable-end matches | {baseline_events['stable_end_matches']} | "
        f"{candidate_events['stable_end_matches']} |",
        f"| Point matches | {baseline_events['point_matches']} | "
        f"{candidate_events['point_matches']} |",
        f"| Interval-presence recall | {baseline['event_presence']['recall']:.2%} | "
        f"{candidate['event_presence']['recall']:.2%} |",
        f"| Detections inside intervals | {baseline_events['detections_inside_intervals']} | "
        f"{candidate_events['detections_inside_intervals']} |",
        f"| Confirmed no-event triggers | {baseline_events['confirmed_no_event_triggers']} | "
        f"{candidate_events['confirmed_no_event_triggers']} |",
        f"| Duplicate detections per reviewed change | "
        f"{baseline_events['duplicate_detections_per_reviewed_change']} | "
        f"{candidate_events['duplicate_detections_per_reviewed_change']} |",
        f"| Causal emission delay p95 | {baseline_delay:.3f} s | {candidate_delay:.3f} s |",
        "",
        "## Gates",
        "",
        "| Gate | Value | Limit | Result |",
        "| --- | ---: | ---: | --- |",
    ]
    for name, gate in result["gates"].items():
        operator = ">=" if gate["comparison"] == "minimum" else "<="
        lines.append(
            f"| {name} | {gate['value']:.6g} | {operator} {gate['limit']:.6g} | "
            f"{'passed' if gate['passed'] else 'failed'} |"
        )
    lines.extend(["", "## Failure reasons", ""])
    if result["decision"]["failure_reasons"]:
        lines.extend(f"- {reason}" for reason in result["decision"]["failure_reasons"])
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "The candidate is not locked until every gate passes. M14 remains blocked.",
            "",
        ]
    )
    return "\n".join(lines)


def compare_cardeventnet_m13_timing_candidate(
    source_campaign_id: str,
    *,
    repository_root: str | Path,
    campaign_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate M12 outputs, compare the candidate, and write immutable M13 artifacts."""
    root = Path(repository_root).resolve()
    campaigns = Path(campaign_root or root / "data" / "model-campaigns")
    if not campaigns.is_absolute():
        campaigns = root / campaigns
    if source_campaign_id != M13_CAMPAIGN_ID:
        raise CardEventM13Error(f"M13 expects source campaign {M13_CAMPAIGN_ID}")
    campaign_dir = (campaigns / source_campaign_id).resolve()
    try:
        campaign_dir.relative_to(root)
    except ValueError as error:
        raise CardEventM13Error("M13 campaign directory must stay inside the repository") from error
    candidate = _verify_m12_outputs(root, campaign_dir)
    baseline = _verify_baseline(root, campaign_dir, candidate=candidate)
    candidate_config = candidate["config"]
    decoder = _decoder(candidate_config)
    candidate_metrics = _stream_metrics(
        candidate["candidate_stream"],
        threshold=_number(candidate["candidate_eval"]["threshold"], "candidate threshold"),
        peak_confirmation_s=decoder["peak_confirmation_s"],
        min_event_gap_s=decoder["min_event_gap_s"],
        event_match_tolerance_s=decoder["event_match_tolerance_s"],
    )
    _verify_metric_summary(
        candidate["candidate_eval"],
        candidate["candidate_diag"],
        candidate_metrics,
        context="M12 validation evaluation",
    )
    baseline_config_path = _required(
        campaign_dir.parent
        / "cardeventnet-0063-m9-hard-negative-ablation"
        / "runs/candidate-hard-negative-v1/config.yaml",
        "M9 baseline config",
    )
    baseline_config = _read_yaml(baseline_config_path, "M9 baseline config")
    baseline_decoder = _decoder(baseline_config)
    if baseline_decoder != decoder:
        raise CardEventM13Error("M9 baseline and M12 candidate use different decoder contracts")
    baseline_metrics = _stream_metrics(
        baseline["stream"],
        threshold=_number(baseline["payload"]["threshold"], "baseline threshold"),
        peak_confirmation_s=decoder["peak_confirmation_s"],
        min_event_gap_s=decoder["min_event_gap_s"],
        event_match_tolerance_s=decoder["event_match_tolerance_s"],
    )
    _verify_metric_summary(
        baseline["payload"],
        baseline["payload"]["transition_diagnostics"],
        baseline_metrics,
        context="M13 baseline evaluation",
    )
    if (
        baseline_metrics["event_presence"]["reviewed_changes"]
        != candidate_metrics["event_presence"]["reviewed_changes"]
    ):
        raise CardEventM13Error("candidate and baseline have different validation reference counts")
    comparison_core = {
        "schema_version": M13_SCHEMA_VERSION,
        "campaign_id": M13_CAMPAIGN_ID,
        "source_campaign_id": source_campaign_id,
        "comparison_contract": {
            "partition": "val",
            "decoder": decoder,
            "sealed_test_read": False,
            "system_holdout_read": False,
        },
        "candidate": {
            "candidate_id": M13_CANDIDATE_ID,
            "checkpoint": {
                "path": _relative(root, candidate["candidate_checkpoint"]),
                "sha256": _sha256_file(
                    candidate["candidate_checkpoint"], "M12 candidate checkpoint"
                ),
            },
            "threshold": candidate["candidate_eval"]["threshold"],
            "metrics": candidate_metrics,
        },
        "baseline": {
            "candidate_id": "m9_hard_negative_v1",
            "checkpoint": {
                "path": baseline["payload"]["checkpoint"],
                "sha256": _sha256_file(
                    root / baseline["payload"]["checkpoint"], "M9 baseline checkpoint"
                ),
            },
            "threshold": baseline["payload"]["threshold"],
            "metrics": baseline_metrics,
        },
        "lineage": {
            "successor_dataset": candidate["lineage"]["successor"],
            "reference_revisions": candidate["candidate_eval"]["data_identity"]["event_references"],
            "hard_negative_manifest": candidate["m12"]["lineage"]["hard_negative_manifest"],
            "m12_result_digest": candidate["m12"]["result_digest"],
        },
    }
    comparison = {**comparison_core, "comparison_digest": sha256_mapping(comparison_core)}
    comparison_path = campaign_dir / "m13-comparison.json"
    comparison_sha256 = _write_json(comparison_path, comparison, "M13 comparison")
    gates = evaluate_cardeventnet_m13_gates(candidate_metrics)
    failure_reasons = _failure_reasons(gates)
    locked = not failure_reasons
    lock_path = campaign_dir / "candidate-lock.json" if locked else None
    result_core = {
        "schema_version": M13_SCHEMA_VERSION,
        "campaign_id": M13_CAMPAIGN_ID,
        "source_campaign_id": source_campaign_id,
        "comparison_path": _relative(root, comparison_path),
        "comparison_sha256": comparison_sha256,
        "comparison_digest": comparison["comparison_digest"],
        "gates": gates,
        "decision": {
            "state": "candidate_locked" if locked else "human_review_required",
            "candidate_locked": locked,
            "failure_reasons": failure_reasons,
            "candidate_lock_path": _relative(root, lock_path) if lock_path else None,
        },
        "comparison": comparison,
        "sealed_test_read": False,
        "system_holdout_read": False,
    }
    result = {**result_core, "result_digest": sha256_mapping(result_core)}
    result_path = campaign_dir / "m13-result.json"
    result_sha256 = _write_json(result_path, result, "M13 result")
    if locked:
        lock = _lock_payload(
            result_digest=result["result_digest"],
            comparison_digest=comparison["comparison_digest"],
            root=root,
            candidate=candidate,
            metrics=candidate_metrics,
        )
        _write_json(lock_path, lock, "M13 candidate lock")
    report_path = campaign_dir / "m13-report.md"
    report_sha256 = _write_immutable(
        report_path, _render_report(result).encode("utf-8"), "M13 report"
    )
    result["result_path"] = _relative(root, result_path)
    result["result_sha256"] = result_sha256
    result["report_path"] = _relative(root, report_path)
    result["report_sha256"] = report_sha256
    return result


def render_cardeventnet_m13_human(result: Mapping[str, Any]) -> str:
    """Render a concise M13 CLI result."""

    candidate = result["comparison"]["candidate"]["metrics"]
    return (
        "CardEventNet M13 timing comparison\n"
        f"campaign: {result['campaign_id']}\n"
        f"decision: {result['decision']['state']}\n"
        f"stable-end matches: {candidate['event_diagnostics']['stable_end_matches']}\n"
        f"event-presence recall: {candidate['event_presence']['recall']:.2%}\n"
        f"comparison: {result['comparison_path']}\n"
        f"report: {result['report_path']}\n"
        f"candidate lock: {result['decision']['candidate_lock_path'] or 'not created'}\n"
        "sealed test read: false\n"
    )


__all__ = [
    "CardEventM13Error",
    "M13_CAMPAIGN_ID",
    "M13_SCHEMA_VERSION",
    "compare_cardeventnet_m13_timing_candidate",
    "evaluate_cardeventnet_m13_gates",
    "render_cardeventnet_m13_human",
]
