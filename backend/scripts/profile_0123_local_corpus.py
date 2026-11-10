#!/usr/bin/env python3
"""Measure the production recording list on an existing local recording corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ROOT_METADATA = ("manifest.json", "source-record.json", "initial-task-enrollment.json")


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
                raise RuntimeError(f"{url} returned HTTP {error.code}") from error
            last_error = error
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            last_error = error
        time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for {url}: {last_error}")


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


def _corpus_snapshot(recording_root: Path, selection_root: Path) -> dict[str, Any]:
    entries: list[tuple[str, str, int]] = []
    recordings = sorted(
        path
        for path in recording_root.iterdir()
        if path.is_dir() and not path.is_symlink() and not path.name.startswith(".")
    )
    for bundle in recordings:
        for name in ROOT_METADATA:
            path = bundle / name
            if not path.is_file() or path.is_symlink():
                continue
            raw = path.read_bytes()
            entries.append((f"{bundle.name}/{name}", hashlib.sha256(raw).hexdigest(), len(raw)))
    for path in sorted(selection_root.glob("*/*.json")):
        if not path.is_file() or path.is_symlink():
            continue
        raw = path.read_bytes()
        entries.append(
            (
                f"selections/{path.parent.name}/{path.name}",
                hashlib.sha256(raw).hexdigest(),
                len(raw),
            )
        )
    canonical = json.dumps(entries, separators=(",", ":"), sort_keys=True).encode()
    return {
        "recording_count": len(recordings),
        "files": len(entries),
        "bytes": sum(entry[2] for entry in entries),
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "digest_method": "SHA256 of compact JSON tuples (relative path, file SHA256, byte length)",
    }


def _freeze_corpus(
    recording_root: Path, selection_root: Path, destination: Path
) -> tuple[Path, Path, dict[str, Any]]:
    source_snapshot = _corpus_snapshot(recording_root, selection_root)
    frozen_recordings = destination / "recordings"
    frozen_selections = destination / "selections"
    frozen_recordings.mkdir(parents=True)
    frozen_selections.mkdir(parents=True)
    for bundle in sorted(
        path
        for path in recording_root.iterdir()
        if path.is_dir() and not path.is_symlink() and not path.name.startswith(".")
    ):
        target_bundle = frozen_recordings / bundle.name
        target_bundle.mkdir()
        for name in ROOT_METADATA:
            source = bundle / name
            if source.is_file() and not source.is_symlink():
                shutil.copyfile(source, target_bundle / name)
    for source in sorted(selection_root.glob("*/*.json")):
        if source.is_file() and not source.is_symlink():
            target = frozen_selections / source.parent.name / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    source_after_copy = _corpus_snapshot(recording_root, selection_root)
    frozen_snapshot = _corpus_snapshot(frozen_recordings, frozen_selections)
    if source_snapshot != source_after_copy or source_snapshot != frozen_snapshot:
        raise RuntimeError("recording metadata changed while the frozen corpus was copied")
    return frozen_recordings, frozen_selections, frozen_snapshot


def _copy_selections(selection_root: Path, operations_root: Path) -> None:
    destination = operations_root / "pipeline-nodes" / ".pipeline-node-selections"
    if selection_root.is_dir():
        shutil.copytree(selection_root, destination, copy_function=os.link)


def _run_session(
    *,
    recording_root: Path,
    selection_root: Path,
    expected_recordings: int,
    fresh_processes: int,
    warm_requests: int,
    browser_contexts: int,
    timeout: float,
    artifact_root: Path,
    corpus_sha256: str,
) -> dict[str, Any]:
    fresh_samples_ns: list[int] = []
    warm_samples_ns: list[int] = []
    response_sizes: list[int] = []
    selected_indicators: int | None = None
    session_root = Path(tempfile.mkdtemp(prefix=".0123-list-profile-", dir=ROOT)).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    backend_port, web_port = _free_port(), _free_port()
    api_url = f"http://127.0.0.1:{backend_port}"
    web_url = f"http://127.0.0.1:{web_port}"
    operations_root = session_root / "data/operations"
    _copy_selections(selection_root, operations_root)
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
            "REPOSITORY_ROOT": str(ROOT),
            "EVIDENCE_ROOT": str(session_root / ".runtime"),
            "OPERATIONS_ROOT": str(operations_root),
            "REPOSITORY_INTAKE_ROOT": str(recording_root),
            "EVIDENCE_PACKAGE_INTAKE_ROOT": str(session_root / "data/intake/evidence-packages"),
            "PENDING_VIDEO_ROOT": str(session_root / "data/incoming/videos"),
            "SERVER_HOST": "127.0.0.1",
            "SERVER_PORT": str(backend_port),
            "BONJOUR_ENABLED": "false",
        }
    )
    backend_log_path = artifact_root / "backend.log"
    web_log_path = artifact_root / "web.log"
    backend_log = backend_log_path.open("wb")
    web_log = web_log_path.open("wb")
    backend: subprocess.Popen[bytes] | None = None
    web: subprocess.Popen[bytes] | None = None

    def start_backend() -> subprocess.Popen[bytes]:
        return subprocess.Popen(
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
            stdout=backend_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def wait_ready() -> None:
        status, _ = _wait(f"{api_url}/health/ready", timeout)
        if status != 200:
            raise RuntimeError(f"backend readiness returned HTTP {status}")

    try:
        for _ in range(fresh_processes):
            backend = start_backend()
            wait_ready()
            started = time.perf_counter_ns()
            status, body = _wait(f"{api_url}/v1/recordings", timeout)
            fresh_samples_ns.append(time.perf_counter_ns() - started)
            if status != 200:
                raise RuntimeError(f"recordings list returned HTTP {status}")
            payload = json.loads(body)
            rows = payload["recordings"]
            if len(rows) != expected_recordings:
                raise RuntimeError(
                    f"fresh-process list returned {len(rows)} rows; expected {expected_recordings}"
                )
            current_selected = sum(
                selection["state"] == "selected" for row in rows for selection in row["selections"]
            )
            if selected_indicators is None:
                selected_indicators = current_selected
            elif current_selected != selected_indicators:
                raise RuntimeError("selected indicator count changed between API processes")
            response_sizes.append(len(body))
            _terminate(backend)
            backend = None

        backend = start_backend()
        wait_ready()
        for _ in range(warm_requests):
            started = time.perf_counter_ns()
            status, body = _wait(f"{api_url}/v1/recordings", timeout)
            warm_samples_ns.append(time.perf_counter_ns() - started)
            if status != 200 or len(json.loads(body)["recordings"]) != expected_recordings:
                raise RuntimeError("warm recordings list did not return the expected corpus")
            response_sizes.append(len(body))

        web_environment = environment.copy()
        web_environment.update(
            {
                "VITE_API_PROXY_TARGET": api_url,
                "UI_PERF_API_URL": api_url,
                "UI_PERF_WEB_URL": web_url,
                "UI_PERF_CONTEXTS": str(browser_contexts),
                "UI_PERF_EXPECTED_RECORDINGS": str(expected_recordings),
                "UI_PERF_SAMPLE_OUTPUT": str(artifact_root / "browser-samples.json"),
            }
        )
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
            stdout=web_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        status, _ = _wait(web_url, timeout)
        if status != 200:
            raise RuntimeError(f"web server returned HTTP {status}")
        command = [
            "npx",
            "playwright",
            "test",
            "--config=playwright.interactive-performance.config.ts",
            "--grep",
            "recordings list renders all expected rows",
        ]
        result = subprocess.run(
            command,
            cwd=ROOT / "web",
            env=web_environment,
            capture_output=True,
            text=True,
            timeout=timeout * 10,
            check=False,
        )
        (artifact_root / "playwright.stdout.txt").write_text(result.stdout)
        (artifact_root / "playwright.stderr.txt").write_text(result.stderr)
        if result.returncode:
            raise RuntimeError(f"Playwright failed: {result.stdout}\n{result.stderr}")
        samples = json.loads((artifact_root / "browser-samples.json").read_text())["samples"]
        if len(samples) != browser_contexts or any(
            sample["scenario"] != "recordings_list_visible" for sample in samples
        ):
            raise RuntimeError("browser sample count or scenario does not match the list profile")
        if any(sample["errors"] for sample in samples):
            raise RuntimeError("browser list profile recorded request errors")
        list_request_counts = []
        recording_detail_request_counts = []
        for sample in samples:
            api_paths = [
                request["path"].split("?", maxsplit=1)[0]
                for request in sample["requests"]
                if request["path"].startswith(("/api/", "/v1/"))
            ]
            list_request_counts.append(api_paths.count("/v1/recordings"))
            recording_detail_request_counts.append(
                sum(path.startswith("/v1/recordings/") for path in api_paths)
            )
        if any(count != 1 for count in list_request_counts):
            raise RuntimeError("browser did not make exactly one recording list request per page")
        if any(recording_detail_request_counts):
            raise RuntimeError("browser made per-recording detail requests from the list page")
        browser_ms = [float(sample["action_ms"]) for sample in samples]
        if len(set(response_sizes)) != 1:
            raise RuntimeError("list response size changed during a profile session")
        return {
            "corpus_sha256": corpus_sha256,
            "fresh_process_samples_ns": fresh_samples_ns,
            "fresh_process_median_ns": statistics.median(fresh_samples_ns),
            "warm_samples_ns": warm_samples_ns,
            "warm_median_ns": statistics.median(warm_samples_ns),
            "browser_samples_ms": browser_ms,
            "browser_median_ms": statistics.median(browser_ms),
            "browser_max_ms": max(browser_ms),
            "browser_api_request_counts": [sample["api_request_count"] for sample in samples],
            "browser_list_request_counts": list_request_counts,
            "browser_recording_detail_request_counts": recording_detail_request_counts,
            "response_bytes": response_sizes[0],
            "selected_indicators": selected_indicators,
            "browser_samples_artifact": str(artifact_root / "browser-samples.json"),
        }
    finally:
        if web is not None:
            _terminate(web)
        if backend is not None:
            _terminate(backend)
        backend_log.close()
        web_log.close()
        shutil.rmtree(session_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recordings-root", type=Path, required=True)
    parser.add_argument("--selection-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sessions", type=int, default=3)
    parser.add_argument("--fresh-processes", type=int, default=10)
    parser.add_argument("--warm-requests", type=int, default=30)
    parser.add_argument("--browser-contexts", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    if min(args.sessions, args.fresh_processes, args.warm_requests, args.browser_contexts) <= 0:
        parser.error("sample counts must be positive")
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    recording_root = args.recordings_root.expanduser().resolve()
    selection_root = args.selection_root.expanduser().resolve()
    if not recording_root.is_dir():
        parser.error(f"recordings root does not exist: {recording_root}")
    corpus = _corpus_snapshot(recording_root, selection_root)
    if corpus["recording_count"] == 0:
        parser.error("recordings root has no accepted recording directories")
    output = args.output.expanduser().resolve()
    artifact_root = output.with_suffix(".artifacts")
    artifact_root.mkdir(parents=True, exist_ok=True)
    sessions = []
    with tempfile.TemporaryDirectory(prefix=".0123-frozen-corpus-", dir=ROOT) as temp:
        frozen_recordings, frozen_selections, frozen_corpus = _freeze_corpus(
            recording_root, selection_root, Path(temp)
        )
        corpus = frozen_corpus
        for index in range(args.sessions):
            if _corpus_snapshot(frozen_recordings, frozen_selections) != corpus:
                raise RuntimeError("frozen corpus changed between qualification sessions")
            sessions.append(
                _run_session(
                    recording_root=frozen_recordings,
                    selection_root=frozen_selections,
                    expected_recordings=corpus["recording_count"],
                    fresh_processes=args.fresh_processes,
                    warm_requests=args.warm_requests,
                    browser_contexts=args.browser_contexts,
                    timeout=args.timeout,
                    artifact_root=artifact_root / f"session-{index + 1:02d}",
                    corpus_sha256=corpus["sha256"],
                )
            )
        if _corpus_snapshot(frozen_recordings, frozen_selections) != corpus:
            raise RuntimeError("frozen corpus changed during qualification")
    if any(session["corpus_sha256"] != corpus["sha256"] for session in sessions):
        raise RuntimeError("qualification sessions did not use one frozen corpus")
    result = {
        "schema_version": "0123-local-recording-list-profile/v1",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reader_source_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "recordings_root": str(recording_root),
        "corpus": corpus,
        "measurement": {
            "sessions": args.sessions,
            "fresh_processes_per_session": args.fresh_processes,
            "warm_requests_per_session": args.warm_requests,
            "browser_contexts_per_session": args.browser_contexts,
            "browser_end_condition": "all expected recording rows are visible in the document",
            "thumbnail_requests": "fulfilled with HTTP 204 to measure list rendering separately",
        },
        "sessions_result": sessions,
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"PASS: wrote local recording list profile to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
