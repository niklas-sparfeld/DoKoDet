from __future__ import annotations

import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_interactive_ui_performance import (  # noqa: E402
    _loopback_sample,
    compare_results,
    run_controlled_http,
    run_startup_profile,
    run_startup_trials,
)


def _sample(duration: int = 100) -> dict[str, object]:
    return {
        "case": "json",
        "duration_ns": duration,
        "status_code": 200,
        "response_bytes": 2,
        "response_sha256": "a" * 64,
        "ok": True,
        "error": None,
    }


def _result(
    *,
    duration: int = 100,
    fixture: str = "same",
    machine: str = "same",
    sample: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "metadata": {"fixture": fixture, "machine": machine},
        "samples": [sample or _sample(duration)],
    }


def test_comparator_reports_slowdown_and_incompatible_profiles() -> None:
    errors = compare_results(
        _result(),
        _result(duration=121, fixture="different", machine="different"),
    )
    assert "incompatible fixture profile" in errors
    assert "incompatible machine profile" in errors
    assert any("slowdown" in error for error in errors)


def test_comparator_rejects_invalid_response() -> None:
    sample = _sample()
    sample["status_code"] = 503
    errors = compare_results(_result(), _result(sample=sample))
    assert any("invalid HTTP response" in error for error in errors)


def test_controlled_http_reads_real_json_endpoint() -> None:
    result = run_controlled_http(repeats=2, warmups=1, batches=2)
    sample = result["samples"][0]
    assert sample["case"] == "jobs_json"
    assert sample["ok"] is True
    assert sample["status_code"] == 200
    assert sum(not item["warmup"] for item in result["samples"]) == 4
    assert sum(item["warmup"] for item in result["samples"]) == 2
    assert [item["samples"] for item in result["distributions"]] == [2, 2]


def test_loopback_runner_reaches_useful_response_and_cleans_up(tmp_path: Path) -> None:
    result = run_startup_profile("empty", tmp_path / "isolated", timeout=20)
    assert [sample["case"] for sample in result["samples"]] == [
        "health_live",
        "health_ready",
        "recordings_first_use",
        "jobs_json",
    ]
    assert all(sample["ok"] for sample in result["samples"])
    assert result["protocol"]["startup_to_useful_ns"] > 0
    endpoint = next(sample for sample in result["samples"] if sample["case"] == "jobs_json")
    assert endpoint["response_bytes"] > 0
    assert endpoint["first_byte_ns"] > 0
    assert endpoint["completion_ns"] == endpoint["duration_ns"]


def test_loopback_runner_cleans_up_after_timeout(tmp_path: Path) -> None:
    result = run_startup_profile(
        "empty",
        tmp_path / "timeout",
        timeout=0.3,
        command=[sys.executable, "-c", "import time; time.sleep(60)"],
    )
    assert result["samples"][-1]["case"] == "startup_failure"
    assert result["samples"][-1]["ok"] is False
    assert result["protocol"]["process_cleanup"] == "SIGTERM; process group exited"
    assert result["protocol"]["process_exit_code"] < 0


def test_loopback_runner_recovers_interrupted_job(tmp_path: Path) -> None:
    result = run_startup_profile("interrupted_recovery", tmp_path / "recovery", timeout=20)
    assert all(sample["ok"] for sample in result["samples"])
    assert result["samples"][-1]["case"] == "jobs_json"
    assert any(sample["case"] == "interrupted_job_recovery" for sample in result["samples"])


def test_startup_trials_use_fresh_roots_on_repeated_invocation(tmp_path: Path) -> None:
    first = run_startup_trials("interrupted_recovery", tmp_path / "runs", repeats=1)
    second = run_startup_trials("interrupted_recovery", tmp_path / "runs", repeats=1)
    assert all(sample["ok"] for sample in first["samples"] + second["samples"])
    assert first["artifacts"]["trial_logs"] != second["artifacts"]["trial_logs"]
    assert any(
        item["case"] == "startup_to_useful_response" and item["samples"] == 1
        for item in first["distributions"]
    )


def test_loopback_sample_reads_full_body_and_times_first_byte() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(206)
            self.send_header("Content-Length", "6")
            self.end_headers()
            self.wfile.write(b"abc")
            self.wfile.flush()
            time.sleep(0.01)
            self.wfile.write(b"def")

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        sample = _loopback_sample(
            "media", f"http://127.0.0.1:{server.server_port}/video", timeout=2, max_bytes=10
        )
    finally:
        server.shutdown()
        worker.join()
        server.server_close()
    assert sample.ok is True
    assert sample.status_code == 206
    assert sample.response_bytes == 6
    assert sample.first_byte_ns is not None
    assert sample.completion_ns is not None
    assert sample.completion_ns > sample.first_byte_ns
