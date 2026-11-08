#!/usr/bin/env python3
"""Run bounded local HTTP and isolated backend startup measurements."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
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
DEFAULT_WARMUPS = 5
DEFAULT_REPEATS = 30
DEFAULT_BATCHES = 3
DEFAULT_STARTUP_PROCESSES = 10


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
    batch: int = 0
    warmup: bool = False
    first_byte_ns: int | None = None
    completion_ns: int | None = None


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
        if not sample.get("warmup", False):
            by_case.setdefault(str(sample["case"]), []).append(sample)
    for sample in next_samples:
        if not isinstance(sample, dict):
            errors.append("candidate contains malformed sample")
            continue
        invalid = validate_sample(sample)
        if invalid:
            errors.append(f"{sample.get('case', 'unknown')}: {invalid}")
            continue
        if sample.get("warmup", False):
            continue
        peers = by_case.get(str(sample["case"]), [])
        if peers:
            reference = sorted(item["duration_ns"] for item in peers)[len(peers) // 2]
            if sample["duration_ns"] > reference * 1.2:
                errors.append(f"{sample['case']}: slowdown exceeds 20% advisory tolerance")
    return errors


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
            completion_ns=time.perf_counter_ns() - start,
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
    batches: int = DEFAULT_BATCHES,
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
        samples: list[Sample] = []
        for batch in range(batches):
            settings = Settings(
                repository_root=fixture_root,
                evidence_root=sandbox / f"batch-{batch}" / ".runtime",
                operations_root=sandbox / f"batch-{batch}" / "data/operations",
                repository_intake_root=fixture_root / "data/intake/recordings",
                evidence_package_intake_root=fixture_root / "data/intake/evidence-packages",
                pending_video_root=fixture_root / "data/incoming/videos",
                bonjour_enabled=False,
            )
            app = create_app(settings)
            media_url = f"/v1/repository-bundles/{recording_id}/video" if recording_id else None

            async def measure_batch(
                batch_app: Any, batch_media_url: str | None, batch_index: int
            ) -> None:
                async with batch_app.router.lifespan_context(batch_app):
                    transport = httpx.ASGITransport(app=batch_app)
                    async with httpx.AsyncClient(
                        transport=transport,
                        base_url="http://controlled.local",
                        timeout=timeout,
                    ) as client:
                        cases = [("jobs_json", "/api/jobs", None)]
                        if batch_media_url:
                            cases.append(
                                (
                                    "video_range",
                                    batch_media_url,
                                    {"Range": f"bytes=0-{MAX_MEDIA_BYTES - 1}"},
                                )
                            )
                        for warmup in (True, False):
                            count = warmups if warmup else repeats
                            for iteration in range(count):
                                for case, url, headers in cases:
                                    sample = await _async_http_sample(
                                        client, case, url, timeout, headers=headers
                                    )
                                    if (
                                        sample.ok
                                        and case == "video_range"
                                        and (
                                            sample.status_code != 206
                                            or sample.response_bytes > MAX_MEDIA_BYTES
                                        )
                                    ):
                                        sample = Sample(
                                            **{
                                                **asdict(sample),
                                                "ok": False,
                                                "error": (
                                                    f"expected 206 and <= {MAX_MEDIA_BYTES} bytes, "
                                                    f"got {sample.status_code}/"
                                                    f"{sample.response_bytes}"
                                                ),
                                            }
                                        )
                                    samples.append(
                                        Sample(
                                            **{
                                                **asdict(sample),
                                                "iteration": iteration,
                                                "batch": batch_index,
                                                "warmup": warmup,
                                            }
                                        )
                                    )

            asyncio.run(measure_batch(app, media_url, batch))
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
                "batches": batches,
                "measured_requests_per_case": repeats * batches,
                "timeout_seconds": timeout,
                "cache_reset": (
                    "fresh isolated app and operations root per batch; app caches persist in batch"
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
    sys.path.insert(0, str(ROOT / "backend/tests"))
    from dokodetector_backend.job_store import JobManager
    from support.job_participants import FakeParticipant

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
    hard_cache_validated: bool = False,
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

        if not hard_cache_validated:
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
            samples.append(
                _loopback_sample(
                    "jobs_json", base + "/api/jobs", timeout=timeout, max_bytes=64 * 1024 * 1024
                )
            )
            if recording_id:
                media = _loopback_sample(
                    "video_range",
                    base + f"/v1/repository-bundles/{recording_id}/video",
                    timeout=timeout,
                    headers={"Range": f"bytes=0-{MAX_MEDIA_BYTES - 1}"},
                    max_bytes=MAX_MEDIA_BYTES,
                )
                if media.ok and media.status_code != 206:
                    media = Sample(**{**asdict(media), "ok": False, "error": "expected HTTP 206"})
                samples.append(media)
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


def _loopback_sample(
    case: str,
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    max_bytes: int,
) -> Sample:
    """Read the entire response and retain first-byte and completion timings."""
    started = time.perf_counter_ns()
    deadline = time.monotonic() + timeout
    digest = hashlib.sha256()
    response_bytes = 0
    first_byte_ns: int | None = None
    status = 0
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"response exceeded {timeout:.3f}s")
                read_size = 1 if first_byte_ns is None else min(
                    64 * 1024, max_bytes + 1 - response_bytes
                )
                chunk = response.read(read_size)
                if not chunk:
                    break
                if first_byte_ns is None:
                    first_byte_ns = time.perf_counter_ns() - started
                response_bytes += len(chunk)
                digest.update(chunk)
                if response_bytes > max_bytes:
                    return Sample(
                        case,
                        time.perf_counter_ns() - started,
                        status,
                        response_bytes,
                        digest.hexdigest(),
                        False,
                        f"response exceeded {max_bytes} bytes before completion",
                        first_byte_ns=first_byte_ns,
                    )
        completion = time.perf_counter_ns() - started
        ok = 200 <= status < 300
        return Sample(
            case,
            completion,
            status,
            response_bytes,
            digest.hexdigest(),
            ok,
            None if ok else f"HTTP {status}",
            first_byte_ns=first_byte_ns,
            completion_ns=completion,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        completion = time.perf_counter_ns() - started
        return Sample(
            case,
            completion,
            status,
            response_bytes,
            digest.hexdigest(),
            False,
            str(error),
            first_byte_ns=first_byte_ns,
            completion_ns=completion,
        )


def _result(
    kind: str,
    fixture: dict[str, Any],
    samples: list[Sample],
    *,
    protocol: dict[str, Any],
    artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_samples = [asdict(sample) for sample in samples]
    return {
        "schema_version": "interactive-ui-performance-result/v1",
        "run_id": str(uuid.uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "kind": kind,
        "metadata": {"fixture": fixture, "machine": machine_metadata()},
        "protocol": protocol,
        "samples": raw_samples,
        "distributions": _sample_distributions(raw_samples),
        "artifacts": artifacts or {},
    }


def _sample_distributions(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for sample in samples:
        if sample.get("warmup"):
            continue
        groups.setdefault((str(sample["case"]), int(sample.get("batch", 0))), []).append(sample)
    summaries = []
    for (case, batch), group in sorted(groups.items()):
        durations = sorted(int(item["duration_ns"]) for item in group)
        first_bytes = sorted(
            int(item["first_byte_ns"]) for item in group if item.get("first_byte_ns") is not None
        )
        summaries.append(_distribution(case, batch, durations, first_bytes))
    return summaries


def _distribution(
    case: str, batch: int, durations: list[int], first_bytes: list[int]
) -> dict[str, Any]:
    durations.sort()
    first_bytes.sort()
    return {
        "case": case,
        "batch": batch,
        "samples": len(durations),
        "min_completion_ns": durations[0],
        "median_completion_ns": int(statistics.median(durations)),
        "p90_completion_ns": durations[max(0, math.ceil(0.9 * len(durations)) - 1)],
        "max_completion_ns": durations[-1],
        "median_first_byte_ns": int(statistics.median(first_bytes)) if first_bytes else None,
        "p90_first_byte_ns": (
            first_bytes[max(0, math.ceil(0.9 * len(first_bytes)) - 1)] if first_bytes else None
        ),
    }


def run_startup_trials(
    profile: str,
    root: Path,
    *,
    repeats: int = DEFAULT_STARTUP_PROCESSES,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    hard_cache: Path | None = None,
) -> dict[str, Any]:
    """Run fresh, isolated processes for each cold startup trial."""
    trial_root = root / uuid.uuid4().hex[:8]
    if profile == "hard_populated":
        if hard_cache is None:
            raise ValueError("hard_populated startup requires the verified --hard-cache")
        sys.path.insert(0, str(FIXTURE_SCRIPT.parent))
        import materialize_interactive_ui_performance_fixtures as fixtures

        fixtures.validate_hard_snapshot(hard_cache)
    runs = [
        run_startup_profile(
            profile,
            trial_root / f"trial-{index:02d}",
            timeout=timeout,
            hard_cache=hard_cache,
            hard_cache_validated=profile == "hard_populated",
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
            "fresh_processes": repeats,
            "warmups": 0,
            "cache_reset": "fresh process and temporary roots for every cold trial",
            "timeout_seconds_per_trial": timeout,
            "process_runs": [run["protocol"] for run in runs],
        },
        artifacts={"trial_logs": [run["artifacts"]["log"] for run in runs]},
    )
    startup_durations = [
        int(run["protocol"]["startup_to_useful_ns"])
        for run in runs
        if "startup_to_useful_ns" in run["protocol"]
    ]
    if startup_durations:
        result["distributions"].append(
            _distribution("startup_to_useful_response", 0, startup_durations, [])
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
    summary_path = output.with_suffix(".summary.csv")
    summaries = result["distributions"]
    with summary_path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(summaries[0]) if summaries else [],
            lineterminator="\n",
        )
        if summaries:
            writer.writeheader()
            writer.writerows(summaries)


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
    parser.add_argument("--batches", type=int, default=DEFAULT_BATCHES)
    parser.add_argument("--startup-processes", type=int, default=DEFAULT_STARTUP_PROCESSES)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    if (
        args.timeout <= 0
        or args.repeats < 1
        or args.warmups < 0
        or args.batches < 1
        or args.startup_processes < 1
    ):
        parser.error("timeout, repeats, batches, and startup processes must be positive")
    if args.mode == "http":
        result = run_controlled_http(
            repeats=args.repeats,
            warmups=args.warmups,
            batches=args.batches,
            timeout=args.timeout,
            hard_cache=args.hard_cache if args.profile == "hard_populated" else None,
        )
    else:
        artifact_root = args.output.with_suffix(".artifacts")
        artifact_root.mkdir(parents=True, exist_ok=True)
        result = run_startup_trials(
            args.profile,
            artifact_root / args.profile,
            repeats=args.startup_processes,
            timeout=args.timeout,
            hard_cache=args.hard_cache if args.profile == "hard_populated" else None,
        )
    export_result(result, args.output)
    if args.compare:
        errors = compare_results(json.loads(args.compare.read_text()), result)
        print(
            "Comparison: " + ("; ".join(errors) if errors else "compatible; no advisory regression")
        )
    print(
        f"Wrote raw samples and distributions to {args.output}, "
        f"{args.output.with_suffix('.csv')}, and {args.output.with_suffix('.summary.csv')}"
    )
    return 0 if all(sample["ok"] for sample in result["samples"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
