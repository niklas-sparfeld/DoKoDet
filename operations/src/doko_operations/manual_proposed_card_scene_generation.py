"""Generate proposed card scenes from selected local RF-DETR revisions."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from .manual_visible_card_detection import (
    ManualVisibleCardDetectionError,
    _output_revision_ids,
    _request_json,
    _run_status,
)

_TERMINAL_STATES = {"complete", "partial", "failed"}


class ManualProposedCardSceneGenerationError(ValueError):
    """The proposed-card-scene batch could not be started or polled."""


def run_manual_proposed_card_scene_generation(
    recording_ids: list[str],
    *,
    base_url: str = "http://127.0.0.1:8000",
    request_timeout_seconds: float = 30.0,
    run_timeout_seconds: float = 3600.0,
    poll_interval_seconds: float = 2.0,
    request_json: Callable[..., dict[str, Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    new_run_id: Callable[[], str] = lambda: f"card-scene-proposal-{uuid.uuid4()}",
) -> dict[str, Any]:
    """Preflight selected detector revisions, then run the proposal API for each."""

    if request_timeout_seconds <= 0 or run_timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise ManualProposedCardSceneGenerationError(
            "timeouts and poll interval must be greater than zero"
        )
    call = request_json or (
        lambda path, *, method, payload=None: _request_json(
            base_url,
            path,
            method=method,
            timeout_seconds=request_timeout_seconds,
            payload=payload,
        )
    )
    report: dict[str, Any] = {
        "schema_version": "manual-proposed-card-scene-generation/v1",
        "backend_url": base_url.rstrip("/"),
        "ready": False,
        "recordings": [],
        "errors": [],
    }

    # Check every selection before starting any proposal run.
    prepared: list[tuple[str, str]] = []
    for recording_id in recording_ids:
        path = f"/api/recordings/{recording_id}/pipeline/visible-cards"
        try:
            selection_response = call(f"{path}/selection", method="GET")
            selection = selection_response.get("selection")
            revision_id = (
                selection.get("selected_generated_revision_id")
                if isinstance(selection, Mapping)
                else None
            )
            if not isinstance(revision_id, str) or not revision_id:
                raise ManualProposedCardSceneGenerationError(
                    "no generated visible-card revision is selected"
                )
            runs_response = call(f"{path}/runs", method="GET")
            runs = runs_response.get("runs")
            matching = [
                run
                for run in runs or []
                if isinstance(run, Mapping)
                and _run_status(run) in {"complete", "partial"}
                and revision_id in _output_revision_ids(run)
                and isinstance(run.get("request"), Mapping)
                and isinstance(run["request"].get("model"), Mapping)
                and str(
                    run["request"]["model"].get("model_id")
                    or run["request"]["model"].get("name", "")
                ).startswith("local-rfdetr-")
            ]
            if not matching:
                raise ManualProposedCardSceneGenerationError(
                    f"selected revision {revision_id} is not a completed local RF-DETR result"
                )
            prepared.append((recording_id, revision_id))
        except (ManualVisibleCardDetectionError, ManualProposedCardSceneGenerationError) as error:
            report["errors"].append(f"{recording_id}: {error}")

    report["ready"] = not report["errors"] and len(prepared) == len(recording_ids)
    if not report["ready"]:
        return report

    for recording_id, revision_id in prepared:
        run_id = new_run_id()
        base_path = f"/api/recordings/{recording_id}/pipeline/proposed-card-scenes"
        record: dict[str, Any] = {
            "recording_id": recording_id,
            "visible_card_revision_id": revision_id,
            "run_id": run_id,
            "status": "not_started",
            "output_revision_ids": [],
            "calibration_revision_id": None,
            "supported_frame_count": None,
            "unsupported_frame_count": None,
            "failure": None,
            "error": None,
        }
        report["recordings"].append(record)
        try:
            run = call(
                base_path,
                method="POST",
                payload={"run_id": run_id, "visible_card_revision_id": revision_id},
            )
            if run.get("run_id") != run_id:
                raise ManualProposedCardSceneGenerationError(
                    f"backend returned unexpected run ID {run.get('run_id')!r}"
                )
            deadline = monotonic() + run_timeout_seconds
            while _run_status(run) not in _TERMINAL_STATES:
                if monotonic() >= deadline:
                    raise ManualProposedCardSceneGenerationError(
                        f"run {run_id} did not reach a terminal state within "
                        f"{run_timeout_seconds:g} seconds"
                    )
                sleep(poll_interval_seconds)
                run = call(f"{base_path}/{run_id}", method="GET")
            record["status"] = _run_status(run)
            record["output_revision_ids"] = _output_revision_ids(run)
            state = run.get("state")
            failure = run.get("failure")
            if failure is None and isinstance(state, Mapping):
                failure = state.get("failure") or state.get("terminal_failure")
            record["failure"] = failure
            if record["status"] in {"complete", "partial"}:
                result = call(f"{base_path}/{run_id}/result", method="GET")
                revisions = result.get("revisions")
                if isinstance(revisions, list):
                    for revision in revisions:
                        manifest = (
                            revision.get("manifest") if isinstance(revision, Mapping) else None
                        )
                        coverage = (
                            manifest.get("coverage") if isinstance(manifest, Mapping) else None
                        )
                        if not isinstance(manifest, Mapping) or not isinstance(coverage, Mapping):
                            continue
                        revision_id = manifest.get("revision_id")
                        if (
                            isinstance(revision_id, str)
                            and revision_id not in record["output_revision_ids"]
                        ):
                            record["output_revision_ids"].append(revision_id)
                        record["calibration_revision_id"] = coverage.get("calibration_revision_id")
                        record["supported_frame_count"] = coverage.get("supported_frame_count")
                        record["unsupported_frame_count"] = coverage.get("unsupported_frame_count")
            if record["status"] == "failed" and failure is not None:
                report["errors"].append(f"{recording_id}: {failure}")
        except (
            ManualVisibleCardDetectionError,
            ManualProposedCardSceneGenerationError,
            OSError,
            ValueError,
        ) as error:
            if record["status"] not in _TERMINAL_STATES:
                record["status"] = "unavailable"
            record["error"] = str(error)
            report["errors"].append(f"{recording_id}: {error}")

    return report


def render_manual_proposed_card_scene_generation(report: Mapping[str, Any]) -> str:
    """Render revision, calibration, and terminal outcome details."""

    lines = [
        "Proposal batch ready" if report.get("ready") else "Proposal batch blocked",
        f"Backend: {report.get('backend_url', 'unknown')}",
    ]
    for item in report.get("recordings", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"{item.get('recording_id')}: {item.get('status')}; "
            f"visible cards {item.get('visible_card_revision_id')}; "
            f"run {item.get('run_id')}; "
            f"outputs {', '.join(item.get('output_revision_ids', [])) or 'none'}; "
            f"calibration {item.get('calibration_revision_id') or 'none'}; "
            f"frames supported/unsupported "
            f"{item.get('supported_frame_count')}/{item.get('unsupported_frame_count')}"
        )
        if item.get("error"):
            lines.append(f"  Error: {item['error']}")
    for error in report.get("errors", []):
        lines.append(f"Error: {error}")
    return "\n".join(lines)


__all__ = [
    "ManualProposedCardSceneGenerationError",
    "render_manual_proposed_card_scene_generation",
    "run_manual_proposed_card_scene_generation",
]
