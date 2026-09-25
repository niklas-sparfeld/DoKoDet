"""Run and retain a manual batch of local RF-DETR visible-card detections."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .manual_proposed_card_scene_preflight import (
    ManualProposedCardScenePreflightError,
    preflight_manual_proposed_card_scene_runs,
)

_TERMINAL_STATES = {"complete", "partial", "failed"}


class ManualVisibleCardDetectionError(ValueError):
    """The manual visible-card batch could not be started or polled."""


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str,
    timeout_seconds: float,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        base_url.rstrip("/") + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as error:
        raise ManualVisibleCardDetectionError(f"{method} {path} failed: {error}") from error
    if not isinstance(result, dict):
        raise ManualVisibleCardDetectionError(f"{method} {path} returned invalid JSON")
    return result


def _run_status(run: Mapping[str, Any]) -> str | None:
    status = run.get("status")
    if isinstance(status, str):
        return status
    state = run.get("state")
    if isinstance(state, Mapping) and isinstance(state.get("status"), str):
        return state["status"]
    return None


def _output_revision_ids(run: Mapping[str, Any]) -> list[str]:
    state = run.get("state")
    values = state.get("output_revision_ids") if isinstance(state, Mapping) else None
    return [value for value in values if isinstance(value, str)] if isinstance(values, list) else []


def run_manual_visible_card_detection(
    recording_ids: list[str],
    *,
    base_url: str = "http://127.0.0.1:8000",
    request_timeout_seconds: float = 30.0,
    run_timeout_seconds: float = 3600.0,
    poll_interval_seconds: float = 2.0,
    preflight: Callable[[], dict[str, Any]] | None = None,
    request_json: Callable[..., dict[str, Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    new_run_id: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> dict[str, Any]:
    """Preflight all inputs, then run each recording through the workspace API."""

    if request_timeout_seconds <= 0 or run_timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise ManualVisibleCardDetectionError(
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
    check = preflight or (
        lambda: preflight_manual_proposed_card_scene_runs(
            recording_ids,
            base_url=base_url,
            timeout_seconds=request_timeout_seconds,
        )
    )
    try:
        readiness = check()
    except ManualProposedCardScenePreflightError as error:
        return {
            "schema_version": "manual-visible-card-detection/v1",
            "backend_url": base_url.rstrip("/"),
            "ready": False,
            "preflight": None,
            "recordings": [],
            "errors": [str(error)],
        }
    report: dict[str, Any] = {
        "schema_version": "manual-visible-card-detection/v1",
        "backend_url": base_url.rstrip("/"),
        "ready": bool(readiness.get("ready")),
        "preflight": readiness,
        "recordings": [],
        "errors": list(readiness.get("errors", [])),
    }
    if not report["ready"]:
        return report

    for item in readiness.get("recordings", []):
        if not isinstance(item, Mapping):
            continue
        recording_id = item.get("recording_id")
        event_revision_id = item.get("event_revision_id")
        if not isinstance(recording_id, str) or not isinstance(event_revision_id, str):
            report["errors"].append("preflight returned a recording without an event revision")
            continue
        run_id = new_run_id()
        record: dict[str, Any] = {
            "recording_id": recording_id,
            "event_revision_id": event_revision_id,
            "run_id": run_id,
            "status": "not_started",
            "input_revision_ids": [event_revision_id],
            "output_revision_ids": [],
            "model": None,
            "implementation": None,
            "error": None,
        }
        report["recordings"].append(record)
        base_path = f"/api/recordings/{recording_id}/pipeline/visible-cards/runs"
        run_request = {
            "request": {
                "run_id": run_id,
                "event_revision_id": event_revision_id,
                "configuration": {"provider": "local-rfdetr-segmentation"},
            }
        }
        try:
            started = call(base_path, method="POST", payload=run_request)
            if started.get("run_id") != run_id:
                raise ManualVisibleCardDetectionError(
                    f"backend returned unexpected run ID {started.get('run_id')!r}"
                )
            run: dict[str, Any] = started
            deadline = monotonic() + run_timeout_seconds
            while _run_status(run) not in _TERMINAL_STATES:
                if monotonic() >= deadline:
                    raise ManualVisibleCardDetectionError(
                        f"run {run_id} did not reach a terminal state within "
                        f"{run_timeout_seconds:g} seconds"
                    )
                sleep(poll_interval_seconds)
                run = call(f"{base_path}/{run_id}", method="GET")
            if run.get("run_id") != run_id:
                raise ManualVisibleCardDetectionError(
                    f"backend returned unexpected run ID {run.get('run_id')!r}"
                )
            record["status"] = _run_status(run)
            run_request_details = run.get("request")
            if isinstance(run_request_details, Mapping):
                record["input_revision_ids"] = run_request_details.get(
                    "input_revision_ids", [event_revision_id]
                )
                record["model"] = run_request_details.get("model")
                record["implementation"] = run_request_details.get("implementation")
                record["configuration"] = run_request_details.get("configuration")
            record["output_revision_ids"] = _output_revision_ids(run)
            if record["status"] in {"complete", "partial"}:
                result = call(f"{base_path}/{run_id}/result", method="GET")
                revisions = result.get("revisions")
                if isinstance(revisions, list) and not record["output_revision_ids"]:
                    record["output_revision_ids"] = [
                        revision.get("manifest", {}).get("revision_id")
                        for revision in revisions
                        if isinstance(revision, Mapping)
                        and isinstance(revision.get("manifest"), Mapping)
                        and isinstance(revision["manifest"].get("revision_id"), str)
                    ]
            state = run.get("state")
            failure = run.get("failure")
            if failure is None and isinstance(state, Mapping):
                failure = state.get("failure")
            if failure is not None:
                record["failure"] = failure
        except (ManualVisibleCardDetectionError, OSError, ValueError) as error:
            if record["status"] not in _TERMINAL_STATES:
                record["status"] = "unavailable"
            record["error"] = str(error)
            report["errors"].append(f"{recording_id}: {error}")

    return report


def render_manual_visible_card_detection(report: Mapping[str, Any]) -> str:
    """Render run lineage and terminal outcomes for the operator."""

    lines = [
        "Visible-card batch ready" if report.get("ready") else "Visible-card batch blocked",
        f"Backend: {report.get('backend_url', 'unknown')}",
    ]
    for item in report.get("recordings", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"{item.get('recording_id')}: {item.get('status')}; "
            f"event {item.get('event_revision_id')}; run {item.get('run_id')}; "
            f"outputs {', '.join(item.get('output_revision_ids', [])) or 'none'}"
        )
        if item.get("error"):
            lines.append(f"  Error: {item['error']}")
    for error in report.get("errors", []):
        lines.append(f"Error: {error}")
    return "\n".join(lines)


__all__ = [
    "ManualVisibleCardDetectionError",
    "render_manual_visible_card_detection",
    "run_manual_visible_card_detection",
]
