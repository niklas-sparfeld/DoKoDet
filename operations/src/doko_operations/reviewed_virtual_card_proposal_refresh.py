"""Audit the durable Epic 0086 proposal-refresh runs."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .rfdetr_segmentation_campaign import sha256_json

PROPOSAL_REFRESH_SCHEMA_VERSION = "reviewed-virtual-card-proposal-refresh/v1"
DEFAULT_INVENTORY = Path("docs/reports/0086-M0_Reviewed_Virtual_Card_Corpus_Inventory.json")
DEFAULT_OUTPUT = Path("docs/reports/0086-M3_Proposal_Refresh.json")
RUN_PREFIX = "card-scene-proposal-0086-91x59-"
GEOMETRY_VERSION = "card-plane-geometry/v6"
POSE_RECIPE_VERSION = "fixed-card-pose-grid-search/v5"
TERMINAL_STATES = {"complete", "partial", "failed"}


def _read(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read {label}: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _resolve(repository: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (repository / path).resolve()


def _proposal_recipe_version(frame: dict[str, Any]) -> str | None:
    proposal = frame.get("proposal")
    fit_diagnostics = proposal.get("fit_diagnostics") if isinstance(proposal, dict) else None
    diagnostics = fit_diagnostics.get("diagnostics") if isinstance(fit_diagnostics, dict) else None
    recipe = diagnostics.get("recipe") if isinstance(diagnostics, dict) else None
    version = recipe.get("recipe_version") if isinstance(recipe, dict) else None
    return version if isinstance(version, str) else None


def _terminal_failure(state: dict[str, Any]) -> dict[str, str] | None:
    failure = state.get("terminal_failure") or state.get("failure")
    if not isinstance(failure, dict):
        return None
    code = failure.get("code")
    message = failure.get("message")
    return {
        "code": str(code or "unknown_failure"),
        "message": str(message or "No failure message was recorded."),
    }


def _audit_detector_input(
    request: dict[str, Any],
    *,
    recording_id: str,
    event_revision_id: str,
    expected_frames: set[str],
    source: dict[str, Any],
    revisions_root: Path,
) -> dict[str, str]:
    input_revision_ids = request.get("input_revision_ids")
    if not isinstance(input_revision_ids, list) or len(input_revision_ids) != 1:
        raise ValueError(f"Proposal run does not select one detector revision for {recording_id}")
    revision_id = input_revision_ids[0]
    if not isinstance(revision_id, str):
        raise ValueError(f"Proposal run has an invalid detector revision ID for {recording_id}")
    revision_path = revisions_root / revision_id
    manifest = _read(revision_path / "manifest.json", "detector revision manifest")
    content = _read(revision_path / "content.json", "detector revision content")
    coverage = manifest.get("coverage")
    producer = manifest.get("producer")
    model_id = producer.get("model_id") if isinstance(producer, dict) else None
    event_ids = coverage.get("event_ids") if isinstance(coverage, dict) else None
    if (
        manifest.get("revision_id") != revision_id
        or manifest.get("recording_id") != recording_id
        or manifest.get("content_type") != "visible_cards"
        or manifest.get("content_schema") != "visible-card-data/v1"
        or manifest.get("content_sha256") != sha256_json(content)
        or manifest.get("source") != source
        or not isinstance(coverage, dict)
        or coverage.get("event_revision_id") != event_revision_id
        or not isinstance(event_ids, list)
        or set(event_ids) != expected_frames
        or not isinstance(model_id, str)
        or not model_id.startswith("local-rfdetr-")
    ):
        raise ValueError(f"Detector revision lineage is invalid for {recording_id}")
    return {
        "revision_id": revision_id,
        "content_sha256": manifest["content_sha256"],
        "model_id": model_id,
    }


def _load_runs(runs_root: Path, candidates: set[str]) -> dict[str, list[dict[str, Any]]]:
    by_recording: dict[str, list[dict[str, Any]]] = {
        recording_id: [] for recording_id in candidates
    }
    if not runs_root.is_dir():
        raise ValueError(f"Pipeline run store is missing: {runs_root}")
    for run_path in sorted(runs_root.iterdir()):
        if not run_path.name.startswith(RUN_PREFIX) or not run_path.is_dir():
            continue
        request_path = run_path / "request.json"
        state_path = run_path / "state.json"
        if not request_path.is_file() or not state_path.is_file():
            continue
        request = _read(request_path, "proposal run request")
        state = _read(state_path, "proposal run state")
        source = request.get("source")
        recording_id = source.get("recording_id") if isinstance(source, dict) else None
        if recording_id not in candidates:
            continue
        if request.get("processor_type") != "visible-card-scene-proposal":
            continue
        run_id = request.get("run_id")
        if run_id != run_path.name or state.get("run_id") != run_id:
            raise ValueError(f"Proposal run identity does not match its directory: {run_path}")
        by_recording[recording_id].append(
            {
                "run_id": run_id,
                "request": request,
                "state": state,
                "completed_at": str(state.get("completed_at") or state.get("updated_at") or ""),
                "created_at": str(state.get("created_at") or ""),
                "path": run_path,
            }
        )
    return by_recording


def _audit_recording(
    recording_id: str,
    inventory_record: dict[str, Any],
    runs: list[dict[str, Any]],
    revisions_root: Path,
) -> dict[str, Any]:
    if not runs:
        raise ValueError(f"No 0086 proposal-refresh run exists for {recording_id}")
    runs.sort(key=lambda run: (run["completed_at"], run["created_at"], run["run_id"]))
    selected = runs[-1]
    request = selected["request"]
    state = selected["state"]
    status = state.get("status")
    if status not in TERMINAL_STATES:
        raise ValueError(
            f"Latest proposal-refresh run is not terminal for {recording_id}: {status}"
        )

    expected_frames = inventory_record.get("event_frame_ids")
    if not isinstance(expected_frames, list) or not all(
        isinstance(frame, str) for frame in expected_frames
    ):
        raise ValueError(f"Frozen event frame scope is invalid for {recording_id}")
    if len(set(expected_frames)) != len(expected_frames):
        raise ValueError(f"Frozen event frame scope contains duplicates for {recording_id}")
    run_frames = state.get("item_ids")
    if not isinstance(run_frames, list):
        raise ValueError(f"Latest proposal run has invalid item scope for {recording_id}")
    if status in {"complete", "partial"} and set(run_frames) != set(expected_frames):
        raise ValueError(
            f"Latest proposal run does not match frozen event scope for {recording_id}"
        )
    if status == "failed" and run_frames and set(run_frames) != set(expected_frames):
        raise ValueError(f"Failed proposal run has an inconsistent item scope for {recording_id}")

    source = request.get("source")
    if not isinstance(source, dict) or source.get("recording_id") != recording_id:
        raise ValueError(f"Proposal run source lineage is missing for {recording_id}")
    event_revision_id = inventory_record.get("selected_event_revision_id")
    if not isinstance(event_revision_id, str):
        raise ValueError(f"Frozen event revision is missing for {recording_id}")
    detector = _audit_detector_input(
        request,
        recording_id=recording_id,
        event_revision_id=event_revision_id,
        expected_frames=set(expected_frames),
        source=source,
        revisions_root=revisions_root,
    )

    attempt_rows = [
        {
            "run_id": run["run_id"],
            "status": run["state"].get("status"),
            "completed_at": run["completed_at"],
            "failure": _terminal_failure(run["state"]),
        }
        for run in runs
    ]
    row: dict[str, Any] = {
        "recording_id": recording_id,
        "event_revision_id": inventory_record.get("selected_event_revision_id"),
        "source_video_sha256": source.get("video_sha256"),
        "event_frame_count": len(expected_frames),
        "processor_item_count": len(run_frames),
        "detector_revision_id": detector["revision_id"],
        "detector_revision_digest": detector["content_sha256"],
        "detector_model_id": detector["model_id"],
        "run_id": selected["run_id"],
        "run_status": status,
        "run_completed_at": selected["completed_at"],
        "attempts": attempt_rows,
        "proposal_revision_id": None,
        "proposal_content_sha256": None,
        "supported_frame_count": 0,
        "unsupported_frames": [],
        "failure": _terminal_failure(state),
    }

    revision_ids = state.get("output_revision_ids") or []
    if status == "failed":
        if revision_ids:
            raise ValueError(f"Failed run unexpectedly published proposals for {recording_id}")
        if row["failure"] is None:
            raise ValueError(f"Failed run has no terminal failure receipt for {recording_id}")
        row["unresolved_event_frame_ids"] = sorted(expected_frames)
        return row

    if len(revision_ids) != 1 or not isinstance(revision_ids[0], str):
        raise ValueError(f"Proposal result revision is missing or ambiguous for {recording_id}")
    revision_id = revision_ids[0]
    revision_path = revisions_root / revision_id
    manifest = _read(revision_path / "manifest.json", "proposal revision manifest")
    content = _read(revision_path / "content.json", "proposal revision content")
    if (
        manifest.get("revision_id") != revision_id
        or manifest.get("recording_id") != recording_id
        or manifest.get("content_type") != "card_scene_proposals"
        or manifest.get("content_schema") != "proposed-card-scene-data/v1"
        or manifest.get("content_sha256") != sha256_json(content)
        or manifest.get("source") != source
    ):
        raise ValueError(f"Proposal revision lineage or digest is invalid for {recording_id}")
    frames = content.get("frames")
    if not isinstance(frames, list):
        raise ValueError(f"Proposal content has no frame list for {recording_id}")
    frame_ids = [frame.get("frame_id") for frame in frames if isinstance(frame, dict)]
    if len(frame_ids) != len(frames) or set(frame_ids) != set(expected_frames):
        raise ValueError(f"Proposal revision does not match frozen event scope for {recording_id}")
    geometry_version = (content.get("calibration") or {}).get("algorithm_version")
    recipes = {_proposal_recipe_version(frame) for frame in frames}
    if geometry_version != GEOMETRY_VERSION or recipes != {POSE_RECIPE_VERSION}:
        raise ValueError(
            f"Proposal revisions use unexpected geometry or pose recipe for {recording_id}: "
            f"{geometry_version}, {sorted(str(recipe) for recipe in recipes)}"
        )
    coverage = manifest.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError(f"Proposal coverage is missing for {recording_id}")
    if (
        coverage.get("detector_revision_id") != detector["revision_id"]
        or coverage.get("detector_revision_digest") != detector["content_sha256"]
    ):
        raise ValueError(f"Proposal result detector lineage differs for {recording_id}")
    unsupported = [
        {
            "frame_id": frame["frame_id"],
            "reason": frame.get("unsupported_reason") or "No unsupported reason was recorded.",
        }
        for frame in frames
        if frame.get("status") == "unsupported"
    ]
    if any(frame.get("status") not in {"supported", "unsupported"} for frame in frames):
        raise ValueError(f"Proposal frame has an unknown status for {recording_id}")
    supported_count = sum(frame.get("status") == "supported" for frame in frames)
    if (
        coverage.get("supported_frame_count") != supported_count
        or coverage.get("unsupported_frame_count") != len(unsupported)
        or supported_count + len(unsupported) != len(expected_frames)
    ):
        raise ValueError(f"Proposal frame coverage is inconsistent for {recording_id}")
    if (status == "complete") != (not unsupported):
        raise ValueError(
            f"Proposal terminal status does not match frame coverage for {recording_id}"
        )
    row.update(
        {
            "proposal_revision_id": revision_id,
            "proposal_content_sha256": manifest["content_sha256"],
            "supported_frame_count": supported_count,
            "unsupported_frames": unsupported,
            "calibration_revision_id": manifest.get("coverage", {}).get("calibration_revision_id"),
            "calibration_digest": manifest.get("coverage", {}).get("calibration_digest"),
            "geometry_version": geometry_version,
            "pose_recipe_version": POSE_RECIPE_VERSION,
        }
    )
    if status == "partial" and not unsupported:
        raise ValueError(f"Partial proposal has no visible unsupported frames for {recording_id}")
    return row


def build_0086_proposal_refresh_report(
    repository_root: str | Path,
    *,
    inventory_path: str | Path = DEFAULT_INVENTORY,
) -> dict[str, Any]:
    """Build a digest-backed, read-only report of the frozen 0086 proposal refresh."""

    repository = Path(repository_root).expanduser().resolve()
    inventory_file = _resolve(repository, inventory_path)
    inventory = _read(inventory_file, "0086 M0 inventory")
    if inventory.get("schema_version") != "reviewed-virtual-card-corpus-work-manifest/v1":
        raise ValueError("0086 M0 inventory has an unsupported schema")
    inventory_core = {key: value for key, value in inventory.items() if key != "manifest_sha256"}
    if inventory.get("manifest_sha256") != sha256_json(inventory_core):
        raise ValueError("0086 M0 inventory digest does not match its contents")
    candidate_ids = inventory.get("scope", {}).get("candidate_recordings")
    records = inventory.get("recordings")
    if not isinstance(candidate_ids, list) or not isinstance(records, list):
        raise ValueError("0086 M0 inventory has no frozen candidate scope")
    records_by_id = {
        record.get("recording_id"): record for record in records if isinstance(record, dict)
    }
    if len(records_by_id) != len(records) or len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("0086 M0 inventory contains duplicate recording IDs")
    if set(candidate_ids) != set(records_by_id) & set(candidate_ids):
        raise ValueError("0086 M0 candidate scope has no inventory records")

    operations = repository / "data" / "operations" / "pipeline"
    runs = _load_runs(operations / "runs", set(candidate_ids))
    recordings = [
        _audit_recording(
            recording_id,
            records_by_id[recording_id],
            runs[recording_id],
            operations / "revisions",
        )
        for recording_id in candidate_ids
    ]
    status_counts = Counter(record["run_status"] for record in recordings)
    total_frames = sum(record["event_frame_count"] for record in recordings)
    supported = sum(record["supported_frame_count"] for record in recordings)
    unsupported = sum(len(record["unsupported_frames"]) for record in recordings)
    core: dict[str, Any] = {
        "schema_version": PROPOSAL_REFRESH_SCHEMA_VERSION,
        "status": "complete" if len(recordings) == len(candidate_ids) else "incomplete",
        "purpose": "proposal_refresh_audit",
        "source_inventory": {
            "path": inventory_file.relative_to(repository).as_posix(),
            "manifest_sha256": inventory["manifest_sha256"],
        },
        "scope": {
            "recording_ids": candidate_ids,
            "recording_count": len(recordings),
            "event_frame_count": total_frames,
            "geometry_version": GEOMETRY_VERSION,
            "pose_recipe_version": POSE_RECIPE_VERSION,
        },
        "summary": {
            "terminal_receipt_count": len(recordings),
            "status_counts": {
                key: status_counts.get(key, 0) for key in ("complete", "partial", "failed")
            },
            "published_proposal_revision_count": sum(
                record["proposal_revision_id"] is not None for record in recordings
            ),
            "supported_frame_count": supported,
            "unsupported_frame_count": unsupported,
            "unresolved_failure_recording_ids": [
                record["recording_id"] for record in recordings if record["run_status"] == "failed"
            ],
            "failed_run_frame_count": sum(
                record["event_frame_count"]
                for record in recordings
                if record["run_status"] == "failed"
            ),
            "event_frame_count_reconciles": supported
            + unsupported
            + sum(
                record["event_frame_count"]
                for record in recordings
                if record["run_status"] == "failed"
            )
            == total_frames,
        },
        "recordings": recordings,
    }
    core["report_sha256"] = sha256_json(core)
    return core


def validate_0086_proposal_refresh_report(report: dict[str, Any]) -> None:
    """Validate the report digest and frame-coverage accounting."""

    if report.get("schema_version") != PROPOSAL_REFRESH_SCHEMA_VERSION:
        raise ValueError("0086 proposal refresh report has an unsupported schema")
    digest = report.get("report_sha256")
    core = {key: value for key, value in report.items() if key != "report_sha256"}
    if digest != sha256_json(core):
        raise ValueError("0086 proposal refresh report digest does not match its contents")
    summary = report.get("summary")
    if not isinstance(summary, dict) or summary.get("event_frame_count_reconciles") is not True:
        raise ValueError("0086 proposal refresh frame coverage does not reconcile")


__all__ = [
    "DEFAULT_INVENTORY",
    "DEFAULT_OUTPUT",
    "GEOMETRY_VERSION",
    "POSE_RECIPE_VERSION",
    "PROPOSAL_REFRESH_SCHEMA_VERSION",
    "build_0086_proposal_refresh_report",
    "validate_0086_proposal_refresh_report",
]
