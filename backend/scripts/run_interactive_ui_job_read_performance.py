#!/usr/bin/env python3
"""Retain preliminary timing and correctness samples for interactive job reads."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
UNKNOWN_ID = "22222222-2222-5222-8222-222222222222"


def _settings(root: Path) -> Any:
    from dokodetector_backend.config import Settings

    return Settings(
        _env_file=None,
        repository_root=ROOT,
        evidence_root=root / "runtime",
        operations_root=root / "data/operations",
        frontend_dist=root / "frontend",
        repository_intake_root=root / "recordings",
        evidence_package_intake_root=root / "packages",
        pending_video_root=root / "pending",
    )


def _record(sample: dict[str, Any], client: TestClient, path: str, expected: int) -> dict[str, Any]:
    started = time.perf_counter_ns()
    response = client.get(path)
    body = response.content
    error = (
        None
        if response.status_code == expected
        else f"expected {expected}, got {response.status_code}"
    )
    try:
        payload = response.json()
    except ValueError:
        payload = None
        error = error or "response was not JSON"
    sample.update(
        {
            "path": path,
            "duration_ns": time.perf_counter_ns() - started,
            "status_code": response.status_code,
            "response_bytes": len(body),
            "response_sha256": hashlib.sha256(body).hexdigest(),
            "ok": error is None,
            "error": error,
        }
    )
    return payload if isinstance(payload, dict) else {}


def run() -> dict[str, Any]:
    from run_interactive_ui_read_performance import _seed_jobs

    from dokodetector_backend.app import create_app
    from dokodetector_backend.poc_analyzer import create_local_poc_analyzer

    expected_ids = [
        str(uuid5(NAMESPACE_URL, f"doko-ui-perf-m3-target-{index}")) for index in reversed(range(6))
    ]
    samples: list[dict[str, Any]] = []
    page_checks = []
    with tempfile.TemporaryDirectory(prefix="doko-ui-m6-jobs-") as temporary:
        root = Path(temporary).resolve()
        for size in (12, 300):
            case_root = root / str(size)
            case_root.mkdir()
            target_id = _seed_jobs(case_root, size)
            app = create_app(_settings(case_root), analyzer=create_local_poc_analyzer())
            with TestClient(app) as client:
                first_sample: dict[str, Any] = {"case": f"history_page_{size}"}
                first = _record(
                    first_sample,
                    client,
                    "/api/jobs?scope=history&recording_id=cardeventnet-IMG_0650&limit=3",
                    200,
                )
                samples.append(first_sample)
                first_ids = [item["id"] for item in first.get("items", [])]
                cursor = first.get("next_cursor")
                second_sample: dict[str, Any] = {"case": f"history_cursor_page_{size}"}
                second = (
                    _record(
                        second_sample,
                        client,
                        "/api/jobs?scope=history&recording_id=cardeventnet-IMG_0650&limit=3&cursor="
                        + str(cursor),
                        200,
                    )
                    if cursor
                    else {}
                )
                samples.append(second_sample)
                second_ids = [item["id"] for item in second.get("items", [])]
                page_checks.append(
                    {
                        "history_size": size,
                        "target_job_id": target_id,
                        "page_ids": first_ids + second_ids,
                        "expected_ids": expected_ids,
                        "cursor_terminated": second.get("next_cursor") is None,
                        "pass": first_ids + second_ids == expected_ids
                        and not (set(first_ids) & set(second_ids))
                        and second.get("next_cursor") is None,
                    }
                )

                for name, path, expected in (
                    ("job_detail", f"/api/jobs/{target_id}", 200),
                    ("job_detail_missing", f"/api/jobs/{UNKNOWN_ID}", 404),
                    (
                        "calibration_preview_wrong_type",
                        f"/api/jobs/{target_id}/calibration-preview",
                        409,
                    ),
                    ("job_logs_first_page", f"/api/jobs/{target_id}/logs?after=0&limit=10", 200),
                    ("job_logs_missing", f"/api/jobs/{UNKNOWN_ID}/logs", 404),
                ):
                    sample = {"case": name, "history_size": size}
                    payload = _record(sample, client, path, expected)
                    if name == "job_detail" and payload.get("id") != target_id:
                        sample.update(ok=False, error="detail job identity mismatch")
                    if (
                        name in {"job_detail_missing", "job_logs_missing"}
                        and payload.get("error", {}).get("code") != "job_not_found"
                    ):
                        sample.update(ok=False, error="expected job_not_found")
                    if (
                        name == "calibration_preview_wrong_type"
                        and payload.get("error", {}).get("code")
                        != "calibration_preview_unavailable"
                    ):
                        sample.update(ok=False, error="expected calibration_preview_unavailable")
                    samples.append(sample)
        calibration_root = root / "calibration-preview"
        calibration_root.mkdir()
        calibration_app = create_app(
            _settings(calibration_root), analyzer=create_local_poc_analyzer()
        )
        with TestClient(calibration_app) as client:
            preview_id = _seed_calibration_preview(calibration_app)
            sample = {"case": "calibration_preview_success"}
            payload = _record(sample, client, f"/api/jobs/{preview_id}/calibration-preview", 200)
            if (
                payload.get("recording_id") != "m6-calibration-preview"
                or payload.get("preview_complete") is not True
            ):
                sample.update(ok=False, error="calibration preview identity mismatch")
            samples.append(sample)
    return {
        "schema_version": "0114-m6-job-read-samples/v1",
        "measurement": "one synchronous ASGI HTTP response per named read; preliminary only",
        "unrelated_history_sizes": [12, 300],
        "samples": samples,
        "pagination_checks": page_checks,
        "all_pass": all(item["ok"] for item in samples)
        and all(item["pass"] for item in page_checks),
    }


def _seed_calibration_preview(app: Any) -> str:
    from doko_operations.card_plane_geometry import TablePlaneCalibration
    from table_evidence_analyzer.card_scene_contract import CalibrationDraft

    calibration = TablePlaneCalibration.create(
        calibration_revision_id="m6-calibration",
        recording_id="m6-calibration-preview",
        source_revision="m6-proposal",
        frame_width=100,
        frame_height=100,
        image_to_table=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        table_to_image=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        card_short_size=1,
        card_long_size=91 / 59,
        candidate_receipt_digests=[],
        diagnostics={},
    )
    draft = CalibrationDraft.create(
        draft_id="m6-draft",
        recording_id="m6-calibration-preview",
        detector_revision_id="m6-proposal",
        detector_revision_digest="a" * 64,
        base_calibration_revision_id="m6-calibration",
        base_calibration_digest=calibration.calibration_digest,
        source_frame_digests={},
        anchors=[],
        commands=[],
    )
    snapshot = {
        "proposal_revision_id": "m6-proposal",
        "proposal_digest": "b" * 64,
        "draft": draft.to_mapping(),
        "calibration": calibration.to_mapping(),
        "frame_scenes": [],
    }
    app.state.calculation_jobs._snapshot = lambda _recording, _body: snapshot
    job = app.state.job_manager_service.run_inline(
        "550e8400-e29b-41d4-a716-446655440090",
        {
            "type": "calibration_preview",
            "context": {"recording_id": "m6-calibration-preview"},
            "request": {"draft_id": "m6-draft", "proposal_revision_id": "m6-proposal"},
        },
    )
    if job.state != "succeeded":
        raise RuntimeError(f"calibration preview fixture did not succeed: {job.failure}")
    return job.id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    result = run()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"{'PASS' if result['all_pass'] else 'FAIL'}: {len(result['samples'])} job-read samples")
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
