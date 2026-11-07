#!/usr/bin/env python3
"""Run real-process Playwright UI cases against isolated local backend storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_FIXTURE = ROOT / "fixtures/repository-bundle/v1/both"
DEFAULT_SAMPLES = 10
STARTUP_SAMPLES = 10
RECORDING_ID = "recording-both"
IDENTITY_ITEMS = 24
SOURCE_PATHS = (
    "backend/scripts/interactive_ui_browser_app.py",
    "backend/scripts/run_interactive_ui_browser_performance.py",
    "web/playwright.interactive-performance.config.ts",
    "web/tests/e2e-performance/interactive-ui-real-process.spec.ts",
)


def _free_port() -> int:
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        return int(stream.getsockname()[1])


def _wait(url: str, timeout: float) -> tuple[int, bytes]:
    deadline = time.monotonic() + timeout
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            if error.code >= 500:
                raise RuntimeError(
                    f"{url} returned HTTP {error.code}: {error.read()[:300]!r}"
                ) from error
            last_error = error
            time.sleep(0.1)
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            last_error = error
            time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for {url}: {last_error}")


def _materialize_browser_fixture(root: Path) -> dict[str, Any]:
    """Build small valid pipeline and review data with the production services."""

    tests = ROOT / "backend/tests"
    sys.path.insert(0, str(tests))
    from app_factory import create_test_app
    from fastapi.testclient import TestClient
    from test_visible_card_pipeline_api import (
        RECORDING_ID as TEST_RECORDING_ID,
    )
    from test_visible_card_pipeline_api import (
        _Detector,
        _EventProvider,
        _FrameResolver,
        _install_recording,
        _run_event_job,
        _selected_node_input,
        _settings,
        _wait,
    )
    from test_visual_identity_pipeline_api import (
        _fixture_generated_visible_revision,
        _IdentityProvider,
        _wait_identity,
    )

    if TEST_RECORDING_ID != RECORDING_ID:
        raise RuntimeError(f"browser fixture identity changed: {TEST_RECORDING_ID}")
    _install_recording(root)
    intake = root / "data/intake/recordings"
    intake.mkdir(parents=True, exist_ok=True)
    shutil.move(root / "recordings" / RECORDING_ID, intake / RECORDING_ID)
    (root / "recordings").rmdir()
    settings = _settings(
        root,
        evidence_root=root / ".runtime",
        operations_root=root / "data/operations",
        repository_intake_root=intake,
        evidence_package_intake_root=root / "data/intake/evidence-packages",
        pending_video_root=root / "data/incoming/videos",
    )
    identity_provider = _IdentityProvider()
    app = create_test_app(
        settings,
        event_provider=_EventProvider(),
        visible_card_provider=_Detector(),
        visible_card_frame_resolver=_FrameResolver(),
        visible_card_identity_classifier=identity_provider,
    )

    def select_revision(content_type: str, revision_id: str) -> None:
        store = app.state.pipeline_selection_store
        current = store.get_exact(RECORDING_ID, content_type)
        reference = store.reference_for_processor_output(revision_id, RECORDING_ID, content_type)
        store.update_exact(
            RECORDING_ID,
            content_type,
            expected_revision=0 if current is None else current.revision,
            selected_generated=reference,
            selected_completed_reference=None,
        )

    with TestClient(app) as client:
        event_revision_id = _run_event_job(client, "m10-browser-seed-events")
        select_revision("events", event_revision_id)
        visible_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visible-cards",
            json={
                "run_id": "m10-browser-seed-visible-cards",
                **_selected_node_input(client, "events"),
            },
        )
        if visible_response.status_code != 202:
            raise RuntimeError(f"visible-card seed failed: {visible_response.text[:500]}")
        visible_run_id = visible_response.json()["run_id"]
        visible_result = _wait(client, visible_run_id)
        if visible_result.get("state", {}).get("status") != "complete":
            raise RuntimeError(f"visible-card seed did not complete: {visible_result}")
        visible_revision_id = visible_result["state"]["output_revision_ids"][0]
        visible_source = app.state.pipeline_selection_store.require_processor_revision(
            visible_revision_id
        )
        generated_revision_id = _fixture_generated_visible_revision(
            app,
            visible_source.manifest.source,
            visible_result["revisions"][0]["content"]["outcomes"][0]["frame_identity"],
            visible_run_id,
        )
        select_revision("visible_cards", generated_revision_id)

        input_selection = _selected_node_input(client, "visible_cards", generated_revision_id)
        identity_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "m10-browser-seed-identities",
                **input_selection,
            },
        )
        if identity_response.status_code != 202:
            raise RuntimeError(f"visual-identity seed failed: {identity_response.text[:500]}")
        identity_run_id = identity_response.json()["run_id"]
        identity_result = _wait_identity(client, identity_run_id)
        if identity_result.get("state", {}).get("status") != "complete":
            raise RuntimeError(f"visual-identity seed did not complete: {identity_result}")
        first_identity_revision_id = identity_result["state"]["output_revision_ids"][0]
        history_response = client.post(
            f"/api/recordings/{RECORDING_ID}/pipeline/visual-identities",
            json={
                "run_id": "m10-browser-seed-identities-history",
                **input_selection,
            },
        )
        if history_response.status_code != 202:
            raise RuntimeError(
                f"visual-identity history seed failed: {history_response.text[:500]}"
            )
        history_result = _wait_identity(client, history_response.json()["run_id"])
        if history_result.get("state", {}).get("status") != "complete":
            raise RuntimeError(f"visual-identity history seed did not complete: {history_result}")
        identity_revision_id = history_result["state"]["output_revision_ids"][0]
        if identity_revision_id == first_identity_revision_id:
            raise RuntimeError("visual-identity history seed did not create a new revision")
        select_revision("visual_identities", identity_revision_id)
        node_store = app.state.visual_identity_pipeline_service.node_store
        identity_node, identity_revision = node_store.find_revision(identity_revision_id)
        outcome_ids = [item["card_id"] for item in identity_revision.content["outcomes"]]

    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        entries.append(
            {
                "path": relative,
                "byte_length": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return {
        "profile": "generated_valid_browser_workflow",
        "recording_id": RECORDING_ID,
        "source_fixture": (
            "fixtures/repository-bundle/v1/both; valid 64x64 local video encoded with ffmpeg"
        ),
        "pipeline_nodes": [identity_node.node_id],
        "visible_card_revision_id": generated_revision_id,
        "identity_revision_id": identity_revision_id,
        "identity_history_revision_id": first_identity_revision_id,
        "review_item_ids": outcome_ids,
        "identity_item_count": len(outcome_ids),
        "files": entries,
        "file_count": len(entries),
        "byte_count": sum(entry["byte_length"] for entry in entries),
        "manifest_sha256": hashlib.sha256(
            json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "pipeline_seed": (
            "production FastAPI services and durable stores with deterministic local providers"
        ),
    }


def _terminate(process: subprocess.Popen[bytes], timeout: float = 10.0) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    if process.poll() is None:
        raise RuntimeError("benchmark process survived process-group cleanup")


def _distributions(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        groups.setdefault(str(sample["scenario"]), []).append(sample)
    summaries = []
    for scenario, rows in sorted(groups.items()):
        timings = sorted(float(row["action_ms"]) for row in rows)
        p90_index = max(0, int(0.9 * len(timings) + 0.999999) - 1)
        summaries.append(
            {
                "scenario": scenario,
                "samples": len(rows),
                "min_action_ms": timings[0],
                "median_action_ms": statistics.median(timings),
                "p90_action_ms": timings[p90_index],
                "max_action_ms": timings[-1],
                "request_count_distribution": sorted(int(row["request_count"]) for row in rows),
                "api_request_count_distribution": sorted(
                    int(row["api_request_count"]) for row in rows
                ),
                "duplicate_request_sample_count": sum(
                    bool(row["duplicate_requests"]) for row in rows
                ),
                "range_request_sample_count": sum(int(row["range_requests"]) > 0 for row in rows),
                "browser_cache_event_sample_count": sum(
                    bool(row["browser_cache_events"]) for row in rows
                ),
                "error_sample_count": sum(bool(row["errors"]) for row in rows),
            }
        )
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contexts", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--job-delay-ms", type=int, default=1_500)
    parser.add_argument("--grep", help="run only Playwright tests matching this expression")
    args = parser.parse_args()
    if args.contexts < 10 or args.timeout <= 0 or args.job_delay_ms < 0:
        parser.error("contexts must be at least 10 and timeout must be positive")
    if not shutil.which("npm"):
        raise RuntimeError("npm is not available; run through the declared mise toolchain")

    output = args.output.expanduser().resolve()
    artifact_root = output.with_suffix(".artifacts")
    artifact_root.mkdir(parents=True, exist_ok=True)
    samples_path = artifact_root / "browser-samples.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="doko-ui-browser-perf-") as temporary:
        root = (Path(temporary) / "repository").resolve()
        root.mkdir()
        fixture = _materialize_browser_fixture(root)
        backend_port, web_port = _free_port(), _free_port()
        api_url = f"http://127.0.0.1:{backend_port}"
        web_url = f"http://127.0.0.1:{web_port}"
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONPATH": os.pathsep.join(
                    [
                        str(ROOT / "backend/scripts"),
                        str(ROOT / "backend/tests"),
                        environment.get("PYTHONPATH", ""),
                    ]
                ),
                "REPOSITORY_ROOT": str(root),
                "EVIDENCE_ROOT": str(root / ".runtime"),
                "OPERATIONS_ROOT": str(root / "data/operations"),
                "REPOSITORY_INTAKE_ROOT": str(root / "data/intake/recordings"),
                "EVIDENCE_PACKAGE_INTAKE_ROOT": str(root / "data/intake/evidence-packages"),
                "PENDING_VIDEO_ROOT": str(root / "data/incoming/videos"),
                "SERVER_HOST": "127.0.0.1",
                "SERVER_PORT": str(backend_port),
                "BONJOUR_ENABLED": "false",
                "UI_PERF_JOB_DELAY_MS": str(args.job_delay_ms),
            }
        )
        backend_log = artifact_root / "backend.log"
        web_log = artifact_root / "web.log"
        backend: subprocess.Popen[bytes] | None = None
        web: subprocess.Popen[bytes] | None = None
        playwright_result: subprocess.CompletedProcess[bytes] | None = None
        backend_startup_samples_ns: list[int] = []
        with backend_log.open("wb") as backend_output, web_log.open("wb") as web_output:
            try:
                for trial in range(STARTUP_SAMPLES):
                    backend_started = time.perf_counter_ns()
                    backend = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "interactive_ui_browser_app:create_app",
                            "--factory",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(backend_port),
                        ],
                        cwd=ROOT,
                        env=environment,
                        stdout=backend_output,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    status, _ = _wait(f"{api_url}/health/live", args.timeout)
                    if status != 200:
                        raise RuntimeError(f"backend liveness probe returned HTTP {status}")
                    ready_status, _ = _wait(f"{api_url}/health/ready", args.timeout)
                    if ready_status != 200:
                        raise RuntimeError(f"backend readiness probe returned HTTP {ready_status}")
                    recordings_status, recordings_body = _wait(
                        f"{api_url}/v1/recordings", args.timeout
                    )
                    if recordings_status != 200:
                        raise RuntimeError(
                            f"backend recordings probe returned HTTP {recordings_status}"
                        )
                    recordings = json.loads(recordings_body)["recordings"]
                    if not any(row["recording_id"] == RECORDING_ID for row in recordings):
                        raise RuntimeError(
                            "the exact generated fixture is missing from the live catalog"
                        )
                    workspace_status, workspace = _wait(
                        f"{api_url}/api/recordings/{RECORDING_ID}/pipeline?stage=visual_identities",
                        args.timeout,
                    )
                    if (
                        workspace_status != 200
                        or json.loads(workspace).get("video", {}).get("recording_id")
                        != RECORDING_ID
                    ):
                        raise RuntimeError("the live workspace identity does not match the fixture")
                    backend_startup_samples_ns.append(time.perf_counter_ns() - backend_started)
                    if trial < STARTUP_SAMPLES - 1:
                        _terminate(backend)
                        backend = None

                backend_startup_sorted = sorted(backend_startup_samples_ns)
                backend_startup_p90 = backend_startup_sorted[
                    max(0, int(0.9 * STARTUP_SAMPLES + 0.999999) - 1)
                ]

                web_started = time.perf_counter_ns()
                web_environment = environment.copy()
                web_environment.update({"VITE_API_PROXY_TARGET": api_url})
                web = subprocess.Popen(
                    [
                        "npm",
                        "run",
                        "dev",
                        "--",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(web_port),
                        "--strictPort",
                    ],
                    cwd=ROOT / "web",
                    env=web_environment,
                    stdout=web_output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                web_status, _ = _wait(web_url, args.timeout)
                if web_status != 200:
                    raise RuntimeError(f"web startup probe returned HTTP {web_status}")
                web_startup_ns = time.perf_counter_ns() - web_started
                browser_environment = web_environment.copy()
                browser_environment.update(
                    {
                        "UI_PERF_API_URL": api_url,
                        "UI_PERF_WEB_URL": web_url,
                        "UI_PERF_CONTEXTS": str(args.contexts),
                        "UI_PERF_SAMPLE_OUTPUT": str(samples_path),
                    }
                )
                playwright_command = [
                    "npx",
                    "playwright",
                    "test",
                    "--config=playwright.interactive-performance.config.ts",
                ]
                if args.grep:
                    playwright_command.extend(["--grep", args.grep])
                playwright_result = subprocess.run(
                    playwright_command,
                    cwd=ROOT / "web",
                    env=browser_environment,
                    capture_output=True,
                    text=True,
                    timeout=args.timeout * 10,
                    check=False,
                )
            finally:
                if web is not None:
                    _terminate(web)
                _terminate(backend)

        browser_data = (
            json.loads(samples_path.read_text(encoding="utf-8"))
            if samples_path.is_file()
            else {"samples": []}
        )
        samples = browser_data.get("samples", [])
        source_files = [
            {
                "path": relative,
                "sha256": hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
            }
            for relative in SOURCE_PATHS
        ]
        result = {
            "schema_version": "interactive-ui-browser-performance/v1",
            "kind": "preliminary_real_process_browser_and_controlled_load_samples",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "metadata": {
                "commit": subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
                "commit_note": (
                    "HEAD at the run start; exact uncommitted M10 source files are hashed below"
                ),
                "source_files": source_files,
                "source_snapshot_sha256": hashlib.sha256(
                    json.dumps(source_files, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "platform": platform.platform(),
                "python": sys.version.split()[0],
                "node": subprocess.run(
                    ["node", "--version"],
                    cwd=ROOT / "web",
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
                "fixture": fixture,
                "backend": (
                    "Real Uvicorn process and production FastAPI app with explicit local "
                    "analyzer, frame resolver, and deterministic event provider"
                ),
                "web": "Real Vite development server; same-origin API proxy to isolated backend",
                "browser_cache": (
                    "Enabled Chromium cache in each fresh context; server derived-media cache "
                    "persists across contexts in the backend process"
                ),
                "load": {
                    "poll_period_ms": 100,
                    "background_job_delay_ms": args.job_delay_ms,
                    "contexts_per_scenario": args.contexts,
                    "timeout_seconds": args.timeout,
                },
                "startup_ns": {
                    "backend_to_recordings_and_workspace_samples": backend_startup_samples_ns,
                    "backend_to_recordings_and_workspace_median": statistics.median(
                        backend_startup_samples_ns
                    ),
                    "backend_to_recordings_and_workspace_p90": backend_startup_p90,
                    "web_to_http_200": web_startup_ns,
                },
                "process_cleanup": (
                    "SIGTERM then SIGKILL after finite wait; both process groups exited"
                ),
            },
            "samples": samples,
            "distributions": _distributions(samples),
            "playwright": {
                "exit_code": playwright_result.returncode if playwright_result else None,
                "stdout": playwright_result.stdout if playwright_result else "",
                "stderr": playwright_result.stderr if playwright_result else "",
                "samples_artifact": str(samples_path),
                "backend_log": str(backend_log),
                "web_log": str(web_log),
            },
        }
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        expected = {
            "recordings_to_workspace",
            "displayed_revision_switch",
            "frame_crop_navigation",
            "review_save",
            "jobs_drawer_history",
            "job_submission_visible_status",
            "controlled_load",
        }
        counts: dict[str, int] = {}
        for sample in samples:
            counts[sample["scenario"]] = counts.get(sample["scenario"], 0) + 1
        missing = (
            []
            if args.grep
            else sorted(name for name in expected if counts.get(name, 0) < args.contexts)
        )
        if playwright_result is None or playwright_result.returncode != 0 or missing:
            print(playwright_result.stdout if playwright_result else "Playwright did not start")
            print(playwright_result.stderr if playwright_result else "")
            print(f"missing or incomplete scenario samples: {missing}; retained {counts}")
            print(f"wrote failure evidence: {output}")
            return 1
        print(f"PASS: retained {len(samples)} samples across {len(counts)} scenarios at {output}")
        print(playwright_result.stdout)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
