from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_interactive_ui_performance import (  # noqa: E402
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
    result = run_controlled_http(repeats=1, warmups=0)
    sample = result["samples"][0]
    assert sample["case"] == "jobs_json"
    assert sample["ok"] is True
    assert sample["status_code"] == 200


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
