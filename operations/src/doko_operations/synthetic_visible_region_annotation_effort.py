"""Audit and publish the epic 0070 M6 annotation-effort decision.

M6 needs a small development batch that is outside the real training, validation, and sealed
test source groups.  This module freezes that boundary before any proposal is reviewed.  When
the frozen 0068 corpus has no such source group, it publishes the gap instead of reusing held-out
frames or inventing operator timing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .reviewed_rfdetr_detector_campaign import canonical_json_bytes

M6_SCHEMA_VERSION = "synthetic-visible-region-annotation-effort/v1"
M6_CAMPAIGN_ID = "0070-m6-synthetic-visible-region-annotation-effort"
SOURCE_MANIFEST_DEFAULT = "data/operations/rfdetr-visible-card-detector-0068-m0-manifest.json"
M5_MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-all-recordings.json"
M4_REPORT_DEFAULT = (
    "data/operations/synthetic-visible-region-0070-m4-50-50-training-comparison.json"
)
M6_REPORT_DEFAULT = "data/operations/synthetic-visible-region-0070-m6-annotation-effort.json"
_SHA256_LENGTH = 64


class SyntheticVisibleRegionAnnotationEffortError(ValueError):
    """The M6 annotation-effort audit cannot be trusted."""


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyntheticVisibleRegionAnnotationEffortError(
            f"could not read {field}: {path}"
        ) from error
    if not isinstance(value, Mapping):
        raise SyntheticVisibleRegionAnnotationEffortError(f"{field} must be an object")
    return dict(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise SyntheticVisibleRegionAnnotationEffortError(f"could not hash file: {path}") from error
    return digest.hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        raise SyntheticVisibleRegionAnnotationEffortError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise SyntheticVisibleRegionAnnotationEffortError(
            f"{field} must be a SHA-256 digest"
        ) from error
    return value


def _resolve(repository: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else repository / path


def _relative(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _verify_manifest_digest(manifest: Mapping[str, Any], field: str) -> str:
    declared = _require_digest(manifest.get("manifest_digest"), f"{field}.manifest_digest")
    core = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    if declared != _digest(core):
        raise SyntheticVisibleRegionAnnotationEffortError(f"{field} manifest digest is stale")
    return declared


def _recording_rows(manifest: Mapping[str, Any], field: str) -> list[dict[str, Any]]:
    rows = manifest.get("recordings")
    if not isinstance(rows, list) or not rows:
        raise SyntheticVisibleRegionAnnotationEffortError(f"{field}.recordings must be non-empty")
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise SyntheticVisibleRegionAnnotationEffortError(
                f"{field}.recordings has an invalid row"
            )
        recording_id = row.get("recording_id")
        source_split = row.get("source_split", row.get("split"))
        if not isinstance(recording_id, str) or not recording_id:
            raise SyntheticVisibleRegionAnnotationEffortError(
                f"{field}.recordings has a missing recording_id"
            )
        if source_split not in {"train", "validation", "sealed_test"}:
            raise SyntheticVisibleRegionAnnotationEffortError(
                f"{field}.recordings/{recording_id} has an invalid source split"
            )
        result.append({"recording_id": recording_id, "source_split": source_split})
    if len({row["recording_id"] for row in result}) != len(result):
        raise SyntheticVisibleRegionAnnotationEffortError(f"{field}.recordings has duplicate IDs")
    return result


def _metric_snapshot(report: Mapping[str, Any], candidate: str) -> dict[str, Any]:
    try:
        metrics = report["evaluation"]["artifacts"][candidate]["metrics"]["overall"]
    except (KeyError, TypeError) as error:
        raise SyntheticVisibleRegionAnnotationEffortError(
            f"M4 report is missing {candidate} overall metrics"
        ) from error
    if not isinstance(metrics, Mapping):
        raise SyntheticVisibleRegionAnnotationEffortError(
            f"M4 report {candidate} overall metrics must be an object"
        )
    fields = (
        "mask_ap_50_95",
        "mask_ap50",
        "box_ap50_95",
        "recall",
        "false_predictions",
        "duplicate_predictions",
        "empty_prediction_rate",
        "frame_count",
        "target_count",
    )
    return {field: metrics.get(field) for field in fields}


def build_synthetic_visible_region_m6_report(
    repository_root: str | Path,
    *,
    source_manifest_path: str | Path = SOURCE_MANIFEST_DEFAULT,
    m5_manifest_path: str | Path = M5_MANIFEST_DEFAULT,
    m4_report_path: str | Path = M4_REPORT_DEFAULT,
) -> dict[str, Any]:
    """Build the immutable M6 audit and decision without running a model or review UI."""

    repository = Path(repository_root).expanduser().resolve()
    source_path = _resolve(repository, source_manifest_path)
    m5_path = _resolve(repository, m5_manifest_path)
    m4_path = _resolve(repository, m4_report_path)

    source = _read_json(source_path, "0068 source manifest")
    source_digest = _verify_manifest_digest(source, "0068 source manifest")
    source_rows = source.get("recordings")
    if not isinstance(source_rows, list) or not source_rows:
        raise SyntheticVisibleRegionAnnotationEffortError("0068 source manifest has no recordings")
    source_by_id: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        if not isinstance(row, Mapping):
            raise SyntheticVisibleRegionAnnotationEffortError(
                "0068 source manifest has an invalid recording"
            )
        recording_id = row.get("recording_id")
        source_split = row.get("split")
        if not isinstance(recording_id, str) or source_split not in {
            "train",
            "validation",
            "sealed_test",
        }:
            raise SyntheticVisibleRegionAnnotationEffortError(
                "0068 source manifest has an invalid recording split"
            )
        source_by_id[recording_id] = {
            "recording_id": recording_id,
            "source_split": source_split,
            "source_group": row.get("source_group"),
        }
    if len(source_by_id) != len(source_rows):
        raise SyntheticVisibleRegionAnnotationEffortError(
            "0068 source manifest has duplicate recordings"
        )

    m5 = _read_json(m5_path, "M5 all-recordings manifest")
    m5_digest = _verify_manifest_digest(m5, "M5 all-recordings manifest")
    if m5.get("source_manifest", {}).get("manifest_digest") != source_digest:
        raise SyntheticVisibleRegionAnnotationEffortError(
            "M5 manifest points to another 0068 source manifest"
        )
    m5_rows = _recording_rows(m5, "M5 all-recordings manifest")
    if {row["recording_id"] for row in m5_rows} != set(source_by_id):
        raise SyntheticVisibleRegionAnnotationEffortError(
            "M5 all-recordings manifest does not cover exactly the 0068 source recordings"
        )
    for row in m5_rows:
        if row["source_split"] != source_by_id[row["recording_id"]]["source_split"]:
            raise SyntheticVisibleRegionAnnotationEffortError(
                f"M5 source split disagrees for {row['recording_id']}"
            )

    m4 = _read_json(m4_path, "M4 comparison report")
    m4_digest = _verify_manifest_digest(m4, "M4 comparison report")
    if m4.get("status") != "completed":
        raise SyntheticVisibleRegionAnnotationEffortError("M4 comparison is not completed")
    control_metrics = _metric_snapshot(m4, "control_validation")
    synthetic_metrics = _metric_snapshot(m4, "synthetic_validation")
    metric_delta = {
        field: (
            synthetic_metrics[field] - control_metrics[field]
            if isinstance(synthetic_metrics[field], (int, float))
            and isinstance(control_metrics[field], (int, float))
            else None
        )
        for field in ("mask_ap_50_95", "mask_ap50", "box_ap50_95", "recall")
    }

    training_ids = sorted(
        recording_id
        for recording_id, row in source_by_id.items()
        if row["source_split"] == "train"
    )
    validation_ids = sorted(
        recording_id
        for recording_id, row in source_by_id.items()
        if row["source_split"] == "validation"
    )
    sealed_ids = sorted(
        recording_id
        for recording_id, row in source_by_id.items()
        if row["source_split"] == "sealed_test"
    )
    excluded_ids = sorted(set(training_ids) | set(validation_ids) | set(sealed_ids))
    development_ids = sorted(set(source_by_id) - set(excluded_ids))
    if development_ids:
        raise SyntheticVisibleRegionAnnotationEffortError(
            "M6 source audit found unexpected development IDs inside the frozen 0068 manifest"
        )

    decision = "retain_as_experiment"
    rationale = (
        "The synthetic candidate improved the frozen real validation metrics, but the frozen "
        "corpus has no source group outside training, validation, or sealed test. No legal M6 "
        "development batch exists, so human correction timing and proposal actions were not "
        "measured. Keep the candidate available for a later development-only pilot; do not use it "
        "as an annotation prefill and do not change a runtime default."
    )
    report_core: dict[str, Any] = {
        "campaign_id": M6_CAMPAIGN_ID,
        "milestone": "M6",
        "status": "complete_with_declared_gap",
        "freeze_state": "complete_with_declared_gap",
        "inputs": {
            "source_manifest": {
                "path": _relative(source_path, repository),
                "sha256": _sha256_file(source_path),
                "manifest_digest": source_digest,
            },
            "m5_recording_audit": {
                "path": _relative(m5_path, repository),
                "sha256": _sha256_file(m5_path),
                "manifest_digest": m5_digest,
            },
            "m4_comparison": {
                "path": _relative(m4_path, repository),
                "sha256": _sha256_file(m4_path),
                "manifest_digest": m4_digest,
            },
        },
        "development_batch": {
            "status": "unavailable",
            "source_group_count": 0,
            "frame_count": 0,
            "source_group_ids": development_ids,
            "excluded_recordings": {
                "train": training_ids,
                "validation": validation_ids,
                "sealed_test": sealed_ids,
            },
            "reason": (
                "All frozen 0068 source groups are already assigned to training, validation, "
                "or sealed test. Reusing any of them would violate the M6 development-frame gate."
            ),
        },
        "proposal_pilot": {
            "status": "not_run",
            "source_order": [],
            "proposal_sources": ["control", "synthetic_addition"],
            "review_contract": "human-authored-maintained-reference/v1",
            "timing": {
                "status": "not_measured",
                "active_correction_seconds": None,
                "model_execution_seconds": None,
                "operator_idle_seconds": None,
            },
            "actions": {
                "accepted_proposals": 0,
                "reshapes": 0,
                "additions": 0,
                "removals": 0,
                "missed_cards": 0,
                "extra_cards": 0,
                "visible_card_ignore_regions": 0,
            },
            "reason": "No legal development batch was available; no proposals were reviewed.",
        },
        "model_metrics": {
            "control_validation": control_metrics,
            "synthetic_addition_validation": synthetic_metrics,
            "synthetic_minus_control": metric_delta,
            "sealed_test": "unchanged_from_M4_and_not_repeated_in_M6",
        },
        "visual_failures": {
            "status": "not_measured_in_M6",
            "known_m4_coverage_gaps": list(m4.get("coverage_gaps", [])),
        },
        "decision": {
            "outcome": decision,
            "rationale": rationale,
            "provider_promoted": False,
            "runtime_default_changed": False,
            "synthetic_contributors_counted_as_real_coverage": False,
            "final_reference_authority": "human",
        },
        "coverage_gaps": [
            "no source group remains for a legal M6 development batch",
            "human correction time and action counts were not measured",
            "face_down and mixed_card_sides synthetic buckets remain unavailable",
        ],
    }
    report = {"schema_version": M6_SCHEMA_VERSION, **report_core}
    report["manifest_digest"] = _digest(report)
    return report


def write_synthetic_visible_region_m6_report(path: str | Path, report: Mapping[str, Any]) -> Path:
    """Write one canonical M6 report and reject stale or malformed digests."""

    if report.get("schema_version") != M6_SCHEMA_VERSION:
        raise SyntheticVisibleRegionAnnotationEffortError("invalid M6 report schema")
    declared = _require_digest(report.get("manifest_digest"), "M6 report manifest_digest")
    if declared != _digest(
        {key: value for key, value in report.items() if key != "manifest_digest"}
    ):
        raise SyntheticVisibleRegionAnnotationEffortError("M6 report digest is stale")
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(report) + b"\n")
    temporary.replace(destination)
    return destination


def render_synthetic_visible_region_m6_human(report: Mapping[str, Any]) -> str:
    """Render the compact operator-facing M6 decision."""

    development = report["development_batch"]
    decision = report["decision"]
    delta = report["model_metrics"]["synthetic_minus_control"]
    return (
        "M6 annotation-effort audit\n"
        f"state: {report['status']}\n"
        f"development source groups: {development['source_group_count']}\n"
        f"development frames: {development['frame_count']}\n"
        f"validation mask AP delta: {delta['mask_ap_50_95']:+.6f}\n"
        f"validation recall delta: {delta['recall']:+.6f}\n"
        f"decision: {decision['outcome']}\n"
        f"report digest: {report['manifest_digest']}\n"
    )


__all__ = [
    "M4_REPORT_DEFAULT",
    "M5_MANIFEST_DEFAULT",
    "M6_REPORT_DEFAULT",
    "M6_SCHEMA_VERSION",
    "SOURCE_MANIFEST_DEFAULT",
    "SyntheticVisibleRegionAnnotationEffortError",
    "build_synthetic_visible_region_m6_report",
    "render_synthetic_visible_region_m6_human",
    "write_synthetic_visible_region_m6_report",
]
