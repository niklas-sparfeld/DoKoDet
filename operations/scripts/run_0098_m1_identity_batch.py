"""Run the frozen 0098 M1 identity proposals through the local backend."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class BatchError(RuntimeError):
    """Raised when the frozen batch contract is not met."""


def _json_request(url: str, *, method: str = "GET", payload: Any = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise FileNotFoundError(url) from error
        detail = error.read().decode("utf-8", errors="replace")
        raise BatchError(f"backend returned HTTP {error.code}: {detail}") from error
    except (OSError, TimeoutError, json.JSONDecodeError) as error:
        raise BatchError(f"backend request failed: {url}") from error
    if not isinstance(value, dict):
        raise BatchError(f"backend returned a non-object response: {url}")
    return value


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.chmod(temporary, 0o644)
    temporary.replace(path)


def _rss_bytes(pid: int) -> int | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        value = result.stdout.strip()
        return None if not value else int(value) * 1024
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _read_run(base: str, recording_id: str, run_id: str) -> dict[str, Any] | None:
    try:
        return _json_request(
            f"{base}/api/recordings/{recording_id}/pipeline/visual-identities/{run_id}"
        )
    except FileNotFoundError:
        return None


def _validate_request(run: dict[str, Any], frozen: dict[str, Any]) -> None:
    request = run.get("request", {})
    if run.get("run_id") != frozen["planned_identity_run_id"]:
        raise BatchError("retained run ID does not match the frozen run ID")
    if request.get("input_revision_ids") != [frozen["m1_revision_id"]]:
        raise BatchError("retained run uses a different visible-card revision")
    if request.get("source", {}).get("video_sha256") != frozen["source_video_sha256"]:
        raise BatchError("retained run uses a different source video")
    if request.get("configuration", {}).get("provider") != "local-dinov3":
        raise BatchError("retained run does not use the pinned local DINOv3 processor")
    if request.get("configuration", {}).get("purpose") != "auto_approval_comparison":
        raise BatchError("retained run could advance the generated identity selection")
    if request.get("crop_policy") != {
        "output_encoding": "ppm",
        "policy_id": "predicted_visible_region",
    }:
        raise BatchError("retained run does not use the frozen predicted-visible crop recipe")
    crop_input = request.get("crop_input", {})
    if crop_input.get("source_revision_id") != frozen["m1_revision_id"]:
        raise BatchError("retained crop input uses a different visible-card revision")
    if crop_input.get("source_view_digest") != frozen["m1_revision_sha256"]:
        raise BatchError("retained crop input digest differs from the frozen visible-card digest")
    if len(crop_input.get("items", [])) != frozen["usable_crop_geometry_count"]:
        raise BatchError("retained crop count differs from the frozen geometry count")


def _result_record(base: str, recording_id: str, run: dict[str, Any]) -> dict[str, Any]:
    result = _json_request(
        f"{base}/api/recordings/{recording_id}/pipeline/visual-identities/{run['run_id']}/result"
    )
    revisions = result.get("revisions", [])
    if len(revisions) != 1:
        raise BatchError(f"{recording_id}: expected one immutable output revision")
    revision = revisions[0]
    outcomes = revision.get("content", {}).get("outcomes", [])
    statuses = Counter(item.get("status", "missing") for item in outcomes)
    latency = [
        item["diagnostics"]["latency_ms"]
        for item in outcomes
        if isinstance(item.get("diagnostics"), dict)
        and isinstance(item["diagnostics"].get("latency_ms"), (int, float))
    ]
    return {
        "run_id": run["run_id"],
        "status": run["state"]["status"],
        "attempt": run["attempt"],
        "input_revision_ids": run["request"]["input_revision_ids"],
        "crop_input_manifest_digest": run["request"]["crop_input"]["manifest_digest"],
        "crop_input_item_count": len(run["request"]["crop_input"]["items"]),
        "output_revision_id": revision["manifest"]["revision_id"],
        "output_content_sha256": revision["manifest"]["content_sha256"],
        "output_outcome_count": len(outcomes),
        "outcomes_by_status": dict(sorted(statuses.items())),
        "latency_ms_count": len(latency),
        "latency_ms_sum": round(sum(latency), 3),
        "classifier_identities": sorted(
            {json.dumps(item.get("classifier", {}), sort_keys=True) for item in outcomes}
        ),
        "started_at": run["state"].get("started_at"),
        "completed_at": run["state"].get("completed_at"),
    }


def run_batch(manifest_path: Path, output_path: Path, base: str, pid: int) -> dict[str, Any]:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("epic") != "0098" or manifest.get("milestone") != "M0":
        raise BatchError("input is not the frozen 0098 M0 manifest")
    if manifest.get("classifier_runs") != 0:
        raise BatchError("M0 manifest already records classifier activity")
    if manifest.get("model", {}).get("bundle_sha256") != (
        "a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79"
    ):
        raise BatchError("M0 manifest does not pin the expected 0088 M6 bundle")
    included = [item for item in manifest["recordings"] if item.get("disposition") == "included"]
    if len(included) != manifest["coverage"]["included_recordings"]:
        raise BatchError("included recording count differs from the frozen M0 coverage")
    if (
        sum(item["usable_crop_geometry_count"] for item in included)
        != manifest["budgets"]["crop_cap"]
    ):
        raise BatchError("frozen crop counts do not sum to the M1 crop cap")

    now = datetime.now(UTC).isoformat()
    report: dict[str, Any] = {
        "schema_version": "0098-m1-identity-batch/v1",
        "epic": "0098",
        "milestone": "M1",
        "status": "running",
        "started_at": now,
        "frozen_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "backend_base_url": base,
        "backend_pid": pid,
        "limits": manifest["budgets"],
        "cloud_requests": 0,
        "classifier": {
            "provider": "local-dinov3",
            "bundle_sha256": manifest["model"]["bundle_sha256"],
            "checkpoint_sha256": manifest["model"]["checkpoint_sha256"],
            "temperature": manifest["model"]["temperature"],
            "bundle_path": (
                "/Users/niklas.sparfeld/Developer/doko_detector/.runtime/"
                "dinov3-identity-0088/m12-final-lock/m6-candidate-bundle"
            ),
            "device": "mps",
            "max_concurrent_requests": 1,
        },
        "recordings": {},
        "rss_samples": [],
        "maximum_rss_bytes": 0,
        "stop_reason": None,
    }
    active_started = time.monotonic()
    processing_seconds = 0.0
    max_rss = 0
    stop = False
    sampling_stop = threading.Event()

    def sample_rss_periodically() -> None:
        nonlocal max_rss
        interval = manifest["budgets"]["rss_sample_interval_seconds"]
        deadline = time.monotonic()
        while not sampling_stop.is_set():
            rss = _rss_bytes(pid)
            report["rss_samples"].append(
                {"sampled_at": datetime.now(UTC).isoformat(), "rss_bytes": rss}
            )
            if rss is not None:
                max_rss = max(max_rss, rss)
            report["maximum_rss_bytes"] = max_rss
            deadline += interval
            if sampling_stop.wait(max(0.0, deadline - time.monotonic())):
                break

    sampler = threading.Thread(target=sample_rss_periodically, daemon=True)
    sampler.start()
    for frozen in manifest["recordings"]:
        if frozen.get("disposition") != "included":
            continue
        if processing_seconds >= manifest["budgets"]["active_processing_seconds"]:
            report["stop_reason"] = "active_processing_budget_exhausted"
            stop = True
            break
        if max_rss > manifest["budgets"]["process_rss_bytes"]:
            report["stop_reason"] = "process_rss_budget_exceeded"
            stop = True
            break

        recording_id = frozen["recording_id"]
        run_id = frozen["planned_identity_run_id"]
        run = _read_run(base, recording_id, run_id)
        if run is None:
            payload = {
                "run_id": run_id,
                "input_revision_ids": [frozen["m1_revision_id"]],
                "configuration": {
                    "provider": "local",
                    # Backend skips generated-pointer movement for this local-only purpose.
                    "purpose": "auto_approval_comparison",
                },
                "extraction_policy": {
                    "policy_id": "exact-event/v1",
                    "output_encoding": "jpeg",
                },
                "crop_policy": {
                    "policy_id": "predicted_visible_region",
                    "output_encoding": "ppm",
                },
            }
            run = _json_request(
                f"{base}/api/recordings/{recording_id}/pipeline/visual-identities",
                method="POST",
                payload=payload,
            )
        _validate_request(run, frozen)
        state = run.get("state", {})
        if state.get("status") == "failed":
            report["recordings"][recording_id] = {
                "run_id": run_id,
                "status": "failed_terminal_no_retry",
                "failure": state.get("failure"),
            }
            _atomic_write(output_path, report)
            continue

        run_started = time.monotonic()
        while state.get("status") in {"queued", "running"}:
            elapsed = time.monotonic() - active_started
            processing_seconds = elapsed
            if elapsed >= manifest["budgets"]["active_processing_seconds"]:
                report["stop_reason"] = "active_processing_budget_exhausted_with_run_active"
                stop = True
                break
            if max_rss > manifest["budgets"]["process_rss_bytes"]:
                report["stop_reason"] = "process_rss_budget_exceeded_with_run_active"
                stop = True
                break
            time.sleep(2)
            run = _json_request(
                f"{base}/api/recordings/{recording_id}/pipeline/visual-identities/{run_id}"
            )
            _validate_request(run, frozen)
            state = run.get("state", {})

        report["active_processing_seconds"] = round(time.monotonic() - active_started, 3)
        if stop:
            report["recordings"][recording_id] = {
                "run_id": run_id,
                "status": state.get("status", "unknown"),
                "detail": "Run retained; no later recording was started.",
            }
            _atomic_write(output_path, report)
            break

        elapsed_run = time.monotonic() - run_started
        processing_seconds = time.monotonic() - active_started
        if state.get("status") in {"complete", "partial"}:
            record = _result_record(base, recording_id, run)
            if record["crop_input_item_count"] != record["output_outcome_count"]:
                record["unprocessed_count"] = (
                    record["crop_input_item_count"] - record["output_outcome_count"]
                )
            else:
                record["unprocessed_count"] = 0
            record["elapsed_poll_seconds"] = round(elapsed_run, 3)
            record["status"] = state["status"]
            report["recordings"][recording_id] = record
        else:
            report["recordings"][recording_id] = {
                "run_id": run_id,
                "status": state.get("status", "unknown"),
                "failure": state.get("failure"),
            }
        _atomic_write(output_path, report)

    sampling_stop.set()
    sampler.join(timeout=5)
    report["active_processing_seconds"] = round(time.monotonic() - active_started, 3)
    report["maximum_rss_bytes"] = max_rss
    report["finished_at"] = datetime.now(UTC).isoformat()
    if stop:
        report["status"] = "incomplete_budget_stop"
    elif len(report["recordings"]) == sum(
        item.get("disposition") == "included" for item in manifest["recordings"]
    ):
        report["status"] = "complete"
    else:
        report["status"] = "incomplete"
    totals: Counter[str] = Counter()
    for item in report["recordings"].values():
        totals.update(item.get("outcomes_by_status", {}))
    report["coverage"] = {
        "recordings_completed": sum(
            item.get("status") == "complete" for item in report["recordings"].values()
        ),
        "frozen_crop_cap": manifest["budgets"]["crop_cap"],
        "crop_inputs": sum(
            item.get("crop_input_item_count", 0) for item in report["recordings"].values()
        ),
        "output_outcomes": sum(
            item.get("output_outcome_count", 0) for item in report["recordings"].values()
        ),
        "outcomes_by_status": dict(sorted(totals.items())),
        "unprocessed": sum(
            item.get("unprocessed_count", 0) for item in report["recordings"].values()
        ),
    }
    timestamps = [
        datetime.fromisoformat(item["sampled_at"])
        for item in report["rss_samples"]
        if item.get("rss_bytes") is not None
    ]
    gaps = [
        (right - left).total_seconds()
        for left, right in zip(timestamps, timestamps[1:], strict=False)
    ]
    report["rss_sampling"] = {
        "requested_interval_seconds": manifest["budgets"]["rss_sample_interval_seconds"],
        "sample_count": len(timestamps),
        "maximum_observed_interval_seconds": None if not gaps else round(max(gaps), 3),
    }
    _atomic_write(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", default="http://127.0.0.1:8001")
    parser.add_argument("--backend-pid", type=int, required=True)
    arguments = parser.parse_args()
    report = run_batch(
        arguments.manifest, arguments.output, arguments.backend, arguments.backend_pid
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "recordings": len(report["recordings"]),
                "active_processing_seconds": report.get("active_processing_seconds"),
                "maximum_rss_bytes": report.get("maximum_rss_bytes"),
                "stop_reason": report.get("stop_reason"),
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
