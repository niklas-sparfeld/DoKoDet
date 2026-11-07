#!/usr/bin/env python3
"""Run bounded local HTTP and isolated backend startup measurements."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SCRIPT = ROOT / "backend/scripts/materialize_interactive_ui_performance_fixtures.py"
FIXTURE_MANIFEST = ROOT / "backend/fixtures/interactive-ui-performance/v1/manifest.json"
MAX_MEDIA_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_WARMUPS = 1
DEFAULT_REPEATS = 5


@dataclass(frozen=True)
class Sample:
    case: str
    duration_ns: int
    status_code: int
    response_bytes: int
    response_sha256: str
    ok: bool
    error: str | None = None
    iteration: int = 0


def machine_metadata() -> dict[str, Any]:
    """Return profile fields needed to reject incomparable measurements."""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }


def fixture_metadata(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {"profile": "empty", "manifest_sha256": None}
    path = root / "fixture-manifest.json"
    if not path.is_file():
        return {"profile": "unknown", "manifest_sha256": None}
    manifest = json.loads(path.read_text())
    return {
        "profile": manifest.get("profile"),
        "seed": manifest.get("seed"),
        "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def startup_fixture_metadata(profile: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"profile": profile}
    if profile == "hard_populated":
        metadata["source_manifest_sha256"] = hashlib.sha256(
            FIXTURE_MANIFEST.read_bytes()
        ).hexdigest()
    elif profile == "interrupted_recovery":
        metadata["seed"] = 11401
    return metadata


def validate_sample(sample: dict[str, Any]) -> str | None:
    if sample.get("ok") is not True:
        return str(sample.get("error") or "sample failed")
    status = sample.get("status_code")
    if not isinstance(status, int) or not 200 <= status < 300:
        return f"invalid HTTP response status: {status!r}"
    length = sample.get("response_bytes")
    if not isinstance(length, int) or length < 0:
        return f"invalid response byte count: {length!r}"
    digest = sample.get("response_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        return "invalid response SHA-256"
    return None


def compare_results(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Compare compatible result documents; this is advisory until M6 enables a gate."""
    errors: list[str] = []
    for key in ("fixture", "machine"):
        if baseline.get("metadata", {}).get(key) != candidate.get("metadata", {}).get(key):
            errors.append(f"incompatible {key} profile")
    base_samples = baseline.get("samples")
    next_samples = candidate.get("samples")
    if not isinstance(base_samples, list) or not isinstance(next_samples, list):
        return [*errors, "missing sample list"]
    by_case: dict[str, list[dict[str, Any]]] = {}
    for sample in base_samples:
        if not isinstance(sample, dict) or validate_sample(sample):
            errors.append("baseline contains invalid response sample")
            continue
        by_case.setdefault(str(sample["case"]), []).append(sample)
    for sample in next_samples:
        if not isinstance(sample, dict):
            errors.append("candidate contains malformed sample")
            continue
        invalid = validate_sample(sample)
        if invalid:
            errors.append(f"{sample.get('case', 'unknown')}: {invalid}")
            continue
        peers = by_case.get(str(sample["case"]), [])
        if peers:
            reference = sorted(item["duration_ns"] for item in peers)[len(peers) // 2]
            if sample["duration_ns"] > reference * 1.2:
                errors.append(f"{sample['case']}: slowdown exceeds 20% advisory tolerance")
    return errors


def _http_sample(client: httpx.Client, case: str, url: str, timeout: float) -> Sample:
    start = time.perf_counter_ns()
    try:
        response = client.get(url, timeout=timeout)
        duration = time.perf_counter_ns() - start
        body = response.content
        ok = 200 <= response.status_code < 300
        return Sample(
            case,
            duration,
            response.status_code,
            len(body),
            hashlib.sha256(body).hexdigest(),
            ok,
            None if ok else f"HTTP {response.status_code}",
        )
    except (httpx.HTTPError, TimeoutError, OSError) as error:
        return Sample(
            case,
            time.perf_counter_ns() - start,
            0,
            0,
            hashlib.sha256(b"").hexdigest(),
            False,
            str(error),
        )


async def _async_http_sample(
    client: httpx.AsyncClient,
    case: str,
    url: str,
    timeout: float,
    *,
    headers: dict[str, str] | None = None,
) -> Sample:
    start = time.perf_counter_ns()
    try:
        response = await asyncio.wait_for(client.get(url, headers=headers), timeout=timeout)
        body = response.content
        ok = 200 <= response.status_code < 300
        return Sample(
            case,
            time.perf_counter_ns() - start,
            response.status_code,
            len(body),
            hashlib.sha256(body).hexdigest(),
            ok,
            None if ok else f"HTTP {response.status_code}",
        )
    except (httpx.HTTPError, TimeoutError, OSError) as error:
        return Sample(
            case,
            time.perf_counter_ns() - start,
            0,
            0,
            hashlib.sha256(b"").hexdigest(),
            False,
            str(error),
        )


def run_controlled_http(
    *,
    repeats: int = DEFAULT_REPEATS,
    warmups: int = DEFAULT_WARMUPS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    hard_cache: Path | None = None,
) -> dict[str, Any]:
    """Measure a real API read and bounded media response against an isolated app."""
    from dokodetector_backend.app import create_app
    from dokodetector_backend.config import Settings

    with tempfile.TemporaryDirectory(prefix="doko-ui-perf-http-") as temporary:
        sandbox = Path(temporary)
        fixture_root = sandbox / "repository"
        fixture_root.mkdir()
        if hard_cache is not None:
            sys.path.insert(0, str(FIXTURE_SCRIPT.parent))
            import materialize_interactive_ui_performance_fixtures as fixtures

            fixtures.validate_hard_snapshot(hard_cache)
            source_manifest = json.loads(FIXTURE_MANIFEST.read_text())
            for asset in source_manifest["assets"]:
                source = hard_cache / "sha256" / asset["sha256"]
                target = fixture_root / asset["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                os.link(source, target)
            recording_id = source_manifest["examples"][0]["recording_id"]
        else:
            recording_id = ""
        settings = Settings(
            repository_root=fixture_root,
            evidence_root=sandbox / ".runtime",
            operations_root=sandbox / "data/operations",
            repository_intake_root=fixture_root / "data/intake/recordings",
            evidence_package_intake_root=fixture_root / "data/intake/evidence-packages",
            pending_video_root=fixture_root / "data/incoming/videos",
            bonjour_enabled=False,
        )
        app = create_app(settings)
        samples: list[Sample] = []

        async def measure() -> None:
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://controlled.local", timeout=timeout
                ) as client:
                    media_url = (
                        f"/v1/repository-bundles/{recording_id}/video" if recording_id else None
                    )
                    for index in range(warmups + repeats):
                        # Warmups prime app caches; timed samples reuse the same app instance.
                        sample = await _async_http_sample(client, "jobs_json", "/api/jobs", timeout)
                        if index >= warmups:
                            samples.append(
                                Sample(**{**asdict(sample), "iteration": index - warmups})
                            )
                        if media_url:
                            sample = await _async_http_sample(
                                client,
                                "video_range",
                                media_url,
                                timeout,
                                headers={"Range": f"bytes=0-{MAX_MEDIA_BYTES - 1}"},
                            )
                            if sample.ok and (
                                sample.status_code != 206 or sample.response_bytes > MAX_MEDIA_BYTES
                            ):
                                sample = Sample(
                                    **{
                                        **asdict(sample),
                                        "ok": False,
                                        "error": (
                                            f"expected 206 and <= {MAX_MEDIA_BYTES} bytes, "
                                            f"got {sample.status_code}/{sample.response_bytes}"
                                        ),
                                    }
                                )
                            if index >= warmups:
                                samples.append(
                                    Sample(**{**asdict(sample), "iteration": index - warmups})
                                )

        asyncio.run(measure())
        fixture = fixture_metadata(None)
        if hard_cache is not None:
            fixture = {
                "profile": "hard",
                "source_manifest_sha256": hashlib.sha256(FIXTURE_MANIFEST.read_bytes()).hexdigest(),
            }
        return _result(
            "controlled_http",
            fixture,
            samples,
            protocol={
                "warmups": warmups,
                "repeats": repeats,
                "timeout_seconds": timeout,
                "cache_reset": (
                    "fresh isolated app per invocation; in-app caches persist across samples"
                ),
                "media_max_bytes": MAX_MEDIA_BYTES,
            },
        )


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _seed_interrupted_job(root: Path) -> str:
    """Create a valid generated job fixture that startup recovery must interrupt."""
    from unittest.mock import patch
    from uuid import NAMESPACE_URL, uuid5

    import dokodetector_backend.job_store as job_store
    from dokodetector_backend.job_store import FakeParticipant, JobManager

    job_id = str(uuid5(NAMESPACE_URL, "doko-ui-perf-interrupted-job"))
    idempotency_key = str(uuid5(NAMESPACE_URL, "doko-ui-perf-interrupted-key"))
    operations = root / "data/operations"
    with (
        patch.object(job_store, "uuid4", return_value=uuid5(NAMESPACE_URL, job_id)),
        JobManager(operations, participant=FakeParticipant(root / "fake-runs")) as manager,
    ):
        job = manager.accept(
            idempotency_key,
            {
                "type": "fake",
                "context": {"recording_id": "perf-recovery"},
                "request": {"input": "seed-11401"},
            },
        )
        manager.transition(job.id, "running")
        return job.id


def _wait_http(url: str, timeout: float) -> tuple[int, bytes]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                url, timeout=max(0.1, deadline - time.monotonic())
            ) as response:
                return response.status, response.read(1024 * 1024)
        except urllib.error.HTTPError as error:
            if error.code == 503 and time.monotonic() < deadline:
                time.sleep(0.1)
                continue
            return error.code, error.read(1024 * 1024)
        except urllib.error.URLError as error:
            if not isinstance(error.reason, ConnectionRefusedError):
                raise
            last_error = error
            time.sleep(0.1)
        except TimeoutError as error:
            raise TimeoutError(f"timed out waiting for {url}: {error}") from error
    raise TimeoutError(f"timed out waiting for {url}: {last_error}")


def _terminate_group(process: subprocess.Popen[bytes], timeout: float = 30.0) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    if process.poll() is None:
        raise RuntimeError("backend process survived process-group cleanup")


def run_startup_profile(
    profile: str,
    root: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    command: list[str] | None = None,
    hard_cache: Path | None = None,
) -> dict[str, Any]:
    """Launch one isolated loopback backend and time readiness through useful responses."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    recording_id: str | None = None
    if profile == "hard_populated":
        if hard_cache is None:
            raise ValueError("hard_populated startup requires the verified --hard-cache")
        sys.path.insert(0, str(FIXTURE_SCRIPT.parent))
        import materialize_interactive_ui_performance_fixtures as fixtures

        fixtures.validate_hard_snapshot(hard_cache)
        source_manifest = json.loads(FIXTURE_MANIFEST.read_text())
        recording_id = next(
            item["recording_id"]
            for item in source_manifest["examples"]
            if item.get("kind") == "copy-lineage-fanout"
        )
        for asset in source_manifest["assets"]:
            if asset["path"].startswith("data/intake/recordings/") and (
                f"data/intake/recordings/{recording_id}/" not in asset["path"]
            ):
                continue
            source = hard_cache / "sha256" / asset["sha256"]
            target = root / asset["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, target)
    recovery_job_id = _seed_interrupted_job(root) if profile == "interrupted_recovery" else None
    port = _free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "REPOSITORY_ROOT": str(root),
            "EVIDENCE_ROOT": str(root / ".runtime"),
            "OPERATIONS_ROOT": str(root / "data/operations"),
            "REPOSITORY_INTAKE_ROOT": str(root / "data/intake/recordings"),
            "EVIDENCE_PACKAGE_INTAKE_ROOT": str(root / "data/intake/evidence-packages"),
            "PENDING_VIDEO_ROOT": str(root / "data/incoming/videos"),
            "SERVER_HOST": "127.0.0.1",
            "SERVER_PORT": str(port),
            "BONJOUR_ENABLED": "false",
            "BONJOUR_HOSTNAME": "localhost",
            "BONJOUR_ADDRESS": "127.0.0.1",
        }
    )
    launch = command or [sys.executable, "-m", "dokodetector_backend.server"]
    started = time.perf_counter_ns()
    output_path = root / "backend-output.log"
    with output_path.open("wb") as output:
        process = subprocess.Popen(
            launch,
            cwd=ROOT,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        samples: list[Sample] = []
        result: dict[str, Any]
        try:
            base = f"http://127.0.0.1:{port}"
            status, body = _wait_http(base + "/health/live", timeout)
            samples.append(
                _raw_sample("health_live", time.perf_counter_ns() - started, status, body)
            )
            if not 200 <= status < 300:
                raise RuntimeError(f"liveness probe returned HTTP {status}")
            ready_start = time.perf_counter_ns()
            status, body = _wait_http(base + "/health/ready", timeout)
            samples.append(
                _raw_sample("health_ready", time.perf_counter_ns() - ready_start, status, body)
            )
            if not 200 <= status < 300:
                raise RuntimeError(f"readiness probe returned HTTP {status}")
            useful_start = time.perf_counter_ns()
            status, body = _wait_http(base + "/v1/recordings", timeout)
            samples.append(
                _raw_sample(
                    "recordings_first_use", time.perf_counter_ns() - useful_start, status, body
                )
            )
            if status != 200:
                raise RuntimeError(f"recordings useful response returned HTTP {status}")
            if recording_id:
                workspace_start = time.perf_counter_ns()
                status, body = _wait_http(
                    base + f"/api/recordings/{recording_id}/pipeline", timeout
                )
                samples.append(
                    _raw_sample(
                        "workspace_first_use",
                        time.perf_counter_ns() - workspace_start,
                        status,
                        body,
                    )
                )
                if status != 200:
                    raise RuntimeError(f"workspace useful response returned HTTP {status}")
            if recovery_job_id:
                recovery_start = time.perf_counter_ns()
                status, body = _wait_http(base + f"/api/jobs/{recovery_job_id}", timeout)
                recovered = status == 200 and json.loads(body).get("state") == "interrupted"
                samples.append(
                    Sample(
                        "interrupted_job_recovery",
                        time.perf_counter_ns() - recovery_start,
                        status,
                        len(body),
                        hashlib.sha256(body).hexdigest(),
                        recovered,
                        None if recovered else "seeded running job was not recovered",
                    )
                )
                if not recovered:
                    raise RuntimeError(
                        "interrupted recovery profile did not recover the seeded running job"
                    )
            duration = time.perf_counter_ns() - started
            with httpx.Client(base_url=base, timeout=timeout) as client:
                samples.append(_http_sample(client, "jobs_json", "/api/jobs", timeout))
            result = _result(
                "loopback_startup",
                startup_fixture_metadata(profile),
                samples,
                protocol={
                    "timeout_seconds": timeout,
                    "startup_to_useful_ns": duration,
                    "probes": ["/health/live", "/health/ready", "/v1/recordings"],
                    "launch_command": launch,
                    "environment": "isolated temporary roots",
                    "process_group_cleanup_timeout_seconds": 30,
                },
                artifacts={"log": str(output_path)},
            )
        except Exception as error:
            samples.append(
                Sample(
                    "startup_failure",
                    time.perf_counter_ns() - started,
                    0,
                    0,
                    hashlib.sha256(b"").hexdigest(),
                    False,
                    str(error),
                )
            )
            result = _result(
                "loopback_startup",
                startup_fixture_metadata(profile),
                samples,
                protocol={"timeout_seconds": timeout, "launch_command": launch},
                artifacts={"log": str(output_path)},
            )
        finally:
            _terminate_group(process)
            for child in root.iterdir():
                if child == output_path:
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        result["protocol"]["process_exit_code"] = process.returncode
        result["protocol"]["process_cleanup"] = (
            "SIGTERM then SIGKILL; process group exited"
            if process.returncode == -signal.SIGKILL
            else "SIGTERM; process group exited"
        )
        return result


def _raw_sample(case: str, duration_ns: int, status: int, body: bytes) -> Sample:
    ok = 200 <= status < 300
    return Sample(
        case,
        duration_ns,
        status,
        len(body),
        hashlib.sha256(body).hexdigest(),
        ok,
        None if ok else f"HTTP {status}",
    )


def _result(
    kind: str,
    fixture: dict[str, Any],
    samples: list[Sample],
    *,
    protocol: dict[str, Any],
    artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "interactive-ui-performance-result/v1",
        "run_id": str(uuid.uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "kind": kind,
        "metadata": {"fixture": fixture, "machine": machine_metadata()},
        "protocol": protocol,
        "samples": [asdict(sample) for sample in samples],
        "artifacts": artifacts or {},
    }


def run_startup_trials(
    profile: str,
    root: Path,
    *,
    repeats: int = DEFAULT_REPEATS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    hard_cache: Path | None = None,
) -> dict[str, Any]:
    """Run fresh, isolated processes for each cold startup trial."""
    trial_root = root / uuid.uuid4().hex[:8]
    runs = [
        run_startup_profile(
            profile,
            trial_root / f"trial-{index:02d}",
            timeout=timeout,
            hard_cache=hard_cache,
        )
        for index in range(repeats)
    ]
    samples = []
    for index, run in enumerate(runs):
        samples.extend({**sample, "iteration": index} for sample in run["samples"])
    result = _result(
        "loopback_startup",
        runs[0]["metadata"]["fixture"],
        [Sample(**sample) for sample in samples],
        protocol={
            "repeats": repeats,
            "warmups": 0,
            "cache_reset": "fresh process and temporary roots for every cold trial",
            "timeout_seconds_per_trial": timeout,
            "process_runs": [run["protocol"] for run in runs],
        },
        artifacts={"trial_logs": [run["artifacts"]["log"] for run in runs]},
    )
    result["runs"] = [run["run_id"] for run in runs]
    return result


def export_result(result: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    csv_path = output.with_suffix(".csv")
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(Sample.__dataclass_fields__),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(result["samples"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["http", "startup"], default="http")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--hard-cache",
        type=Path,
        default=Path.home() / ".cache/doko-detector/interactive-performance",
    )
    parser.add_argument(
        "--profile", choices=["empty", "hard_populated", "interrupted_recovery"], default="empty"
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    if args.timeout <= 0 or args.repeats < 1 or args.warmups < 0:
        parser.error("timeout must be positive, repeats at least one, and warmups nonnegative")
    if args.mode == "http":
        result = run_controlled_http(
            repeats=args.repeats,
            warmups=args.warmups,
            timeout=args.timeout,
            hard_cache=args.hard_cache if args.profile == "hard_populated" else None,
        )
    else:
        artifact_root = args.output.with_suffix(".artifacts")
        artifact_root.mkdir(parents=True, exist_ok=True)
        result = run_startup_trials(
            args.profile,
            artifact_root / args.profile,
            repeats=args.repeats,
            timeout=args.timeout,
            hard_cache=args.hard_cache if args.profile == "hard_populated" else None,
        )
    export_result(result, args.output)
    if args.compare:
        errors = compare_results(json.loads(args.compare.read_text()), result)
        print(
            "Comparison: " + ("; ".join(errors) if errors else "compatible; no advisory regression")
        )
    print(f"Wrote raw samples to {args.output} and {args.output.with_suffix('.csv')}")
    return 0 if all(sample["ok"] for sample in result["samples"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
