"""Preflight a manual batch of RF-DETR proposed-card-scene recordings."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_RECORDING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_PROVIDER_PATH = "/api/processors/visible-cards/local-rfdetr-segmentation/availability"


class ManualProposedCardScenePreflightError(ValueError):
    """The recording list or backend preflight could not be completed."""


def read_recording_ids(path: Path) -> list[str]:
    """Read one unique recording ID per non-empty line."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ManualProposedCardScenePreflightError(
            f"Could not read recording list {path}: {error}"
        ) from error
    recording_ids: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(lines, start=1):
        recording_id = raw.strip()
        if not recording_id:
            continue
        if _RECORDING_ID.fullmatch(recording_id) is None:
            errors.append(f"line {line_number}: invalid recording ID {recording_id!r}")
        elif recording_id in seen:
            errors.append(f"line {line_number}: duplicate recording ID {recording_id!r}")
        else:
            seen.add(recording_id)
            recording_ids.append(recording_id)
    if not recording_ids:
        errors.append("the list contains no recording IDs")
    if errors:
        raise ManualProposedCardScenePreflightError("; ".join(errors))
    return recording_ids


def _get_json(base_url: str, path: str, timeout_seconds: float) -> dict[str, Any]:
    request = Request(
        base_url.rstrip("/") + path,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as error:
        raise ManualProposedCardScenePreflightError(f"GET {path} failed: {error}") from error
    if not isinstance(payload, dict):
        raise ManualProposedCardScenePreflightError(f"GET {path} returned invalid JSON")
    return payload


def preflight_manual_proposed_card_scene_runs(
    recording_ids: list[str],
    *,
    base_url: str = "http://127.0.0.1:8000",
    timeout_seconds: float = 15.0,
    get_json: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check the backend, local provider, accepted recordings, and selected event revisions."""

    get = get_json or (lambda path: _get_json(base_url, path, timeout_seconds))
    report: dict[str, Any] = {
        "schema_version": "manual-proposed-card-scene-preflight/v1",
        "backend_url": base_url.rstrip("/"),
        "ready": False,
        "provider": None,
        "recordings": [],
        "errors": [],
    }
    try:
        health = get("/health/ready")
    except ManualProposedCardScenePreflightError as error:
        report["errors"].append(f"backend is unavailable: {error}")
        return report
    if health.get("status") != "ok":
        report["errors"].append("backend readiness check did not return status ok")

    try:
        provider = get(_PROVIDER_PATH)
        report["provider"] = provider
        if provider.get("available") is not True:
            report["errors"].append(
                "local-rfdetr-segmentation is unavailable: "
                + str(provider.get("error", "backend did not confirm provider availability"))
            )
    except ManualProposedCardScenePreflightError as error:
        report["errors"].append(f"local-rfdetr-segmentation availability check failed: {error}")

    try:
        catalog = get("/v1/recordings")
        entries = catalog.get("recordings")
        if not isinstance(entries, list):
            raise ManualProposedCardScenePreflightError(
                "recording catalog has no recordings list"
            )
        by_id = {
            entry.get("recording_id"): entry
            for entry in entries
            if isinstance(entry, Mapping) and isinstance(entry.get("recording_id"), str)
        }
    except ManualProposedCardScenePreflightError as error:
        report["errors"].append(f"recording catalog check failed: {error}")
        return report

    for recording_id in recording_ids:
        item: dict[str, Any] = {
            "recording_id": recording_id,
            "accepted_video": False,
            "event_revision_id": None,
            "errors": [],
        }
        if recording_id not in by_id:
            item["errors"].append("no accepted recording video is available")
        else:
            item["accepted_video"] = True
            try:
                selection_response = get(
                    f"/api/recordings/{recording_id}/pipeline/events/selection"
                )
                selection = selection_response.get("selection")
                if isinstance(selection, Mapping):
                    revision_id = (
                        selection.get("selected_completed_reference_revision_id")
                        or selection.get("selected_generated_revision_id")
                    )
                    if isinstance(revision_id, str) and revision_id:
                        item["event_revision_id"] = revision_id
                    else:
                        item["errors"].append("no selected event revision is available")
                else:
                    item["errors"].append("no selected event revision is available")
            except ManualProposedCardScenePreflightError as error:
                item["errors"].append(f"event selection check failed: {error}")
        if item["errors"]:
            report["errors"].extend(
                f"{recording_id}: {message}" for message in item["errors"]
            )
        report["recordings"].append(item)

    report["ready"] = not report["errors"] and len(report["recordings"]) == len(recording_ids)
    return report


def render_manual_proposed_card_scene_preflight(report: Mapping[str, Any]) -> str:
    """Render the preflight report as concise operator-facing text."""

    lines = [
        "Preflight ready" if report.get("ready") else "Preflight failed",
        f"Backend: {report.get('backend_url', 'unknown')}",
    ]
    provider = report.get("provider")
    if isinstance(provider, Mapping):
        lines.append(
            "RF-DETR provider: "
            + ("available" if provider.get("available") else "unavailable")
        )
        identity = provider.get("bundle_identity")
        if isinstance(identity, Mapping):
            digest = identity.get("bundle_digest")
            if isinstance(digest, str):
                lines.append(f"Bundle digest: {digest}")
    for item in report.get("recordings", []):
        if not isinstance(item, Mapping):
            continue
        event_revision = item.get("event_revision_id") or "missing"
        state = "ready" if not item.get("errors") else "blocked"
        lines.append(f"{item.get('recording_id')}: {state}; event revision {event_revision}")
    for error in report.get("errors", []):
        lines.append(f"Error: {error}")
    return "\n".join(lines)
